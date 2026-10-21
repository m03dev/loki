#include "sculpt/sdf_volume.h"
#include <algorithm>
#include <cmath>
#include <cfloat>
#include <cstdio>

namespace sculpt {

static inline uint64_t key3(int x, int y, int z) {
    uint64_t ox = (uint64_t)(x + (1 << 20)) & 0x1FFFFF;
    uint64_t oy = (uint64_t)(y + (1 << 20)) & 0x1FFFFF;
    uint64_t oz = (uint64_t)(z + (1 << 20)) & 0x1FFFFF;
    return (ox << 42) | (oy << 21) | oz;
}

static constexpr int kB = SdfVolume::kBrick;
static constexpr int kBV = kB * kB * kB;

int64_t SdfVolume::floorDiv(int a, int b) { int q = a / b; if ((a % b) != 0 && ((a < 0) != (b < 0))) --q; return q; }

void SdfVolume::clear() { bricks_.clear(); }

float SdfVolume::sampleGrid(int gx, int gy, int gz) const {
    int lx, ly, lz;
    const auto* br = brickAt(gx, gy, gz, lx, ly, lz);
    if (!br) return farW();  // absent brick = far outside
    return (*br)[(lz * kB + ly) * kB + lx];
}

bool SdfVolume::present(int gx, int gy, int gz) const {
    int lx, ly, lz;
    const auto* br = brickAt(gx, gy, gz, lx, ly, lz);
    if (!br) return false;
    return (*br)[(lz * kB + ly) * kB + lx] != farW();  // brick exists, but this voxel may be unset
}

const std::array<float, kBV>* SdfVolume::brickAt(int gx, int gy, int gz, int& lx, int& ly, int& lz) const {
    int bx = (int)floorDiv(gx, kB), by = (int)floorDiv(gy, kB), bz = (int)floorDiv(gz, kB);
    lx = gx - bx * kB; ly = gy - by * kB; lz = gz - bz * kB;
    auto it = bricks_.find(key3(bx, by, bz));
    return it == bricks_.end() ? nullptr : &it->second;
}

bool SdfVolume::setVoxelMag(int gx, int gy, int gz, float d) {
    int bx = (int)floorDiv(gx, kB), by = (int)floorDiv(gy, kB), bz = (int)floorDiv(gz, kB);
    int lx = gx - bx * kB, ly = gy - by * kB, lz = gz - bz * kB;
    uint64_t k = key3(bx, by, bz);
    auto it = bricks_.find(k);
    bool created = false;
    if (it == bricks_.end()) {
        std::array<float, kBV> br; br.fill(farW());
        it = bricks_.emplace(k, br).first; created = true;
    }
    float& slot = it->second[(lz * kB + ly) * kB + lx];
    if (std::fabs(d) < std::fabs(slot)) slot = d;
    return created;
}

bool SdfVolume::setVoxelMin(int gx, int gy, int gz, float d) {
    int bx = (int)floorDiv(gx, kB), by = (int)floorDiv(gy, kB), bz = (int)floorDiv(gz, kB);
    int lx = gx - bx * kB, ly = gy - by * kB, lz = gz - bz * kB;
    uint64_t k = key3(bx, by, bz);
    auto it = bricks_.find(k);
    bool created = false;
    if (it == bricks_.end()) {
        std::array<float, kBV> br; br.fill(farW());
        it = bricks_.emplace(k, br).first; created = true;
    }
    float& slot = it->second[(lz * kB + ly) * kB + lx];
    if (d < slot) slot = d;
    return created;
}

void SdfVolume::setFill(int gx, int gy, int gz, float d) {
    int bx = (int)floorDiv(gx, kB), by = (int)floorDiv(gy, kB), bz = (int)floorDiv(gz, kB);
    int lx = gx - bx * kB, ly = gy - by * kB, lz = gz - bz * kB;
    uint64_t k = key3(bx, by, bz);
    auto it = bricks_.find(k);
    if (it == bricks_.end()) {
        std::array<float, kBV> br; br.fill(farW());
        it = bricks_.emplace(k, br).first;
    }
    float& slot = it->second[(lz * kB + ly) * kB + lx];
    if (slot == farW()) slot = d;
}

void SdfVolume::widenBand(int layers) {
    const float bandW = band_ * voxelSize_;
    std::vector<std::array<int, 3>> cur;
    for (auto& kv : bricks_) {
        uint64_t k = kv.first;
        int bx = (int)((k >> 42) & 0x1FFFFF) - (1 << 20);
        int by = (int)((k >> 21) & 0x1FFFFF) - (1 << 20);
        int bz = (int)(k & 0x1FFFFF) - (1 << 20);
        for (int lz = 0; lz < kB; ++lz)
            for (int ly = 0; ly < kB; ++ly)
                for (int lx = 0; lx < kB; ++lx) {
                    int gx = bx * kB + lx, gy = by * kB + ly, gz = bz * kB + lz;
                    if (present(gx, gy, gz)) cur.push_back({gx, gy, gz});
                }
    }
    for (int pass = 0; pass < layers; ++pass) {
        std::vector<std::array<int, 3>> next;
        for (auto& g : cur) {
            float v = sampleGrid(g[0], g[1], g[2]);
            float s = v < 0 ? -1.0f : 1.0f;
            for (int dz = -1; dz <= 1; ++dz)
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        if (!dx && !dy && !dz) continue;
                        int nx = g[0] + dx, ny = g[1] + dy, nz = g[2] + dz;
                        if (!present(nx, ny, nz)) { setFill(nx, ny, nz, s * bandW); next.push_back({nx, ny, nz}); }
                    }
        }
        cur.swap(next);
    }
}

