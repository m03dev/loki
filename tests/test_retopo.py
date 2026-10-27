"""Workable topology (owner 2026-10-26: "the entire point of blender is so it can edit the mesh and make em workable ...
i need the models to be improved with working topology"). Off Blender: Blender's QuadriFlow pre-check (replica of
object_remesh.cc mesh_is_manifold_consistent, incl. the 1e-4 short-edge test that blocked the PC's voxel mesh), the
Instant Meshes OBJ round trip, the polish chain with retopo (no decimate after the quads, normal map baked), the topology
summary Forge / Home show, and /forge/finish asking for quads. The real runs are on the PC (Blender 5.2.3).

    python tests/test_retopo.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "tests" / "fixtures"))
TMP = Path(tempfile.mkdtemp(prefix="loki-retopo-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_COMFY_AUTOSTART"] = "0"
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import fake_bpy  # noqa: E402

fake_bpy.install()
spec = importlib.util.spec_from_file_location("loki_core_retopo", REPO / "engine" / "blender_scripts" / "loki_blender_core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def V(x, y, z):
    return types.SimpleNamespace(co=types.SimpleNamespace(x=x, y=y, z=z, __iter__=None))


def mesh(verts, faces):
    """A tiny bpy-like mesh: vertices[i].co, edges[i].vertices, loops (vertex_index, edge_index) in face order."""
    edges, index, loops = [], {}, []
    for f in faces:
        for i, v in enumerate(f):
            w = f[(i + 1) % len(f)]
            key = (min(v, w), max(v, w))
            if key not in index:
                index[key] = len(edges)
                edges.append(types.SimpleNamespace(vertices=key))
            loops.append(types.SimpleNamespace(vertex_index=v, edge_index=index[key]))
    return types.SimpleNamespace(vertices=[V(*p) for p in verts], edges=edges, loops=loops)


TET_V = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
TET_F = [(0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)]           # outward, consistent
r = core.qf_problems(mesh(TET_V, TET_F))
check("a closed, consistent mesh passes QuadriFlow's check", r["ok"], r)
r = core.qf_problems(mesh(TET_V, [(0, 1, 2)] + TET_F[1:]))
check("one face flipped against its neighbours -> 'flips' (QuadriFlow refuses it)", not r["ok"] and r["flips"] >= 1, r)
r = core.qf_problems(mesh(TET_V + [(0, 0, 0.00005)], TET_F + [(0, 4, 1)]))
check("an edge under 1e-4 on every axis -> 'short' (what blocked the PC's voxel mesh)", r["short"] >= 1 and not r["ok"], r)
fin = mesh(TET_V + [(1, 1, 1)], TET_F + [(0, 1, 4)])
check("an edge shared by three faces -> 'gt2'", core.qf_problems(fin)["gt2"] >= 1)
wire = mesh(TET_V, TET_F)
wire.edges.append(types.SimpleNamespace(vertices=(1, 3)))
wire.edges.append(types.SimpleNamespace(vertices=(0, 1)))
check("an edge with no face -> 'wire'", core.qf_problems(wire)["wire"] >= 1)

# Instant Meshes speaks OBJ
obj = TMP / "m.obj"
me = types.SimpleNamespace(vertices=[types.SimpleNamespace(co=p) for p in TET_V],
                           polygons=[types.SimpleNamespace(vertices=f) for f in TET_F])
core._obj_write(me, obj)
v, f = core._obj_read(obj)
check("OBJ out and back: same vertices and faces (1-based on disk)", v == [tuple(map(float, p)) for p in TET_V]
      and f == [list(x) for x in TET_F] and "f 1 3 2" in obj.read_text(), (v, f))
(TMP / "q.obj").write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvn 0 0 1\nf 1//1 2//1 3//1 4//1\n")
check("OBJ read takes 'i//n' faces (Instant Meshes writes normals)", core._obj_read(TMP / "q.obj")[1] == [[0, 1, 2, 3]])
calls = []


def fbx(**kw):
    calls.append(sorted(kw))
    if "use_active_scene" in kw:
        raise TypeError('Converting py args to operator properties: keyword "use_active_scene" unrecognized')
    return {"FINISHED"}


core._op(fbx, filepath="x.fbx", use_active_scene=True, embed_textures=True)
check("an option this Blender lacks is dropped, the rest kept (FBX lost embed_textures on the PC)",
      calls[-1] == ["embed_textures", "filepath"], calls)
check("repair drops floater OBJECTS too (the Mac's dragon had a stray cyan blob beside it)",
      "floaters that are whole OBJECTS" in src_core if (src_core := (REPO / "engine" / "blender_scripts" / "loki_blender_core.py").read_text()) else False)
check("retopo, topology and bake are core commands", {"retopo", "topology", "bake"} <= set(core.COMMANDS))
src = (REPO / "engine" / "blender_scripts" / "loki_blender_core.py").read_text(encoding="utf-8")
check("colour is baked as emission of Base Color (a DIFFUSE bake is black on metallic glTF - the PC)",
      'type="EMIT"' in src and "_emit_base_colour(high)" in src and 'type="DIFFUSE"' not in src)
check("the normal map is a Non-Color tangent-space bake wired through a Normal Map node",
      'normal_space="TANGENT"' in src and '"Non-Color"' in src and "ShaderNodeNormalMap" in src)

# ------------------------------------------------------------------ polish with retopo
import blender_link  # noqa: E402

seen = {}
topo = {"body": {"faces": 7260, "quad_pct": 100.0, "pole_pct": 4.2, "verdict": "quads"}}
ret = {"objects": {"body": {"how": "quadriflow", "quads": True}}, "quads": True}


def fake_run(cmds, name="", **kw):
    seen["cmds"] = cmds
    return {"ok": True, "results": [{"type": "retopo", "status": "success", "result": ret},
                                    {"type": "topology", "status": "success", "result": topo},
                                    {"type": "scene_info", "status": "success", "result": {"triangles": 14520}}]}


blender_link.run = fake_run
model = TMP / "ws" / "models" / "dragon_20261026-1400.glb"
model.parent.mkdir(parents=True)
model.write_bytes(b"glTF")
res = blender_link.polish(model, TMP / "ws", retopo=8000, turntable=0)
kinds = [c["type"] for c in seen["cmds"]]
check("polish(retopo): repair (no voxel of its own) -> retopo -> bake with a normal map -> uv -> topology, never decimate",
      kinds[:8] == ["clear", "import", "cleanup", "normalize", "repair", "retopo", "bake", "uv"]
      and "decimate" not in kinds and "topology" in kinds and seen["cmds"][4]["params"].get("remesh") is False
      and seen["cmds"][5]["params"]["faces"] == 8000 and seen["cmds"][6]["params"].get("normal") is True, kinds)
check("... the result says how workable it is", res.get("topology") == {"verdict": "quads", "faces": 7260, "quad_pct": 100.0,
                                                                          "pole_pct": 4.2, "retopo": "quadriflow"}, res.get("topology"))
side = json.loads((model.parent / ".meta" / (Path(res["files"]["models"][0]).name + ".json")).read_text())
check("... and the sidecar carries it (Forge's list, Home)", side.get("topology", {}).get("verdict") == "quads", side)
blob = TMP / "ws" / "models" / "golem_20261025-2226.glb"
blob.write_bytes(b"glTF")
(blob.parent / ".meta").mkdir(exist_ok=True)
(blob.parent / ".meta" / (blob.name + ".json")).write_text('{"backend": "lift"}')
seen.clear()
r = blender_link.polish(blob, TMP / "ws", retopo=8000)
check("a 'lift' silhouette draft is refused - polishing a blob only makes a cleaner blob (the Mac golem)",
      not r["ok"] and "lift" in r["error"] and "cmds" not in seen, r)
res = blender_link.polish(model, TMP / "ws", turntable=0)
check("polish without retopo keeps its decimate", "decimate" in [c["type"] for c in seen["cmds"]]
      and "retopo" not in [c["type"] for c in seen["cmds"]])
check("summary: the worst object decides", blender_link.topology_summary(
    {"a": {"faces": 100, "quad_pct": 100, "pole_pct": 2, "verdict": "quads"},
     "b": {"faces": 100, "quad_pct": 0, "pole_pct": 90, "verdict": "soup"}})["verdict"] == "soup")

# ------------------------------------------------------------------ Forge asks for quads
import forge3d  # noqa: E402
import forge_api  # noqa: E402


class St:
    class agent:  # noqa: N801
        WORKSPACE = TMP / "fws"


st = St()
models = forge_api.models_dir(st)
models.mkdir(parents=True, exist_ok=True)
(models / "imp.glb").write_bytes(b"glTF")
got = {}


def fake_polish(m, out_dir, name="", **kw):
    got.update(kw)
    return {"ok": False, "error": "stop here"}


blender_link.polish, blender_link.find_blender = fake_polish, lambda: "/x/blender"
forge_api.handle_post(st, "/forge/finish", json.dumps({"name": "imp.glb"}).encode(), thread=False)
check("Forge's Clean up retopologises by default (8000 quads)", got.get("retopo") == 8000, got)
got.clear()
forge_api.handle_post(st, "/forge/finish", json.dumps({"name": "imp.glb", "retopo": 0}).encode(), thread=False)
check("... retopo: 0 keeps the old clean-up (decimate only)", got.get("retopo") == 0, got)
got.clear()
forge3d.make_3d = lambda *a, **k: {"ok": True, "glb": str(models / "imp.glb"), "name": "imp.glb", "backend": "pixal3d"}
forge_api.handle_post(st, "/forge/make", json.dumps({"prompt": "a dragon"}).encode(), thread=False)
check("a new AI model is retopologised after it is made", got.get("retopo") == 8000, got)

# ------------------------------------------------------------------ the agents' skill pack + the 3D Finisher
import agents  # noqa: E402

cat = {s["id"]: s for s in agents.skills_catalog(agents.skill_roots(REPO, TMP / "data"))}
pack = ["blender-gameready", "gameready-cleanup", "gameready-retopo", "gameready-uv-bake", "gameready-qa"]
check("blender-gameready + its four stage skills are in the catalog", all(p in cat for p in pack), sorted(cat)[:5])
texts = {p: agents.skill_text(cat[p]) for p in pack if p in cat}
check("each skill fits the prompt budget (MAX_SKILL_CHARS) whole",
      all(0 < len((REPO / Path(cat[p]["path"]).relative_to(REPO)).read_text(encoding="utf-8")) <= agents.MAX_SKILL_CHARS
          for p in texts), {p: len(t) for p, t in texts.items()})
check("the router names the one call (polish retopo=) and the gates", "retopo=8000" in texts.get("blender-gameready", "")
      and "pole_pct" in texts.get("gameready-retopo", "") and "SHIP" in texts.get("gameready-qa", ""))
fin = next((a for a in agents.TEMPLATES if a["id"] == "3d-finisher"), None)
check("a 3D Finisher agent template carries the pack (OpenCode: it has LOKI's blender tool)",
      fin and fin["engine"] == "opencode" and agents.validate(fin)["skills"] == pack, fin)
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
