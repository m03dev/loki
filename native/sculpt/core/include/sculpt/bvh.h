// Triangle BVH. Built once per topology change. After a dab only a few
// triangles move, so refitTris() updates just their leaves and the path to the
// root (O(k log n)); refit() redoes every box (O(n)).
#pragma once
#include "sculpt/mesh.h"
#include <vector>

namespace sculpt {

struct Hit {
    bool hit = false;
    float t = 1e30f;
    int tri = -1;
    float u = 0, v = 0;  // barycentrics of vertices 1 and 2
    Vec3 point, normal;
};

class BVH {
public:
    void build(const Mesh& m);
    void refit(const Mesh& m);
    // Partial refit for the given triangles (may include appended ones).
    void refitTris(const Mesh& m, const std::vector<int>& tris);
    // Same, for a triangle set that repeats every dab (grab brushes): the dirty
    // node list (walk-up + sort) is computed once into nodeCache and reused.
    // `tris` must be unique.
    void refitTrisCached(const Mesh& m, const std::vector<int>& tris, std::vector<int>& nodeCache);
    bool empty() const { return nodes_.empty(); }

    Hit raycast(const Mesh& m, const Ray& r, bool backfaces = false, float maxT = 1e30f) const;

    // All vertex indices within `radius` of `c` (deduplicated, unsorted).
    void queryVerts(const Mesh& m, const Vec3& c, float radius, std::vector<int>& out) const;

    // All vertex indices within `radius` of the infinite line through `r`.
    // This is the "infinite depth" selection used by Move Infinite Depth.
    void queryVertsCylinder(const Mesh& m, const Ray& r, float radius, std::vector<int>& out) const;

    // All triangles whose bounds touch the sphere (dyntopo uses this).
    void queryTris(const Vec3& c, float radius, std::vector<int>& out) const;

    struct NodeT {
        AABB box;
        int left = -1, right = -1;  // children (internal)
        int first = 0, count = 0;   // leaf range in order_
    };

private:
    using Node = NodeT;
    std::vector<Node> nodes_;
    std::vector<int> order_;   // triangle indices
    std::vector<AABB> triBox_;
    size_t builtCount_ = 0;          // triangles covered by the tree
    std::vector<int> parent_;        // node -> parent (-1 for root)
    std::vector<int> triLeaf_;       // triangle -> leaf node (built triangles only)
    std::vector<int> dirtyNodes_;    // scratch
    std::vector<uint32_t> nodeStamp_;
    std::vector<int> nodePending_;   // scratch: dirty children not yet refit (all zero between uses)
    std::vector<int> orderScratch_;  // scratch: bottom-up refit order
    uint32_t nodeStampId_ = 0;
    // Triangles appended since the last build (dyntopo splits). Scanned
    // linearly; the tree is rebuilt once there are too many of them.
    size_t extrasBegin() const { return builtCount_; }
    mutable std::vector<uint32_t> stamp_;  // per-vertex dedupe stamps
    mutable uint32_t stampId_ = 0;

    int buildRec(int first, int count, std::vector<Vec3>& centroids);
    // Subtree for order_[first, first+count) into `out` (indices local to out,
    // root at 0); the top levels run their two halves on separate threads.
    void buildSub(int first, int count, std::vector<Vec3>& centroids, std::vector<Node>& out, int depth);
    AABB triBounds(const Mesh& m, int t) const;
    template <class BoxTest, class Emit>
    void traverse(BoxTest boxTest, Emit emit) const;
};

}  // namespace sculpt
