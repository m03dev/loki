// Sculpting engine — brush preset (JSON) parsing. A preset is a flat JSON object whose
// keys mirror Brush fields, e.g.
//   {"name":"Clay Tubes","kernel":"ClayStrips","strength":0.6,"squareTip":true,
//    "falloff":"Smooth","autoSmooth":0.2}
// Unknown keys are ignored so newer libraries load in older builds.
#pragma once
#include "sculpt/brush.h"
#include <string>

namespace sculpt {

// Applies keys from `json` onto `b`. Returns false on malformed JSON
// (b is left partially updated only for keys before the error).
bool applyPresetJson(const std::string& json, Brush& b, std::string* error = nullptr);

std::string presetToJson(const Brush& b);

}  // namespace sculpt
