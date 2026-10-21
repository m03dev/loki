#include "sculpt/paged_store.h"
#include "sculpt/cluster_lod.h"
#include "meshoptimizer.h"

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>

namespace sculpt {

namespace {

constexpr size_t kPageTarget = 256u * 1024u;  // raw bytes per page
constexpr size_t kStride = 12;                // per vertex: u16x3 pos + u16x2 oct normal + 2 pad
constexpr uint32_t kMagic = 0x3153504Bu;      // 'KPS1'

void octEncode(const Vec3& n0, float& u, float& v) {
    float l = std::fabs(n0.x) + std::fabs(n0.y) + std::fabs(n0.z);
    Vec3 n = l > 1e-20f ? n0 / l : Vec3{0, 0, 1};
    if (n.z >= 0) { u = n.x; v = n.y; }
    else { u = (1 - std::fabs(n.y)) * (n.x >= 0 ? 1.0f : -1.0f); v = (1 - std::fabs(n.x)) * (n.y >= 0 ? 1.0f : -1.0f); }
}
Vec3 octDecode(float u, float v) {
    Vec3 n{u, v, 1 - std::fabs(u) - std::fabs(v)};
    if (n.z < 0) { n.x = (1 - std::fabs(v)) * (u >= 0 ? 1.0f : -1.0f); n.y = (1 - std::fabs(u)) * (v >= 0 ? 1.0f : -1.0f); }
    return normalize(n);
}
uint16_t quant(float t) {
    float c = t < 0 ? 0 : (t > 1 ? 1 : t);
    return (uint16_t)(c * 65535.0f + 0.5f);
}

template <class T>
void put(std::vector<unsigned char>& b, const T& v) { const unsigned char* p = (const unsigned char*)&v; b.insert(b.end(), p, p + sizeof(T)); }

}  // namespace

PagedStore::~PagedStore() = default;

bool PagedStore::readAt(uint64_t off, size_t n, unsigned char* dst) const {
    if (!file_.is_open()) return false;
    file_.clear();
    file_.seekg((std::streamoff)off, std::ios::beg);
    if (!file_) return false;
    file_.read((char*)dst, (std::streamsize)n);
    return (size_t)file_.gcount() == n;
}

bool PagedStore::build(const Mesh& m, const std::string& path, int maxTriangles) {
    clusters_.clear(); groups_.clear(); pages_.clear();
    path_ = path;
    ClusterLOD lod;
    lod.build(m, maxTriangles);
    sourceTris_ = lod.sourceTriangles();
    levels_ = lod.levels();

    const auto& lc = lod.clusters();
    const auto& lg = lod.groups();
    const auto& lidx = lod.indices();
    groups_.reserve(lg.size());
    for (const auto& g : lg) {
        StoredGroup s; s.depth = g.depth; s.center = g.center; s.radius = g.radius; s.error = g.error;
        groups_.push_back(s);
    }

    const size_t nv = m.positions.size();
    std::vector<int> stamp(nv, -1), localOf(nv, 0);
    // unique vertex count per cluster (same traversal order as the payload pass)
    std::vector<uint32_t> vcount(lc.size(), 0);
    for (size_t i = 0; i < lc.size(); ++i) {
        const auto& cl = lc[i];
        int cnt = 0;
        for (uint32_t k = 0; k < cl.indexCount; ++k) {
            uint32_t g = lidx[cl.indexOffset + k];
            if (stamp[g] != (int)i) { stamp[g] = (int)i; ++cnt; }
        }
        vcount[i] = (uint32_t)cnt;
    }

    // --- page grouping: accumulate clusters until the raw payload target -----
    std::vector<uint32_t> pageOf(lc.size(), 0);
    size_t raw = 0;
    uint32_t page = 0;
    for (size_t i = 0; i < lc.size(); ++i) {
        size_t cb = (size_t)vcount[i] * kStride + (size_t)lc[i].indexCount * 4;
        if (raw + cb > kPageTarget && raw > 0) { ++page; raw = 0; }
        pageOf[i] = page;
        raw += cb;
    }
    const uint32_t pageCount = page + 1;
    pages_.assign(pageCount, PageInfo{});
    pageFirstCluster_.assign(pageCount + 1, 0);
    pageClusterCount_.assign(pageCount, 0);
    for (size_t i = 0; i < lc.size(); ++i) ++pageClusterCount_[pageOf[i]];
    { uint32_t acc = 0; for (uint32_t p = 0; p < pageCount; ++p) { pageFirstCluster_[p] = acc; acc += pageClusterCount_[p]; } pageFirstCluster_[pageCount] = acc; }

    clusters_.resize(lc.size());
    for (size_t i = 0; i < lc.size(); ++i) {
        StoredCluster& s = clusters_[i];
        s.center = lc[i].center; s.radius = lc[i].radius; s.page = pageOf[i];
        s.vertexCount = vcount[i]; s.indexCount = lc[i].indexCount;
        s.group = lc[i].group; s.refined = lc[i].refined;
    }

    // --- write header + directory (placeholder page offsets), then payloads ---
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) return false;
    uint64_t cursor = 0;
    auto wraw = [&](const void* p, size_t n) { out.write((const char*)p, (std::streamsize)n); cursor += n; };
    const uint32_t version = 1;
    wraw(&kMagic, 4); wraw(&version, 4);
    uint64_t srcT = sourceTris_; wraw(&srcT, 8);
    int32_t lv = levels_; wraw(&lv, 4);
    uint32_t pc = pageCount, cc = (uint32_t)clusters_.size(), gc = (uint32_t)groups_.size();
    wraw(&pc, 4); wraw(&cc, 4); wraw(&gc, 4);
    const uint64_t pageInfoOff = cursor;
    for (uint32_t p = 0; p < pageCount; ++p) { uint64_t o = 0; uint32_t b = 0, r = 0; wraw(&o, 8); wraw(&b, 4); wraw(&r, 4); }
    for (auto& s : clusters_) {
        wraw(&s.center.x, 4); wraw(&s.center.y, 4); wraw(&s.center.z, 4); wraw(&s.radius, 4);
        wraw(&s.page, 4); wraw(&s.vertexCount, 4); wraw(&s.indexCount, 4);
        wraw(&s.group, 4); wraw(&s.refined, 4);
    }
    for (auto& g : groups_) {
        wraw(&g.depth, 4);
        wraw(&g.center.x, 4); wraw(&g.center.y, 4); wraw(&g.center.z, 4);
        wraw(&g.radius, 4); wraw(&g.error, 4);
    }

