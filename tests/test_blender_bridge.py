"""LOKI <-> Blender (owner 2026-10-26: "fix it properly ... come up with a solution for the unexpected ... make it work i
dont wanna be coming back to blender"). Off Blender, against tests/fixtures/fake_bpy.py:
  the loader     its timer never dies; it hot-reloads the core when the file changes; a broken core (load or start)
                 is logged and the running one kept; status.json says alive + the error
  the core       inbox jobs one per tick, answers written whole; python jobs run in the window + 3D view context in
                 their OWN scene and the owner's scene comes back; print output and `result` returned; a failing
                 command stops the job with its traceback; the watchdog turns the MCP add-on back on when something
                 switched it off (the PC, 2026-10-26) and starts the socket; mcp_off is respected; the add-on's
                 execute_code is wrapped in the context; unknown commands go to the add-on
  blender_link   setup copies all three files via Blender itself; run() uses the open window when its loader is
                 alive, else a background Blender, and falls back when the window closes before taking the job;
                 build_render_export / proof / the agents' tool
  the scripts    campfire.py and every script parse; the campfire builds in the fake (no bpy.ops, no deletes outside
                 its scene)

    python tests/test_blender_bridge.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "engine" / "blender_scripts"
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "tests" / "fixtures"))
TMP = Path(tempfile.mkdtemp(prefix="loki-blender-bridge-"))
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %r" % (detail,)))


import fake_bpy  # noqa: E402

# ------------------------------------------------------------------ every script parses
for f in sorted(SCRIPTS.glob("*.py")):
    try:
        ast.parse(f.read_text(encoding="utf-8"))
        check("parses: %s" % f.name, True)
    except SyntaxError as exc:
        check("parses: %s" % f.name, False, exc)

# ------------------------------------------------------------------ the loader
bpy = fake_bpy.install()
ROOT = TMP / "home" / "blender"
CORE = TMP / "scripts" / "loki" / "loki_blender_core.py"
CORE.parent.mkdir(parents=True)
CORE.write_text((SCRIPTS / "loki_blender_core.py").read_text(encoding="utf-8"), encoding="utf-8")
os.environ["LOKI_BLENDER_CORE"] = str(CORE)
os.environ["LOKI_BLENDER_INBOX"] = str(ROOT)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


loader = load(SCRIPTS / "loki_blender_startup.py", "loki_blender")
loader.register()
tick = lambda n=1: [bpy.app.timers.run_all() for _ in range(n)]   # noqa: E731
tick()
st = json.loads((ROOT / "status.json").read_text())
check("loader: core loaded, status.json alive with the core's version", st["alive"] and st["core"] and not st["core_error"], st)
check("loader: the MCP add-on is on and its socket up after start", st.get("mcp_socket") is True, st)
first_core = loader.STATE["core"]

CORE.write_text("this is not python(", encoding="utf-8")
os.utime(CORE, (time.time() + 5,) * 2)
tick()
check("loader: a core with a syntax error is not loaded - the running one stays", loader.STATE["core"] is first_core
      and "SyntaxError" in loader.STATE["error"], loader.STATE["error"][-200:])
check("loader: its timer survived the broken core", bpy.app.timers.is_registered(loader._tick))
tick(3)
st = json.loads((ROOT / "status.json").read_text())
check("loader: status.json shows the core error", "SyntaxError" in st["core_error"], st["core_error"][-120:])

CORE.write_text("VERSION='x'\ndef start(log, root):\n    raise RuntimeError('boom')\ndef stop(): pass\ndef tick(): pass\n",
                encoding="utf-8")
os.utime(CORE, (time.time() + 10,) * 2)
tick()
check("loader: a core whose start() fails is not used - the old one is restarted", loader.STATE["core"] is first_core
      and "boom" in loader.STATE["error"])

good = (SCRIPTS / "loki_blender_core.py").read_text(encoding="utf-8").replace('VERSION = "', 'VERSION = "hot-')
CORE.write_text(good, encoding="utf-8")
os.utime(CORE, (time.time() + 15,) * 2)
tick()
check("loader: writing a fixed core is enough - it is hot-reloaded, no restart", loader.STATE["core"] is not first_core
      and loader.STATE["core"].VERSION.startswith("hot-") and not loader.STATE["error"], loader.STATE["error"])

bad_tick_core = loader.STATE["core"]
orig_tick = bad_tick_core.tick
bad_tick_core.tick = lambda: 1 / 0
tick(2)
check("loader: a core whose tick() raises does not kill the timer", bpy.app.timers.is_registered(loader._tick))
bad_tick_core.tick = orig_tick
core = loader.STATE["core"]

# ------------------------------------------------------------------ the core: jobs
inbox, outbox = ROOT / "inbox", ROOT / "outbox"


def job(name, commands, age=5):
    p = inbox / (name + ".json")
    p.write_text(json.dumps(commands), encoding="utf-8")
    os.utime(p, (time.time() - age,) * 2)
    return p


def answer(name):
    return json.loads((outbox / (name + ".json")).read_text())


owner_scene = bpy.win.scene
job("a1", [{"type": "ping"},
           {"type": "python", "params": {"scene": "LOKI Test", "code":
            "print('hello from', scene.name)\nimport bpy\nresult = {'ctx': bpy.context.scene.name, "
            "'has_area': 'area' in bpy.context.overrides[-1], 'win_scene': bpy.win.scene.name}"}}])
job("a2", [{"type": "ping"}])
tick()
check("one job per tick", (outbox / "a1.json").is_file() and not (outbox / "a2.json").exists())
a = answer("a1")
r = a["results"][1]["result"] if a.get("ok") else a
check("python job: print output and `result` come back", a["ok"] and "hello from LOKI Test" in r["stdout"], a)
check("python job: runs in its OWN scene, inside a window + 3D-view context", r["result"]["ctx"] == "LOKI Test"
      and r["result"]["has_area"] and r["result"]["win_scene"] == "LOKI Test", r)
check("the owner's scene is back in the window afterwards", bpy.win.scene is owner_scene, bpy.win.scene.name)
check("the job file moves to done/", (ROOT / "done" / "a1.json").is_file() and not (inbox / "a1.json").exists())
tick()
check("the next tick takes the next job", (outbox / "a2.json").is_file())

job("young", [{"type": "ping"}], age=0)
tick()
check("a job still being written (under 1 s old) waits", not (outbox / "young.json").exists())
os.utime(inbox / "young.json", (time.time() - 5,) * 2)
tick()

job("err", [{"type": "python", "params": {"code": "x = 1\nraise ValueError('nope')"}}, {"type": "ping"}])
tick()
e = answer("err")
check("a failing command: the job says why, with its traceback, and stops there", not e["ok"] and len(e["results"]) == 1
      and "ValueError: nope" in e["results"][0]["message"] and "Traceback" in e["results"][0]["traceback"], e)
check("... and the owner's scene is still back", bpy.win.scene is owner_scene)

# render / export / scene_info in the job's scene
png, glb, blend = TMP / "out" / "x.png", TMP / "out" / "x.glb", TMP / "out" / "x.blend"
job("rx", [{"type": "python", "params": {"scene": "R", "code": "import types\nscene.camera = types.SimpleNamespace(name='Cam')"}},
           {"type": "render", "params": {"scene": "R", "path": str(png)}},
           {"type": "export", "params": {"scene": "R", "path": str(glb)}},
           {"type": "export", "params": {"scene": "R", "path": str(blend)}},
           {"type": "scene_info", "params": {"scene": "R"}}])
tick()
rx = answer("rx")
check("render + export (.glb, .blend) + scene_info", rx["ok"] and png.is_file() and glb.is_file() and blend.is_file(), rx)
job("nocam", [{"type": "render", "params": {"scene": "Empty", "path": str(TMP / "out" / "n.png")}}])
tick()
check("render without a camera says so", "has no camera" in answer("nocam")["results"][0]["message"])

# ------------------------------------------------------------------ the watchdog (the PC: add-on switched off between jobs)
sys.modules["blender_mcp"].unregister()
check("(the add-on is off now, like on the PC)", not hasattr(bpy.types.Scene, "blendermcp_port"))
core._S["last_watch"] = 0
tick()
check("watchdog: turns the add-on back on", hasattr(bpy.types.Scene, "blendermcp_port"))
check("watchdog: and the socket is up again", bpy.types.blendermcp_server.running)
job("addon", [{"type": "get_viewport_screenshot", "params": {}}])
sys.modules["blender_mcp"].unregister()
tick()
check("an add-on command right after the add-on went off still works (watchdog runs first)", answer("addon")["ok"], answer("addon"))

sys.modules["addon_utils"].fail = True
sys.modules["blender_mcp"].unregister()
core._S["last_watch"] = 0
tick()
check("watchdog: if addon_utils.enable fails (restricted), it registers the add-on itself",
      hasattr(bpy.types.Scene, "blendermcp_port"))
sys.modules["addon_utils"].fail = False

(ROOT / "mcp_off").write_text("")
sys.modules["blender_mcp"].unregister()
core._S["last_watch"] = 0
tick()
check("watchdog: blender/mcp_off leaves the add-on off (the owner's choice wins)", not hasattr(bpy.types.Scene, "blendermcp_port"))
(ROOT / "mcp_off").unlink()
core._S["last_watch"] = 0
tick()

srv = bpy.types.blendermcp_server
out = srv.execute_code("x")
check("the add-on's execute_code (what MCP clients call) runs in the window + 3D-view context",
      out["override"] and "area" in out["override"] and "window" in out["override"], out)

# ------------------------------------------------------------------ the campfire, in the fake
bmesh = types.ModuleType("bmesh")
made = []
bmesh.new = lambda: types.SimpleNamespace(to_mesh=lambda me: None, free=lambda: None)
bmesh.ops = types.SimpleNamespace(create_cone=lambda bm, **k: made.append("cone"), create_icosphere=lambda bm, **k: made.append("ico"))
sys.modules["bmesh"] = bmesh
mathutils = types.ModuleType("mathutils")


class V(tuple):
    def __new__(cls, t):
        return tuple.__new__(cls, t)

    def __sub__(self, o):
        return V(tuple(a - b for a, b in zip(self, o)))

    def to_track_quat(self, *a):
        return types.SimpleNamespace(to_euler=lambda: (0, 0, 0))


mathutils.Vector = V
sys.modules["mathutils"] = mathutils


def mk(name, *a):
    return types.SimpleNamespace(name=name, use_nodes=True, materials=[], diffuse_color=None, energy=0, color=None,
                                 polygons=[], node_tree=types.SimpleNamespace(nodes={
                                     "Principled BSDF": types.SimpleNamespace(inputs={k: types.SimpleNamespace(default_value=None) for k in
                                                                                      ("Base Color", "Roughness", "Emission Color", "Emission Strength")}),
                                     "Background": types.SimpleNamespace(inputs=[types.SimpleNamespace(default_value=None)])}))


coll = types.SimpleNamespace(get=lambda n: None, new=mk)
removed = []
bpy.data.materials = bpy.data.meshes = bpy.data.lights = bpy.data.cameras = bpy.data.worlds = coll


class O(types.SimpleNamespace):
    pass


def new_obj(name, data):
    o = O(name=name, data=data, location=None, rotation_euler=None, scale=None, parent=None)
    o.type = "MESH" if data is not None and hasattr(data, "polygons") and name not in ("Camera",) and "LOKI " not in getattr(data, "name", "") else "OTHER"
    return o


bpy.data.objects = types.SimpleNamespace(new=new_obj, remove=lambda o, do_unlink=True: removed.append(o.name))
job("camp", [{"type": "python", "params": {"scene": "LOKI Campfire", "code": (SCRIPTS / "campfire.py").read_text(encoding="utf-8")}},
             {"type": "scene_info", "params": {"scene": "LOKI Campfire"}}])
tick()
c = answer("camp")
info = c["results"][1]["result"] if c.get("ok") else {}
check("campfire builds (fake bpy): ground, 9 stones, 5 logs, 3 flames, 2 lights, a camera", c["ok"]
      and made.count("ico") == 9 and made.count("cone") == 9 and info.get("objects", 0) >= 21, (c.get("results") or c)[:1])
check("campfire sets its own scene's camera, not the owner's", bpy.data.scenes.get("LOKI Campfire").camera is not None
      and owner_scene.camera is None)
job("camp2", [{"type": "python", "params": {"scene": "LOKI Campfire", "code": (SCRIPTS / "campfire.py").read_text(encoding="utf-8")}}])
owner_scene.collection.objects.link(O(name="OwnersSculpt", type="MESH"))
tick()
check("running it again clears only its own scene - the owner's objects are never removed",
      "OwnersSculpt" not in removed and len(removed) >= 21, removed[:3])
loader.unregister()

# ------------------------------------------------------------------ blender_link: setup, run (window / background), tool
import blender_link  # noqa: E402

calls = []
fake_blender = TMP / "blender.exe"
fake_blender.write_text("")
os.environ["LOKI_BLENDER"] = str(fake_blender)


def fake_setup_run(argv, **kw):
    calls.append(argv)
    expr = argv[argv.index("--python-expr") + 1]
    return types.SimpleNamespace(returncode=0, stdout="LOKI_BLENDER_SCRIPTS %s\nLOKI_BLENDER_ADDON_OK (True, True)\n" % TMP, stderr="")


res = blender_link.setup(run=fake_setup_run)
a = calls[-1]
files = a[a.index("--") + 1:]
expr = a[a.index("--python-expr") + 1]
check("setup: Blender itself copies the add-on, the loader and the core into its own scripts folder",
      res["ok"] and [Path(x).name for x in files] == ["addon.py", "loki_blender_startup.py", "loki_blender_core.py"]
      and all(s in expr for s in ("'addons'", "'startup'", "'loki'", "user_resource('SCRIPTS'")), (res, files))
check("setup: background, no window; the add-on is enabled and saved", "--background" in a and "addon_utils.enable" in expr
      and "save_userpref" in expr)

# run(): a window is alive -> the inbox; a background Blender otherwise
ROOT2 = TMP / "home2" / "blender"
os.environ["LOKI_BLENDER_INBOX"] = str(ROOT2)
(ROOT2 / "inbox").mkdir(parents=True)


def fake_window(stop):
    while not stop.is_set():
        (ROOT2 / "status.json").write_text(json.dumps({"alive": True, "background": False, "at": time.time()}))
        for p in (ROOT2 / "inbox").glob("*.json"):
            (ROOT2 / "outbox").mkdir(exist_ok=True)
            (ROOT2 / "outbox" / p.name).write_text(json.dumps({"ok": True, "results": [], "mode": "window"}))
            p.unlink()
        time.sleep(0.1)


stop = threading.Event()
th = threading.Thread(target=fake_window, args=(stop,), daemon=True)
th.start()
time.sleep(0.2)
bg = []
r = blender_link.run([{"type": "ping"}], name="w", run_proc=lambda *a, **k: bg.append(a), timeout=5)
check("run(): a live Blender window takes the job through its inbox", r.get("ok") and r.get("via") == "window" and not bg, r)
stop.set()
th.join()
(ROOT2 / "status.json").write_text(json.dumps({"alive": True, "background": False, "at": time.time() - 999}))


def fake_bg(argv, **kw):
    bg.append(argv)
    ans = Path(argv[-1])
    ans.write_text(json.dumps({"ok": True, "results": [{"status": "success"}], "mode": "background"}))
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


r = blender_link.run([{"type": "ping"}], name="b", run_proc=fake_bg, timeout=5)
check("run(): no live window -> a background Blender with the runner and the same core", r.get("ok")
      and r.get("via") == "background" and bg[-1][1:4] == ["--background", "--factory-startup", "--python"]
      and Path(bg[-1][4]).name == "run_job.py" and Path(bg[-1][6]).name == "loki_blender_core.py", (r, bg[-1] if bg else None))

# the window closes before it takes the job -> background instead, the stale job is removed
(ROOT2 / "status.json").write_text(json.dumps({"alive": True, "background": False, "at": time.time()}))
t_close = threading.Timer(0.6, lambda: (ROOT2 / "status.json").write_text(json.dumps({"alive": True, "background": False,
                                                                                       "at": time.time() - 999})))
t_close.start()
n = len(bg)
r = blender_link.run([{"type": "ping"}], name="c", run_proc=fake_bg, timeout=5)
t_close.join()
check("run(): the window closed before taking the job -> it runs in the background, no stale job left",
      r.get("via") == "background" and len(bg) == n + 1 and not list((ROOT2 / "inbox").glob("c-*.json")), r)

r = blender_link.run([{"type": "ping"}], name="none", run_proc=lambda argv, **k: types.SimpleNamespace(returncode=1, stdout="crash", stderr=""), timeout=5)
check("run(): a background Blender that dies says so with its log", not r["ok"] and "no answer" in r["error"] and "crash" in r["log"], r)

# build_render_export / proof / the agents' tool
seen = []


def fake_bg2(argv, **kw):
    cmds = json.loads(Path(argv[-2]).read_text())
    seen.append(cmds)
    for c in cmds:
        if c["type"] in ("render", "export"):
            Path(c["params"]["path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(c["params"]["path"]).write_bytes(b"x")
    Path(argv[-1]).write_text(json.dumps({"ok": True, "results": []}))
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


pr = blender_link.proof(TMP / "ws", run_proc=fake_bg2)
cmds = seen[-1]
check("proof: build in its own scene -> scene_info -> render -> export .glb + .blend",
      [c["type"] for c in cmds] == ["python", "scene_info", "render", "export", "export"]
      and {c["params"].get("scene") for c in cmds} == {"LOKI Campfire"}, [c["type"] for c in cmds])
check("proof: renders/ and models/, named by out_names", Path(pr["files"]["render"]).parent.name == "renders"
      and Path(pr["files"]["render"]).name.startswith("campfire-blender_")
      and [Path(m).suffix for m in pr["files"]["models"]] == [".glb", ".blend"], pr["files"])
t = blender_link.tool({"action": "make", "name": "low poly tree", "code": "result = 1"}, TMP / "ws", ) if False else None
blender_link.run.__defaults__  # noqa: B018
orig_run = blender_link.run
blender_link.run = lambda commands, name="", **kw: orig_run(commands, name, run_proc=fake_bg2, **kw)
t = blender_link.tool({"action": "make", "name": "low poly tree", "code": "result = 1"}, TMP / "ws")
check("tool make: renders + exports and lists what it made", t.get("ok") and len(t.get("made", [])) == 3
      and all(Path(p).is_file() for p in t["made"]), t)
check("tool make without code says what is missing", "code" in blender_link.tool({"action": "make"}, TMP)["error"])
blender_link.run = orig_run
import make_mcp  # noqa: E402
check("LOKI's agents have the blender tool", any(x.get("name") == "blender" for x in make_mcp.TOOLS))

check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
