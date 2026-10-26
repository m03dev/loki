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

SHELL_ON = {"on": False}
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
VERSION = "1.0"

TOOLS = [
    {"name": "make_image",
     "description": "Draw a picture (art, a painting, a comic panel, a book cover, concept art, a texture) with the "
                    "best image model this machine can reach (its own local model, Qwen-Image, FLUX on NVIDIA / "
                    "Hugging Face) and save it as a PNG in this folder (folder=, default images). Write the prompt "
                    "like an art director: subject and action, setting, composition and camera, light, palette, "
                    "mood, medium. style= adds a professional finish: " + ", ".join(sorted(__import__("art_direction").STYLES)) +
                    ". count 1-4 makes variations to choose from; upscale 2 or 4 enlarges the result with Real-ESRGAN "
                    "(print and cover quality). style pixel-art also makes the real pixel sprite (pixel_size=, default "
                    "64; palette= optional). Look at what you made before you call it done.",
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string"}, "style": {"type": "string"},
         "count": {"type": "integer", "minimum": 1, "maximum": 4},
         "width": {"type": "integer"}, "height": {"type": "integer"}, "folder": {"type": "string"},
         "negative": {"type": "string"}, "upscale": {"type": "integer", "enum": [2, 4]},
         "pixel_size": {"type": "integer"}, "palette": {"type": "string"}}, "required": ["prompt"]}},
    {"name": "pixelize",
     "description": "Turn a picture in this folder into real game pixel art (PixelOE's contrast-aware outlines + "
                    "per-patch downscale): size= the sprite's longer side in pixels (16-512, default 64), palette= "
                    "pico-8 | sweetie-16 | endesga-32 | gameboy | grayscale-4 | '#hex #hex ...', or colors= 2-256; "
                    "dither= none | floyd | bayer; outline= 0-4 (thickness of kept outlines); mode= contrast | center | "
                    "median | k-centroid | nearest. Transparent sprites stay transparent (hard edges). Saves "
                    "<name>-pixel<size>.png and an enlarged preview beside it.",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string"}, "size": {"type": "integer"}, "palette": {"type": "string"},
         "colors": {"type": "integer"}, "dither": {"type": "string", "enum": ["none", "floyd", "bayer"]},
         "outline": {"type": "integer"}, "mode": {"type": "string",
                                                   "enum": ["contrast", "center", "median", "k-centroid", "nearest"]}},
         "required": ["image"]}},
    __import__("voice_studio").TOOL,
    __import__("toolshelf").TOOL,
    __import__("comfy_jobs").MUSIC_TOOL,
    __import__("creations").LIBRARY_TOOL,
    __import__("render_agent").TOOL,
    {"name": "upscale_image",
     "description": "Enlarge a picture in this folder 2x or 4x with Real-ESRGAN (sharp detail, not blur); "
                    "anime=true for drawn / comic / anime art. Saves <name>-4x.png beside it.",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string"}, "scale": {"type": "integer", "enum": [2, 4]}, "anime": {"type": "boolean"}},
         "required": ["image"]}},
    {"name": "make_3d",
     "description": "Make a 3D model (.glb and .obj) from a description (prompt=; LOKI draws it first) or from a "
                    "picture in this folder (image=). Saved in folder= (default models). It opens in LOKI's Forge to "
                    "look at, sculpt and export. backend: auto (the best available: Pixal3D on the owner's ComfyUI "
                    "gives a fully textured model) | pixal3d | trellis2 | triposr | online | lift.",
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string"}, "image": {"type": "string"}, "folder": {"type": "string"},
         "backend": {"type": "string", "enum": ["auto", "pixal3d", "trellis2", "triposr", "online", "lift"]}}}},
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
    import art_direction  # pylint: disable=import-outside-toplevel
    style = str(args.get("style") or "")
    prompt, style_neg = art_direction.direct(prompt, style)
    negative = ", ".join(x for x in (str(args.get("negative") or "").strip(), style_neg) if x)
    job = {"prompt": prompt[:1800], "out_dir": str(out), "count": max(1, min(int(args.get("count") or 1), 4)),
           "width": int(args.get("width") or 1024), "height": int(args.get("height") or 1024),
           "negative": negative[:600], "backend": os.environ.get("LOKI_IMAGE_BACKEND", "auto")}
    res = run_imagegen(job, runner)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "the picture was not made")}
    files = [str(Path(f).resolve()) for f in (res.get("files") or [res.get("file")]) if f]
    answer = {"ok": True, "files": [os.path.relpath(f, cwd) for f in files], "backend": res.get("backend", ""),
              "model": res.get("model", ""), "seed": res.get("seed")}
    if res.get("backend") == "pollinations":
        answer["note"] = ("made by Pollinations, the weakest fallback - no better model was reachable (set an NVIDIA "
                          "key or HF_TOKEN in Settings, or install the local image model)")
    if style.lower() == "pixel-art" or args.get("pixel_size"):
        import pixel_art  # pylint: disable=import-outside-toplevel
        sprites = []
        for f in files:
            try:
                px = pixel_art.pixelize(f, size=int(args.get("pixel_size") or 64), palette=args.get("palette") or "")
                sprites.append(os.path.relpath(px["file"], cwd))
            except Exception as exc:  # noqa: BLE001 - the picture itself is still made
                answer["pixel_error"] = str(exc)[:200]
        answer["pixel_sprites"] = sprites
    if args.get("upscale"):
        anime = style.lower() in ("comic", "manga", "pixel-art")
        big = [art_direction.upscale(f, int(args["upscale"]), anime) for f in files]
        answer["upscaled"] = [os.path.relpath(b["file"], cwd) for b in big if b.get("ok")]
        if not answer["upscaled"]:
            answer["upscale_error"] = big[0].get("error", "") if big else ""
    return answer