    // --- payloads -------------------------------------------------------------
    std::vector<unsigned char> encV, encI, encG, pageBuf;
    for (uint32_t p = 0; p < pageCount; ++p) {
        uint32_t first = pageFirstCluster_[p], cnt = pageClusterCount_[p];
        uint32_t totalV = 0, totalI = 0;
        std::vector<uint32_t> metaC(cnt), metaV(cnt), metaI(cnt);
        std::vector<std::array<float, 6>> bounds(cnt);
        std::vector<unsigned char> vertsBlob;
        std::vector<uint32_t> indexBlob;
        std::vector<uint32_t> idsBlob;
        std::fill(stamp.begin(), stamp.end(), -1);  // fresh traversal for this page
        for (uint32_t j = 0; j < cnt; ++j) {
            const size_t ci = first + j;
            const auto& cl = lc[ci];
            Vec3 lo{1e30f, 1e30f, 1e30f}, hi{-1e30f, -1e30f, -1e30f};
            std::vector<uint32_t> globals;
            globals.reserve(vcount[ci]);
            for (uint32_t k = 0; k < cl.indexCount; ++k) {
                uint32_t g = lidx[cl.indexOffset + k];
                if (stamp[g] != (int)ci) {
                    stamp[g] = (int)ci; localOf[g] = (int)globals.size(); globals.push_back(g);
                    const Vec3& pt = m.positions[g]; lo = vmin(lo, pt); hi = vmax(hi, pt);
                }
            }
            const uint32_t V = (uint32_t)globals.size();
            Vec3 ext = hi - lo;
            std::vector<unsigned char> vb((size_t)V * kStride, 0);
            for (uint32_t i2 = 0; i2 < V; ++i2) {
                const uint32_t g = globals[i2];
                const Vec3& pt = m.positions[g];
                Vec3 nd = (g < m.normals.size()) ? m.normals[g] : Vec3{0, 1, 0};
                float u, v; octEncode(nd, u, v);
                uint16_t q[5];
                q[0] = quant(ext.x > 1e-20f ? (pt.x - lo.x) / ext.x : 0);
                q[1] = quant(ext.y > 1e-20f ? (pt.y - lo.y) / ext.y : 0);
                q[2] = quant(ext.z > 1e-20f ? (pt.z - lo.z) / ext.z : 0);
                q[3] = quant(u * 0.5f + 0.5f);
                q[4] = quant(v * 0.5f + 0.5f);
                std::memcpy(&vb[(size_t)i2 * kStride], q, 10);
            }
            std::vector<uint32_t> ib(cl.indexCount);
            for (uint32_t k = 0; k < cl.indexCount; ++k) ib[k] = (uint32_t)localOf[lidx[cl.indexOffset + k]];
            vertsBlob.insert(vertsBlob.end(), vb.begin(), vb.end());
            indexBlob.insert(indexBlob.end(), ib.begin(), ib.end());
            for (uint32_t i2 = 0; i2 < V; ++i2) idsBlob.push_back(globals[i2]);
            metaC[j] = (uint32_t)ci; metaV[j] = V; metaI[j] = cl.indexCount;
            bounds[j] = {lo.x, lo.y, lo.z, hi.x, hi.y, hi.z};
            totalV += V; totalI += cl.indexCount;
        }
        encV.resize(meshopt_encodeVertexBufferBound(totalV, kStride));
        encV.resize(meshopt_encodeVertexBuffer(encV.data(), encV.size(), vertsBlob.data(), totalV, kStride));
        encI.resize(meshopt_encodeIndexBufferBound(totalI, totalV));
        encI.resize(meshopt_encodeIndexBuffer(encI.data(), encI.size(), indexBlob.data(), totalI));
        encG.resize(meshopt_encodeVertexBufferBound(totalV, 4));
        encG.resize(meshopt_encodeVertexBuffer(encG.data(), encG.size(), idsBlob.data(), totalV, 4));

        pageBuf.clear();
        uint32_t cntU = cnt, tvU = totalV, tiU = totalI, evU = (uint32_t)encV.size(), eiU = (uint32_t)encI.size(), giU = (uint32_t)encG.size();
        put(pageBuf, cntU); put(pageBuf, tvU); put(pageBuf, tiU); put(pageBuf, evU); put(pageBuf, eiU); put(pageBuf, giU);
        for (uint32_t j = 0; j < cnt; ++j) {
            put(pageBuf, metaC[j]); put(pageBuf, metaV[j]); put(pageBuf, metaI[j]);
            for (float f : bounds[j]) put(pageBuf, f);
        }
        pageBuf.insert(pageBuf.end(), encV.begin(), encV.end());
        pageBuf.insert(pageBuf.end(), encI.begin(), encI.end());
        pageBuf.insert(pageBuf.end(), encG.begin(), encG.end());

        pages_[p].offset = cursor;
        pages_[p].bytes = (uint32_t)pageBuf.size();
        pages_[p].rawBytes = (uint32_t)(totalV * 28 + totalI * 4);
        wraw(pageBuf.data(), pageBuf.size());
    }
    diskBytes_ = cursor;
    rawBytes_ = 0;
    for (auto& pi : pages_) rawBytes_ += pi.rawBytes;

