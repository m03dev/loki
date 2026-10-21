// Sculpting engine — sculpt mesh. Triangle soup with optional source-polygon description,
// per-vertex attributes (mask, color) and lazily rebuilt adjacency.
#pragma once
#include "sculpt/math.h"
#include <array>
#include <vector>

namespace sculpt {

using Tri = std::array<int, 3>;

struct Mesh {
    std::vector<Vec3> positions;
    std::vector<Vec3> normals;      // per-vertex, area-weighted
    std::vector<Tri> tris;
    std::vector<float> mask;        // 0 = free, 1 = fully masked (frozen)
    std::vector<Vec3> color;        // polypaint (vertex color), linear RGB

    // Original polygon layout from the host (e.g. the host quads). Valid only while
    // topology is untouched (no dyntopo / remesh). Used so a non-dyntopo sculpt
    // writes back only point positions, which keeps UVs, sets and history intact.
    std::vector<int> polyCounts, polyIndices;
    bool topologyFromHost = false;
    // Source polygon of each triangle (-1 = created or rewritten by dyntopo) and
    // the triangle count of each source polygon. Lets a dyntopo'd mesh write
    // back its untouched polygons as the original quads/n-gons and only the
    // re-tessellated region as triangles (like dynamic detail in pro sculpting apps).
    // Empty when unknown; dyntopo/compact keep it in sync with `tris`.
    std::vector<int> triPoly, polyTriCount;

    // Polygon layout for writing back: intact source polygons + loose triangles
    // (live tris only). `vertexUsed` gets every referenced vertex.
    void hybridPolygons(std::vector<int>& counts, std::vector<int>& indices) const;

    // Adjacency (rebuilt on demand)
    std::vector<std::vector<int>> vertTris;   // vertex -> incident triangles
    std::vector<std::vector<int>> vertNbrs;   // vertex -> one-ring vertices

    size_t vertexCount() const { return positions.size(); }
    size_t triCount() const { return tris.size(); }

    void ensureAttributes();             // size mask/color/normals to vertex count
    void buildAdjacency();               // vertTris + vertNbrs
    void computeNormals();               // all vertices
    void computeNormals(const std::vector<int>& verts);  // only these (needs adjacency)
    Vec3 triNormal(int t) const {  // unnormalized: area weighting falls out of the length
        const Tri& f = tris[t];
        return cross(positions[f[1]] - positions[f[0]], positions[f[2]] - positions[f[0]]);
    }
    // Per-vertex cavity in [0,1] (Mask by Cavity): umbrella-Laplacian
    // offset along the normal / local edge length, normalized by the 95th
    // percentile so it adapts to the model's detail. Needs adjacency + normals.
    void cavity(std::vector<float>& out) const;         // unnormalized (length = 2*area)
    AABB bounds() const;

    // Builds triangles from host polygons with fan triangulation.
    static Mesh fromPolygons(const std::vector<Vec3>& pts, const std::vector<int>& counts,
                             const std::vector<int>& indices);

    // Primitive generators (used by tests, Insert Mesh defaults, voxel remesh blocking).
    static Mesh icosphere(int subdivisions, float radius = 1.0f);
    static Mesh box(float size = 1.0f, int segments = 1);
};

}  // namespace sculpt
