// Sculpting engine as a WebAssembly module: a plain C API over the core
// (brushes, dyntopo, voxel remesh, quad remesh, subdivision levels, undo).
// The host (LOKI Forge, three.js) owns the camera: it turns the cursor into an
// object-space ray and calls ks_press / ks_drag / ks_release, then re-uploads
// the vertices ks_take_dirty reports (or everything after a topology change).
//
// Memory: positions / normals / colors are float[3] per vertex, triangles are
// int32[3], all read straight out of the module's memory via the *_ptr calls.
#include "sculpt/brush.h"
#include "sculpt/cage_subdiv.h"
#include "sculpt/curve_tube.h"
#include "sculpt/dyntopo.h"
#include "sculpt/multires.h"
#include "sculpt/preset_io.h"
#include "sculpt/quad_remesh.h"
#include "sculpt/voxel_remesh.h"
#include "meshoptimizer.h"

#include <cmath>
#include <cstdio>
#include <algorithm>
#include <unordered_set>
#include <unordered_map>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <string>
#include <vector>

#define KS_EXPORT(name) extern "C" __attribute__((export_name(#name)))

using namespace sculpt;

namespace {

struct Snapshot {  // whole-mesh state (topology changes, remesh, levels)
    std::vector<Vec3> positions, color;
    std::vector<Tri> tris;
    std::vector<float> mask;
    std::vector<int> polyCounts, polyIndices;
};

struct UndoRec {
    bool topology = false;
    std::vector<int> verts;
    std::vector<Vec3> before, after;
    std::vector<float> maskBefore, maskAfter;
    std::vector<Vec3> colorBefore, colorAfter;
    std::shared_ptr<Snapshot> sBefore, sAfter;
};

struct Session {
    Mesh mesh;
    std::unique_ptr<BrushEngine> engine;
    DynTopo dyntopo;
    DynTopoSettings dyn;
    Brush brush;
    Brush active;
    Multires levels;
    std::deque<UndoRec> undo, redo;
    size_t undoLimit = 40;
    unsigned topoVersion = 1;   // host re-uploads everything when this changes
    bool stroking = false, topoChanged = false;
    Vec3 pressPoint, lastDab, planeNormal{0, 0, 1};
    std::shared_ptr<Snapshot> preStroke;
    std::vector<int> dirty;
    std::vector<float> maskStart;
    std::vector<Vec3> colorStart;
    float hit[8] = {0};         // x y z nx ny nz t ok
    std::string text;           // last JSON / error out
};

Session* S = nullptr;

std::shared_ptr<Snapshot> snap() {
    auto s = std::make_shared<Snapshot>();
    s->positions = S->mesh.positions;
    s->color = S->mesh.color;
    s->tris = S->mesh.tris;
    s->mask = S->mesh.mask;
    s->polyCounts = S->mesh.polyCounts;
    s->polyIndices = S->mesh.polyIndices;
    return s;
}

void rebuild() {  // after any topology change
    S->mesh.ensureAttributes();
    S->mesh.buildAdjacency();
    S->mesh.computeNormals();
    if (!S->engine) S->engine.reset(new BrushEngine(S->mesh));
    S->engine->rebuildSpatial();
    if (S->dyn.enabled) S->dyntopo.attach(S->mesh);
    ++S->topoVersion;
}

void restore(const Snapshot& s) {
    S->mesh.positions = s.positions;
    S->mesh.color = s.color;
    S->mesh.tris = s.tris;
    S->mesh.mask = s.mask;
    S->mesh.polyCounts = s.polyCounts;
    S->mesh.polyIndices = s.polyIndices;
    S->mesh.topologyFromHost = !s.polyCounts.empty();
    S->mesh.triPoly.clear();
    S->mesh.polyTriCount.clear();
    rebuild();
}

void pushUndo(UndoRec&& r) {
    S->undo.push_back(std::move(r));
    while (S->undo.size() > S->undoLimit) S->undo.pop_front();
    S->redo.clear();
}

// replace the whole mesh (remesh / levels), undoable
void replaceMesh(Mesh&& m) {
    UndoRec r;
    r.topology = true;
    r.sBefore = snap();
    m.ensureAttributes();
    S->mesh = std::move(m);
    S->engine.reset();
    rebuild();
    r.sAfter = snap();
    pushUndo(std::move(r));
}

Vec3 planePoint(const Ray& r) {
    float den = dot(r.dir, S->planeNormal);
    if (std::fabs(den) < 1e-8f) return S->pressPoint;
    float t = dot(S->pressPoint - r.origin, S->planeNormal) / den;
    return r.origin + r.dir * t;
}

Ray mkRay(float ox, float oy, float oz, float dx, float dy, float dz) {
    Ray r;
    r.origin = Vec3(ox, oy, oz);
    r.dir = normalize(Vec3(dx, dy, dz));
    return r;
}

bool surfaceDab(const Ray& r, float pressure, float radius, Dab& d) {
    Hit h = S->engine->bvh().raycast(S->mesh, r);
    if (h.hit) {
        d.position = h.point;
        d.normal = h.normal;
    } else {
        if (S->active.kernel != Kernel::SnakeHook) return false;
        d.normal = S->planeNormal;
    }
    d.ray = r;
    d.viewDir = r.dir;
    d.pressure = pressure;
    S->active.radius = radius;
    d.dabDelta = d.position - S->lastDab;
    if (S->active.kernel == Kernel::SnakeHook) {
        Vec3 pp = planePoint(r);
        d.dabDelta = pp - S->lastDab;
        d.position = S->lastDab;
        S->lastDab = pp;
    } else {
        S->lastDab = d.position;
    }
    return true;
}

void dynAt(const Vec3& c, float radius) {
    if (S->dyn.enabled && !kernelIsGrab(S->active.kernel) &&
        S->dyntopo.apply(S->mesh, S->engine->bvh(), c, radius, S->dyn)) {
        S->topoChanged = true;
        S->mesh.topologyFromHost = false;
        S->mesh.polyCounts.clear();
        S->mesh.polyIndices.clear();
    }
}

// polygons of the current mesh: host quads when known, else its triangles
void currentPolys(std::vector<int>& counts, std::vector<int>& idx) {
    counts.clear();
    idx.clear();
    if (!S->mesh.polyCounts.empty()) {
        counts = S->mesh.polyCounts;
        idx = S->mesh.polyIndices;
        return;
    }
    for (const Tri& t : S->mesh.tris) {
        if (t[0] < 0) continue;
        counts.push_back(3);
        idx.insert(idx.end(), {t[0], t[1], t[2]});
    }
}

Mesh meshFromPolys(const std::vector<Vec3>& p, const std::vector<int>& counts, const std::vector<int>& idx) {
    Mesh m = Mesh::fromPolygons(p, counts, idx);
    m.polyCounts = counts;
    m.polyIndices = idx;
    m.topologyFromHost = true;
    return m;
}

}  // namespace

