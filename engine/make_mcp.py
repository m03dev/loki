"""loki-make: LOKI's making tools for the agent (OpenCode) as a small MCP server over stdio.

Owner 2026-10-25 11:20: "i want them to make real things like art 3d models or paintings comic books novels real
websites". OpenCode (the agent, engine/opencode_engine.py) reads and writes files and runs a shell by itself; what it
cannot do on its own is draw a picture or make a 3D model. These tools give it LOKI's own makers, saved into the
folder the agent works in:

  make_image  {prompt, count 1-4, width, height, folder="images", negative}  LOKI's image runner (runners/imagegen.py):
              this machine's local model when installed (stable-diffusion.cpp on the PC, mflux on the Mac), else
              Z-Image / Qwen-Image / Pollinations - the same backends as the image specialist
  make_3d     {prompt | image, folder="models"}  forge3d.make_3d: a picture (or a description, drawn first) lifted to
              a .glb + .obj (TripoSR here, an online Space, or the offline inflate that always works); opens in Forge
  make_video  {prompt, seconds, image}  creative.make_video: Wan2GP on the PC, Higgsfield when its key is set

No package needed: MCP's stdio transport is JSON-RPC 2.0, one message per line (initialize, tools/list, tools/call).
Paths stay inside the agent's working folder (the process's cwd): a folder like "../x" is refused.

    python engine/make_mcp.py            (OpenCode starts it; opencode_engine.build_config adds it)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
VERSION = "1.0"

TOOLS = [
    {"name": "make_image",
     "description": "Draw a picture (art, a painting, a comic panel, a book cover, a concept, a texture) with LOKI's "
                    "image model and save it as a PNG in this folder (folder=, default images). Describe the picture "
                    "fully: subject, style (oil painting, ink comic, watercolour, pixel art ...), light, colours, "
                    "framing. count 1-4 makes variations. Returns the saved files.",
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string"}, "count": {"type": "integer", "minimum": 1, "maximum": 4},
         "width": {"type": "integer"}, "height": {"type": "integer"}, "folder": {"type": "string"},
         "negative": {"type": "string"}}, "required": ["prompt"]}},
    {"name": "make_3d",
     "description": "Make a 3D model (.glb and .obj) from a description (prompt=; LOKI draws it first) or from a "
                    "picture in this folder (image=). Saved in folder= (default models). It opens in LOKI's Forge to "
                    "look at, sculpt and export.",
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string"}, "image": {"type": "string"}, "folder": {"type": "string"}}}},
    {"name": "make_video",
     "description": "Make a short video clip (a few seconds) from a description, or animate a picture in this folder "
                    "(image=). Saved in videos/.",
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string"}, "seconds": {"type": "number"}, "image": {"type": "string"}},
         "required": ["prompt"]}},
]


def inside(base: Path, rel: str, default: str) -> Path:
    """A folder under the working folder; never outside it."""
    base = base.resolve()
    target = (base / (str(rel or "").strip() or default)).resolve()
    if target != base and base not in target.parents:
        raise ValueError("folder must be inside the working folder: %s" % rel)
    target.mkdir(parents=True, exist_ok=True)
    return target


def run_imagegen(job: dict, runner=subprocess.run) -> dict:
    proc = runner([sys.executable, str(HERE / "runners" / "imagegen.py")], input=json.dumps(job), capture_output=True,
                  text=True, timeout=1800, shell=False)
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    return json.loads(lines[-1]) if lines else {"ok": False, "error": (proc.stderr or "no answer")[-400:]}


def make_image(args: dict, cwd: Path, runner=subprocess.run) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "describe the picture (prompt)"}
    out = inside(cwd, args.get("folder", ""), "images")
    job = {"prompt": prompt[:1500], "out_dir": str(out), "count": max(1, min(int(args.get("count") or 1), 4)),
           "width": int(args.get("width") or 1024), "height": int(args.get("height") or 1024),
           "negative": str(args.get("negative") or "")[:600], "backend": os.environ.get("LOKI_IMAGE_BACKEND", "auto")}
    res = run_imagegen(job, runner)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "the picture was not made")}
    files = [str(Path(f).resolve()) for f in (res.get("files") or [res.get("file")]) if f]
    return {"ok": True, "files": [os.path.relpath(f, cwd) for f in files], "backend": res.get("backend", ""),
            "seed": res.get("seed")}


def make_3d(args: dict, cwd: Path, runner=subprocess.run, make=None) -> dict:
    prompt, image = str(args.get("prompt") or "").strip(), str(args.get("image") or "").strip()
    if not prompt and not image:
        return {"ok": False, "error": "give a description (prompt) or a picture (image)"}
    src = ""
    if image:
        p = (cwd / image).resolve()
        if cwd.resolve() not in p.parents or not p.is_file():
            return {"ok": False, "error": "no such picture in this folder: %s" % image}
        src = str(p)
    out = inside(cwd, args.get("folder", ""), "models")
    if make is None:
        import forge3d  # pylint: disable=import-outside-toplevel
        make = forge3d.make_3d

    def maker(text: str) -> str:
        res = run_imagegen({"prompt": text + ", a single object, centered, plain white background, full view, studio light",
                            "out_dir": str(inside(cwd, "images", "images")), "width": 1024, "height": 1024,
                            "backend": os.environ.get("LOKI_IMAGE_BACKEND", "auto")}, runner)
        if not res.get("ok"):
            raise RuntimeError("could not draw it first: %s" % res.get("error"))
        return str(res["file"])

    res = make(src, out, prompt, "auto", image_maker=maker)
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error", "the model was not made"))[:400]}
    files = [os.path.relpath(str(Path(f).resolve()), cwd) for f in (res.get("glb"), res.get("obj")) if f]
    return {"ok": True, "files": files, "backend": res.get("backend", ""),
            "triangles": (res.get("meta") or {}).get("triangles", 0)}


def make_video(args: dict, cwd: Path, make=None) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "describe the clip (prompt)"}
    if make is None:
        import creative  # pylint: disable=import-outside-toplevel
        make = creative.make_video
    res = make(prompt[:800], cwd, image=str(args.get("image") or ""), seconds=float(args.get("seconds") or 3.0))
    return res if isinstance(res, dict) else {"ok": False, "error": "no answer"}


def call(name: str, args: dict, cwd: Path) -> dict:
    fn = {"make_image": make_image, "make_3d": make_3d, "make_video": make_video}.get(name)
    if fn is None:
        return {"ok": False, "error": "no tool %s" % name}
    try:
        return fn(args or {}, cwd)
    except Exception as exc:  # noqa: BLE001 - a tool error is an answer, never a dead server
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}


def handle(msg: dict, cwd: Path) -> dict | None:
    """One JSON-RPC request -> its response (None for a notification)."""
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "loki-make", "version": VERSION}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params") or {}
        out = call(str(p.get("name", "")), p.get("arguments") or {}, cwd)
        result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": not out.get("ok")}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method " + method}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=sys.stdin, stdout=sys.stdout, cwd: Path | None = None) -> None:
    cwd = Path(cwd or os.getcwd())
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(msg, cwd) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