AABB SdfVolume::bounds() const {
    AABB b;
    for (auto& kv : bricks_) {
        uint64_t k = kv.first;
        int bx = (int)((k >> 42) & 0x1FFFFF) - (1 << 20);
        int by = (int)((k >> 21) & 0x1FFFFF) - (1 << 20);
        int bz = (int)(k & 0x1FFFFF) - (1 << 20);
        float s = voxelSize_;
        b.expand(Vec3(bx * kB * s, by * kB * s, bz * kB * s));
        b.expand(Vec3((bx * kB + kB) * s, (by * kB + kB) * s, (bz * kB + kB) * s));
    }
    return b;
}

size_t SdfVolume::denseVoxelCount() const {
    AABB b = bounds();
    if (!b.valid()) return 0;
    Vec3 e = b.extent();
    double vx = std::ceil(e.x / voxelSize_), vy = std::ceil(e.y / voxelSize_), vz = std::ceil(e.z / voxelSize_);
    return (size_t)std::max(0.0, vx * vy * vz);
}

// ---- closest point on a triangle (Ericson 5.1.5) -------------------------
static Vec3 closestPointTri(const Vec3& p, const Vec3& a, const Vec3& b, const Vec3& c) {
    Vec3 ab = b - a, ac = c - a, ap = p - a;
    float d1 = dot(ab, ap), d2 = dot(ac, ap);
    if (d1 <= 0 && d2 <= 0) return a;
    Vec3 bp = p - b; float d3 = dot(ab, bp), d4 = dot(ac, bp);
    if (d3 >= 0 && d4 <= d3) return b;
    float vc = d1 * d4 - d3 * d2;
    if (vc <= 0 && d1 >= 0 && d3 <= 0) { float v = d1 / (d1 - d3); return a + ab * v; }
    Vec3 cp = p - c; float d5 = dot(ab, cp), d6 = dot(ac, cp);
    if (d6 >= 0 && d5 <= d6) return c;
    float vb = d5 * d2 - d1 * d6;
    if (vb <= 0 && d2 >= 0 && d6 <= 0) { float w = d2 / (d2 - d6); return a + ac * w; }
    float va = d3 * d6 - d5 * d4;
    if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) { float w = (d4 - d3) / ((d4 - d3) + (d5 - d6)); return b + (c - b) * w; }
    float denom = va + vb + vc;
    if (denom < 1e-20f) return a;
    float v = vb / denom, w = vc / denom;
    return a + ab * v + ac * w;
}

