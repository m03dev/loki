"""Design: UI screens, cards, posters and app mock-ups as real design files, made with OpenPencil
(github.com/open-pencil/open-pencil, MIT - an open Figma-compatible editor; owner 2026-10-28: "as well as open-pencil
somewhere ... everything should be symbiotic").

LOKI drives OpenPencil's command line headlessly - no app has to be open:
    new      an empty .fig, or one imported from HTML + CSS / Tailwind (an agent's mock-up becomes real layers)
    render   JSX (<Frame> <Text> <Rectangle> <svg> ...) drawn into the file - OpenPencil's own `render` tool
    eval     the Figma Plugin API on the file (figma.currentPage ...) - anything the 122 core tools can do
    call     any of OpenPencil's core tools by name (tool list / tool describe <name> shows them)
    export   png / jpg / webp / svg / jsx / tailwind-jsx / html / pptx / fig (PDF is broken in 0.16.0: svg instead)
    lint     the design checked (recommended / strict / accessibility); exit 1 = problems
    tree     the layer tree; info: pages, node counts, fonts
    open     the file in the OpenPencil desktop app, when it is installed (brew --cask openpencil / winget)
Every change writes a PNG preview next to the file, so the owner and the agents can look at it.

Files: <workspace>/designs/<name>.fig (+ <name>.png preview), exports in designs/exports/.
The CLI comes from the Tool Shelf (engine/toolshelf/design_mobile.json, installed once into LOKI's data folder - the
external drive on the Mac), or `npx -y @open-pencil/cli@0.16.0` when Node is there and it is not installed yet.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


PIN = "0.16.0"
FORMATS = ("png", "jpg", "webp", "svg", "jsx", "tailwind-jsx", "html", "pptx", "fig")
LINT = ("recommended", "strict", "accessibility")


def designs(ws) -> Path:
    d = Path(ws) / "designs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _name(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48]
    return s or "design"


def _file(ws, name: str) -> Path:
    base = designs(ws).resolve()
    stem = Path(str(name or "")).name
    if stem.endswith(".fig"):
        stem = stem[:-4]
    p = (base / (_name(stem) + ".fig")).resolve()
    if base not in p.parents:
        raise ValueError("a design lives in designs/")
    return p


def cli() -> list:
    """The command that runs OpenPencil's CLI here, or [] (with no Node)."""
    exe = ""
    try:
        import toolshelf  # pylint: disable=import-outside-toplevel
        d = toolshelf.tool_dir("openpencil")
        exe = toolshelf.find_exe(d, "openpencil") if d.is_dir() else ""
    except Exception:  # noqa: BLE001
        exe = ""
    if exe and Path(exe).is_file():
        return [exe]
    npx = shutil.which("npx")
    return [npx, "-y", "@open-pencil/cli@%s" % PIN] if npx else []


def available() -> bool:
    return bool(cli())


