// Sculpting engine — voxel remesh (voxel remesh equivalent).
//
// 1. Narrow-band unsigned distance to the input triangles on a regular grid.
// 2. Sign by flood fill from the grid border: a sample is *outside* if it can
//    be reached without crossing the surface. Overlapping / intersecting parts
//    therefore union automatically and their internal faces vanish — this is
//    what makes voxel remesh good for merging primitives and cleaning booleans.
// 3. Naive Surface Nets extraction (Gibson 1998): one vertex per sign-changing
//    cell at the mean of its edge crossings, one quad per sign-changing grid
//    edge. Output is an all-quad, uniform mesh.
// 4. Optional relax + projection back onto the source (keeps detail, carries
//    polypaint across).
#pragma once
#include "sculpt/mesh.h"

namespace sculpt {

struct VoxelRemeshSettings {
    int resolution = 128;      // voxels along the longest bounds axis ("Resolution")
    float voxelSize = 0.0f;    // if > 0 overrides resolution
    int relaxIterations = 2;   // tangential smoothing of the new surface
    bool project = true;       // snap vertices back to the source surface
    bool keepColor = true;     // transfer vertex color from the source
    float blur = 0.0f;         // "Blur": extra smoothing before projection (0..1)
    bool sharpFeatures = true; // Dual Contouring vertex placement: keeps hard edges/corners
};

struct VoxelRemeshResult {
    Mesh mesh;                 // triangles + quads in polyCounts/polyIndices
    int gridX = 0, gridY = 0, gridZ = 0;
    float voxelSize = 0;
};

VoxelRemeshResult voxelRemesh(const Mesh& source, const VoxelRemeshSettings& s);

// Duplicates vertices so every edge of a quad mesh borders exactly two quads
// (applied to voxel remesh output; see voxel_remesh.cpp).
void splitNonManifold(Mesh& quadMesh, std::vector<int>* origin = nullptr);  // origin: source of each new vertex

// Closest point on triangle (Ericson, Real-Time Collision Detection 5.1.5).
Vec3 closestPointOnTriangle(const Vec3& p, const Vec3& a, const Vec3& b, const Vec3& c, float& u, float& v);

// Signed volume (divergence theorem); > 0 for outward-oriented closed meshes.
float signedVolume(const Mesh& m);

}  // namespace sculpt
