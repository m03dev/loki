#include "sculpt/multires.h"
#include "sculpt/parallel.h"
#include <algorithm>
#include <cmath>
#include <utility>

namespace sculpt {

// ------------------------------------------------------------ Catmull-Clark

void CCSubdivider::build(const std::vector<int>& counts, const std::vector<int>& indices, int vertexCount) {
    nv_ = vertexCount;
    const int F = (int)counts.size();
    faceOff_.assign(F + 1, 0);
    for (int f = 0; f < F; ++f) faceOff_[f + 1] = faceOff_[f] + counts[f];
    idx_ = indices;

    // Half-edges grouped by their lower vertex: (hi, face). Sorting each small
    // list finds both faces of an edge without a global hash map.
    std::vector<int> cnt(nv_ + 1, 0);
    for (int f = 0; f < F; ++f)
        for (int c = faceOff_[f]; c < faceOff_[f + 1]; ++c) {
            int a = idx_[c], b = idx_[c + 1 < faceOff_[f + 1] ? c + 1 : faceOff_[f]];
            ++cnt[std::min(a, b) + 1];
        }
    for (int v = 0; v < nv_; ++v) cnt[v + 1] += cnt[v];
    std::vector<std::pair<int, int>> he(cnt[nv_]);
    {
        std::vector<int> fill(cnt.begin(), cnt.end() - 1);
        for (int f = 0; f < F; ++f)
            for (int c = faceOff_[f]; c < faceOff_[f + 1]; ++c) {
                int a = idx_[c], b = idx_[c + 1 < faceOff_[f + 1] ? c + 1 : faceOff_[f]];
                he[fill[std::min(a, b)]++] = {std::max(a, b), f};
            }
    }
    parallelFor(nv_, [&](int v) { std::sort(he.begin() + cnt[v], he.begin() + cnt[v + 1]); }, 16384);
    // unique edges per vertex -> ids by prefix sum
    std::vector<int> ucount(nv_ + 1, 0);
    parallelFor(nv_, [&](int v) {
        int u = 0;
        for (int i = cnt[v]; i < cnt[v + 1]; ++i)
            if (i == cnt[v] || he[i].first != he[i - 1].first) ++u;
        ucount[v + 1] = u;
    }, 16384);
    for (int v = 0; v < nv_; ++v) ucount[v + 1] += ucount[v];
    edges_.assign(ucount[nv_], Edge{});
    parallelFor(nv_, [&](int v) {
        int e = ucount[v] - 1;
        for (int i = cnt[v]; i < cnt[v + 1]; ++i) {
            if (i == cnt[v] || he[i].first != he[i - 1].first) {
                ++e;
                edges_[e] = {v, he[i].first, he[i].second, -1};
            } else if (edges_[e].f1 < 0 && he[i].second != edges_[e].f0) {
                edges_[e].f1 = he[i].second;  // (non-manifold extras beyond 2 faces are ignored)
            }
        }
    }, 16384);
    auto edgeId = [&](int a, int b) {
        int lo = std::min(a, b), hi = std::max(a, b);
        // unique edges of `lo` are contiguous from ucount[lo]
        int l = ucount[lo], r = ucount[lo + 1];
        while (l < r) {
            int m = (l + r) / 2;
            if (edges_[m].b < hi) l = m + 1; else r = m;
        }
        return l;
    };

    // vertex -> faces, vertex -> edges
    vfOff_.assign(nv_ + 1, 0);
    for (int c = 0; c < (int)idx_.size(); ++c) ++vfOff_[idx_[c] + 1];
    for (int v = 0; v < nv_; ++v) vfOff_[v + 1] += vfOff_[v];
    vf_.assign(vfOff_[nv_], 0);
    {
        std::vector<int> fill(vfOff_.begin(), vfOff_.end() - 1);
        for (int f = 0; f < F; ++f)
            for (int c = faceOff_[f]; c < faceOff_[f + 1]; ++c) vf_[fill[idx_[c]]++] = f;
    }
    veOff_.assign(nv_ + 1, 0);
    for (const Edge& e : edges_) { ++veOff_[e.a + 1]; ++veOff_[e.b + 1]; }
    for (int v = 0; v < nv_; ++v) veOff_[v + 1] += veOff_[v];
    ve_.assign(veOff_[nv_], 0);
    {
        std::vector<int> fill(veOff_.begin(), veOff_.end() - 1);
        for (int e = 0; e < (int)edges_.size(); ++e) {
            ve_[fill[edges_[e].a]++] = e;
            ve_[fill[edges_[e].b]++] = e;
        }
    }

    // Output topology: corner i of face f -> quad (v_i, e(v_i,v_i+1), F, e(v_i-1,v_i)).
    const int E = (int)edges_.size();
    outCounts_.assign(idx_.size(), 4);
    outIdx_.assign(idx_.size() * 4, 0);
    parallelFor(F, [&](int f) {
        int o = faceOff_[f], k = faceOff_[f + 1] - o;
        int fp = nv_ + E + f;
        for (int i = 0; i < k; ++i) {
            int v = idx_[o + i], vn = idx_[o + (i + 1) % k], vp = idx_[o + (i + k - 1) % k];
            int* q = &outIdx_[(size_t)(o + i) * 4];
            q[0] = v;
            q[1] = nv_ + edgeId(v, vn);
            q[2] = fp;
            q[3] = nv_ + edgeId(vp, v);
        }
    }, 4096);
}

void CCSubdivider::apply(const std::vector<Vec3>& P, std::vector<Vec3>& out) const {
    const int F = (int)faceOff_.size() - 1, E = (int)edges_.size();
    out.resize((size_t)nv_ + E + F);
    Vec3* fp = out.data() + nv_ + E;
    parallelFor(F, [&](int f) {
        Vec3 s{};
        for (int c = faceOff_[f]; c < faceOff_[f + 1]; ++c) s += P[idx_[c]];
        fp[f] = s / (float)(faceOff_[f + 1] - faceOff_[f]);
    }, 8192);
    parallelFor(E, [&](int e) {
        const Edge& ed = edges_[e];
        out[nv_ + e] = ed.f1 < 0 ? (P[ed.a] + P[ed.b]) * 0.5f
                                 : (P[ed.a] + P[ed.b] + fp[ed.f0] + fp[ed.f1]) * 0.25f;
    }, 8192);
    parallelFor(nv_, [&](int v) {
        int e0 = veOff_[v], e1 = veOff_[v + 1];
        int n = e1 - e0;
        if (n == 0 || vfOff_[v] == vfOff_[v + 1]) { out[v] = P[v]; return; }
        int nb = 0;
        Vec3 bsum{};
        for (int i = e0; i < e1; ++i) {
            const Edge& ed = edges_[ve_[i]];
            if (ed.f1 < 0) { ++nb; bsum += P[ed.a == v ? ed.b : ed.a]; }
        }
        if (nb == 2 && n == 2) { out[v] = P[v]; return; }                 // open corner: pinned
        if (nb == 2) { out[v] = (P[v] * 6.0f + bsum) * 0.125f; return; }  // boundary crease rule
        if (nb > 0) { out[v] = P[v]; return; }                             // corner / non-manifold: pinned
        Vec3 Q{}, R{};
        for (int i = vfOff_[v]; i < vfOff_[v + 1]; ++i) Q += fp[vf_[i]];
        Q = Q / (float)(vfOff_[v + 1] - vfOff_[v]);
        for (int i = e0; i < e1; ++i) {
            const Edge& ed = edges_[ve_[i]];
            R += (P[ed.a] + P[ed.b]) * 0.5f;
        }
        R = R / (float)n;
        out[v] = (Q + R * 2.0f + P[v] * (float)(n - 3)) / (float)n;
    }, 8192);
}

// ------------------------------------------------------------ frames

void PolyFrames::build(const std::vector<int>& counts, const std::vector<int>& indices, int vertexCount) {
    nv_ = vertexCount;
    off_.assign(nv_ + 1, 0);
    for (int i : indices) ++off_[i + 1];
    for (int v = 0; v < nv_; ++v) off_[v + 1] += off_[v];
    prev_.assign(off_[nv_], 0);
    next_.assign(off_[nv_], 0);
    std::vector<int> fill(off_.begin(), off_.end() - 1);
    size_t o = 0;
    for (int k : counts) {
        for (int i = 0; i < k; ++i) {
            int v = indices[o + i];
            int slot = fill[v]++;
            next_[slot] = indices[o + (i + 1) % k];
            prev_[slot] = indices[o + (i + k - 1) % k];
        }
        o += k;
    }
}

void PolyFrames::compute(const std::vector<Vec3>& P, std::vector<Vec3>& N, std::vector<Vec3>& T) const {
    N.resize(nv_);
    T.resize(nv_);
    parallelFor(nv_, [&](int v) {
        Vec3 n{};
        for (int s = off_[v]; s < off_[v + 1]; ++s) n += cross(P[next_[s]] - P[v], P[prev_[s]] - P[v]);
        n = normalize(n);
        if (length2(n) < 1e-20f) n = {0, 0, 1};
        Vec3 t = off_[v] < off_[v + 1] ? P[next_[off_[v]]] - P[v] : Vec3{1, 0, 0};
        t = t - n * dot(t, n);
        if (length2(t) < 1e-20f) t = std::fabs(n.x) < 0.9f ? Vec3{1, 0, 0} - n * n.x : Vec3{0, 1, 0} - n * n.y;
        N[v] = n;
        T[v] = normalize(t);
    }, 8192);
}

// ------------------------------------------------------------ stack

void Multires::init(const std::vector<int>& counts, const std::vector<int>& indices, const std::vector<Vec3>& positions) {
    levels_.clear();
    MultiresLevel l0;
    l0.counts = counts;
    l0.indices = indices;
    l0.vertexCount = (int)positions.size();
    l0.positions = positions;
    levels_.push_back(std::move(l0));
    edited_.assign(1, false);
    cur_ = 0;
}

CCSubdivider& Multires::sub(int k) {
    MultiresLevel& l = levels_[k];
    if (!l.up) {
        l.up = std::make_shared<CCSubdivider>();
        l.up->build(l.counts, l.indices, l.vertexCount);
    }
    return *l.up;
}

PolyFrames& Multires::frames(int k) {
    MultiresLevel& l = levels_[k];
    if (!l.frames) {
        l.frames = std::make_shared<PolyFrames>();
        l.frames->build(l.counts, l.indices, l.vertexCount);
    }
    return *l.frames;
}

bool Multires::matches(int vertexCount, int faceCount) const {
    if (levels_.empty()) return false;
    const MultiresLevel& l = levels_[cur_];
    return l.vertexCount == vertexCount && (int)l.counts.size() == faceCount;
}

void Multires::storeCurrent(const std::vector<Vec3>& positions) {
    MultiresLevel& l = levels_[cur_];
    if (positions.size() != l.positions.size()) return;
    bool same = true;
    for (size_t i = 0; i < positions.size() && same; ++i)
        same = positions[i].x == l.positions[i].x && positions[i].y == l.positions[i].y && positions[i].z == l.positions[i].z;
    if (!same) {
        l.positions = positions;
        edited_[cur_] = true;
    }
}

// Level `from` holds edited positions: push them down the stack. The lower
// level's control points take the vertex-point positions, then that level's
// detail is re-derived against the new subdivided surface (exact round trip).
void Multires::propagateDown(int from) {
    for (int j = from; j >= 1 && edited_[j]; --j) {
        MultiresLevel& hi = levels_[j];
        MultiresLevel& lo = levels_[j - 1];
        for (int v = 0; v < lo.vertexCount; ++v) lo.positions[v] = hi.positions[v];
        edited_[j - 1] = true;
        std::vector<Vec3> S, N, T;
        sub(j - 1).apply(lo.positions, S);
        frames(j).compute(S, N, T);
        hi.detail.resize(hi.vertexCount);
        parallelFor(hi.vertexCount, [&](int v) {
            Vec3 d = hi.positions[v] - S[v];
            Vec3 b = cross(N[v], T[v]);
            hi.detail[v] = {dot(d, T[v]), dot(d, b), dot(d, N[v])};
        }, 8192);
        edited_[j] = false;
    }
    if (from >= 0 && from < (int)edited_.size()) edited_[0] = false;
}

void Multires::rebuildUp(int to) {
    for (int k = cur_; k < to; ++k) {
        MultiresLevel& lo = levels_[k];
        MultiresLevel& hi = levels_[k + 1];
        std::vector<Vec3> S, N, T;
        sub(k).apply(lo.positions, S);
        frames(k + 1).compute(S, N, T);
        hi.positions.resize(hi.vertexCount);
        bool hasD = (int)hi.detail.size() == hi.vertexCount;
        parallelFor(hi.vertexCount, [&](int v) {
            if (!hasD) { hi.positions[v] = S[v]; return; }
            const Vec3& d = hi.detail[v];
            Vec3 b = cross(N[v], T[v]);
            hi.positions[v] = S[v] + T[v] * d.x + b * d.y + N[v] * d.z;
        }, 8192);
        edited_[k + 1] = false;
    }
}

bool Multires::divide(const std::vector<Vec3>& positions) {
    if (levels_.empty() || cur_ != (int)levels_.size() - 1) return false;
    storeCurrent(positions);
    propagateDown(cur_);
    CCSubdivider& s = sub(cur_);
    MultiresLevel nl;
    nl.counts = s.outCounts();
    nl.indices = s.outIndices();
    nl.vertexCount = s.outVerts();
    s.apply(levels_[cur_].positions, nl.positions);
    nl.detail.assign(nl.vertexCount, Vec3{});
    levels_.push_back(std::move(nl));
    edited_.push_back(false);
    cur_ = (int)levels_.size() - 1;
    return true;
}

bool Multires::setLevel(int k, const std::vector<Vec3>& positions) {
    if (levels_.empty() || k < 0 || k >= (int)levels_.size()) return false;
    storeCurrent(positions);
    propagateDown(cur_);  // lower levels follow the current one
    if (k > cur_) rebuildUp(k);
    cur_ = k;
    return true;
}

void Multires::deleteHigher(const std::vector<Vec3>& positions) {
    if (levels_.empty()) return;
    storeCurrent(positions);
    propagateDown(cur_);
    levels_.resize(cur_ + 1);
    edited_.resize(cur_ + 1);
    levels_[cur_].up.reset();
}

void Multires::deleteLower(const std::vector<Vec3>& positions) {
    if (levels_.empty() || cur_ == 0) return;
    storeCurrent(positions);
    propagateDown(cur_);
    levels_.erase(levels_.begin(), levels_.begin() + cur_);
    edited_.erase(edited_.begin(), edited_.begin() + cur_);
    levels_[0].detail.clear();
    cur_ = 0;
}

size_t Multires::memoryBytes() const {
    size_t b = 0;
    for (const auto& l : levels_)
        b += (l.counts.size() + l.indices.size()) * sizeof(int) + (l.positions.size() + l.detail.size()) * sizeof(Vec3);
    return b;
}

}  // namespace sculpt
