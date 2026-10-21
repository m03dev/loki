// Catmull-Clark on a polygon cage - see sculpt/cage_subdiv.h. Written to give the very same result as
// ForgePoly.smooth in app/ui/forge_poly.js (native/sculpt/wasm/test/test_cage.js checks it on cubes, grids,
// n-gons, open borders and non-manifold edges), only much faster on big cages.
#include "sculpt/cage_subdiv.h"

#include <cstdint>
#include <unordered_map>

namespace sculpt {

namespace {
struct Edge { int a, b; int f0 = -1, f1 = -1, nf = 0; int id = 0; };
inline uint64_t key(int a, int b) { if (a > b) { int t = a; a = b; b = t; } return ((uint64_t)(uint32_t)a << 32) | (uint32_t)b; }
}  // namespace

bool cageSubdivideOnce(const Cage& in, Cage& out) {
    const int nv = (int)(in.v.size() / 3), nf = (int)in.sizes.size();
    std::vector<int> start((size_t)nf + 1, 0);
    for (int f = 0; f < nf; ++f) start[f + 1] = start[f] + in.sizes[f];
    if ((size_t)start[nf] != in.idx.size()) return false;
    for (int i : in.idx) if (i < 0 || i >= nv) return false;
    const double* V = in.v.data();

    // face points (the centroids)
    std::vector<double> fp((size_t)nf * 3, 0.0);
    for (int f = 0; f < nf; ++f) {
        double s[3] = {0, 0, 0};
        const int n = in.sizes[f];
        for (int k = 0; k < n; ++k) { const double* p = V + 3 * in.idx[start[f] + k]; s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; }
        const double r = 1.0 / n;
        fp[3 * f] = s[0] * r; fp[3 * f + 1] = s[1] * r; fp[3 * f + 2] = s[2] * r;
    }

    // edges in first-seen order (the JS Map's insertion order), each vertex's faces (per corner) and edges
    std::vector<Edge> edges; edges.reserve(in.idx.size());
    std::unordered_map<uint64_t, int> emap; emap.reserve(in.idx.size() * 2);
    std::vector<std::vector<int>> vf((size_t)nv), ve((size_t)nv);
    for (int f = 0; f < nf; ++f) {
        const int n = in.sizes[f], s0 = start[f];
        for (int k = 0; k < n; ++k) {
            const int a = in.idx[s0 + k], b = in.idx[s0 + (k + 1) % n];
            const uint64_t kk = key(a, b);
            auto it = emap.find(kk);
            int e;
            if (it == emap.end()) {
                e = (int)edges.size(); emap.emplace(kk, e);
                Edge E; E.a = a; E.b = b; edges.push_back(E);
                ve[a].push_back(e); ve[b].push_back(e);
            } else e = it->second;
            Edge& E = edges[e];
            if (E.nf == 0) E.f0 = f; else if (E.nf == 1) E.f1 = f;
            E.nf++;
            vf[a].push_back(f);
        }
    }

    out.v.clear(); out.sizes.clear(); out.idx.clear();
    out.v.reserve(((size_t)nv + nf + edges.size()) * 3);
    auto push = [&](double x, double y, double z) { out.v.push_back(x); out.v.push_back(y); out.v.push_back(z); };

    // vertex points
    for (int i = 0; i < nv; ++i) {
        const double* p = V + 3 * i;
        int nb = 0, q[2] = {-1, -1};
        for (int e : ve[i]) if (edges[e].nf == 1) { if (nb < 2) q[nb] = edges[e].a == i ? edges[e].b : edges[e].a; nb++; }
        if (nb) {
            if (nb != 2) { push(p[0], p[1], p[2]); continue; }
            const double* a = V + 3 * q[0]; const double* b = V + 3 * q[1];
            push(p[0] * 0.75 + (a[0] + b[0]) * 0.125, p[1] * 0.75 + (a[1] + b[1]) * 0.125, p[2] * 0.75 + (a[2] + b[2]) * 0.125);
            continue;
        }
        const int n = (int)vf[i].size();
        if (!n) { push(p[0], p[1], p[2]); continue; }
        double F[3] = {0, 0, 0}, R[3] = {0, 0, 0};
        for (int f : vf[i]) { F[0] += fp[3 * f]; F[1] += fp[3 * f + 1]; F[2] += fp[3 * f + 2]; }
        for (int c = 0; c < 3; ++c) F[c] *= 1.0 / n;
        for (int e : ve[i]) {
            const double* a = V + 3 * edges[e].a; const double* b = V + 3 * edges[e].b;
            for (int c = 0; c < 3; ++c) R[c] += (a[c] + b[c]) * 0.5;
        }
        const double rn = 1.0 / (double)ve[i].size();
        for (int c = 0; c < 3; ++c) R[c] *= rn;
        const double k = 1.0 / n;
        push((F[0] + R[0] * 2 + p[0] * (n - 3)) * k, (F[1] + R[1] * 2 + p[1] * (n - 3)) * k, (F[2] + R[2] * 2 + p[2] * (n - 3)) * k);
    }
    // face points, then edge points
    const int fBase = nv;
    for (int f = 0; f < nf; ++f) push(fp[3 * f], fp[3 * f + 1], fp[3 * f + 2]);
    for (Edge& E : edges) {
        E.id = (int)(out.v.size() / 3);
        const double* a = V + 3 * E.a; const double* b = V + 3 * E.b;
        if (E.nf == 2) {
            const double* f0 = fp.data() + 3 * E.f0; const double* f1 = fp.data() + 3 * E.f1;
            push(((a[0] + b[0]) + (f0[0] + f1[0])) * 0.25, ((a[1] + b[1]) + (f0[1] + f1[1])) * 0.25, ((a[2] + b[2]) + (f0[2] + f1[2])) * 0.25);
        } else push((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5);
    }
    // every n-gon -> n quads: [corner, edge to next, face point, edge from previous]
    out.sizes.reserve(in.idx.size()); out.idx.reserve(in.idx.size() * 4);
    for (int f = 0; f < nf; ++f) {
        const int n = in.sizes[f], s0 = start[f];
        for (int k = 0; k < n; ++k) {
            const int prev = in.idx[s0 + (k + n - 1) % n], cur = in.idx[s0 + k], next = in.idx[s0 + (k + 1) % n];
            out.sizes.push_back(4);
            out.idx.push_back(cur);
            out.idx.push_back(edges[emap[key(cur, next)]].id);
            out.idx.push_back(fBase + f);
            out.idx.push_back(edges[emap[key(prev, cur)]].id);
        }
    }
    return true;
}

int cageSubdivide(const Cage& in, int levels, int maxFaces, Cage& out) {
    Cage a = in, b;
    int done = 0;
    for (int k = 0; k < levels && (long long)a.sizes.size() * 4 <= (long long)maxFaces; ++k) {
        if (!cageSubdivideOnce(a, b)) return -1;
        a.v.swap(b.v); a.sizes.swap(b.sizes); a.idx.swap(b.idx);
        done++;
    }
    out = std::move(a);
    return done;
}

void cageTriangulate(const Cage& c, std::vector<int>& tris) {
    tris.clear();
    int s = 0;
    for (int n : c.sizes) {
        for (int k = 1; k + 1 < n; ++k) { tris.push_back(c.idx[s]); tris.push_back(c.idx[s + k]); tris.push_back(c.idx[s + k + 1]); }
        s += n;
    }
}

}  // namespace sculpt