void SdfVolume::fromMesh(const Mesh& m, const SdfSettings& s) {
    clear();
    voxelSize_ = s.voxelSize;
    band_ = s.band;
    const float bandW = band_ * voxelSize_;
    // area-weighted vertex normals (pseudonormal sign is stable at shared edges)
    std::vector<Vec3> vn(m.positions.size(), Vec3{0, 0, 0});
    for (const Tri& t : m.tris)
        if (t[0] >= 0) {
            Vec3 n = cross(m.positions[t[1]] - m.positions[t[0]], m.positions[t[2]] - m.positions[t[0]]);
            vn[t[0]] += n; vn[t[1]] += n; vn[t[2]] += n;
        }
    for (Vec3& v : vn) v = normalize(v);
    for (const Tri& t : m.tris) {
        if (t[0] < 0) continue;
        const Vec3 a = m.positions[t[0]], b = m.positions[t[1]], c = m.positions[t[2]];
        Vec3 fn = normalize(cross(b - a, c - a));
        Vec3 lo = vmin(a, vmin(b, c)) - Vec3(bandW, bandW, bandW);
        Vec3 hi = vmax(a, vmax(b, c)) + Vec3(bandW, bandW, bandW);
        int gx0 = (int)std::floor(lo.x / voxelSize_), gx1 = (int)std::ceil(hi.x / voxelSize_);
        int gy0 = (int)std::floor(lo.y / voxelSize_), gy1 = (int)std::ceil(hi.y / voxelSize_);
        int gz0 = (int)std::floor(lo.z / voxelSize_), gz1 = (int)std::ceil(hi.z / voxelSize_);
        for (int gz = gz0; gz <= gz1; ++gz)
            for (int gy = gy0; gy <= gy1; ++gy)
                for (int gx = gx0; gx <= gx1; ++gx) {
                    Vec3 p(gx * voxelSize_, gy * voxelSize_, gz * voxelSize_);
                    Vec3 cp = closestPointTri(p, a, b, c);
                    float d = length(p - cp);
                    if (d >= bandW) continue;
                    // barycentric weights of cp -> interpolated vertex normal (pseudonormal)
                    Vec3 e0 = cross(cp - b, cp - c), e1 = cross(cp - c, cp - a), e2 = cross(cp - a, cp - b);
                    float wa = length(e0), wb = length(e1), wc = length(e2);
                    float tot = wa + wb + wc;
                    Vec3 n = tot > 1e-20f ? normalize(vn[t[0]] * wa + vn[t[1]] * wb + vn[t[2]] * wc) : fn;
                    if (length2(n) < 0.5f) n = fn;
                    float sd = dot(p - cp, n) < 0.0f ? -d : d;
                    setVoxelMag(gx, gy, gz, sd);
                }
    }
}

void SdfVolume::addSphere(const Vec3& c, float r) {
    Vec3 lo = c - Vec3(r + band_ * voxelSize_, r + band_ * voxelSize_, r + band_ * voxelSize_);
    Vec3 hi = c + Vec3(r + band_ * voxelSize_, r + band_ * voxelSize_, r + band_ * voxelSize_);
    int gx0 = (int)std::floor(lo.x / voxelSize_), gx1 = (int)std::ceil(hi.x / voxelSize_);
    int gy0 = (int)std::floor(lo.y / voxelSize_), gy1 = (int)std::ceil(hi.y / voxelSize_);
    int gz0 = (int)std::floor(lo.z / voxelSize_), gz1 = (int)std::ceil(hi.z / voxelSize_);
    for (int gz = gz0; gz <= gz1; ++gz)
        for (int gy = gy0; gy <= gy1; ++gy)
            for (int gx = gx0; gx <= gx1; ++gx) {
                Vec3 p(gx * voxelSize_, gy * voxelSize_, gz * voxelSize_);
                float d = length(p - c) - r;
                if (std::fabs(d) < band_ * voxelSize_) setVoxelMin(gx, gy, gz, d);
            }
}

void SdfVolume::subtractSphere(const Vec3& c, float r) {
    // d = max(d, -(length(p-c)-r)) over the sphere's band and everything inside it
    Vec3 lo = c - Vec3(r + band_ * voxelSize_, r + band_ * voxelSize_, r + band_ * voxelSize_);
    Vec3 hi = c + Vec3(r + band_ * voxelSize_, r + band_ * voxelSize_, r + band_ * voxelSize_);
    int gx0 = (int)std::floor(lo.x / voxelSize_), gx1 = (int)std::ceil(hi.x / voxelSize_);
    int gy0 = (int)std::floor(lo.y / voxelSize_), gy1 = (int)std::ceil(hi.y / voxelSize_);
    int gz0 = (int)std::floor(lo.z / voxelSize_), gz1 = (int)std::ceil(hi.z / voxelSize_);
    for (int gz = gz0; gz <= gz1; ++gz)
        for (int gy = gy0; gy <= gy1; ++gy)
            for (int gx = gx0; gx <= gx1; ++gx) {
                int lx, ly, lz;
                const auto* br = brickAt(gx, gy, gz, lx, ly, lz);
                if (!br) continue;                      // only rewrite existing voxels
                Vec3 p(gx * voxelSize_, gy * voxelSize_, gz * voxelSize_);
                float neg = -(length(p - c) - r);
                float& slot = const_cast<std::array<float, kBV>*>(br)->at((lz * kB + ly) * kB + lx);
                if (neg > slot) slot = neg;
            }
}