def pixelize(args: dict, cwd: Path) -> dict:
    import pixel_art  # pylint: disable=import-outside-toplevel
    p = (cwd / str(args.get("image") or "")).resolve()
    if cwd.resolve() not in p.parents or not p.is_file():
        return {"ok": False, "error": "no such picture in this folder: %s" % args.get("image")}
    try:
        res = pixel_art.pixelize(p, size=int(args.get("size") or 64), outline=int(args.get("outline", 2) or 0),
                                 mode=str(args.get("mode") or "contrast"), colors=int(args.get("colors") or 0),
                                 palette=str(args.get("palette") or ""), dither=str(args.get("dither") or "none"))
    except pixel_art.PixelError as exc:
        return {"ok": False, "error": str(exc)}
    res["file"] = os.path.relpath(res["file"], cwd)
    res["preview"] = os.path.relpath(res["preview"], cwd)
    return res


def voice(args: dict, cwd: Path) -> dict:
    import voice_studio  # pylint: disable=import-outside-toplevel
    ask = None
    if str(args.get("action") or "") == "install":
        ask = lambda tool, details: ask_owner(tool, details)[0]  # noqa: E731 - the owner allows it in LOKI first
    return voice_studio.tool(args, cwd, ask)


def make_music(args: dict, cwd: Path) -> dict:
    import comfy_jobs  # pylint: disable=import-outside-toplevel
    import music  # pylint: disable=import-outside-toplevel - ACE-Step's own server first, then ComfyUI
    a = args or {}
    res = music.make(str(a.get("tags") or a.get("prompt") or ""), inside(cwd, "", "music"), str(a.get("lyrics") or ""),
                     float(a.get("seconds") or 0), int(a.get("bpm") or 0), str(a.get("key") or ""))
    if not res.get("ok"):
        res = comfy_jobs.make_music(a, inside(cwd, "", "music"))
    if res.get("ok"):
        res["files"] = [os.path.relpath(f, cwd) for f in res["files"]]
    return res


def toolshelf_call(args: dict, cwd: Path) -> dict:
    import toolshelf  # pylint: disable=import-outside-toplevel
    args = dict(args or {})
    if isinstance(args.get("args"), str):        # loki-make passes --args '{"input": "x.glb"}'
        try:
            args["args"] = json.loads(args["args"])
        except ValueError:
            return {"ok": False, "error": "args= must be JSON, e.g. '{\"input\": \"models/a.glb\"}'"}
    ask = lambda tool, details: ask_owner(tool, details)[0]  # noqa: E731 - installs and removals: the owner first
    return toolshelf.tool(args, cwd, ask)


