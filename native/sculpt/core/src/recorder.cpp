#include "sculpt/recorder.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>

namespace sculpt {

static void putDab(std::ostringstream& o, const Dab& d, float r) {
    const float v[] = {d.position.x, d.position.y, d.position.z, d.normal.x,    d.normal.y,    d.normal.z,
                       d.viewDir.x,  d.viewDir.y,  d.viewDir.z,  d.ray.origin.x, d.ray.origin.y, d.ray.origin.z,
                       d.ray.dir.x,  d.ray.dir.y,  d.ray.dir.z,  d.grabDelta.x, d.grabDelta.y, d.grabDelta.z,
                       d.dabDelta.x, d.dabDelta.y, d.dabDelta.z, d.pressure,    d.angle,       r};
    o << '[';
    for (int i = 0; i < 24; ++i) {
        char buf[32];
        snprintf(buf, sizeof buf, "%.9g", v[i]);  // round-trips float exactly
        o << (i ? "," : "") << buf;
    }
    o << ']';
}

static void getDab(const float* v, Dab& d, float& r) {
    d.position = {v[0], v[1], v[2]};
    d.normal = {v[3], v[4], v[5]};
    d.viewDir = {v[6], v[7], v[8]};
    d.ray = {{v[9], v[10], v[11]}, {v[12], v[13], v[14]}};
    d.grabDelta = {v[15], v[16], v[17]};
    d.dabDelta = {v[18], v[19], v[20]};
    d.pressure = v[21];
    d.angle = v[22];
    r = v[23];
}

static std::string esc(const std::string& s) {
    std::string o;
    for (char c : s) {
        if (c == '"' || c == '\\') o += '\\';
        o += c;
    }
    return o;
}

std::string StrokeRecord::toJson() const {
    std::ostringstream o;
    o << "{\"snapshot\":\"" << esc(snapshot) << "\",\"brush\":\"" << esc(brushJson) << "\",\"symmetry\":" << symmetry
      << ",\"dyntopo\":" << (dyntopo ? 1 : 0) << ",\"detail\":" << dynSettings.detail
      << ",\"relative\":" << (dynSettings.relativeDetail ? 1 : 0) << ",\"collapse\":" << (dynSettings.allowCollapse ? 1 : 0)
      << ",\"constant\":" << dynSettings.constantDetail << ",\"begin\":";
    if (hasBegin) putDab(o, begin, beginRadius); else o << "null";
    o << ",\"dabs\":[";
    for (size_t i = 0; i < dabs.size(); ++i) {
        if (i) o << ',';
        putDab(o, dabs[i], dabRadius[i]);
    }
    o << "],\"events\":[";
    for (size_t i = 0; i < eventMs.size(); ++i) {
        char buf[48];
        snprintf(buf, sizeof buf, "%s[%.3f,%.3f]", i ? "," : "", eventMs[i].first, eventMs[i].second);
        o << buf;
    }
    o << "]}";
    return o.str();
}

// Minimal reader for exactly the format toJson() writes.
namespace {
struct R {
    const std::string& s;
    size_t i = 0;
    explicit R(const std::string& x) : s(x) {}
    bool seek(const char* key) {
        std::string k = std::string("\"") + key + "\":";
        size_t p = s.find(k);
        if (p == std::string::npos) return false;
        i = p + k.size();
        return true;
    }
    std::string str() {
        std::string o;
        if (s[i] != '"') return o;
        ++i;
        while (i < s.size() && s[i] != '"') {
            if (s[i] == '\\' && i + 1 < s.size()) ++i;
            o += s[i++];
        }
        ++i;
        return o;
    }
    double num() {
        const char* b = s.c_str() + i;
        char* e = nullptr;
        double v = strtod(b, &e);
        i += (size_t)(e - b);
        return v;
    }
    bool dab(Dab& d, float& r) {
        if (s.compare(i, 4, "null") == 0) { i += 4; return false; }
        float v[24] = {0};
        ++i;  // [
        for (int k = 0; k < 24; ++k) {
            v[k] = (float)num();
            if (s[i] == ',' || s[i] == ']') ++i;
        }
        getDab(v, d, r);
        return true;
    }
};
}  // namespace

bool StrokeRecord::fromJson(const std::string& line) {
    R r(line);
    if (!r.seek("snapshot")) return false;
    snapshot = r.str();
    if (r.seek("brush")) brushJson = r.str();
    if (r.seek("symmetry")) symmetry = (int)r.num();
    if (r.seek("dyntopo")) dyntopo = r.num() != 0;
    if (r.seek("detail")) dynSettings.detail = (float)r.num();
    if (r.seek("relative")) dynSettings.relativeDetail = r.num() != 0;
    if (r.seek("collapse")) dynSettings.allowCollapse = r.num() != 0;
    if (r.seek("constant")) dynSettings.constantDetail = (float)r.num();
    dynSettings.enabled = dyntopo;
    if (r.seek("begin")) hasBegin = r.dab(begin, beginRadius);
    dabs.clear();
    dabRadius.clear();
    if (r.seek("dabs")) {
        ++r.i;  // [
        while (r.i < line.size() && line[r.i] == '[') {
            Dab d;
            float rad;
            r.dab(d, rad);
            dabs.push_back(d);
            dabRadius.push_back(rad);
            if (line[r.i] == ',') ++r.i;
        }
    }
    eventMs.clear();
    if (r.seek("events")) {
        ++r.i;
        while (r.i < line.size() && line[r.i] == '[') {
            ++r.i;
            float a = (float)r.num();
            ++r.i;
            float b = (float)r.num();
            ++r.i;  // ]
            eventMs.push_back({a, b});
            if (line[r.i] == ',') ++r.i;
        }
    }
    return true;
}

bool writeSnapshot(const std::string& path, const Mesh& m) {
    FILE* f = fopen(path.c_str(), "wb");
    if (!f) return false;
    uint32_t live = 0;
    for (const Tri& t : m.tris) if (t[0] >= 0) ++live;
    uint32_t hdr[3] = {0x504e534bu /* KSNP */, (uint32_t)m.positions.size(), live};
    fwrite(hdr, 4, 3, f);
    fwrite(m.positions.data(), sizeof(Vec3), m.positions.size(), f);
    for (const Tri& t : m.tris) if (t[0] >= 0) fwrite(t.data(), 4, 3, f);
    if (m.mask.size() == m.positions.size()) fwrite(m.mask.data(), 4, m.mask.size(), f);
    fclose(f);
    return true;
}

bool readSnapshot(const std::string& path, Mesh& m) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return false;
    uint32_t hdr[3];
    bool ok = fread(hdr, 4, 3, f) == 3 && hdr[0] == 0x504e534bu;
    if (ok) {
        m = Mesh{};
        m.positions.resize(hdr[1]);
        m.tris.resize(hdr[2]);
        ok = fread(m.positions.data(), sizeof(Vec3), hdr[1], f) == hdr[1] &&
             fread(m.tris.data(), 12, hdr[2], f) == hdr[2];
        m.ensureAttributes();
        if (ok && fread(m.mask.data(), 4, hdr[1], f) != hdr[1]) std::fill(m.mask.begin(), m.mask.end(), 0.0f);
        m.buildAdjacency();
        m.computeNormals();
    }
    fclose(f);
    return ok;
}

}  // namespace sculpt
