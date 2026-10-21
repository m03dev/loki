// OptCuts for LOKI's Forge - the C API of optcuts.wasm (LOKI, AGPL-3.0).
//
// OptCuts (Li, Kaufman, Kim, Sheffer, Levin, "OptCuts: Joint Optimization of Surface Cuts and
// Parameterization", SIGGRAPH Asia 2018; github.com/liminchen/OptCuts, MIT) jointly optimises seams and
// UVs: it adds and removes seams while minimising the symmetric Dirichlet distortion, until the
// distortion meets the bound b_d with the shortest seams it can find. The algorithm itself is the
// unchanged upstream code in ../src. This file replaces OptCuts' main.cpp (a viewer program that reads
// OBJ files and writes PNGs): it ports main()'s "initialise UV" part and the headless (mode 100) loop of
// preDrawFunc / updateLambda_stationaryV / converge_preDrawFunc into a state machine that runs in
// slices, so a Web Worker can report progress between slices:
//
//   oc_init(mesh, options)   - validate, cut to disk(s), Tutte map, set up the optimizer
//   oc_step(n, ms)           - up to n units of work (one Newton step or one topology decision each),
//                              at most `ms` milliseconds; returns 0 running, 1 finished, -1 error
//   oc_finish()              - build the result (also when stopped early: the best feasible map so far)
//   oc_uv / oc_corner_uv / oc_seams / ... read it
//
// Single-threaded, no C++ exceptions: errors inside OptCuts call oc_fatal(), which stores the message
// and traps; the JS wrapper reads oc_error() and starts a fresh instance.
#include "Types.hpp"
#include "IglUtils.hpp"
#include "Optimizer.hpp"
#include "SymDirichletEnergy.hpp"
#include "Timer.hpp"
#include "cut_to_disk.hpp"

#include <igl/boundary_loop.h>
#include <igl/edge_lengths.h>
#include <igl/euler_characteristic.h>
#include <igl/facet_components.h>
#include <igl/harmonic.h>
#include <igl/is_edge_manifold.h>
#include <igl/is_vertex_manifold.h>
#include <igl/map_vertices_to_circle.h>

#include <algorithm>
#include <cfloat>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>

#define OC_EXPORT(name) extern "C" __attribute__((export_name(#name)))

// ------------------------------------------------------------------ globals OptCuts' sources expect
// (main.cpp defined them; TriMesh.cpp / Optimizer.cpp / Scaffold.cpp / Energy*.cpp declare them extern)
std::ofstream logFile;  // never opened: OptCuts' log lines go nowhere
Timer timer, timer_step;
OptCuts::MethodType methodType = OptCuts::MT_OPTCUTS;
extern const std::string outputFolderPath = "";
extern const bool fractureMode = true;
std::vector<std::pair<double, double>> energyChanges_bSplit, energyChanges_iSplit, energyChanges_merge;
std::vector<std::vector<int>> paths_bSplit, paths_iSplit, paths_merge;
std::vector<Eigen::MatrixXd> newVertPoses_bSplit, newVertPoses_iSplit, newVertPoses_merge;
double filterExp_in = 0.6;
int inSplitTotalAmt = 0;

static char gError[512] = "";
static char gPhase[64] = "idle";

extern "C" [[noreturn]] void oc_fatal(const char* msg) {
    std::snprintf(gError, sizeof gError, "%s (during %s)", msg ? msg : "error", gPhase);
    __builtin_trap();
}
extern "C" void oc_phase(const char* phase) { std::snprintf(gPhase, sizeof gPhase, "%s", phase); }

static bool fail(const char* msg) { std::snprintf(gError, sizeof gError, "%s", msg); return false; }

static double nowMs() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

namespace {

const double convTol_upperBound = 1.0e-3;  // main.cpp
const double fracThres = 0.0;              // main.cpp
const bool topoLineSearch = true;          // main.cpp

enum Phase { P_IDLE, P_OPT, P_EXACT, P_DONE, P_ERROR };

struct Run {
    // input (compacted: only vertices that triangles use)
    Eigen::MatrixXd V;
    Eigen::MatrixXi F;
    std::vector<int> compactToInput;
    double upperBound = 4.1, lambdaInit = 0.999;
    bool bijectiveParam = true;
    int initCutOption = 0, maxIterations = 0;
    double timeBudgetMs = 0, startMs = 0;
    unsigned seed = 0;

    std::vector<OptCuts::Energy*> energyTerms;
    std::vector<double> energyParams;
    OptCuts::TriMesh* triSoup0 = nullptr;
    OptCuts::Optimizer* optimizer = nullptr;
    bool rand1PInitCut = false;

    Phase phase = P_IDLE;
    int iterNum = 0, converged = 0, topoOps = 0;
    bool budgetHit = false, outerConverged = false;

