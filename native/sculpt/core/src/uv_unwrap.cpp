// UV unwrapping of a polygon cage with map UVs - see sculpt/uv_unwrap.h.
//
// uvUnfold, per shell (faces joined by shared UV indices):
//   1. the shell's polygons are fanned into triangles (f0, fk, fk+1); each triangle is laid flat in its own
//      orthonormal 2D frame (counter-clockwise), from the 3D positions of its corners' vertices
//   2. LSCM (Levy, Petitjean, Ray, Maillot 2002): minimise sum_T |sum_j W_Tj U_j|^2 / d_T, U = u + iv, W the
//      triangle's edges as complex numbers, d_T twice its area (= the area-weighted |dU/dz-bar|^2, zero for a
//      conformal map). Pins: the user's; with fewer than 2 the two boundary UVs farthest apart in 3D (all UVs of a
//      closed shell) are added, set apart by their 3D distance. Normal equations solved with Eigen's SparseLU
//      (COLAMD ordering, MPL-2.0 parts only)
//   3. `iterations` rounds of ARAP (Liu, Zhang, Xu, Gotsman, Gortler 2008): local step = the closest rotation to
//      each triangle's cotangent-weighted Jacobian (closed form in 2D), global step = one cotangent-Laplacian
//      solve per axis (factored once). Shells without user pins keep only one pin here (ARAP fixes the scale
//      itself), shells with user pins keep all of them
//   4. shells without user pins: mirrored if they came out clockwise, turned to their minimum-area box, scaled to 2D area = 3D area *
//      scaleToDensity, moved so the UV bounding box centre is where the input's was
//
// uvLayout: per shell optional texel-density equalisation and rotation (90-degree choice inside the packer, or
// the minimum-area box from the convex hull: rotating calipers over the hull edges), then a skyline packer
// (bottom-left by the lowest resulting top) over several strip widths; the squarest result is scaled into the
// 0-1 square minus the margin. The gap is in final UV units, so the pack is repeated until the final scale
// leaves at least paddingPx / resolution between boxes.
//
// uvAuto: xatlas (third_party/xatlas, MIT) - see the comment above uvAuto below.
//
// Written for LOKI (AGPL-3.0) from the published algorithms named above; no code taken from other unwrappers.
#include "sculpt/uv_unwrap.h"

#include <Eigen/Sparse>
#include <Eigen/SparseLU>
#include <Eigen/OrderingMethods>

#include "../../third_party/xatlas/xatlas.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <numeric>

