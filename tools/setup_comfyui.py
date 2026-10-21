"""Set up ComfyUI for Render Studio's AI Renderer - on the PC (Windows, NVIDIA) or a Mac. Never run by the tests.

    python tools/setup_comfyui.py --dry-run            print the plan (what is fetched, from where, how big), change nothing
    python tools/setup_comfyui.py --install            ComfyUI + ComfyUI-GGUF at pinned commits, a venv, the Python packages
    python tools/setup_comfyui.py --models --yes-download [--quant Q4_K_M] [--zimage]
                                                       the model files docs/AI_RENDERER.md lists, at pinned revisions
    python tools/setup_comfyui.py --start              start ComfyUI on 127.0.0.1:8188, hidden (no console window)
    python tools/setup_comfyui.py --stop | --status
    python tools/setup_comfyui.py --uninstall --yes    remove harness_data/comfyui/ (models included)

Everything lives in harness_data/comfyui/ (never committed): ComfyUI/ (the checkout, its models/ folders), venv/, comfyui.log,
comfyui.pid. ComfyUI listens on 127.0.0.1 only; to let the Mac use the PC's ComfyUI over the LAN, start it with
--listen 0.0.0.0 (or the PC's LAN address) and set that address in Render Studio's settings - this is your choice, the
helper never opens it by itself.

Sources (licences): comfyanonymous/ComfyUI (GPL-3.0), city96/ComfyUI-GGUF (Apache-2.0); PyTorch from download.pytorch.org
(the CUDA 13.0 wheels ComfyUI's README names for NVIDIA). The models and their licences: docs/AI_RENDERER.md.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import no_console  # noqa: E402,F401 - no console windows for git / pip / ComfyUI on Windows

PINS = {
    "ComfyUI": {"repo": "https://github.com/comfyanonymous/ComfyUI.git", "commit": "7a28332047b6af638dc6c7f72ef3481a718769fd",
                "license": "GPL-3.0"},
    "ComfyUI-GGUF": {"repo": "https://github.com/city96/ComfyUI-GGUF.git", "commit": "6ea2651e7df66d7585f6ffee804b20e92fb38b8a",
                     "license": "Apache-2.0", "into": "custom_nodes"},
}
TORCH_INDEX = {"win32": "https://download.pytorch.org/whl/cu130", "linux": "https://download.pytorch.org/whl/cu130"}
QUANTS = ("Q3_K_M", "Q4_K_M", "Q5_K_M", "Q8_0")
HOST, PORT = "127.0.0.1", 8188


def home(data: Path | None = None) -> Path:
    return Path(data or os.getenv("LOKI_DATA") or REPO / "harness_data") / "comfyui"


def venv_python(root: Path, platform: str | None = None) -> Path:
    plat = platform or sys.platform
    return root / "venv" / ("Scripts/python.exe" if plat == "win32" else "bin/python")


def model_plan(quant: str = "Q4_K_M", zimage: bool = False) -> list:
    """The files to download, from the workflow graphs' own model lists (engine/ai_renderer_workflows)."""
    import ai_renderer  # pylint: disable=import-outside-toplevel
    want = ["vace_render"] + (["zimage_reference"] if zimage else [])
    out, seen = [], set()
    for name in want:
        for m in ai_renderer.workflow(name)["models"]:
            file, path, size = m["file"], m["path"], m.get("size")
            if name == "vace_render" and m["folder"] == "models/unet" and quant != "Q4_K_M":
                alt = next((a for a in m.get("alternatives") or [] if quant in a["file"]), None)
                if not alt:
                    raise SystemExit("no %s file in %s" % (quant, m["repo"]))
                file, path, size = alt["file"], alt["file"], alt["size"]
            if file in seen:
                continue
            seen.add(file)
            out.append({"file": file, "folder": m["folder"], "size": size, "license": m.get("license"),
                        "url": ai_renderer.HF % (m["repo"], m["revision"], path)})
    return out


