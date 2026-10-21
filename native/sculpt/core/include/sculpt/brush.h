// Sculpting engine — brush engine.
//
// Every brush is (kernel, parameters). Kernels are the math (docs/MATH.md has a
// section per kernel); the preset library in brushes/ is hundreds of parameter
// sets over these kernels, which is how and ship large brush
// counts too.
#pragma once
#include "sculpt/bvh.h"
#include "sculpt/mesh.h"
#include <memory>
#include <string>
#include <vector>

namespace sculpt {

enum class Kernel {
    // additive
    Standard, DamStandard, Inflate, Blob, Displace, Magnify, Pinch, Layer, SurfaceNoise, Crease,
    // plane-based (clay family + hard surface)
    Clay, ClayBuildup, ClayStrips, Flatten, Fill, Scrape, Planar, TrimDynamic, TrimAdaptive, Polish,
    MultiplaneScrape,
    // smoothing
    Smooth, SmoothRelax,
    // transform
    Move, MoveElastic, MoveInfiniteDepth, MoveTopological, SnakeHook, Nudge, Rotate,
    ElasticTwist, ElasticScale, Pose, Thumb,
    // simulation / targets
    Cloth, Morph, HistoryRecall,
    // non-geometric
    Mask, Paint,
    COUNT
};

const char* kernelName(Kernel k);
bool kernelFromName(const std::string& s, Kernel& out);
bool kernelIsGrab(Kernel k);  // vertex set fixed at press (Move family, Cloth)

enum class FalloffPreset { Smooth, Sphere, Root, Sharp, Linear, Constant, Custom };

// Radial falloff f(x), x = distance / radius in [0,1]. Custom = piecewise-linear
// through (x, y) control points (the curve editor in the panel writes these).
struct Falloff {
    FalloffPreset preset = FalloffPreset::Smooth;
    std::vector<std::pair<float, float>> points;
    float eval(float x) const;
};

// Grayscale stamp ("Alpha", "texture"). Sampled in the brush's
// tangent plane: (u, v) in [-1, 1]^2 -> [0, 1].
struct Alpha {
    int width = 0, height = 0;
    std::vector<float> data;
    float midValue = 0.0f;  // MidValue: value treated as zero displacement
    float sample(float u, float v) const;  // bilinear, clamped
    bool valid() const { return width > 0 && height > 0; }
};

struct Brush {
    std::string name = "Standard";
    Kernel kernel = Kernel::Standard;
    float radius = 1.0f;       // world units (host converts from screen pixels)
    float strength = 0.5f;     // 0..1 (Z Intensity)
    float spacing = 0.1f;      // dab spacing as a fraction of radius
    bool invert = false;       // Alt in , Ctrl in 
    bool frontFacesOnly = true;
    bool usePressure = true;
    Falloff falloff;
    std::shared_ptr<Alpha> alpha;
    bool alphaFollowStroke = true;  // rotate alpha with stroke direction

    // Plane brushes
    float planeOffset = 0.0f;       // fraction of radius; >0 lifts plane (clay buildup)
    float planeTrim = 0.5f;         // fraction of radius beyond which plane brushes stop
    bool squareTip = false;         // ClayStrips style square footprint
    float tipRoundness = 1.0f;      // 1 = round, 0 = square

    // Layer
    float layerHeight = 0.05f;      // fraction of radius

    // Pinch component (DamStandard, Crease, SnakeHook)
    float pinch = 0.0f;

    // Elastic move (Kelvinlet)
    float poisson = 0.4f;           // 0 = compressible, 0.5 = volume-preserving

    // Multiplane Scrape: tilt of each of the two planes from the area plane
    float planeAngle = 30.0f;       // degrees

    // Cloth
    int clothIterations = 6;
    float clothDamping = 0.1f;
    float clothGravity = 0.0f;

    // Smoothing
    float autoSmooth = 0.0f;        // smooth applied after every dab (weighted by the dab's falloff)
    int smoothIterations = 1;
    // Volume preservation of the Smooth kernel and of auto-smooth, 0..1:
    // 0 = the classic umbrella Laplacian (shrinks: thin parts thin out, spheres
    // get smaller), 1 = the HC step (Vollmer, Mencl & Mueller 1999, alpha = 0,
    // beta = 0.5), which removes bumps but leaves constant-curvature surfaces
    // where they are. Between the two blends the steps.
    float smoothVolume = 0.5f;
    // The same for auto-smooth. 0 (the classic Laplacian, as before) by
    // default: under a build-up brush its slight shrink is welcome and it is
    // the stronger of the two on the per-vertex ripples plane brushes leave.
    float autoSmoothVolume = 0.0f;

    // Noise
    float noiseScale = 4.0f;        // features per radius

    // Paint
    Vec3 color{1, 0.2f, 0.2f};

