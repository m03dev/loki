#include "sculpt/bvh.h"
#include "sculpt/parallel.h"
#include <algorithm>
#include <functional>
#include <thread>

namespace sculpt {

static constexpr int kLeafSize = 8;

AABB BVH::triBounds(const Mesh& m, int t) const {
    AABB b;
    const Tri& f = m.tris[t];
    if (f[0] < 0) return b;  // tombstoned triangle -> empty box
    for (int k = 0; k < 3; ++k) b.expand(m.positions[f[k]]);
    return b;
}

void BVH::build(const Mesh& m) {
    int n = (int)m.tris.size();
    nodes_.clear();
    order_.resize(n);
    triBox_.resize(n);
    std::vector<Vec3> centroids(n);
    parallelFor(n, [&](int t) {
        order_[t] = t;
        triBox_[t] = triBounds(m, t);
        centroids[t] = triBox_[t].valid() ? triBox_[t].center() : Vec3{0, 0, 0};
    }, 16384);
    builtCount_ = (size_t)n;
    if (n) {
        if (n < 200000) {
            nodes_.reserve(2 * n / kLeafSize + 2);
            buildRec(0, n, centroids);
        } else {
            std::vector<Node> built;
            buildSub(0, n, centroids, built, 0);  // millions of triangles: parallel top levels
            nodes_.swap(built);
        }
    }
    parent_.assign(nodes_.size(), -1);
    triLeaf_.assign(n, -1);
    for (int i = 0; i < (int)nodes_.size(); ++i) {
        const Node& nd = nodes_[i];
        if (nd.left >= 0) { parent_[nd.left] = i; parent_[nd.right] = i; }
        else for (int k = nd.first; k < nd.first + nd.count; ++k) triLeaf_[order_[k]] = i;
    }
    nodeStamp_.assign(nodes_.size(), 0);
    nodeStampId_ = 0;
    stamp_.assign(m.positions.size(), 0);
    stampId_ = 0;
}

int BVH::buildRec(int first, int count, std::vector<Vec3>& centroids) {
    int idx = (int)nodes_.size();
    nodes_.push_back({});
    AABB box, cbox;
    for (int i = first; i < first + count; ++i) {
        if (triBox_[order_[i]].valid()) box.expand(triBox_[order_[i]]);
        cbox.expand(centroids[order_[i]]);
    }
    nodes_[idx].box = box;
    if (count <= kLeafSize) {
        nodes_[idx].first = first;
        nodes_[idx].count = count;
        return idx;
    }
    // Median split on the longest centroid axis: O(n log n) build, good enough
    // for sculpt meshes (uniform triangle sizes) and much faster to build than SAH.
    Vec3 e = cbox.extent();
    int axis = (e.x > e.y && e.x > e.z) ? 0 : (e.y > e.z ? 1 : 2);
    int mid = first + count / 2;
    std::nth_element(order_.begin() + first, order_.begin() + mid, order_.begin() + first + count,
                     [&](int a, int b) { return centroids[a][axis] < centroids[b][axis]; });
    int l = buildRec(first, mid - first, centroids);
    int r = buildRec(mid, first + count - mid, centroids);
    nodes_[idx].left = l;
    nodes_[idx].right = r;
    return idx;
}

// Recursive median-split build into `out` (indices local to out). Reads
// triBox, partitions order[first, first+count) in place: two calls on
// disjoint ranges can run concurrently.
static void buildInto(std::vector<BVH::NodeT>& out, std::vector<int>& order, const std::vector<AABB>& triBox,
                      const std::vector<Vec3>& centroids, int first, int count) {
    int idx = (int)out.size();
    out.push_back({});
    AABB box, cbox;
    for (int i = first; i < first + count; ++i) {
        if (triBox[order[i]].valid()) box.expand(triBox[order[i]]);
        cbox.expand(centroids[order[i]]);
    }
    out[idx].box = box;
    if (count <= kLeafSize) {
        out[idx].first = first;
        out[idx].count = count;
        return;
    }
    Vec3 e = cbox.extent();
    int axis = (e.x > e.y && e.x > e.z) ? 0 : (e.y > e.z ? 1 : 2);
    int mid = first + count / 2;
    std::nth_element(order.begin() + first, order.begin() + mid, order.begin() + first + count,
                     [&](int a, int b) { return centroids[a][axis] < centroids[b][axis]; });
    int l = (int)out.size();
    buildInto(out, order, triBox, centroids, first, mid - first);
    int r = (int)out.size();
    buildInto(out, order, triBox, centroids, mid, first + count - mid);
    out[idx].left = l;
    out[idx].right = r;
}

void BVH::buildSub(int first, int count, std::vector<Vec3>& centroids, std::vector<Node>& out, int depth) {
    // Same median split as buildRec. The two halves are disjoint ranges of
    // order_, so they partition concurrently; node arrays are merged in
    // pre-order afterwards (node, left subtree, right subtree).
    const int kParDepth = 4;  // up to 16 concurrent subtrees
    out.clear();
    if (depth >= kParDepth || count < 65536) {
        out.reserve(2 * count / kLeafSize + 2);
        buildInto(out, order_, triBox_, centroids, first, count);
        return;
    }
    AABB box, cbox;
    for (int i = first; i < first + count; ++i) {
        if (triBox_[order_[i]].valid()) box.expand(triBox_[order_[i]]);
        cbox.expand(centroids[order_[i]]);
    }
    Vec3 e = cbox.extent();
    int axis = (e.x > e.y && e.x > e.z) ? 0 : (e.y > e.z ? 1 : 2);
    int mid = first + count / 2;
    std::nth_element(order_.begin() + first, order_.begin() + mid, order_.begin() + first + count,
                     [&](int a, int b) { return centroids[a][axis] < centroids[b][axis]; });
    std::vector<Node> L, R;
    std::thread th([&] { buildSub(first, mid - first, centroids, L, depth + 1); });
    buildSub(mid, first + count - mid, centroids, R, depth + 1);
    th.join();
    out.reserve(1 + L.size() + R.size());
    Node root;
    root.box = box;
    root.left = 1;
    root.right = 1 + (int)L.size();
    out.push_back(root);
    for (Node nd : L) {
        if (nd.left >= 0) { nd.left += 1; nd.right += 1; }
        out.push_back(nd);
    }
    int off = 1 + (int)L.size();
    for (Node nd : R) {
        if (nd.left >= 0) { nd.left += off; nd.right += off; }
        out.push_back(nd);
    }
}

void BVH::refit(const Mesh& m) {
    size_t extras = m.tris.size() > builtCount_ ? m.tris.size() - builtCount_ : 0;
    if (m.tris.size() < builtCount_ || nodes_.empty() || extras > std::max<size_t>(4096, builtCount_ / 10)) {
        build(m);
        return;
    }
    triBox_.resize(m.tris.size());
    for (size_t t = 0; t < m.tris.size(); ++t) triBox_[t] = triBounds(m, (int)t);
    // Children always have larger indices than parents (pre-order), so a reverse
    // sweep refits bottom-up in a single pass.
    for (int i = (int)nodes_.size() - 1; i >= 0; --i) {
        Node& nd = nodes_[i];
        AABB b;
        if (nd.left < 0) {
            for (int k = nd.first; k < nd.first + nd.count; ++k)
                if (triBox_[order_[k]].valid()) b.expand(triBox_[order_[k]]);
        } else {
            b = nodes_[nd.left].box;
            b.expand(nodes_[nd.right].box);
        }
        nd.box = b;
    }
    if (stamp_.size() != m.positions.size()) stamp_.assign(m.positions.size(), 0);
}

void BVH::refitTris(const Mesh& m, const std::vector<int>& tris) {
    std::vector<int>& cache = dirtyNodes_;
    cache.clear();
    refitTrisCached(m, tris, cache);
}

void BVH::refitTrisCached(const Mesh& m, const std::vector<int>& tris, std::vector<int>& nodes) {
    if (nodes_.empty() || m.tris.size() < builtCount_) { build(m); nodes.clear(); return; }
    size_t extras = m.tris.size() - builtCount_;
    if (extras > std::max<size_t>(4096, builtCount_ / 10)) { build(m); nodes.clear(); return; }
    if (tris.size() * 4 > builtCount_) { refit(m); return; }  // big change: full sweep is cheaper
    if (triBox_.size() < m.tris.size()) {
        size_t old = triBox_.size();
        triBox_.resize(m.tris.size());
        for (size_t t = old; t < m.tris.size(); ++t) triBox_[t] = triBounds(m, (int)t);
    }
    // triangle boxes: independent (callers pass unique triangles)
    const int nt = (int)m.tris.size();
    parallelFor((int)tris.size(), [&](int i) {
        int t = tris[i];
        if (t >= 0 && t < nt) triBox_[t] = triBounds(m, t);
    }, 4096);
    if (nodes.empty()) {
        if (++nodeStampId_ == 0) { std::fill(nodeStamp_.begin(), nodeStamp_.end(), 0); nodeStampId_ = 1; }
        for (int t : tris) {
            if (t < 0 || t >= nt || (size_t)t >= builtCount_) continue;  // extras: scanned linearly, no node
            for (int nd = triLeaf_[t]; nd >= 0 && nodeStamp_[nd] != nodeStampId_; nd = parent_[nd]) {
                nodeStamp_[nd] = nodeStampId_;
                nodes.push_back(nd);
            }
        }
        // Bottom-up order without a sort (the sort was ~8% of a dab at 262k
        // verts): count each node's dirty children, emit the nodes with none
        // (exactly the leaves: every interior node was reached from below),
        // then a parent as soon as its last dirty child is out. Leaves come
        // first, interior nodes follow in a valid bottom-up order, and the
        // counters are all back at zero afterwards.
        if (nodePending_.size() < nodes_.size()) nodePending_.assign(nodes_.size(), 0);
        for (int nd : nodes) { int p = parent_[nd]; if (p >= 0) ++nodePending_[p]; }
        std::vector<int>& q = orderScratch_;
        q.clear();
        for (int nd : nodes) if (nodePending_[nd] == 0) q.push_back(nd);
        for (size_t i = 0; i < q.size(); ++i) {
            int p = parent_[q[i]];
            if (p >= 0 && --nodePending_[p] == 0) q.push_back(p);
        }
        nodes.swap(q);
    }
    // leaves first (independent, the bulk of the work), then interior nodes in order
    parallelFor((int)nodes.size(), [&](int i) {
        Node& nd = nodes_[nodes[i]];
        if (nd.left >= 0) return;
        AABB b;
        for (int k = nd.first; k < nd.first + nd.count; ++k)
            if (triBox_[order_[k]].valid()) b.expand(triBox_[order_[k]]);
        nd.box = b;
    }, 2048);
    for (int i : nodes) {
        Node& nd = nodes_[i];
        if (nd.left < 0) continue;
        AABB b = nodes_[nd.left].box;
        b.expand(nodes_[nd.right].box);
        nd.box = b;
    }
    if (stamp_.size() != m.positions.size()) stamp_.assign(m.positions.size(), 0);
}

template <class BoxTest, class Emit>
void BVH::traverse(BoxTest boxTest, Emit emit) const {
    for (size_t t = builtCount_; t < triBox_.size(); ++t)
        if (triBox_[t].valid() && boxTest(triBox_[t])) emit((int)t);
    if (nodes_.empty()) return;
    int stack[128];
    int sp = 0;
    stack[sp++] = 0;
    while (sp) {
        const Node& nd = nodes_[stack[--sp]];
        if (!nd.box.valid() || !boxTest(nd.box)) continue;
        if (nd.left < 0) {
            for (int k = nd.first; k < nd.first + nd.count; ++k) emit(order_[k]);
        } else {
            stack[sp++] = nd.left;
            stack[sp++] = nd.right;
        }
    }
}

// Slab test.
static bool rayBox(const Ray& r, const AABB& b, float tmax) {
    float t0 = 0, t1 = tmax;
    for (int i = 0; i < 3; ++i) {
        float inv = 1.0f / (std::fabs(r.dir[i]) > 1e-12f ? r.dir[i] : 1e-12f);
        float tn = (b.lo[i] - r.origin[i]) * inv, tf = (b.hi[i] - r.origin[i]) * inv;
        if (tn > tf) std::swap(tn, tf);
        t0 = std::max(t0, tn);
        t1 = std::min(t1, tf);
        if (t0 > t1) return false;
    }
    return true;
}

Hit BVH::raycast(const Mesh& m, const Ray& r, bool backfaces, float maxT) const {
    Hit best;
    best.t = maxT;
    // Möller–Trumbore. Traversal is not ordered front-to-back; the shrinking
    // best.t still prunes most nodes through the slab test.
    auto testTri = [&](int t) {
            const Tri& f = m.tris[t];
            if (f[0] < 0) return;
            const Vec3 &p0 = m.positions[f[0]], &p1 = m.positions[f[1]], &p2 = m.positions[f[2]];
            Vec3 e1 = p1 - p0, e2 = p2 - p0;
            Vec3 pv = cross(r.dir, e2);
            float det = dot(e1, pv);
            if (backfaces ? std::fabs(det) < 1e-12f : det < 1e-12f) return;
            float inv = 1.0f / det;
            Vec3 tv = r.origin - p0;
            float u = dot(tv, pv) * inv;
            if (u < 0 || u > 1) return;
            Vec3 qv = cross(tv, e1);
            float v = dot(r.dir, qv) * inv;
            if (v < 0 || u + v > 1) return;
            float tt = dot(e2, qv) * inv;
            if (tt > 0 && tt < best.t) {
                best.hit = true;
                best.t = tt;
                best.tri = t;
                best.u = u;
                best.v = v;
            }
    };
    for (size_t t = builtCount_; t < m.tris.size() && t < triBox_.size(); ++t) testTri((int)t);
    if (!nodes_.empty()) {
        int stack[128];
        int sp = 0;
        stack[sp++] = 0;
        while (sp) {
            const Node& nd = nodes_[stack[--sp]];
            if (!nd.box.valid() || !rayBox(r, nd.box, best.t)) continue;
            if (nd.left >= 0) {
                stack[sp++] = nd.left;
                stack[sp++] = nd.right;
                continue;
            }
            for (int k = nd.first; k < nd.first + nd.count; ++k) testTri(order_[k]);
        }
    }
    if (!best.hit) best.t = 1e30f;
    if (best.hit) {
        const Tri& f = m.tris[best.tri];
        best.point = r.origin + r.dir * best.t;
        float w = 1 - best.u - best.v;
        best.normal = normalize(m.normals[f[0]] * w + m.normals[f[1]] * best.u + m.normals[f[2]] * best.v);
    }
    return best;
}

void BVH::queryVerts(const Mesh& m, const Vec3& c, float radius, std::vector<int>& out) const {
    out.clear();
    if (stamp_.size() != m.positions.size()) stamp_.assign(m.positions.size(), 0);
    if (++stampId_ == 0) { std::fill(stamp_.begin(), stamp_.end(), 0); stampId_ = 1; }
    float r2 = radius * radius;
    traverse([&](const AABB& b) { return b.dist2(c) <= r2; },
             [&](int t) {
                 const Tri& f = m.tris[t];
                 if (f[0] < 0) return;
                 for (int k = 0; k < 3; ++k) {
                     int v = f[k];
                     if (stamp_[v] == stampId_) continue;
                     stamp_[v] = stampId_;
                     if (length2(m.positions[v] - c) <= r2) out.push_back(v);
                 }
             });
}

void BVH::queryVertsCylinder(const Mesh& m, const Ray& r, float radius, std::vector<int>& out) const {
    out.clear();
    if (stamp_.size() != m.positions.size()) stamp_.assign(m.positions.size(), 0);
    if (++stampId_ == 0) { std::fill(stamp_.begin(), stamp_.end(), 0); stampId_ = 1; }
    float r2 = radius * radius;
    auto lineDist2 = [&](const Vec3& p) {
        Vec3 d = p - r.origin;
        return length2(d - r.dir * dot(d, r.dir));
    };
    // Conservative box test: distance from box center to the line minus the
    // half-diagonal.
    traverse(
        [&](const AABB& b) {
            float hd = length(b.extent()) * 0.5f;
            float d = std::sqrt(lineDist2(b.center()));
            return d - hd <= radius;
        },
        [&](int t) {
            const Tri& f = m.tris[t];
            if (f[0] < 0) return;
            for (int k = 0; k < 3; ++k) {
                int v = f[k];
                if (stamp_[v] == stampId_) continue;
                stamp_[v] = stampId_;
                if (lineDist2(m.positions[v]) <= r2) out.push_back(v);
            }
        });
}

void BVH::queryTris(const Vec3& c, float radius, std::vector<int>& out) const {
    out.clear();
    float r2 = radius * radius;
    traverse([&](const AABB& b) { return b.dist2(c) <= r2; },
             [&](int t) {
                 if (triBox_[t].valid() && triBox_[t].dist2(c) <= r2) out.push_back(t);
             });
}

}  // namespace sculpt
