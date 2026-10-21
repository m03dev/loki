// Catmull-Clark subdivision of a polygon cage - the C++ twin of Forge's JS ForgePoly.smooth (app/ui/forge_poly.js),
// used for the 2 / 3 smooth-mesh preview of a modelled mesh. Same rules, same vertex and face order as the JS, so
// either one can draw the preview: every n-gon becomes n quads, a boundary keeps its shape (crease rule), a corner
// with other than two boundary edges stays put, a non-manifold edge takes its midpoint.
#pragma once
#include <vector>

namespace sculpt {

struct Cage {
    std::vector<double> v;      // xyz per vertex
    std::vector<int> sizes;     // corners per face
    std::vector<int> idx;       // the faces' vertex indices, face after face
};

// One Catmull-Clark step. Returns false (out untouched) when the cage refers to a vertex that is not there.
bool cageSubdivideOnce(const Cage& in, Cage& out);

// Up to `levels` steps, stopping before a step would make more than maxFaces faces (the JS preview's limit rule:
// a step runs only while faces * 4 <= maxFaces). Returns the number of steps done, or -1 on a bad cage.
int cageSubdivide(const Cage& in, int levels, int maxFaces, Cage& out);

// Fan triangulation in the JS order (f[0], f[k], f[k+1]).
void cageTriangulate(const Cage& c, std::vector<int>& tris);

}  // namespace sculpt
