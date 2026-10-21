#include "sculpt/bvh.h"
#include <memory>
#include <atomic>
#include "sculpt/voxel_remesh.h"
#include "sculpt/parallel.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <unordered_map>

namespace sculpt {

Vec3 closestPointOnTriangle(const Vec3& p, const Vec3& a, const Vec3& b, const Vec3& c, float& u, float& v) {
    Vec3 ab = b - a, ac = c - a, ap = p - a;
    float d1 = dot(ab, ap), d2 = dot(ac, ap);
    if (d1 <= 0 && d2 <= 0) { u = 0; v = 0; return a; }
    Vec3 bp = p - b;
    float d3 = dot(ab, bp), d4 = dot(ac, bp);
    if (d3 >= 0 && d4 <= d3) { u = 1; v = 0; return b; }
    float vc = d1 * d4 - d3 * d2;
    if (vc <= 0 && d1 >= 0 && d3 <= 0) {
        float t = d1 / (d1 - d3);
        u = t; v = 0;
        return a + ab * t;
    }
    Vec3 cp = p - c;
    float d5 = dot(ab, cp), d6 = dot(ac, cp);
    if (d6 >= 0 && d5 <= d6) { u = 0; v = 1; return c; }
    float vb = d5 * d2 - d1 * d6;
    if (vb <= 0 && d2 >= 0 && d6 <= 0) {
        float t = d2 / (d2 - d6);
        u = 0; v = t;
        return a + ac * t;
    }
    float va = d3 * d6 - d5 * d4;
    if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
        float t = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        u = 1 - t; v = t;
        return b + (c - b) * t;
    }
    float denom = 1.0f / (va + vb + vc);
    u = vb * denom;
    v = vc * denom;
    return a + ab * u + ac * v;
}

float signedVolume(const Mesh& m) {
    double vol = 0;
    for (const Tri& f : m.tris) {
        if (f[0] < 0) continue;
        vol += dot(m.positions[f[0]], cross(m.positions[f[1]], m.positions[f[2]]));
    }
    return (float)(vol / 6.0);
}

// Surface Nets is non-manifold where two sign-changing grid edges lie on one
// cell face (ambiguous face) or a feature is thinner than a voxel: an edge then
// borders 4 quads and a vertex joins two separate surface sheets. Fix: for each
// vertex, group its incident quads into fans connected through *manifold*
// edges (exactly 2 uses) incident to it, and give every extra fan its own copy
// of the vertex. Afterwards every edge is used exactly twice.
// Each quad corner (q, k) is a node of a union-find. Across every edge we
// join the corners of the quads that belong to the same surface sheet:
//  * edge used by 2 quads: join them;
//  * edge used by 4 quads: sort them by angle around the edge and join
//    neighbours with opposite winding (one pair per sheet).
// Corners of one vertex that end up in different sets lie on different
// sheets (or a bowtie): each extra set gets its own copy of the vertex.
// Sort-based, no hash maps: ~10x faster than the first version.
void splitNonManifold(Mesh& m, std::vector<int>* origin) {
    const size_t nq = m.polyCounts.size();
    if (!nq) return;
    std::vector<int>& P = m.polyIndices;
    struct E { uint64_t key; int corner; };  // corner = q*4+k, edge k -> k+1
    std::vector<E> edges(nq * 4);
    for (size_t q = 0; q < nq; ++q)
        for (int k = 0; k < 4; ++k) {
            int a = P[q * 4 + k], b = P[q * 4 + (k + 1) % 4];
            if (a > b) std::swap(a, b);
            edges[q * 4 + k] = {((uint64_t)(uint32_t)a << 32) | (uint32_t)b, (int)(q * 4 + k)};
        }
    std::sort(edges.begin(), edges.end(), [](const E& x, const E& y) { return x.key < y.key; });

    std::vector<int> par(nq * 4);
    for (size_t i = 0; i < par.size(); ++i) par[i] = (int)i;
    auto find = [&](int x) {
        while (par[x] != x) { par[x] = par[par[x]]; x = par[x]; }
        return x;
    };
    auto unite = [&](int x, int y) { x = find(x); y = find(y); if (x != y) par[x] = y; };
    auto cornerOf = [&](int q, int v) {  // corner index of vertex v in quad q
        for (int k = 0; k < 4; ++k) if (P[(size_t)q * 4 + k] == v) return q * 4 + k;
        return -1;
    };
    auto centroid = [&](int q) {
        Vec3 c{};
        for (int k = 0; k < 4; ++k) c += m.positions[P[(size_t)q * 4 + k]];
        return c * 0.25f;
    };
    auto join = [&](int qa, int qb, int a, int b) {
        int ca = cornerOf(qa, a), cb = cornerOf(qb, a);
        if (ca >= 0 && cb >= 0) unite(ca, cb);
        ca = cornerOf(qa, b); cb = cornerOf(qb, b);
        if (ca >= 0 && cb >= 0) unite(ca, cb);
    };
    // Corners of the same vertex inside one quad are already one node; also
    // join the two corners of an edge *within* a quad? No: a vertex appears once
    // per quad, so nothing to do there.
    for (size_t i = 0; i < edges.size();) {
        size_t j = i;
        while (j < edges.size() && edges[j].key == edges[i].key) ++j;
        size_t n = j - i;
        int a = (int)(edges[i].key >> 32), b = (int)(edges[i].key & 0xffffffffu);
        if (n == 2) {
            join(edges[i].corner / 4, edges[i + 1].corner / 4, a, b);
        } else if (n == 4) {
            Vec3 pa = m.positions[a], e = normalize(m.positions[b] - pa);
            int qs[4];
            for (int t = 0; t < 4; ++t) qs[t] = edges[i + t].corner / 4;
            Vec3 u = normalize(projectOnPlane(centroid(qs[0]) - pa, e)), w = cross(e, u);
            std::pair<float, int> ang[4];
            for (int t = 0; t < 4; ++t) {
                Vec3 d = projectOnPlane(centroid(qs[t]) - pa, e);
                ang[t] = {std::atan2(dot(d, w), dot(d, u)), qs[t]};
            }
            std::sort(ang, ang + 4);
            auto fwd = [&](int q) {  // quad q traverses a -> b
                int k = cornerOf(q, a) - q * 4;
                return P[(size_t)q * 4 + (k + 1) % 4] == b;
            };
            int st = fwd(ang[0].second) != fwd(ang[1].second) ? 0 : 1;
            join(ang[st].second, ang[(st + 1) % 4].second, a, b);
            join(ang[(st + 2) % 4].second, ang[(st + 3) % 4].second, a, b);
        }
        i = j;
    }
    // Assign vertex copies: the first set seen for a vertex keeps its index.
    const size_t nv0 = m.positions.size();
    std::vector<int> firstRoot(nv0, -1);
    std::vector<std::pair<int, int>> extra;  // (root, newVertex) per original vertex, small
    std::vector<int> extraHead(nv0, -1), extraNext;
    for (size_t c = 0; c < P.size(); ++c) {
        int v = P[c];
        if ((size_t)v >= nv0) continue;
        int r = find((int)c);
        if (firstRoot[v] < 0) { firstRoot[v] = r; continue; }
        if (firstRoot[v] == r) continue;
        int nvtx = -1;
        for (int e = extraHead[v]; e >= 0; e = extraNext[e])
            if (extra[e].first == r) { nvtx = extra[e].second; break; }
        if (nvtx < 0) {
            nvtx = (int)m.positions.size();
            m.positions.push_back(m.positions[v]);
            if (origin) origin->push_back(v);
            extra.push_back({r, nvtx});
            extraNext.push_back(extraHead[v]);
            extraHead[v] = (int)extra.size() - 1;
        }
        P[c] = nvtx;
    }
}