    // Symmetry: bit 0 = X, 1 = Y, 2 = Z (mirror across object-space planes)
    int symmetry = 0;
};

// One brush sample.
struct Dab {
    Vec3 position;        // surface hit (world/object space, same space as Mesh)
    Vec3 normal;          // surface normal at hit
    Vec3 viewDir;         // camera forward
    Ray ray;              // camera ray through the cursor (Move Infinite Depth)
    Vec3 grabDelta;       // Move family: cursor movement since press, in the view plane
    Vec3 dabDelta;        // movement since previous dab (Snake Hook, Nudge)
    float pressure = 1.0f;
    float angle = 0.0f;   // Rotate brush: radians since press
};

// Snapshots used by Morph / History Recall.
struct TargetSnapshot {
    std::vector<Vec3> positions;
};

class BrushEngine {
public:
    explicit BrushEngine(Mesh& mesh);

    void rebuildSpatial();   // after topology change
    void refitSpatial();     // after positions change (partial when few verts moved)
    BVH& bvh() { return bvh_; }
    Mesh& mesh() { return mesh_; }

    void setMorphTarget(std::shared_ptr<TargetSnapshot> s) { morph_ = std::move(s); }
    void setRecallTarget(std::shared_ptr<TargetSnapshot> s) { recall_ = std::move(s); }

    void beginStroke(const Brush& b, const Dab& d);
    void applyDab(const Brush& b, const Dab& d);   // one sample; host spaces them
    void endStroke();

    // Vertices touched during the current stroke (for undo diffs and partial
    // host write-back).
    const std::vector<int>& strokeTouched() const { return touchedList_; }
    // Vertices moved since the last call (host write-back); clears the list.
    // Lets the host update only what changed this event instead of everything
    // touched since the stroke began (which grows with stroke length).
    void takeHostDirty(std::vector<int>& out);
    const std::vector<Vec3>& strokeOriginal() const { return origPos_; }

    // Smooth helper usable from commands (e.g. post-voxel remesh relax).
    // Set positions directly (undo/redo, history): normals, BVH and host-dirty
    // tracking update exactly as for a dab.
    void setPositions(const std::vector<int>& verts, const std::vector<Vec3>& pos);

    void smoothVerts(const std::vector<int>& verts, float strength, int iterations, bool tangentialOnly);

    // Weighted smoothing of a region: vertex i moves by min(1, strength * w[i])
    // of its smoothing step; `volume` blends the umbrella Laplacian (0) with the
    // volume-preserving HC step (1). Used by the Smooth kernel and auto-smooth.
    void smoothRegion(const std::vector<int>& verts, const std::vector<float>& w, float strength,
                      int iterations, float volume, bool tangentialOnly);

private:
    struct Instance {          // one per symmetry mirror
        Vec3 mirror{1, 1, 1};
        std::vector<int> grabVerts;
        std::vector<float> grabWeights;
        Vec3 startPos, startNormal;
        Vec3 planeCenter, planeNormal;  // stroke-start plane (Planar)
        Vec3 pivot;                     // Pose: joint the segment rotates about
        // grab brushes move the same vertex set every dab: its normal ring,
        // triangles and dirty BVH nodes are computed once per stroke
        std::vector<int> ringCache, trisCache, nodeCache;
    };

    Mesh& mesh_;
    BVH bvh_;
    std::vector<Instance> inst_;
    std::vector<Vec3> origPos_, origNrm_;
    std::vector<float> layerDisp_;
    std::vector<char> touched_;
    std::vector<int> touchedList_;
    std::vector<Vec3> disp_;      // scratch displacement buffer
    std::vector<int> verts_;      // scratch query buffer
    std::vector<float> weights_;
    std::vector<int> dirtyVerts_;          // moved since the last refit
    std::vector<char> dirtyMark_;
    std::vector<int> dirtyTris_;           // scratch
    std::vector<char> triMark_;            // scratch (all zero between uses)
    std::vector<int> changed_;             // positions/normals changed since the last beginStroke
    std::vector<char> changedMark_;
    bool fullResync_ = true;               // stroke buffers must be rebuilt (new mesh / topology)
    std::vector<int> hostDirty_;
    std::vector<char> hostMark_;
    std::shared_ptr<TargetSnapshot> morph_, recall_;
    Vec3 lastStrokeDir_{1, 0, 0};

    void markTouched(const std::vector<int>& vs);
    float vertexWeight(const Brush& b, const Dab& d, const Vec3& center, const Vec3& normal,
                       const Vec3& tangent, int v, float pressure) const;
    void areaPlane(const std::vector<int>& vs, const std::vector<float>& w, Vec3& c, Vec3& n) const;
    void dabInstance(const Brush& b, const Dab& d, Instance& in);
    void applyDisplacements(const std::vector<int>& vs, Instance* fixedSet = nullptr);
    std::vector<Instance*> pendingRefit_;  // grab instances whose cached triangles need a refit
    // smoothing scratch (region + one ring, compact): slot of a vertex in it, its Laplacian
    std::vector<int> smSlot_, smRing_;
    std::vector<Vec3> smLap_;
    // normals scratch: triangles around the moved ring, each face normal computed once
    std::vector<int> nrmSlot_, nrmTris_;
    std::vector<Vec3> nrmFace_;
    void recomputeRingNormals(const std::vector<int>& ring);
};

}  // namespace sculpt
