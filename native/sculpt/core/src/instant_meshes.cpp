// Wrapper around the vendored Instant Meshes pipeline (third_party/instant-meshes,
// BSD-3; see THIRD_PARTY_NOTICES.md). Mirrors batch.cpp without file I/O and
// replaces its BVH-based smoothing with Sculpting engine's own projection.
#include "sculpt/instant_meshes.h"
#include "sculpt/bvh.h"
#include "sculpt/voxel_remesh.h"  // closestPointOnTriangle

#include "dedge.h"
#include "extract.h"
#include "field.h"
#include "hierarchy.h"
#include "meshstats.h"
#include "normal.h"
#include "subdivide.h"

#include <chrono>
#include <map>
#include <set>
#include <sstream>

// defined in third_party/instant-meshes/src/field.cpp (not in its header)
void freeze_ivars_orientations(MultiResolutionHierarchy& mRes, int level, bool extrinsic, int rosy);
void freeze_ivars_positions(MultiResolutionHierarchy& mRes, int level, bool extrinsic, int posy);

namespace sculpt {

static InstantMeshesResult runOnce(const Mesh& src, const InstantMeshesSettings& st, float calib) {
    InstantMeshesResult res;
    auto t0 = std::chrono::steady_clock::now();
    // Instant Meshes prints progress to std::cout; keep the host's console clean.
    std::stringstream sink;
    std::streambuf* old = std::cout.rdbuf(sink.rdbuf());
    struct Restore { std::streambuf* o; ~Restore() { std::cout.rdbuf(o); } } restore{old};
    try {
        // live triangles + compact vertex numbering
        std::vector<int> remap(src.positions.size(), -1);
        std::vector<Vec3> pts;
        std::vector<Tri> tris;
        for (const Tri& f : src.tris) {
            if (f[0] < 0) continue;
            Tri g;
            for (int k = 0; k < 3; ++k) {
                if (remap[f[k]] < 0) { remap[f[k]] = (int)pts.size(); pts.push_back(src.positions[f[k]]); }
                g[k] = remap[f[k]];
            }
            if (g[0] == g[1] || g[1] == g[2] || g[0] == g[2]) continue;
            tris.push_back(g);
        }
        if (tris.empty()) { res.error = "empty mesh"; return res; }
        MatrixXu F(3, tris.size());
        MatrixXf V(3, pts.size()), N;
        for (size_t t = 0; t < tris.size(); ++t)
            for (int k = 0; k < 3; ++k) F(k, t) = (uint32_t)tris[t][k];
        for (size_t v = 0; v < pts.size(); ++v) V.col(v) = Vector3f(pts[v].x, pts[v].y, pts[v].z);

        const int rosy = 4, posy = 4;
        const bool det = st.deterministic;
        MeshStats stats = compute_mesh_stats(F, V, det);
        int faceCount = std::max(16, (int)(calib * (st.pureQuad ? st.targetFaces / 4 : st.targetFaces)));
        Float faceArea = stats.mSurfaceArea / faceCount;
        Float scale = std::sqrt(faceArea);

        MultiResolutionHierarchy mRes;
        VectorXu V2E, E2E;
        VectorXb boundary, nonManifold;
        if (stats.mMaximumEdgeLength * 2 > scale || stats.mMaximumEdgeLength > stats.mAverageEdgeLength * 2) {
            build_dedge(F, V, V2E, E2E, boundary, nonManifold);
            subdivide(F, V, V2E, E2E, boundary, nonManifold, std::min(scale / 2, (Float)stats.mAverageEdgeLength * 2), det);
        }
        build_dedge(F, V, V2E, E2E, boundary, nonManifold);
        AdjacencyMatrix adj = generate_adjacency_matrix_uniform(F, V2E, E2E, nonManifold);
        std::set<uint32_t> creaseIn, creaseOut;
        if (st.creaseAngle >= 0)
            generate_crease_normals(F, V, V2E, E2E, boundary, nonManifold, st.creaseAngle, N, creaseIn);
        else
            generate_smooth_normals(F, V, V2E, E2E, nonManifold, N);
        VectorXf A;
        compute_dual_vertex_areas(F, V, V2E, E2E, nonManifold, A);
        mRes.setE2E(std::move(E2E));
        mRes.setAdj(std::move(adj));
        mRes.setF(std::move(F));
        mRes.setV(std::move(V));
        mRes.setA(std::move(A));
        mRes.setN(std::move(N));
        mRes.setScale(scale);
        mRes.build(det);
        mRes.resetSolution();

        if (st.alignToBoundaries) {
            mRes.clearConstraints();
            for (uint32_t i = 0; i < 3 * mRes.F().cols(); ++i) {
                if (mRes.E2E()[i] != INVALID) continue;
                uint32_t i0 = mRes.F()(i % 3, i / 3), i1 = mRes.F()((i + 1) % 3, i / 3);
                Vector3f p0 = mRes.V().col(i0), p1 = mRes.V().col(i1), e = p1 - p0;
                if (e.squaredNorm() <= 0) continue;
                e.normalize();
                mRes.CO().col(i0) = p0;
                mRes.CO().col(i1) = p1;
                mRes.CQ().col(i0) = mRes.CQ().col(i1) = e;
                mRes.CQw()[i0] = mRes.CQw()[i1] = mRes.COw()[i0] = mRes.COw()[i1] = 1.0f;
            }
            mRes.propagateConstraints(rosy, posy);
        }

        // Field optimization, run synchronously on this thread with the same
        // schedule as Instant Meshes' Optimizer::run() in hierarchical mode
        // (6 iterations per level, coarse to fine, solution copied down, ivars
        // frozen at the end). The original drives this from a worker thread
        // through condition variables; inside the host that handshake deadlocked.
        const int levelIterations = 6;
        auto noProgress = [](uint32_t) {};
        mRes.setFrozenQ(false);
        for (int level = mRes.levels() - 1; level >= 0; --level) {
            for (int it = 0; it < levelIterations; ++it)
                optimize_orientations(mRes, level, st.extrinsic, rosy, noProgress);
            if (level > 0) {
                const MatrixXf& srcField = mRes.Q(level);
                const MatrixXu& toUpper = mRes.toUpper(level - 1);
                MatrixXf& destField = mRes.Q(level - 1);
                const MatrixXf& Nl = mRes.N(level - 1);
                tbb::parallel_for(0u, (uint32_t)srcField.cols(), [&](uint32_t j) {
                    for (int k = 0; k < 2; ++k) {
                        uint32_t dest = toUpper(k, j);
                        if (dest == INVALID) continue;
                        Vector3f q = srcField.col(j), n = Nl.col(dest);
                        destField.col(dest) = q - n * n.dot(q);
                    }
                });
            }
        }
        if (!mRes.frozenQ()) freeze_ivars_orientations(mRes, 0, st.extrinsic, rosy);
        mRes.propagateSolution(rosy);  // Optimizer::stop() after orientations

        mRes.setFrozenO(false);
        for (int level = mRes.levels() - 1; level >= 0; --level) {
            for (int it = 0; it < levelIterations; ++it)
                optimize_positions(mRes, level, st.extrinsic, posy, noProgress);
            if (level > 0) {
                const MatrixXf& srcField = mRes.O(level);
                MatrixXf& destField = mRes.O(level - 1);
                const MatrixXf& Nl = mRes.N(level - 1);
                const MatrixXf& Vl = mRes.V(level - 1);
                const MatrixXu& toUpper = mRes.toUpper(level - 1);
                tbb::parallel_for(0u, (uint32_t)srcField.cols(), [&](uint32_t j) {
                    for (int k = 0; k < 2; ++k) {
                        uint32_t dest = toUpper(k, j);
                        if (dest == INVALID) continue;
                        Vector3f o = srcField.col(j), n = Nl.col(dest), v = Vl.col(dest);
                        o -= n * n.dot(o - v);
                        destField.col(dest) = o;
                    }
                });
            }
        }
        if (!mRes.frozenO()) freeze_ivars_positions(mRes, 0, st.extrinsic, posy);

        MatrixXf O, Ne, Nf;
        std::vector<std::vector<TaggedLink>> adjE;
        extract_graph(mRes, st.extrinsic, rosy, posy, adjE, O, Ne, creaseIn, creaseOut, det);
        MatrixXu Fo;
        extract_faces(adjE, O, Ne, Nf, Fo, posy, mRes.scale(), creaseOut, true, st.pureQuad, nullptr, 0);

        // ---- output polygons: quads, plus irregular faces encoded as edge
        // loops sharing F(2)==F(3) (same decoding as Instant Meshes' write_obj)
        std::map<uint32_t, std::map<uint32_t, uint32_t>> irregular;
        for (uint32_t f = 0; f < Fo.cols(); ++f) {
            if (Fo(2, f) == Fo(3, f)) { irregular[Fo(2, f)][Fo(0, f)] = Fo(1, f); continue; }
            res.counts.push_back(4);
            for (int j = 0; j < 4; ++j) res.indices.push_back((int)Fo(j, f));
            ++res.quads;
        }
        for (auto& item : irregular) {
            auto& next = item.second;
            uint32_t v = next.begin()->first, first = v;
            std::vector<int> loop;
            for (size_t i = 0; i <= next.size(); ++i) {
                loop.push_back((int)v);
                auto it = next.find(v);
                if (it == next.end()) break;
                v = it->second;
                if (v == first) break;
            }
            if (loop.size() >= 3) {
                res.counts.push_back((int)loop.size());
                res.indices.insert(res.indices.end(), loop.begin(), loop.end());
                ++res.others;
            }
        }
        // drop unreferenced vertices
        std::vector<int> used(O.cols(), -1);
        for (int& i : res.indices) {
            if (used[i] < 0) {
                used[i] = (int)res.positions.size();
                res.positions.push_back(Vec3{O(0, i), O(1, i), O(2, i)});
            }
            i = used[i];
        }

        // ---- project onto the source + tangential smoothing (replaces Instant
        // Meshes' own BVH smoothing pass)
        if (st.smoothIterations > 0 && !res.positions.empty()) {
            Mesh s2;
            s2.positions = src.positions;
            s2.tris = src.tris;
            s2.ensureAttributes();
            BVH bvh;
            bvh.build(s2);
            std::vector<std::vector<int>> nb(res.positions.size());
            size_t off = 0;
            for (int c : res.counts) {
                for (int k = 0; k < c; ++k) {
                    int a = res.indices[off + k], b = res.indices[off + (k + 1) % c];
                    nb[a].push_back(b);
                    nb[b].push_back(a);
                }
                off += c;
            }
            float h = (float)scale * (st.pureQuad ? 0.5f : 1.0f);
            std::vector<int> cand;
            const bool hasColor = src.color.size() == src.positions.size();
            auto sampleColor = [&](const Vec3& p) {
                bvh.queryTris(p, h * 2, cand);
                float best = 1e30f;
                Vec3 col{0.8f, 0.8f, 0.8f};
                for (int t : cand) {
                    const Tri& f = src.tris[t];
                    if (f[0] < 0) continue;
                    float u, w;
                    Vec3 c = closestPointOnTriangle(p, src.positions[f[0]], src.positions[f[1]], src.positions[f[2]], u, w);
                    float d = length2(c - p);
                    if (d < best) { best = d; col = src.color[f[0]] * (1 - u - w) + src.color[f[1]] * u + src.color[f[2]] * w; }
                }
                return col;
            };
            auto project = [&](Vec3& p) {
                bvh.queryTris(p, h, cand);
                float best = 1e30f;
                Vec3 q = p;
                for (int t : cand) {
                    const Tri& f = src.tris[t];
                    if (f[0] < 0) continue;
                    float u, w;
                    Vec3 c = closestPointOnTriangle(p, src.positions[f[0]], src.positions[f[1]], src.positions[f[2]], u, w);
                    float d = length2(c - p);
                    if (d < best) { best = d; q = c; }
                }
                p = q;
            };
            for (auto& p : res.positions) project(p);
            for (int it = 0; it < st.smoothIterations; ++it) {
                std::vector<Vec3> np = res.positions;
                for (size_t v = 0; v < np.size(); ++v) {
                    if (nb[v].empty()) continue;
                    Vec3 avg{};
                    for (int x : nb[v]) avg += res.positions[x];
                    np[v] = lerp(res.positions[v], avg / (float)nb[v].size(), 0.5f);
                }
                res.positions.swap(np);
                for (auto& p : res.positions) project(p);
            }
            if (hasColor) {
                res.color.resize(res.positions.size());
                for (size_t v = 0; v < res.positions.size(); ++v) res.color[v] = sampleColor(res.positions[v]);
            }
        }
        res.ok = res.quads > 0;
        if (!res.ok) res.error = "no faces extracted";
    }
#ifndef SCULPT_SINGLE_THREAD  // (WebAssembly build: no exceptions, see wasm/st_compat.h)
    catch (const std::exception& e) {
        res.error = e.what();
    }
#endif
    res.seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    return res;
}

// The extracted face count is only roughly surfaceArea/scale^2 (typically
// 55%, but anywhere from 50-180% depending on curvature and how much the input
// is subdivided), so: start from the typical ratio, and if the result misses
// the target by more than 15%, rescale once (count ~ 1/scale^2 ~ calib).
InstantMeshesResult instantMeshes(const Mesh& src, const InstantMeshesSettings& st) {
    float calib = 1.8f;
    InstantMeshesResult r = runOnce(src, st, calib);
    double secs = r.seconds;
    for (int attempt = 0; attempt < 2 && r.ok && !r.counts.empty(); ++attempt) {
        float ratio = (float)st.targetFaces / (float)r.counts.size();
        if (ratio > 0.87f && ratio < 1.15f) break;
        calib *= ratio;
        InstantMeshesResult r2 = runOnce(src, st, calib);
        secs += r2.seconds;
        if (!r2.ok) break;
        if (std::abs((int)r2.counts.size() - st.targetFaces) < std::abs((int)r.counts.size() - st.targetFaces))
            r = std::move(r2);
        else break;
    }
    r.seconds = secs;
    return r;
}

}  // namespace sculpt
