// Field-aligned quad remeshing via Instant Meshes (Jakob, Tarini, Panozzo,
// Sorkine-Hornung, SIGGRAPH Asia 2015; BSD-3, vendored in third_party/).
//
// In-process and fast (a 100k-triangle sculpt -> 5k quads in a few seconds),
// so the quad remesher no longer needs any external program.
// Pipeline (same as Instant Meshes' batch mode): subdivide if too coarse ->
// directed edges -> multi-resolution hierarchy -> orientation field (4-RoSy)
// -> position field (4-PoSy) -> graph extraction -> faces. The result is then
// projected back onto the source surface.
#pragma once
#include "sculpt/mesh.h"
#include <string>
#include <vector>

namespace sculpt {

struct InstantMeshesSettings {
    int targetFaces = 5000;
    bool pureQuad = true;        // all quads (the quad remesher-like); false: quad-dominant (a few
                                 // triangles/pentagons at singularities). Pure-quad extraction
                                 // subdivides once, so targetFaces/4 is passed to the solver.
    float creaseAngle = -1.0f;   // degrees; >= 0 keeps sharp creases (Detect Edges / Keep Creases)
    bool extrinsic = true;       // extrinsic smoothing (smoother flow on curved shapes)
    bool alignToBoundaries = true;
    int smoothIterations = 2;    // projection + tangential smoothing passes onto the source
    bool deterministic = false;
};

struct InstantMeshesResult {
    std::vector<Vec3> positions;
    std::vector<int> counts, indices;   // polygons (mostly quads)
    std::vector<Vec3> color;            // polypaint sampled from the source (if it has color)
    int quads = 0, others = 0;
    bool ok = false;
    std::string error;
    double seconds = 0;
};

InstantMeshesResult instantMeshes(const Mesh& source, const InstantMeshesSettings& s);

}  // namespace sculpt