void SdfVolume::offset(float amount) {
    float far = farW();
    for (auto& kv : bricks_)
        for (float& d : kv.second)
            if (d != far) d -= amount;
}

void SdfVolume::smooth(int iterations, float amount) {
    for (int it = 0; it < iterations; ++it) {
        std::vector<float> vals;
        std::vector<uint64_t> keys;
        std::vector<int> idxs;
        for (auto& kv : bricks_) {
            for (int lz = 0; lz < kB; ++lz)
                for (int ly = 0; ly < kB; ++ly)
                    for (int lx = 0; lx < kB; ++lx)
                        vals.push_back(kv.second[(lz * kB + ly) * kB + lx]);
            keys.push_back(kv.first);
        }
        // rebuild with a 6-neighbour average, sampling across bricks
        int vi = 0;
        for (size_t bi = 0; bi < keys.size(); ++bi) {
            uint64_t k = keys[bi];
            int bx = (int)((k >> 42) & 0x1FFFFF) - (1 << 20);
            int by = (int)((k >> 21) & 0x1FFFFF) - (1 << 20);
            int bz = (int)(k & 0x1FFFFF) - (1 << 20);
            auto& out = bricks_[k];
            for (int lz = 0; lz < kB; ++lz)
                for (int ly = 0; ly < kB; ++ly)
                    for (int lx = 0; lx < kB; ++lx) {
                        int gx = bx * kB + lx, gy = by * kB + ly, gz = bz * kB + lz;
                        float self = vals[vi++];
                        float sum = self;
                        sum += sampleGrid(gx + 1, gy, gz) + sampleGrid(gx - 1, gy, gz);
                        sum += sampleGrid(gx, gy + 1, gz) + sampleGrid(gx, gy - 1, gz);
                        sum += sampleGrid(gx, gy, gz + 1) + sampleGrid(gx, gy, gz - 1);
                        out[(lz * kB + ly) * kB + lx] = self + (sum / 7.0f - self) * amount;
                    }
        }
    }
}

float SdfVolume::sample(const Vec3& p) const {
    int gx = (int)std::lround(p.x / voxelSize_), gy = (int)std::lround(p.y / voxelSize_), gz = (int)std::lround(p.z / voxelSize_);
    return sampleGrid(gx, gy, gz);
}

