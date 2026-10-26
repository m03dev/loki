"""A small stand-in for Blender's bpy, enough to test LOKI's loader / core / runner off Blender: timers you tick by
hand, a window with a scene and a 3D view, scenes, objects, context.temp_override, an add-on module you can switch
off (like the PC did), and addon_utils. Not a renderer: render/export write placeholder files."""
import contextlib
import sys
import types


class Timers:
    def __init__(self):
        self.fns = {}

    def register(self, fn, first_interval=0, persistent=False):
        self.fns[fn] = first_interval

    def is_registered(self, fn):
        return fn in self.fns

    def unregister(self, fn):
        self.fns.pop(fn, None)

    def run_all(self):
        """One pass: call every timer; one that returns None (or raises - like Blender) is removed."""
        for fn in list(self.fns):
            try:
                again = fn()
            except Exception:  # noqa: BLE001 - Blender prints it and drops the timer
                again = None
            if again is None:
                self.fns.pop(fn, None)


class Obj:
    def __init__(self, name, data=None):
        self.name, self.data = name, data
        self.type = "MESH" if data is not None and getattr(data, "polygons", None) is not None else "EMPTY"
        self.selected = False

    def select_set(self, state):
        self.selected = bool(state)

    def get(self, key, default=None):          # custom properties (o["loki_free_asset"])
        return getattr(self, "_props", {}).get(key, default)


class Coll:
    def __init__(self):
        self.objects = Linker()


class Linker(list):
    def link(self, o):
        self.append(o)


class Scene:
    def __init__(self, name):
        self.name, self.collection, self.camera = name, Coll(), None
        self.view_layers = [types.SimpleNamespace(name="ViewLayer", objects=types.SimpleNamespace(active=None))]
        self.render = types.SimpleNamespace(engine="BLENDER_EEVEE", filepath="", resolution_x=0, resolution_y=0,
                                            resolution_percentage=100, image_settings=types.SimpleNamespace(file_format=""))
        self.cycles = types.SimpleNamespace(samples=0, device="CPU")

    @property
    def objects(self):
        return list(self.collection.objects)


class Scenes(list):
    def get(self, name):
        return next((s for s in self if s.name == name), None)

    def new(self, name):
        s = Scene(name)
        self.append(s)
        return s


def install(background=False, version="5.2.3 LTS"):
    """Put a fresh fake bpy (+ addon_utils, blender_mcp) into sys.modules and return it."""
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(version_string=version, background=background, timers=Timers())
    scenes = Scenes([Scene("Scene")])
    bpy.data = types.SimpleNamespace(scenes=scenes, filepath="",
                                     objects=types.SimpleNamespace(remove=lambda o, do_unlink=True: None),
                                     libraries=types.SimpleNamespace(write=lambda path, ids, **kw: open(path, "wb").write(b"BLENDER")))
    area = types.SimpleNamespace(type="VIEW_3D", regions=[types.SimpleNamespace(type="WINDOW")])
    win = types.SimpleNamespace(scene=scenes[0], screen=types.SimpleNamespace(areas=[area]))
    ctx = types.SimpleNamespace(window_manager=types.SimpleNamespace(windows=[] if background else [win]),
                                overrides=[])
    ctx.scene = scenes[0]

    @contextlib.contextmanager
    def temp_override(**kw):
        ctx.overrides.append(kw)
        old = ctx.scene
        if "scene" in kw:
            ctx.scene = kw["scene"]
        try:
            yield
        finally:
            ctx.scene = old
            ctx.overrides.pop()
    ctx.temp_override = temp_override
    bpy.context = ctx
    bpy.win = win

    class SceneType:          # bpy.types.Scene - the add-on adds blendermcp_* here when registered
        pass
    bpy.types = types.SimpleNamespace(Scene=SceneType)

    def render(write_still=True, scene=""):
        sc = scenes.get(scene) or ctx.scene
        open(sc.render.filepath, "wb").write(b"\x89PNG fake")
    bpy.ops = types.SimpleNamespace(render=types.SimpleNamespace(render=render),
                                    export_scene=types.SimpleNamespace(gltf=lambda **kw: open(kw["filepath"], "wb").write(b"glTF"),
                                                                       fbx=lambda **kw: open(kw["filepath"], "wb").write(b"FBX")),
                                    wm=types.SimpleNamespace(obj_export=lambda **kw: open(kw["filepath"], "wb").write(b"o")))
    sys.modules["bpy"] = bpy

    # the MCP add-on: register() adds the Scene properties and the server class; unregister() takes them away
    mcp = types.ModuleType("blender_mcp")

    class Server:
        instances = []

        def __init__(self, port=9876):
            self.port, self.running = port, False
            Server.instances.append(self)

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

        def execute_code(self, code):
            return {"executed": True, "override": dict(ctx.overrides[-1]) if ctx.overrides else None}

        def execute_command(self, c):
            if not hasattr(SceneType, "blendermcp_use_polyhaven"):
                return {"status": "error", "message": "'Scene' object has no attribute 'blendermcp_use_polyhaven'"}
            if c.get("type") == "execute_code":
                return {"status": "success", "result": self.execute_code(c["params"]["code"])}
            return {"status": "success", "result": {"addon_command": c.get("type")}}
    mcp.BlenderMCPServer = Server

    def register():
        SceneType.blendermcp_use_polyhaven = False
        SceneType.blendermcp_port = 9876

    def unregister():
        for k in ("blendermcp_use_polyhaven", "blendermcp_port"):
            if hasattr(SceneType, k):
                delattr(SceneType, k)
        srv = getattr(bpy.types, "blendermcp_server", None)
        if srv:
            srv.stop()
    mcp.register, mcp.unregister = register, unregister
    sys.modules["blender_mcp"] = mcp

    au = types.ModuleType("addon_utils")
    au.enabled = set()
    au.fail = False

    def enable(name, default_set=True, persistent=True, handle_error=None):
        if au.fail:
            if handle_error:
                handle_error(RuntimeError("restricted"))
            return None
        au.enabled.add(name)
        register()
        return mcp
    au.enable = enable
    au.check = lambda name: (name in au.enabled, name in au.enabled and hasattr(SceneType, "blendermcp_port"))
    sys.modules["addon_utils"] = au
    sys.modules.pop("bmesh", None)
    return bpy