// ---------------------------------------------------------------- memory

KS_EXPORT(ks_alloc) void* ks_alloc(int bytes) { return std::malloc((size_t)bytes); }
KS_EXPORT(ks_free) void ks_free(void* p) { std::free(p); }

// ---------------------------------------------------------------- the modelling cage's smooth preview
// Catmull-Clark of a polygon cage (Forge's 2 / 3 smooth preview), independent of the sculpt mesh: in go the cage's
// vertices (float xyz), corners per face and the faces' indices; out come the smoothed vertices and their fan
// triangles, read with ks_cage_pos / ks_cage_tris until the next ks_cage_subdiv. Returns the steps done (-1: bad cage).
namespace { std::vector<float> gCagePos; std::vector<int> gCageTris; int gCageFaces = 0; }
KS_EXPORT(ks_cage_subdiv) int ks_cage_subdiv(const float* v, int nv, const int* sizes, int nf, const int* idx, int nIdx, int levels, int maxFaces) {
    Cage in;
    in.v.assign(v, v + (size_t)nv * 3);
    in.sizes.assign(sizes, sizes + nf);
    in.idx.assign(idx, idx + nIdx);
    Cage out;
    const int done = cageSubdivide(in, levels, maxFaces, out);
    if (done < 0) { gCagePos.clear(); gCageTris.clear(); gCageFaces = 0; return -1; }
    gCagePos.resize(out.v.size());
    for (size_t i = 0; i < out.v.size(); ++i) gCagePos[i] = (float)out.v[i];
    cageTriangulate(out, gCageTris);
    gCageFaces = (int)out.sizes.size();
    return done;
}

