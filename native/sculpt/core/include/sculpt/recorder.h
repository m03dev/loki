// Stroke recording: everything needed to replay a sculpt session outside the
// host, bit-for-bit, plus per-event timings for lag analysis.
//
//   <dir>/<session>.snap-N   mesh snapshot (binary) taken when a mesh is bound
//   <dir>/<session>.jsonl    one JSON object per stroke, referencing its snapshot
//
// tests/replay.cpp loads both and re-runs the strokes through BrushEngine.
#pragma once
#include "sculpt/brush.h"
#include "sculpt/dyntopo.h"
#include <string>
#include <vector>

namespace sculpt {

struct StrokeRecord {
    std::string snapshot;          // file name of the mesh snapshot it starts from
    std::string brushJson;         // presetToJson() of the active brush
    int symmetry = 0;
    bool dyntopo = false;
    DynTopoSettings dynSettings;
    bool hasBegin = false;
    Dab begin;                     // dab passed to beginStroke()
    float beginRadius = 0;
    std::vector<Dab> dabs;         // every applyDab() call, in order
    std::vector<float> dabRadius;  // object-space radius per dab
    std::vector<std::pair<float, float>> eventMs;  // per host event: (engine ms, write-back ms)
    std::string toJson() const;
    bool fromJson(const std::string& line);
};

bool writeSnapshot(const std::string& path, const Mesh& m);
bool readSnapshot(const std::string& path, Mesh& m);

}  // namespace sculpt