def upscale_image(args: dict, cwd: Path) -> dict:
    import art_direction  # pylint: disable=import-outside-toplevel
    p = (cwd / str(args.get("image") or "")).resolve()
    if cwd.resolve() not in p.parents or not p.is_file():
        return {"ok": False, "error": "no such picture in this folder: %s" % args.get("image")}
    res = art_direction.upscale(str(p), int(args.get("scale") or 4), bool(args.get("anime")))
    if res.get("ok"):
        res["file"] = os.path.relpath(res["file"], cwd)
    return res


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

    backend = str(args.get("backend") or "auto").lower()
    res = make(src, out, prompt, backend if backend in ("auto", "pixal3d", "trellis2", "triposr", "online", "lift")
               else "auto", image_maker=maker)
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error", "the model was not made"))[:400]}
    files = [os.path.relpath(str(Path(f).resolve()), cwd) for f in (res.get("glb"), res.get("obj")) if f]
    return {"ok": True, "files": files, "backend": res.get("backend", ""),
            "triangles": (res.get("meta") or {}).get("triangles", 0),
            "next": "render_scene model=%s (passes, an AI still or a turntable)" % files[0] if files else ""}


def make_video(args: dict, cwd: Path, make=None) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "describe the clip (prompt)"}
    if make is None:
        import creative  # pylint: disable=import-outside-toplevel
        make = creative.make_video
    res = make(prompt[:800], cwd, image=str(args.get("image") or ""), seconds=float(args.get("seconds") or 3.0))
    return res if isinstance(res, dict) else {"ok": False, "error": "no answer"}


try:   # the owner's other machines (engine/machines.py): list them, hand one a task, check on it
    import machines as _machines  # noqa: E402
    TOOLS += _machines.TOOLS
except Exception:  # noqa: BLE001 - the making tools work without it
    _machines = None


def call(name: str, args: dict, cwd: Path) -> dict:
    fn = {"make_image": make_image, "make_3d": make_3d, "make_video": make_video, "upscale_image": upscale_image,
          "pixelize": pixelize, "voice": voice, "toolshelf": toolshelf_call,
          "make_music": make_music,
          "render_scene": lambda a, cwd: __import__("render_agent").render(a or {}, cwd),
          "library": lambda a, cwd: __import__("creations").library(cwd, str((a or {}).get("kind") or ""),
                                                                   str((a or {}).get("search") or ""),
                                                                   int((a or {}).get("limit") or 40)),
          "run_command": run_shell if SHELL_ON["on"] else None}.get(name)
    if fn is None and _machines is not None and name in _machines.FUNCS:
        try:
            return _machines.FUNCS[name](args or {})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}
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
        result = {"tools": TOOLS + ([SHELL_TOOL] if SHELL_ON["on"] else [])}
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


# --shell: run_command, so an outside agent that reaches LOKI over MCP (Claude Code, Codex ...) can do
# real work for the owner - anything, anywhere (owner 2026-10-25: "it needs to be allowed to do everything just ask
# before and detail what its going to [do]"). EVERY command first shows the owner an Allow / Deny card in LOKI with
# the plan, the exact command and the folder (POST /approval/ask on the running engine); nothing runs unless Allowed.
# Commands that can wreck a machine are marked DANGEROUS on that card.
DANGER = ("rm -rf /", "rm -fr /", "rm -rf ~", "del /f /s /q", "del /s /q", "rd /s /q", "rmdir /s /q", "format ",
          "mkfs", "diskpart", "fdisk", "wipefs", "dd if=", "dd of=/dev/", ":(){", "shutdown", "reboot", "poweroff",
          "chmod -r 777 /", "chmod 777 /", "reg delete", "bcdedit", "vssadmin", "| sh", "| bash", "sudo ")
SHELL_TOOL = {"name": "run_command",
              "description": "Run a shell command on the owner's computer (bash; Git Bash on Windows) and get its real "
                             "output - git, files, folders anywhere, builds, scripts. The owner sees plan + command + "
                             "folder and must click Allow in LOKI first, so write plan= clearly: what you will do and "
                             "why. folder= where it runs (default ~/LOKI Projects/Home; a name there or a full path). "
                             "GitHub: gh repo create <name> --private --source=. --remote=origin --push.",
              "inputSchema": {"type": "object", "properties": {
                  "plan": {"type": "string", "description": "for the owner: what this command does and why"},
                  "command": {"type": "string"}, "folder": {"type": "string"}, "timeout_s": {"type": "integer"}},
                  "required": ["plan", "command"]}}


def _engine() -> tuple:
    """(url, token) of the running LOKI (~/.loki/engine_connect.json, written by the engine at start)."""
    try:
        d = json.loads((Path.home() / ".loki" / "engine_connect.json").read_text(encoding="utf-8"))
        if d.get("url") and d.get("token"):
            return str(d["url"]).rstrip("/"), str(d["token"])
    except (OSError, ValueError):
        pass
    return "", ""


