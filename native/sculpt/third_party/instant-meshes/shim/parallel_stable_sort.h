// Shim: pss::parallel_stable_sort -> std::stable_sort (same result, serial).
#pragma once
#include <algorithm>
namespace pss {
template <typename It, typename Comp>
void parallel_stable_sort(It b, It e, Comp c) { std::stable_sort(b, e, c); }
}