def _run(args: list, cwd: Path, timeout: int = 180, runner=subprocess.run, stdin: str | None = None) -> tuple:
    cmd = cli()
    if not cmd:
        return 127, "OpenPencil needs Node.js - install Node (nodejs.org), or the Tool Shelf's 'openpencil'"
    env = dict(os.environ, OPENPENCIL_TELEMETRY="0", DO_NOT_TRACK="1", NO_COLOR="1")
    try:
        proc = runner(cmd + [str(a) for a in args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                      env=env, input=stdin, shell=False)
    except subprocess.TimeoutExpired:
        return 124, "OpenPencil took longer than %d s" % timeout
    except OSError as exc:
        return 127, "OpenPencil did not start: %s" % exc
    return proc.returncode, ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()


def _json_out(text: str):
    s, e = text.find("{"), text.rfind("}")
    s2, e2 = text.find("["), text.rfind("]")
    if s2 >= 0 and (s < 0 or s2 < s):
        s, e = s2, e2
    try:
        return json.loads(text[s:e + 1]) if s >= 0 and e > s else None
    except ValueError:
        return None


def _rel(ws, p: Path) -> str:
    return os.path.relpath(p, ws).replace("\\", "/")


def preview(ws, f: Path, runner=subprocess.run) -> str:
    png = f.with_suffix(".png")
    code, out = _run(["export", f.name, "-f", "png", "-s", "1", "-o", png.name], f.parent, runner=runner)
    return _rel(ws, png) if code == 0 and png.is_file() else ""


def new(ws, name: str, html: str = "", css: str = "", tailwind: str = "", page: str = "Page 1",
        runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if f.exists():
        return {"ok": False, "error": "%s already exists - render / eval into it, or pick another name" % _rel(ws, f)}
    src = f.with_suffix(".src.html")
    src.write_text(html if html.strip() else "<html><body></body></html>", encoding="utf-8")
    args = ["import", src.name, "-o", f.name, "--pageName", page or "Page 1", "--json"]
    if css.strip():
        cssf = f.with_suffix(".src.css")
        cssf.write_text(css, encoding="utf-8")
        args += ["--css", cssf.name]
    if tailwind.strip():
        args += ["--tailwind", tailwind[:4000]]
    code, out = _run(args, f.parent, runner=runner)
    if code != 0 or not f.is_file():
        return {"ok": False, "error": "import failed: %s" % out[-600:]}
    return {"ok": True, "file": _rel(ws, f), "preview": preview(ws, f, runner), "import": _json_out(out)}


def _tool_call(f: Path, tool_name: str, payload: dict, runner) -> tuple:
    """OpenPencil core tool on a file, written back (the CLI's stdin args do not work in 0.16.0: a file does)."""
    argf = f.with_name(".%s.args.json" % f.stem)
    argf.write_text(json.dumps(payload), encoding="utf-8")
    try:
        return _run(["tool", "call", tool_name, f.name, "--args-file", argf.name, "-w", "--json"], f.parent, runner=runner)
    finally:
        try:
            argf.unlink()
        except OSError:
            pass


def render(ws, name: str, jsx: str, parent: str = "", runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if not str(jsx or "").strip():
        return {"ok": False, "error": "jsx= what to draw, e.g. <Frame w={360} h={640} bg=\"#111\">...</Frame>"}
    if not f.is_file():
        made = new(ws, name, runner=runner)
        if not made.get("ok"):
            return made
    payload = {"jsx": jsx}
    if parent:
        payload["parent_id"] = parent
    code, out = _tool_call(f, "render", payload, runner)
    if code != 0:
        return {"ok": False, "error": "render failed: %s" % out[-800:]}
    return {"ok": True, "file": _rel(ws, f), "preview": preview(ws, f, runner), "result": _json_out(out)}


def call_tool(ws, name: str, tool_name: str, args: dict, runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if not f.is_file():
        return {"ok": False, "error": "no design %s" % _rel(ws, f)}
    if not re.fullmatch(r"[a-z_]{2,40}", str(tool_name or "")):
        return {"ok": False, "error": "which OpenPencil tool? (action=tools lists them)"}
    code, out = _tool_call(f, tool_name, args or {}, runner)
    if code != 0:
        return {"ok": False, "error": "%s failed: %s" % (tool_name, out[-800:])}
    return {"ok": True, "file": _rel(ws, f), "preview": preview(ws, f, runner), "result": _json_out(out) or out[-2000:]}


def run_eval(ws, name: str, code_text: str, write: bool = False, runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if not f.is_file():
        return {"ok": False, "error": "no design %s" % _rel(ws, f)}
    args = ["eval", f.name, "--stdin", "--json"] + (["-w"] if write else [])
    code, out = _run(args, f.parent, runner=runner, stdin=code_text)
    if code != 0:
        return {"ok": False, "error": "eval failed: %s" % out[-800:]}
    res = {"ok": True, "file": _rel(ws, f), "result": _json_out(out) if _json_out(out) is not None else out[-3000:]}
    if write:
        res["preview"] = preview(ws, f, runner)
    return res


def export(ws, name: str, fmt: str = "png", scale: int = 2, page: str = "", node: str = "", runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if not f.is_file():
        return {"ok": False, "error": "no design %s" % _rel(ws, f)}
    fmt = str(fmt or "png").lower()
    if fmt == "pdf":
        return {"ok": False, "error": "PDF export is broken in OpenPencil %s - export svg (or png) instead" % PIN}
    if fmt not in FORMATS:
        return {"ok": False, "error": "format is one of %s" % ", ".join(FORMATS)}
    out_dir = designs(ws) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = {"tailwind-jsx": "jsx"}.get(fmt, fmt)
    target = out_dir / ("%s%s.%s" % (f.stem, "@%dx" % scale if fmt in ("png", "jpg", "webp") else "", ext))
    args = ["export", f.name, "-f", fmt, "-o", str(target)]
    if fmt in ("png", "jpg", "webp"):
        args += ["-s", str(max(1, min(int(scale or 2), 4)))]
    if fmt == "html":
        args += ["--html", "standalone"]
    if page:
        args += ["--page", page]
    elif node:
        args += ["--node", node]
    code, out = _run(args, f.parent, runner=runner)
    if code != 0 or not target.is_file():
        return {"ok": False, "error": "export failed: %s" % out[-600:]}
    return {"ok": True, "file": _rel(ws, target), "format": fmt}


def lint(ws, name: str, preset: str = "recommended", runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if not f.is_file():
        return {"ok": False, "error": "no design %s" % _rel(ws, f)}
    code, out = _run(["lint", f.name, "--preset", preset if preset in LINT else "recommended", "--json"], f.parent,
                     runner=runner)
    data = _json_out(out)
    return {"ok": code == 0, "clean": code == 0, "report": data if data is not None else out[-3000:],
            **({} if code in (0, 1) else {"error": out[-600:]})}


def tree(ws, name: str, depth: int = 3, runner=subprocess.run) -> dict:
    f = _file(ws, name)
    if not f.is_file():
        return {"ok": False, "error": "no design %s" % _rel(ws, f)}
    code, out = _run(["tree", f.name, "--depth", str(max(1, min(int(depth or 3), 8))), "--json"], f.parent, runner=runner)
    return {"ok": code == 0, "tree": _json_out(out) or out[-6000:]}


def tools(runner=subprocess.run) -> dict:
    code, out = _run(["tool", "list", "--json"], Path.home(), runner=runner)
    data = _json_out(out)
    names = [t.get("name") if isinstance(t, dict) else t for t in (data or [])] if isinstance(data, list) else []
    return {"ok": code == 0, "tools": names or out[-4000:]}


def app_path() -> str:
    """The OpenPencil desktop app, when installed."""
    if sys.platform == "darwin":
        for p in ("/Applications/OpenPencil.app", str(Path.home() / "Applications" / "OpenPencil.app")):
            if Path(p).exists():
                return p
    elif sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenPencil" / "OpenPencil.exe"
        if p.is_file():
            return str(p)
    return shutil.which("openpencil-app") or ""


def app_running() -> bool:
    """The desktop app's MCP discovery file exists (engine/mcp_servers.json starts openpencil-mcp only then)."""
    if sys.platform == "darwin":
        f = Path.home() / "Library" / "Application Support" / "OpenPencil" / "mcp.json"
    elif sys.platform == "win32":
        f = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenPencil" / "mcp.json"
    else:
        f = Path.home() / ".config" / "OpenPencil" / "mcp.json"
    return f.is_file()


def open_in_app(ws, name: str, popen=subprocess.Popen) -> dict:
    f = _file(ws, name)
    if not f.is_file():
        return {"ok": False, "error": "no design %s" % _rel(ws, f)}
    app = app_path()
    if not app:
        how = ("brew install --cask openpencil" if sys.platform == "darwin" else
               "winget install --id OpenPencil.OpenPencil --exact" if sys.platform == "win32" else "openpencil.dev")
        return {"ok": False, "error": "the OpenPencil app is not installed here (%s)" % how}
    env = dict(os.environ, OPENPENCIL_TELEMETRY="0", DO_NOT_TRACK="1")
    cmd = ["open", "-a", app, str(f)] if sys.platform == "darwin" else [app, str(f)]
    popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "opened": _rel(ws, f)}


def listing(ws) -> list:
    out = []
    for f in sorted(designs(ws).glob("*.fig"), key=lambda p: p.stat().st_mtime, reverse=True):
        png = f.with_suffix(".png")
        out.append({"name": f.stem, "file": _rel(ws, f), "preview": _rel(ws, png) if png.is_file() else "",
                    "updated": f.stat().st_mtime, "size": f.stat().st_size})
    return out


def tool(args: dict, ws, runner=subprocess.run) -> dict:
    a = dict(args or {})
    act = str(a.get("action") or "list").lower()
    ws = Path(ws)
    name = str(a.get("name") or a.get("file") or "")
    try:
        if act == "list":
            return {"ok": True, "designs": listing(ws), "cli": bool(cli()), "app": bool(app_path()),
                    "app_running": app_running()}
        if act == "tools":
            return tools(runner)
        if act == "describe" or (act == "call" and str(a.get("tool") or "") in ("describe", "list")):
            # what one core tool takes (2026-10-29, the Mac: an agent called the tool "describe" through call and got
            # "Invalid key: Expected never but received tool")
            what = str(a.get("tool") or "") if act == "describe" else str((a.get("args") or {}).get("tool") or a.get("name") or "")
            if not what or what in ("describe", "list"):
                return tools(runner)
            code, out = _run(["tool", "describe", what, "--json"], Path.home(), runner=runner)
            return {"ok": code == 0, "tool": what, "describe": _json_out(out) or out[-4000:]}
        if not name:
            return {"ok": False, "error": "name= the design (designs/<name>.fig)"}
        if act == "new":
            return new(ws, name, str(a.get("html") or ""), str(a.get("css") or ""), str(a.get("tailwind") or ""),
                       str(a.get("page") or "Page 1"), runner)
        if act == "render":
            return render(ws, name, str(a.get("jsx") or ""), str(a.get("parent") or ""), runner)
        if act == "call":
            targs = a.get("args") or {}
            if isinstance(targs, str):
                targs = json.loads(targs or "{}")
            return call_tool(ws, name, str(a.get("tool") or ""), targs, runner)
        if act == "eval":
            return run_eval(ws, name, str(a.get("code") or ""), bool(a.get("write")), runner)
        if act == "export":
            return export(ws, name, str(a.get("format") or "png"), int(a.get("scale") or 2), str(a.get("page") or ""),
                          str(a.get("node") or ""), runner)
        if act == "lint":
            return lint(ws, name, str(a.get("preset") or "recommended"), runner)
        if act == "tree":
            return tree(ws, name, int(a.get("depth") or 3), runner)
        if act == "preview":
            f = _file(ws, name)
            return {"ok": f.is_file(), "preview": preview(ws, f, runner) if f.is_file() else ""}
        if act == "open":
            return open_in_app(ws, name)
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": False, "error": "unknown design action %r" % act}


TOOL_SCHEMA = {
    "name": "design",
    "description": ("UI / app / web / poster DESIGN as real layered design files (OpenPencil, Figma-compatible .fig) in "
                    "designs/. action: new (name, optional html+css or tailwind = import a mock-up as layers) | render "
                    "(name, jsx: <Frame name w h bg rounded flex gap p> <Text size color weight> <Rectangle> <svg> ...) | "
                    "call (name, tool, args: any OpenPencil core tool - action=tools lists them, action=describe tool=<name> shows its args) | eval (name, code: "
                    "Figma Plugin API, write=true saves) | export (name, format png/svg/jsx/tailwind-jsx/html/pptx, "
                    "scale) | lint (name, preset recommended/strict/accessibility) | tree | open (desktop app) | list. "
                    "Every change writes designs/<name>.png - look at it before saying done."),
    "inputSchema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["list", "tools", "describe", "new", "render", "call", "eval", "export", "lint", "tree",
                                              "preview", "open"]},
        "name": {"type": "string"}, "html": {"type": "string"}, "css": {"type": "string"},
        "tailwind": {"type": "string"}, "jsx": {"type": "string"}, "parent": {"type": "string"},
        "tool": {"type": "string"}, "args": {"type": "object"}, "code": {"type": "string"}, "write": {"type": "boolean"},
        "format": {"type": "string", "enum": list(FORMATS)}, "scale": {"type": "integer"},
        "preset": {"type": "string", "enum": list(LINT)}, "page": {"type": "string"}, "node": {"type": "string"},
        "depth": {"type": "integer"}},
        "required": ["action"]},
}