    out.seekp((std::streamoff)pageInfoOff, std::ios::beg);
    for (auto& pi : pages_) { uint64_t o = pi.offset; uint32_t b = pi.bytes, r = pi.rawBytes; out.write((const char*)&o, 8); out.write((const char*)&b, 4); out.write((const char*)&r, 4); }
    out.close();
    file_.open(path, std::ios::binary);
    return true;
}

bool PagedStore::open(const std::string& path) {
    clusters_.clear(); groups_.clear(); pages_.clear(); path_ = path;
    file_.open(path, std::ios::binary);
    if (!file_) return false;
    unsigned char buf[64];
    uint64_t off = 0;
    auto rd = [&](void* p, size_t n) { bool ok = readAt(off, n, (unsigned char*)p); off += n; return ok; };
    uint32_t magic = 0, version = 0, pc = 0, cc = 0, gc = 0; uint64_t srcT = 0; int32_t lv = 0;
    if (!rd(&magic, 4) || magic != kMagic) return false;
    rd(&version, 4); rd(&srcT, 8); rd(&lv, 4); rd(&pc, 4); rd(&cc, 4); rd(&gc, 4);
    sourceTris_ = srcT; levels_ = lv;
    pages_.resize(pc);
    for (uint32_t p = 0; p < pc; ++p) { rd(&pages_[p].offset, 8); rd(&pages_[p].bytes, 4); rd(&pages_[p].rawBytes, 4); }
    clusters_.resize(cc);
    for (auto& s : clusters_) {
        rd(&s.center.x, 4); rd(&s.center.y, 4); rd(&s.center.z, 4); rd(&s.radius, 4);
        rd(&s.page, 4); rd(&s.vertexCount, 4); rd(&s.indexCount, 4); rd(&s.group, 4); rd(&s.refined, 4);
    }
    groups_.resize(gc);
    for (auto& g : groups_) { rd(&g.depth, 4); rd(&g.center.x, 4); rd(&g.center.y, 4); rd(&g.center.z, 4); rd(&g.radius, 4); rd(&g.error, 4); }
    pageFirstCluster_.assign(pc + 1, 0); pageClusterCount_.assign(pc, 0);
    for (auto& s : clusters_) ++pageClusterCount_[s.page];
    { uint32_t acc = 0; for (uint32_t p = 0; p < pc; ++p) { pageFirstCluster_[p] = acc; acc += pageClusterCount_[p]; } pageFirstCluster_[pc] = acc; }
    diskBytes_ = 0;
    for (auto& pi : pages_) { diskBytes_ += pi.bytes; rawBytes_ += pi.rawBytes; }
    return true;
}

