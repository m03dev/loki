// Force-included into every OptCuts translation unit by build.sh (LOKI, AGPL-3.0).
// WebAssembly build without threads or C++ exceptions:
//  - libigl's parallel_for.h names std::thread; IGL_PARALLEL_FOR_FORCE_SERIAL means it never starts one,
//    so a stub type that only has to compile is enough (the pthread-less libc++ has none).
//  - oc_fatal(): where OptCuts called exit(-1) (invalid mesh, inverted initial map, failed factorization)
//    the port records a message and traps; the JS wrapper reads it with oc_error() and drops the instance.
#pragma once
#include <cstddef>
#include <cmath>
#include <thread>

#ifdef __cplusplus
extern "C" [[noreturn]] void oc_fatal(const char* msg);
extern "C" void oc_phase(const char* phase);
#if defined(_LIBCPP_HAS_NO_THREADS)
namespace std {
class thread {
public:
    thread() = default;
    template <class F, class... A> explicit thread(F&&, A&&...) { oc_fatal("std::thread is not available"); }
    bool joinable() const { return false; }
    void join() {}
    static unsigned hardware_concurrency() { return 1; }
};
}  // namespace std
#endif
#endif
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
