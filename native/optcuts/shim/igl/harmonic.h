// LOKI (AGPL-3.0): stand-in for libigl's igl::harmonic for the k = 1 case OptCuts uses (Tutte /
// harmonic map with fixed boundary). libigl's harmonic.h pulls min_quad_with_fixed (SparseLU, SparseQR,
// unsupported SparseExtra); this solves the same problem - minimise x' A x with x(b) = bc - directly:
// A_II x_I = -A_IB bc, with Eigen's SimplicialLDLT on -A_II (symmetric positive definite for a
// Laplacian of a connected mesh with a non-empty boundary). Returns false if the solve fails.
#pragma once
#include <Eigen/Core>
#include <Eigen/Sparse>
#include <Eigen/SparseCholesky>
#include <igl/cotmatrix.h>
#include <vector>

namespace igl {
inline bool harmonic(const Eigen::SparseMatrix<double>& A, const Eigen::SparseMatrix<double>& /*M*/,
                     const Eigen::VectorXi& b, const Eigen::MatrixXd& bc, int k, Eigen::MatrixXd& W)
{
    if (k != 1 || A.rows() != A.cols() || b.size() != bc.rows() || b.size() == 0) return false;
    const int n = static_cast<int>(A.rows());
    std::vector<int> slot(n, -1);  // >= 0: interior index; -2 - j: boundary entry j
    for (int j = 0; j < b.size(); ++j) { if (b[j] < 0 || b[j] >= n) return false; slot[b[j]] = -2 - j; }
    int ni = 0;
    for (int i = 0; i < n; ++i) if (slot[i] == -1) slot[i] = ni++;
    W.resize(n, bc.cols());
    for (int j = 0; j < b.size(); ++j) W.row(b[j]) = bc.row(j);
    if (ni == 0) return true;
    std::vector<Eigen::Triplet<double>> tri;
    Eigen::MatrixXd rhs = Eigen::MatrixXd::Zero(ni, bc.cols());
    for (int c = 0; c < A.outerSize(); ++c)
        for (Eigen::SparseMatrix<double>::InnerIterator it(A, c); it; ++it) {
            const int r = static_cast<int>(it.row()), col = static_cast<int>(it.col());
            if (slot[r] < 0) continue;
            if (slot[col] >= 0) tri.emplace_back(slot[r], slot[col], -it.value());
            else rhs.row(slot[r]) += it.value() * bc.row(-2 - slot[col]);
        }
    Eigen::SparseMatrix<double> Aii(ni, ni);
    Aii.setFromTriplets(tri.begin(), tri.end());
    Eigen::SimplicialLDLT<Eigen::SparseMatrix<double>> ldlt(Aii);
    if (ldlt.info() != Eigen::Success) return false;
    Eigen::MatrixXd x = ldlt.solve(rhs);
    if (ldlt.info() != Eigen::Success || !x.allFinite()) return false;
    for (int i = 0; i < n; ++i) if (slot[i] >= 0) W.row(i) = x.row(slot[i]);
    return true;
}
// cotangent-weight overload (OptCuts' EBCuts mode 2, unused by the C API but kept compiling)
inline bool harmonic(const Eigen::MatrixXd& V, const Eigen::MatrixXi& F, const Eigen::VectorXi& b,
                     const Eigen::MatrixXd& bc, int k, Eigen::MatrixXd& W)
{
    Eigen::SparseMatrix<double> L, M;
    igl::cotmatrix(V, F, L);
    return harmonic(L, M, b, bc, k, W);
}
}  // namespace igl
