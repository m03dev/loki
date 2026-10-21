#include "sculpt/quad_remesh.h"
#include "sculpt/bvh.h"
#include "sculpt/dyntopo.h"
#include "sculpt/parallel.h"
#include "sculpt/voxel_remesh.h"
#include <algorithm>
#include <unordered_map>

namespace sculpt {

static float surfaceArea(const Mesh& m) {
    double a = 0;
    for (int t = 0; t < (int)m.tris.size(); ++t)
        if (m.tris[t][0] >= 0) a += 0.5 * length(m.triNormal(t));
    return (float)a;
}

static void projectToSource(Mesh& m, const Mesh& src, const BVH& srcBvh, float searchR, bool color) {
    bool hasColor = color && src.color.size() == src.positions.size();
    parallelFor((int)m.positions.size(), [&](int v) {
        thread_local std::vector<int> tris;
        Vec3 p = m.positions[v];
        srcBvh.queryTris(p, searchR, tris);
        float best = 1e30f;
        Vec3 bq = p, bc = m.color.empty() ? Vec3{} : m.color[v];
        for (int t : tris) {
            const Tri& f = src.tris[t];
            float u, w;
            Vec3 q = closestPointOnTriangle(p, src.positions[f[0]], src.positions[f[1]], src.positions[f[2]], u, w);
            float d = length2(q - p);
            if (d < best) {
                best = d;
                bq = q;
                if (hasColor) bc = src.color[f[0]] * (1 - u - w) + src.color[f[1]] * u + src.color[f[2]] * w;
            }
        }
        m.positions[v] = bq;
        if (hasColor) m.color[v] = bc;
    });
}

Mesh isotropicRemesh(const Mesh& source, float L, int iterations) {
    Mesh src = source;
    src.ensureAttributes();
    src.computeNormals();
    BVH srcBvh;
    srcBvh.build(src);
    Mesh m = src;
    m.buildAdjacency();
    AABB bb = m.bounds();
    float R = length(bb.extent()) + 1.0f;
    for (int it = 0; it < iterations; ++it) {
        BVH bvh;
        bvh.build(m);
        DynTopo dt;
        dt.attach(m);
        DynTopoSettings s;
        s.enabled = true;
        s.relativeDetail = false;
        s.constantDetail = L;
        s.maxOpsPerDab = 1 << 30;
        dt.apply(m, bvh, bb.center(), R, s);
        DynTopo::compact(m);
        m.ensureAttributes();
        m.computeNormals();
        // Tangential relax (Botsch & Kobbelt step 4)
        std::vector<Vec3> tmp(m.positions.size());
        parallelFor((int)m.positions.size(), [&](int v) {
            const auto& nb = m.vertNbrs[v];
            if (nb.empty()) { tmp[v] = m.positions[v]; return; }
            Vec3 avg{};
            for (int n : nb) avg += m.positions[n];
            tmp[v] = m.positions[v] + projectOnPlane(avg / (float)nb.size() - m.positions[v], m.normals[v]) * 0.8f;
        });
        m.positions.swap(tmp);
        projectToSource(m, src, srcBvh, L * 2.0f, true);
        m.computeNormals();
    }
    return m;
}

QuadRemeshResult quadRemesh(const Mesh& source, const QuadRemeshSettings& s) {
    QuadRemeshResult res;
    float area = surfaceArea(source);
    int F = std::max(10, s.targetFaces);
    // F quads -> 2F triangles; equilateral edge for area A/(2F): l = sqrt(2A / (sqrt(3) F))
    float L = std::sqrt(2.0f * area / (1.7320508f * F));
    Mesh m = isotropicRemesh(source, L, s.iterations);

    // Greedy pairing.
    struct Cand { float q; int t0, t1, a, b; };
    std::unordered_map<uint64_t, std::pair<int, int>> edgeFaces;
    auto key = [](int a, int b) { if (a > b) std::swap(a, b); return ((uint64_t)(uint32_t)a << 32) | (uint32_t)b; };
    for (int t = 0; t < (int)m.tris.size(); ++t)
        for (int k = 0; k < 3; ++k) {
            auto& e = edgeFaces[key(m.tris[t][k], m.tris[t][(k + 1) % 3])];
            if (e.first == 0 && e.second == 0) e = {t + 1, 0};
            else e.second = t + 1;
        }
    auto corner = [&](int prev, int cur, int next) {
        Vec3 u = normalize(m.positions[prev] - m.positions[cur]), w = normalize(m.positions[next] - m.positions[cur]);
        return std::fabs(dot(u, w));  // |cos|: 0 at 90 degrees
    };
    std::vector<Cand> cand;
    for (auto& kv : edgeFaces) {
        if (!kv.second.second) continue;
        int t0 = kv.second.first - 1, t1 = kv.second.second - 1;
        int a = (int)(kv.first >> 32), b = (int)(kv.first & 0xffffffffu);
        // orient: t0 contains a->b
        const Tri& f0 = m.tris[t0];
        bool ab = false;
        for (int k = 0; k < 3; ++k) if (f0[k] == a && f0[(k + 1) % 3] == b) ab = true;
        if (!ab) std::swap(a, b);
        int c = -1, d = -1;
        for (int v : m.tris[t0]) if (v != a && v != b) c = v;
        for (int v : m.tris[t1]) if (v != a && v != b) d = v;
        // quad loop a -> d -> b -> c
        float worst = std::max(std::max(corner(c, a, d), corner(a, d, b)), std::max(corner(d, b, c), corner(b, c, a)));
        float planar = dot(normalize(m.triNormal(t0)), normalize(m.triNormal(t1)));
        float q = (1 - worst) * std::max(0.0f, planar);
        if (q >= s.minQuadQuality) cand.push_back({q, t0, t1, a, b});
    }
    std::sort(cand.begin(), cand.end(), [](const Cand& x, const Cand& y) { return x.q > y.q; });
    const int nt = (int)m.tris.size();
    std::vector<int> mate(nt, -1);
    for (auto& c : cand) {
        if (mate[c.t0] >= 0 || mate[c.t1] >= 0) continue;
        mate[c.t0] = c.t1;
        mate[c.t1] = c.t0;
    }
    // Triangle adjacency limited to acceptable pairs.
    std::vector<std::vector<int>> adj(nt);
    for (auto& c : cand) { adj[c.t0].push_back(c.t1); adj[c.t1].push_back(c.t0); }
    // Augmenting paths (alternating BFS, bounded depth): an orphan steals a
    // partner whose old mate can re-pair with another orphan or further along.
    // Classic matching repair; turns most leftover triangles into quads.
    for (int pass = 0; pass < 3; ++pass) {
        bool any = false;
        for (int t = 0; t < nt; ++t) {
            if (mate[t] >= 0) continue;
            // BFS over alternating paths up to length 7
            std::vector<std::pair<int, int>> prev;   // (node, parentIndex) for matched-hop nodes
            std::vector<int> frontier{t};
            std::unordered_map<int, int> from;      // tri reached via unmatched edge -> previous tri
            from[t] = -1;
            int found = -1;
            for (int depth = 0; depth < 4 && found < 0 && !frontier.empty(); ++depth) {
                std::vector<int> next;
                for (int x : frontier) {
                    for (int y : adj[x]) {
                        if (from.count(y)) continue;
                        from[y] = x;
                        if (mate[y] < 0) { found = y; break; }
                        int z = mate[y];
                        if (from.count(z)) continue;
                        from[z] = y;
                        next.push_back(z);
                    }
                    if (found >= 0) break;
                }
                frontier.swap(next);
            }
            if (found < 0) continue;
            // Flip the path: walk back pairing (y, from[y]).
            int y = found;
            while (y >= 0) {
                int x = from[y];
                int nextY = (x >= 0 && x != t) ? from[x] : -1;
                mate[y] = x;
                mate[x] = y;
                if (x == t) break;
                y = nextY;
            }
            any = true;
        }
        if (!any) break;
    }
    m.polyCounts.clear();
    m.polyIndices.clear();
    auto shared = [&](int t0, int t1, int& a, int& b) {
        // directed edge a->b of t0 that also lies in t1
        for (int k = 0; k < 3; ++k) {
            int u = m.tris[t0][k], w = m.tris[t0][(k + 1) % 3];
            for (int j = 0; j < 3; ++j)
                if (m.tris[t1][j] == w && m.tris[t1][(j + 1) % 3] == u) { a = u; b = w; return true; }
        }
        return false;
    };
    for (int t = 0; t < nt; ++t) {
        int o = mate[t];
        if (o >= 0 && o < t) continue;
        int a, b;
        if (o >= 0 && shared(t, o, a, b)) {
            int cc = -1, dd = -1;
            for (int v : m.tris[t]) if (v != a && v != b) cc = v;
            for (int v : m.tris[o]) if (v != a && v != b) dd = v;
            m.polyCounts.push_back(4);
            m.polyIndices.insert(m.polyIndices.end(), {a, dd, b, cc});
            ++res.quads;
        } else {
            m.polyCounts.push_back(3);
            m.polyIndices.insert(m.polyIndices.end(), {m.tris[t][0], m.tris[t][1], m.tris[t][2]});
            ++res.tris;
            if (o >= 0) {  // shouldn't happen, keep partner as a triangle too
                m.polyCounts.push_back(3);
                m.polyIndices.insert(m.polyIndices.end(), {m.tris[o][0], m.tris[o][1], m.tris[o][2]});
                ++res.tris;
            }
        }
    }
    m.topologyFromHost = false;
    res.mesh = std::move(m);
    return res;
}

}  // namespace sculpt