    // main.cpp's updateLambda_stationaryV() function statics, now per run
    int iterNum_bestFeasible = -1;
    OptCuts::TriMesh triSoup_bestFeasible;
    double E_se_bestFeasible = DBL_MAX;
    int lastStationaryIterNum = 0;
    std::map<double, std::vector<std::pair<double, double>>> configs_stationaryV;
    // main.cpp's queried-operation globals
    int opType_queried = -1;
    std::vector<int> path_queried;
    Eigen::MatrixXd newVertPos_queried;
    bool reQuery = false;

    // result
    std::vector<float> uv;
    std::vector<int> cornerUV, seams;
    double distortion = 0, seamLength = 0;
    int flipped = 0;

    ~Run() {
        delete optimizer;
        for (auto* e : energyTerms) delete e;
        delete triSoup0;
    }
};

Run* R = nullptr;

// ------------------------------------------------------------------ main.cpp helpers (unchanged logic)
int computeOptPicked(const std::vector<std::pair<double, double>>& energyChanges0,
                     const std::vector<std::pair<double, double>>& energyChanges1, double lambda) {
    double minEChange0 = __DBL_MAX__;
    for (const auto& ec : energyChanges0) {
        if ((ec.first == __DBL_MAX__) || (ec.second == __DBL_MAX__)) continue;
        double EwChange = ec.first * (1.0 - lambda) + ec.second * lambda;
        if (EwChange < minEChange0) minEChange0 = EwChange;
    }
    double minEChange1 = __DBL_MAX__;
    for (const auto& ec : energyChanges1) {
        if ((ec.first == __DBL_MAX__) || (ec.second == __DBL_MAX__)) continue;
        double EwChange = ec.first * (1.0 - lambda) + ec.second * lambda;
        if (EwChange < minEChange1) minEChange1 = EwChange;
    }
    return (minEChange0 > minEChange1);
}

int computeBestCand(const std::vector<std::pair<double, double>>& energyChanges, double lambda, double& bestEChange) {
    bestEChange = __DBL_MAX__;
    int id_minEChange = -1;
    for (int ecI = 0; ecI < (int)energyChanges.size(); ecI++) {
        if ((energyChanges[ecI].first == __DBL_MAX__) || (energyChanges[ecI].second == __DBL_MAX__)) continue;
        double EwChange = energyChanges[ecI].first * (1.0 - lambda) + energyChanges[ecI].second * lambda;
        if (EwChange < bestEChange) { bestEChange = EwChange; id_minEChange = ecI; }
    }
    return id_minEChange;
}

bool checkCand(const std::vector<std::pair<double, double>>& energyChanges) {
    for (const auto& candI : energyChanges)
        if ((candI.first < 0.0) || (candI.second < 0.0)) return true;
    return false;
}

double updateLambda(Run& r, double measure_bound) {
    double lambda_SD = r.energyParams[0];
    lambda_SD = std::max(0.0, (measure_bound - (r.upperBound - convTol_upperBound / 2.0)) + lambda_SD / (1.0 - lambda_SD));
    return lambda_SD / (1.0 + lambda_SD);
}

// LOKI: the original's do/while lambda loops have no exit when the candidates never change sign;
// cap them (the run then ends as converged, with the best feasible map).
const int kLambdaLoopCap = 100000;

bool updateLambda_stationaryV(Run& r, bool cancelMomentum = true, bool checkConvergence = false) {
    (void)cancelMomentum;
    OptCuts::Optimizer* optimizer = r.optimizer;
    OptCuts::TriMesh& res = optimizer->getResult();
    Eigen::MatrixXd edgeLengths;
    igl::edge_lengths(res.V_rest, res.F, edgeLengths);
    const double eps_E_se = 1.0e-3 * edgeLengths.minCoeff() / res.virtualRadius;

    const double E_SD = optimizer->getLastEnergyVal(true) / r.energyParams[0];
    double E_se;
    res.computeSeamSparsity(E_se);
    E_se /= res.virtualRadius;
    const double measure_bound = E_SD;
    const double eps_lambda = std::min(1.0e-3, std::abs(updateLambda(r, measure_bound) - r.energyParams[0]));

    if (r.iterNum != r.lastStationaryIterNum) {
        const double lambda = 1.0 - r.energyParams[0];
        bool oscillate = false;
        auto matches = [&](const std::vector<std::pair<double, double>>& list) {
            for (const auto& lambdaI : list)
                if ((std::abs(lambdaI.first - lambda) < eps_lambda) && (std::abs(lambdaI.second - E_SD) < eps_E_se)) return true;
            return false;
        };
        auto& cfg = r.configs_stationaryV;
        const auto low = cfg.lower_bound(E_se);
        if (low == cfg.end()) {
            if (!cfg.empty() && std::abs(cfg.rbegin()->first - E_se) < eps_E_se) oscillate = matches(cfg.rbegin()->second);
        } else if (low == cfg.begin()) {
            if (std::abs(low->first - E_se) < eps_E_se) oscillate = matches(low->second);
        } else {
            const auto prev = std::prev(low);
            if (std::abs(low->first - E_se) < eps_E_se) oscillate = matches(low->second);
            if (!oscillate && std::abs(prev->first - E_se) < eps_E_se) oscillate = matches(prev->second);
        }

        // record best feasible UV map
        if ((measure_bound <= r.upperBound) && (E_se < r.E_se_bestFeasible)) {
            r.iterNum_bestFeasible = r.iterNum;
            r.triSoup_bestFeasible = res;
            r.E_se_bestFeasible = E_se;
        }

        if (oscillate && (r.iterNum_bestFeasible >= 0)) {
            if (r.iterNum_bestFeasible != r.iterNum)
                optimizer->setConfig(r.triSoup_bestFeasible, r.iterNum, optimizer->getTopoIter());
            return false;
        }
        cfg[E_se].emplace_back(lambda, E_SD);
    }
    r.lastStationaryIterNum = r.iterNum;

    if (checkConvergence) {
        if (measure_bound <= r.upperBound) {
            if (measure_bound >= r.upperBound - convTol_upperBound) {
                if (r.iterNum_bestFeasible != r.iterNum)
                    optimizer->setConfig(r.triSoup_bestFeasible, r.iterNum, optimizer->getTopoIter());
                return false;
            }
        }
    }

    r.energyParams[0] = updateLambda(r, measure_bound);

    if (checkConvergence) {
        if (measure_bound > r.upperBound) {
            if ((!energyChanges_merge.empty()) &&
                (computeOptPicked(energyChanges_bSplit, energyChanges_merge, 1.0 - r.energyParams[0]) == 1)) {
                int guard = 0;
                do {
                    r.energyParams[0] = updateLambda(r, measure_bound);
                } while ((computeOptPicked(energyChanges_bSplit, energyChanges_merge, 1.0 - r.energyParams[0]) == 1) && ++guard < kLambdaLoopCap);
            }
            if ((!checkCand(energyChanges_iSplit)) && (!checkCand(energyChanges_bSplit))) {
                r.reQuery = true;
            } else {
                double eDec_b, eDec_i;
                int id_b = computeBestCand(energyChanges_bSplit, 1.0 - r.energyParams[0], eDec_b);
                int id_i = computeBestCand(energyChanges_iSplit, 1.0 - r.energyParams[0], eDec_i);
                int guard = 0;
                while ((eDec_b > 0.0) && (eDec_i > 0.0)) {
                    if (++guard >= kLambdaLoopCap) return false;  // LOKI guard
                    r.energyParams[0] = updateLambda(r, measure_bound);
                    id_b = computeBestCand(energyChanges_bSplit, 1.0 - r.energyParams[0], eDec_b);
                    id_i = computeBestCand(energyChanges_iSplit, 1.0 - r.energyParams[0], eDec_i);
                }
                if (eDec_b <= 0.0) {
                    r.opType_queried = 0;
                    r.path_queried = paths_bSplit[id_b];
                    r.newVertPos_queried = newVertPoses_bSplit[id_b];
                } else {
                    r.opType_queried = 1;
                    r.path_queried = paths_iSplit[id_i];
                    r.newVertPos_queried = newVertPoses_iSplit[id_i];
                }
            }
        } else {
            bool noOp = true;
            for (const auto& ecI : energyChanges_merge)
                if (ecI.first != __DBL_MAX__) { noOp = false; break; }
            if (noOp) {
                r.energyParams[0] = 1.0 - eps_lambda;
                optimizer->updateEnergyData(true, false, false);
                if (r.iterNum_bestFeasible != r.iterNum)
                    optimizer->setConfig(r.triSoup_bestFeasible, r.iterNum, optimizer->getTopoIter());
                return false;
            }
            if (computeOptPicked(energyChanges_bSplit, energyChanges_merge, 1.0 - r.energyParams[0]) == 0) {
                int guard = 0;
                do {
                    r.energyParams[0] = updateLambda(r, measure_bound);
                } while ((computeOptPicked(energyChanges_bSplit, energyChanges_merge, 1.0 - r.energyParams[0]) == 0) && ++guard < kLambdaLoopCap);
            }
            double eDec_m;
            int id_m = computeBestCand(energyChanges_merge, 1.0 - r.energyParams[0], eDec_m);
            int guard = 0;
            while (eDec_m > 0.0) {
                if (++guard >= kLambdaLoopCap) return false;  // LOKI guard
                r.energyParams[0] = updateLambda(r, measure_bound);
                id_m = computeBestCand(energyChanges_merge, 1.0 - r.energyParams[0], eDec_m);
            }
            r.opType_queried = 2;
            r.path_queried = paths_merge[id_m];
            r.newVertPos_queried = newVertPoses_merge[id_m];
        }
    }

    if (r.energyParams[0] > 1.0 - eps_lambda) r.energyParams[0] = 1.0 - eps_lambda;
    if (r.energyParams[0] < eps_lambda) r.energyParams[0] = eps_lambda;
    optimizer->updateEnergyData(true, false, false);
    return true;
}

// converge_preDrawFunc: without bijectivity OptCuts finishes with an exact solve (no relative-decrease stop)
void converge(Run& r) {
    r.outerConverged = true;
    if (!r.bijectiveParam) {
        r.optimizer->setAllowEDecRelTol(false);
        r.converged = 0;
        r.optimizer->setPropagateFracture(false);
        r.phase = P_EXACT;
    } else {
        r.phase = P_DONE;
    }
}

// One unit of preDrawFunc's offline loop: a Newton step while not converged, else the topology decision.
void stepUnit(Run& r) {
    OptCuts::Optimizer* optimizer = r.optimizer;
    if (r.phase == P_EXACT) {
        oc_phase("final solve");
        r.converged = optimizer->solve(1);
        r.iterNum = optimizer->getIterNum();
        if (r.converged) r.phase = P_DONE;
        return;
    }
    if (!r.converged) {
        oc_phase("descent");
        r.converged = optimizer->solve(1);
        r.iterNum = optimizer->getIterNum();
        return;
    }
    oc_phase("topology");
    if (r.converged == 2) { r.converged = 0; return; }
    const double measure_bound = optimizer->getLastEnergyVal(true) / r.energyParams[0];

    if (!optimizer->isScaffolding() && r.bijectiveParam && r.rand1PInitCut) optimizer->setScaffolding(true);

    if (!updateLambda_stationaryV(r)) { converge(r); return; }
    r.topoOps++;
    if (optimizer->createFracture(fracThres, false, topoLineSearch)) { r.converged = 0; return; }
    if ((measure_bound > r.upperBound) && optimizer->createFracture(fracThres, false, topoLineSearch, true)) { r.converged = 0; return; }
    if (!updateLambda_stationaryV(r, false, true)) { converge(r); return; }
    if (r.reQuery) {
        filterExp_in += std::log(2.0) / std::log(std::max(inSplitTotalAmt, 3));
        filterExp_in = std::min(1.0, filterExp_in);
        bool made = false;
        while (!(made = optimizer->createFracture(fracThres, false, topoLineSearch, true))) {
            if (filterExp_in >= 1.0) break;  // LOKI guard: the original looped forever here
            filterExp_in += std::log(2.0) / std::log(std::max(inSplitTotalAmt, 3));
            filterExp_in = std::min(1.0, filterExp_in);
        }
        r.reQuery = false;
        if (!made) { converge(r); return; }
    } else {
        optimizer->createFracture(r.opType_queried, r.path_queried, r.newVertPos_queried, topoLineSearch);
    }
    r.opType_queried = -1;
    r.converged = 0;
}

// ------------------------------------------------------------------ input checks + initial UV (main.cpp)
bool loadMesh(Run& r, const float* pos, int nv, const int* tris, int nt) {
    if (!pos || !tris || nv < 3 || nt < 1) return fail("empty mesh");
    for (int i = 0; i < nv * 3; ++i)
        if (!std::isfinite(pos[i])) return fail("a vertex position is not a finite number");
    std::vector<int> map(nv, -1);
    for (int i = 0; i < nt * 3; ++i) {
        const int v = tris[i];
        if (v < 0 || v >= nv) return fail("a triangle index is out of range");
    }
    for (int t = 0; t < nt; ++t) {
        const int a = tris[3 * t], b = tris[3 * t + 1], c = tris[3 * t + 2];
        if (a == b || b == c || c == a) return fail("a triangle uses the same vertex twice");
        for (int k = 0; k < 3; ++k) if (map[tris[3 * t + k]] < 0) { map[tris[3 * t + k]] = (int)r.compactToInput.size(); r.compactToInput.push_back(tris[3 * t + k]); }
    }
    const int n = (int)r.compactToInput.size();
    r.V.resize(n, 3);
    for (int i = 0; i < n; ++i)
        for (int k = 0; k < 3; ++k) r.V(i, k) = pos[3 * r.compactToInput[i] + k];
    r.F.resize(nt, 3);
    for (int t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k) r.F(t, k) = map[tris[3 * t + k]];
    // zero-area triangles make OptCuts' rest shape singular
    double scale = (r.V.colwise().maxCoeff() - r.V.colwise().minCoeff()).norm();
    if (!(scale > 0)) return fail("the mesh has no extent");
    for (int t = 0; t < nt; ++t) {
        Eigen::Vector3d e1 = r.V.row(r.F(t, 1)) - r.V.row(r.F(t, 0)), e2 = r.V.row(r.F(t, 2)) - r.V.row(r.F(t, 0));
        if (e1.cross(e2).norm() <= 1e-14 * scale * scale) return fail("the mesh has a zero-area triangle");
    }
    // manifold and consistently oriented (each directed edge at most once)
    Eigen::VectorXi B;
    if (!igl::is_edge_manifold(r.F)) return fail("the mesh has non-manifold edges");
    if (!igl::is_vertex_manifold(r.F, B)) return fail("the mesh has non-manifold vertices");
    std::set<std::pair<int, int>> directed;
    for (int t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k)
            if (!directed.insert({r.F(t, k), r.F(t, (k + 1) % 3)}).second) return fail("the mesh's triangles are not consistently oriented");
    return true;
}

// Split the mesh along the given seam edges (compact vertex ids): returns the cut mesh's vertices and faces.
void cutAlongSeams(const Run& r, const std::set<std::pair<int, int>>& seamSet, Eigen::MatrixXd& Vc, Eigen::MatrixXi& Fc) {
    const int nt = (int)r.F.rows();
    // union corners (t, k) around each vertex across non-seam edges
    std::vector<int> parent(nt * 3);
    for (int i = 0; i < nt * 3; ++i) parent[i] = i;
    std::function<int(int)> find = [&](int x) { while (parent[x] != x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    std::map<std::pair<int, int>, int> halfEdge;  // directed edge -> face
    for (int t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k) halfEdge[{r.F(t, k), r.F(t, (k + 1) % 3)}] = t;
    auto cornerOf = [&](int t, int v) { for (int k = 0; k < 3; ++k) if (r.F(t, k) == v) return t * 3 + k; return -1; };
    for (const auto& he : halfEdge) {
        const int a = he.first.first, b = he.first.second;
        if (a > b) continue;
        auto opp = halfEdge.find({b, a});
        if (opp == halfEdge.end()) continue;
        if (seamSet.count({a, b})) continue;
        const int t0 = he.second, t1 = opp->second;
        for (int v : {a, b}) {
            int c0 = find(cornerOf(t0, v)), c1 = find(cornerOf(t1, v));
            if (c0 != c1) parent[c0] = c1;
        }
    }
    std::map<int, int> rootToV;
    Fc.resize(nt, 3);
    std::vector<int> src;
    for (int t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k) {
            int root = find(t * 3 + k);
            auto it = rootToV.find(root);
            if (it == rootToV.end()) { it = rootToV.emplace(root, (int)src.size()).first; src.push_back(r.F(t, k)); }
            Fc(t, k) = it->second;
        }
    Vc.resize((int)src.size(), 3);
    for (int i = 0; i < (int)src.size(); ++i) Vc.row(i) = r.V.row(src[i]);
}

bool initialUV(Run& r, const std::set<std::pair<int, int>>& seamSet) {
    oc_phase("initial cut");
    Eigen::MatrixXd Vc;
    Eigen::MatrixXi Fc;
    if (!seamSet.empty()) cutAlongSeams(r, seamSet, Vc, Fc);
    else { Vc = r.V; Fc = r.F; }

    Eigen::VectorXi C;
    igl::facet_components(Fc, C);
    const int n_components = C.maxCoeff() + 1;

    OptCuts::TriMesh temp(Vc, Fc, Eigen::MatrixXd(), Eigen::MatrixXi(), false);
    std::vector<Eigen::MatrixXi> F_component(n_components);
    std::vector<std::set<int>> V_ind_component(n_components);
    auto rebuild = [&]() {
        F_component.assign(n_components, Eigen::MatrixXi());
        V_ind_component.assign(n_components, std::set<int>());
        std::vector<std::vector<int>> rows(n_components);
        for (int triI = 0; triI < temp.F.rows(); ++triI) rows[C[triI]].push_back(triI);
        for (int c = 0; c < n_components; ++c) {
            F_component[c].resize((int)rows[c].size(), 3);
            for (int i = 0; i < (int)rows[c].size(); ++i) {
                F_component[c].row(i) = temp.F.row(rows[c][i]);
                for (int k = 0; k < 3; ++k) V_ind_component[c].insert(temp.F(rows[c][i], k));
            }
        }
    };
    rebuild();
    for (int pass = 0;; ++pass) {
        if (pass > 4 * (int)r.F.rows() + 16) return fail("could not cut the mesh into disks");
        std::vector<int> components_to_cut;
        for (int componentI = 0; componentI < n_components; ++componentI) {
            int EC = igl::euler_characteristic(temp.V, F_component[componentI]) - (int)temp.V.rows() + (int)V_ind_component[componentI].size();
            if (EC < 1) components_to_cut.push_back(-componentI - 1);  // higher genus or with holes: cut_to_disk
            else if (EC == 2) components_to_cut.push_back(componentI); // closed genus-0
            else if (EC != 1) return fail("unsupported connected component (Euler characteristic)");
        }
        if (components_to_cut.empty()) break;
        for (int componentI : components_to_cut) {
            if (componentI < 0) {
                componentI = -componentI - 1;
                std::vector<std::vector<int>> cuts;
                igl::cut_to_disk(F_component[componentI], cuts);
                int cuts_made = 0;
                for (auto& seamI : cuts) {
                    if (seamI.size() < 2) continue;
                    if (seamI.front() == seamI.back()) {
                        if (seamI.size() < 4) continue;
                        cuts_made += temp.cutPath(std::vector<int>({seamI[seamI.size() - 3], seamI[seamI.size() - 2], seamI[seamI.size() - 1]}), true);
                        temp.initSeams = temp.cohE;
                        seamI.resize(seamI.size() - 2);
                    }
                    cuts_made += temp.cutPath(seamI, true);
                    temp.initSeams = temp.cohE;
                    if (cuts_made) break;
                }
                if (!cuts_made) return fail("no cut could be made to turn the mesh into a disk");
            } else {
                // closed genus-0 component: OptCuts' one-point (initCutOption 0) or farthest-point (1) cut.
                // seed 0 starts at the component's first vertex, as OptCuts does; another seed picks
                // another of its triangles (deterministically).
                const Eigen::MatrixXi& Fcomp = F_component[componentI];
                const int row = r.seed ? int(r.seed % (unsigned)Fcomp.rows()) : 0;
                if (r.initCutOption == 2) temp.farthestPointCut(Fcomp(row, 0));
                else {
                    temp.onePointCut(Fcomp(row, 0));
                    r.rand1PInitCut = (n_components == 1);
                }
            }
        }
        rebuild();
    }

    // boundary of each component on a unit circle, components on a grid; Tutte (uniform harmonic) map
    int UVGridDim = 0;
    do { ++UVGridDim; } while (UVGridDim * UVGridDim < n_components);
    Eigen::VectorXi bnd_stacked;
    Eigen::MatrixXd bnd_uv_stacked;
    for (int componentI = 0; componentI < n_components; ++componentI) {
        std::vector<std::vector<int>> bnd_all;
        igl::boundary_loop(F_component[componentI], bnd_all);
        if (bnd_all.empty()) return fail("a component has no boundary after cutting");
        int longest = 0;
        for (int b = 1; b < (int)bnd_all.size(); ++b)
            if (bnd_all[longest].size() < bnd_all[b].size()) longest = b;
        const int nb = (int)bnd_all[longest].size();
        bnd_stacked.conservativeResize(bnd_stacked.size() + nb);
        bnd_stacked.tail(nb) = Eigen::VectorXi::Map(bnd_all[longest].data(), nb);
        Eigen::MatrixXd bnd_uv;
        igl::map_vertices_to_circle(temp.V_rest, Eigen::VectorXi(bnd_stacked.tail(nb)), bnd_uv);
        const double xOffset = componentI % UVGridDim * 2.1, yOffset = componentI / UVGridDim * 2.1;
        bnd_uv.col(0).array() += xOffset;
        bnd_uv.col(1).array() += yOffset;
        bnd_uv_stacked.conservativeResize(bnd_uv_stacked.rows() + bnd_uv.rows(), 2);
        bnd_uv_stacked.bottomRows(bnd_uv.rows()) = bnd_uv;
    }
    oc_phase("Tutte map");
    Eigen::MatrixXd UV_Tutte;
    Eigen::SparseMatrix<double> A, M;
    OptCuts::IglUtils::computeUniformLaplacian(temp.F, A);
    if (!igl::harmonic(A, M, bnd_stacked, bnd_uv_stacked, 1, UV_Tutte)) return fail("the initial (Tutte) map could not be solved");
    r.triSoup0 = new OptCuts::TriMesh(r.V, r.F, UV_Tutte, temp.F, false);
    if (!r.triSoup0->checkInversion(true)) return fail("the initial (Tutte) map has flipped triangles - is the mesh consistently oriented?");
    return true;
}

double nowDistortion(const Run& r) {
    return r.optimizer ? r.optimizer->getLastEnergyVal(true) / r.energyParams[0] : 0.0;
}

}  // namespace

// ------------------------------------------------------------------ exports
OC_EXPORT(oc_alloc) void* oc_alloc(int bytes) { return std::malloc((size_t)(bytes > 0 ? bytes : 1)); }
OC_EXPORT(oc_free) void oc_free(void* p) { std::free(p); }
OC_EXPORT(oc_error) const char* oc_error() { return gError; }
OC_EXPORT(oc_phase_name) const char* oc_phase_name() { return gPhase; }

OC_EXPORT(oc_reset) void oc_reset() {
    delete R;
    R = nullptr;
    energyChanges_bSplit.clear(); energyChanges_iSplit.clear(); energyChanges_merge.clear();
    paths_bSplit.clear(); paths_iSplit.clear(); paths_merge.clear();
    newVertPoses_bSplit.clear(); newVertPoses_iSplit.clear(); newVertPoses_merge.clear();
    filterExp_in = 0.6;
    inSplitTotalAmt = 0;
    oc_phase("idle");
}

/** pos: nv xyz floats; tris: nt*3 vertex ids (triangles, consistently oriented, manifold).
 *  seams/nseams: optional seam edges as vertex-id pairs (used when initialCut == 1).
 *  initialCut: 0 OptCuts' one-point cut, 1 cut along `seams` first (then OptCuts' cut for anything that is
 *  still not a disk), 2 OptCuts' farthest-point cut. maxIterations: Newton steps in total (0 = no limit);
 *  timeBudgetMs: whole run, measured from oc_init (0 = no limit). Returns 1, or 0 (oc_error says why). */
OC_EXPORT(oc_init) int oc_init(const float* pos, int nv, const int* tris, int nt, const int* seams, int nseams,
                               double distortionBound, double lambdaInit, int useBijectivity, int initialCut,
                               int maxIterations, double timeBudgetMs, unsigned seed) {
    oc_reset();
    gError[0] = 0;
    std::cout.setstate(std::ios::badbit);  // OptCuts prints a lot; keep the console quiet
    R = new Run();
    Run& r = *R;
    r.startMs = nowMs();
    if (!(distortionBound > 4.0) || !std::isfinite(distortionBound)) return fail("distortionBound must be a number above 4 (4 is a perfect isometry)"), 0;
    if (!(lambdaInit > 0.0 && lambdaInit < 1.0)) return fail("lambdaInit must be between 0 and 1"), 0;
    if (initialCut < 0 || initialCut > 2) return fail("initialCut must be 0, 1 or 2"), 0;
    r.upperBound = distortionBound;
    r.lambdaInit = lambdaInit;
    r.bijectiveParam = useBijectivity != 0;
    r.initCutOption = initialCut;
    r.maxIterations = std::max(0, maxIterations);
    r.timeBudgetMs = timeBudgetMs > 0 ? timeBudgetMs : 0;
    r.seed = seed;
    oc_phase("checking the mesh");
    if (!loadMesh(r, pos, nv, tris, nt)) { r.phase = P_ERROR; return 0; }

    std::set<std::pair<int, int>> seamSet;
    if (initialCut == 1 && seams && nseams > 0) {
        std::vector<int> map(nv, -1);
        for (int i = 0; i < (int)r.compactToInput.size(); ++i) map[r.compactToInput[i]] = i;
        for (int s = 0; s < nseams; ++s) {
            int a = seams[2 * s], b = seams[2 * s + 1];
            if (a < 0 || b < 0 || a >= nv || b >= nv || map[a] < 0 || map[b] < 0) { fail("a seam uses a vertex that is not in the mesh"); r.phase = P_ERROR; return 0; }
            a = map[a]; b = map[b];
            seamSet.insert({std::min(a, b), std::max(a, b)});
        }
    }
    if (!initialUV(r, seamSet)) { r.phase = P_ERROR; return 0; }

    oc_phase("setting up the optimizer");
    r.energyParams.push_back(1.0 - lambdaInit);
    r.energyTerms.push_back(new OptCuts::SymDirichletEnergy());
    // as main.cpp: for the one-point initial cut the scaffold (bijectivity) starts after the first solve
    r.optimizer = new OptCuts::Optimizer(*r.triSoup0, r.energyTerms, r.energyParams, 0, true,
                                         r.bijectiveParam && !r.rand1PInitCut);
    r.optimizer->precompute();
    r.phase = P_OPT;
    r.converged = 0;
    return 1;
}

/** Run up to `units` units of work, at most `sliceMs` ms (0 = no slice limit). 0 running, 1 finished, -1 error. */
OC_EXPORT(oc_step) int oc_step(int units, double sliceMs) {
    if (!R || R->phase == P_ERROR || R->phase == P_IDLE) return -1;
    Run& r = *R;
    const double t0 = nowMs();
    for (int u = 0; u < std::max(1, units) && r.phase != P_DONE; ++u) {
        if ((r.maxIterations && r.iterNum >= r.maxIterations) ||
            (r.timeBudgetMs && nowMs() - r.startMs >= r.timeBudgetMs)) {
            r.budgetHit = true;
            r.phase = P_DONE;
            break;
        }
        stepUnit(r);
        if (sliceMs > 0 && nowMs() - t0 >= sliceMs) break;
    }
    return r.phase == P_DONE ? 1 : 0;
}

OC_EXPORT(oc_iterations) int oc_iterations() { return R ? R->iterNum : 0; }
OC_EXPORT(oc_topology_ops) int oc_topology_ops() { return R ? R->topoOps : 0; }
OC_EXPORT(oc_distortion) double oc_distortion() { return R ? nowDistortion(*R) : 0.0; }
OC_EXPORT(oc_lambda) double oc_lambda() { return R && !R->energyParams.empty() ? 1.0 - R->energyParams[0] : 0.0; }

/** Build the result. When the run stopped early (budget) and the current map breaks the bound, the best
 *  feasible map seen so far (OptCuts keeps it for its own roll-backs) is returned instead, if there is one. */
OC_EXPORT(oc_finish) int oc_finish() {
    if (!R || !R->optimizer) return 0;
    Run& r = *R;
    oc_phase("result");
    if (r.budgetHit && nowDistortion(r) > r.upperBound && r.iterNum_bestFeasible >= 0)
        r.optimizer->setConfig(r.triSoup_bestFeasible, r.iterNum, r.optimizer->getTopoIter());
    const OptCuts::TriMesh& res = r.optimizer->getResult();
    const int nt = (int)res.F.rows();
    // compact UV vertices (only those triangles use)
    std::vector<int> remap(res.V.rows(), -1);
    r.uv.clear();
    r.cornerUV.assign(nt * 3, -1);
    for (int t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k) {
            int v = res.F(t, k);
            if (remap[v] < 0) { remap[v] = (int)(r.uv.size() / 2); r.uv.push_back((float)res.V(v, 0)); r.uv.push_back((float)res.V(v, 1)); }
            r.cornerUV[t * 3 + k] = remap[v];
        }
    // seams: input edges whose two triangles disagree on a UV vertex at either end
    std::map<std::pair<int, int>, std::pair<int, int>> edgeFaces;  // undirected -> (face, face)
    for (int t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k) {
            int a = r.F(t, k), b = r.F(t, (k + 1) % 3);
            auto key = std::make_pair(std::min(a, b), std::max(a, b));
            auto it = edgeFaces.find(key);
            if (it == edgeFaces.end()) edgeFaces[key] = {t, -1};
            else it->second.second = t;
        }
    auto uvAt = [&](int t, int v) { for (int k = 0; k < 3; ++k) if (r.F(t, k) == v) return r.cornerUV[t * 3 + k]; return -1; };
    r.seams.clear();
    r.seamLength = 0;
    for (const auto& e : edgeFaces) {
        const int t0 = e.second.first, t1 = e.second.second;
        if (t1 < 0) continue;
        const int a = e.first.first, b = e.first.second;
        if (uvAt(t0, a) != uvAt(t1, a) || uvAt(t0, b) != uvAt(t1, b)) {
            r.seams.push_back(r.compactToInput[a]);
            r.seams.push_back(r.compactToInput[b]);
            r.seamLength += (r.V.row(a) - r.V.row(b)).norm();
        }
    }
    OptCuts::SymDirichletEnergy SD;
    SD.computeEnergyVal(res, r.distortion);
    r.flipped = 0;
    for (int t = 0; t < nt; ++t) if (!res.checkInversion(t, true)) r.flipped++;
    oc_phase("done");
    return 1;
}

OC_EXPORT(oc_uv_count) int oc_uv_count() { return R ? (int)R->uv.size() / 2 : 0; }
OC_EXPORT(oc_uv) const float* oc_uv() { return R ? R->uv.data() : nullptr; }
OC_EXPORT(oc_corner_uv) const int* oc_corner_uv() { return R ? R->cornerUV.data() : nullptr; }
OC_EXPORT(oc_corner_count) int oc_corner_count() { return R ? (int)R->cornerUV.size() : 0; }
OC_EXPORT(oc_seam_count) int oc_seam_count() { return R ? (int)R->seams.size() / 2 : 0; }
OC_EXPORT(oc_seams) const int* oc_seams() { return R ? R->seams.data() : nullptr; }
OC_EXPORT(oc_seam_length) double oc_seam_length() { return R ? R->seamLength : 0.0; }
OC_EXPORT(oc_result_distortion) double oc_result_distortion() { return R ? R->distortion : 0.0; }
OC_EXPORT(oc_flipped) int oc_flipped() { return R ? R->flipped : 0; }
/** 1 when OptCuts finished on its own (its convergence test), 0 when the iteration/time budget stopped it. */
OC_EXPORT(oc_converged) int oc_converged() { return R && R->outerConverged && !R->budgetHit ? 1 : 0; }
