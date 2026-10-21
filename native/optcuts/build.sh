#!/usr/bin/env bash
# Build OptCuts (headless solve + LOKI's C API) as one WebAssembly module with the WASI SDK
# (https://github.com/WebAssembly/wasi-sdk, clang + libc++ for wasm32):
#   WASI_SDK=/path/to/wasi-sdk-25.0 bash native/optcuts/build.sh [out-dir]
# Default out-dir: app/ui/vendor/optcuts (optcuts.wasm next to optcuts_engine.js / optcuts_worker.js).
# Single-threaded (TBB replaced by serial loops: shim/tbb/tbb.h), no C++ exceptions, SIMD on.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
W="${WASI_SDK:?set WASI_SDK to the wasi-sdk folder}"
OUT="${1:-$REPO/app/ui/vendor/optcuts}"
# object files live outside the repository (OPTCUTS_OBJ to choose), so nothing to commit by mistake
OBJ="${OPTCUTS_OBJ:-${TMPDIR:-/tmp}/loki-optcuts-obj}"
mkdir -p "$OUT" "$OBJ"
cd "$HERE"
CXX=("$W/bin/clang++" --target=wasm32-wasip1 --sysroot="$W/share/wasi-sysroot" -std=c++17 -O2 -msimd128
     -fno-exceptions -DNDEBUG -DEIGEN_MPL2_ONLY -DEIGEN_NO_EXCEPTIONS -DIGL_PARALLEL_FOR_FORCE_SERIAL
     -DCDT_DISABLE_EXCEPTIONS -include shim/oc_compat.h
     -Ishim -Isrc -Isrc/Energy -Isrc/Utils -Isrc/LinSysSolver
     -Ithird_party/eigen -Ithird_party/libigl/include -Ithird_party/CDT/include)
SRC=(wasm/optcuts_api.cpp src/Optimizer.cpp src/TriMesh.cpp src/Scaffold.cpp src/Energy/Energy.cpp
     src/Energy/SymDirichletEnergy.cpp src/Utils/IglUtils.cpp src/LinSysSolver/EigenLibSolver.cpp)
pids=(); objs=()
for f in "${SRC[@]}"; do
  o="$OBJ/$(echo "$f" | tr / _).o"; objs+=("$o")
  # rebuilt when its source or any header of the port changed
  if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ -n "$(find src shim wasm -name '*.h*' -newer "$o" -print -quit)" ]; then
    "${CXX[@]}" -w -c "$f" -o "$o" & pids+=($!); fi
done
for p in "${pids[@]}"; do wait "$p"; done
"${CXX[@]}" -mexec-model=reactor -Wl,--strip-all -Wl,-z,stack-size=4194304 -Wl,--initial-memory=33554432 \
  "${objs[@]}" -o "$OUT/optcuts.wasm"
ls -la "$OUT/optcuts.wasm"
