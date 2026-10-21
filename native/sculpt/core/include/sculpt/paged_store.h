// Sculpting engine v2 — out-of-core paged cluster store.
//
// The sculpt dataset no longer has to fit in RAM. The cluster DAG (from
// cluster_lod / meshoptimizer clusterlod) is serialised into fixed-size pages
// on disk, positions quantised per cluster and every buffer compressed with
// meshoptimizer's vertex/index codecs. A budgeted LRU keeps only the working
// set resident, so base pages are immutable and may be evicted and re-read at
// will. This is the foundation for 100M-1B triangle datasets.
//
// Directory (cluster bounds/offsets, ~48 B/cluster) stays in RAM; the heavy
// per-cluster geometry lives in the pages.
#pragma once
#include "sculpt/mesh.h"
#include "sculpt/cluster_lod.h"  // LodView, Plane
#include <cstdint>
#include <utility>
#include <fstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace sculpt {

struct StoredCluster {
    Vec3 center;              // bounding sphere (for LOD cut + culling, no load)
    float radius = 0;
    uint32_t page = 0;        // page holding this cluster's geometry
    uint32_t vertexCount = 0; // unique verts in this cluster
    uint32_t indexCount = 0;  // 3 * triangle count
    int group = -1;           // group whose simplification produced it
    int refined = -1;         // group this cluster refines (-1: original geometry)
    uint32_t pageByteOffset = 0;  // where its geometry starts inside the page payload
};

struct StoredGroup {
    int depth = 0;
    Vec3 center;
    float radius = 0;
    float error = 0;          // simplification error (FLT_MAX: terminal)
};

struct PageInfo { uint64_t offset = 0; uint32_t bytes = 0; uint32_t rawBytes = 0; };

class PagedStore {
public:
    struct ClusterMesh {  // decoded geometry of one cluster (local vertex space)
        std::vector<Vec3> positions;
        std::vector<Vec3> normals;
        std::vector<uint32_t> globalIds;  // original mesh vertex of each local vertex
        std::vector<uint32_t> indices;    // index into positions
    };

    ~PagedStore();
    // Build a store from a mesh: cluster DAG -> pages on disk. Returns false on
    // IO failure. `maxTriangles` is the cluster size (meshoptimizer clusterlod).
    bool build(const Mesh& m, const std::string& path, int maxTriangles = 128);
    // Open directory + page table only; geometry stays on disk until decodePage.
    bool open(const std::string& path);

    size_t clusterCount() const { return clusters_.size(); }
    size_t pageCount() const { return pages_.size(); }
    int levels() const { return levels_; }
    size_t sourceTriangles() const { return sourceTris_; }
    uint64_t diskBytes() const { return diskBytes_; }
    uint64_t rawBytes() const { return rawBytes_; }  // uncompressed float equivalent
    const std::vector<StoredCluster>& clusters() const { return clusters_; }
    const std::vector<StoredGroup>& groups() const { return groups_; }
    const std::vector<PageInfo>& pages() const { return pages_; }

    // Per-frame LOD cut over the STORED DAG (no rebuild, no page load): pick the
    // clusters whose simplifying group projects below the pixel threshold and
    // that pass the frustum. `out` is a list of cluster indices to draw.
    void select(const LodView& v, std::vector<uint32_t>& out) const;

    // A sculpt edit inside `spheres` (object-space centre, radius) moved vertices
    // by up to `delta`. Grow the bounds of the clusters it overlaps and raise the
    // error of the groups that contain it, so the next select() refines exactly
    // there — no rebuild, no page rewrite. This is the "no drag" edit path.
    void touch(const std::vector<std::pair<Vec3, float>>& spheres, float delta);

    // Decode every cluster of one page. Not cached: use ResidentSet to cache.
    // If `overlay` is given, its per-vertex offsets are applied on top of the
    // immutable base geometry (base pages are never rewritten by sculpting).
    bool decodePage(uint32_t page, std::vector<ClusterMesh>& out, const class EditOverlay* overlay = nullptr) const;

private:
    std::string path_;
    std::vector<StoredCluster> clusters_;
    std::vector<StoredGroup> groups_;
    std::vector<PageInfo> pages_;
    std::vector<uint32_t> pageFirstCluster_, pageClusterCount_;
    int levels_ = 0;
    size_t sourceTris_ = 0;
    uint64_t diskBytes_ = 0, rawBytes_ = 0;
    mutable std::ifstream file_;
    bool readAt(uint64_t off, size_t n, unsigned char* dst) const;
};

// Sparse per-vertex offsets on top of the immutable base pages. A brush stroke
// records offsets keyed by the original vertex id, so a 1B-triangle store is
// never rewritten; edits are tiny and undoing is dropping offsets. Applied when
// a page is decoded. Every LOD level indexes the same original vertices, so one
// offset moves the vertex in every level.
class EditOverlay {
public:
    void set(uint32_t vertex, const Vec3& delta) { delta_[vertex] = delta; }
    void add(uint32_t vertex, const Vec3& delta) { delta_[vertex] += delta; }
    Vec3 get(uint32_t vertex) const {
        auto it = delta_.find(vertex);
        return it == delta_.end() ? Vec3{} : it->second;
    }
    bool has(uint32_t vertex) const { return delta_.find(vertex) != delta_.end(); }
    void clear() { delta_.clear(); }
    size_t count() const { return delta_.size(); }
    // A rough resident cost of the sparse set.
    size_t bytes() const { return delta_.size() * 48; }

private:
    std::unordered_map<uint32_t, Vec3> delta_;
};

// Budgeted LRU over decoded pages: the resident working set. acquire() returns
// clusters decoded, evicting least-recently-used pages to stay under budget.
class ResidentSet {
public:
    ResidentSet(const PagedStore& store, size_t budgetBytes) : store_(store), budget_(budgetBytes) {}
    // Decoded clusters of `page`. Pointer valid until the next acquire(). The
    // page pinning: pass pin=true to skip eviction of this page this call.
    const std::vector<PagedStore::ClusterMesh>* acquire(uint32_t page);
    size_t residentBytes() const { return residentBytes_; }
    size_t peakBytes() const { return peakBytes_; }
    size_t pageCount() const { return resident_.size(); }
    uint64_t hits() const { return hits_; }
    uint64_t misses() const { return misses_; }
    uint64_t evictions() const { return evictions_; }
    uint64_t bytesRead() const { return bytesRead_; }
    void clear();

private:
    struct Entry { uint64_t stamp = 0; size_t bytes = 0; std::vector<PagedStore::ClusterMesh> data; };
    const PagedStore& store_;
    size_t budget_;
    uint64_t clock_ = 0;
    std::unordered_map<uint32_t, Entry> resident_;
    size_t residentBytes_ = 0, peakBytes_ = 0;
    uint64_t hits_ = 0, misses_ = 0, evictions_ = 0, bytesRead_ = 0;
    void evictOne();
};

}  // namespace sculpt
