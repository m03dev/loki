# Third-party notices

LOKI's sculpting engine (AGPL-3.0, like the rest of LOKI) contains, or derives algorithms from, the
following open-source work; their licences require these notices.

## SculptGL — MIT
https://github.com/stephomi/sculptgl — the Crease brush's displacement profile
(pinch toward the centre plus a carve with falloff^5) follows SculptGL's
`Crease.js`.

```
MIT License

Copyright (c) 2019 Stéphane GINIER

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Instant Meshes — BSD 3-Clause
https://github.com/wjakob/instant-meshes — field-aligned quad remeshing behind
the quad remesher (`third_party/instant-meshes/src`, used unmodified except:
file I/O removed from `serializer.cpp`, BVH replaced by stubs (`bvh_stub.cpp`), a lock
fix in `Optimizer::shutdown()` (`field.h`); The engine drives the field optimization
synchronously in `core/src/instant_meshes.cpp`). Intel TBB and pss are replaced by
small shims in `third_party/instant-meshes/shim` (no TBB code is included).

```
Copyright (c) 2015 Wenzel Jakob, Daniele Panozzo, Marco Tarini,
and Olga Sorkine-Hornung. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

You are under no obligation whatsoever to provide any bug fixes, patches, or
upgrades to the features, functionality or performance of the source code
("Enhancements") to anyone; however, if you choose to make your Enhancements
available either publicly, or directly to the authors of this software, without
imposing a separate written license agreement for such Enhancements, then you
hereby grant the following license: a non-exclusive, royalty-free perpetual
license to install, use, modify, prepare derivative works, incorporate into
other computer software, distribute, and sublicense such enhancements or
derivative works thereof, in binary and source code form.
```

## Eigen 3.3.7 — MPL-2.0
https://eigen.tuxfamily.org — header-only linear algebra used by Instant Meshes,
compiled with `EIGEN_MPL2_ONLY` (no LGPL parts). Unmodified source in
`third_party/eigen`; the MPL-2.0 text is in `third_party/eigen/COPYING.MPL2`.

## pcg32 — Apache-2.0
https://github.com/wjakob/pcg32 (Wenzel Jakob, after Melissa O'Neill's PCG) —
`third_party/instant-meshes/shim/pcg32.h`, unmodified. Apache License 2.0:
https://www.apache.org/licenses/LICENSE-2.0

## dset — zlib
https://github.com/wjakob/dset — `third_party/instant-meshes/shim/dset.h`, unmodified.

```
Copyright (c) 2015 Wenzel Jakob <wenzel@inf.ethz.ch>

This software is provided 'as-is', without any express or implied
warranty.  In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not
claim that you wrote the original software. If you use this software
in a product, an acknowledgment in the product documentation would be
appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be
misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
```

## Papers (no code used)
* F. de Goes, D. James, *Regularized Kelvinlets*, SIGGRAPH 2017 — Move Elastic,
  Elastic Twist, Elastic Scale.
* M. Botsch, L. Kobbelt, *A Remeshing Approach to Multiresolution Modeling*,
  SGP 2004 — Sculptris Pro split/collapse.
* T. Ju et al., *Dual Contouring of Hermite Data*, SIGGRAPH 2002 — voxel remesh sharp features.
* W. Jakob, M. Tarini, D. Panozzo, O. Sorkine-Hornung, *Instant Field-Aligned Meshes*,
  SIGGRAPH Asia 2015 — the quad remesher (code above).
* B. Lévy, S. Petitjean, N. Ray, J. Maillot, *Least Squares Conformal Maps for Automatic Texture
  Atlas Generation*, SIGGRAPH 2002 — `uv_unwrap.cpp` uvUnfold (LSCM with pins).
* L. Liu, L. Zhang, Y. Xu, C. Gotsman, S. Gortler, *A Local/Global Approach to Mesh
  Parameterization*, SGP 2008 — `uv_unwrap.cpp` uvUnfold (ARAP rounds).
* Skyline bin packing (as surveyed by J. Jylänki, *A Thousand Ways to Pack the Bin*, 2010) and
  rotating calipers (G. Toussaint 1983) — `uv_unwrap.cpp` uvLayout.

## meshoptimizer — MIT

https://github.com/zeux/meshoptimizer (third_party/meshoptimizer, commit in
COMMIT.txt). Copyright (c) 2016-2026 Arseny Kapoulkine. Used for meshlets,
simplification and the cluster LOD DAG (`clusterlod.h`, from the project's
demo/). Sculpting modification to clusterlod.h: per-level groups are
simplified on worker threads and very large inputs are clusterized in parallel
spatial chunks (output order unchanged). Full license text in
third_party/meshoptimizer/LICENSE.md.


## xatlas — MIT

https://github.com/jpcy/xatlas (third_party/xatlas, commit in COMMIT.txt), the automatic chart
cutting / parameterization / packing behind `uvAuto` (`core/src/uv_unwrap.cpp`). Built single-threaded
(`XA_MULTITHREADED=0`) with no default print (`XA_DEFAULT_PRINT=nullptr`). LOKI's changes, each marked
`LOKI` in xatlas.cpp: polygon input (MeshDecl::faceVertexCount) reads corner `firstCorner + i` instead of
`face * faceVertexCount + i` (mixed polygon sizes were read wrong) and checks that the sizes sum to the
index count; the degenerate-edge test wraps at the polygon's size (was `% 3`); triangle corners map back
to polygon *corners* (was the vertex id, which wrote outside the index array); ignored triangles of a
polygon mesh are counted and written at their polygon corners; the output index array starts as
UINT32_MAX (= a corner no chart wrote); the default print function can be set at build time.

```
MIT License

Copyright (c) 2018-2020 Jonathan Young

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
