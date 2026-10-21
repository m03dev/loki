// Cluster LOD — the sculpt as a hierarchy of meshlets (Nanite-style DAG).
//
// Built with meshoptimizer's clusterlod (MIT, vendored): the mesh is split
// into ~128-triangle clusters; clusters are grouped, each group simplified to
// half with its border locked (no cracks between neighbours), re-split into
// clusters, and so on up to a single root. Every LOD's triangles index the
// ORIGINAL vertex buffer, so when the brush moves vertices every level of the
// hierarchy follows immediately; only cluster bounds need refreshing
// (touch()). Groups whose shape changed a lot can be re-simplified later.
//
// Per frame, select() picks the cut through the DAG whose projected error is
// below a pixel threshold, and drops clusters outside the view frustum. The
// renderer then draws only those index ranges.
#pragma once
#include "sculpt/mesh.h"
#include <cstdint>
#include <vector>

namespace sculpt {

struct Plane {
    Vec3 n;
    float d = 0;  // inside when dot(n, p) + d >= 0
};

struct LodView {
    Vec3 eye;                 // object space
    float projScale = 1.0f;   // projection[1][1] (cot(fovy/2)); 0 = orthographic (uses orthoHeight)
    float orthoHeight = 0;    // world height of the view (orthographic)
    float viewportHeight = 1000;
    float znear = 0.01f;
    float pixelError = 1.0f;  // allowed screen-space error in pixels
    Plane planes[6];          // object-space frustum planes
    bool cull = true;
};

class ClusterLOD {
public:
    struct Cluster {
        uint32_t indexOffset = 0, indexCount = 0;  // into indices()
        int group = -1;       // the group this cluster is a member of
        int refined = -1;     // the group whose simplification produced it (-1: original geometry)
        Vec3 center;          // bounding sphere (refreshed by touch)
        float radius = 0;
    };
    struct Group {
        int depth = 0;
        Vec3 center;          // bounds of the group's simplified result (for error projection)
        float radius = 0;
        float error = 0;      // simplification error of the group (FLT_MAX: terminal)
    };

    // Full build from the current mesh (live triangles only). Seconds for
    // millions of triangles: run it off the main thread.
    void build(const Mesh& m, int maxTriangles = 128);
    bool empty() const { return clusters_.empty(); }

    void select(const LodView& v, std::vector<int>& out) const;
    // Brush moved these vertices: refresh bounds of every cluster using them,
    // and raise the error of every group overlapping the edit by how far the
    // vertices moved since the build (so the cut refines there right away;
    // a background rebuild later restores optimal simplification).
    void touch(const Mesh& m, const std::vector<int>& verts);

    // Display vertex order: spatially coherent (order of first use in the
    // original clusters), so a brush stroke dirties few contiguous GPU blocks.
    // displayIndices() = indices() remapped through toDisplay().
    const std::vector<uint32_t>& toDisplay() const { return toDisplay_; }    // mesh vertex -> display slot
    const std::vector<uint32_t>& fromDisplay() const { return fromDisplay_; }  // display slot -> mesh vertex
    const std::vector<uint32_t>& displayIndices() const { return displayIdx_; }

    const std::vector<Cluster>& clusters() const { return clusters_; }
    const std::vector<Group>& groups() const { return groups_; }
    const std::vector<uint32_t>& indices() const { return indices_; }
    size_t sourceTriangles() const { return sourceTris_; }
    int levels() const { return levels_; }
    double buildMs() const { return buildMs_; }

private:
    std::vector<Cluster> clusters_;
    std::vector<Group> groups_;
    std::vector<uint32_t> indices_;
    std::vector<uint32_t> vcOff_, vc_;   // vertex -> clusters (CSR, all levels)
    std::vector<char> clusterMark_;
    std::vector<uint32_t> gcOff_, gc_;   // group -> clusters it produced (refined == group)
    std::vector<uint32_t> toDisplay_, fromDisplay_, displayIdx_;
    std::vector<Vec3> basePos_;          // positions at build time (edit magnitude)
    void groupBounds(int g);
    size_t sourceTris_ = 0;
    int levels_ = 0;
    double buildMs_ = 0;
    void clusterBounds(const Mesh& m, int c);
    bool visible(const LodView& v, const Vec3& c, float r) const;
};

}  // namespace sculpt
