// Sculpting engine v2 — sparse narrow-band signed-distance volume (voxel sculpting).
//
// For dense volumes a regular grid is hopeless (4096^3 is ~64 GB). This stores
// the surface as a sparse set of 8^3 bricks holding signed distance + sign, so
// memory scales with SURFACE AREA, not volume. Sculpt operations act on the
// distance field (union = min, subtraction = max of negated, offset = subtract
// a constant), so booleans / inflation / smoothing never re-triangulate the
// mesh. Extraction (naive Surface Nets) turns the field back into a quad mesh,
// which then feeds the same paged cluster store the triangle path uses.
#pragma once
#include "sculpt/mesh.h"
#include <array>
#include <cstdint>
#include <unordered_map>
#include <vector>

namespace sculpt {

struct SdfSettings {
    float voxelSize = 0.02f;
    float band = 3.0f;  // narrow-band half-width in voxels
};

class SdfVolume {
public:
    static constexpr int kBrick = 8;  // 8^3 = 512 voxels per brick

    void clear();
    bool empty() const { return bricks_.empty(); }
    size_t brickCount() const { return bricks_.size(); }
    size_t voxelCount() const { return bricks_.size() * kBrick * kBrick * kBrick; }
    float voxelSize() const { return voxelSize_; }
    float band() const { return band_; }
    AABB bounds() const;                    // world bounds of the active bricks
    // A dense grid of the same world extent would hold this many voxels (for the
    // sparsity comparison).
    size_t denseVoxelCount() const;

    // Build a narrow band from a mesh (min distance to its triangles).
    void fromMesh(const Mesh& m, const SdfSettings& s);
    // SDF sculpt operators (distance-field maths, no remesh).
    void addSphere(const Vec3& c, float r);        // union
    void subtractSphere(const Vec3& c, float r);   // subtraction
    void offset(float amount);                     // inflate (amount>0) / erode
    void smooth(int iterations, float amount);     // blur the narrow band

    float sample(const Vec3& p) const;             // bilinear-ish nearest distance
    // Naive Surface Nets -> all-quad mesh (one vertex per sign-changing cell).
    Mesh toMesh() const;

private:
    float voxelSize_ = 0.02f;
    float band_ = 3.0f;
    std::unordered_map<uint64_t, std::array<float, kBrick * kBrick * kBrick>> bricks_;

    static int64_t floorDiv(int a, int b);
    float farW() const { return band_ * voxelSize_ * 4.0f + 1.0f; }  // sentinel for 'not stored'
    bool setVoxelMag(int gx, int gy, int gz, float d);  // keep smallest |d| (build from mesh)
    bool setVoxelMin(int gx, int gy, int gz, float d);  // keep smallest signed d (union)
    void setFill(int gx, int gy, int gz, float d);       // write only if currently unset
    void widenBand(int layers);                          // extrapolate sign outward before extraction
    float sampleGrid(int gx, int gy, int gz) const;  // +far for absent voxels
    bool present(int gx, int gy, int gz) const;      // voxel is inside the stored band
    const std::array<float, kBrick * kBrick * kBrick>* brickAt(int gx, int gy, int gz, int& lx, int& ly, int& lz) const;
};

}  // namespace sculpt
