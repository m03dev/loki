// Sculpting engine — hashed value noise (deterministic, no tables) for SurfaceNoise and
// the cloth fold seed.
#pragma once
#include "sculpt/math.h"

namespace sculpt {

inline float hash3(int x, int y, int z) {
    uint32_t h = (uint32_t)x * 374761393u + (uint32_t)y * 668265263u + (uint32_t)z * 2147483647u;
    h = (h ^ (h >> 13)) * 1274126177u;
    return (float)((h ^ (h >> 16)) & 0xffffff) / (float)0xffffff;
}

// Trilinear value noise in [0,1] with smoothstep interpolation.
inline float valueNoise3(const Vec3& p) {
    int x0 = (int)std::floor(p.x), y0 = (int)std::floor(p.y), z0 = (int)std::floor(p.z);
    float fx = p.x - x0, fy = p.y - y0, fz = p.z - z0;
    auto s = [](float t) { return t * t * (3 - 2 * t); };
    fx = s(fx); fy = s(fy); fz = s(fz);
    float v = 0;
    for (int dz = 0; dz < 2; ++dz)
        for (int dy = 0; dy < 2; ++dy)
            for (int dx = 0; dx < 2; ++dx) {
                float w = (dx ? fx : 1 - fx) * (dy ? fy : 1 - fy) * (dz ? fz : 1 - fz);
                v += w * hash3(x0 + dx, y0 + dy, z0 + dz);
            }
    return v;
}

inline float fbm3(Vec3 p, int octaves) {
    float sum = 0, amp = 0.5f, norm = 0;
    for (int i = 0; i < octaves; ++i) {
        sum += amp * valueNoise3(p);
        norm += amp;
        p = p * 2.03f;
        amp *= 0.5f;
    }
    return sum / norm;
}

}  // namespace sculpt
