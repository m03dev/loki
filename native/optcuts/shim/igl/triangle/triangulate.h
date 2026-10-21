// LOKI (AGPL-3.0): stand-in for libigl's igl::triangle::triangulate, which wraps Jonathan Shewchuk's
// Triangle - Triangle's licence forbids commercial use, so it is not in LOKI. OptCuts calls it once per
// scaffold rebuild with flags "qYQ" (+ libigl's own "pzB"): a constrained Delaunay triangulation of the
// UV boundary loops plus a bounding box, quality-refined (20 degree minimum angle) WITHOUT new vertices
// on the constraint segments (Y), and with the regions inside the charts removed. This does the same
// with CDT (Artem Amirkhanov, MPL-2.0, third_party/CDT):
//   - the input points keep their indices (CDT appends Steiner points after them), as OptCuts requires;
//   - holes: Triangle eats the region around each hole point H; CDT removes the regions at even
//     nesting depth (outside the box, inside each chart, ...). For OptCuts' inputs (non-overlapping
//     charts inside a box, or one loop for the local stencils) both remove exactly the chart interiors,
//     so H is not needed;
//   - quality: CDT::refineTriangles with the smallest-angle criterion, fixed edges never split
//     (Triangulation::splitFixedEdges = false, a small LOKI patch), with a vertex budget.
// Flags other than q are accepted and ignored. Errors (duplicate points, bad input) call oc_fatal.
#pragma once
#include <Eigen/Core>
#include <string>
#include <vector>
#ifndef CDT_DISABLE_EXCEPTIONS
#define CDT_DISABLE_EXCEPTIONS
#endif
#ifndef CDT_ERROR_HANDLER
#define CDT_ERROR_HANDLER(msg) oc_fatal(msg)
#endif
#include <CDT.h>

namespace igl { namespace triangle {
inline void triangulate(const Eigen::MatrixXd& V, const Eigen::MatrixXi& E, const Eigen::MatrixXd& /*H*/,
                        const std::string flags, Eigen::MatrixXd& V2, Eigen::MatrixXi& F2)
{
    CDT::Triangulation<double> cdt(CDT::VertexInsertionOrder::Auto,
                                   CDT::IntersectingConstraintEdges::TryResolve, 0.0);
    std::vector<CDT::V2d<double>> pts(V.rows());
    for (int i = 0; i < V.rows(); ++i) pts[i] = CDT::V2d<double>(V(i, 0), V(i, 1));
    std::vector<CDT::Edge> edges;
    edges.reserve(E.rows());
    for (int i = 0; i < E.rows(); ++i)
        if (E(i, 0) != E(i, 1)) edges.emplace_back(CDT::VertInd(E(i, 0)), CDT::VertInd(E(i, 1)));
    cdt.insertVertices(pts);
    cdt.insertEdges(edges);
    CDT::TriIndUSet erase = cdt.collectOuterTrianglesAndHoles();
    if (flags.find('q') != std::string::npos) {
        cdt.splitFixedEdges = false;  // Triangle's Y
        const CDT::VertInd budget = CDT::VertInd(4 * V.rows() + 64);
        cdt.refineTriangles(budget, CDT::RefinementCriterion::SmallestAngle, CDT::degToRad(20.0), &erase, 0.0);
    }
    cdt.finalizeTriangulation(erase);
    V2.resize(cdt.vertices.size(), 2);
    for (size_t i = 0; i < cdt.vertices.size(); ++i) { V2(i, 0) = cdt.vertices[i].x; V2(i, 1) = cdt.vertices[i].y; }
    F2.resize(cdt.triangles.size(), 3);
    for (size_t t = 0; t < cdt.triangles.size(); ++t)
        for (int k = 0; k < 3; ++k) F2(t, k) = int(cdt.triangles[t].vertices[k]);
}
}}  // namespace igl::triangle