bool PagedStore::decodePage(uint32_t page, std::vector<ClusterMesh>& out, const EditOverlay* overlay) const {
    if (page >= pages_.size()) return false;
    const PageInfo& pi = pages_[page];
    std::vector<unsigned char> buf(pi.bytes);
    if (!readAt(pi.offset, pi.bytes, buf.data())) return false;
    size_t pos = 0;
    auto get = [&](void* p, size_t n) { if (pos + n > buf.size()) return false; std::memcpy(p, buf.data() + pos, n); pos += n; return true; };
    uint32_t cnt = 0, totalV = 0, totalI = 0, evU = 0, eiU = 0, giU = 0;
    if (!get(&cnt, 4) || !get(&totalV, 4) || !get(&totalI, 4) || !get(&evU, 4) || !get(&eiU, 4) || !get(&giU, 4)) return false;
    std::vector<uint32_t> cIdx(cnt), vCount(cnt), iCount(cnt);
    std::vector<std::array<float, 6>> bounds(cnt);
    for (uint32_t i = 0; i < cnt; ++i) {
        if (!get(&cIdx[i], 4) || !get(&vCount[i], 4) || !get(&iCount[i], 4)) return false;
        for (int f = 0; f < 6; ++f) get(&bounds[i][f], 4);
    }
    std::vector<unsigned char> verts((size_t)totalV * kStride);
    if (meshopt_decodeVertexBuffer(verts.data(), totalV, kStride, buf.data() + pos, evU) != 0) return false;
    pos += evU;
    std::vector<uint32_t> idx(totalI);
    if (meshopt_decodeIndexBuffer(idx.data(), totalI, 4, buf.data() + pos, eiU) != 0) return false;
    pos += eiU;
    std::vector<uint32_t> ids(totalV);
    if (meshopt_decodeVertexBuffer(ids.data(), totalV, 4, buf.data() + pos, giU) != 0) return false;

    out.resize(cnt);
    uint32_t vbase = 0, ibase = 0;
    for (uint32_t i = 0; i < cnt; ++i) {
        const uint32_t V = vCount[i];
        Vec3 lo{bounds[i][0], bounds[i][1], bounds[i][2]}, hi{bounds[i][3], bounds[i][4], bounds[i][5]};
        Vec3 ext = hi - lo;
        ClusterMesh& cm = out[i];
        cm.positions.resize(V); cm.normals.resize(V); cm.globalIds.resize(V); cm.indices.resize(iCount[i]);
        for (uint32_t k = 0; k < V; ++k) {
            const unsigned char* p = &verts[(size_t)(vbase + k) * kStride];
            uint16_t q[5]; std::memcpy(q, p, 10);
            cm.positions[k] = {lo.x + q[0] / 65535.0f * ext.x, lo.y + q[1] / 65535.0f * ext.y, lo.z + q[2] / 65535.0f * ext.z};
            cm.normals[k] = octDecode(q[3] / 65535.0f * 2 - 1, q[4] / 65535.0f * 2 - 1);
            cm.globalIds[k] = ids[vbase + k];
            if (overlay && overlay->has(ids[vbase + k])) cm.positions[k] += overlay->get(ids[vbase + k]);
        }
        for (uint32_t k = 0; k < iCount[i]; ++k) cm.indices[k] = idx[ibase + k];
        vbase += V; ibase += iCount[i];
    }
    return true;
}