def plan(args, root: Path, platform: str | None = None) -> dict:
    plat = platform or sys.platform
    steps = []
    if args.install:
        for name, pin in PINS.items():
            dest = root / "ComfyUI" / pin["into"] / name if pin.get("into") else root / "ComfyUI"
            steps.append({"do": "git clone + checkout", "what": name, "repo": pin["repo"], "commit": pin["commit"],
                          "license": pin["license"], "into": str(dest)})
        steps.append({"do": "python -m venv", "into": str(root / "venv")})
        torch = ["torch", "torchvision", "torchaudio"]
        if plat in TORCH_INDEX:
            steps.append({"do": "pip install", "packages": torch, "extra_index": TORCH_INDEX[plat], "note": "NVIDIA CUDA wheels (ComfyUI README)"})
        else:
            steps.append({"do": "pip install", "packages": torch, "note": "macOS: PyTorch with Metal (MPS); ComfyUI's README suggests nightly for the newest fixes"})
        steps.append({"do": "pip install -r", "file": "ComfyUI/requirements.txt"})
        steps.append({"do": "pip install -r", "file": "ComfyUI/custom_nodes/ComfyUI-GGUF/requirements.txt"})
    if args.models:
        files = model_plan(args.quant, args.zimage)
        total = sum(f["size"] or 0 for f in files)
        steps.append({"do": "download", "files": files, "total_gb": round(total / 1e9, 2),
                      "confirmed": bool(args.yes_download)})
    if args.start:
        steps.append({"do": "start", "argv": start_argv(root, plat), "hidden": True, "log": str(root / "comfyui.log")})
    return {"root": str(root), "platform": plat, "steps": steps}


def start_argv(root: Path, platform: str | None = None, listen: str = HOST, port: int = PORT) -> list:
    return [str(venv_python(root, platform)), str(root / "ComfyUI" / "main.py"), "--listen", listen, "--port", str(port),
            "--disable-auto-launch"]


def run(argv: list, cwd: Path | None = None) -> None:
    print("  $ " + " ".join(argv), flush=True)
    subprocess.run(argv, cwd=str(cwd) if cwd else None, check=True)


def install(root: Path) -> None:
    git = shutil.which("git")
    if not git:
        raise SystemExit("git is needed (it comes with LOKI's setup)")
    for name, pin in PINS.items():
        dest = root / "ComfyUI" / pin["into"] / name if pin.get("into") else root / "ComfyUI"
        if not (dest / ".git").is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            run([git, "clone", pin["repo"], str(dest)])
        run([git, "-C", str(dest), "fetch", "--quiet", "origin"])
        run([git, "-C", str(dest), "checkout", "--quiet", pin["commit"]])
    py = venv_python(root)
    if not py.exists():
        run([sys.executable, "-m", "venv", str(root / "venv")])
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    torch = ["torch", "torchvision", "torchaudio"]
    if sys.platform in TORCH_INDEX:
        run([str(py), "-m", "pip", "install", *torch, "--extra-index-url", TORCH_INDEX[sys.platform]])
    else:
        run([str(py), "-m", "pip", "install", *torch])
    run([str(py), "-m", "pip", "install", "-r", str(root / "ComfyUI" / "requirements.txt")])
    run([str(py), "-m", "pip", "install", "-r", str(root / "ComfyUI" / "custom_nodes" / "ComfyUI-GGUF" / "requirements.txt")])


