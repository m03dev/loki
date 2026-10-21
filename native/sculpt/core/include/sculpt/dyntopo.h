// Sculpting engine — dynamic tessellation (dynamic detail / Dyntopo equivalent).
//
// Under the brush, edges longer than 4/3·L are split and edges shorter than
// 4/5·L are collapsed (Botsch & Kobbelt 2004 isotropic remeshing thresholds),
// where L is the detail size. With "relative" detail, L = radius · detail, so a
// small brush adds fine triangles and a big brush decimates — 's
// Tessimation behaviour. Topology edits are local and incremental: an edge map
// and the mesh adjacency are patched in place; dead elements are tombstoned
// and compacted once, at stroke end.
#pragma once
#include "sculpt/bvh.h"
#include "sculpt/mesh.h"
#include <cstdint>
#include <unordered_map>

namespace sculpt {

struct DynTopoSettings {
    bool enabled = false;
    bool relativeDetail = true;   // L = radius * detail  (else L = constantDetail)
    float detail = 0.12f;
    float constantDetail = 0.02f;
    bool allowCollapse = true;    // Tessimation: decimate where detail is coarser
    int maxOpsPerDab = 20000;     // interactivity budget
};

class DynTopo {
public:
    void attach(Mesh& m);   // builds the edge map
    // Remesh the region; returns true if topology changed.
    bool apply(Mesh& m, BVH& bvh, const Vec3& center, float radius, const DynTopoSettings& s);
    // Remove tombstoned faces/vertices. Invalidates all vertex indices.
    static void compact(Mesh& m);

    struct Stats { int splits = 0, collapses = 0, flips = 0; } stats;

private:
    struct EdgeRec { int f0 = -1, f1 = -1; };
    std::unordered_map<uint64_t, EdgeRec> edges_;
    static uint64_t key(int a, int b) {
        if (a > b) std::swap(a, b);
        return ((uint64_t)(uint32_t)a << 32) | (uint32_t)b;
    }
    void addFace(int e0, int e1, int f);
    void removeFace(int e0, int e1, int f);
    void replaceFace(int e0, int e1, int from, int to);
    bool split(Mesh& m, int a, int b);
    bool collapse(Mesh& m, int a, int b);
    bool flip(Mesh& m, int a, int b);   // edge a-b -> c-d (the two opposite vertices)
};

}  // namespace sculpt
