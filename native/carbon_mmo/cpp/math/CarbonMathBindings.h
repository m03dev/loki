// MODULE: math
// Python bindings for Carbon's math library (carbonengine/math).
// Swap point: replace CarbonMath with another vector library by re-implementing
// this one function; Python code only ever sees the `Vector3` API defined here.
#pragma once

#include <pybind11/pybind11.h>

namespace cmmo
{
// Registers `Vector3` and helpers on `m`. Types are module-local so the same
// bindings can live in the cmmo_math extension and in the embedded host module.
void BindCarbonMath( pybind11::module_& m );
}
