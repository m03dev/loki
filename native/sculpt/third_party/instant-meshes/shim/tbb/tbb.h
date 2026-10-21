// Minimal Intel TBB API shim for the vendored Instant Meshes sources.
// Sculpting does not ship TBB: these map the handful of TBB calls Instant
// Meshes uses onto std::thread. Reductions combine chunk results in index
// order, so results are deterministic for a given thread count.
#pragma once
#if defined(_MSC_VER)
#include <intrin.h>  // _InterlockedCompareExchange etc. (real TBB pulled this in)
#endif
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdlib>
#include <functional>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>

namespace tbb {

template <typename T>
class blocked_range {
public:
    using const_iterator = T;
    blocked_range() = default;
    blocked_range(T b, T e, size_t grain = 1) : b_(b), e_(e), g_(grain ? grain : 1) {}
    T begin() const { return b_; }
    T end() const { return e_; }
    size_t size() const { return (size_t)(e_ - b_); }
    bool empty() const { return !(b_ < e_); }
    size_t grainsize() const { return g_; }

private:
    T b_{}, e_{};
    size_t g_ = 1;
};

namespace detail {
inline unsigned threads() {
    if (const char* e = std::getenv("SCULPT_IM_THREADS")) { int v = std::atoi(e); if (v > 0) return (unsigned)v; }
    unsigned n = std::thread::hardware_concurrency();
    return n ? n : 4;
}
// Split [b, e) into at most threads()*4 chunks of >= grain items.
template <typename T>
std::vector<blocked_range<T>> chunks(const blocked_range<T>& r) {
    std::vector<blocked_range<T>> out;
    size_t n = r.size();
    if (n == 0) return out;
    size_t parts = std::max<size_t>(1, std::min<size_t>(detail::threads() * 4, n / std::max<size_t>(1, r.grainsize())));
    size_t step = (n + parts - 1) / parts;
    for (size_t i = 0; i < n; i += step)
        out.emplace_back((T)(r.begin() + i), (T)(r.begin() + std::min(n, i + step)), r.grainsize());
    return out;
}
template <typename F>
void run(size_t count, F&& f) {  // f(i) for i in [0, count), on a few threads
    if (count <= 1) { if (count) f(0); return; }
    std::atomic<size_t> next{0};
    unsigned nt = (unsigned)std::min<size_t>(detail::threads(), count);
    std::vector<std::thread> pool;
    for (unsigned t = 1; t < nt; ++t)
        pool.emplace_back([&] { for (size_t i; (i = next.fetch_add(1)) < count;) f(i); });
    for (size_t i; (i = next.fetch_add(1)) < count;) f(i);
    for (auto& th : pool) th.join();
}
}  // namespace detail

template <typename T, typename Body>
void parallel_for(const blocked_range<T>& r, const Body& body) {
    auto cs = detail::chunks(r);
    detail::run(cs.size(), [&](size_t i) { body(cs[i]); });
}

template <typename Index, typename Func>
void parallel_for(Index first, Index last, const Func& f) {
    blocked_range<Index> r(first, last, 1);
    parallel_for(r, [&](const blocked_range<Index>& c) { for (Index i = c.begin(); i < c.end(); ++i) f(i); });
}

template <typename T, typename Value, typename Map, typename Reduce>
Value parallel_reduce(const blocked_range<T>& r, const Value& identity, const Map& map, const Reduce& reduce) {
    auto cs = detail::chunks(r);
    std::vector<Value> part(cs.size(), identity);
    detail::run(cs.size(), [&](size_t i) { part[i] = map(cs[i], identity); });
    Value acc = identity;
    for (auto& p : part) acc = reduce(acc, p);
    return acc;
}

template <typename T, typename Value, typename Map, typename Reduce>
Value parallel_deterministic_reduce(const blocked_range<T>& r, const Value& identity, const Map& map,
                                    const Reduce& reduce) {
    return parallel_reduce(r, identity, map, reduce);
}

template <typename It, typename Comp>
void parallel_sort(It b, It e, const Comp& c) { std::sort(b, e, c); }
template <typename It>
void parallel_sort(It b, It e) { std::sort(b, e); }

class spin_mutex {
public:
    void lock() { while (flag_.test_and_set(std::memory_order_acquire)) std::this_thread::yield(); }
    void unlock() { flag_.clear(std::memory_order_release); }
    class scoped_lock {
    public:
        scoped_lock() = default;
        explicit scoped_lock(spin_mutex& m) : m_(&m) { m.lock(); }
        ~scoped_lock() { release(); }
        void acquire(spin_mutex& m) { release(); m_ = &m; m.lock(); }
        void release() { if (m_) { m_->unlock(); m_ = nullptr; } }

    private:
        spin_mutex* m_ = nullptr;
    };

private:
    std::atomic_flag flag_ = ATOMIC_FLAG_INIT;
};

template <typename T>
class concurrent_vector {
public:
    void reserve(size_t n) { std::lock_guard<std::mutex> l(m_); v_.reserve(n); }
    void push_back(const T& x) { std::lock_guard<std::mutex> l(m_); v_.push_back(x); }
    size_t size() const { return v_.size(); }
    bool empty() const { return v_.empty(); }
    T& operator[](size_t i) { return v_[i]; }
    const T& operator[](size_t i) const { return v_[i]; }
    typename std::vector<T>::iterator begin() { return v_.begin(); }
    typename std::vector<T>::iterator end() { return v_.end(); }
    void clear() { v_.clear(); }

private:
    std::vector<T> v_;
    std::mutex m_;
};

template <typename T, typename Comp = std::less<T>>
class concurrent_priority_queue {
public:
    void push(const T& x) { std::lock_guard<std::mutex> l(m_); q_.push(x); }
    bool try_pop(T& out) {
        std::lock_guard<std::mutex> l(m_);
        if (q_.empty()) return false;
        out = q_.top();
        q_.pop();
        return true;
    }
    bool empty() const { return q_.empty(); }
    size_t size() const { return q_.size(); }

private:
    std::priority_queue<T, std::vector<T>, Comp> q_;
    std::mutex m_;
};

class task_scheduler_init {
public:
    static const int automatic = -1;
    explicit task_scheduler_init(int = automatic) {}
};

}  // namespace tbb