def download(root: Path, files: list, opener=urllib.request.urlopen) -> None:
    for f in files:
        dest = root / "ComfyUI" / f["folder"] / f["file"]
        if dest.is_file() and (not f["size"] or dest.stat().st_size == f["size"]):
            print("  have %s" % dest.name)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(f["url"], headers={"Range": "bytes=%d-" % have} if have else {})
        print("  get %s (%.2f GB) -> %s" % (f["file"], (f["size"] or 0) / 1e9, dest.parent), flush=True)
        with opener(req, timeout=60) as resp, open(part, "ab" if have and getattr(resp, "status", 200) == 206 else "wb") as out:
            t0, done = time.time(), 0
            while True:
                chunk = resp.read(8 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if time.time() - t0 > 10:
                    print("    %.2f GB" % ((have + done) / 1e9), flush=True)
                    t0 = time.time()
        if f["size"] and part.stat().st_size != f["size"]:
            raise SystemExit("%s: got %d bytes, expected %d - run again to resume" % (f["file"], part.stat().st_size, f["size"]))
        os.replace(part, dest)


def start(root: Path, listen: str = HOST, port: int = PORT) -> int:
    if not venv_python(root).exists() or not (root / "ComfyUI" / "main.py").is_file():
        raise SystemExit("ComfyUI is not installed here yet: run --install first")
    log = open(root / "comfyui.log", "ab")
    kw = {"cwd": str(root / "ComfyUI"), "stdout": log, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = no_console.CREATE_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(start_argv(root, listen=listen, port=port), **kw)
    (root / "comfyui.pid").write_text(str(proc.pid))
    print("ComfyUI starting (pid %d) on http://%s:%d - log: %s" % (proc.pid, listen, port, root / "comfyui.log"))
    return proc.pid


def stop(root: Path) -> None:
    pid_file = root / "comfyui.pid"
    if not pid_file.is_file():
        print("not running (no pid file)")
        return
    pid = int(pid_file.read_text().strip() or 0)
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    pid_file.unlink()
    print("stopped pid %d" % pid)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--models", action="store_true")
    ap.add_argument("--yes-download", action="store_true", help="confirm the model downloads (tens of GB)")
    ap.add_argument("--quant", default="Q4_K_M", choices=QUANTS, help="the GGUF size (Q4_K_M is the model card's balance; Q3_K_M for less memory)")
    ap.add_argument("--zimage", action="store_true", help="also the Z-Image Turbo reference-frame models")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--listen", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--data", default="")
    a = ap.parse_args(argv)
    root = home(Path(a.data) if a.data else None)
    if a.dry_run or not any((a.install, a.models, a.start, a.stop, a.status, a.uninstall)):
        if not any((a.install, a.models, a.start)):
            a.install = a.models = a.start = True
        print(json.dumps(plan(a, root), indent=1))
        return 0
    if a.status:
        print(json.dumps({"root": str(root), "installed": (root / "ComfyUI" / "main.py").is_file(),
                          "venv": venv_python(root).exists(), "pid": (root / "comfyui.pid").read_text().strip() if (root / "comfyui.pid").is_file() else None,
                          "models": [str(p.relative_to(root / "ComfyUI")) for p in (root / "ComfyUI" / "models").rglob("*")
                                     if p.suffix in (".gguf", ".safetensors")] if (root / "ComfyUI" / "models").is_dir() else []}, indent=1))
        return 0
    if a.uninstall:
        if not a.yes:
            print("This deletes %s (ComfyUI, its venv and every downloaded model). Run again with --yes." % root)
            return 1
        stop(root) if (root / "comfyui.pid").is_file() else None
        shutil.rmtree(root, ignore_errors=True)
        print("removed %s" % root)
        return 0
    if a.stop:
        stop(root)
    if a.install:
        install(root)
    if a.models:
        files = model_plan(a.quant, a.zimage)
        if not a.yes_download:
            print("These downloads total %.1f GB:" % (sum(f["size"] or 0 for f in files) / 1e9))
            for f in files:
                print("  %s (%.2f GB, %s) -> ComfyUI/%s" % (f["file"], (f["size"] or 0) / 1e9, f["license"], f["folder"]))
            print("Run again with --yes-download to fetch them.")
            return 1
        download(root, files)
    if a.start:
        start(root, a.listen, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