namespace sculpt {

namespace {

using SpMat = Eigen::SparseMatrix<double>;
using Solver = Eigen::SparseLU<SpMat, Eigen::COLAMDOrdering<int>>;
using Trip = Eigen::Triplet<double>;

struct V3 { double x, y, z; };
inline V3 sub(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline double dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline V3 cross(V3 a, V3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
inline double len(V3 a) { return std::sqrt(dot(a, a)); }

struct DSU {
    std::vector<int> p;
    explicit DSU(int n) : p((size_t)n) { std::iota(p.begin(), p.end(), 0); }
    int find(int a) { while (p[a] != a) { p[a] = p[p[a]]; a = p[a]; } return a; }
    void join(int a, int b) { a = find(a); b = find(b); if (a != b) p[b] = a; }
};

std::vector<int> faceStarts(const UvCage& c) {
    std::vector<int> s((size_t)c.nf + 1, 0);
    for (int f = 0; f < c.nf; ++f) s[f + 1] = s[f] + c.sizes[f];
    return s;
}

inline V3 vpos(const UvCage& c, int v) { const float* p = c.pos + 3 * (size_t)v; return {p[0], p[1], p[2]}; }

// One shell, in local UV numbering.
struct Shell {
    std::vector<int> uvs;            // local -> global UV index
    std::vector<int> faces;
    std::vector<V3> p3;              // a 3D position per local UV (its first corner's vertex)
    struct Tri { int a, b, c; double x[3], y[3]; double area; };   // local UV ids + flat 2D coords (ccw)
    std::vector<Tri> tris;
    std::vector<std::pair<int, int>> edges;   // polygon edges (local UV pairs), for the boundary
};

void buildShell(const UvCage& c, const std::vector<int>& st, const std::vector<int>& faces, std::vector<int>& g2l, Shell& S) {
    S.faces = faces;
    for (int f : faces)
        for (int k = st[f]; k < st[f + 1]; ++k) {
            const int g = c.fuv[k];
            if (g2l[g] < 0) { g2l[g] = (int)S.uvs.size(); S.uvs.push_back(g); S.p3.push_back(vpos(c, c.fv[k])); }
        }
    for (int f : faces) {
        const int s0 = st[f], n = c.sizes[f];
        for (int k = 0; k < n; ++k) S.edges.push_back({g2l[c.fuv[s0 + k]], g2l[c.fuv[s0 + (k + 1) % n]]});
        for (int k = 1; k + 1 < n; ++k) {
            const int ca = s0, cb = s0 + k, cc = s0 + k + 1;
            Shell::Tri t;
            t.a = g2l[c.fuv[ca]]; t.b = g2l[c.fuv[cb]]; t.c = g2l[c.fuv[cc]];
            if (t.a == t.b || t.b == t.c || t.a == t.c) continue;
            const V3 A = vpos(c, c.fv[ca]), B = vpos(c, c.fv[cb]), C = vpos(c, c.fv[cc]);
            const V3 e1 = sub(B, A), e2 = sub(C, A);
            const V3 n3 = cross(e1, e2);
            const double l1 = len(e1), nn = len(n3);
            const double scale2 = std::max(dot(e1, e1), dot(e2, e2));
            if (l1 <= 0 || nn <= 1e-12 * scale2 || !(nn > 0)) continue;   // degenerate: no energy
            const V3 ex = {e1.x / l1, e1.y / l1, e1.z / l1};
            const V3 ey0 = cross({n3.x / nn, n3.y / nn, n3.z / nn}, ex);
            t.x[0] = 0; t.y[0] = 0;
            t.x[1] = l1; t.y[1] = 0;
            t.x[2] = dot(e2, ex); t.y[2] = dot(e2, ey0);
            t.area = 0.5 * nn;
            S.tris.push_back(t);
        }
    }
    for (int g : S.uvs) g2l[g] = -1;   // leave the scratch map clean for the next shell
}

double signedArea(const double* u, const double* v, int a, int b, int c) {
    return 0.5 * ((u[b] - u[a]) * (v[c] - v[a]) - (u[c] - u[a]) * (v[b] - v[a]));
}

// Two points far apart among `cand` (local ids): repeated farthest-point sweeps (exact on most shapes, close otherwise).
void farthestPair(const Shell& S, const std::vector<int>& cand, int& a, int& b) {
    a = cand[0]; b = cand[0];
    double best = -1;
    int cur = cand[0];
    for (int it = 0; it < 4; ++it) {
        int far = cur; double fd = -1;
        for (int i : cand) { const double d = dot(sub(S.p3[i], S.p3[cur]), sub(S.p3[i], S.p3[cur])); if (d > fd) { fd = d; far = i; } }
        if (fd > best) { best = fd; a = cur; b = far; }
        if (far == cur) break;
        cur = far;
    }
}

// LSCM: solves for the free UVs given the pinned ones (u, v hold the pins' values). False when the solve fails.
bool lscm(const Shell& S, const std::vector<char>& pin, std::vector<double>& u, std::vector<double>& v) {
    const int n = (int)S.uvs.size();
    std::vector<int> fid((size_t)n, -1);
    int nfree = 0;
    for (int i = 0; i < n; ++i) if (!pin[i]) fid[i] = nfree++;
    if (!nfree) return true;
    const int N = 2 * nfree;
    std::vector<Trip> trips; trips.reserve(S.tris.size() * 72);
    Eigen::VectorXd rhs = Eigen::VectorXd::Zero(N);
    for (const auto& t : S.tris) {
        const int id[3] = {t.a, t.b, t.c};
        const double d = 2.0 * t.area, w = 1.0 / std::sqrt(d);
        double a[3], b[3];   // W_j = (x_l - x_k) + i (y_l - y_k), (j, k, l) cyclic
        for (int j = 0; j < 3; ++j) { const int k = (j + 1) % 3, l = (j + 2) % 3; a[j] = (t.x[l] - t.x[k]) * w; b[j] = (t.y[l] - t.y[k]) * w; }
        // row 1: sum a u - b v ; row 2: sum b u + a v. Variables: u_j -> 2*fid, v_j -> 2*fid+1
        for (int row = 0; row < 2; ++row) {
            int var[6]; double cf[6]; double val[6]; bool fr[6];
            for (int j = 0; j < 3; ++j) {
                const int g = id[j];
                fr[2 * j] = fr[2 * j + 1] = !pin[g];
                var[2 * j] = pin[g] ? -1 : 2 * fid[g]; var[2 * j + 1] = pin[g] ? -1 : 2 * fid[g] + 1;
                val[2 * j] = u[g]; val[2 * j + 1] = v[g];
                if (row == 0) { cf[2 * j] = a[j]; cf[2 * j + 1] = -b[j]; } else { cf[2 * j] = b[j]; cf[2 * j + 1] = a[j]; }
            }
            double fixed = 0;
            for (int q = 0; q < 6; ++q) if (!fr[q]) fixed += cf[q] * val[q];
            for (int p = 0; p < 6; ++p) {
                if (!fr[p]) continue;
                for (int q = 0; q < 6; ++q) if (fr[q]) trips.emplace_back(var[p], var[q], cf[p] * cf[q]);
                rhs[var[p]] -= cf[p] * fixed;
            }
        }
    }
    SpMat A(N, N);
    A.setFromTriplets(trips.begin(), trips.end());
    // a UV only on degenerate triangles has an empty row: tie it weakly to zero so the system stays solvable
    for (int i = 0; i < N; ++i) A.coeffRef(i, i) += 1e-12;
    A.makeCompressed();
    Solver lu; lu.compute(A);
    if (lu.info() != Eigen::Success) return false;
    Eigen::VectorXd x = lu.solve(rhs);
    if (lu.info() != Eigen::Success) return false;
    for (int i = 0; i < n; ++i) if (!pin[i]) {
        const double uu = x[2 * fid[i]], vv = x[2 * fid[i] + 1];
        if (!std::isfinite(uu) || !std::isfinite(vv)) return false;
        u[i] = uu; v[i] = vv;
    }
    return true;
}

// ARAP rounds (local rotation fit + global cotangent solve), `pin` fixed.
void arap(const Shell& S, const std::vector<char>& pin, int iterations, std::vector<double>& u, std::vector<double>& v) {
    if (iterations <= 0 || S.tris.empty()) return;
    const int n = (int)S.uvs.size();
    std::vector<int> fid((size_t)n, -1);
    int nfree = 0;
    for (int i = 0; i < n; ++i) if (!pin[i]) fid[i] = nfree++;
    if (!nfree) return;
    // cot of the angle opposite each half-edge (j -> j+1) of every triangle
    const size_t nt = S.tris.size();
    std::vector<double> cotw(nt * 3);
    for (size_t t = 0; t < nt; ++t) {
        const auto& T = S.tris[t];
        for (int j = 0; j < 3; ++j) {
            const int k = (j + 1) % 3, l = (j + 2) % 3;   // edge j-k, opposite vertex l
            const double ax = T.x[j] - T.x[l], ay = T.y[j] - T.y[l], bx = T.x[k] - T.x[l], by = T.y[k] - T.y[l];
            const double cr = std::fabs(ax * by - ay * bx);
            double ct = cr > 0 ? (ax * bx + ay * by) / cr : 0.0;
            ct = std::max(-1e3, std::min(1e3, ct));
            cotw[t * 3 + j] = 0.5 * ct;
        }
    }
    std::vector<Trip> trips; trips.reserve(nt * 12);
    for (size_t t = 0; t < nt; ++t) {
        const auto& T = S.tris[t];
        const int id[3] = {T.a, T.b, T.c};
        for (int j = 0; j < 3; ++j) {
            const int i0 = id[j], i1 = id[(j + 1) % 3];
            const double w = cotw[t * 3 + j];
            if (!pin[i0]) trips.emplace_back(fid[i0], fid[i0], w);
            if (!pin[i1]) trips.emplace_back(fid[i1], fid[i1], w);
            if (!pin[i0] && !pin[i1]) { trips.emplace_back(fid[i0], fid[i1], -w); trips.emplace_back(fid[i1], fid[i0], -w); }
        }
    }
    SpMat L(nfree, nfree);
    L.setFromTriplets(trips.begin(), trips.end());
    for (int i = 0; i < nfree; ++i) L.coeffRef(i, i) += 1e-10;
    L.makeCompressed();
    Solver lu; lu.compute(L);
    if (lu.info() != Eigen::Success) return;
    std::vector<double> rc(nt), rs(nt);
    Eigen::VectorXd bu(nfree), bv(nfree);
    for (int it = 0; it < iterations; ++it) {
        // local step: R_t = rotation closest to S_t = sum w (u_i - u_j)(x_i - x_j)^T
        for (size_t t = 0; t < nt; ++t) {
            const auto& T = S.tris[t];
            const int id[3] = {T.a, T.b, T.c};
            double s00 = 0, s01 = 0, s10 = 0, s11 = 0;
            for (int j = 0; j < 3; ++j) {
                const int k = (j + 1) % 3;
                const double w = cotw[t * 3 + j];
                const double du = u[id[j]] - u[id[k]], dv = v[id[j]] - v[id[k]];
                const double dx = T.x[j] - T.x[k], dy = T.y[j] - T.y[k];
                s00 += w * du * dx; s01 += w * du * dy; s10 += w * dv * dx; s11 += w * dv * dy;
            }
            const double th = std::atan2(s10 - s01, s00 + s11);
            rc[t] = std::cos(th); rs[t] = std::sin(th);
        }
        // global step: L u = sum w R (x_i - x_j) (+ pinned neighbours)
        bu.setZero(); bv.setZero();
        for (size_t t = 0; t < nt; ++t) {
            const auto& T = S.tris[t];
            const int id[3] = {T.a, T.b, T.c};
            for (int j = 0; j < 3; ++j) {
                const int k = (j + 1) % 3, i0 = id[j], i1 = id[k];
                const double w = cotw[t * 3 + j];
                const double dx = T.x[j] - T.x[k], dy = T.y[j] - T.y[k];
                const double ru = rc[t] * dx - rs[t] * dy, rv = rs[t] * dx + rc[t] * dy;
                if (!pin[i0]) { bu[fid[i0]] += w * ru; bv[fid[i0]] += w * rv; if (pin[i1]) { bu[fid[i0]] += w * u[i1]; bv[fid[i0]] += w * v[i1]; } }
                if (!pin[i1]) { bu[fid[i1]] -= w * ru; bv[fid[i1]] -= w * rv; if (pin[i0]) { bu[fid[i1]] += w * u[i0]; bv[fid[i1]] += w * v[i0]; } }
            }
        }
        const Eigen::VectorXd xu = lu.solve(bu), xv = lu.solve(bv);
        bool ok = true;
        for (int i = 0; i < nfree && ok; ++i) ok = std::isfinite(xu[i]) && std::isfinite(xv[i]);
        if (!ok) return;
        for (int i = 0; i < n; ++i) if (!pin[i]) { u[i] = xu[fid[i]]; v[i] = xv[fid[i]]; }
    }
}

void shellStats(const Shell& S, const std::vector<double>& u, const std::vector<double>& v, int& flips, double& wsum, double& stretchSum) {
    double tot = 0;
    for (const auto& t : S.tris) tot += signedArea(u.data(), v.data(), t.a, t.b, t.c);
    const double sgn = tot >= 0 ? 1.0 : -1.0;
    for (const auto& t : S.tris) {
        const double sa = signedArea(u.data(), v.data(), t.a, t.b, t.c) * sgn;
        if (sa <= 0) ++flips;
        // Jacobian J = [du1 du2; dv1 dv2] * inverse([dx1 dx2; dy1 dy2]) (x0 = y0 = y1 = 0)
        const double du1 = u[t.b] - u[t.a], du2 = u[t.c] - u[t.a], dv1 = v[t.b] - v[t.a], dv2 = v[t.c] - v[t.a];
        const double x1 = t.x[1], x2 = t.x[2], y2 = t.y[2];
        const double det = x1 * y2;
        double ratio = 10.0;
        if (det > 0) {
            const double j00 = du1 / x1, j01 = (du2 - du1 * x2 / x1) / y2;
            const double j10 = dv1 / x1, j11 = (dv2 - dv1 * x2 / x1) / y2;
            const double a = j00 * j00 + j10 * j10, b = j00 * j01 + j10 * j11, d = j01 * j01 + j11 * j11;
            const double tr = a + d, disc = std::sqrt(std::max(0.0, (a - d) * (a - d) + 4 * b * b));
            const double l1 = 0.5 * (tr + disc), l2 = 0.5 * (tr - disc);
            if (l2 > 1e-300 && sa > 0) ratio = std::min(10.0, std::sqrt(l1 / l2));
        }
        wsum += t.area; stretchSum += t.area * ratio;
    }
}

struct P2 { double x, y; };

std::vector<P2> convexHull(std::vector<P2> p) {
    std::sort(p.begin(), p.end(), [](const P2& a, const P2& b) { return a.x < b.x || (a.x == b.x && a.y < b.y); });
    p.erase(std::unique(p.begin(), p.end(), [](const P2& a, const P2& b) { return a.x == b.x && a.y == b.y; }), p.end());
    if (p.size() < 3) return p;
    std::vector<P2> h(2 * p.size());
    size_t k = 0;
    auto crs = [](const P2& o, const P2& a, const P2& b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); };
    for (size_t i = 0; i < p.size(); ++i) { while (k >= 2 && crs(h[k - 2], h[k - 1], p[i]) <= 0) --k; h[k++] = p[i]; }
    for (size_t i = p.size() - 1, t = k + 1; i > 0; --i) { while (k >= t && crs(h[k - 2], h[k - 1], p[i - 1]) <= 0) --k; h[k++] = p[i - 1]; }
    h.resize(k - 1);
    return h;
}

// Angle that turns the points' minimum-area bounding box axis-aligned (rotating calipers over the hull edges);
// returns false when the axis-aligned box is already (about) as small.
bool minBoxAngle(const std::vector<P2>& pts, double& angle) {
    const std::vector<P2> h = convexHull(pts);
    if (h.size() < 3) return false;
    double bestA = 1e300, bestAng = 0, a0 = 0;
    for (size_t i = 0; i < h.size(); ++i) {
        const P2 a = h[i], b = h[(i + 1) % h.size()];
        const double ang = std::atan2(b.y - a.y, b.x - a.x), cs = std::cos(-ang), sn = std::sin(-ang);
        double x0 = 1e300, x1 = -1e300, y0 = 1e300, y1 = -1e300;
        for (const auto& p : h) { const double x = p.x * cs - p.y * sn, y = p.x * sn + p.y * cs; x0 = std::min(x0, x); x1 = std::max(x1, x); y0 = std::min(y0, y); y1 = std::max(y1, y); }
        const double A = (x1 - x0) * (y1 - y0);
        if (A < bestA - 1e-15) { bestA = A; bestAng = ang; }
    }
    {
        double x0 = 1e300, y0 = 1e300, x1 = -1e300, y1 = -1e300;
        for (const auto& p : h) { x0 = std::min(x0, p.x); x1 = std::max(x1, p.x); y0 = std::min(y0, p.y); y1 = std::max(y1, p.y); }
        a0 = (x1 - x0) * (y1 - y0);
    }
    if (bestA >= a0 * (1 - 1e-9)) return false;   // never worse than as is
    angle = bestAng;
    return true;
}

// Faces per shell (shell ids from uvShells).
std::vector<std::vector<int>> facesByShell(const std::vector<int>& faceShell, int ns) {
    std::vector<std::vector<int>> out((size_t)ns);
    for (size_t f = 0; f < faceShell.size(); ++f) if (faceShell[f] >= 0) out[faceShell[f]].push_back((int)f);
    return out;
}

}  // namespace

int uvValidate(const UvCage& c, bool needFuv) {
    if (!c.pos || c.nv < 0 || c.nf < 0 || (c.nf > 0 && (!c.sizes || !c.fv))) return -1;
    if (needFuv && (c.nuv < 1 || (c.nf > 0 && !c.fuv))) return -1;
    long long nc = 0;
    for (int f = 0; f < c.nf; ++f) { if (c.sizes[f] < 3) return -1; nc += c.sizes[f]; }
    if (nc > 0x7fffffff || (c.nc >= 0 && nc != c.nc)) return -1;
    for (long long i = 0; i < nc; ++i) {
        if (c.fv[i] < 0 || c.fv[i] >= c.nv) return -1;
        if (needFuv && (c.fuv[i] < 0 || c.fuv[i] >= c.nuv)) return -1;
    }
    return (int)nc;
}

int uvShells(const UvCage& c, std::vector<int>& uvShell, std::vector<int>& faceShell) {
    const std::vector<int> st = faceStarts(c);
    DSU d(c.nuv);
    for (int f = 0; f < c.nf; ++f) for (int k = st[f] + 1; k < st[f + 1]; ++k) d.join(c.fuv[st[f]], c.fuv[k]);
    std::vector<int> rootId((size_t)c.nuv, -1);
    uvShell.assign((size_t)c.nuv, -1);
    faceShell.assign((size_t)c.nf, -1);
    int ns = 0;
    for (int f = 0; f < c.nf; ++f) {
        const int r = d.find(c.fuv[st[f]]);
        if (rootId[r] < 0) rootId[r] = ns++;
        faceShell[f] = rootId[r];
        for (int k = st[f]; k < st[f + 1]; ++k) uvShell[c.fuv[k]] = rootId[r];
    }
    return ns;
}

int uvUnfold(const UvCage& c, const float* uvIn, const unsigned char* pinned, int iterations, float scaleToDensity,
             std::vector<float>& uvOut, UvUnfoldStats* stats) {
    if (uvValidate(c) < 0 || !uvIn) return -1;
    if (!(scaleToDensity > 0) || !std::isfinite(scaleToDensity)) scaleToDensity = 1.0f;
    iterations = std::max(0, std::min(iterations, 1000));
    uvOut.assign(uvIn, uvIn + 2 * (size_t)c.nuv);
    std::vector<int> uvShell, faceShell;
    const int ns = uvShells(c, uvShell, faceShell);
    const std::vector<int> st = faceStarts(c);
    const auto byShell = facesByShell(faceShell, ns);
    std::vector<int> g2l((size_t)c.nuv, -1);
    int flips = 0; double wsum = 0, ssum = 0;
    for (int s = 0; s < ns; ++s) {
        Shell S;
        buildShell(c, st, byShell[s], g2l, S);
        const int n = (int)S.uvs.size();
        if (n < 3 || S.tris.empty()) continue;
        std::vector<char> pin((size_t)n, 0);
        std::vector<double> u((size_t)n, 0.0), v((size_t)n, 0.0);
        int userPins = 0;
        double cx0 = 1e300, cy0 = 1e300, cx1 = -1e300, cy1 = -1e300;
        for (int i = 0; i < n; ++i) {
            const int g = S.uvs[i];
            const double iu = uvIn[2 * g], iv = uvIn[2 * g + 1];
            cx0 = std::min(cx0, iu); cx1 = std::max(cx1, iu); cy0 = std::min(cy0, iv); cy1 = std::max(cy1, iv);
            if (pinned && pinned[g]) { pin[i] = 1; u[i] = iu; v[i] = iv; ++userPins; }
        }
        std::vector<char> lscmPin = pin;
        int autoA = -1;
        if (userPins < 2) {
            // boundary UVs: polygon edges used once (in either direction)
            std::vector<std::pair<int, int>> es = S.edges;
            for (auto& e : es) if (e.first > e.second) std::swap(e.first, e.second);
            std::sort(es.begin(), es.end());
            std::vector<char> onB((size_t)n, 0);
            for (size_t i = 0; i < es.size();) {
                size_t j = i; while (j < es.size() && es[j] == es[i]) ++j;
                if (j - i == 1 && es[i].first != es[i].second) { onB[es[i].first] = 1; onB[es[i].second] = 1; }
                i = j;
            }
            std::vector<int> cand;
            for (int i = 0; i < n; ++i) if (onB[i]) cand.push_back(i);
            if (cand.size() < 2) { cand.resize((size_t)n); std::iota(cand.begin(), cand.end(), 0); }
            int a, b;
            if (userPins == 1) {
                a = (int)(std::find(pin.begin(), pin.end(), 1) - pin.begin());
                b = a; double fd = -1;
                for (int i : cand) { const double d = dot(sub(S.p3[i], S.p3[a]), sub(S.p3[i], S.p3[a])); if (i != a && d > fd) { fd = d; b = i; } }
                if (b == a) continue;
                const double d3 = std::sqrt(fd);
                double dx = uvIn[2 * S.uvs[b]] - u[a], dy = uvIn[2 * S.uvs[b] + 1] - v[a];
                const double dl = std::sqrt(dx * dx + dy * dy);
                if (dl > 1e-12) { dx /= dl; dy /= dl; } else { dx = 1; dy = 0; }
                u[b] = u[a] + dx * d3; v[b] = v[a] + dy * d3; lscmPin[b] = 1;
            } else {
                farthestPair(S, cand, a, b);
                if (a == b) continue;
                u[a] = 0; v[a] = 0; u[b] = len(sub(S.p3[b], S.p3[a])); v[b] = 0;
                lscmPin[a] = lscmPin[b] = 1;
                autoA = a;
            }
        }
        if (!lscm(S, lscmPin, u, v)) {
            // keep the input for this shell, but report it as fully flipped so the caller sees the failure
            flips += (int)S.tris.size();
            continue;
        }
        if (!userPins) {   // LSCM keeps the orientation; the two pins only fix a similarity, so mirror if needed
            double tot = 0;
            for (const auto& t : S.tris) tot += signedArea(u.data(), v.data(), t.a, t.b, t.c);
            if (tot < 0) for (int i = 0; i < n; ++i) u[i] = -u[i];
        }
        std::vector<char> arapPin = pin;
        if (!userPins) arapPin[autoA >= 0 ? autoA : 0] = 1;
        else if (userPins == 1) arapPin = pin;   // one user pin is enough for ARAP
        arap(S, arapPin, iterations, u, v);
        if (!userPins) {
            // lay the shell along its minimum-area bounding box (the auto pins are arbitrary, e.g. a cylinder's
            // opposite corners, which would leave the unfolded rectangle on its diagonal)
            std::vector<P2> pts((size_t)n);
            for (int i = 0; i < n; ++i) pts[i] = {u[i], v[i]};
            double ang = 0;
            if (minBoxAngle(pts, ang)) {
                const double cs = std::cos(-ang), sn = std::sin(-ang);
                for (int i = 0; i < n; ++i) { const double x = u[i], y = v[i]; u[i] = x * cs - y * sn; v[i] = x * sn + y * cs; }
            }
            double a2 = 0, a3 = 0;
            for (const auto& t : S.tris) { a2 += std::fabs(signedArea(u.data(), v.data(), t.a, t.b, t.c)); a3 += t.area; }
            const double k = a2 > 0 ? std::sqrt(a3 * scaleToDensity / a2) : 1.0;
            double x0 = 1e300, y0 = 1e300, x1 = -1e300, y1 = -1e300;
            for (int i = 0; i < n; ++i) { u[i] *= k; v[i] *= k; x0 = std::min(x0, u[i]); x1 = std::max(x1, u[i]); y0 = std::min(y0, v[i]); y1 = std::max(y1, v[i]); }
            const double tx = 0.5 * (cx0 + cx1) - 0.5 * (x0 + x1), ty = 0.5 * (cy0 + cy1) - 0.5 * (y0 + y1);
            for (int i = 0; i < n; ++i) { u[i] += tx; v[i] += ty; }
        }
        shellStats(S, u, v, flips, wsum, ssum);
        for (int i = 0; i < n; ++i) {
            const int g = S.uvs[i];
            if (pin[i]) continue;   // user pins stay bit-exact
            uvOut[2 * g] = (float)u[i]; uvOut[2 * g + 1] = (float)v[i];
        }
    }
    if (stats) { stats->shells = ns; stats->flips = flips; stats->stretch = wsum > 0 ? (float)(ssum / wsum) : 1.0f; }
    return ns;
}

// ------------------------------------------------------------------------------------------------ layout

namespace {

struct PackRect { double w, h; int id; };
struct Placed { double x, y; bool rot; };

// Skyline bottom-left packing in a strip of width W. Returns the used height; usedW gets the used width.
double skyline(const std::vector<PackRect>& rs, double W, bool allowRot, std::vector<Placed>& out, double& usedW) {
    struct Seg { double x, y, w; };
    std::vector<Seg> sky{{0, 0, W}};
    out.assign(rs.size(), Placed{0, 0, false});
    double usedH = 0; usedW = 0;
    for (size_t r = 0; r < rs.size(); ++r) {
        double bestTop = 1e300, bestX = 0, bestY = 0; int bestI = -1; bool bestRot = false; double bw = 0, bh = 0;
        for (int o = 0; o < (allowRot ? 2 : 1); ++o) {
            const double w = o ? rs[r].h : rs[r].w, h = o ? rs[r].w : rs[r].h;
            if (w > W * (1 + 1e-9)) continue;
            for (size_t i = 0; i < sky.size(); ++i) {
                const double x = sky[i].x;
                if (x + w > W * (1 + 1e-9)) break;
                double y = 0, reach = x;
                for (size_t j = i; j < sky.size() && reach < x + w - 1e-12; ++j) { y = std::max(y, sky[j].y); reach = sky[j].x + sky[j].w; }
                const double top = y + h;
                if (top < bestTop - 1e-12 || (std::fabs(top - bestTop) <= 1e-12 && x < bestX)) {
                    bestTop = top; bestX = x; bestY = y; bestI = (int)i; bestRot = o == 1; bw = w; bh = h;
                }
            }
        }
        if (bestI < 0) return 1e300;   // wider than the strip
        out[r] = {bestX, bestY, bestRot};
        usedH = std::max(usedH, bestY + bh); usedW = std::max(usedW, bestX + bw);
        // raise the skyline over [bestX, bestX + bw)
        std::vector<Seg> ns; ns.reserve(sky.size() + 2);
        const double x0 = bestX, x1 = bestX + bw;
        bool inserted = false;
        for (const auto& s : sky) {
            const double s0 = s.x, s1 = s.x + s.w;
            if (s1 <= x0 + 1e-12 || s0 >= x1 - 1e-12) {
                if (s0 >= x1 - 1e-12 && !inserted) { ns.push_back({x0, bestY + bh, bw}); inserted = true; }
                ns.push_back(s); continue;
            }
            if (s0 < x0) ns.push_back({s0, s.y, x0 - s0});
            if (!inserted) { ns.push_back({x0, bestY + bh, bw}); inserted = true; }
            if (s1 > x1) ns.push_back({x1, s.y, s1 - x1});
        }
        if (!inserted) ns.push_back({x0, bestY + bh, bw});
        // merge neighbours at the same height
        sky.clear();
        for (const auto& s : ns) {
            if (s.w <= 1e-15) continue;
            if (!sky.empty() && std::fabs(sky.back().y - s.y) < 1e-15 && std::fabs(sky.back().x + sky.back().w - s.x) < 1e-12) sky.back().w += s.w;
            else sky.push_back(s);
        }
    }
    return usedH;
}

}  // namespace

int uvLayout(const UvCage& c, const float* uvIn, const UvLayoutSettings& set, std::vector<float>& uvOut) {
    if (uvValidate(c) < 0 || !uvIn) return -1;
    uvOut.assign(uvIn, uvIn + 2 * (size_t)c.nuv);
    std::vector<int> uvShell, faceShell;
    const int ns = uvShells(c, uvShell, faceShell);
    if (!ns) return 0;
    const std::vector<int> st = faceStarts(c);
    const auto byShell = facesByShell(faceShell, ns);
    std::vector<std::vector<int>> uvsOf((size_t)ns);
    for (int g = 0; g < c.nuv; ++g) if (uvShell[g] >= 0) uvsOf[uvShell[g]].push_back(g);
    std::vector<double> U(uvOut.begin(), uvOut.end());   // working copy in double

    const int rotate = std::max(0, std::min(2, set.rotate));
    const int mode = std::max(0, std::min(2, set.scaleMode));
    const double gapUV = std::max(0.0, (double)set.paddingPx) / std::max(1.0, (double)set.resolution);
    const double margin = std::max(0.0, std::min(0.45, (double)set.margin));

    // 1. texel density: 2D area / 3D area equal across shells
    if (mode == 1) {
        for (int s = 0; s < ns; ++s) {
            double a2 = 0, a3 = 0;
            for (int f : byShell[s]) {
                const int s0 = st[f];
                for (int k = 1; k + 1 < c.sizes[f]; ++k) {
                    const int g0 = c.fuv[s0], g1 = c.fuv[s0 + k], g2 = c.fuv[s0 + k + 1];
                    a2 += std::fabs(signedArea(&U[0], &U[1], 2 * g0, 2 * g1, 2 * g2) * 1.0);
                    const V3 A = vpos(c, c.fv[s0]), B = vpos(c, c.fv[s0 + k]), C = vpos(c, c.fv[s0 + k + 1]);
                    a3 += 0.5 * len(cross(sub(B, A), sub(C, A)));
                }
            }
            if (!(a2 > 1e-30) || !(a3 > 0)) continue;
            const double k = std::sqrt(a3 / a2);
            for (int g : uvsOf[s]) { U[2 * g] *= k; U[2 * g + 1] *= k; }
        }
    }
    // 2. free rotation: the minimum-area bounding box from the hull's edge directions
    if (rotate == 2) {
        for (int s = 0; s < ns; ++s) {
            std::vector<P2> pts; pts.reserve(uvsOf[s].size());
            for (int g : uvsOf[s]) pts.push_back({U[2 * g], U[2 * g + 1]});
            double bestAng = 0;
            if (!minBoxAngle(pts, bestAng)) continue;
            const double cs = std::cos(-bestAng), sn = std::sin(-bestAng);
            for (int g : uvsOf[s]) { const double x = U[2 * g], y = U[2 * g + 1]; U[2 * g] = x * cs - y * sn; U[2 * g + 1] = x * sn + y * cs; }
        }
    }
    // 3. boxes
    std::vector<double> bx0((size_t)ns), by0((size_t)ns), bw((size_t)ns), bh((size_t)ns);
    double area = 0, maxDim = 0;
    for (int s = 0; s < ns; ++s) {
        double x0 = 1e300, y0 = 1e300, x1 = -1e300, y1 = -1e300;
        for (int g : uvsOf[s]) { x0 = std::min(x0, U[2 * g]); x1 = std::max(x1, U[2 * g]); y0 = std::min(y0, U[2 * g + 1]); y1 = std::max(y1, U[2 * g + 1]); }
        bx0[s] = x0; by0[s] = y0; bw[s] = std::max(0.0, x1 - x0); bh[s] = std::max(0.0, y1 - y0);
        area += bw[s] * bh[s]; maxDim = std::max(maxDim, std::max(bw[s], bh[s]));
    }
    if (!(maxDim > 0)) maxDim = 1;
    const bool allowRot = rotate >= 1;
    // 4. pack; the gap in packing units is gapUV / finalScale, so iterate until the final scale is not smaller
    //    than the one the gap was computed for
    const double avail = mode == 2 ? 1.0 : 1.0 - 2 * margin;
    double scale = mode == 2 ? 1.0 : avail / std::max(std::sqrt(std::max(area, 1e-30)) * 1.1, maxDim);
    std::vector<Placed> best; double bestSide = 1e300, bestW = 0, bestH = 0, bestG = 0;
    const double tries[] = {0.7, 0.85, 1.0, 1.15, 1.3, 1.6, 2.0};
    const int ntries = ns > 3000 ? 2 : 7;
    for (int round = 0; round < 24; ++round) {
        const double g = gapUV / scale;
        std::vector<PackRect> rs((size_t)ns);
        double tot = 0, minW = 0;
        for (int s = 0; s < ns; ++s) {
            double w = bw[s], h = bh[s];
            if (allowRot && h > w) std::swap(w, h);   // lie down: sorted by height, wide boxes pack tighter
            rs[s] = {w + g, h + g, s};
            tot += rs[s].w * rs[s].h;
            minW = std::max(minW, allowRot ? std::min(rs[s].w, rs[s].h) : rs[s].w);
        }
        std::vector<int> order((size_t)ns); std::iota(order.begin(), order.end(), 0);
        std::stable_sort(order.begin(), order.end(), [&](int a, int b) { return rs[a].h > rs[b].h || (rs[a].h == rs[b].h && rs[a].w > rs[b].w); });
        std::vector<PackRect> sorted((size_t)ns);
        for (int i = 0; i < ns; ++i) sorted[i] = rs[order[i]];
        double side = 1e300, uw = 0, uh = 0; std::vector<Placed> pl;
        for (int t = (ntries == 2 ? 2 : 0); t < (ntries == 2 ? 4 : 7); ++t) {
            const double W = std::max(minW, std::max(std::sqrt(tot) * tries[t], allowRot ? 0.0 : minW));
            std::vector<Placed> out; double usedW = 0;
            const double usedH = skyline(sorted, W, allowRot, out, usedW);
            if (usedH >= 1e299) continue;
            const double sd = std::max(usedW - g, usedH - g);
            if (sd < side) { side = sd; uw = usedW; uh = usedH; pl.resize((size_t)ns); for (int i = 0; i < ns; ++i) pl[order[i]] = out[i]; }
        }
        if (side >= 1e299) break;
        const double newScale = mode == 2 ? 1.0 : avail / std::max(side, 1e-30);
        best = pl; bestSide = side; bestW = uw; bestH = uh; bestG = g;
        if (mode == 2 || newScale >= scale * (1 - 1e-9)) { scale = newScale; break; }
        scale = newScale * 0.995;
    }
    (void)bestSide; (void)bestW; (void)bestH;
    if (best.empty()) return ns;
    if (mode != 2) scale = avail / std::max(std::max(bestW, bestH) - bestG, 1e-30);
    const double off = mode == 2 ? margin : margin;
    // 5. place: lie down (if swapped), packer rotation, translate to the slot, final scale
    for (int s = 0; s < ns; ++s) {
        const bool laid = allowRot && bh[s] > bw[s];
        const bool rot = (laid != best[s].rot);   // two quarter turns cancel
        for (int g : uvsOf[s]) {
            double x = U[2 * g] - bx0[s], y = U[2 * g + 1] - by0[s];
            if (rot) { const double t = x; x = bh[s] - y; y = t; }   // +90 degrees about the box, kept in the positive quadrant
            x += best[s].x; y += best[s].y;
            uvOut[2 * g] = (float)(off + x * scale);
            uvOut[2 * g + 1] = (float)(off + y * scale);
        }
    }
    return ns;
}

// ------------------------------------------------------------------------------------------------ automatic (xatlas)
// keepSeams = false: the cage goes to xatlas as polygons (MeshDecl::faceVertexCount; LOKI's copy fixes xatlas's
// corner mapping for mixed polygon sizes, see THIRD_PARTY_NOTICES.md), xatlas grows charts over the triangles,
// parameterizes (planar / orthogonal / LSCM / piecewise) and packs. Each output vertex is one UV index; every
// input corner points at the output vertex written for it. A polygon whose triangles ended in two charts is
// re-joined: the charts' UV indices that meet in that polygon are merged into one shell, which is unfolded again
// by uvUnfold and the result packed again by xatlas (the keepSeams path below).
// keepSeams = true: the existing shells are unfolded by uvUnfold (world scale, so density is uniform) and xatlas
// only packs them (AddUvMesh; each shell gets its own material so overlapping shells are never merged).
// Corners xatlas leaves without a chart (zero-area faces) take the UV of another corner of their face.
namespace {

void xaQuiet() { xatlas::SetPrint(nullptr, false); }

bool packUvShells(const UvCage& c, const std::vector<float>& uv, const UvAutoOptions& o, UvAutoResult& out) {
    const std::vector<int> st = faceStarts(c);
    std::vector<int> uvShell, faceShell;
    uvShells(c, uvShell, faceShell);
    std::vector<uint32_t> idx; std::vector<uint32_t> mat;
    for (int f = 0; f < c.nf; ++f)
        for (int k = 1; k + 1 < c.sizes[f]; ++k) {
            idx.push_back((uint32_t)c.fuv[st[f]]); idx.push_back((uint32_t)c.fuv[st[f] + k]); idx.push_back((uint32_t)c.fuv[st[f] + k + 1]);
            mat.push_back((uint32_t)faceShell[f]);
        }
    out.uv.assign(uv.begin(), uv.end());
    out.fuv.assign(c.fuv, c.fuv + st[c.nf]);
    if (idx.empty()) return true;
    xaQuiet();
    xatlas::Atlas* A = xatlas::Create();
    xatlas::UvMeshDecl d;
    d.vertexUvData = uv.data(); d.vertexCount = (uint32_t)c.nuv; d.vertexStride = 8;
    d.indexData = idx.data(); d.indexCount = (uint32_t)idx.size(); d.indexFormat = xatlas::IndexFormat::UInt32;
    d.faceMaterialData = mat.data();
    if (xatlas::AddUvMesh(A, d) != xatlas::AddMeshError::Success) { xatlas::Destroy(A); return false; }
    xatlas::ChartOptions co;
    xatlas::PackOptions po;
    po.padding = (uint32_t)std::max(0, o.padding); po.resolution = (uint32_t)std::max(0, o.resolution);
    po.texelsPerUnit = std::max(0.0f, o.texelsPerUnit);
    po.bilinear = o.bilinear; po.blockAlign = o.blockAlign; po.bruteForce = o.bruteForce;
    po.rotateCharts = o.rotateCharts; po.rotateChartsToAxis = o.rotateChartsToAxis;
    xatlas::Generate(A, co, po);
    if (A->meshCount < 1 || A->width == 0 || A->height == 0) { xatlas::Destroy(A); return false; }
    const xatlas::Mesh& m = A->meshes[0];
    const double inv = 1.0 / std::max(A->width, A->height);
    std::vector<char> ok((size_t)c.nuv, 0);
    for (uint32_t i = 0; i < m.vertexCount && i < (uint32_t)c.nuv; ++i) {
        const xatlas::Vertex& v = m.vertexArray[i];
        if (v.chartIndex < 0) continue;
        out.uv[2 * v.xref] = (float)(v.uv[0] * inv); out.uv[2 * v.xref + 1] = (float)(v.uv[1] * inv); ok[v.xref] = 1;
    }
    xatlas::Destroy(A);
    // UVs only on ignored (zero-area) triangles: take a placed UV of the same face
    for (int f = 0; f < c.nf; ++f) {
        int good = -1;
        for (int k = st[f]; k < st[f + 1]; ++k) if (ok[c.fuv[k]]) { good = c.fuv[k]; break; }
        for (int k = st[f]; k < st[f + 1]; ++k) {
            const int g = c.fuv[k];
            if (ok[g]) continue;
            out.uv[2 * g] = good >= 0 ? out.uv[2 * good] : 0.0f; out.uv[2 * g + 1] = good >= 0 ? out.uv[2 * good + 1] : 0.0f;
        }
    }
    return true;
}

}  // namespace

int uvAuto(const UvCage& cin, const float* uvIn, bool keepSeams, const UvAutoOptions& o, UvAutoResult& out) {
    out = UvAutoResult();
    UvCage c = cin;
    const int nc = uvValidate(c, keepSeams);
    if (nc < 0) return -1;
    if (c.nf == 0) return 0;
    const std::vector<int> st = faceStarts(c);
    if (keepSeams) {
        std::vector<float> zero;
        if (!uvIn) { zero.assign(2 * (size_t)c.nuv, 0.0f); uvIn = zero.data(); }
        std::vector<float> uv;
        if (uvUnfold(c, uvIn, nullptr, o.unfoldIterations, 1.0f, uv) < 0) return -1;
        if (!packUvShells(c, uv, o, out)) return -1;
        return uvShellCount(c);
    }
    // xatlas cuts: polygons when every face has <= 255 corners, else fan triangles
    bool poly = true;
    for (int f = 0; f < c.nf; ++f) if (c.sizes[f] > 255) poly = false;
    std::vector<uint32_t> idx; std::vector<uint8_t> fvc; std::vector<int> triCorner;   // fan: output corner -> input corner
    if (poly) {
        idx.assign(c.fv, c.fv + nc);
        fvc.resize((size_t)c.nf);
        for (int f = 0; f < c.nf; ++f) fvc[f] = (uint8_t)c.sizes[f];
    } else {
        for (int f = 0; f < c.nf; ++f)
            for (int k = 1; k + 1 < c.sizes[f]; ++k) {
                const int cs[3] = {st[f], st[f] + k, st[f] + k + 1};
                for (int q : cs) { idx.push_back((uint32_t)c.fv[q]); triCorner.push_back(q); }
            }
    }
    xaQuiet();
    xatlas::Atlas* A = xatlas::Create();
    xatlas::MeshDecl d;
    d.vertexPositionData = c.pos; d.vertexCount = (uint32_t)c.nv; d.vertexPositionStride = 12;
    d.indexData = idx.data(); d.indexCount = (uint32_t)idx.size(); d.indexFormat = xatlas::IndexFormat::UInt32;
    if (poly) { d.faceVertexCount = fvc.data(); d.faceCount = (uint32_t)c.nf; }
    if (xatlas::AddMesh(A, d) != xatlas::AddMeshError::Success) { xatlas::Destroy(A); return -1; }
    xatlas::ChartOptions co;
    co.maxChartArea = o.maxChartArea; co.maxBoundaryLength = o.maxBoundaryLength;
    co.normalDeviationWeight = o.normalDeviationWeight; co.roundnessWeight = o.roundnessWeight;
    co.straightnessWeight = o.straightnessWeight; co.normalSeamWeight = o.normalSeamWeight;
    co.textureSeamWeight = o.textureSeamWeight; co.maxCost = o.maxCost;
    co.maxIterations = (uint32_t)std::max(1, o.maxIterations);
    xatlas::PackOptions po;
    po.padding = (uint32_t)std::max(0, o.padding); po.resolution = (uint32_t)std::max(0, o.resolution);
    po.texelsPerUnit = std::max(0.0f, o.texelsPerUnit);
    po.bilinear = o.bilinear; po.blockAlign = o.blockAlign; po.bruteForce = o.bruteForce;
    po.rotateCharts = o.rotateCharts; po.rotateChartsToAxis = o.rotateChartsToAxis;
    xatlas::Generate(A, co, po);
    if (A->meshCount < 1 || A->width == 0 || A->height == 0) { xatlas::Destroy(A); return -1; }
    const xatlas::Mesh& m = A->meshes[0];
    const double inv = 1.0 / std::max(A->width, A->height);
    const float texelsPerUnit = A->texelsPerUnit;
    const int nOut = (int)m.vertexCount;
    std::vector<float> uv(2 * (size_t)nOut + 2, 0.0f);
    std::vector<int> chartOf((size_t)nOut + 1, -1);
    for (int i = 0; i < nOut; ++i) {
        uv[2 * i] = (float)(m.vertexArray[i].uv[0] * inv); uv[2 * i + 1] = (float)(m.vertexArray[i].uv[1] * inv);
        chartOf[i] = m.vertexArray[i].chartIndex;
    }
    std::vector<int> fuv((size_t)nc, -1);
    if (poly) {
        for (int k = 0; k < nc && k < (int)m.indexCount; ++k) if (m.indexArray[k] != UINT32_MAX && (int)m.indexArray[k] < nOut) fuv[k] = (int)m.indexArray[k];
    } else {
        for (size_t k = 0; k < triCorner.size() && k < m.indexCount; ++k) {
            const uint32_t ov = m.indexArray[k];
            if (ov == UINT32_MAX || (int)ov >= nOut) continue;
            const int q = triCorner[k];
            if (fuv[q] < 0 || (chartOf[fuv[q]] < 0 && chartOf[ov] >= 0)) fuv[q] = (int)ov;
        }
    }
    xatlas::Destroy(A);
    // corners without a chart vertex: share a charted corner of the same face (or one extra UV at 0,0)
    int extra = -1;
    for (int f = 0; f < c.nf; ++f) {
        int good = -1;
        for (int k = st[f]; k < st[f + 1]; ++k) if (fuv[k] >= 0 && chartOf[fuv[k]] >= 0) { good = fuv[k]; break; }
        for (int k = st[f]; k < st[f + 1]; ++k) {
            if (fuv[k] >= 0 && (chartOf[fuv[k]] >= 0 || good < 0)) continue;
            if (good >= 0) fuv[k] = good;
            else { if (extra < 0) extra = nOut; fuv[k] = extra; }
        }
    }
    int nuvOut = extra >= 0 ? nOut + 1 : nOut;
    uv.resize(2 * (size_t)nuvOut);
    // compact: drop output UVs no corner points at (a split polygon's corner written by its other triangle)
    {
        std::vector<int> remap((size_t)nuvOut, -1);
        int n = 0;
        for (int k = 0; k < nc; ++k) if (remap[fuv[k]] < 0) remap[fuv[k]] = n++;
        std::vector<float> cu(2 * (size_t)n);
        std::vector<int> cc((size_t)n, -1);
        for (int g = 0; g < nuvOut; ++g) if (remap[g] >= 0) {
            cu[2 * remap[g]] = uv[2 * g]; cu[2 * remap[g] + 1] = uv[2 * g + 1];
            cc[remap[g]] = g < nOut ? chartOf[g] : -1;
        }
        for (int k = 0; k < nc; ++k) fuv[k] = remap[fuv[k]];
        uv.swap(cu); chartOf.swap(cc); nuvOut = n;
    }
    // polygons spread over more than one chart
    int split = 0;
    std::vector<char> splitFace((size_t)c.nf, 0);
    for (int f = 0; f < c.nf; ++f) {
        const int c0 = chartOf[fuv[st[f]]];
        for (int k = st[f] + 1; k < st[f + 1]; ++k) if (chartOf[fuv[k]] != c0) { ++split; splitFace[f] = 1; break; }
    }
    out.uv = uv; out.fuv = fuv;
    UvCage r = c; r.fuv = out.fuv.data(); r.nuv = nuvOut; r.nc = nc;
    if (split) {
        // uvShells joins every UV of a polygon, so the charts meeting in a split polygon are one shell now: those
        // shells are unfolded again (at the atlas's texel density; the other shells are pinned, so untouched)
        // and everything is packed again
        std::vector<int> uvShell, faceShell;
        const int ns = uvShells(r, uvShell, faceShell);
        std::vector<char> redo((size_t)ns, 0);
        for (int f = 0; f < c.nf; ++f) if (splitFace[f]) redo[faceShell[f]] = 1;
        std::vector<unsigned char> pin((size_t)nuvOut, 0);
        for (int g = 0; g < nuvOut; ++g) pin[g] = uvShell[g] >= 0 && !redo[uvShell[g]];
        const double k = (double)texelsPerUnit * inv;
        std::vector<float> uf;
        if (uvUnfold(r, out.uv.data(), pin.data(), o.unfoldIterations, (float)(k * k), uf) < 0) return -1;
        UvAutoResult again;
        if (!packUvShells(r, uf, o, again)) return -1;
        out.uv = again.uv;
        out.splitFaces = split;
    }
    out.charts = uvShellCount(r);
    return out.charts;
}

}  // namespace sculpt