// ------------------------------------------------------------------ LOD cut

static bool visibleCluster(const LodView& v, const Vec3& c, float r) {
    if (!v.cull) return true;
    for (const Plane& p : v.planes)
        if (dot(p.n, c) + p.d < -r) return false;
    return true;
}

void PagedStore::select(const LodView& v, std::vector<uint32_t>& out) const {
    out.clear();
    const float thr = v.pixelError;
    std::vector<float> ge(groups_.size());
    for (size_t i = 0; i < groups_.size(); ++i) {
        const StoredGroup& g = groups_[i];
        if (g.error >= FLT_MAX * 0.5f) { ge[i] = FLT_MAX; continue; }
        if (v.projScale <= 0) ge[i] = g.error / std::max(1e-12f, v.orthoHeight) * v.viewportHeight;
        else {
            float d = std::max(length(g.center - v.eye) - g.radius, v.znear);
            ge[i] = g.error / d * (v.projScale * 0.5f) * v.viewportHeight;
        }
    }
    for (uint32_t i = 0; i < clusters_.size(); ++i) {
        const StoredCluster& c = clusters_[i];
        if (c.group >= 0 && ge[c.group] <= thr) continue;        // coarser version is good enough
        if (c.refined >= 0 && ge[c.refined] > thr) continue;     // a finer version is needed
        if (visibleCluster(v, c.center, c.radius)) out.push_back(i);
    }
}

void PagedStore::touch(const std::vector<std::pair<Vec3, float>>& spheres, float delta) {
    if (spheres.empty() || delta <= 0) return;
    for (auto& c : clusters_) {
        for (auto& sp : spheres) {
            float d = length(c.center - sp.first);
            if (d <= c.radius + sp.second) { c.radius = std::max(c.radius, d + sp.second + delta); break; }
        }
    }
    for (auto& g : groups_) {
        if (g.error >= FLT_MAX * 0.5f) continue;
        for (auto& sp : spheres) {
            if (length(g.center - sp.first) <= g.radius + sp.second) {
                if (g.error < delta) g.error = delta;
                break;
            }
        }
    }
}

// ---------------------------------------------------------------- ResidentSet

const std::vector<PagedStore::ClusterMesh>* ResidentSet::acquire(uint32_t page) {
    ++clock_;
    auto it = resident_.find(page);
    if (it != resident_.end()) { it->second.stamp = clock_; ++hits_; return &it->second.data; }
    ++misses_;
    std::vector<PagedStore::ClusterMesh> data;
    if (!store_.decodePage(page, data)) return nullptr;
    size_t bytes = 0;
    for (auto& cm : data) bytes += cm.positions.size() * (sizeof(Vec3) * 2 + sizeof(uint32_t));
    bytesRead_ += bytes;
    while (residentBytes_ + bytes > budget_ && !resident_.empty()) evictOne();
    Entry e; e.stamp = clock_; e.bytes = bytes; e.data = std::move(data);
    auto res = resident_.emplace(page, std::move(e));
    residentBytes_ += bytes;
    peakBytes_ = std::max(peakBytes_, residentBytes_);
    return &res.first->second.data;
}

void ResidentSet::evictOne() {
    auto victim = resident_.end();
    for (auto it = resident_.begin(); it != resident_.end(); ++it)
        if (victim == resident_.end() || it->second.stamp < victim->second.stamp) victim = it;
    if (victim == resident_.end()) return;
    residentBytes_ -= victim->second.bytes;
    resident_.erase(victim);
    ++evictions_;
}

void ResidentSet::clear() { resident_.clear(); residentBytes_ = 0; }

}  // namespace sculpt
