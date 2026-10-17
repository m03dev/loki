"""Videos made from code with Remotion. stdin/stdout JSON, like every runner.

    {"op": "scaffold", "dir": "<workspace>/videos/intro"}
    {"op": "render", "project_dir": "<workspace>/videos/intro", "composition": "MyComp",
     "out": "<workspace>/videos/intro.mp4", "props": {...}, "entry": "src/index.ts"}

Remotion (github.com/remotion-dev/remotion) is NOT open source in the usual sense: its
licence is free for individuals and for companies with up to 3 employees; bigger companies
need a company licence (remotion.dev/license). LOKI never vendors it: `npx` fetches it into
the video project the user asked for. Needs Node 18+ (npx). Rendering runs the project's
own code (it is a React app), so the agent tool that calls this always asks first.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ENTRIES = ("src/index.ts", "src/index.tsx", "src/index.js", "src/index.jsx", "remotion/index.ts")


def find_npx():
    return shutil.which("npx") or shutil.which("npx.cmd") or ""


def scaffold_argv(npx, directory):
    return [npx, "--yes", "create-video@latest", "--yes", "--blank", str(directory)]


def find_entry(project_dir, entry=""):
    root = Path(project_dir)
    if entry:
        return entry
    for candidate in ENTRIES:
        if (root / candidate).is_file():
            return candidate
    return ENTRIES[0]


def render_argv(npx, entry, composition, out, props_file=""):
    argv = [npx, "remotion", "render", str(entry), str(composition), str(out)]
    if props_file:
        argv.append("--props=%s" % props_file)
    return argv + ["--codec=h264", "--overwrite"]


def _run(argv, cwd, timeout):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout, shell=False)
    return proc.returncode, ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()[-2000:]


def main():
    job = json.loads(sys.stdin.read() or "{}")
    npx = find_npx()
    if not npx:
        print(json.dumps({"ok": False, "missing": True,
                          "error": "npx is missing: install Node 18+ (https://nodejs.org), then try again"}))
        return
    op = str(job.get("op", "render"))
    timeout = int(job.get("timeout", 1800) or 1800)
    try:
        if op == "scaffold":
            target = Path(job["dir"])
            if (target / "package.json").is_file():
                print(json.dumps({"ok": True, "dir": str(target), "note": "already a video project"}))
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            code, log = _run(scaffold_argv(npx, target.name), str(target.parent), timeout)
            if code != 0:
                print(json.dumps({"ok": False, "error": "create-video failed: " + log[-800:]}))
                return
            npm = shutil.which("npm") or shutil.which("npm.cmd") or ""
            install_code, install_log = _run([npm, "install"], str(target), timeout) \
                if npm and not (target / "node_modules").is_dir() else (0, "")
            print(json.dumps({"ok": True, "dir": str(target), "entry": find_entry(target),
                              "note": "" if install_code == 0 else "npm install failed: " + install_log[-400:]}))
            return
        project = Path(job["project_dir"])
        if not (project / "package.json").is_file():
            print(json.dumps({"ok": False, "error": "%s is not a Remotion project (no package.json); "
                                                    "make one with video_project first" % project}))
            return
        out = Path(job["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        props_file = ""
        if job.get("props"):
            props_path = project / ".loki-props.json"
            props_path.write_text(json.dumps(job["props"]), encoding="utf-8")
            props_file = str(props_path)
        argv = render_argv(npx, find_entry(project, str(job.get("entry") or "")), job["composition"], out, props_file)
        code, log = _run(argv, str(project), timeout)
        if code != 0 or not out.is_file():
            print(json.dumps({"ok": False, "error": "remotion render failed (exit %d): %s" % (code, log[-800:])}))
            return
        print(json.dumps({"ok": True, "file": str(out), "bytes": out.stat().st_size}))
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok": False, "error": "Remotion took longer than %ds" % timeout}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}))


if __name__ == "__main__":
    main()
