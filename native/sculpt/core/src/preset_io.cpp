#include "sculpt/preset_io.h"
#include <cctype>
#include <cstdlib>
#include <iomanip>
#include <sstream>

namespace sculpt {

namespace {

// Minimal JSON reader for flat objects with scalar / number-array values.
struct Reader {
    const std::string& s;
    size_t i = 0;
    std::string err;
    explicit Reader(const std::string& str) : s(str) {}
    void ws() { while (i < s.size() && std::isspace((unsigned char)s[i])) ++i; }
    bool eat(char c) { ws(); if (i < s.size() && s[i] == c) { ++i; return true; } return false; }
    bool str(std::string& out) {
        ws();
        if (i >= s.size() || s[i] != '"') { err = "expected string"; return false; }
        ++i;
        out.clear();
        while (i < s.size() && s[i] != '"') {
            if (s[i] == '\\' && i + 1 < s.size()) { ++i; out += s[i] == 'n' ? '\n' : s[i]; }
            else out += s[i];
            ++i;
        }
        if (i >= s.size()) { err = "unterminated string"; return false; }
        ++i;
        return true;
    }
    bool num(double& out) {
        ws();
        const char* b = s.c_str() + i;
        char* e = nullptr;
        out = std::strtod(b, &e);
        if (e == b) { err = "expected number"; return false; }
        i += (size_t)(e - b);
        return true;
    }
};

struct Value {
    enum Kind { Num, Str, Bool, Arr } kind = Num;
    double n = 0;
    std::string s;
    bool b = false;
    std::vector<double> arr;
};

bool readValue(Reader& r, Value& v) {
    r.ws();
    if (r.i >= r.s.size()) { r.err = "unexpected end"; return false; }
    char c = r.s[r.i];
    if (c == '"') { v.kind = Value::Str; return r.str(v.s); }
    if (r.s.compare(r.i, 4, "true") == 0) { r.i += 4; v.kind = Value::Bool; v.b = true; return true; }
    if (r.s.compare(r.i, 5, "false") == 0) { r.i += 5; v.kind = Value::Bool; v.b = false; return true; }
    if (r.s.compare(r.i, 4, "null") == 0) { r.i += 4; v.kind = Value::Num; return true; }
    if (c == '{') {  // nested object (host-side settings): skip it, balanced
        int depth = 0;
        bool inStr = false;
        for (; r.i < r.s.size(); ++r.i) {
            char ch = r.s[r.i];
            if (inStr) { if (ch == '\\') ++r.i; else if (ch == '"') inStr = false; continue; }
            if (ch == '"') inStr = true;
            else if (ch == '{') ++depth;
            else if (ch == '}' && --depth == 0) { ++r.i; v.kind = Value::Num; return true; }
        }
        r.err = "unterminated object";
        return false;
    }
    if (c == '[') {
        ++r.i;
        v.kind = Value::Arr;
        if (r.eat(']')) return true;
        do {
            r.ws();
            if (r.i < r.s.size() && r.s[r.i] == '[') {  // nested pair [x, y] -> flattened
                ++r.i;
                do { double d; if (!r.num(d)) return false; v.arr.push_back(d); } while (r.eat(','));
                if (!r.eat(']')) { r.err = "expected ]"; return false; }
            } else {
                double d;
                if (!r.num(d)) return false;
                v.arr.push_back(d);
            }
        } while (r.eat(','));
        if (!r.eat(']')) { r.err = "expected ]"; return false; }
        return true;
    }
    v.kind = Value::Num;
    return r.num(v.n);
}

FalloffPreset falloffFromName(const std::string& s) {
    if (s == "Sphere") return FalloffPreset::Sphere;
    if (s == "Root") return FalloffPreset::Root;
    if (s == "Sharp") return FalloffPreset::Sharp;
    if (s == "Linear") return FalloffPreset::Linear;
    if (s == "Constant") return FalloffPreset::Constant;
    if (s == "Custom") return FalloffPreset::Custom;
    return FalloffPreset::Smooth;
}
const char* falloffName(FalloffPreset f) {
    static const char* n[] = {"Smooth", "Sphere", "Root", "Sharp", "Linear", "Constant", "Custom"};
    return n[(int)f];
}

}  // namespace

bool applyPresetJson(const std::string& json, Brush& b, std::string* error) {
    Reader r(json);
    if (!r.eat('{')) { if (error) *error = "expected {"; return false; }
    if (r.eat('}')) return true;
    do {
        std::string k;
        Value v;
        if (!r.str(k) || !r.eat(':') || !readValue(r, v)) {
            if (error) *error = r.err.empty() ? "malformed pair" : r.err;
            return false;
        }
        auto f = [&]() { return (float)(v.kind == Value::Bool ? (v.b ? 1 : 0) : v.n); };
        auto bo = [&]() { return v.kind == Value::Bool ? v.b : v.n != 0; };
        if (k == "name") b.name = v.s;
        else if (k == "kernel") { Kernel kk; if (kernelFromName(v.s, kk)) b.kernel = kk; }
        else if (k == "radius") b.radius = f();
        else if (k == "strength") b.strength = f();
        else if (k == "spacing") b.spacing = f();
        else if (k == "invert") b.invert = bo();
        else if (k == "frontFacesOnly") b.frontFacesOnly = bo();
        else if (k == "usePressure") b.usePressure = bo();
        else if (k == "falloff") b.falloff.preset = falloffFromName(v.s);
        else if (k == "falloffPoints") {
            b.falloff.points.clear();
            for (size_t j = 0; j + 1 < v.arr.size(); j += 2) b.falloff.points.push_back({(float)v.arr[j], (float)v.arr[j + 1]});
            b.falloff.preset = FalloffPreset::Custom;
        }
        else if (k == "alphaFollowStroke") b.alphaFollowStroke = bo();
        else if (k == "planeOffset") b.planeOffset = f();
        else if (k == "planeTrim") b.planeTrim = f();
        else if (k == "squareTip") b.squareTip = bo();
        else if (k == "tipRoundness") b.tipRoundness = f();
        else if (k == "layerHeight") b.layerHeight = f();
        else if (k == "pinch") b.pinch = f();
        else if (k == "poisson") b.poisson = f();
        else if (k == "planeAngle") b.planeAngle = f();
        else if (k == "clothIterations") b.clothIterations = (int)f();
        else if (k == "clothDamping") b.clothDamping = f();
        else if (k == "clothGravity") b.clothGravity = f();
        else if (k == "autoSmooth") b.autoSmooth = f();
        else if (k == "smoothIterations") b.smoothIterations = (int)f();
        else if (k == "noiseScale") b.noiseScale = f();
        else if (k == "color" && v.arr.size() >= 3) b.color = {(float)v.arr[0], (float)v.arr[1], (float)v.arr[2]};
        else if (k == "symmetry") b.symmetry = (int)f();
        // other keys (category, icon, alpha path, tags, ui hints) are host-side
    } while (r.eat(','));
    if (!r.eat('}')) { if (error) *error = "expected }"; return false; }
    return true;
}

std::string presetToJson(const Brush& b) {
    std::ostringstream o;
    o << std::setprecision(9);  // exact float round trip (replays must match)
    o << "{\"name\":\"" << b.name << "\",\"kernel\":\"" << kernelName(b.kernel) << "\""
      << ",\"radius\":" << b.radius << ",\"strength\":" << b.strength << ",\"spacing\":" << b.spacing
      << ",\"invert\":" << (b.invert ? "true" : "false") << ",\"frontFacesOnly\":" << (b.frontFacesOnly ? "true" : "false")
      << ",\"falloff\":\"" << falloffName(b.falloff.preset) << "\""
      << ",\"planeOffset\":" << b.planeOffset << ",\"planeTrim\":" << b.planeTrim
      << ",\"squareTip\":" << (b.squareTip ? "true" : "false") << ",\"tipRoundness\":" << b.tipRoundness
      << ",\"layerHeight\":" << b.layerHeight << ",\"pinch\":" << b.pinch << ",\"poisson\":" << b.poisson << ",\"planeAngle\":" << b.planeAngle
      << ",\"autoSmooth\":" << b.autoSmooth << ",\"noiseScale\":" << b.noiseScale << ",\"symmetry\":" << b.symmetry
      << ",\"usePressure\":" << (b.usePressure ? "true" : "false")
      << ",\"alphaFollowStroke\":" << (b.alphaFollowStroke ? "true" : "false")
      << ",\"clothIterations\":" << b.clothIterations << ",\"clothDamping\":" << b.clothDamping
      << ",\"clothGravity\":" << b.clothGravity << ",\"smoothIterations\":" << b.smoothIterations
      << ",\"color\":[" << b.color.x << "," << b.color.y << "," << b.color.z << "]";
    if (b.falloff.preset == FalloffPreset::Custom && !b.falloff.points.empty()) {
        o << ",\"falloffPoints\":[";
        for (size_t i = 0; i < b.falloff.points.size(); ++i)
            o << (i ? "," : "") << "[" << b.falloff.points[i].first << "," << b.falloff.points[i].second << "]";
        o << "]";
    }
    o << "}";
    return o.str();
}

}  // namespace sculpt
