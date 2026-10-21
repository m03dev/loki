#!/usr/bin/env bash
# Build the sculpting engine as one WebAssembly module (sculpt.wasm) with the
# WASI SDK (https://github.com/WebAssembly/wasi-sdk, clang + libc++ for wasm32).
#   WASI_SDK=/path/to/wasi-sdk-25.0 bash wasm/build.sh [out-dir]
# Single-threaded (no SharedArrayBuffer needed in the page), SIMD on.
set -euo pipefail
cd "$(dirname "$0")/.."
W="${WASI_SDK:?set WASI_SDK to the wasi-sdk folder}"
OUT="${1:-build-wasm}"
mkdir -p "$OUT/obj"
CXX=("$W/bin/clang++" --target=wasm32-wasip1 --sysroot="$W/share/wasi-sysroot" -std=c++17 -O3 -msimd128
     -fno-exceptions -Wno-keyword-macro -include wasm/st_compat.h
     -Icore/include -Ithird_party/instant-meshes/src -Ithird_party/instant-meshes/shim -Ithird_party/eigen
     -Ithird_party/meshoptimizer/src -Ithird_party/meshoptimizer -DEIGEN_MPL2_ONLY -DEIGEN_NO_EXCEPTIONS -DNDEBUG -DXA_MULTITHREADED=0 -DXA_DEFAULT_PRINT=nullptr)
SRC=(wasm/sculpt_api.cpp core/src/mesh.cpp core/src/bvh.cpp core/src/brush.cpp core/src/dyntopo.cpp
     core/src/voxel_remesh.cpp core/src/quad_remesh.cpp core/src/preset_io.cpp core/src/instant_meshes.cpp
     core/src/multires.cpp core/src/curve_tube.cpp core/src/cage_subdiv.cpp core/src/uv_unwrap.cpp
     third_party/xatlas/xatlas.cpp third_party/instant-meshes/src/*.cpp)
pids=(); objs=()
for f in "${SRC[@]}"; do
  o="$OUT/obj/$(echo "$f" | tr / _).o"; objs+=("$o")
  # rebuilt when its source, st_compat.h or ANY engine header changed (a changed class layout in a header that only
  # some objects were rebuilt against linked into a module that crashed)
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ wasm/st_compat.h -nt "$o" ] || [ -n "$(find core/include -name '*.h' -newer "$o" -print -quit)" ]; then
    "${CXX[@]}" -w -c "$f" -o "$o" & pids+=($!); fi
done
for p in "${pids[@]}"; do wait "$p"; done
"${CXX[@]}" -mexec-model=reactor -Wl,--strip-all -Wl,-z,stack-size=2097152 -Wl,--initial-memory=33554432 \
  "${objs[@]}" -o "$OUT/sculpt.wasm"
ls -la "$OUT/sculpt.wasm"
