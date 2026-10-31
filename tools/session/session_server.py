"""LOKI's live session: one interpreter that stays open for a job (plain Python, or Python inside Blender).

The driver starts it once per job and kind, then sends small pieces of code; variables, imports and the open scene stay
between calls - like an artist working step by step instead of re-running one big script. Protocol (stdin/stdout):
  in:  one JSON line per request  {"code": "..."}
  out: anything, then one line    \\x1eLOKI_DONE {"ok": true|false, "out": "<printed output and/or the error>"}
Inside Blender the helpers from scripts/loki_bpy.py are preloaded (look(), save(), frame(), lights() ...).
"""
import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.getcwd()
ns = {"__name__": "__loki_session__", "ROOT": ROOT}
sys.path.insert(0, os.path.join(ROOT, "scripts"))
try:
    import bpy  # noqa: F401  (only inside Blender)
    ns["os"] = os
    exec("from loki_bpy import *\nimport bpy, bmesh, math\nfrom mathutils import Vector, Matrix", ns)
    exec("""
def look(name='look', size=384):
    '''Render this scene from four sides into renders/<name>_views.png (adds camera and light if missing).'''
    import loki_bpy
    loki_bpy.ROOT = ROOT
    os.makedirs(os.path.join(ROOT, 'renders'), exist_ok=True)
    sc = bpy.context.scene
    if not sc.camera: frame()
    if not any(o.type == 'LIGHT' for o in sc.objects): lights()
    return views(name, size=size)

def save(path='scenes/scene.blend'):
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=p)
    return p

def scene():
    '''One line per object: name, type, size (m), location, material.'''
    out = []
    for o in bpy.context.scene.objects:
        d = tuple(round(v, 3) for v in o.dimensions); l = tuple(round(v, 3) for v in o.location)
        m = o.active_material.name if getattr(o, 'active_material', None) else '-'
        out.append(f'{o.name}: {o.type} size {d} at {l} mat {m}')
    print('\\n'.join(out) or '(empty scene)')
""", ns)
    import loki_bpy
    loki_bpy.ROOT = ROOT
except Exception:  # noqa: BLE001  plain Python, or Blender without the helpers
    pass

sys.stdout.write("\x1eLOKI_DONE " + json.dumps({"ok": True, "out": "session ready"}) + "\n")
sys.stdout.flush()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        code = json.loads(line).get("code", "")
    except ValueError:
        code = line
    buf = io.StringIO()
    ok = True
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            try:
                result = eval(compile(code, "<session>", "eval"), ns)   # a bare expression shows its value
                if result is not None:
                    print(repr(result))
            except SyntaxError:
                exec(compile(code, "<session>", "exec"), ns)
    except SystemExit:
        break
    except BaseException:  # noqa: BLE001
        ok = False
        buf.write(traceback.format_exc(limit=4))
    out = buf.getvalue()
    if len(out) > 6000:
        out = out[:2500] + "\n...\n" + out[-3000:]
    sys.stdout.write("\x1eLOKI_DONE " + json.dumps({"ok": ok, "out": out}) + "\n")
    sys.stdout.flush()
