// Sculpting engine: Instant Meshes' BVH is only needed for point-cloud input and for its
// optional extraction smoothing, neither of which Sculpting uses (meshes only,
// smoothing done by Sculpting engine's own BVH). These stubs satisfy the linker; the
// original bvh.cpp depends on TBB's task scheduler.
#include "bvh.h"
#include <stdexcept>

bool BVH::rayIntersect(Ray, uint32_t &, Float &, Vector2f *) const {
    throw std::runtime_error("Instant Meshes BVH is not available in this build");
}

void BVH::findKNearest(const Vector3f &, const Vector3f &, uint32_t, Float &,
                       std::vector<std::pair<Float, uint32_t>> &, Float, bool) const {
    throw std::runtime_error("Instant Meshes BVH is not available in this build");
}
