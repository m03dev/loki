#include "sculpt/mesh.h"
#include "sculpt/parallel.h"
#include <algorithm>
#include <map>
#include <unordered_map>

namespace sculpt {

void Mesh::ensureAttributes() {
    size_t n = positions.size();
    if (mask.size() != n) mask.resize(n, 0.0f);
    if (color.size() != n) color.resize(n, Vec3{0.8f, 0.8f, 0.8f});
    if (normals.size() != n) normals.resize(n, Vec3{0, 1, 0});
}

void Mesh::buildAdjacency() {
    size_t n = positions.size();
    vertTris.assign(n, {});
    vertNbrs.assign(n, {});
    {   // exact sizes first: one allocation per vertex instead of realloc churn
        std::vector<int> deg(n, 0);
        for (const Tri& f : tris)
            if (f[0] >= 0) for (int k = 0; k < 3; ++k) ++deg[f[k]];
        for (size_t v = 0; v < n; ++v) {
            vertTris[v].reserve(deg[v]);
            vertNbrs[v].reserve(2 * deg[v]);
        }
    }
    for (int t = 0; t < (int)tris.size(); ++t) {
        const Tri& f = tris[t];
        if (f[0] < 0) continue;  // tombstoned
        for (int k = 0; k < 3; ++k) {
            vertTris[f[k]].push_back(t);
            vertNbrs[f[k]].push_back(f[(k + 1) % 3]);
            vertNbrs[f[k]].push_back(f[(k + 2) % 3]);
        }
    }
    parallelFor((int)n, [&](int v) {
        auto& nb = vertNbrs[v];
        std::sort(nb.begin(), nb.end());
        nb.erase(std::unique(nb.begin(), nb.end()), nb.end());
    }, 16384);
}


void Mesh::computeNormals() {
    normals.assign(positions.size(), Vec3{0, 0, 0});
    for (int t = 0; t < (int)tris.size(); ++t) {
        if (tris[t][0] < 0) continue;
        Vec3 n = triNormal(t);  // area weighting falls out of the cross product length
        for (int k = 0; k < 3; ++k) normals[tris[t][k]] += n;
    }
    for (auto& n : normals) n = normalize(n);
}

void Mesh::computeNormals(const std::vector<int>& verts) {
    for (int v : verts) {
        Vec3 n{0, 0, 0};
        for (int t : vertTris[v]) n += triNormal(t);
        normals[v] = normalize(n);
    }
}

AABB Mesh::bounds() const {
    AABB b;
    for (const auto& p : positions) b.expand(p);
    return b;
}

Mesh Mesh::fromPolygons(const std::vector<Vec3>& pts, const std::vector<int>& counts,
                        const std::vector<int>& indices) {
    Mesh m;
    m.positions = pts;
    m.polyCounts = counts;
    m.polyIndices = indices;
    m.topologyFromHost = true;
    size_t off = 0;
    m.polyTriCount.assign(counts.size(), 0);
    for (size_t p = 0; p < counts.size(); ++p) {
        int c = counts[p];
        for (int k = 1; k + 1 < c; ++k) {
            m.tris.push_back({indices[off], indices[off + k], indices[off + k + 1]});
            m.triPoly.push_back((int)p);
            ++m.polyTriCount[p];
        }
        off += c;
    }
    m.ensureAttributes();
    m.buildAdjacency();
    m.computeNormals();
    return m;
}

Mesh Mesh::icosphere(int subdivisions, float radius) {
    Mesh m;
    const float t = (1.0f + std::sqrt(5.0f)) * 0.5f;
    std::vector<Vec3> p = {{-1, t, 0}, {1, t, 0}, {-1, -t, 0}, {1, -t, 0}, {0, -1, t}, {0, 1, t},
                           {0, -1, -t}, {0, 1, -t}, {t, 0, -1}, {t, 0, 1}, {-t, 0, -1}, {-t, 0, 1}};
    std::vector<Tri> f = {{0, 11, 5}, {0, 5, 1},  {0, 1, 7},   {0, 7, 10}, {0, 10, 11},
                          {1, 5, 9},  {5, 11, 4}, {11, 10, 2}, {10, 7, 6}, {7, 1, 8},
                          {3, 9, 4},  {3, 4, 2},  {3, 2, 6},   {3, 6, 8},  {3, 8, 9},
                          {4, 9, 5},  {2, 4, 11}, {6, 2, 10},  {8, 6, 7},  {9, 8, 1}};
    for (auto& v : p) v = normalize(v);
    for (int s = 0; s < subdivisions; ++s) {
        std::map<std::pair<int, int>, int> mid;
        auto midpoint = [&](int a, int b) {
            auto key = std::minmax(a, b);
            auto it = mid.find(key);
            if (it != mid.end()) return it->second;
            p.push_back(normalize((p[a] + p[b]) * 0.5f));
            return mid[key] = (int)p.size() - 1;
        };
        std::vector<Tri> nf;
        nf.reserve(f.size() * 4);
        for (auto& tri : f) {
            int a = midpoint(tri[0], tri[1]), b = midpoint(tri[1], tri[2]), c = midpoint(tri[2], tri[0]);
            nf.push_back({tri[0], a, c});
            nf.push_back({tri[1], b, a});
            nf.push_back({tri[2], c, b});
            nf.push_back({a, b, c});
        }
        f.swap(nf);
    }
    for (auto& v : p) v *= radius;
    m.positions = p;
    m.tris = f;
    m.ensureAttributes();
    m.buildAdjacency();
    m.computeNormals();
    return m;
}

Mesh Mesh::box(float size, int seg) {
    // Six grid faces welded by position key.
    Mesh m;
    std::unordered_map<long long, int> weld;
    auto key = [&](int i, int j, int k) { return ((long long)i * 4096 + j) * 4096 + k; };
    auto vert = [&](int i, int j, int k) {
        long long kk = key(i, j, k);
        auto it = weld.find(kk);
        if (it != weld.end()) return it->second;
        float s = size / seg;
        m.positions.push_back({i * s - size * 0.5f, j * s - size * 0.5f, k * s - size * 0.5f});
        return weld[kk] = (int)m.positions.size() - 1;
    };
    auto quad = [&](int a, int b, int c, int d) {
        m.tris.push_back({a, b, c});
        m.tris.push_back({a, c, d});
    };
    for (int a = 0; a < seg; ++a)
        for (int b = 0; b < seg; ++b) {
            // -X / +X
            quad(vert(0, a, b), vert(0, a, b + 1), vert(0, a + 1, b + 1), vert(0, a + 1, b));
            quad(vert(seg, a, b), vert(seg, a + 1, b), vert(seg, a + 1, b + 1), vert(seg, a, b + 1));
            // -Y / +Y
            quad(vert(a, 0, b), vert(a + 1, 0, b), vert(a + 1, 0, b + 1), vert(a, 0, b + 1));
            quad(vert(a, seg, b), vert(a, seg, b + 1), vert(a + 1, seg, b + 1), vert(a + 1, seg, b));
            // -Z / +Z
            quad(vert(a, b, 0), vert(a, b + 1, 0), vert(a + 1, b + 1, 0), vert(a + 1, b, 0));
            quad(vert(a, b, seg), vert(a + 1, b, seg), vert(a + 1, b + 1, seg), vert(a, b + 1, seg));
        }
    m.ensureAttributes();
    m.buildAdjacency();
    m.computeNormals();
    return m;
}

}  // namespace sculpt