// ---------------------------------------------------------------- soft / hard edges: one normal per face corner
// (Forge's polySoftEdge display; owner 2026-10-22 "should we rebuild in c++ to make it faster"). Corners of the same
// vertex on two faces that meet over a SOFT edge are joined (union-find) and share the area-weighted sum of their
// faces' normals; a HARD edge (hard: vertex pairs, 2 ints each) keeps them apart. Out: 3 floats per corner, in the
// faces' corner order, read with ks_corner_nrm. The JS version took ~860 ms on 98k faces.
namespace { std::vector<float> gCornerNrm; }
KS_EXPORT(ks_corner_normals) int ks_corner_normals(const float* v, int nv, const int* sizes, int nf, const int* idx, int nIdx,
                                                   const int* hard, int nHard) {
    if (nv <= 0 || nf <= 0 || nIdx <= 0) return 0;
    std::vector<int> base((size_t)nf + 1, 0);
    for (int f = 0; f < nf; ++f) base[f + 1] = base[f] + sizes[f];
    if (base[nf] != nIdx) return -1;
    // face normals (Newell) and areas
    std::vector<float> fn((size_t)nf * 3);
    for (int f = 0; f < nf; ++f) {
        double x = 0, y = 0, z = 0;
        const int b = base[f], n = sizes[f];
        for (int k = 0; k < n; ++k) {
            const float* a = v + (size_t)idx[b + k] * 3;
            const float* c = v + (size_t)idx[b + (k + 1) % n] * 3;
            x += ((double)a[1] - c[1]) * ((double)a[2] + c[2]);
            y += ((double)a[2] - c[2]) * ((double)a[0] + c[0]);
            z += ((double)a[0] - c[0]) * ((double)a[1] + c[1]);
        }
        // Newell's vector = 2 x area x unit normal: its length weights by area for free
        fn[(size_t)f * 3] = (float)x; fn[(size_t)f * 3 + 1] = (float)y; fn[(size_t)f * 3 + 2] = (float)z;
    }
    auto key = [](int a, int b) -> uint64_t { if (a > b) std::swap(a, b); return ((uint64_t)(uint32_t)a << 32) | (uint32_t)b; };
    std::unordered_set<uint64_t> hardSet;
    hardSet.reserve((size_t)nHard * 2 + 1);
    for (int i = 0; i < nHard; ++i) hardSet.insert(key(hard[i * 2], hard[i * 2 + 1]));
    // union-find over corners
    std::vector<int> parent((size_t)nIdx);
    for (int i = 0; i < nIdx; ++i) parent[i] = i;
    auto find = [&](int x) { while (parent[x] != x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    auto join = [&](int a, int b) { a = find(a); b = find(b); if (a != b) parent[b] = a; };
    // every face side as (edge key, corner of the smaller vertex, corner of the larger), sorted by key: the sides of one
    // edge end up next to each other (a sort beats hash maps here: ~5x on 600k corners)
    struct Side { uint64_t k; int lo, hi; };
    std::vector<Side> sides((size_t)nIdx);
    for (int f = 0; f < nf; ++f) {
        const int b = base[f], n = sizes[f];
        for (int k = 0; k < n; ++k) {
            const int ca = b + k, cb = b + (k + 1) % n, a = idx[ca], c = idx[cb];
            sides[ca] = { key(a, c), a < c ? ca : cb, a < c ? cb : ca };
        }
    }
    std::sort(sides.begin(), sides.end(), [](const Side& x, const Side& y) { return x.k < y.k; });
    for (size_t i = 0; i + 1 < sides.size(); ) {
        size_t j = i + 1;
        while (j < sides.size() && sides[j].k == sides[i].k) ++j;
        if (j - i >= 2 && !hardSet.count(sides[i].k)) { join(sides[i].lo, sides[i + 1].lo); join(sides[i].hi, sides[i + 1].hi); }
        i = j;
    }
    // an edge with 3+ faces was joined by its first two: keep that (rare, non-manifold)
    std::vector<double> sum((size_t)nIdx * 3, 0.0);
    for (int f = 0; f < nf; ++f)
        for (int c = base[f]; c < base[f + 1]; ++c) {
            const int r = find(c);
            sum[(size_t)r * 3] += fn[(size_t)f * 3]; sum[(size_t)r * 3 + 1] += fn[(size_t)f * 3 + 1]; sum[(size_t)r * 3 + 2] += fn[(size_t)f * 3 + 2];
        }
    gCornerNrm.assign((size_t)nIdx * 3, 0.f);
    for (int c = 0; c < nIdx; ++c) {
        const int r = find(c);
        const double x = sum[(size_t)r * 3], y = sum[(size_t)r * 3 + 1], z = sum[(size_t)r * 3 + 2];
        const double l = std::sqrt(x * x + y * y + z * z);
        if (l > 0) { gCornerNrm[(size_t)c * 3] = (float)(x / l); gCornerNrm[(size_t)c * 3 + 1] = (float)(y / l); gCornerNrm[(size_t)c * 3 + 2] = (float)(z / l); }
    }
    return nIdx;
}
KS_EXPORT(ks_corner_nrm) const float* ks_corner_nrm() { return gCornerNrm.data(); }
KS_EXPORT(ks_cage_pos) const float* ks_cage_pos() { return gCagePos.data(); }
KS_EXPORT(ks_cage_nverts) int ks_cage_nverts() { return (int)(gCagePos.size() / 3); }
KS_EXPORT(ks_cage_tris) const int* ks_cage_tris() { return gCageTris.data(); }
KS_EXPORT(ks_cage_ntris) int ks_cage_ntris() { return (int)(gCageTris.size() / 3); }
KS_EXPORT(ks_cage_nfaces) int ks_cage_nfaces() { return gCageFaces; }


// Triangles, or polygons when counts != null (quads kept for subdivision levels).
KS_EXPORT(ks_load) int ks_load(const float* pos, int nVerts, const int* idx, int nIdx, const int* counts, int nCounts) {
    if (!S) S = new Session;
    std::vector<Vec3> pts((size_t)nVerts);
    std::memcpy(pts.data(), pos, sizeof(float) * 3 * (size_t)nVerts);
    std::vector<int> ix(idx, idx + nIdx);
    std::vector<int> cs;
    if (counts && nCounts > 0) cs.assign(counts, counts + nCounts);
    else cs.assign((size_t)nIdx / 3, 3);
    for (int i : ix) if (i < 0 || i >= nVerts) return 0;
    Mesh m = meshFromPolys(pts, cs, ix);
    if (!counts) { m.polyCounts.clear(); m.polyIndices.clear(); m.topologyFromHost = false; }
    S->mesh = std::move(m);
    S->engine.reset();
    S->undo.clear();
    S->redo.clear();
    S->levels = Multires();
    rebuild();
    return 1;
}

KS_EXPORT(ks_vertex_count) int ks_vertex_count() { return S ? (int)S->mesh.positions.size() : 0; }
KS_EXPORT(ks_tri_count) int ks_tri_count() { return S ? (int)S->mesh.tris.size() : 0; }
KS_EXPORT(ks_positions) float* ks_positions() { return S ? &S->mesh.positions[0].x : nullptr; }
KS_EXPORT(ks_normals) float* ks_normals() { return S ? &S->mesh.normals[0].x : nullptr; }
KS_EXPORT(ks_colors) float* ks_colors() { return S ? &S->mesh.color[0].x : nullptr; }
KS_EXPORT(ks_mask) float* ks_mask() { return S ? S->mesh.mask.data() : nullptr; }
// Triangles: dyntopo leaves dead ones as (-1,-1,-1) until the stroke ends.
KS_EXPORT(ks_tris) int* ks_tris() { return S ? &S->mesh.tris[0][0] : nullptr; }
KS_EXPORT(ks_topology_version) unsigned ks_topology_version() { return S ? S->topoVersion : 0; }
KS_EXPORT(ks_poly_count) int ks_poly_count() { return S ? (int)S->mesh.polyCounts.size() : 0; }
KS_EXPORT(ks_poly_counts) int* ks_poly_counts() { return S && !S->mesh.polyCounts.empty() ? S->mesh.polyCounts.data() : nullptr; }
KS_EXPORT(ks_poly_index_count) int ks_poly_index_count() { return S ? (int)S->mesh.polyIndices.size() : 0; }
KS_EXPORT(ks_poly_indices) int* ks_poly_indices() { return S && !S->mesh.polyIndices.empty() ? S->mesh.polyIndices.data() : nullptr; }

// Vertices changed since the last call: count, then ks_dirty() for the ids.
KS_EXPORT(ks_take_dirty) int ks_take_dirty() {
    if (!S || !S->engine) return 0;
    S->engine->takeHostDirty(S->dirty);
    return (int)S->dirty.size();
}
KS_EXPORT(ks_dirty) int* ks_dirty() { return S && !S->dirty.empty() ? S->dirty.data() : nullptr; }

// Positions changed outside the engine (host undo, transform tools): copy all,
// then normals + BVH refit as for a dab. Not recorded for ks_undo.
KS_EXPORT(ks_set_positions) int ks_set_positions(const float* pos, int nVerts) {
    if (!S || !S->engine || nVerts != (int)S->mesh.positions.size()) return 0;
    std::vector<int> all((size_t)nVerts);
    std::vector<Vec3> p((size_t)nVerts);
    std::memcpy(p.data(), pos, sizeof(float) * 3 * (size_t)nVerts);
    for (int i = 0; i < nVerts; ++i) all[i] = i;
    S->engine->setPositions(all, p);
    S->dirty.clear();
    std::vector<int> drop;
    S->engine->takeHostDirty(drop);
    return 1;
}

// ---------------------------------------------------------------- brush

// JSON preset (the brush library's format: kernel, strength, falloff, ...).
KS_EXPORT(ks_brush_json) int ks_brush_json(const char* json, int len) {
    if (!S) S = new Session;
    Brush b;  // presets start from defaults; size/strength/symmetry are kept
    b.radius = S->brush.radius;
    b.symmetry = S->brush.symmetry;
    b.radial = S->brush.radial;
    b.radialAxis = S->brush.radialAxis;
    std::string err;
    if (!applyPresetJson(std::string(json, (size_t)len), b, &err)) { S->text = err; return 0; }
    S->brush = b;
    return 1;
}
KS_EXPORT(ks_brush_strength) void ks_brush_strength(float v) { if (S) S->brush.strength = v; }
KS_EXPORT(ks_brush_invert) void ks_brush_invert(int v) { if (S) S->brush.invert = v != 0; }
KS_EXPORT(ks_brush_symmetry) void ks_brush_symmetry(int bits) { if (S) S->brush.symmetry = bits; }
KS_EXPORT(ks_brush_radial) void ks_brush_radial(int count, int axis) { if (S) { S->brush.radial = count; S->brush.radialAxis = axis; } }
KS_EXPORT(ks_brush_color) void ks_brush_color(float r, float g, float b) { if (S) S->brush.color = Vec3(r, g, b); }
KS_EXPORT(ks_brush_spacing) float ks_brush_spacing() { return S ? S->brush.spacing : 0.1f; }
KS_EXPORT(ks_brush_is_grab) int ks_brush_is_grab() { return S && kernelIsGrab(S->brush.kernel) ? 1 : 0; }

KS_EXPORT(ks_dyntopo) void ks_dyntopo(int on, float detail, int relative, float constant) {
    if (!S) return;
    S->dyn.enabled = on != 0;
    S->dyn.detail = detail;
    S->dyn.relativeDetail = relative != 0;
    S->dyn.constantDetail = constant;
    if (S->dyn.enabled && !S->mesh.tris.empty()) S->dyntopo.attach(S->mesh);
}

// ---------------------------------------------------------------- picking

// Raycast; ks_hit() -> [x y z nx ny nz t ok].
KS_EXPORT(ks_raycast) int ks_raycast(float ox, float oy, float oz, float dx, float dy, float dz) {
    if (!S || !S->engine) return 0;
    Hit h = S->engine->bvh().raycast(S->mesh, mkRay(ox, oy, oz, dx, dy, dz));
    float o[8] = {h.point.x, h.point.y, h.point.z, h.normal.x, h.normal.y, h.normal.z, h.t, h.hit ? 1.f : 0.f};
    std::memcpy(S->hit, o, sizeof o);
    return h.hit ? 1 : 0;
}
KS_EXPORT(ks_hit) float* ks_hit() { return S ? S->hit : nullptr; }

// ---------------------------------------------------------------- strokes

// mods: 1 = invert (Ctrl), 2 = smooth (Shift), 3 = mask (Ctrl+Shift).
KS_EXPORT(ks_press) int ks_press(float ox, float oy, float oz, float dx, float dy, float dz, float pressure, float radius, int mods) {
    if (!S || !S->engine || S->stroking) return 0;
    Ray r = mkRay(ox, oy, oz, dx, dy, dz);
    Hit h = S->engine->bvh().raycast(S->mesh, r);
    if (!h.hit) return 0;
    S->active = S->brush;
    if (mods == 3) { S->active.kernel = Kernel::Mask; S->active.invert = false; }
    else if (mods == 2) {
        S->active.kernel = Kernel::Smooth; S->active.invert = false; S->active.strength = std::max(0.3f, S->brush.strength);
        S->active.autoSmooth = 0.0f;   // the brush's own auto-smooth on top of Smooth only doubled the pass
    }
    else if (mods == 1) S->active.invert = !S->brush.invert;
    S->active.radius = radius;
    Dab d;
    d.position = h.point;
    d.normal = h.normal;
    d.viewDir = r.dir;
    d.ray = r;
    d.pressure = pressure;
    S->pressPoint = S->lastDab = h.point;
    S->planeNormal = -r.dir;
    S->topoChanged = false;
    S->preStroke = S->dyn.enabled && !kernelIsGrab(S->active.kernel) ? snap() : nullptr;
    S->maskStart = S->mesh.mask;
    S->colorStart = S->active.kernel == Kernel::Paint ? S->mesh.color : std::vector<Vec3>();
    S->engine->beginStroke(S->active, d);
    if (!kernelIsGrab(S->active.kernel)) {
        dynAt(d.position, radius);
        S->engine->applyDab(S->active, d);
    }
    S->stroking = true;
    return 1;
}

// One sample along the stroke (the host spaces samples by spacing * radius px).
// Grab brushes: the cursor ray moves the vertex set picked at press; angle is
// the Rotate brush's sweep around the press point (radians).
KS_EXPORT(ks_drag) int ks_drag(float ox, float oy, float oz, float dx, float dy, float dz, float pressure, float radius, float angle) {
    if (!S || !S->stroking) return 0;
    Ray r = mkRay(ox, oy, oz, dx, dy, dz);
    Dab d;
    if (kernelIsGrab(S->active.kernel)) {
        d.position = S->pressPoint;
        d.viewDir = -S->planeNormal;
        d.ray = r;
        d.pressure = 1.0f;
        d.grabDelta = planePoint(r) - S->pressPoint;
        d.angle = angle;
    } else {
        if (!surfaceDab(r, pressure, radius, d)) return 0;
        dynAt(d.position, radius);
    }
    S->engine->applyDab(S->active, d);
    return 1;
}

KS_EXPORT(ks_release) int ks_release() {
    if (!S || !S->stroking) return 0;
    S->stroking = false;
    S->engine->endStroke();
    UndoRec rec;
    if (S->topoChanged) {
        DynTopo::compact(S->mesh);
        S->engine->rebuildSpatial();
        S->dyntopo.attach(S->mesh);
        S->mesh.computeNormals();
        ++S->topoVersion;
        rec.topology = true;
        rec.sBefore = S->preStroke;
        rec.sAfter = snap();
    } else {
        const auto& touched = S->engine->strokeTouched();
        const auto& orig = S->engine->strokeOriginal();
        rec.verts = touched;
        for (int v : touched) {
            rec.before.push_back(orig[v]);
            rec.after.push_back(S->mesh.positions[v]);
        }
        if (S->active.kernel == Kernel::Mask) {
            rec.maskBefore = S->maskStart;
            rec.maskAfter = S->mesh.mask;
        }
        if (S->active.kernel == Kernel::Paint) {
            rec.colorBefore = S->colorStart;
            rec.colorAfter = S->mesh.color;
        }
    }
    S->preStroke.reset();
    pushUndo(std::move(rec));
    return S->topoChanged ? 2 : 1;
}

// ---------------------------------------------------------------- undo

static int applyRec(const UndoRec& r, bool forward) {
    if (r.topology) {
        restore(forward ? *r.sAfter : *r.sBefore);
        return 2;
    }
    const auto& p = forward ? r.after : r.before;
    S->engine->setPositions(r.verts, p);
    const auto& m = forward ? r.maskAfter : r.maskBefore;
    if (!m.empty() && m.size() == S->mesh.mask.size()) S->mesh.mask = m;
    const auto& c = forward ? r.colorAfter : r.colorBefore;
    if (!c.empty() && c.size() == S->mesh.color.size()) { S->mesh.color = c; ++S->topoVersion; }
    return 1;
}
KS_EXPORT(ks_undo) int ks_undo() {
    if (!S || S->undo.empty() || S->stroking) return 0;
    UndoRec r = std::move(S->undo.back());
    S->undo.pop_back();
    int k = applyRec(r, false);
    S->redo.push_back(std::move(r));
    return k;
}
KS_EXPORT(ks_redo) int ks_redo() {
    if (!S || S->redo.empty() || S->stroking) return 0;
    UndoRec r = std::move(S->redo.back());
    S->redo.pop_back();
    int k = applyRec(r, true);
    S->undo.push_back(std::move(r));
    return k;
}

// ---------------------------------------------------------------- mask

KS_EXPORT(ks_mask_op) void ks_mask_op(int op) {  // 0 clear, 1 invert, 2 fill
    if (!S) return;
    for (float& m : S->mesh.mask) m = op == 0 ? 0.f : op == 1 ? 1.f - m : 1.f;
}

// ---------------------------------------------------------------- remeshing

// Voxel remesh ("voxel remesh"): resolution along the longest axis.
KS_EXPORT(ks_voxel_remesh) int ks_voxel_remesh(int resolution, int relax, int sharp) {
    if (!S || S->mesh.tris.empty()) return 0;
    VoxelRemeshSettings st;
    st.resolution = std::max(8, std::min(1024, resolution));
    st.relaxIterations = relax;
    st.sharpFeatures = sharp != 0;
    VoxelRemeshResult res = voxelRemesh(S->mesh, st);
    if (res.mesh.tris.empty()) return 0;
    S->levels = Multires();
    replaceMesh(std::move(res.mesh));
    return 1;
}

// Quad remesh (field-aligned): about targetFaces quads.
KS_EXPORT(ks_quad_remesh) int ks_quad_remesh(int targetFaces) {
    if (!S || S->mesh.tris.empty()) return 0;
    QuadRemeshSettings st;
    st.targetFaces = std::max(16, targetFaces);
    QuadRemeshResult res = quadRemesh(S->mesh, st);
    if (res.mesh.tris.empty()) return 0;
    S->levels = Multires();
    replaceMesh(std::move(res.mesh));
    return res.quads;
}

// Reduce (decimation, like ZBrush's Decimation Master / the pro tools' Reduce): quadric edge collapse with
// meshoptimizer's simplifier down to about `percent` % of the triangles. The silhouette and detail where the
// surface bends most are kept; polypaint colour is an attribute so painted borders stay; masked vertices
// (mask > 0.5) are locked and never move or collapse; `lockBorder` keeps open edges exactly where they are.
// `maxError` (0..1, relative to the model's size) stops early when the next collapse would cost more. One undo
// step; subdivision levels restart. Returns the triangle count after (0 = nothing done).
KS_EXPORT(ks_decimate) int ks_decimate(float percent, int lockBorder, float maxError) {
    if (!S || S->mesh.tris.empty()) return 0;
    const Mesh& M = S->mesh;
    const size_t nv = M.positions.size();
    std::vector<unsigned> idx;
    idx.reserve(M.tris.size() * 3);
    for (const Tri& t : M.tris)
        if (t[0] >= 0 && t[1] >= 0 && t[2] >= 0 && t[0] != t[1] && t[1] != t[2] && t[0] != t[2])
            idx.insert(idx.end(), {(unsigned)t[0], (unsigned)t[1], (unsigned)t[2]});
    if (idx.size() < 36) return 0;
    const float pct = std::max(0.1f, std::min(100.f, percent));
    size_t target = (size_t)((double)(idx.size() / 3) * pct / 100.0) * 3;
    target = std::max<size_t>(target, 12);
    if (target >= idx.size()) return (int)(idx.size() / 3);
    std::vector<float> attr(nv * 3, 0.8f);
    const bool hasColor = M.color.size() == nv;
    if (hasColor) for (size_t i = 0; i < nv; ++i) { attr[i * 3] = M.color[i].x; attr[i * 3 + 1] = M.color[i].y; attr[i * 3 + 2] = M.color[i].z; }
    const float w[3] = {0.5f, 0.5f, 0.5f};
    std::vector<unsigned char> lock(nv, 0);
    if (M.mask.size() == nv) for (size_t i = 0; i < nv; ++i) lock[i] = M.mask[i] > 0.5f ? 1 : 0;
    std::vector<unsigned> out(idx.size());
    float err = 0.f;
    const unsigned opts = lockBorder ? meshopt_SimplifyLockBorder : 0;
    size_t n = meshopt_simplifyWithAttributes(out.data(), idx.data(), idx.size(), &M.positions[0].x, nv, sizeof(Vec3),
                                              hasColor ? attr.data() : nullptr, sizeof(float) * 3, w, hasColor ? 3 : 0,
                                              lock.data(), target, maxError > 0.f ? maxError : 1.f, opts, &err);
    if (n < 12 || n >= idx.size()) return 0;
    out.resize(n);
    std::vector<int> remap(nv, -1);
    std::vector<Vec3> pts; std::vector<Vec3> col; std::vector<float> msk;
    std::vector<int> counts(n / 3, 3), fidx(n);
    for (size_t i = 0; i < n; ++i) {
        unsigned o = out[i];
        if (remap[o] < 0) {
            remap[o] = (int)pts.size();
            pts.push_back(M.positions[o]);
            col.push_back(hasColor ? M.color[o] : Vec3{0.8f, 0.8f, 0.8f});
            msk.push_back(M.mask.size() == nv ? M.mask[o] : 0.f);
        }
        fidx[i] = remap[o];
    }
    Mesh m = meshFromPolys(pts, counts, fidx);
    m.color = std::move(col);
    m.mask = std::move(msk);
    S->levels = Multires();
    replaceMesh(std::move(m));
    char buf[96];
    std::snprintf(buf, sizeof buf, "reduced %zu -> %zu triangles (error %.4f)", idx.size() / 3, n / 3, err);
    S->text = buf;
    return (int)(n / 3);
}

// ---------------------------------------------------------------- tube / insert (add geometry)

// Add a separate shell to the sculpt mesh (one undo step). The current
// polygons stay as they are (quads kept), the new part brings its own; colour
// and mask of the existing vertices are kept. Subdivision levels restart (the
// base changed), as after a remesh.
static int appendShell(const Mesh& part) {
    if (!S || !S->engine || part.positions.empty() || part.tris.empty()) return 0;
    std::vector<int> counts, idx;
    currentPolys(counts, idx);
    const int base = (int)S->mesh.positions.size();
    std::vector<Vec3> pts = S->mesh.positions;
    pts.insert(pts.end(), part.positions.begin(), part.positions.end());
    if (!part.polyCounts.empty()) {
        counts.insert(counts.end(), part.polyCounts.begin(), part.polyCounts.end());
        for (int i : part.polyIndices) idx.push_back(base + i);
    } else {
        for (const Tri& t : part.tris) {
            if (t[0] < 0) continue;
            counts.push_back(3);
            idx.insert(idx.end(), {base + t[0], base + t[1], base + t[2]});
        }
    }
    std::vector<Vec3> color = S->mesh.color;
    std::vector<float> mask = S->mesh.mask;
    Mesh m = meshFromPolys(pts, counts, idx);
    color.resize(pts.size(), Vec3{0.8f, 0.8f, 0.8f});
    mask.resize(pts.size(), 0.0f);
    m.color = std::move(color);
    m.mask = std::move(mask);
    S->levels = Multires();
    replaceMesh(std::move(m));
    return (int)part.positions.size();
}

// Tube (Curve Tube): sweep a circle of `radius` along the stroke's surface
// points (xyz, n of them) with twist-free frames (curve_tube.cpp). Returns the
// vertex count added.
KS_EXPORT(ks_tube) int ks_tube(const float* pts, int n, float radius, int sides, float taperStart, float taperEnd) {
    if (!S || !S->engine || n < 2 || radius <= 0) return 0;
    std::vector<Vec3> p((size_t)n);
    std::memcpy(p.data(), pts, sizeof(float) * 3 * (size_t)n);
    TubeSettings ts;
    ts.radius = radius;
    ts.sides = std::max(3, std::min(64, sides));
    ts.taperStart = clamp01(taperStart);
    ts.taperEnd = clamp01(taperEnd);
    Mesh tube = sweepTube(p, ts);
    return appendShell(tube);
}

// Insert Mesh: a primitive at a surface point, its axis along the normal,
// sunk by `depth` x radius. kind 0 = sphere, 1 = cube.
KS_EXPORT(ks_insert) int ks_insert(int kind, float x, float y, float z, float nx, float ny, float nz, float radius, float depth) {
    if (!S || !S->engine || radius <= 0) return 0;
    Mesh part = kind == 1 ? Mesh::box(2.0f, 4) : Mesh::icosphere(3, 1.0f);
    Vec3 n = normalize(Vec3(nx, ny, nz));
    if (length2(n) < 1e-12f) n = Vec3(0, 1, 0);
    Vec3 t = normalize(projectOnPlane(std::fabs(n.y) < 0.9f ? Vec3(0, 1, 0) : Vec3(1, 0, 0), n)), b = cross(n, t);
    Vec3 c = Vec3(x, y, z) - n * (radius * depth);
    for (Vec3& p : part.positions) {
        Vec3 q = p * radius;
        p = c + t * q.x + n * q.y + b * q.z;
    }
    if (signedVolume(part) < 0)
        for (Tri& f : part.tris) std::swap(f[1], f[2]);
    part.polyCounts.clear();
    part.polyIndices.clear();
    return appendShell(part);
}

// ---------------------------------------------------------------- subdivision levels

static void syncLevelsBase() {
    std::vector<int> counts, idx;
    currentPolys(counts, idx);
    if (S->levels.empty() || !S->levels.matches((int)S->mesh.positions.size(), (int)counts.size()))
        S->levels.init(counts, idx, S->mesh.positions);
}
static void showLevel() {
    const MultiresLevel& L = S->levels.level(S->levels.current());
    Mesh m = meshFromPolys(L.positions, L.counts, L.indices);
    m.color.clear();
    UndoRec r;
    r.topology = true;
    r.sBefore = snap();
    S->mesh = std::move(m);
    S->engine.reset();
    rebuild();
    r.sAfter = snap();
    pushUndo(std::move(r));
}
KS_EXPORT(ks_divide) int ks_divide() {
    if (!S || S->mesh.tris.empty()) return 0;
    syncLevelsBase();
    if (S->levels.current() != S->levels.levelCount() - 1) return 0;  // divide from the top level
    if (!S->levels.divide(S->mesh.positions)) return 0;
    showLevel();
    return S->levels.levelCount();
}
KS_EXPORT(ks_set_level) int ks_set_level(int k) {
    if (!S || S->levels.empty()) return 0;
    if (!S->levels.matches((int)S->mesh.positions.size(), (int)S->mesh.polyCounts.size())) return 0;
    if (k < 0 || k >= S->levels.levelCount() || k == S->levels.current()) return 0;
    if (!S->levels.setLevel(k, S->mesh.positions)) return 0;
    showLevel();
    return 1;
}
KS_EXPORT(ks_level_count) int ks_level_count() { return S ? S->levels.levelCount() : 0; }
KS_EXPORT(ks_level) int ks_level() { return S && !S->levels.empty() ? S->levels.current() : 0; }

// ---------------------------------------------------------------- misc

KS_EXPORT(ks_text) const char* ks_text() { return S ? S->text.c_str() : ""; }
KS_EXPORT(ks_smooth_all) void ks_smooth_all(float strength, int iterations) {
    if (!S || !S->engine) return;
    std::vector<int> all(S->mesh.positions.size());
    for (size_t i = 0; i < all.size(); ++i) all[i] = (int)i;
    UndoRec r;
    r.verts = all;
    r.before = S->mesh.positions;
    S->engine->smoothVerts(all, strength, iterations, false);
    r.after = S->mesh.positions;
    pushUndo(std::move(r));
}

// thread_local objects with destructors (the engine's per-thread scratch): one
// thread that lives as long as the page, so their destructors never need to run.
extern "C" int __cxa_thread_atexit(void (*)(void*), void*, void*) { return 0; }

// ---------------------------------------------------------------- UV unwrapping (map UVs of a polygon cage)
// Independent of the sculpt mesh, like the cage preview. In: the cage (float xyz per vertex, corners per face, the
// faces' vertex ids, nc = the corner count, checked against the sizes) and its map UVs (a UV index per corner,
// float u,v per UV index). Out (until the next ks_uv_* call): ks_uv_out() 2 floats per UV index (ks_uv_nuv() of
// them); ks_uv_auto also ks_uv_auto_fuv() (a UV index per corner) and ks_uv_auto_nuv(). -1 = bad input.
// sculpt/uv_unwrap.h has the algorithms; native/sculpt/wasm/test/test_uv.js checks them.
#include "sculpt/uv_unwrap.h"
namespace { std::vector<float> gUvOut; std::vector<int> gUvFuv; int gUvFlips = 0; float gUvStretch = 1.0f; }
KS_EXPORT(ks_uv_unfold) int ks_uv_unfold(const float* pos, int nv, const int* sizes, int nf, const int* fv, const int* fuv, int nc,
                                         int nuv, const float* uvIn, const unsigned char* pinned, int iterations, float scaleToDensity) {
    UvCage c; c.pos = pos; c.nv = nv; c.sizes = sizes; c.nf = nf; c.fv = fv; c.fuv = fuv; c.nuv = nuv; c.nc = nc;
    UvUnfoldStats st;
    const int r = uvUnfold(c, uvIn, pinned, iterations, scaleToDensity, gUvOut, &st);
    gUvFuv.clear();
    if (r < 0) { gUvOut.clear(); gUvFlips = 0; gUvStretch = 1.0f; return -1; }
    gUvFlips = st.flips; gUvStretch = st.stretch;
    return r;
}
KS_EXPORT(ks_uv_layout) int ks_uv_layout(const float* pos, int nv, const int* sizes, int nf, const int* fv, const int* fuv, int nc,
                                         int nuv, const float* uvIn, float paddingPx, float resolution, int rotate, int scaleMode, float margin) {
    UvCage c; c.pos = pos; c.nv = nv; c.sizes = sizes; c.nf = nf; c.fv = fv; c.fuv = fuv; c.nuv = nuv; c.nc = nc;
    UvLayoutSettings s; s.paddingPx = paddingPx; s.resolution = resolution; s.rotate = rotate; s.scaleMode = scaleMode; s.margin = margin;
    const int r = uvLayout(c, uvIn, s, gUvOut);
    gUvFuv.clear();
    if (r < 0) gUvOut.clear();
    return r;
}
// opts: up to 18 floats in this order (missing ones keep xatlas's defaults): maxChartArea, maxBoundaryLength,
// normalDeviationWeight, roundnessWeight, straightnessWeight, normalSeamWeight, textureSeamWeight, maxCost,
// maxIterations, padding, resolution, bilinear, blockAlign, bruteForce, rotateCharts, rotateChartsToAxis,
// texelsPerUnit, unfoldIterations. keepSeams 1: fuv / nuv (and uvIn, may be null) are the existing seams.
KS_EXPORT(ks_uv_auto) int ks_uv_auto(const float* pos, int nv, const int* sizes, int nf, const int* fv, int nc, int keepSeams,
                                     const int* fuv, int nuv, const float* uvIn, const float* opts, int nopts) {
    UvCage c; c.pos = pos; c.nv = nv; c.sizes = sizes; c.nf = nf; c.fv = fv; c.nc = nc;
    if (keepSeams) { c.fuv = fuv; c.nuv = nuv; }
    UvAutoOptions o;
    auto g = [&](int i, float d) { return opts && i < nopts ? opts[i] : d; };
    o.maxChartArea = g(0, o.maxChartArea); o.maxBoundaryLength = g(1, o.maxBoundaryLength);
    o.normalDeviationWeight = g(2, o.normalDeviationWeight); o.roundnessWeight = g(3, o.roundnessWeight);
    o.straightnessWeight = g(4, o.straightnessWeight); o.normalSeamWeight = g(5, o.normalSeamWeight);
    o.textureSeamWeight = g(6, o.textureSeamWeight); o.maxCost = g(7, o.maxCost);
    o.maxIterations = (int)g(8, (float)o.maxIterations); o.padding = (int)g(9, (float)o.padding);
    o.resolution = (int)g(10, (float)o.resolution);
    o.bilinear = g(11, o.bilinear ? 1.f : 0.f) != 0; o.blockAlign = g(12, o.blockAlign ? 1.f : 0.f) != 0;
    o.bruteForce = g(13, o.bruteForce ? 1.f : 0.f) != 0; o.rotateCharts = g(14, o.rotateCharts ? 1.f : 0.f) != 0;
    o.rotateChartsToAxis = g(15, o.rotateChartsToAxis ? 1.f : 0.f) != 0;
    o.texelsPerUnit = g(16, o.texelsPerUnit); o.unfoldIterations = (int)g(17, (float)o.unfoldIterations);
    UvAutoResult res;
    const int r = uvAuto(c, keepSeams ? uvIn : nullptr, keepSeams != 0, o, res);
    if (r < 0) { gUvOut.clear(); gUvFuv.clear(); return -1; }
    gUvOut.swap(res.uv); gUvFuv.swap(res.fuv);
    return r;
}
KS_EXPORT(ks_uv_out) const float* ks_uv_out() { return gUvOut.data(); }
KS_EXPORT(ks_uv_nuv) int ks_uv_nuv() { return (int)(gUvOut.size() / 2); }
KS_EXPORT(ks_uv_flips) int ks_uv_flips() { return gUvFlips; }
KS_EXPORT(ks_uv_stretch) float ks_uv_stretch() { return gUvStretch; }
KS_EXPORT(ks_uv_auto_fuv) const int* ks_uv_auto_fuv() { return gUvFuv.data(); }
KS_EXPORT(ks_uv_auto_nuv) int ks_uv_auto_nuv() { return (int)(gUvOut.size() / 2); }
