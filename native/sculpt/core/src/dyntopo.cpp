#include "sculpt/dyntopo.h"
#include <algorithm>

namespace sculpt {

static void eraseVal(std::vector<int>& v, int x) {
    auto it = std::find(v.begin(), v.end(), x);
    if (it != v.end()) { *it = v.back(); v.pop_back(); }
}
static void replaceVal(std::vector<int>& v, int from, int to) {
    for (int& x : v) if (x == from) { x = to; return; }
}
static void addUnique(std::vector<int>& v, int x) {
    if (std::find(v.begin(), v.end(), x) == v.end()) v.push_back(x);
}

void DynTopo::addFace(int a, int b, int f) {
    EdgeRec& e = edges_[key(a, b)];
    if (e.f0 < 0) e.f0 = f;
    else if (e.f1 < 0) e.f1 = f;
    // non-manifold third face: ignored (edge is then never split/collapsed)
}
void DynTopo::removeFace(int a, int b, int f) {
    auto it = edges_.find(key(a, b));
    if (it == edges_.end()) return;
    if (it->second.f0 == f) it->second.f0 = it->second.f1, it->second.f1 = -1;
    else if (it->second.f1 == f) it->second.f1 = -1;
    if (it->second.f0 < 0) edges_.erase(it);
}
void DynTopo::replaceFace(int a, int b, int from, int to) {
    auto it = edges_.find(key(a, b));
    if (it == edges_.end()) return;
    if (it->second.f0 == from) it->second.f0 = to;
    else if (it->second.f1 == from) it->second.f1 = to;
}

void DynTopo::attach(Mesh& m) {
    edges_.clear();
    edges_.reserve(m.tris.size() * 2);
    for (int t = 0; t < (int)m.tris.size(); ++t) {
        const Tri& f = m.tris[t];
        if (f[0] < 0) continue;
        for (int k = 0; k < 3; ++k) addFace(f[k], f[(k + 1) % 3], t);
    }
    if (m.vertTris.size() != m.positions.size()) m.buildAdjacency();
    m.ensureAttributes();
}

// Index (0..2) where tri f has the directed edge a->b, or -1.
static int directed(const Tri& f, int a, int b) {
    for (int k = 0; k < 3; ++k)
        if (f[k] == a && f[(k + 1) % 3] == b) return k;
    return -1;
}

bool DynTopo::split(Mesh& m, int a, int b) {
    auto it = edges_.find(key(a, b));
    if (it == edges_.end()) return false;
    int fa = it->second.f0, fb = it->second.f1;
    // fa must contain a->b; fb (if any) contains b->a.
    if (directed(m.tris[fa], a, b) < 0) {
        if (fb >= 0 && directed(m.tris[fb], a, b) >= 0) std::swap(fa, fb);
        else std::swap(a, b);
    }
    int ka = directed(m.tris[fa], a, b);
    if (ka < 0) return false;
    int c = m.tris[fa][(ka + 2) % 3];
    int d = -1, kb = -1;
    if (fb >= 0) {
        kb = directed(m.tris[fb], b, a);
        if (kb < 0) return false;
        d = m.tris[fb][(kb + 2) % 3];
    }

    // New vertex: attribute midpoint.
    int mv = (int)m.positions.size();
    m.positions.push_back((m.positions[a] + m.positions[b]) * 0.5f);
    m.normals.push_back(normalize(m.normals[a] + m.normals[b]));
    m.mask.push_back((m.mask[a] + m.mask[b]) * 0.5f);
    m.color.push_back((m.color[a] + m.color[b]) * 0.5f);
    m.vertTris.emplace_back();
    m.vertNbrs.emplace_back();

    edges_.erase(key(a, b));

    // fa (a,b,c) -> fa (a,m,c) + na (m,b,c)
    int na = (int)m.tris.size();
    m.tris[fa] = {a, mv, c};
    m.tris.push_back({mv, b, c});
    if (m.triPoly.size() + 1 == m.tris.size()) { m.triPoly[fa] = -1; m.triPoly.push_back(-1); }
    replaceFace(b, c, fa, na);
    addFace(a, mv, fa);
    addFace(mv, c, fa);
    addFace(mv, c, na);
    addFace(mv, b, na);
    replaceVal(m.vertTris[b], fa, na);
    m.vertTris[c].push_back(na);
    m.vertTris[mv] = {fa, na};

    if (fb >= 0) {
        // fb (b,a,d) -> fb (b,m,d) + nb (m,a,d)
        int nb = (int)m.tris.size();
        m.tris[fb] = {b, mv, d};
        m.tris.push_back({mv, a, d});
        if (m.triPoly.size() + 1 == m.tris.size()) { m.triPoly[fb] = -1; m.triPoly.push_back(-1); }
        replaceFace(a, d, fb, nb);
        addFace(b, mv, fb);
        addFace(mv, d, fb);
        addFace(mv, d, nb);
        addFace(mv, a, nb);
        replaceVal(m.vertTris[a], fb, nb);
        m.vertTris[d].push_back(nb);
        m.vertTris[mv].push_back(fb);
        m.vertTris[mv].push_back(nb);
    }

    replaceVal(m.vertNbrs[a], b, mv);
    replaceVal(m.vertNbrs[b], a, mv);
    m.vertNbrs[c].push_back(mv);
    m.vertNbrs[mv] = {a, b, c};
    if (d >= 0) { m.vertNbrs[d].push_back(mv); m.vertNbrs[mv].push_back(d); }
    ++stats.splits;
    return true;
}

bool DynTopo::collapse(Mesh& m, int a, int b) {
    auto it = edges_.find(key(a, b));
    if (it == edges_.end()) return false;
    int f0 = it->second.f0, f1 = it->second.f1;
    if (f0 < 0 || f1 < 0) return false;  // keep open boundaries intact

    auto onBoundary = [&](int v) {
        for (int n : m.vertNbrs[v]) {
            auto e = edges_.find(key(v, n));
            if (e == edges_.end() || e->second.f1 < 0) return true;
        }
        return false;
    };
    if (onBoundary(a) || onBoundary(b)) return false;

    // Link condition: the edge's two opposite vertices are the only common neighbours.
    int common = 0;
    for (int x : m.vertNbrs[a])
        if (std::find(m.vertNbrs[b].begin(), m.vertNbrs[b].end(), x) != m.vertNbrs[b].end()) ++common;
    if (common != 2) return false;

    auto opp = [&](int f) {
        for (int v : m.tris[f]) if (v != a && v != b) return v;
        return -1;
    };
    int c = opp(f0), d = opp(f1);
    if (m.vertNbrs[c].size() <= 3 || m.vertNbrs[d].size() <= 3) return false;
    if (m.vertNbrs[a].size() + m.vertNbrs[b].size() - 4 < 3) return false;

    Vec3 p = (m.positions[a] + m.positions[b]) * 0.5f;

    // Reject collapses that flip or degenerate a surviving face.
    std::vector<int> T;
    for (int t : m.vertTris[a]) if (t != f0 && t != f1) T.push_back(t);
    for (int t : m.vertTris[b]) if (t != f0 && t != f1) T.push_back(t);
    for (int t : T) {
        Tri f = m.tris[t];
        Vec3 n0 = normalize(m.triNormal(t));
        Vec3 q[3];
        for (int k = 0; k < 3; ++k) q[k] = (f[k] == a || f[k] == b) ? p : m.positions[f[k]];
        Vec3 n1 = cross(q[1] - q[0], q[2] - q[0]);
        if (length2(n1) < 1e-20f || dot(normalize(n1), n0) < 0.3f) return false;
    }

    // Erase edges touching a or b (all edges of f0/f1 are among them); edges of
    // the fan's outer ring keep their face indices and are left alone.
    auto eraseTouching = [&](int v) {
        for (int t : m.vertTris[v]) {
            const Tri& f = m.tris[t];
            for (int k = 0; k < 3; ++k) {
                int u = f[k], w = f[(k + 1) % 3];
                if (u == a || u == b || w == a || w == b) edges_.erase(key(u, w));
            }
        }
    };
    eraseTouching(a);
    eraseTouching(b);
    m.tris[f0] = {-1, -1, -1};
    m.tris[f1] = {-1, -1, -1};
    eraseVal(m.vertTris[c], f0);
    eraseVal(m.vertTris[d], f1);
    const bool tagged = m.triPoly.size() == m.tris.size();
    if (tagged) { m.triPoly[f0] = -1; m.triPoly[f1] = -1; }
    for (int t : T) {
        Tri& f = m.tris[t];
        for (int k = 0; k < 3; ++k)
            if (f[k] == b) { f[k] = a; if (tagged) m.triPoly[t] = -1; }
    }
    for (int t : T) {
        const Tri& f = m.tris[t];
        for (int k = 0; k < 3; ++k) {
            int u = f[k], w = f[(k + 1) % 3];
            if (u == a || w == a) addFace(u, w, t);
        }
    }

    m.positions[a] = p;
    m.mask[a] = (m.mask[a] + m.mask[b]) * 0.5f;
    m.color[a] = (m.color[a] + m.color[b]) * 0.5f;
    m.vertTris[a] = T;
    std::vector<int> nbrs;
    for (int x : m.vertNbrs[a]) if (x != b) addUnique(nbrs, x);
    for (int x : m.vertNbrs[b]) if (x != a) addUnique(nbrs, x);
    for (int x : m.vertNbrs[b]) {
        if (x == a) continue;
        auto& nx = m.vertNbrs[x];
        bool hasA = std::find(nx.begin(), nx.end(), a) != nx.end();
        if (hasA) eraseVal(nx, b); else replaceVal(nx, b, a);
    }
    m.vertNbrs[a] = nbrs;
    m.vertTris[b].clear();
    m.vertNbrs[b].clear();
    ++stats.collapses;
    return true;
}

// Edge flip (Botsch & Kobbelt 2004 step 3): faces (a,b,c) + (b,a,d) become
// (c,a,d) + (d,b,c). Rejected if c-d already exists, a or b would drop below
// valence 3, or either new face would flip / degenerate against the old pair.
bool DynTopo::flip(Mesh& m, int a, int b) {
    auto it = edges_.find(key(a, b));
    if (it == edges_.end()) return false;
    int fa = it->second.f0, fb = it->second.f1;
    if (fa < 0 || fb < 0) return false;
    if (directed(m.tris[fa], a, b) < 0) std::swap(fa, fb);
    int ka = directed(m.tris[fa], a, b), kb = directed(m.tris[fb], b, a);
    if (ka < 0 || kb < 0) return false;
    int c = m.tris[fa][(ka + 2) % 3], d = m.tris[fb][(kb + 2) % 3];
    if (c == d || edges_.count(key(c, d))) return false;
    if (m.vertNbrs[a].size() <= 3 || m.vertNbrs[b].size() <= 3) return false;
    const Vec3 &pa = m.positions[a], &pb = m.positions[b], &pc = m.positions[c], &pd = m.positions[d];
    Vec3 nOld = m.triNormal(fa) + m.triNormal(fb);
    Vec3 n1 = cross(pa - pc, pd - pc), n2 = cross(pb - pd, pc - pd);
    float l0 = length(nOld), l1 = length(n1), l2 = length(n2);
    if (l0 < 1e-20f || l1 < 1e-20f || l2 < 1e-20f) return false;
    if (dot(n1, nOld) < 0.2f * l1 * l0 || dot(n2, nOld) < 0.2f * l2 * l0) return false;

    edges_.erase(key(a, b));
    m.tris[fa] = {c, a, d};
    m.tris[fb] = {d, b, c};
    if (m.triPoly.size() == m.tris.size()) { m.triPoly[fa] = -1; m.triPoly[fb] = -1; }
    replaceFace(a, d, fb, fa);
    replaceFace(b, c, fa, fb);
    addFace(c, d, fa);
    addFace(c, d, fb);
    eraseVal(m.vertTris[a], fb);
    eraseVal(m.vertTris[b], fa);
    m.vertTris[c].push_back(fb);
    m.vertTris[d].push_back(fa);
    eraseVal(m.vertNbrs[a], b);
    eraseVal(m.vertNbrs[b], a);
    m.vertNbrs[c].push_back(d);
    m.vertNbrs[d].push_back(c);
    ++stats.flips;
    return true;
}

bool DynTopo::apply(Mesh& m, BVH& bvh, const Vec3& center, float radius, const DynTopoSettings& s) {
    if (!s.enabled) return false;
    float L = s.relativeDetail ? radius * s.detail : s.constantDetail;
    if (L <= 0) return false;
    float hi2 = (4.0f / 3.0f * L) * (4.0f / 3.0f * L);
    float lo2 = (4.0f / 5.0f * L) * (4.0f / 5.0f * L);
    float r2 = radius * radius;
    int budget = s.maxOpsPerDab;
    bool changed = false;
    std::vector<int> tris;
    std::vector<std::pair<float, uint64_t>> cand;
    size_t trisBefore = m.tris.size();
    // Only triangles in the queried region change, plus the ones appended by
    // splits: refit just those (full refit costs ~30 ms on 1M triangles).
    // Faces incident to an edited edge can poke slightly past the brush
    // sphere, so re-query with a margin of two detail lengths (boxes there are
    // stale but still enclose the old positions, which is all the query needs).
    std::vector<int> region;
    auto refitRegion = [&](Mesh& mm, BVH& b, const std::vector<int>&, size_t before) {
        b.queryTris(center, radius + 3.0f * L, region);
        for (size_t t = before; t < mm.tris.size(); ++t) region.push_back((int)t);
        b.refitTris(mm, region);
    };

    auto gather = [&](bool longEdges) {
        bvh.queryTris(center, radius, tris);
        cand.clear();
        for (int t : tris) {
            const Tri& f = m.tris[t];
            if (f[0] < 0) continue;
            for (int k = 0; k < 3; ++k) {
                int a = f[k], b = f[(k + 1) % 3];
                if (a > b) continue;  // each interior edge once (boundary edges seen from one side only)
                Vec3 mid = (m.positions[a] + m.positions[b]) * 0.5f;
                if (length2(mid - center) > r2) continue;
                float l2 = length2(m.positions[a] - m.positions[b]);
                if (longEdges ? l2 > hi2 : l2 < lo2) cand.push_back({l2, key(a, b)});
            }
        }
        if (longEdges) std::sort(cand.begin(), cand.end(), [](auto& x, auto& y) { return x.first > y.first; });
        else std::sort(cand.begin(), cand.end());
        cand.erase(std::unique(cand.begin(), cand.end()), cand.end());
    };

    // Splits: a few passes because a split leaves the two side edges as long as before.
    for (int pass = 0; pass < 4 && budget > 0; ++pass) {
        gather(true);
        if (cand.empty()) break;
        int done = 0;
        for (auto& c : cand) {
            if (budget-- <= 0) break;
            int a = (int)(c.second >> 32), b = (int)(c.second & 0xffffffffu);
            if (length2(m.positions[a] - m.positions[b]) <= hi2) continue;
            if (split(m, a, b)) ++done;
        }
        if (!done) break;
        changed = true;
        refitRegion(m, bvh, tris, trisBefore);
    }

    if (s.allowCollapse && budget > 0) {
        gather(false);
        int done = 0;
        for (auto& c : cand) {
            if (budget-- <= 0) break;
            int a = (int)(c.second >> 32), b = (int)(c.second & 0xffffffffu);
            if (m.vertTris[a].empty() || m.vertTris[b].empty()) continue;
            if (length2(m.positions[a] - m.positions[b]) >= lo2) continue;
            // New edges must not exceed the split threshold (prevents split/collapse ping-pong).
            Vec3 p = (m.positions[a] + m.positions[b]) * 0.5f;
            bool ok = true;
            for (int x : m.vertNbrs[a]) if (x != b && length2(m.positions[x] - p) > hi2) { ok = false; break; }
            if (ok) for (int x : m.vertNbrs[b]) if (x != a && length2(m.positions[x] - p) > hi2) { ok = false; break; }
            if (ok && collapse(m, a, b)) ++done;
        }
        if (done) { changed = true; refitRegion(m, bvh, tris, trisBefore); }
    }

    if (changed) {
        // Flips: Delaunay criterion (angles opposite the edge sum > 180 deg)
        // removes the slivers splits leave behind; without it, splitting
        // slivers made fans of ever smaller slivers (25k triangles at 1/7 the
        // target size under one Crease stroke). Then one tangential relax of
        // the region (Botsch & Kobbelt step 4) evens the new vertices out.
        auto oppAngle = [&](int v, int x, int y) {
            Vec3 u = m.positions[x] - m.positions[v], w = m.positions[y] - m.positions[v];
            float lu = length(u), lw = length(w);
            if (lu < 1e-12f || lw < 1e-12f) return 3.14159265f;
            return std::acos(std::max(-1.0f, std::min(1.0f, dot(u, w) / (lu * lw))));
        };
        for (int pass = 0; pass < 2 && budget > 0; ++pass) {
            bvh.queryTris(center, radius, tris);
            int done = 0;
            for (int t : tris) {
                if (budget <= 0) break;
                const Tri f = m.tris[t];
                if (f[0] < 0) continue;
                for (int k = 0; k < 3; ++k) {
                    int a = f[k], b = f[(k + 1) % 3], c = f[(k + 2) % 3];
                    if (a > b) continue;
                    if (length2((m.positions[a] + m.positions[b]) * 0.5f - center) > r2) continue;
                    auto e = edges_.find(key(a, b));
                    if (e == edges_.end() || e->second.f1 < 0) continue;
                    int other = e->second.f0 == t ? e->second.f1 : e->second.f0;
                    int d = -1;
                    for (int v : m.tris[other]) if (v != a && v != b) d = v;
                    if (d < 0) continue;
                    if (oppAngle(c, a, b) + oppAngle(d, a, b) <= 3.14159265f + 1e-3f) continue;
                    --budget;
                    if (flip(m, a, b)) { ++done; break; }  // t changed: next triangle
                }
            }
            if (!done) break;
            refitRegion(m, bvh, tris, trisBefore);
        }
        {
            std::vector<int> vs;
            bvh.queryTris(center, radius, tris);
            for (int t : tris) if (m.tris[t][0] >= 0) for (int v : m.tris[t]) vs.push_back(v);
            std::sort(vs.begin(), vs.end());
            vs.erase(std::unique(vs.begin(), vs.end()), vs.end());
            std::vector<Vec3> np(vs.size());
            for (size_t i = 0; i < vs.size(); ++i) {
                int v = vs[i];
                const auto& nb = m.vertNbrs[v];
                if (nb.size() < 3 || length2(m.positions[v] - center) > r2) { np[i] = m.positions[v]; continue; }
                Vec3 avg{};
                for (int x : nb) avg += m.positions[x];
                Vec3 L3 = avg / (float)nb.size() - m.positions[v];
                Vec3 n = m.normals[v];
                np[i] = m.positions[v] + (L3 - n * dot(L3, n)) * 0.5f;
            }
            for (size_t i = 0; i < vs.size(); ++i) m.positions[vs[i]] = np[i];
            refitRegion(m, bvh, tris, trisBefore);
        }
        // Refresh normals in the remeshed area.
        bvh.queryTris(center, radius * 1.1f, tris);
        std::vector<int> vs;
        for (int t : tris) if (m.tris[t][0] >= 0) for (int v : m.tris[t]) vs.push_back(v);
        std::sort(vs.begin(), vs.end());
        vs.erase(std::unique(vs.begin(), vs.end()), vs.end());
        m.computeNormals(vs);
    }
    return changed;
}

void DynTopo::compact(Mesh& m) {
    std::vector<int> remap(m.positions.size(), -1);
    int nv = 0;
    for (const Tri& f : m.tris)
        if (f[0] >= 0) for (int v : f) if (remap[v] < 0) remap[v] = 0;
    for (size_t v = 0; v < remap.size(); ++v) if (remap[v] == 0) remap[v] = nv++;
    Mesh out;
    out.positions.resize(nv);
    out.normals.resize(nv);
    out.mask.resize(nv);
    out.color.resize(nv);
    for (size_t v = 0; v < remap.size(); ++v) {
        int r = remap[v];
        if (r < 0) continue;
        out.positions[r] = m.positions[v];
        out.normals[r] = m.normals[v];
        out.mask[r] = m.mask[v];
        out.color[r] = m.color[v];
    }
    const bool tagged = m.triPoly.size() == m.tris.size();
    for (size_t t = 0; t < m.tris.size(); ++t) {
        const Tri& f = m.tris[t];
        if (f[0] < 0) continue;
        out.tris.push_back({remap[f[0]], remap[f[1]], remap[f[2]]});
        if (tagged) out.triPoly.push_back(m.triPoly[t]);
    }
    // keep the source polygons (renumbered) so untouched ones write back as quads
    out.polyCounts = m.polyCounts;
    out.polyTriCount = m.polyTriCount;
    out.polyIndices.resize(m.polyIndices.size());
    for (size_t i = 0; i < m.polyIndices.size(); ++i) {
        int v = m.polyIndices[i];
        out.polyIndices[i] = (v >= 0 && v < (int)remap.size()) ? remap[v] : -1;
    }
    out.topologyFromHost = false;
    out.buildAdjacency();
    m = std::move(out);
}

}  // namespace sculpt
