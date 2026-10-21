// Sculpting engine — regularized Kelvinlet grab (de Goes & James, "Regularized Kelvinlets",
// SIGGRAPH 2017). Closed-form elastic response of an infinite medium to a
// regularized point force: volume-aware, smooth, no mesh solve.
//
//   u(r) = c·ε · [ (a−b)/r_ε · I + b/r_ε³ · r rᵀ + a·ε²/(2 r_ε³) · I ] · f
//   r_ε = sqrt(|r|² + ε²),  a = 1/(4πμ),  b = a / (4(1−ν)),  c = 2 / (3a − 2b)
//
// With this c, u(0) = f exactly, so passing the cursor delta as f makes the
// vertex under the cursor follow the cursor 1:1 (Move Elastic feel).
// ν (Poisson ratio) → 0.5 approaches incompressible = maximum volume preservation.
#pragma once
#include "sculpt/math.h"

namespace sculpt {

struct Kelvinlet {
    float eps, a, b, c;
    Kelvinlet(float radius, float poisson, float shear = 1.0f) {
        const float kPi = 3.14159265358979f;
        poisson = std::min(0.49f, std::max(0.0f, poisson));
        eps = std::max(1e-6f, radius);
        a = 1.0f / (4.0f * kPi * shear);
        b = a / (4.0f * (1.0f - poisson));
        c = 2.0f / (3.0f * a - 2.0f * b);
    }
    // Displacement at offset r from the grab point for brush force f.
    Vec3 grab(const Vec3& r, const Vec3& f) const {
        float re2 = length2(r) + eps * eps;
        float re = std::sqrt(re2);
        float re3 = re2 * re;
        float iso = (a - b) / re + a * eps * eps / (2.0f * re3);
        float aniso = b / re3;
        return (f * iso + r * (aniso * dot(r, f))) * (c * eps);
    }
    // Radial profile of the regularized twist and scale Kelvinlets,
    // (1/r_e^3 + 3 e^2 / (2 r_e^5)), normalized to 1 at r = 0 (value there is
    // 5 / (2 e^3)). Twist: u = profile * (q x r); scale: u = profile * s r.
    float profile(const Vec3& r) const {
        float re2 = length2(r) + eps * eps;
        float re = std::sqrt(re2);
        float re3 = re2 * re, re5 = re3 * re2;
        float e2 = eps * eps;
        return (1.0f / re3 + 1.5f * e2 / re5) * (e2 * eps / 2.5f);
    }
};

}  // namespace sculpt
