// Sculpting engine — portable quad remesh fallback (the quad remesher button when the host's
// polyRetopo is unavailable, i.e. the host < 2023.2, or for the standalone core).
//
// Inside the host, Sculpting engine's the quad remesher panel drives the host's own field-aligned
// polyRetopo node (targetFaceCount, preserveHardEdges, featureTags, symmetry,
// faceUniformity) — that is the production path, see python/sculpt/remesh.py.
//
// Fallback pipeline:
//   1. isotropic remesh to the edge length implied by targetFaces
//      (split 4/3 L, collapse 4/5 L, tangential relax, project to source)
//   2. quad pairing: greedy by squareness, then augmenting-path repair of the
//      matching so few triangles are left over
// Produces quad-dominant meshes without edge-flow alignment.
#pragma once
#include "sculpt/mesh.h"

namespace sculpt {

struct QuadRemeshSettings {
    int targetFaces = 5000;
    int iterations = 5;
    bool keepColor = true;
    bool keepBoundaries = true;
    float minQuadQuality = 0.2f;   // 0..1, lower merges more aggressively
};

struct QuadRemeshResult {
    Mesh mesh;   // tris + polyCounts/polyIndices (quads + leftover tris)
    int quads = 0, tris = 0;
};

QuadRemeshResult quadRemesh(const Mesh& source, const QuadRemeshSettings& s);

// Isotropic remesh only (also used by "Remesh to uniform" command).
Mesh isotropicRemesh(const Mesh& source, float edgeLength, int iterations);

}  // namespace sculpt