namespace sculpt {

void Mesh::hybridPolygons(std::vector<int>& counts, std::vector<int>& indices) const {
    counts.clear();
    indices.clear();
    const bool tagged = triPoly.size() == tris.size() && polyTriCount.size() == polyCounts.size() && !polyCounts.empty();
    std::vector<int> live;
    if (tagged) {
        live.assign(polyCounts.size(), 0);
        for (size_t t = 0; t < tris.size(); ++t)
            if (tris[t][0] >= 0 && triPoly[t] >= 0) ++live[triPoly[t]];
        size_t off = 0;
        for (size_t p = 0; p < polyCounts.size(); ++p) {
            int c = polyCounts[p];
            bool intact = polyTriCount[p] > 0 && live[p] == polyTriCount[p];
            for (int k = 0; k < c && intact; ++k) intact = polyIndices[off + k] >= 0;
            if (intact) {
                counts.push_back(c);
                indices.insert(indices.end(), polyIndices.begin() + off, polyIndices.begin() + off + c);
            } else {
                live[p] = -1;  // mark: its surviving triangles go out loose
            }
            off += c;
        }
    }
    for (size_t t = 0; t < tris.size(); ++t) {
        const Tri& f = tris[t];
        if (f[0] < 0) continue;
        if (tagged && triPoly[t] >= 0 && live[triPoly[t]] >= 0) continue;  // inside an intact polygon
        counts.push_back(3);
        indices.insert(indices.end(), f.begin(), f.end());
    }
}

}  // namespace sculpt

namespace sculpt {

void Mesh::cavity(std::vector<float>& out) const {
    const size_t n = positions.size();
    out.assign(n, 0.0f);
    if (vertNbrs.size() != n || normals.size() != n) return;
    std::vector<float> c(n, 0.0f), pos;
    for (size_t v = 0; v < n; ++v) {
        const auto& nb = vertNbrs[v];
        if (nb.empty()) continue;
        Vec3 avg{};
        float el = 0;
        for (int j : nb) { avg += positions[j]; el += length(positions[j] - positions[v]); }
        avg = avg / (float)nb.size();
        el /= (float)nb.size();
        if (el <= 0) continue;
        c[v] = dot(avg - positions[v], normals[v]) / el;  // > 0: concave (cavity)
        if (c[v] > 0) pos.push_back(c[v]);
    }
    if (pos.empty()) return;
    size_t k = std::min(pos.size() - 1, (size_t)(pos.size() * 0.95));
    std::nth_element(pos.begin(), pos.begin() + k, pos.end());
    float scale = pos[k] > 0 ? 1.0f / pos[k] : 1.0f;
    for (size_t v = 0; v < n; ++v) {
        float x = std::max(0.0f, std::min(1.0f, c[v] * scale));
        out[v] = x * x * (3 - 2 * x);
    }
}

}  // namespace sculpt