// ---- Surface Nets extraction --------------------------------------------
Mesh SdfVolume::toMesh() const {
    const_cast<SdfVolume*>(this)->widenBand(8);  // fill voids around booleans with the correct sign
    const float vs = voxelSize_;
    const float bandW = band_ * voxelSize_;
    // Value at a grid point: stored distance if present, else the sign of the
    // nearest stored voxel times the band (extrapolation). Unset voxels are far
    // from the surface, so this keeps the bulk sign and avoids false surfaces.
    auto valAt = [&](int gx, int gy, int gz) -> float {
        for (int r = 0; r <= 2; ++r) {
            for (int dz = -r; dz <= r; ++dz)
                for (int dy = -r; dy <= r; ++dy)
                    for (int dx = -r; dx <= r; ++dx) {
                        if (std::max(std::abs(dx), std::max(std::abs(dy), std::abs(dz))) != r) continue;
                        int lx, ly, lz;
                        const auto* br = brickAt(gx + dx, gy + dy, gz + dz, lx, ly, lz);
                        if (br) {
                            float v = (*br)[(lz * kB + ly) * kB + lx];
                            if (v != farW()) return r == 0 ? v : (v < 0 ? -bandW : bandW);
                        }
                    }
        }
        return bandW;  // nothing nearby: outside
    };
    auto inside = [&](int gx, int gy, int gz) { return valAt(gx, gy, gz) < 0.0f; };

    static const int corner[8][3] = {{0,0,0},{1,0,0},{1,1,0},{0,1,0},{0,0,1},{1,0,1},{1,1,1},{0,1,1}};
    static const int edge[12][2] = {{0,1},{1,2},{2,3},{3,0},{4,5},{5,6},{6,7},{7,4},{0,4},{1,5},{2,6},{3,7}};

    // 1. one vertex per sign-changing cell (cell = min-corner voxel of a cube)
    std::unordered_map<uint64_t, uint32_t> cellVert;
    std::vector<Vec3> positions;
    std::unordered_map<uint64_t, uint8_t> seenCell;
    for (auto& kv : bricks_) {
        uint64_t k = kv.first;
        int bx = (int)((k >> 42) & 0x1FFFFF) - (1 << 20);
        int by = (int)((k >> 21) & 0x1FFFFF) - (1 << 20);
        int bz = (int)(k & 0x1FFFFF) - (1 << 20);
        for (int lz = 0; lz < kB; ++lz)
            for (int ly = 0; ly < kB; ++ly)
                for (int lx = 0; lx < kB; ++lx) {
                    if (kv.second[(lz * kB + ly) * kB + lx] >= 0.0f) continue;  // only cells touching an inside voxel
                    int sx = bx * kB + lx, sy = by * kB + ly, sz = bz * kB + lz;
                    for (int ci = 0; ci < 8; ++ci) {
                        int cx = sx + corner[ci][0] - 1, cy = sy + corner[ci][1] - 1, cz = sz + corner[ci][2] - 1;
                        uint64_t ck = key3(cx, cy, cz);
                        if (cellVert.count(ck)) continue;
                        float v[8];
                        bool neg = false, pos = false, allPresent = true;
                        for (int j = 0; j < 8; ++j) {
                            int jx = cx + corner[j][0], jy = cy + corner[j][1], jz = cz + corner[j][2];
                            if (!present(jx, jy, jz)) { allPresent = false; break; }
                            v[j] = sampleGrid(jx, jy, jz);
                            if (v[j] < 0) neg = true; else pos = true;
                        }
                        if (!allPresent || !(neg && pos)) { cellVert[ck] = UINT32_MAX; continue; }
                        Vec3 sum{0, 0, 0}; int n = 0;
                        for (int e = 0; e < 12; ++e) {
                            int a = edge[e][0], b = edge[e][1];
                            if ((v[a] < 0) == (v[b] < 0)) continue;
                            float t = v[a] / (v[a] - v[b]);
                            Vec3 pa((cx + corner[a][0]) * vs, (cy + corner[a][1]) * vs, (cz + corner[a][2]) * vs);
                            Vec3 pb((cx + corner[b][0]) * vs, (cy + corner[b][1]) * vs, (cz + corner[b][2]) * vs);
                            sum += pa + (pb - pa) * t; ++n;
                        }
                        Vec3 p = n ? sum / (float)n : Vec3((cx + 0.5f) * vs, (cy + 0.5f) * vs, (cz + 0.5f) * vs);
                        cellVert[ck] = (uint32_t)positions.size();
                        positions.push_back(p);
                    }
                }
    }

    // 2. one quad per sign-changing grid edge, joining the 4 cells around it
    int gEdgesTried = 0;
    std::vector<int> counts, indices;
    std::unordered_map<uint64_t, uint8_t> doneEdge;
    // Create a cell's vertex on demand: an edge may border a cell that was never
    // seeded above (its inside corner is an extrapolated voxel), which would
    // otherwise leave a hole.
    auto getOrMakeCell = [&](int cx, int cy, int cz) -> int {
        uint64_t ck = key3(cx, cy, cz);
        auto it = cellVert.find(ck);
        if (it != cellVert.end() && it->second != UINT32_MAX) return (int)it->second;
        // else (unseeded, or seeded without all corners present): recompute from the
        // extrapolated field. Only real sign-changing edges reach here, so this
        // stays near the true surface and cannot invent an interior sheet.
        float v[8];
        bool neg = false, pos = false;
        for (int j = 0; j < 8; ++j) {
            v[j] = valAt(cx + corner[j][0], cy + corner[j][1], cz + corner[j][2]);
            if (v[j] < 0) neg = true; else pos = true;
        }
        if (!(neg && pos)) { cellVert[ck] = UINT32_MAX; return -1; }
        Vec3 sum{0, 0, 0}; int n = 0;
        for (int e = 0; e < 12; ++e) {
            int a = edge[e][0], b = edge[e][1];
            if ((v[a] < 0) == (v[b] < 0)) continue;
            float t = v[a] / (v[a] - v[b]);
            Vec3 pa((cx + corner[a][0]) * vs, (cy + corner[a][1]) * vs, (cz + corner[a][2]) * vs);
            Vec3 pb((cx + corner[b][0]) * vs, (cy + corner[b][1]) * vs, (cz + corner[b][2]) * vs);
            sum += pa + (pb - pa) * t; ++n;
        }
        Vec3 p = n ? sum / (float)n : Vec3((cx + 0.5f) * vs, (cy + 0.5f) * vs, (cz + 0.5f) * vs);
        uint32_t id = (uint32_t)positions.size();
        positions.push_back(p);
        cellVert[ck] = id;
        return (int)id;
    };

    // orient each quad from its own geometry so its normal points inside->outside
    auto emit = [&](int a, int b, int c, int d, const Vec3& desired) {
        if (a < 0 || b < 0 || c < 0 || d < 0) return;
        Vec3 n = cross(positions[b] - positions[a], positions[c] - positions[a]);
        counts.push_back(4);
        if (dot(n, desired) < 0) { indices.push_back(a); indices.push_back(d); indices.push_back(c); indices.push_back(b); }
        else { indices.push_back(a); indices.push_back(b); indices.push_back(c); indices.push_back(d); }
    };
    for (auto& kv : bricks_) {
        uint64_t k = kv.first;
        int bx = (int)((k >> 42) & 0x1FFFFF) - (1 << 20);
        int by = (int)((k >> 21) & 0x1FFFFF) - (1 << 20);
        int bz = (int)(k & 0x1FFFFF) - (1 << 20);
        for (int lz = 0; lz < kB; ++lz)
            for (int ly = 0; ly < kB; ++ly)
                for (int lx = 0; lx < kB; ++lx) {
                    int sx = bx * kB + lx, sy = by * kB + ly, sz = bz * kB + lz;
                    for (int axis = 0; axis < 3; ++axis) {
                        for (int dir = 0; dir < 2; ++dir) {
                            int ax = (axis == 0), ay = (axis == 1), az = (axis == 2);
                            int px = dir ? sx : sx - ax, py = dir ? sy : sy - ay, pz = dir ? sz : sz - az;
                            if (!present(px, py, pz) && !present(px + ax, py + ay, pz + az)) continue;  // at least one endpoint near the surface
                            bool in0 = inside(px, py, pz);
                            bool in1 = inside(px + ax, py + ay, pz + az);
                            if (in0 == in1) continue;
                            uint64_t ek = key3(px, py, pz) ^ ((uint64_t)(axis + 1) << 60);
                            if (doneEdge.count(ek)) continue;
                            doneEdge[ek] = 1;
                            Vec3 des = axis == 0 ? Vec3(1, 0, 0) : (axis == 1 ? Vec3(0, 1, 0) : Vec3(0, 0, 1));
                            if (!in0) des = -des;  // outward = inside -> outside
                            if (axis == 0)
                                emit(getOrMakeCell(px, py, pz), getOrMakeCell(px, py - 1, pz), getOrMakeCell(px, py - 1, pz - 1), getOrMakeCell(px, py, pz - 1), des);
                            else if (axis == 1)
                                emit(getOrMakeCell(px, py, pz), getOrMakeCell(px - 1, py, pz), getOrMakeCell(px - 1, py, pz - 1), getOrMakeCell(px, py, pz - 1), des);
                            else
                                emit(getOrMakeCell(px, py, pz), getOrMakeCell(px, py - 1, pz), getOrMakeCell(px - 1, py - 1, pz), getOrMakeCell(px - 1, py, pz), des);
                            gEdgesTried++;
                        }
                    }
                }
    }
    std::printf("[sdf] cells=%zu quads=%zu edgesTried=%d skippedCellEdges=%d\n", positions.size(), counts.size(), gEdgesTried, gEdgesTried - (int)counts.size());
    return Mesh::fromPolygons(positions, counts, indices);
}

}  // namespace sculpt
