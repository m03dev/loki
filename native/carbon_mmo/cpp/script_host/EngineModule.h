// MODULE: script-host
#pragma once

#include <pybind11/pybind11.h>

namespace cmmo::engine_module
{
// Number of times Python called into C++ through cmmo_engine (proves Python -> C++).
int PythonToCppCalls();
// The callable registered with cmmo_engine.on_frame(), or None.
pybind11::object FrameCallback();
// Drops Python references before the interpreter shuts down.
void Reset();
}
