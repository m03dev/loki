// Sculpting engine — curve brush geometry: sweep a circular (or custom) profile along a
// stroke polyline with rotation-minimizing (parallel-transport) frames, so
// tubes never twist (Bishop 1975; Wang et al. 2008 double reflection).
#pragma once
#include "sculpt/mesh.h"
#include <vector>

namespace sculpt {

struct TubeSettings {
    float radius = 0.1f;
    int sides = 12;
    bool capEnds = true;
    float taperStart = 0.0f;   // 0..1 fraction of radius removed at the start
    float taperEnd = 0.0f;
    std::vector<float> radiusCurve;  // optional per-sample multiplier (pressure)
};

// Resamples to uniform spacing first so ring density is even.
Mesh sweepTube(const std::vector<Vec3>& points, const TubeSettings& s);

std::vector<Vec3> resamplePolyline(const std::vector<Vec3>& pts, float spacing);

}  // namespace sculpt
