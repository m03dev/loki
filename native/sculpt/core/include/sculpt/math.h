// Sculpting engine — core math primitives. Header-only, no dependencies.
#pragma once
#include <cmath>
#include <algorithm>
#include <cstdint>

namespace sculpt {

struct Vec3 {
    float x = 0, y = 0, z = 0;
    Vec3() = default;
    constexpr Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
    Vec3 operator+(const Vec3& o) const { return {x + o.x, y + o.y, z + o.z}; }
    Vec3 operator-(const Vec3& o) const { return {x - o.x, y - o.y, z - o.z}; }
    Vec3 operator*(float s) const { return {x * s, y * s, z * s}; }
    Vec3 operator/(float s) const { return {x / s, y / s, z / s}; }
    Vec3 operator-() const { return {-x, -y, -z}; }
    Vec3& operator+=(const Vec3& o) { x += o.x; y += o.y; z += o.z; return *this; }
    Vec3& operator-=(const Vec3& o) { x -= o.x; y -= o.y; z -= o.z; return *this; }
    Vec3& operator*=(float s) { x *= s; y *= s; z *= s; return *this; }
    float operator[](int i) const { return i == 0 ? x : (i == 1 ? y : z); }
    float& operator[](int i) { return i == 0 ? x : (i == 1 ? y : z); }
};

inline Vec3 operator*(float s, const Vec3& v) { return v * s; }
inline float dot(const Vec3& a, const Vec3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Vec3 cross(const Vec3& a, const Vec3& b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
inline float length2(const Vec3& v) { return dot(v, v); }
inline float length(const Vec3& v) { return std::sqrt(dot(v, v)); }
inline Vec3 normalize(const Vec3& v) {
    float l = length(v);
    return l > 1e-20f ? v / l : Vec3{0, 0, 0};
}
inline Vec3 vmin(const Vec3& a, const Vec3& b) { return {std::min(a.x, b.x), std::min(a.y, b.y), std::min(a.z, b.z)}; }
inline Vec3 vmax(const Vec3& a, const Vec3& b) { return {std::max(a.x, b.x), std::max(a.y, b.y), std::max(a.z, b.z)}; }
inline Vec3 lerp(const Vec3& a, const Vec3& b, float t) { return a + (b - a) * t; }
inline float clamp01(float t) { return t < 0 ? 0 : (t > 1 ? 1 : t); }

// Project v onto the plane with unit normal n.
inline Vec3 projectOnPlane(const Vec3& v, const Vec3& n) { return v - n * dot(v, n); }

// Rodrigues rotation of v around unit axis k by angle a.
inline Vec3 rotate(const Vec3& v, const Vec3& k, float a) {
    float c = std::cos(a), s = std::sin(a);
    return v * c + cross(k, v) * s + k * (dot(k, v) * (1 - c));
}

struct AABB {
    Vec3 lo{1e30f, 1e30f, 1e30f}, hi{-1e30f, -1e30f, -1e30f};
    void expand(const Vec3& p) { lo = vmin(lo, p); hi = vmax(hi, p); }
    void expand(const AABB& b) { lo = vmin(lo, b.lo); hi = vmax(hi, b.hi); }
    Vec3 center() const { return (lo + hi) * 0.5f; }
    Vec3 extent() const { return hi - lo; }
    bool valid() const { return lo.x <= hi.x; }
    // Squared distance from point to box (0 if inside).
    float dist2(const Vec3& p) const {
        float d = 0;
        for (int i = 0; i < 3; ++i) {
            float v = p[i];
            if (v < lo[i]) d += (lo[i] - v) * (lo[i] - v);
            else if (v > hi[i]) d += (v - hi[i]) * (v - hi[i]);
        }
        return d;
    }
};

struct Ray {
    Vec3 origin, dir;  // dir normalized
};

}  // namespace sculpt
