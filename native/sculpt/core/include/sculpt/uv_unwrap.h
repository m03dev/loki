// UV unwrapping of a polygon cage with map UVs (the pro tool's data model): every face corner has a vertex index
// (fv) and a UV index (fuv); a UV "shell" is the set of faces connected through shared UV indices, seams are
// implicit (neighbouring faces that use different UV indices along an edge).
//
//   uvUnfold - per shell: LSCM (Levy et al. 2002) with pins, then ARAP local/global rounds (Liu et al. 2008)
//   uvLayout - per shell: optional density equalisation and rotation, skyline packing into the 0-1 square
//   uvAuto   - fully automatic: xatlas (third_party/xatlas, MIT) cuts charts and packs them; or, keeping the
//              existing seams, uvUnfold on each existing shell and xatlas packs them
//
// The C API (wasm/sculpt_api.cpp ks_uv_*) and native/sculpt/wasm/test/test_uv.js describe the call shapes.
#pragma once
#include <vector>

namespace sculpt {

struct UvCage {
    const float* pos = nullptr;   // xyz per vertex
    int nv = 0;
    const int* sizes = nullptr;   // corners per face
    int nf = 0;
    const int* fv = nullptr;      // vertex index per corner, face after face
    const int* fuv = nullptr;     // UV index per corner (same layout); may be null for uvAuto without keepSeams
    int nuv = 0;
    int nc = -1;                  // corners the caller passed (fv / fuv length); -1 = trust sum(sizes)
};

// Checks sizes (>= 3 each, summing to nc when nc >= 0), every fv in [0, nv), every fuv in [0, nuv), nuv >= 1.
// Returns the corner count, or -1.
int uvValidate(const UvCage& c, bool needFuv = true);

// Shell id per UV index (-1 for a UV no face uses) and per face; shells are numbered in order of first use.
int uvShells(const UvCage& c, std::vector<int>& uvShell, std::vector<int>& faceShell);
inline int uvShellCount(const UvCage& c) { std::vector<int> a, b; return uvShells(c, a, b); }

struct UvUnfoldStats {
    int shells = 0;
    int flips = 0;          // triangles (fan of every face) whose UV orientation is opposite to their shell's
    float stretch = 1.0f;   // 3D-area-weighted mean over the triangles of sigma_max / sigma_min of the 3D->UV
                            // Jacobian (1 = no shape distortion, scale-free; a triangle's ratio is capped at 10)
};

// uvIn: 2 floats per UV index; pinned: nuv bytes (may be null), 1 = keep that UV exactly. iterations: ARAP rounds
// after LSCM (0 = pure LSCM). Shells without user pins are scaled so 2D area = 3D area * scaleToDensity and put
// back where their input bounding box centre was. uvOut gets 2 * nuv floats (UVs no face uses are copied).
// Returns the shell count, or -1 on bad input.
int uvUnfold(const UvCage& c, const float* uvIn, const unsigned char* pinned, int iterations, float scaleToDensity,
             std::vector<float>& uvOut, UvUnfoldStats* stats = nullptr);

struct UvLayoutSettings {
    float paddingPx = 4.0f;     // gap between shells in texels of `resolution` (gap in UV = paddingPx / resolution)
    float resolution = 1024.0f;
    int rotate = 1;             // 0 none, 1 90-degree steps, 2 free (minimum-area box via convex hull)
    int scaleMode = 1;          // 0 keep relative sizes, 1 uniform texel density, 2 no scaling at all (translate only)
    float margin = 0.005f;      // border kept free inside the 0-1 square
};

// Packs the shells of the faces into the 0-1 square. uvOut: 2 * nuv. Returns the shell count, or -1.
int uvLayout(const UvCage& c, const float* uvIn, const UvLayoutSettings& s, std::vector<float>& uvOut);

struct UvAutoOptions {   // xatlas ChartOptions + PackOptions (same names and defaults as xatlas)
    float maxChartArea = 0.0f, maxBoundaryLength = 0.0f;
    float normalDeviationWeight = 2.0f, roundnessWeight = 0.01f, straightnessWeight = 6.0f;
    float normalSeamWeight = 4.0f, textureSeamWeight = 0.5f, maxCost = 2.0f;
    int maxIterations = 1;
    int padding = 4;            // texels
    int resolution = 1024;
    bool bilinear = true, blockAlign = false, bruteForce = false, rotateCharts = true, rotateChartsToAxis = true;
    float texelsPerUnit = 0.0f; // 0: estimated from the resolution
    int unfoldIterations = 6;   // keepSeams: ARAP rounds of uvUnfold on every existing shell
};

struct UvAutoResult {
    std::vector<float> uv;      // 2 per output UV index, inside 0-1
    std::vector<int> fuv;       // one per input corner
    int charts = 0;             // shells of the result (by UV connectivity)
    int splitFaces = 0;         // polygons whose triangles xatlas put in different charts (re-joined, see .cpp)
};

// keepSeams = false: c.fuv is ignored, xatlas cuts and parameterizes. keepSeams = true: c.fuv / c.nuv are the
// existing seams (uvIn may be null), every shell is unfolded with uvUnfold and xatlas packs them.
// Returns the chart count, or -1 on bad input.
int uvAuto(const UvCage& c, const float* uvIn, bool keepSeams, const UvAutoOptions& o, UvAutoResult& out);

}  // namespace sculpt
