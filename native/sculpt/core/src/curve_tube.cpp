#include "sculpt/curve_tube.h"
#include "sculpt/voxel_remesh.h"
#include <algorithm>

namespace sculpt {

std::vector<Vec3> resamplePolyline(const std::vector<Vec3>& pts, float spacing) {
    std::vector<Vec3> out;
    if (pts.size() < 2 || spacing <= 0) return pts;
    out.push_back(pts[0]);
    float carry = 0;
    for (size_t i = 1; i < pts.size(); ++i) {
        Vec3 a = pts[i - 1], b = pts[i];
        float seg = length(b - a);
        float t = spacing - carry;
        while (t <= seg) {
            out.push_back(lerp(a, b, t / seg));
            t += spacing;
        }
        carry = seg - (t - spacing);
    }
    if (length(out.back() - pts.back()) > spacing * 0.3f) out.push_back(pts.back());
    return out;
}

Mesh sweepTube(const std::vector<Vec3>& raw, const TubeSettings& s) {
    Mesh m;
    if (raw.size() < 2 || s.sides < 3) return m;
    std::vector<Vec3> p = resamplePolyline(raw, s.radius * 0.5f);
    const int n = (int)p.size(), k = s.sides;

    // Tangents + parallel-transport (double reflection) frames.
    std::vector<Vec3> T(n), N(n);
    for (int i = 0; i < n; ++i)
        T[i] = normalize(i == 0 ? p[1] - p[0] : (i == n - 1 ? p[n - 1] - p[n - 2] : p[i + 1] - p[i - 1]));
    Vec3 up = std::fabs(T[0].y) < 0.9f ? Vec3{0, 1, 0} : Vec3{1, 0, 0};
    N[0] = normalize(projectOnPlane(up, T[0]));
    for (int i = 0; i + 1 < n; ++i) {
        Vec3 v1 = p[i + 1] - p[i];
        float c1 = dot(v1, v1);
        if (c1 < 1e-12f) { N[i + 1] = N[i]; continue; }
        Vec3 rL = N[i] - v1 * (2.0f / c1 * dot(v1, N[i]));
        Vec3 tL = T[i] - v1 * (2.0f / c1 * dot(v1, T[i]));
        Vec3 v2 = T[i + 1] - tL;
        float c2 = dot(v2, v2);
        N[i + 1] = c2 < 1e-12f ? rL : normalize(rL - v2 * (2.0f / c2 * dot(v2, rL)));
    }

    const float kTwoPi = 6.28318530718f;
    for (int i = 0; i < n; ++i) {
        float t = n > 1 ? (float)i / (n - 1) : 0;
        float r = s.radius * (1 - s.taperStart * (1 - t)) * (1 - s.taperEnd * t);
        if (!s.radiusCurve.empty()) r *= s.radiusCurve[std::min(s.radiusCurve.size() - 1, (size_t)(t * (s.radiusCurve.size() - 1)))];
        r = std::max(r, s.radius * 0.02f);
        Vec3 B = cross(T[i], N[i]);
        for (int j = 0; j < k; ++j) {
            float a = kTwoPi * j / k;
            m.positions.push_back(p[i] + (N[i] * std::cos(a) + B * std::sin(a)) * r);
        }
    }
    for (int i = 0; i + 1 < n; ++i)
        for (int j = 0; j < k; ++j) {
            int a = i * k + j, b = i * k + (j + 1) % k, c = (i + 1) * k + (j + 1) % k, d = (i + 1) * k + j;
            m.polyCounts.push_back(4);
            m.polyIndices.insert(m.polyIndices.end(), {a, b, c, d});
        }
    if (s.capEnds) {
        for (int end = 0; end < 2; ++end) {
            int ring = end == 0 ? 0 : (n - 1) * k;
            int c = (int)m.positions.size();
            m.positions.push_back(p[end == 0 ? 0 : n - 1]);
            for (int j = 0; j < k; ++j) {
                int a = ring + j, b = ring + (j + 1) % k;
                m.polyCounts.push_back(3);
                if (end == 0) m.polyIndices.insert(m.polyIndices.end(), {c, b, a});
                else m.polyIndices.insert(m.polyIndices.end(), {c, a, b});
            }
        }
    }
    // Triangulate polygons for the sculpt representation.
    size_t off = 0;
    for (int c : m.polyCounts) {
        for (int q = 1; q + 1 < c; ++q)
            m.tris.push_back({m.polyIndices[off], m.polyIndices[off + q], m.polyIndices[off + q + 1]});
        off += c;
    }
    // Orientation depends on frame handedness along the curve; normalize outward.
    if (s.capEnds && signedVolume(m) < 0) {
        for (auto& f : m.tris) std::swap(f[1], f[2]);
        off = 0;
        for (int c : m.polyCounts) { std::reverse(m.polyIndices.begin() + off, m.polyIndices.begin() + off + c); off += c; }
    }
    m.ensureAttributes();
    m.buildAdjacency();
    m.computeNormals();
    return m;
}

}  // namespace sculpt
