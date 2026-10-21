// Subdivision levels ("Divide" / SDiv): a stack of Catmull-Clark levels
// of one base mesh, so a sculpt can go to millions of polys and still be
// edited coarsely.
//
// Level k+1 = CC(level k) plus per-vertex *detail*: the offset from the
// subdivided lower level to the sculpted higher level, stored in the local
// frame (tangent, bitangent, normal) of the subdivided surface. So
//   up:   P[k+1] = S(P[k]) + Frame(S(P[k])) * D[k+1]
//   down: P[k][v] = P[k+1][v] for the vertex points (CC keeps original
//         indices first), then D[k+1] is re-derived so the round trip is exact.
// Edits at a low level therefore carry the high-frequency detail with them
// (it rotates with the surface), and edits at a high level show up as the
// smoothed shape on the levels below.
//
// Vertex order of a subdivided level: [original vertices | edge points |
// face points]; every face becomes quads (one per corner).
#pragma once
#include "sculpt/math.h"
#include <memory>
#include <vector>

namespace sculpt {

// One Catmull-Clark step for a fixed polygon topology. Topology analysis is
// done once (build); apply() then maps positions in parallel.
class CCSubdivider {
public:
    void build(const std::vector<int>& counts, const std::vector<int>& indices, int vertexCount);
    void apply(const std::vector<Vec3>& in, std::vector<Vec3>& out) const;

    int inVerts() const { return nv_; }
    int outVerts() const { return nv_ + (int)edges_.size() + (int)faceOff_.size() - 1; }
    const std::vector<int>& outCounts() const { return outCounts_; }
    const std::vector<int>& outIndices() const { return outIdx_; }

private:
    int nv_ = 0;
    std::vector<int> faceOff_;            // CSR of input faces (size F+1)
    std::vector<int> idx_;
    struct Edge { int a, b, f0, f1; };    // f1 = -1 on a boundary
    std::vector<Edge> edges_;
    std::vector<int> vfOff_, vf_;         // vertex -> incident faces
    std::vector<int> veOff_, ve_;         // vertex -> incident edges
    std::vector<int> outCounts_, outIdx_;
};

// Per-vertex normals and stable tangents of a polygon mesh (vertex -> corner
// adjacency built once per topology).
class PolyFrames {
public:
    void build(const std::vector<int>& counts, const std::vector<int>& indices, int vertexCount);
    // N: normalized vertex normals; T: unit tangent (first neighbour, projected).
    void compute(const std::vector<Vec3>& P, std::vector<Vec3>& N, std::vector<Vec3>& T) const;

private:
    int nv_ = 0;
    std::vector<int> off_;                // vertex -> corners (CSR)
    std::vector<int> prev_, next_;        // per corner entry: previous/next vertex in its face
};

struct MultiresLevel {
    std::vector<int> counts, indices;     // topology
    int vertexCount = 0;
    std::vector<Vec3> positions;          // last stored state of this level
    std::vector<Vec3> detail;             // (t, b, n) offsets vs S(level below); empty for level 0
    std::shared_ptr<CCSubdivider> up;     // this level -> next (built on demand)
    std::shared_ptr<PolyFrames> frames;   // frames of this level's topology (for its detail)
};

class Multires {
public:
    // Level 0 from the current mesh.
    void init(const std::vector<int>& counts, const std::vector<int>& indices, const std::vector<Vec3>& positions);
    bool empty() const { return levels_.empty(); }
    int levelCount() const { return (int)levels_.size(); }
    int current() const { return cur_; }
    const MultiresLevel& level(int k) const { return levels_[k]; }

    // `positions` is the sculpted state of the current level (must match its
    // vertex count). Each call stores it first.
    bool divide(const std::vector<Vec3>& positions);          // only from the top level: adds level top+1
    bool setLevel(int k, const std::vector<Vec3>& positions); // move to level k (up or down)
    void deleteHigher(const std::vector<Vec3>& positions);     // drop levels above the current one
    void deleteLower(const std::vector<Vec3>& positions);      // current level becomes the base (details baked)

    // Does a mesh with this topology size belong to the current level?
    bool matches(int vertexCount, int faceCount) const;
    size_t memoryBytes() const;

private:
    std::vector<MultiresLevel> levels_;
    int cur_ = 0;
    void storeCurrent(const std::vector<Vec3>& positions);
    void propagateDown(int from);         // level `from` changed: refresh lower levels + details
    void rebuildUp(int to);               // P[k+1] = S(P[k]) + frame * D for k < to
    CCSubdivider& sub(int k);
    PolyFrames& frames(int k);
    std::vector<bool> edited_;            // level positions changed since its details were derived
};

}  // namespace sculpt