VoxelRemeshResult voxelRemesh(const Mesh& src, const VoxelRemeshSettings& s) {
    VoxelRemeshResult res;
    const bool prof = getenv("SCULPT_PROFILE") != nullptr;
    auto tp = std::chrono::steady_clock::now();
    auto lap = [&](const char* what) {
        if (!prof) return;
        auto now = std::chrono::steady_clock::now();
        fprintf(stderr, "  %-22s %7.1f ms\n", what, std::chrono::duration<double, std::milli>(now - tp).count());
        tp = now;
    };
    AABB bb = src.bounds();
    if (!bb.valid() || src.tris.empty()) return res;
    Vec3 ext = bb.extent();
    float longest = std::max(ext.x, std::max(ext.y, ext.z));
    float h = s.voxelSize > 0 ? s.voxelSize : longest / std::max(8, s.resolution);
    const float band = 1.75f * h;
    Vec3 o = bb.lo - Vec3{h, h, h} * 3.0f;
    int nx = (int)std::ceil((ext.x + 6 * h) / h) + 1;
    int ny = (int)std::ceil((ext.y + 6 * h) / h) + 1;
    int nz = (int)std::ceil((ext.z + 6 * h) / h) + 1;
    res.gridX = nx; res.gridY = ny; res.gridZ = nz; res.voxelSize = h;
    const size_t N = (size_t)nx * ny * nz;
    auto idx = [&](int i, int j, int k) { return ((size_t)k * ny + j) * nx + i; };
    auto pt = [&](int i, int j, int k) { return o + Vec3{(float)i, (float)j, (float)k} * h; };

    // Connected components of the input (union-find over triangle vertices).
    // Each closed part gets its own signed field; the union is min() over the
    // parts (exact CSG union of signed distance fields). Doing the flood fill on
    // all parts at once would leak through the seams where parts intersect.
    std::vector<int> parent(src.positions.size());
    for (size_t v = 0; v < parent.size(); ++v) parent[v] = (int)v;
    auto findRoot = [&](int v) {
        while (parent[v] != v) { parent[v] = parent[parent[v]]; v = parent[v]; }
        return v;
    };
    for (const Tri& f : src.tris) {
        if (f[0] < 0) continue;
        int a = findRoot(f[0]);
        for (int k = 1; k < 3; ++k) { int b = findRoot(f[k]); if (a != b) parent[b] = a; }
    }
    std::vector<int> compOfTri(src.tris.size(), -1);
    std::vector<int> rootToComp(src.positions.size(), -1);
    int ncomp = 0;
    for (size_t t = 0; t < src.tris.size(); ++t) {
        if (src.tris[t][0] < 0) continue;
        int r = findRoot(src.tris[t][0]);
        if (rootToComp[r] < 0) rootToComp[r] = ncomp++;
        compOfTri[t] = rootToComp[r];
    }

    std::vector<float> field(N, band);       // union signed field
    std::vector<float> bestDist(N, band);    // global unsigned distance (for projection)
    std::vector<int> closest(N, -1);         // global closest triangle
    std::vector<float> dist(N);
    std::vector<int> cclosest(N);
    std::vector<char> outsideHint(N), outside(N);
    std::vector<size_t> q;  // DFS stack (order doesn't matter for reachability)
    q.reserve(N / 8);
    const size_t sx = 1, sy = nx, sz = (size_t)nx * ny;

    for (int comp = 0; comp < ncomp; ++comp) {
        std::fill(dist.begin(), dist.end(), band);
        std::fill(cclosest.begin(), cclosest.end(), -1);
        std::fill(outsideHint.begin(), outsideHint.end(), 1);
        std::fill(outside.begin(), outside.end(), 0);

        // ---- 1. narrow-band unsigned distance + closest triangle
        // Parallel over z-slabs: each worker scans the triangles (cheap bounds
        // test) and writes only voxels in its own slab, so there are no races.
        // The comparison is strict (<) and triangles are visited in the same
        // order in every slab, so the result is identical to the serial loop.
        {
            const int slabs = std::max(1, std::min(nz, 64));
            parallelFor(slabs, [&](int sidx) {
                int zk0 = sidx * nz / slabs, zk1 = (sidx + 1) * nz / slabs - 1;
                for (int t = 0; t < (int)src.tris.size(); ++t) {
                    if (compOfTri[t] != comp) continue;
                    const Tri& f = src.tris[t];
                    const Vec3 &a = src.positions[f[0]], &b = src.positions[f[1]], &c = src.positions[f[2]];
                    float zlo = std::min(a.z, std::min(b.z, c.z)) - band, zhi = std::max(a.z, std::max(b.z, c.z)) + band;
                    int k0 = std::max(zk0, (int)std::floor((zlo - o.z) / h)), k1 = std::min(zk1, (int)std::ceil((zhi - o.z) / h));
                    if (k0 > k1) continue;
                    Vec3 lo = vmin(a, vmin(b, c)) - Vec3{band, band, band}, hi = vmax(a, vmax(b, c)) + Vec3{band, band, band};
                    int i0 = std::max(0, (int)std::floor((lo.x - o.x) / h)), i1 = std::min(nx - 1, (int)std::ceil((hi.x - o.x) / h));
                    int j0 = std::max(0, (int)std::floor((lo.y - o.y) / h)), j1 = std::min(ny - 1, (int)std::ceil((hi.y - o.y) / h));
                    for (int k = k0; k <= k1; ++k)
                        for (int j = j0; j <= j1; ++j)
                            for (int i = i0; i <= i1; ++i) {
                                Vec3 p = pt(i, j, k);
                                float u, v;
                                Vec3 qp = closestPointOnTriangle(p, a, b, c, u, v);
                                float d = length(p - qp);
                                size_t id = idx(i, j, k);
                                if (d < dist[id]) {
                                    dist[id] = d;
                                    cclosest[id] = t;
                                    // Pseudo-normal sign from interpolated vertex normals —
                                    // robust at edges/corners where the face normal is not.
                                    Vec3 n = src.normals[f[0]] * (1 - u - v) + src.normals[f[1]] * u + src.normals[f[2]] * v;
                                    outsideHint[id] = dot(p - qp, n) >= 0 ? 1 : 0;
                                }
                            }
                }
            }, 1);
        }

        // ---- 2. sign by flood fill from the border
        // Watertight wall: any 6-connected path of voxel centres that crosses
        // the (closed) surface has an endpoint within h/2 of it, so voxels with
        // d <= h/2 ("wall") block every leak. Phase A floods the non-wall
        // voxels from the border; unreached non-wall voxels are inside, however
        // wrong the normals are. Phase B extends the outside into wall voxels
        // whose pseudo-normal says outside, but only through wall voxels
        // connected to the phase-A region, so a wrong normal can neither leak
        // into the interior nor leave an isolated outside bubble.
        // (Pseudo-normal-only passability leaked through folds on sculpted
        // input: bogus inner shells + coincident vertices on re-voxel remesh.)
        const float wall = 0.5f * h;
        auto seedOk = [&](size_t id) { return dist[id] > wall; };
        auto expand = [&](bool intoWall) {
            while (!q.empty()) {
                size_t id = q.back();
                q.pop_back();
                int i = (int)(id % nx), j = (int)((id / nx) % ny), k = (int)(id / sz);
                size_t nb[6];
                int c = 0;
                if (i > 0) nb[c++] = id - sx;
                if (i < nx - 1) nb[c++] = id + sx;
                if (j > 0) nb[c++] = id - sy;
                if (j < ny - 1) nb[c++] = id + sy;
                if (k > 0) nb[c++] = id - sz;
                if (k < nz - 1) nb[c++] = id + sz;
                for (int n = 0; n < c; ++n) {
                    size_t b = nb[n];
                    if (outside[b]) continue;
                    bool ok = intoWall ? (dist[b] <= wall && outsideHint[b]) : seedOk(b);
                    if (ok) { outside[b] = 1; q.push_back(b); }
                }
            }
        };
        for (int k = 0; k < nz; ++k)
            for (int j = 0; j < ny; ++j)
                for (int i = 0; i < nx; ++i)
                    if (i == 0 || j == 0 || k == 0 || i == nx - 1 || j == ny - 1 || k == nz - 1) {
                        size_t id = idx(i, j, k);
                        if (!outside[id] && seedOk(id)) { outside[id] = 1; q.push_back(id); }
                    }
        expand(false);
        for (size_t id = 0; id < N; ++id) if (outside[id]) q.push_back(id);
        expand(true);
        for (size_t id = 0; id < N; ++id) {
            float fc = outside[id] ? dist[id] : -dist[id];
            if (fc < field[id]) field[id] = fc;
            if (cclosest[id] >= 0 && dist[id] < bestDist[id]) { bestDist[id] = dist[id]; closest[id] = cclosest[id]; }
        }
    }
    lap("distance + sign");
    // Remove sign specks: near the surface a voxel's inside/outside guess can
    // be wrong where the pseudo-normal is unreliable (folds, creases). Such a
    // voxel is unreachable by the flood fill and stays "inside" as a 1-2 voxel
    // bubble whose tiny closed surface touches the real one along shared edges
    // (non-manifold). Real inside regions are never this small, so any inside
    // 6-connected component under kMinInside voxels is flipped to outside.
    {
        // Only near-surface inside voxels can be specks; a region that reaches
        // a deep voxel (|d| == band, far from every triangle) or one already
        // known to be real is real. BFS stops as soon as the region is proven
        // real, so the deep interior is never walked.
        const int kMinInside = 8;
        std::vector<uint8_t> label(N, 0);  // 0 unvisited, 1 real, 2 speck
        std::vector<size_t> comp, stack;
        for (size_t seed = 0; seed < N; ++seed) {
            if (field[seed] >= 0 || label[seed]) continue;
            if (-field[seed] >= band * 0.999f) { label[seed] = 1; continue; }  // deep
            comp.clear();
            stack.assign(1, seed);
            label[seed] = 2;
            bool real = false;
            while (!stack.empty() && !real) {
                size_t id = stack.back();
                stack.pop_back();
                comp.push_back(id);
                if ((int)comp.size() >= kMinInside) { real = true; break; }
                int i = (int)(id % nx), j = (int)((id / nx) % ny), k = (int)(id / sz);
                size_t nb[6];
                int c = 0;
                if (i > 0) nb[c++] = id - sx;
                if (i < nx - 1) nb[c++] = id + sx;
                if (j > 0) nb[c++] = id - sy;
                if (j < ny - 1) nb[c++] = id + sy;
                if (k > 0) nb[c++] = id - sz;
                if (k < nz - 1) nb[c++] = id + sz;
                for (int n = 0; n < c; ++n) {
                    size_t q = nb[n];
                    if (field[q] >= 0) continue;
                    if (label[q] == 1 || -field[q] >= band * 0.999f) { real = true; break; }
                    if (label[q] == 0) { label[q] = 2; stack.push_back(q); }
                }
            }
            if (real) {
                for (size_t id : comp) label[id] = 1;
                for (size_t id : stack) label[id] = 1;
            } else {
                for (size_t id : comp) field[id] = std::fabs(field[id]) + 1e-6f;
            }
        }
    }

    lap("speck removal");
    // Resolve ambiguous (checkerboard) faces: a 2x2 square of samples whose
    // diagonal corners agree but neighbours differ makes Surface Nets join two
    // cells by an edge shared by four quads. Flip the least certain corner
    // (smallest |distance| among the inside corners) to outside; repeat since
    // a flip can create a new checkerboard nearby.
    for (int pass = 0; pass < 8; ++pass) {
        int flips = 0;
        auto fix = [&](size_t c0, size_t c1, size_t c2, size_t c3) {  // square in order
            bool s0 = field[c0] < 0, s1 = field[c1] < 0, s2 = field[c2] < 0, s3 = field[c3] < 0;
            if (!(s0 == s2 && s1 == s3 && s0 != s1)) return;
            size_t cs[4] = {c0, c1, c2, c3};
            size_t best = (size_t)-1;  // monotone: least certain inside corner -> outside
            for (size_t c : cs)
                if (field[c] < 0 && (best == (size_t)-1 || std::fabs(field[c]) < std::fabs(field[best]))) best = c;
            field[best] = std::fabs(field[best]) + 1e-6f;
            ++flips;
        };
        for (int k = 0; k < nz; ++k)
            for (int j = 0; j < ny; ++j)
                for (int i = 0; i < nx; ++i) {
                    size_t id = idx(i, j, k);
                    if (std::fabs(field[id]) >= band * 0.999f) continue;  // far from surface: no sign change
                    if (i + 1 < nx && j + 1 < ny) fix(id, id + sx, id + sx + sy, id + sy);
                    if (i + 1 < nx && k + 1 < nz) fix(id, id + sx, id + sx + sz, id + sz);
                    if (j + 1 < ny && k + 1 < nz) fix(id, id + sy, id + sy + sz, id + sz);
                }
        if (!flips) break;
    }

    // keep exact zeros off the grid so every crossing is strict
    for (auto& fv : field) if (fv == 0.0f) fv = 1e-7f;

    lap("checkerboard faces");
    // ---- 3. surface nets
    const int cx = nx - 1, cy = ny - 1, cz = nz - 1;
    auto cidx = [&](int i, int j, int k) { return ((size_t)k * cy + j) * cx + i; };
    Mesh& out = res.mesh;
    std::vector<int> cellVert;
    std::vector<size_t> vertCell;
    std::vector<char> featureVert;  // Dual Contouring found an edge/corner here
    // Extract; if an edge still borders 4 quads (a 3D ambiguity the face rule
    // above doesn't cover), flip the least certain sample on the face shared by
    // the edge's two cells and extract again. Converges in 1-2 rounds.
    for (int round = 0; round < 8; ++round) {
        out = Mesh{};
        cellVert.assign((size_t)cx * cy * cz, -1);
        vertCell.clear();
        static const int corner[8][3] = {{0,0,0},{1,0,0},{0,1,0},{1,1,0},{0,0,1},{1,0,1},{0,1,1},{1,1,1}};
        static const int edgeC[12][2] = {{0,1},{2,3},{4,5},{6,7},{0,2},{1,3},{4,6},{5,7},{0,4},{1,5},{2,6},{3,7}};
        // Cell vertices, parallel over z-slabs into per-slab lists, then
        // numbered in slab order so the result matches a serial scan.
        {
            const int slabs = std::max(1, std::min(cz, 64));
            struct Found { size_t cell; Vec3 p; bool feature; };
            std::vector<std::vector<Found>> found(slabs);
            parallelFor(slabs, [&](int sidx) {
                int k0 = sidx * cz / slabs, k1 = (sidx + 1) * cz / slabs;
                auto& outv = found[sidx];
                for (int k = k0; k < k1; ++k)
                    for (int j = 0; j < cy; ++j)
                        for (int i = 0; i < cx; ++i) {
                            float fv[8];
                            int inside = 0;
                            for (int c = 0; c < 8; ++c) {
                                fv[c] = field[idx(i + corner[c][0], j + corner[c][1], k + corner[c][2])];
                                inside |= (fv[c] < 0) << c;
                            }
                            if (inside == 0 || inside == 255) continue;
                            Vec3 sum{};
                            int cnt = 0;
                            for (auto& e : edgeC) {
                                float a = fv[e[0]], b = fv[e[1]];
                                if ((a < 0) == (b < 0)) continue;
                                float t = a / (a - b);
                                Vec3 pa{(float)corner[e[0]][0], (float)corner[e[0]][1], (float)corner[e[0]][2]};
                                Vec3 pb{(float)corner[e[1]][0], (float)corner[e[1]][1], (float)corner[e[1]][2]};
                                sum += lerp(pa, pb, t);
                                ++cnt;
                            }
                            Vec3 local = sum / (float)cnt;  // Surface Nets: mass point of crossings
                            bool feature = false;
                            if (s.sharpFeatures) {
                                // Dual Contouring (Ju et al. 2002): minimise the squared
                                // distance to the source tangent planes at the crossings,
                                // biased toward the mass point (lambda) for stability.
                                double A[3][3] = {{0}}, bv[3] = {0};
                                Vec3 nfirst{};
                                float minCos = 1.0f;
                                Vec3 cellO = o + Vec3{(float)i, (float)j, (float)k} * h;
                                int planes = 0;
                                for (auto& e : edgeC) {
                                    float a = fv[e[0]], b = fv[e[1]];
                                    if ((a < 0) == (b < 0)) continue;
                                    int ce = std::fabs(a) < std::fabs(b) ? e[0] : e[1];
                                    int tri = closest[idx(i + corner[ce][0], j + corner[ce][1], k + corner[ce][2])];
                                    if (tri < 0) continue;
                                    float t = a / (a - b);
                                    Vec3 pa{(float)corner[e[0]][0], (float)corner[e[0]][1], (float)corner[e[0]][2]};
                                    Vec3 pb{(float)corner[e[1]][0], (float)corner[e[1]][1], (float)corner[e[1]][2]};
                                    Vec3 xw = cellO + lerp(pa, pb, t) * h;
                                    const Tri& f = src.tris[tri];
                                    Vec3 n = normalize(cross(src.positions[f[1]] - src.positions[f[0]],
                                                             src.positions[f[2]] - src.positions[f[0]]));
                                    float uu, vv;
                                    Vec3 q = closestPointOnTriangle(xw, src.positions[f[0]], src.positions[f[1]], src.positions[f[2]], uu, vv);
                                    Vec3 ql = (q - cellO) / h;  // plane point in cell-local units
                                    if (planes == 0) nfirst = n;
                                    else minCos = std::min(minCos, dot(n, nfirst));
                                    double d = dot(n, ql);
                                    for (int r = 0; r < 3; ++r) {
                                        for (int c2 = 0; c2 < 3; ++c2) A[r][c2] += (double)n[r] * n[c2];
                                        bv[r] += (double)n[r] * d;
                                    }
                                    ++planes;
                                }
                                if (planes >= 2) {
                                    const double lambda = 0.05;
                                    for (int r = 0; r < 3; ++r) { A[r][r] += lambda; bv[r] += lambda * local[r]; }
                                    double det = A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1]) -
                                                 A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0]) +
                                                 A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]);
                                    if (std::fabs(det) > 1e-12) {
                                        Vec3 x;
                                        for (int col = 0; col < 3; ++col) {  // Cramer's rule
                                            double M[3][3];
                                            for (int r = 0; r < 3; ++r)
                                                for (int c2 = 0; c2 < 3; ++c2) M[r][c2] = c2 == col ? bv[r] : A[r][c2];
                                            double dc = M[0][0] * (M[1][1] * M[2][2] - M[1][2] * M[2][1]) -
                                                        M[0][1] * (M[1][0] * M[2][2] - M[1][2] * M[2][0]) +
                                                        M[0][2] * (M[1][0] * M[2][1] - M[1][1] * M[2][0]);
                                            x[col] = (float)(dc / det);
                                        }
                                        // keep the vertex in (a slightly grown) cell; otherwise the
                                        // QEF is ill-conditioned there and the mass point is safer
                                        if (x.x > -0.25f && x.x < 1.25f && x.y > -0.25f && x.y < 1.25f && x.z > -0.25f && x.z < 1.25f) {
                                            local = x;
                                            feature = minCos < 0.866f;  // planes > 30 deg apart: edge/corner
                                        }
                                    }
                                }
                            }
                            outv.push_back({cidx(i, j, k), o + (Vec3{(float)i, (float)j, (float)k} + local) * h, feature});
                        }
            }, 1);
            size_t total = 0;
            for (auto& f : found) total += f.size();
            out.positions.reserve(total);
            featureVert.clear();
            for (auto& f : found)
                for (auto& pr : f) {
                    cellVert[pr.cell] = (int)out.positions.size();
                    out.positions.push_back(pr.p);
                    featureVert.push_back(pr.feature ? 1 : 0);
                }
        }

        auto quad = [&](int a, int b, int c, int d, bool flip) {
            if (a < 0 || b < 0 || c < 0 || d < 0) return;
            if (flip) std::swap(b, d);
            out.polyCounts.push_back(4);
            out.polyIndices.insert(out.polyIndices.end(), {a, b, c, d});
        };
        for (int k = 1; k < nz - 1; ++k)
            for (int j = 1; j < ny - 1; ++j)
                for (int i = 0; i < nx - 1; ++i) {  // x edges
                    float a = field[idx(i, j, k)], b = field[idx(i + 1, j, k)];
                    if ((a < 0) == (b < 0)) continue;
                    quad(cellVert[cidx(i, j - 1, k - 1)], cellVert[cidx(i, j, k - 1)], cellVert[cidx(i, j, k)],
                         cellVert[cidx(i, j - 1, k)], !(a < 0));
                }
        for (int k = 1; k < nz - 1; ++k)
            for (int j = 0; j < ny - 1; ++j)
                for (int i = 1; i < nx - 1; ++i) {  // y edges
                    float a = field[idx(i, j, k)], b = field[idx(i, j + 1, k)];
                    if ((a < 0) == (b < 0)) continue;
                    quad(cellVert[cidx(i - 1, j, k - 1)], cellVert[cidx(i - 1, j, k)], cellVert[cidx(i, j, k)],
                         cellVert[cidx(i, j, k - 1)], !(a < 0));
                }
        for (int k = 0; k < nz - 1; ++k)
            for (int j = 1; j < ny - 1; ++j)
                for (int i = 1; i < nx - 1; ++i) {  // z edges
                    float a = field[idx(i, j, k)], b = field[idx(i, j, k + 1)];
                    if ((a < 0) == (b < 0)) continue;
                    quad(cellVert[cidx(i - 1, j - 1, k)], cellVert[cidx(i, j - 1, k)], cellVert[cidx(i, j, k)],
                         cellVert[cidx(i - 1, j, k)], !(a < 0));
                }

        // record cell of each vertex (for the repair step)
        vertCell.resize(out.positions.size());
        for (size_t c = 0; c < cellVert.size(); ++c) if (cellVert[c] >= 0) vertCell[cellVert[c]] = c;
        std::vector<uint64_t> keys(out.polyIndices.size());
        for (size_t q = 0; q < out.polyCounts.size(); ++q)
            for (int kk = 0; kk < 4; ++kk) {
                int u = out.polyIndices[q * 4 + kk], w = out.polyIndices[q * 4 + (kk + 1) % 4];
                if (u > w) std::swap(u, w);
                keys[q * 4 + kk] = ((uint64_t)(uint32_t)u << 32) | (uint32_t)w;
            }
        std::sort(keys.begin(), keys.end());
        std::vector<uint64_t> badEdges;
        for (size_t i = 0; i < keys.size();) {
            size_t j = i;
            while (j < keys.size() && keys[j] == keys[i]) ++j;
            if (j - i > 2) badEdges.push_back(keys[i]);
            i = j;
        }
        int flips = 0;
        for (uint64_t key : badEdges) {
            size_t ca = vertCell[(int)(key >> 32)], cb = vertCell[(int)(key & 0xffffffffu)];
            int ai = (int)(ca % cx), aj = (int)((ca / cx) % cy), ak = (int)(ca / ((size_t)cx * cy));
            int bi = (int)(cb % cx), bj = (int)((cb / cx) % cy), bk = (int)(cb / ((size_t)cx * cy));
            // shared face: the cells differ by one along exactly one axis
            int fi = std::max(ai, bi), fj = std::max(aj, bj), fk = std::max(ak, bk);
            size_t cs[4];
            if (ai != bi) { cs[0] = idx(fi, aj, ak); cs[1] = idx(fi, aj + 1, ak); cs[2] = idx(fi, aj + 1, ak + 1); cs[3] = idx(fi, aj, ak + 1); }
            else if (aj != bj) { cs[0] = idx(ai, fj, ak); cs[1] = idx(ai + 1, fj, ak); cs[2] = idx(ai + 1, fj, ak + 1); cs[3] = idx(ai, fj, ak + 1); }
            else { cs[0] = idx(ai, aj, fk); cs[1] = idx(ai + 1, aj, fk); cs[2] = idx(ai + 1, aj + 1, fk); cs[3] = idx(ai, aj + 1, fk); }
            // Monotone repair: only ever turn an *inside* sample outside (the
            // least certain one). Toggling either way can oscillate between
            // two ambiguous configurations; shrinking the inside set cannot.
            size_t best = (size_t)-1;
            for (size_t c : cs)
                if (field[c] < 0 && (best == (size_t)-1 || std::fabs(field[c]) < std::fabs(field[best]))) best = c;
            if (best == (size_t)-1) continue;
            field[best] = std::fabs(field[best]) + 1e-6f;
            ++flips;
        }
        if (!flips) break;
    }

    lap("extract + repair");
    {
        std::vector<int> origin;  // source vertex of each appended copy
        splitNonManifold(out, &origin);
        for (int v : origin) featureVert.push_back(featureVert[v]);
    }
    lap("split non-manifold");
    // Drop bubbles: a sign repair can leave a lone flipped voxel enclosed by
    // the solid, which extracts as a separate 6-quad cube that then collapses
    // onto the surface. No real part is this small (< kMinShell quads and
    // under 1% of the largest shell); everything else is kept.
    {
        const int kMinShell = 24;
        const size_t nq = out.polyCounts.size(), nvt = out.positions.size();
        std::vector<int> par(nvt);
        for (size_t v = 0; v < nvt; ++v) par[v] = (int)v;
        auto fr = [&](int v) { while (par[v] != v) { par[v] = par[par[v]]; v = par[v]; } return v; };
        for (size_t q = 0; q < nq; ++q)
            for (int k = 1; k < 4; ++k) { int a = fr(out.polyIndices[q * 4]), b = fr(out.polyIndices[q * 4 + k]); if (a != b) par[b] = a; }
        std::vector<int> size(nvt, 0);
        for (size_t q = 0; q < nq; ++q) ++size[fr(out.polyIndices[q * 4])];
        int largest = 0;
        for (int c : size) largest = std::max(largest, c);
        auto tiny = [&](size_t q) { int c = size[fr(out.polyIndices[q * 4])]; return c < kMinShell && c * 100 < largest; };
        size_t drop = 0;
        for (size_t q = 0; q < nq; ++q) drop += tiny(q);
        if (drop) {
            std::vector<int> remap(nvt, -1), idxs;
            std::vector<Vec3> pos;
            std::vector<char> feat;
            idxs.reserve(out.polyIndices.size());
            for (size_t q = 0; q < nq; ++q) {
                if (tiny(q)) continue;
                for (int k = 0; k < 4; ++k) {
                    int v = out.polyIndices[q * 4 + k];
                    if (remap[v] < 0) {
                        remap[v] = (int)pos.size();
                        pos.push_back(out.positions[v]);
                        feat.push_back(v < (int)featureVert.size() ? featureVert[v] : 0);
                    }
                    idxs.push_back(remap[v]);
                }
            }
            out.positions.swap(pos);
            out.polyIndices.swap(idxs);
            out.polyCounts.assign(out.polyIndices.size() / 4, 4);
            featureVert.swap(feat);
        }
    }
    lap("drop bubbles");
    for (size_t q = 0; q < out.polyCounts.size(); ++q) {
        const int* f = &out.polyIndices[q * 4];
        out.tris.push_back({f[0], f[1], f[2]});
        out.tris.push_back({f[0], f[2], f[3]});
    }
    out.ensureAttributes();
    out.buildAdjacency();
    out.computeNormals();

    lap("triangulate + normals");
    // ---- 4. relax + project
    const int nv = (int)out.positions.size();
    std::vector<Vec3> tmp(nv);
    auto tangentialRelax = [&](float weight) {
        parallelFor(nv, [&](int v) {
            const auto& nb = out.vertNbrs[v];
            if (nb.empty()) { tmp[v] = out.positions[v]; return; }
            Vec3 avg{};
            for (int n : nb) avg += out.positions[n];
            Vec3 L = avg / (float)nb.size() - out.positions[v];
            // feature vertices (hard edges/corners) stay put so relax can't round them
            float w = (s.sharpFeatures && v < (int)featureVert.size() && featureVert[v]) ? 0.0f : weight;
            tmp[v] = out.positions[v] + projectOnPlane(L, out.normals[v]) * w;
        });
        out.positions.swap(tmp);
        out.computeNormals();
    };
    bool hasColor = s.keepColor && src.color.size() == src.positions.size();
    // Projection onto the source. Closest-point projection is many-to-one at
    // convex creases/corners of the source (every point in a corner's normal
    // cone maps onto the corner), which collapsed neighbours into zero-length
    // edges on sculpted input. So vertices move along their own normal to the
    // nearest source hit (|t| < 2h); closest point is only the fallback.
    std::unique_ptr<BVH> srcBvh;
    if (s.project) { srcBvh = std::make_unique<BVH>(); srcBvh->build(src); }
    lap("source BVH");
    static const bool dbgProj = getenv("SCULPT_DEBUG_PROJECT") != nullptr;
    std::atomic<int> dbgRay{0}, dbgClosest{0}, dbgNone{0};
    auto project = [&](bool colors) {
        parallelFor(nv, [&](int v) {
            Vec3 p = out.positions[v];
            Vec3 n = out.normals[v];
            int gi = (int)std::round((p.x - o.x) / h), gj = (int)std::round((p.y - o.y) / h), gk = (int)std::round((p.z - o.z) / h);
            float best = 1e30f, bestT = 1e30f;
            Vec3 bestQ = p, rayQ = p, bestC{0.8f, 0.8f, 0.8f}, rayC = bestC;
            // 1) along the normal (BVH, bounded to 2h)
            if (srcBvh && length2(n) > 0.5f) {
                for (float sg : {1.0f, -1.0f}) {
                    Hit hh = srcBvh->raycast(src, Ray{p, n * sg}, true, std::min(2 * h, std::fabs(bestT)));
                    if (hh.hit) {
                        bestT = hh.t * sg;
                        rayQ = p + n * bestT;
                        if (colors) {
                            const Tri& f = src.tris[hh.tri];
                            rayC = src.color[f[0]] * (1 - hh.u - hh.v) + src.color[f[1]] * hh.u + src.color[f[2]] * hh.v;
                        }
                    }
                }
            }
            // 2) fallback: closest point among the near voxels' closest triangles
            if (!(std::fabs(bestT) < 2 * h)) {
                int lastT = -1;
                for (int dk = -1; dk <= 1; ++dk)
                    for (int dj = -1; dj <= 1; ++dj)
                        for (int di = -1; di <= 1; ++di) {
                            int i = gi + di, j = gj + dj, k = gk + dk;
                            if (i < 0 || j < 0 || k < 0 || i >= nx || j >= ny || k >= nz) continue;
                            int t = closest[idx(i, j, k)];
                            if (t < 0 || t == lastT) continue;
                            lastT = t;
                            const Tri& f = src.tris[t];
                            float u, w;
                            Vec3 qq = closestPointOnTriangle(p, src.positions[f[0]], src.positions[f[1]], src.positions[f[2]], u, w);
                            float d = length2(qq - p);
                            if (d < best) {
                                best = d;
                                bestQ = qq;
                                if (colors) bestC = src.color[f[0]] * (1 - u - w) + src.color[f[1]] * u + src.color[f[2]] * w;
                            }
                        }
            }
            bool ray = std::fabs(bestT) < 2 * h;
            if (dbgProj) { if (ray) ++dbgRay; else if (best < 4 * h * h) ++dbgClosest; else ++dbgNone; }
            if (s.project) {
                if (ray) out.positions[v] = rayQ;
                else if (best < (2 * h) * (2 * h)) out.positions[v] = bestQ;
            }
            if (colors) out.color[v] = ray ? rayC : bestC;
        });
        out.computeNormals();
        if (dbgProj) { fprintf(stderr, "project: ray %d closest %d none %d\n", dbgRay.load(), dbgClosest.load(), dbgNone.load()); dbgRay = dbgClosest = dbgNone = 0; }
    };
    int relax = s.relaxIterations + (int)std::round(s.blur * 8);
    for (int it = 0; it < relax; ++it) tangentialRelax(0.5f);
    if (s.project || hasColor) {
        project(hasColor);
        // Closest-point projection onto a crumpled source can pull neighbours
        // onto the same point (concave creases): zero-length edges that break
        // Retopologize and brushes. Relax-on-surface passes spread them again.
        if (s.project)
            { tangentialRelax(0.5f); project(false); }
    }
    lap("relax + project");
    out.topologyFromHost = false;
    return res;
}

}  // namespace sculpt
