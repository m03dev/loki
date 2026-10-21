#include "sculpt/cluster_lod.h"
#include "sculpt/parallel.h"
#include "meshoptimizer.h"
#define CLUSTERLOD_IMPLEMENTATION
#include "clusterlod.h"
#include <algorithm>
#include <cfloat>
#include <chrono>
#include <cmath>

namespace sculpt {

void ClusterLOD::build(const Mesh& m, int maxTriangles) {
    auto t0 = std::chrono::steady_clock::now();
    clusters_.clear();
    groups_.clear();
    indices_.clear();
    std::vector<uint32_t> src;
    src.reserve(m.tris.size() * 3);
    for (const Tri& t : m.tris)
        if (t[0] >= 0) { src.push_back((uint32_t)t[0]); src.push_back((uint32_t)t[1]); src.push_back((uint32_t)t[2]); }
    sourceTris_ = src.size() / 3;
    if (src.empty() || m.positions.empty()) return;
    clodConfig cfg = clodDefaultConfig((size_t)maxTriangles);
    clodMesh cm{};
    cm.indices = src.data();
    cm.index_count = src.size();
    cm.vertex_count = m.positions.size();
    cm.vertex_positions = &m.positions[0].x;
    cm.vertex_positions_stride = sizeof(Vec3);
    // Shading-aware: normals as simplification attributes, so a fine sculpt
    // detail that is sub-pixel in height but visible in shading keeps its
    // triangles (pure geometric error would flatten it in the coarse levels).
    static const float kNormalWeights[3] = {0.5f, 0.5f, 0.5f};
    if (m.normals.size() == m.positions.size()) {
        cm.vertex_attributes = &m.normals[0].x;
        cm.vertex_attributes_stride = sizeof(Vec3);
        cm.attribute_weights = kNormalWeights;
        cm.attribute_count = 3;
    }
    indices_.reserve(src.size() * 2 + 1024);
    levels_ = 0;
    clodBuild(cfg, cm, [&](clodGroup g, const clodCluster* cl, size_t n) {
        int gid = (int)groups_.size();
        Group gr;
        gr.depth = g.depth;
        gr.center = {g.simplified.center[0], g.simplified.center[1], g.simplified.center[2]};
        gr.radius = g.simplified.radius;
        gr.error = g.simplified.error;
        groups_.push_back(gr);
        levels_ = std::max(levels_, g.depth + 1);
        for (size_t i = 0; i < n; ++i) {
            Cluster c;
            c.indexOffset = (uint32_t)indices_.size();
            c.indexCount = (uint32_t)cl[i].index_count;
            c.group = gid;
            c.refined = cl[i].refined;
            c.center = {cl[i].bounds.center[0], cl[i].bounds.center[1], cl[i].bounds.center[2]};
            c.radius = cl[i].bounds.radius;
            indices_.insert(indices_.end(), cl[i].indices, cl[i].indices + cl[i].index_count);
            clusters_.push_back(c);
        }
        return gid;
    });
    // vertex -> clusters (each cluster listed once per vertex), all levels
    const size_t nv = m.positions.size(), nc = clusters_.size();
    vcOff_.assign(nv + 1, 0);
    std::vector<uint32_t> stamp(nv, UINT32_MAX);
    for (size_t c = 0; c < nc; ++c)
        for (uint32_t k = 0; k < clusters_[c].indexCount; ++k) {
            uint32_t v = indices_[clusters_[c].indexOffset + k];
            if (stamp[v] != c) { stamp[v] = (uint32_t)c; ++vcOff_[v + 1]; }
        }
    for (size_t v = 0; v < nv; ++v) vcOff_[v + 1] += vcOff_[v];
    vc_.assign(vcOff_[nv], 0);
    {
        std::vector<uint32_t> fill(vcOff_.begin(), vcOff_.end() - 1);
        std::fill(stamp.begin(), stamp.end(), UINT32_MAX);
        for (size_t c = 0; c < nc; ++c)
            for (uint32_t k = 0; k < clusters_[c].indexCount; ++k) {
                uint32_t v = indices_[clusters_[c].indexOffset + k];
                if (stamp[v] != c) { stamp[v] = (uint32_t)c; vc_[fill[v]++] = (uint32_t)c; }
            }
    }
    // group -> the clusters its simplification produced
    gcOff_.assign(groups_.size() + 1, 0);
    for (const Cluster& c : clusters_) if (c.refined >= 0) ++gcOff_[c.refined + 1];
    for (size_t g = 0; g < groups_.size(); ++g) gcOff_[g + 1] += gcOff_[g];
    gc_.assign(gcOff_[groups_.size()], 0);
    {
        std::vector<uint32_t> fill(gcOff_.begin(), gcOff_.end() - 1);
        for (size_t c = 0; c < nc; ++c) if (clusters_[c].refined >= 0) gc_[fill[clusters_[c].refined]++] = (uint32_t)c;
    }
    clusterMark_.assign(nc, 0);
    // display order: first use in the original (level-0) clusters, which are
    // spatially coherent; vertices only used at coarser levels (none normally) last
    toDisplay_.assign(nv, UINT32_MAX);
    fromDisplay_.clear();
    fromDisplay_.reserve(nv);
    for (const Cluster& c : clusters_) {
        if (c.refined >= 0) continue;
        for (uint32_t k = 0; k < c.indexCount; ++k) {
            uint32_t v = indices_[c.indexOffset + k];
            if (toDisplay_[v] == UINT32_MAX) { toDisplay_[v] = (uint32_t)fromDisplay_.size(); fromDisplay_.push_back(v); }
        }
    }
    for (size_t v = 0; v < nv; ++v)
        if (toDisplay_[v] == UINT32_MAX) { toDisplay_[v] = (uint32_t)fromDisplay_.size(); fromDisplay_.push_back((uint32_t)v); }
    displayIdx_.resize(indices_.size());
    parallelFor((int)indices_.size(), [&](int i) { displayIdx_[i] = toDisplay_[indices_[i]]; }, 65536);
    basePos_ = m.positions;
    buildMs_ = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
}

bool ClusterLOD::visible(const LodView& v, const Vec3& c, float r) const {
    if (!v.cull) return true;
    for (const Plane& p : v.planes)
        if (dot(p.n, c) + p.d < -r) return false;
    return true;
}

void ClusterLOD::select(const LodView& v, std::vector<int>& out) const {
    out.clear();
    const float thr = v.pixelError;
    auto projected = [&](const Group& g) {
        if (g.error >= FLT_MAX * 0.5f) return FLT_MAX;
        if (v.projScale <= 0) return g.error / std::max(1e-12f, v.orthoHeight) * v.viewportHeight;
        float d = std::max(length(g.center - v.eye) - g.radius, v.znear);
        return g.error / d * (v.projScale * 0.5f) * v.viewportHeight;
    };
    // per-group projected error once, then the per-cluster DAG cut test
    std::vector<float> ge(groups_.size());
    parallelFor((int)groups_.size(), [&](int g) { ge[g] = projected(groups_[g]); }, 4096);
    const int nc = (int)clusters_.size();
    std::vector<char> pick(nc, 0);
    parallelFor(nc, [&](int i) {
        const Cluster& c = clusters_[i];
        if (ge[c.group] <= thr) return;                        // the coarser version is good enough
        if (c.refined >= 0 && ge[c.refined] > thr) return;     // a finer version is needed
        pick[i] = visible(v, c.center, c.radius);
    }, 8192);
    for (int i = 0; i < nc; ++i) if (pick[i]) out.push_back(i);
}

void ClusterLOD::clusterBounds(const Mesh& m, int ci) {
    Cluster& c = clusters_[ci];
    AABB b;
    for (uint32_t k = 0; k < c.indexCount; ++k) b.expand(m.positions[indices_[c.indexOffset + k]]);
    c.center = b.center();
    float r2 = 0;
    for (uint32_t k = 0; k < c.indexCount; ++k) r2 = std::max(r2, length2(m.positions[indices_[c.indexOffset + k]] - c.center));
    c.radius = std::sqrt(r2);
}

void ClusterLOD::groupBounds(int g) {
    uint32_t a = gcOff_[g], e = gcOff_[g + 1];
    if (a == e) return;  // terminal / root: keep
    AABB b;
    for (uint32_t i = a; i < e; ++i) {
        const Cluster& c = clusters_[gc_[i]];
        b.expand(c.center - Vec3{c.radius, c.radius, c.radius});
        b.expand(c.center + Vec3{c.radius, c.radius, c.radius});
    }
    Group& gr = groups_[g];
    gr.center = b.center();
    float r = 0;
    for (uint32_t i = a; i < e; ++i) {
        const Cluster& c = clusters_[gc_[i]];
        r = std::max(r, length(c.center - gr.center) + c.radius);
    }
    gr.radius = r;
}

void ClusterLOD::touch(const Mesh& m, const std::vector<int>& verts) {
    if (clusters_.empty() || vcOff_.size() != m.positions.size() + 1) return;
    std::vector<int> dirty;
    for (int v : verts) {
        if (v < 0 || (size_t)v + 1 >= vcOff_.size()) continue;
        for (uint32_t i = vcOff_[v]; i < vcOff_[v + 1]; ++i) {
            uint32_t c = vc_[i];
            if (!clusterMark_[c]) { clusterMark_[c] = 1; dirty.push_back((int)c); }
        }
    }
    parallelFor((int)dirty.size(), [&](int i) { clusterBounds(m, dirty[i]); }, 256);
    std::vector<int> groups;
    for (int c : dirty) {
        clusterMark_[c] = 0;
        if (clusters_[c].refined >= 0) groups.push_back(clusters_[c].refined);
    }
    std::sort(groups.begin(), groups.end());
    groups.erase(std::unique(groups.begin(), groups.end()), groups.end());
    for (int g : groups) groupBounds(g);

    // Edit magnitude: simplified levels were fitted to the build-time shape, so
    // any group overlapping the edited region may now be off by up to the
    // vertex displacement. Raise its error accordingly.
    if (basePos_.size() != m.positions.size()) return;
    float delta = 0;
    AABB box;
    for (int v : verts) {
        if (v < 0 || (size_t)v >= m.positions.size()) continue;
        delta = std::max(delta, length(m.positions[v] - basePos_[v]));
        box.expand(m.positions[v]);
        box.expand(basePos_[v]);
    }
    if (delta <= 0 || !box.valid()) return;
    // A group much smaller than the edit moves almost rigidly with it (its
    // vertices are the moved ones), so its shape error barely changes; a group
    // larger than the edit now contains a bump of height ~delta.
    const float extent = std::max(1e-12f, length(box.extent()));
    parallelFor((int)groups_.size(), [&](int g) {
        Group& gr = groups_[g];
        if (gr.error >= FLT_MAX * 0.5f) return;
        float e = delta * std::min(1.0f, 2.0f * gr.radius / extent);
        if (gr.error >= e) return;
        if (box.dist2(gr.center) <= gr.radius * gr.radius) gr.error = e;
    }, 4096);
}

}  // namespace sculpt