def ask_owner(tool: str, details: str, timeout_s: float = 600, opener=None) -> tuple:
    """(approved, why): an Allow / Deny card in LOKI; False when LOKI is not running or nobody answers."""
    import urllib.error  # pylint: disable=import-outside-toplevel
    import urllib.request  # pylint: disable=import-outside-toplevel
    url, token = _engine()
    if not url:
        return False, "LOKI is not running, so nobody can approve it - open LOKI and try again"
    req = urllib.request.Request(url + "/approval/ask", method="POST",
                                 data=json.dumps({"tool": tool, "details": details, "timeout_s": timeout_s}).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    try:
        with opener(req, timeout=timeout_s + 30) as resp:
            d = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, "LOKI did not answer (%s)" % getattr(exc, "reason", exc)
    return bool(d.get("approved")), str(d.get("why") or ("" if d.get("approved") else "the owner said no"))


def run_shell(args: dict, cwd: Path, ask=None) -> dict:  # noqa: ARG001 - the folder comes from args
    import local_agent  # pylint: disable=import-outside-toplevel
    cmd = str(args.get("command") or "").strip()
    plan = str(args.get("plan") or "").strip()
    if not cmd:
        return {"ok": False, "error": "which command?"}
    if len(plan) < 8:
        return {"ok": False, "error": "say in plan= what this command will do and why - the owner reads it before allowing"}
    try:
        import agent_folders  # pylint: disable=import-outside-toplevel
        base = agent_folders.projects_dir()
    except Exception:  # noqa: BLE001
        base = Path.home() / "LOKI Projects"
    raw = os.path.expanduser(str(args.get("folder") or "").strip())
    where = (Path(raw) if raw and os.path.isabs(raw) else base / (raw or "Home")).resolve()
    danger = next((d for d in DANGER if d in cmd.lower()), "")
    details = "%s%s\n\nPlan: %s\n\nCommand:\n$ %s\n\nIn: %s%s" % (
        "DANGEROUS - '%s' can destroy data or the system. " % danger.strip() if danger else "",
        "An outside agent (through LOKI's tools) wants to run a command.", plan[:2000], cmd[:4000], where,
        "" if where.exists() else " (this folder does not exist yet - it will be made)")
    ok, why = (ask or ask_owner)("run_command", details)
    if not ok:
        return {"ok": False, "error": "not run - %s" % why}
    where.mkdir(parents=True, exist_ok=True)
    local_agent.protect(where)
    code, out = local_agent.run_command(cmd, where, timeout=max(10, min(int(args.get("timeout_s") or 300), 1800)))
    return {"ok": code == 0, "exit": code, "folder": str(where), "output": out[-12000:]}


CLI = {"image": "make_image", "3d": "make_3d", "video": "make_video", "upscale": "upscale_image", "pixel": "pixelize",
       "voice": "voice", "shelf": "toolshelf", "music": "make_music", "library": "library",
       "render": "render_scene", "machines": "list_machines", "run-on": "run_on_machine", "job": "machine_job"}


def cli(argv: list, cwd: Path | None = None) -> int:
    """`loki-make <what> "<prompt>" [--key value ...]` - the same tools for an agent that only has a shell
    (engine/local_agent.py): image, 3d, video, upscale, pixel, machines, run-on, job. Prints the JSON answer."""
    if not argv or argv[0] not in CLI:
        print("usage: loki-make image|3d|video|upscale|pixel|machines|run-on|job \"<prompt or file>\" [--style comic] "
              "[--count 4] [--upscale 4] [--image pic.png] [--machine mac] [--job id]")
        return 2
    what, rest = argv[0], argv[1:]
    args: dict = {}
    while rest:
        a = rest.pop(0)
        if a.startswith("--") and rest:
            v = rest.pop(0)
            args[a[2:].replace("-", "_")] = int(v) if v.isdigit() else v
        elif what in ("upscale", "pixel"):
            args.setdefault("image", a)
        elif what == "run-on":
            args.setdefault("task", a)
        else:
            args.setdefault("prompt", a)
    out = call(CLI[what], args, Path(cwd or os.getcwd()))
    print(json.dumps(out, indent=1))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--shell"]:
        SHELL_ON["on"] = True
        serve()
    elif len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    else:
        serve()
