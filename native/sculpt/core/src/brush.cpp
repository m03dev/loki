#include "sculpt/brush.h"
#include "sculpt/kelvinlet.h"
#include "sculpt/noise.h"
#include "sculpt/parallel.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <unordered_map>

namespace sculpt {

// ---------------------------------------------------------------- names

static const char* kNames[] = {
    "Standard", "DamStandard", "Inflate", "Blob", "Displace", "Magnify", "Pinch", "Layer", "SurfaceNoise", "Crease",
    "Clay", "ClayBuildup", "ClayStrips", "Flatten", "Fill", "Scrape", "Planar", "TrimDynamic", "TrimAdaptive",
    "Polish", "MultiplaneScrape", "Smooth", "SmoothRelax", "Move", "MoveElastic", "MoveInfiniteDepth", "MoveTopological",
    "SnakeHook", "Nudge", "Rotate", "ElasticTwist", "ElasticScale", "Pose", "Thumb",
    "Cloth", "Morph", "HistoryRecall", "Mask", "Paint"};
static_assert(sizeof(kNames) / sizeof(kNames[0]) == (size_t)Kernel::COUNT, "kernel name table out of sync");

const char* kernelName(Kernel k) { return kNames[(int)k]; }

bool kernelFromName(const std::string& s, Kernel& out) {
    for (int i = 0; i < (int)Kernel::COUNT; ++i)
        if (s == kNames[i]) { out = (Kernel)i; return true; }
    return false;
}

bool kernelIsGrab(Kernel k) {
    return k == Kernel::Move || k == Kernel::MoveElastic || k == Kernel::MoveInfiniteDepth ||
           k == Kernel::MoveTopological || k == Kernel::Rotate || k == Kernel::Cloth ||
           k == Kernel::ElasticTwist || k == Kernel::ElasticScale || k == Kernel::Pose;
}

// ---------------------------------------------------------------- falloff / alpha

float Falloff::eval(float x) const {
    x = clamp01(x);
    switch (preset) {
        case FalloffPreset::Smooth: return 3 * (1 - x) * (1 - x) - 2 * (1 - x) * (1 - x) * (1 - x);  // smoothstep(1-x)
        case FalloffPreset::Sphere: return std::sqrt(std::max(0.0f, 1 - x * x));
        case FalloffPreset::Root: return 1 - std::sqrt(x);
        case FalloffPreset::Sharp: return (1 - x) * (1 - x);
        case FalloffPreset::Linear: return 1 - x;
        case FalloffPreset::Constant: return 1.0f;
        case FalloffPreset::Custom: {
            if (points.empty()) return 1 - x;
            if (x <= points.front().first) return points.front().second;
            for (size_t i = 1; i < points.size(); ++i)
                if (x <= points[i].first) {
                    float t = (x - points[i - 1].first) / std::max(1e-6f, points[i].first - points[i - 1].first);
                    return points[i - 1].second + (points[i].second - points[i - 1].second) * t;
                }
            return points.back().second;
        }
    }
    return 1 - x;
}

float Alpha::sample(float u, float v) const {
    if (!valid()) return 1.0f;
    float fx = (u * 0.5f + 0.5f) * (width - 1), fy = (v * 0.5f + 0.5f) * (height - 1);
    if (fx < 0 || fy < 0 || fx > width - 1 || fy > height - 1) return 0.0f;
    int x0 = (int)fx, y0 = (int)fy;
    int x1 = std::min(x0 + 1, width - 1), y1 = std::min(y0 + 1, height - 1);
    float tx = fx - x0, ty = fy - y0;
    float a = data[y0 * width + x0] * (1 - tx) + data[y0 * width + x1] * tx;
    float b = data[y1 * width + x0] * (1 - tx) + data[y1 * width + x1] * tx;
    return (a * (1 - ty) + b * ty) - midValue;
}

// ---------------------------------------------------------------- engine

BrushEngine::BrushEngine(Mesh& mesh) : mesh_(mesh) {
    mesh_.ensureAttributes();
    if (mesh_.vertTris.size() != mesh_.positions.size()) mesh_.buildAdjacency();
    rebuildSpatial();
}

void BrushEngine::rebuildSpatial() {
    bvh_.build(mesh_);
    dirtyVerts_.clear();
    dirtyMark_.assign(mesh_.positions.size(), 0);
    // topology changed: per-vertex stroke buffers no longer line up
    fullResync_ = true;
    pendingRefit_.clear();
    for (Instance& in : inst_) { in.ringCache.clear(); in.trisCache.clear(); in.nodeCache.clear(); }
    changed_.clear();
    changedMark_.assign(mesh_.positions.size(), 0);
}
void BrushEngine::takeHostDirty(std::vector<int>& out) {
    out.swap(hostDirty_);
    hostDirty_.clear();
    for (int v : out) if (v < (int)hostMark_.size()) hostMark_[v] = 0;
}

void BrushEngine::refitSpatial() {
    for (Instance* in : pendingRefit_) bvh_.refitTrisCached(mesh_, in->trisCache, in->nodeCache);
    pendingRefit_.clear();
    if (dirtyVerts_.empty()) return;
    if (dirtyVerts_.size() * 4 > mesh_.positions.size() || mesh_.vertTris.size() != mesh_.positions.size()) {
        bvh_.refit(mesh_);
    } else {
        // duplicates are harmless (refitTris dedupes nodes by stamp); skipping
        // the sort keeps this well under a millisecond
        // unique triangles (each one appears once per moved corner otherwise)
        if (triMark_.size() < mesh_.tris.size()) triMark_.resize(mesh_.tris.size(), 0);
        dirtyTris_.clear();
        for (int v : dirtyVerts_)
            for (int t : mesh_.vertTris[v])
                if (!triMark_[t]) { triMark_[t] = 1; dirtyTris_.push_back(t); }
        for (int t : dirtyTris_) triMark_[t] = 0;
        bvh_.refitTris(mesh_, dirtyTris_);
    }
    for (int v : dirtyVerts_) if (v < (int)dirtyMark_.size()) dirtyMark_[v] = 0;
    dirtyVerts_.clear();
}

static void tangentFrame(const Vec3& n, const Vec3& hint, Vec3& t, Vec3& b) {
    t = normalize(projectOnPlane(hint, n));
    if (length2(t) < 1e-8f) t = normalize(projectOnPlane(std::fabs(n.x) < 0.9f ? Vec3{1, 0, 0} : Vec3{0, 1, 0}, n));
    b = cross(n, t);
}

void BrushEngine::beginStroke(const Brush& b, const Dab& d) {
    size_t n = mesh_.positions.size();
    // Per-vertex stroke buffers persist across strokes: only what changed since
    // the last stroke is re-synced (a full copy + clear was ~41 bytes x verts
    // per stroke: ~100 ms at 2.6M verts).
    if (fullResync_ || origPos_.size() != n || origNrm_.size() != mesh_.normals.size()) {
        origPos_ = mesh_.positions;
        origNrm_ = mesh_.normals;
        layerDisp_.assign(n, 0.0f);
        touched_.assign(n, 0);
        disp_.assign(n, Vec3{});
        fullResync_ = false;
    } else {
        for (int v : changed_) {
            origPos_[v] = mesh_.positions[v];
            if ((size_t)v < origNrm_.size()) origNrm_[v] = mesh_.normals[v];
            disp_[v] = Vec3{};
        }
        for (int v : touchedList_) { touched_[v] = 0; layerDisp_[v] = 0.0f; disp_[v] = Vec3{}; }
    }
    for (int v : changed_) changedMark_[v] = 0;
    changed_.clear();
    touchedList_.clear();
    for (int v : hostDirty_) if (v < (int)hostMark_.size()) hostMark_[v] = 0;
    hostDirty_.clear();

    pendingRefit_.clear();
    inst_.clear();
    // Symmetry: every subset of enabled axes is one mirror instance (1, 2, 4 or 8).
    // Radial: each of those is repeated `radial` times around the object-space axis.
    const int rad = b.radial > 1 ? b.radial : 1;
    const Vec3 raxis = b.radialAxis == 0 ? Vec3{1, 0, 0} : (b.radialAxis == 2 ? Vec3{0, 0, 1} : Vec3{0, 1, 0});
    const float kTau = 6.283185307179586f;
    for (int mask = 0; mask < 8; ++mask) {
        if ((mask & ~b.symmetry) != 0) continue;
        for (int k = 0; k < rad; ++k) {
            Instance in;
            in.mirror = {(mask & 1) ? -1.f : 1.f, (mask & 2) ? -1.f : 1.f, (mask & 4) ? -1.f : 1.f};
            in.axis = raxis;
            in.ang = rad > 1 ? kTau * (float)k / (float)rad : 0.0f;
            inst_.push_back(in);
        }
    }

    for (Instance& in : inst_) {
        const Vec3 m = in.mirror, ax = in.axis;
        const float ang = in.ang;
        auto M = [&](const Vec3& v) { Vec3 d{v.x * m.x, v.y * m.y, v.z * m.z}; return ang != 0.0f ? rotate(d, ax, ang) : d; };
        in.startPos = M(d.position);
        in.startNormal = normalize(M(d.normal));
        in.grabVerts.clear();
        in.grabWeights.clear();

        // Stroke-start plane (Planar / TrimAdaptive)
        bvh_.queryVerts(mesh_, in.startPos, b.radius, verts_);
        weights_.assign(verts_.size(), 1.0f);
        areaPlane(verts_, weights_, in.planeCenter, in.planeNormal);
        if (length2(in.planeNormal) < 1e-8f) { in.planeNormal = in.startNormal; in.planeCenter = in.startPos; }

        if (!kernelIsGrab(b.kernel)) continue;

        if (b.kernel == Kernel::MoveInfiniteDepth) {
            Ray r{M(d.ray.origin), normalize(M(d.ray.dir))};
            bvh_.queryVertsCylinder(mesh_, r, b.radius, in.grabVerts);
            for (int v : in.grabVerts) {
                Vec3 q = mesh_.positions[v] - r.origin;
                float dist = length(q - r.dir * dot(q, r.dir));
                in.grabWeights.push_back(b.falloff.eval(dist / b.radius) * (1 - mesh_.mask[v]));
            }
        } else if (b.kernel == Kernel::MoveTopological) {
            // BFS over mesh edges from the closest vertex, limited to the sphere:
            // only geometry *connected* to the hit moves (fingers, lips, eyelids).
            bvh_.queryVerts(mesh_, in.startPos, b.radius, verts_);
            if (verts_.empty()) continue;
            int seed = verts_[0];
            float best = 1e30f;
            for (int v : verts_) {
                float dd = length2(mesh_.positions[v] - in.startPos);
                if (dd < best) { best = dd; seed = v; }
            }
            std::vector<char> seen(n, 0);
            std::deque<int> q{seed};
            seen[seed] = 1;
            float r2 = b.radius * b.radius;
            while (!q.empty()) {
                int v = q.front();
                q.pop_front();
                float dist = length(mesh_.positions[v] - in.startPos);
                in.grabVerts.push_back(v);
                in.grabWeights.push_back(b.falloff.eval(dist / b.radius) * (1 - mesh_.mask[v]));
                for (int nb : mesh_.vertNbrs[v])
                    if (!seen[nb] && length2(mesh_.positions[nb] - in.startPos) <= r2) {
                        seen[nb] = 1;
                        q.push_back(nb);
                    }
            }
        } else if (b.kernel == Kernel::Pose) {
            // Pose (like Pose brush): the joint (pivot) is the
            // centroid of the cross-section where the brush sphere cuts the
            // surface (vertices in its outer 15% shell). The segment is every
            // vertex *connected* to the grabbed one on the far side of the
            // joint plane (flood fill over edges, up to 4 radii): it rotates
            // rigidly about the pivot, blending over +-0.25 r across the joint.
            bvh_.queryVerts(mesh_, in.startPos, b.radius, verts_);
            if (verts_.empty()) continue;
            int seed = verts_[0];
            float best = 1e30f;
            std::vector<char> shell(n, 0);
            for (int v : verts_) {
                float dd = length(mesh_.positions[v] - in.startPos);
                if (dd > 0.85f * b.radius) shell[v] = 1;
                if (dd < best) { best = dd; seed = v; }
            }
            // The sphere can cut a limb twice (toward the tip and toward the
            // body): split the cut into connected rings and take the one
            // nearest the model's centre - the joint where the part attaches.
            Vec3 centre{};
            for (const Vec3& p : mesh_.positions) centre += p;
            centre = centre / (float)std::max<size_t>(1, n);
            in.pivot = in.startPos - in.startNormal * b.radius;
            float bestD = 1e30f;
            std::vector<int> stack;
            for (int v0 : verts_) {
                if (shell[v0] != 1) continue;
                Vec3 c{};
                int cnt = 0;
                stack.assign(1, v0);
                shell[v0] = 2;
                while (!stack.empty()) {
                    int v = stack.back();
                    stack.pop_back();
                    c += mesh_.positions[v];
                    ++cnt;
                    for (int nb : mesh_.vertNbrs[v]) if (shell[nb] == 1) { shell[nb] = 2; stack.push_back(nb); }
                }
                if (cnt < 6) continue;
                c = c / (float)cnt;
                float dc = length2(c - centre);
                if (dc < bestD) { bestD = dc; in.pivot = c; }
            }
            Vec3 axis = in.startPos - in.pivot;
            float al = length(axis);
            axis = al > 1e-9f ? axis / al : in.startNormal;
            const float blend = 0.25f * b.radius, reach2 = 16.0f * b.radius * b.radius;
            std::vector<char> seen(n, 0);
            std::deque<int> q{seed};
            seen[seed] = 1;
            while (!q.empty()) {
                int v = q.front();
                q.pop_front();
                float h = dot(mesh_.positions[v] - in.pivot, axis);
                float t = clamp01((h + blend) / (2 * blend));
                in.grabVerts.push_back(v);
                in.grabWeights.push_back(t * t * (3 - 2 * t) * (1 - mesh_.mask[v]));
                for (int nb : mesh_.vertNbrs[v]) {
                    if (seen[nb]) continue;
                    seen[nb] = 1;
                    const Vec3& p = mesh_.positions[nb];
                    if (dot(p - in.pivot, axis) > -blend && length2(p - in.startPos) < reach2) q.push_back(nb);
                }
            }
        } else {
            bool elastic = b.kernel == Kernel::MoveElastic || b.kernel == Kernel::ElasticTwist ||
                           b.kernel == Kernel::ElasticScale;
            float support = elastic ? b.radius * 3.0f : b.kernel == Kernel::Cloth ? b.radius * 1.5f : b.radius;
            bvh_.queryVerts(mesh_, in.startPos, support, in.grabVerts);
            for (int v : in.grabVerts) {
                float dist = length(mesh_.positions[v] - in.startPos);
                in.grabWeights.push_back((elastic ? 1.0f : b.falloff.eval(dist / b.radius)) * (1 - mesh_.mask[v]));
            }
        }
        markTouched(in.grabVerts);
    }
}

void BrushEngine::markTouched(const std::vector<int>& vs) {
    if (touched_.size() < mesh_.positions.size()) {
        // dyntopo added vertices mid-stroke: new verts start at their current state
        size_t old = touched_.size();
        touched_.resize(mesh_.positions.size(), 0);
        origPos_.resize(mesh_.positions.size());
        origNrm_.resize(mesh_.positions.size());
        layerDisp_.resize(mesh_.positions.size(), 0.0f);
        disp_.resize(mesh_.positions.size());
        for (size_t i = old; i < mesh_.positions.size(); ++i) {
            origPos_[i] = mesh_.positions[i];
            origNrm_[i] = mesh_.normals[i];
        }
    }
    for (int v : vs)
        if (!touched_[v]) { touched_[v] = 1; touchedList_.push_back(v); }
}

void BrushEngine::areaPlane(const std::vector<int>& vs, const std::vector<float>& w, Vec3& c, Vec3& n) const {
    Vec3 sc{}, sn{};
    float sw = 0;
    for (size_t i = 0; i < vs.size(); ++i) {
        sc += mesh_.positions[vs[i]] * w[i];
        sn += mesh_.normals[vs[i]] * w[i];
        sw += w[i];
    }
    c = sw > 0 ? sc / sw : Vec3{};
    n = normalize(sn);
}

float BrushEngine::vertexWeight(const Brush& b, const Dab& d, const Vec3& center, const Vec3& normal,
                                const Vec3& tangent, int v, float pressure) const {
    const Vec3& p = mesh_.positions[v];
    float facing = -dot(mesh_.normals[v], d.viewDir);   // 1 = faces the camera
    if (b.frontFacesOnly && facing <= 0.0f) return 0.0f;
    // Fade out toward the silhouette: at grazing angles a dab's displacement is
    // nearly tangential to the view and folds the surface over itself.
    float graze = b.frontFacesOnly ? clamp01(facing / 0.3f) : 1.0f;
    Vec3 q = p - center;
    float x, u = 0.0f, w = 0.0f;
    if (b.squareTip || b.alpha) {   // tip coordinates: only square tips and alphas need them
        Vec3 bt = cross(normal, tangent);
        u = dot(q, tangent) / b.radius;
        w = dot(q, bt) / b.radius;
    }
    if (b.squareTip) {
        // Blend between a square (Chebyshev) and round (Euclidean) footprint.
        float sq = std::max(std::fabs(u), std::fabs(w));
        float rd = std::sqrt(u * u + w * w);
        x = sq + (rd - sq) * b.tipRoundness;
        if (x > 1) return 0.0f;
    } else {
        float d2 = length2(q);
        if (d2 > b.radius * b.radius) return 0.0f;
        x = std::sqrt(d2) / b.radius;
    }
    float f = b.falloff.eval(x);
    if (b.alpha) f *= b.alpha->sample(u, w);
    f *= (1.0f - mesh_.mask[v]) * graze * graze * (3.0f - 2.0f * graze);  // smoothstep fade
    return f * (b.usePressure ? pressure : 1.0f);
}

void BrushEngine::applyDab(const Brush& b, const Dab& d) {
    if (length2(d.dabDelta) > 1e-12f) lastStrokeDir_ = normalize(d.dabDelta);
    for (Instance& in : inst_) dabInstance(b, d, in);
    refitSpatial();  // partial: only boxes of moved triangles (keeps raycasts exact)
}

void BrushEngine::applyDisplacements(const std::vector<int>& vs, Instance* fixed) {
    if (dirtyMark_.size() < mesh_.positions.size()) dirtyMark_.resize(mesh_.positions.size(), 0);
    parallelFor((int)vs.size(), [&](int i) {
        int v = vs[i];
        mesh_.positions[v] += disp_[v];
        disp_[v] = Vec3{};
    }, 8192);
    if (hostMark_.size() < mesh_.positions.size()) hostMark_.resize(mesh_.positions.size(), 0);
    if (changedMark_.size() < mesh_.positions.size()) changedMark_.resize(mesh_.positions.size(), 0);

    // Normals of the ring around the region change too.
    static thread_local std::vector<int> ringScratch;
    static thread_local std::vector<char> inRing;
    std::vector<int>* ringPtr = &ringScratch;
    bool build = true;
    if (fixed) {
        ringPtr = &fixed->ringCache;
        build = fixed->ringCache.empty();
    }
    std::vector<int>& ring = *ringPtr;
    if (build) {
        ring.clear();
        if (inRing.size() != mesh_.positions.size()) inRing.assign(mesh_.positions.size(), 0);
        for (int v : vs) {
            if (!inRing[v]) { inRing[v] = 1; ring.push_back(v); }
            for (int nb : mesh_.vertNbrs[v])
                if (!inRing[nb]) { inRing[nb] = 1; ring.push_back(nb); }
        }
        for (int v : ring) inRing[v] = 0;  // keep the scratch all-zero: no O(mesh) clear per dab
        if (fixed) {
            // unique triangles of the moved set, for the cached refit
            if (triMark_.size() < mesh_.tris.size()) triMark_.resize(mesh_.tris.size(), 0);
            fixed->trisCache.clear();
            for (int v : vs)
                for (int t : mesh_.vertTris[v])
                    if (!triMark_[t]) { triMark_[t] = 1; fixed->trisCache.push_back(t); }
            for (int t : fixed->trisCache) triMark_[t] = 0;
            fixed->nodeCache.clear();
        }
    }
    // per-vertex normals are independent: parallel (through a reference: the
    // scratch is thread_local, workers must use the caller's copy)
    const std::vector<int>& R = ring;
    recomputeRingNormals(R);
    // host display + next-stroke resync need every vertex whose position or normal changed
    for (int v : R) {
        if (!hostMark_[v]) { hostMark_[v] = 1; hostDirty_.push_back(v); }
        if (!changedMark_[v]) { changedMark_[v] = 1; changed_.push_back(v); }
    }
    if (fixed) {
        if (std::find(pendingRefit_.begin(), pendingRefit_.end(), fixed) == pendingRefit_.end())
            pendingRefit_.push_back(fixed);
    } else {
        for (int v : vs)
            if (!dirtyMark_[v]) { dirtyMark_[v] = 1; dirtyVerts_.push_back(v); }
    }
}

// Vertex normals of the ring (area-weighted: the sum of the unnormalized face
// normals around each vertex). Measured (callgrind, 262k verts, r = 0.6): a
// variant that computed each shared face normal once into a compact scratch
// cost 5% more than this per-corner sum (the slot lookups outweigh the saved
// cross products: the neighbours' positions are already in cache), so the
// per-corner sum stays; nrmSlot_/nrmTris_/nrmFace_ are kept for that variant
// (build with -DSCULPT_FACE_NORMAL_CACHE) should a SIMD build tip the balance.
void BrushEngine::recomputeRingNormals(const std::vector<int>& R) {
#ifdef SCULPT_FACE_NORMAL_CACHE
    const size_t nt = mesh_.tris.size();
    if (nrmSlot_.size() < nt) nrmSlot_.resize(nt, -1);
    nrmTris_.clear();
    for (int v : R)
        for (int t : mesh_.vertTris[v])
            if (nrmSlot_[t] < 0) { nrmSlot_[t] = (int)nrmTris_.size(); nrmTris_.push_back(t); }
    nrmFace_.resize(nrmTris_.size());
    parallelFor((int)nrmTris_.size(), [&](int i) { nrmFace_[i] = mesh_.triNormal(nrmTris_[i]); }, 4096);
    parallelFor((int)R.size(), [&](int i) {
        int v = R[i];
        Vec3 nn{0, 0, 0};
        for (int t : mesh_.vertTris[v]) nn += nrmFace_[nrmSlot_[t]];
        mesh_.normals[v] = normalize(nn);
    }, 2048);
    for (int t : nrmTris_) nrmSlot_[t] = -1;  // keep the scratch all -1: no O(mesh) reset per dab
#else
    parallelFor((int)R.size(), [&](int i) {
        int v = R[i];
        Vec3 nn{0, 0, 0};
        for (int t : mesh_.vertTris[v]) nn += mesh_.triNormal(t);
        mesh_.normals[v] = normalize(nn);
    }, 2048);
#endif
}

void BrushEngine::setPositions(const std::vector<int>& verts, const std::vector<Vec3>& pos) {
    size_t n = mesh_.positions.size();
    if (disp_.size() < n) disp_.resize(n, Vec3{});
    std::vector<int> vs;
    vs.reserve(verts.size());
    for (size_t i = 0; i < verts.size() && i < pos.size(); ++i) {
        int v = verts[i];
        if (v < 0 || (size_t)v >= n) continue;
        disp_[v] = pos[i] - mesh_.positions[v];
        vs.push_back(v);
    }
    applyDisplacements(vs);
    refitSpatial();
}

static Vec3 laplacian(const Mesh& m, int v) {
    const auto& nb = m.vertNbrs[v];
    if (nb.empty()) return Vec3{};
    Vec3 avg{};
    for (int j : nb) avg += m.positions[j];
    return avg / (float)nb.size() - m.positions[v];
}

void BrushEngine::smoothVerts(const std::vector<int>& vs, float strength, int iterations, bool tangentialOnly) {
    if (disp_.size() < mesh_.positions.size()) disp_.resize(mesh_.positions.size());
    for (int it = 0; it < iterations; ++it) {
        parallelFor((int)vs.size(), [&](int i) {
            int v = vs[i];
            Vec3 L = laplacian(mesh_, v);
            if (tangentialOnly) L = projectOnPlane(L, mesh_.normals[v]);
            disp_[v] = L * (strength * (1 - mesh_.mask[v]));
        });
        applyDisplacements(vs);
    }
}

// Smoothing step of each vertex, weighted. The HC part (Vollmer, Mencl &
// Mueller, "Improved Laplacian Smoothing of Noisy Surface Meshes", 1999) with
// alpha = 0: b_i = L_i (the umbrella Laplacian), p_i' = q_i + L_i - (beta b_i +
// (1 - beta) mean_j b_j) = q_i + (1 - beta)(L_i - mean_j L_j). Where the
// Laplacian is constant (a sphere, a cylinder, a flat plane) the step is zero,
// so smoothing removes bumps and noise without shrinking the form.
void BrushEngine::smoothRegion(const std::vector<int>& vs, const std::vector<float>& w, float strength,
                               int iterations, float volume, bool tangentialOnly) {
    const size_t n = mesh_.positions.size();
    if (disp_.size() < n) disp_.resize(n);
    if (smSlot_.size() < n) smSlot_.resize(n, -1);
    volume = clamp01(volume);
    const int nv = (int)std::min(vs.size(), w.size());
    if (nv == 0) return;
    const float beta = 0.5f;
    for (int it = 0; it < std::max(1, iterations); ++it) {
        if (volume <= 0.0f || tangentialOnly) {
            parallelFor(nv, [&](int i) {
                int v = vs[i];
                Vec3 L = laplacian(mesh_, v);
                if (tangentialOnly) L = projectOnPlane(L, mesh_.normals[v]);
                disp_[v] = L * std::min(1.0f, strength * w[i]);
            });
        } else {
            // the region and its one ring (the HC step reads the neighbours' Laplacians)
            smRing_.clear();
            for (int i = 0; i < nv; ++i)
                if (smSlot_[vs[i]] < 0) { smSlot_[vs[i]] = (int)smRing_.size(); smRing_.push_back(vs[i]); }
            const size_t core = smRing_.size();
            for (size_t i = 0; i < core; ++i)
                for (int nb : mesh_.vertNbrs[smRing_[i]])
                    if (smSlot_[nb] < 0) { smSlot_[nb] = (int)smRing_.size(); smRing_.push_back(nb); }
            smLap_.resize(smRing_.size());
            parallelFor((int)smRing_.size(), [&](int i) { smLap_[i] = laplacian(mesh_, smRing_[i]); });
            parallelFor(nv, [&](int i) {
                int v = vs[i];
                const Vec3 L = smLap_[smSlot_[v]];
                const auto& nb = mesh_.vertNbrs[v];
                Vec3 mean{0, 0, 0};
                for (int j : nb) mean += smLap_[smSlot_[j]];
                if (!nb.empty()) mean = mean / (float)nb.size();
                Vec3 hc = (L - mean) * (1.0f - beta);
                disp_[v] = (L * (1.0f - volume) + hc * volume) * std::min(1.0f, strength * w[i]);
            });
            for (int v : smRing_) smSlot_[v] = -1;
        }
        applyDisplacements(vs);
    }
}

void BrushEngine::dabInstance(const Brush& b, const Dab& dIn, Instance& in) {
    const Vec3 m = in.mirror, ax = in.axis;
    const float ang = in.ang;
    auto M = [&](const Vec3& v) { Vec3 q{v.x * m.x, v.y * m.y, v.z * m.z}; return ang != 0.0f ? rotate(q, ax, ang) : q; };
    Dab d = dIn;
    d.position = M(dIn.position);
    d.normal = normalize(M(dIn.normal));
    d.viewDir = normalize(M(dIn.viewDir));
    d.grabDelta = M(dIn.grabDelta);
    d.dabDelta = M(dIn.dabDelta);
    if ((m.x * m.y * m.z) < 0) d.angle = -dIn.angle;  // mirroring flips handedness

    const float sgn = b.invert ? -1.0f : 1.0f;
    const float s = b.strength;
    const float r = b.radius;

    // ---------------- grab family: fixed vertex set, positions from originals
    if (kernelIsGrab(b.kernel)) {
        auto& vs = in.grabVerts;
        auto& ws = in.grabWeights;
        Vec3 delta = d.grabDelta;
        switch (b.kernel) {
            case Kernel::Move:
            case Kernel::MoveTopological:
            case Kernel::MoveInfiniteDepth:
                parallelFor((int)vs.size(), [&](int i) {
                    int v = vs[i];
                    disp_[v] = origPos_[v] + delta * ws[i] - mesh_.positions[v];
                });
                break;
            case Kernel::MoveElastic: {
                Kelvinlet k(r, b.poisson);
                parallelFor((int)vs.size(), [&](int i) {
                    int v = vs[i];
                    Vec3 u = k.grab(origPos_[v] - in.startPos, delta);
                    disp_[v] = origPos_[v] + u * ws[i] - mesh_.positions[v];
                });
                break;
            }
            case Kernel::Rotate: {
                Vec3 axis = in.startNormal;
                parallelFor((int)vs.size(), [&](int i) {
                    int v = vs[i];
                    Vec3 rel = origPos_[v] - in.startPos;
                    Vec3 rot = rotate(rel, axis, d.angle * ws[i] * sgn);
                    disp_[v] = in.startPos + rot - mesh_.positions[v];
                });
                break;
            }
            case Kernel::ElasticTwist: {
                // Regularized Kelvinlet twist (de Goes & James 2017 §4): rotation
                // about the stroke-start normal whose angle decays with the
                // Kelvinlet profile; the centre turns by exactly the swept angle.
                Kelvinlet k(r, b.poisson);
                Vec3 axis = in.startNormal;
                float ang = d.angle * sgn * s * 2.0f;
                parallelFor((int)vs.size(), [&](int i) {
                    int v = vs[i];
                    Vec3 rel = origPos_[v] - in.startPos;
                    Vec3 rot = rotate(rel, axis, ang * k.profile(rel) * ws[i]);
                    disp_[v] = in.startPos + rot - mesh_.positions[v];
                });
                break;
            }
            case Kernel::ElasticScale: {
                // Regularized Kelvinlet scale (de Goes & James 2017 §4): radial
                // grow/shrink about the press point. Drag distance / radius sets
                // the amount, Ctrl shrinks.
                Kelvinlet k(r, b.poisson);
                float amount = length(delta) / r * sgn * s * 2.0f;
                parallelFor((int)vs.size(), [&](int i) {
                    int v = vs[i];
                    Vec3 rel = origPos_[v] - in.startPos;
                    float f = std::max(-0.95f, amount * k.profile(rel) * ws[i]);
                    disp_[v] = origPos_[v] + rel * f - mesh_.positions[v];
                });
                break;
            }
            case Kernel::Pose: {
                // Rotate the segment about its joint so the grabbed point
                // follows the cursor (arc, not translation: limbs keep length).
                Vec3 a = in.startPos - in.pivot, bb = in.startPos + delta - in.pivot;
                Vec3 ax = cross(a, bb);
                float la = length(a), lb = length(bb), lx = length(ax);
                if (la < 1e-9f || lb < 1e-9f || lx < 1e-12f) break;
                ax = ax / lx;
                float ang = std::atan2(lx, dot(a, bb)) * (b.invert ? -1.0f : 1.0f);
                parallelFor((int)vs.size(), [&](int i) {
                    int v = vs[i];
                    Vec3 rot = rotate(origPos_[v] - in.pivot, ax, ang * ws[i]);
                    disp_[v] = in.pivot + rot - mesh_.positions[v];
                });
                break;
            }
            case Kernel::Cloth: {
                // Position-based dynamics on the grabbed patch (see docs/MATH.md#cloth).
                const int nv = (int)vs.size();
                std::unordered_map<int, int> local;
                local.reserve(nv * 2);
                for (int i = 0; i < nv; ++i) local[vs[i]] = i;
                std::vector<Vec3> x(nv);
                for (int i = 0; i < nv; ++i) x[i] = mesh_.positions[vs[i]];
                std::vector<char> pinned(nv, 0);
                for (int i = 0; i < nv; ++i) {
                    int v = vs[i];
                    float dist = length(origPos_[v] - in.startPos) / r;
                    if (dist > 1.35f) { x[i] = origPos_[v]; pinned[i] = 1; continue; }
                    float w = ws[i];
                    Vec3 target = origPos_[v] + delta * w;
                    x[i] = lerp(x[i], target, std::min(1.0f, w * w * 1.5f));
                    x[i] += Vec3{0, -b.clothGravity * r * 0.01f, 0} * (1 - w);
                }
                for (int it = 0; it < b.clothIterations; ++it) {
                    for (int i = 0; i < nv; ++i) {
                        int v = vs[i];
                        for (int nb : mesh_.vertNbrs[v]) {
                            auto f = local.find(nb);
                            if (f == local.end() || f->second < i) continue;  // each edge once
                            int j = f->second;
                            float rest = length(origPos_[nb] - origPos_[v]);
                            Vec3 e = x[j] - x[i];
                            float len = length(e);
                            if (len < 1e-9f) continue;
                            Vec3 corr = e * ((len - rest) / len * 0.5f);
                            if (!pinned[i]) x[i] += corr;
                            if (!pinned[j]) x[j] -= corr;
                            if (len < rest) {
                                // Compression buckles out of plane: seed folds along
                                // the normal with a spatially coherent sign.
                                float sign = valueNoise3(origPos_[v] * (3.0f / r)) > 0.5f ? 1.f : -1.f;
                                Vec3 off = mesh_.normals[v] * ((rest - len) * 0.5f * sign);
                                if (!pinned[i]) x[i] += off;
                                if (!pinned[j]) x[j] += off;
                            }
                        }
                    }
                }
                for (int i = 0; i < nv; ++i) {
                    int v = vs[i];
                    disp_[v] = lerp(mesh_.positions[v], x[i], 1 - b.clothDamping) - mesh_.positions[v];
                }
                break;
            }
            default: break;
        }
        applyDisplacements(vs, &in);
        // auto-smooth follows the grab's falloff (a uniform pass flattened the
        // whole sphere's edge into a visible ring)
        if (b.autoSmooth > 0) smoothRegion(vs, ws, b.autoSmooth, 1, b.autoSmoothVolume, false);
        return;
    }

    // ---------------- per-dab families: query the sphere at the dab
    bvh_.queryVerts(mesh_, d.position, r, verts_);
    if (verts_.empty()) return;

    // Area plane from the unweighted neighbourhood, then weights in that frame.
    Vec3 hint = b.alphaFollowStroke ? M(lastStrokeDir_) : Vec3{1, 0, 0};
    Vec3 T, B;
    tangentFrame(d.normal, hint, T, B);
    weights_.resize(verts_.size());
    for (size_t i = 0; i < verts_.size(); ++i)
        weights_[i] = vertexWeight(b, d, d.position, d.normal, T, verts_[i], d.pressure);
    if (b.kernel != Kernel::Mask && b.kernel != Kernel::Paint) {
        // Vertices with zero weight (facing away, masked, outside a square tip
        // or an alpha) never move: drop them before the kernel, so neither
        // the kernel nor the normals / BVH / host upload pay for them. On a
        // thin part (an ear, a finger) that is half of the sphere's vertices.
        size_t k = 0;
        for (size_t i = 0; i < verts_.size(); ++i)
            if (weights_[i] > 0.0f) { verts_[k] = verts_[i]; weights_[k] = weights_[i]; ++k; }
        verts_.resize(k);
        weights_.resize(k);
        if (verts_.empty()) return;
    }
    markTouched(verts_);

    Vec3 ac, an;
    areaPlane(verts_, weights_, ac, an);
    if (length2(an) < 1e-8f) { an = d.normal; ac = d.position; }

    const int nv = (int)verts_.size();
    // Per-dab height. Scaled by spacing so a stroke builds the same height
    // whatever the dab density: dabs per radius = 1/spacing, height per dab ∝
    // spacing -> height per radius of stroke = s·r·0.3. See docs/MATH.md#strength.
    const float h = s * r * 0.3f * std::max(0.01f, std::min(1.0f, b.spacing));

    auto planeDisp = [&](const Vec3& pc, const Vec3& pn, int mode) {
        // mode: 0 flatten, 1 fill only, 2 scrape only
        float trim = b.planeTrim * r;
        parallelFor(nv, [&](int i) {
            int v = verts_[i];
            float w = weights_[i];
            if (w <= 0) { disp_[v] = Vec3{}; return; }
            float dist = dot(mesh_.positions[v] - pc, pn);
            if (std::fabs(dist) > trim) { disp_[v] = Vec3{}; return; }
            if ((mode == 1 && dist > 0) || (mode == 2 && dist < 0)) { disp_[v] = Vec3{}; return; }
            disp_[v] = pn * (-dist * std::min(1.0f, s * w * 2.0f));
        });
    };

    switch (b.kernel) {
        case Kernel::Standard:
            parallelFor(nv, [&](int i) { disp_[verts_[i]] = an * (h * weights_[i] * sgn); });
            break;
        case Kernel::DamStandard: {
            // Carve along the area normal plus a tangential pinch toward the
            // stroke line: crisp creases with tight walls.
            float pinch = b.pinch > 0 ? b.pinch : 0.5f;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                Vec3 q = projectOnPlane(mesh_.positions[v] - d.position, an);
                Vec3 side = B * dot(q, B);  // perpendicular to stroke direction only
                disp_[v] = (an * (-h * sgn) - side * (pinch * s * 0.25f)) * weights_[i];
            });
            break;
        }
        case Kernel::Inflate:
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                disp_[v] = mesh_.normals[v] * (h * weights_[i] * sgn);
            });
            break;
        case Kernel::Blob:
            // Inflate with a magnify term: bulges grow fastest where the
            // surface already bulges, which gives the irregular organic look.
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                Vec3 q = projectOnPlane(mesh_.positions[v] - d.position, an);
                disp_[v] = (mesh_.normals[v] * h + q * (s * 0.05f)) * (weights_[i] * sgn);
            });
            break;
        case Kernel::Displace:
            // Push along the *stroke-start* normal: the whole patch moves
            // rigidly, so existing detail is carried along instead of inflated.
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                disp_[v] = origNrm_[v] * (h * weights_[i] * sgn);
            });
            break;
        case Kernel::Magnify:
        case Kernel::Pinch: {
            float dir = (b.kernel == Kernel::Pinch ? -1.0f : 1.0f) * sgn;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                Vec3 q = projectOnPlane(mesh_.positions[v] - d.position, an);
                disp_[v] = q * (dir * s * 0.1f * weights_[i]);
            });
            break;
        }
        case Kernel::Layer: {
            // Persistent height: each vertex rises to at most layerHeight above
            // its stroke-start position, however many times it is crossed.
            float maxH = b.layerHeight * r;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                float target = std::max(layerDisp_[v], maxH * weights_[i]);
                layerDisp_[v] = target;
                Vec3 want = origPos_[v] + origNrm_[v] * (target * sgn);
                disp_[v] = (want - mesh_.positions[v]) * std::min(1.0f, s * 2.0f);
            });
            break;
        }
        case Kernel::Crease: {
            // Pinch toward the stroke centre + a carve whose profile is the
            // falloff to the 5th power: a sharp V crease with tight walls
            // (after SculptGL's Crease tool, MIT; see THIRD_PARTY_NOTICES).
            float pinch = (b.pinch > 0 ? b.pinch : 0.7f) * s * 0.15f;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                float w = weights_[i];
                float w5 = w * w * w * w * w;
                Vec3 q = projectOnPlane(d.position - mesh_.positions[v], an);
                disp_[v] = q * (pinch * w) - an * (h * 4.0f * w5 * sgn);
            });
            break;
        }
        case Kernel::SurfaceNoise:
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                float n = fbm3(origPos_[v] * (b.noiseScale / r), 3) - 0.5f;
                disp_[v] = origNrm_[v] * (n * h * 2.0f * weights_[i] * sgn);
            });
            break;

        case Kernel::Clay:
        case Kernel::ClayBuildup:
        case Kernel::ClayStrips: {
            // Fill toward a plane lifted above the area centre. Only material
            // below the plane moves, so strokes stack up like slabs of clay.
            float off = (b.planeOffset != 0 ? b.planeOffset : (b.kernel == Kernel::ClayBuildup ? 0.25f : 0.12f));
            Vec3 pn = an * sgn;
            Vec3 pc = ac + pn * (off * r * s);
            planeDisp(pc, pn, 1);
            break;
        }
        case Kernel::Flatten:
            planeDisp(ac, an * sgn, 0);
            break;
        case Kernel::Fill:
            planeDisp(ac, an * sgn, 1);
            break;
        case Kernel::Scrape:
            planeDisp(ac, an * sgn, 2);
            break;
        case Kernel::Planar:
            // Plane locked at stroke start: every dab cuts to the same plane.
            planeDisp(in.planeCenter, in.planeNormal * sgn, 2);
            break;
        case Kernel::TrimDynamic:
            planeDisp(ac - an * (0.05f * r), an * sgn, 2);
            break;
        case Kernel::TrimAdaptive: {
            Vec3 pn = normalize(in.planeNormal + an) * sgn;
            planeDisp(ac, pn, 2);
            break;
        }
        case Kernel::Polish:
            // Flatten toward the local plane + tangential relax: removes
            // lumps while keeping silhouettes tight (hard-surface finishing).
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                float w = weights_[i];
                float dist = dot(mesh_.positions[v] - ac, an);
                Vec3 L = projectOnPlane(laplacian(mesh_, v), mesh_.normals[v]);
                disp_[v] = (an * (-dist) + L) * std::min(1.0f, s * w);
            });
            break;
        case Kernel::MultiplaneScrape: {
            // Two planes through the area centre, each tilted by planeAngle
            // about the stroke direction: scrapes a roof-shaped ridge along
            // the stroke (Ctrl: a V valley). Each vertex uses the plane on its
            // side of the stroke line.
            float th = b.planeAngle * 3.14159265f / 180.0f;
            // Frame from the stroke-start surface (normals measured on the
            // trench being cut tilt, rotate the planes and shred the ridge).
            Vec3 n0{};
            for (int i = 0; i < nv; ++i) n0 += origNrm_[verts_[i]] * weights_[i];
            n0 = length2(n0) > 1e-12f ? normalize(n0) : an;
            Vec3 T0, B0;
            tangentFrame(n0, hint, T0, B0);
            Vec3 n1 = normalize(n0 * std::cos(th) + B0 * std::sin(th));
            Vec3 n2 = normalize(n0 * std::cos(th) - B0 * std::sin(th));
            float trim = std::max(b.planeTrim, 0.75f) * r;
            // Apex on the stroke-start surface: re-measuring the already cut
            // surface every dab dug the ridge deeper and deeper (ragged).
            Vec3 apex{};
            float wsum = 0;
            for (int i = 0; i < nv; ++i) { apex += origPos_[verts_[i]] * weights_[i]; wsum += weights_[i]; }
            apex = wsum > 0 ? apex / wsum : ac;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                float w = weights_[i];
                Vec3 rel = mesh_.positions[v] - apex;
                Vec3 pn = (dot(rel, B0) >= 0) == (sgn > 0) ? n1 : n2;
                pn = pn * sgn;
                float dist = dot(rel, pn);
                if (w <= 0 || dist <= 0) { disp_[v] = Vec3{}; return; }
                // Drop the vertex onto its plane *along the area normal*: moving
                // along the tilted plane normal pushed both sides onto the
                // ridge line and folded the surface. Depth fades out smoothly
                // toward the trim (a hard cut-off left cliffs on steep angles).
                float t = dist / std::max(0.2f, std::fabs(dot(n0, pn)));
                float fade = clamp01((trim - t) / (0.5f * trim) + 1.0f);
                t = std::min(t, trim) * fade;
                // at most a third of the way per dab: overlapping dabs on a
                // curving stroke converge instead of snapping to rotating planes
                disp_[v] = n0 * (-sgn * t * std::min(0.35f, s * w));
            });
            break;
        }
        case Kernel::Smooth:
        case Kernel::SmoothRelax: {
            // Smooth: Laplacian blended with the volume-preserving HC step
            // (smoothVolume); Smooth Relax: tangential only (slides vertices
            // along the surface, evens the triangles, keeps the shape).
            bool tangential = b.kernel == Kernel::SmoothRelax;
            smoothRegion(verts_, weights_, s, std::max(1, b.smoothIterations), tangential ? 0.0f : b.smoothVolume, tangential);
            if (b.autoSmooth > 0) smoothRegion(verts_, weights_, b.autoSmooth, 1, b.autoSmoothVolume, false);
            return;
        }
        case Kernel::SnakeHook: {
            float pinch = b.pinch;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                Vec3 q = projectOnPlane(mesh_.positions[v] - d.position, an);
                disp_[v] = (d.dabDelta - q * (pinch * 0.2f)) * weights_[i];
            });
            break;
        }
        case Kernel::Nudge:
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                disp_[v] = projectOnPlane(d.dabDelta, mesh_.normals[v]) * (s * weights_[i]);
            });
            break;
        case Kernel::Thumb:
            // Flatten toward the area plane while dragging the surface along
            // the stroke (Thumb): smears and presses at once.
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                float w = std::min(1.0f, s * weights_[i]);
                float dist = dot(mesh_.positions[v] - ac, an);
                disp_[v] = an * (-dist * w * 0.5f) + projectOnPlane(d.dabDelta, an) * w;
            });
            break;
        case Kernel::Morph:
        case Kernel::HistoryRecall: {
            auto& tgt = b.kernel == Kernel::Morph ? morph_ : recall_;
            if (!tgt || tgt->positions.size() != mesh_.positions.size()) return;  // topology changed
            const auto& tp = tgt->positions;
            parallelFor(nv, [&](int i) {
                int v = verts_[i];
                Vec3 to = b.invert ? (mesh_.positions[v] * 2.0f - tp[v]) : tp[v];  // invert = exaggerate
                disp_[v] = (to - mesh_.positions[v]) * std::min(1.0f, s * weights_[i]);
            });
            break;
        }
        case Kernel::Mask:
            for (int i = 0; i < nv; ++i) {
                int v = verts_[i];
                // Mask weight ignores the existing mask (it *edits* the mask).
                float x = length(mesh_.positions[v] - d.position) / r;
                float w = b.falloff.eval(x) * s * (b.usePressure ? d.pressure : 1.f);
                mesh_.mask[v] = clamp01(mesh_.mask[v] + (b.invert ? -w : w));
            }
            return;
        case Kernel::Paint:
            for (int i = 0; i < nv; ++i) {
                int v = verts_[i];
                mesh_.color[v] = lerp(mesh_.color[v], b.color, std::min(1.0f, s * weights_[i]));
            }
            return;
        default:
            return;
    }

    applyDisplacements(verts_);
    if (b.autoSmooth > 0) smoothRegion(verts_, weights_, b.autoSmooth, 1, b.autoSmoothVolume, false);
}

void BrushEngine::endStroke() {
    for (Instance& in : inst_) { in.grabVerts.clear(); in.grabWeights.clear(); }
    refitSpatial();
}

}  // namespace sculpt
