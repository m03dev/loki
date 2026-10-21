// Serial stand-in for the one Intel TBB call OptCuts makes (tbb::parallel_for over an int range).
// LOKI builds OptCuts single-threaded for WebAssembly (no SharedArrayBuffer), so the loop body runs
// in order on the calling thread. Results are identical; OptCuts' parallel loops write disjoint slots.
// Part of LOKI (AGPL-3.0).
#pragma once
namespace tbb {
template <typename Index, typename Func>
inline void parallel_for(Index first, Index last, Index step, const Func& f) {
    for (Index i = first; i < last; i += step) f(i);
}
template <typename Index, typename Func>
inline void parallel_for(Index first, Index last, const Func& f) {
    for (Index i = first; i < last; ++i) f(i);
}
}  // namespace tbb
