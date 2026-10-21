// Single-threaded build (WebAssembly without shared memory): the C++ library
// has no std::thread / std::mutex. The engine only uses threads for speed-ups
// (worker pools, a parallel BVH build), so a "thread" here runs its function
// right away on the caller and the locks are no-ops. Results are identical,
// only sequential. Force-included by wasm/build.sh, never by native builds.
#pragma once
#include <chrono>
#include <cstdlib>
#include <functional>
#include <utility>
#include <mutex>   // lock_guard / unique_lock / defer_lock exist; mutex itself does not

#define SCULPT_SINGLE_THREAD 1

namespace std {
struct mutex { void lock() {} void unlock() {} bool try_lock() { return true; } };
struct recursive_mutex : mutex {};
template <class M> struct unique_lock {
    unique_lock() = default;
    explicit unique_lock(M&) {}
    unique_lock(M&, defer_lock_t) {}
    void lock() {} void unlock() {} bool owns_lock() const { return true; }
};
enum class cv_status { no_timeout, timeout };
struct condition_variable {
    void notify_one() {} void notify_all() {}
    template <class L> void wait(L&) {}
    template <class L, class P> void wait(L&, P p) { (void)p; }   // never blocks: nothing else runs
    template <class L, class D, class P> bool wait_for(L&, const D&, P p) { return p(); }
};
using condition_variable_any = condition_variable;
class thread {
public:
    thread() = default;
    template <class F, class... A> explicit thread(F&& f, A&&... a) { std::invoke(std::forward<F>(f), std::forward<A>(a)...); }
    thread(thread&&) = default;
    thread& operator=(thread&&) = default;
    bool joinable() const { return false; }
    void join() {}
    void detach() {}
    static unsigned hardware_concurrency() { return 1; }
};
namespace this_thread {
inline void yield() {}
template <class R, class P> void sleep_for(const chrono::duration<R, P>&) {}
}
}  // namespace std

// No C++ exceptions in this toolchain: a throw ends the program, try runs its
// body, catch blocks are dropped (code that needs the error uses SCULPT_CATCH).
#define try if (true)
#define catch(...) else if (false)
#define throw ::abort(), (void)
