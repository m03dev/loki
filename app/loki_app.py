"""LOKI launcher (Mac + Windows). Standard library only.

The window and the driver are separate. This file:
  1. builds the driver `lokid` (Rust) on this machine, installing Rust first if needed,
  2. starts it in the background (it keeps working when the window closes),
  3. opens the window (pywebview if present, else the browser),
  4. keeps this machine on `master`: checks every 10 minutes and on "Update everything",
     swaps code only after the new version builds and its driver answers, and rolls back otherwise.

It keeps the old app's entry point (`app/loki_app.py`, `--self-test`, `--background`) so machines
running the previous LOKI move to this one through their old updater.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("LOKI_DATA") or REPO / "harness_data")
HOME = Path(os.environ.get("LOKI_HOME") or DATA / "home")
PORT = int(os.environ.get("LOKI_DRIVER_PORT") or 7717)
URL = f"http://127.0.0.1:{PORT}/"
WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
EXE = ".exe" if WIN else ""
UPDATE_EVERY_S = int(os.environ.get("LOKI_UPDATE_EVERY_S") or 600)
LOG = HOME / "launcher.log"
STATUS = HOME / "launcher_status.json"
SOURCES = ("Cargo.toml", "Cargo.lock", "crates", "app/ui/index.html")
NO_WINDOW = 0x08000000 if WIN else 0   # CREATE_NO_WINDOW: no console flashes for git/cargo
STATE: dict = {"window": None, "phase": "starting"}


def log(msg: str) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if sys.stdout and not WIN:
        print(line, flush=True)


def status(**kv) -> None:
    STATE.update(kv)
    data = {k: v for k, v in STATE.items() if k != "window"}
    data["t"] = time.time()
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, STATUS)
    except OSError:
        pass


def run(cmd: list, timeout: float = 120, **kw) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW, **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ds" % timeout
    except OSError as e:
        return 127, str(e)


def git(*args: str, timeout: float = 120) -> tuple[int, str]:
    return run(["git", "-C", str(REPO), *args], timeout=timeout)


# ---------------------------------------------------------------- environment

def load_env_file(path: Path, env: dict) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.replace("export ", "").strip()
        if k and k not in env:
            env[k] = v.strip().strip('"').strip("'")


def find_blender() -> str:
    found = [os.environ.get("LOKI_BLENDER", "")]
    if MAC:
        import glob
        for base in ["/Applications", str(Path.home() / "Applications")] + [str(p / "Applications") for p in Path("/Volumes").glob("*")]:
            found += sorted(glob.glob(base + "/Blender*.app/Contents/MacOS/Blender"), reverse=True)
    elif WIN:
        import glob
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                     str(Path.home() / "AppData" / "Local" / "Programs")):
            if base:
                found += sorted(glob.glob(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe")), reverse=True)
        found += [r"D:\Blender\blender.exe", r"C:\Blender\blender.exe"]
    found.append(shutil.which("blender") or "")
    for f in found:
        if f and Path(f).is_file():
            return f
    return ""


def driver_env() -> dict:
    env = dict(os.environ)
    load_env_file(DATA / ".env", env)       # the old app's keys (NVIDIA_API_KEY ...) keep working
    load_env_file(HOME / ".env", env)
    env["LOKI_HOME"] = str(HOME)
    env["LOKI_DRIVER_PORT"] = str(PORT)
    extra = [str(Path(sys.executable).parent)]  # `python` for the driver = this machine's LOKI python
    blender = find_blender()
    if blender:
        env["LOKI_BLENDER"] = blender
        extra.append(str(Path(blender).parent))
    extra.append(str(cargo_home() / "bin"))
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


# ---------------------------------------------------------------- building the driver

def source_hash() -> str:
    """Hash of everything the driver binary is built from (works with or without git)."""
    h = hashlib.sha256()
    for name in SOURCES:
        p = REPO / name
        files = sorted(x for x in p.rglob("*") if x.is_file() and "target" not in x.parts) if p.is_dir() else [p]
        for f in files:
            try:
                h.update(str(f.relative_to(REPO)).replace("\\", "/").encode())
                h.update(f.read_bytes())
            except OSError:
                pass
    return h.hexdigest()[:12]


def binary_path(tag: str) -> Path:
    return HOME / "bin" / f"lokid-{tag}{EXE}"


def cargo_home() -> Path:
    own = DATA / "toolchain" / "cargo"
    if own.is_dir():
        return own
    return Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")


def find_cargo() -> str:
    for c in (cargo_home() / "bin" / f"cargo{EXE}", Path.home() / ".cargo" / "bin" / f"cargo{EXE}"):
        if c.is_file():
            return str(c)
    return shutil.which("cargo") or ""


def install_rust() -> str:
    """Rust into harness_data/toolchain (on the Mac that is the external drive, never the internal disk)."""
    tc = DATA / "toolchain"
    tc.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, RUSTUP_HOME=str(tc / "rustup"), CARGO_HOME=str(tc / "cargo"))
    status(phase="installing Rust (first start only)")
    log("installing Rust into %s" % tc)
    if WIN:
        exe = tc / "rustup-init.exe"
        urllib.request.urlretrieve("https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe", exe)
        code, out = run([str(exe), "-y", "--no-modify-path", "--profile", "minimal"], timeout=1800, env=env)
    else:
        script = tc / "rustup.sh"
        urllib.request.urlretrieve("https://sh.rustup.rs", script)
        code, out = run(["sh", str(script), "-y", "--no-modify-path", "--profile", "minimal"], timeout=1800, env=env)
    log("rustup exit %s: %s" % (code, out[-600:]))
    cargo = tc / "cargo" / "bin" / f"cargo{EXE}"
    return str(cargo) if cargo.is_file() else ""


def build_driver(tree: Path, tag: str) -> Path | None:
    """Build lokid from `tree` into the versioned binary; None (with the reason logged) on failure."""
    out = binary_path(tag)
    if out.is_file():
        return out
    cargo = find_cargo() or install_rust()
    if not cargo:
        log("no Rust toolchain and it could not be installed")
        status(phase="error: Rust could not be installed (see launcher.log)")
        return None
    env = dict(os.environ)
    if (DATA / "toolchain" / "rustup").is_dir():
        env.update(RUSTUP_HOME=str(DATA / "toolchain" / "rustup"), CARGO_HOME=str(DATA / "toolchain" / "cargo"))
    env["CARGO_TARGET_DIR"] = str(DATA / "build")            # big build cache stays next to the checkout
    cmd = [cargo, "build", "--release", "-p", "lokid"]
    if MAC:
        cmd += ["-j", "2"]                                   # the Mac is not the powerhouse: gentle on memory
    status(phase="building the driver (first start takes a few minutes)")
    log("building lokid %s: %s" % (tag, " ".join(cmd)))
    t = time.time()
    code, text = run(cmd, timeout=3600, cwd=str(tree), env=env)
    (HOME / "build.log").write_text(text[-20000:], encoding="utf-8", errors="replace")
    if code != 0:
        log("build failed (exit %s) after %ds: %s" % (code, time.time() - t, text[-800:]))
        status(phase="error: the driver did not build (see build.log)")
        return None
    built = DATA / "build" / "release" / f"lokid{EXE}"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, out)
    log("built lokid %s in %ds" % (tag, time.time() - t))
    for old in sorted(out.parent.glob("lokid-*"), key=lambda p: p.stat().st_mtime)[:-3]:
        try:
            old.unlink()   # keep the 3 newest builds for rollback
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- running the driver

def health(timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(URL + "health", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if WIN:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill(pid: int) -> None:
    if not pid_alive(pid):
        return
    if WIN:
        run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=30)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(40):
        if not pid_alive(pid):
            return
        time.sleep(0.25)


def driver_record() -> dict:
    try:
        return json.loads((HOME / "lokid.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def start_driver(binary: Path, tag: str) -> bool:
    """Run `binary` as the driver. An older driver is stopped first; its jobs resume in the new one."""
    rec = driver_record()
    if rec.get("tag") == tag and pid_alive(int(rec.get("pid", 0))) and health():
        return True
    if rec.get("pid"):
        log("stopping driver %s (pid %s)" % (rec.get("tag"), rec.get("pid")))
        kill(int(rec["pid"]))
    out = open(HOME / "lokid.log", "a", encoding="utf-8")
    kw: dict = {"stdout": out, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "cwd": str(HOME), "env": driver_env()}
    if WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200 | NO_WINDOW   # detached, own group, no console
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen([str(binary), "serve"], **kw)  # noqa: S603 - our own binary
    (HOME / "lokid.json").write_text(json.dumps({"pid": proc.pid, "tag": tag, "binary": str(binary)}), encoding="utf-8")
    for _ in range(60):
        if health():
            log("driver %s up (pid %s)" % (tag, proc.pid))
            return True
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    log("driver %s did not answer (exit %s)" % (tag, proc.poll()))
    return False


def stop_old_engine() -> None:
    """The previous LOKI's engine may still be running from memory; ask it to quit for good."""
    token_file = DATA / "app" / "engine.token"
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return
    for port in (8767, 8766):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/quit", data=b"{}", method="POST",
                                         headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
            log("asked the old engine on port %d to quit" % port)
        except Exception:  # noqa: BLE001
            pass
    try:
        token_file.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- first light (proof on a fresh machine)

FIRST_GOAL = (
    "First light on this PC: prove the new LOKI can make art. Write ONE Blender Python script, scripts/campfire.py, "
    "that builds a small low-poly campfire scene from scratch (a ring of stones, crossed logs, a few flame shapes "
    "with an emissive orange material, a ground disc, a camera and warm lighting), saves the scene to "
    "scenes/campfire.blend and renders it with Eevee to renders/campfire.png at 1024x1024. Use absolute paths built "
    "from the script's own folder (os.path.dirname(os.path.abspath(__file__))) and create the output folders inside "
    "the script. Then run it with: blender --background --python scripts/campfire.py . "
    "Tasks and checks: the script (file:scripts/campfire.py), the render (file:renders/campfire.png), "
    "the scene (file:scenes/campfire.blend)."
)


def first_light() -> None:
    marker = HOME / "first_light_v2.json"
    if marker.exists() or not WIN or not find_blender():
        return   # the PC proves the driver; the Mac stays light
    try:   # an older first-light job left waiting is replaced by this one, never left hanging
        old = json.loads((HOME / "first_light.json").read_text(encoding="utf-8")).get("run")
        if old:
            req = urllib.request.Request(URL + f"runs/{old}/reply", method="POST", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"approve": False, "note": "Replaced by a newer first-light job; stop here."}).encode())
            urllib.request.urlopen(req, timeout=10)
            urllib.request.urlopen(urllib.request.Request(URL + f"runs/{old}/stop", method="POST", data=b""), timeout=10)
            log("declined and stopped the older first-light job %s" % old)
    except Exception:  # noqa: BLE001
        pass
    try:
        req = urllib.request.Request(URL + "runs", data=json.dumps({"goal": FIRST_GOAL, "max_hours": 2}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            run_info = json.loads(r.read().decode())
        marker.write_text(json.dumps({"run": run_info.get("id"), "t": time.time()}), encoding="utf-8")
        log("first-light job started: %s" % run_info.get("id"))
    except Exception as e:  # noqa: BLE001
        log("first-light job not started: %s" % e)


def probe_models() -> None:
    try:
        with urllib.request.urlopen(URL + "models?refresh=1", timeout=120) as r:
            rows = json.loads(r.read().decode())
        ok = [f"{x['provider']}/{x['role']}" for x in rows if x.get("ok")]
        log("models answering: %s" % (", ".join(ok) or "none"))
    except Exception as e:  # noqa: BLE001
        log("model probe failed: %s" % e)


# ---------------------------------------------------------------- staying on master

def head() -> str:
    code, out = git("rev-parse", "HEAD")
    return out.strip() if code == 0 else ""


def update(force: bool = False) -> str:
    """Move to origin/master if it changed, only once the new driver builds and answers."""
    if not (REPO / ".git").exists():
        return "not a git checkout"
    code, out = git("fetch", "-q", "origin", "master", timeout=180)
    if code != 0:
        return "fetch failed: " + out.strip()[-200:]
    before = head()
    code, target = git("rev-parse", "FETCH_HEAD")
    target = target.strip()
    if code != 0 or not target or target == before:
        return "up to date"
    skip_file = HOME / "update_skip.json"
    try:
        skip = json.loads(skip_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        skip = {}
    if target in skip:
        return "up to date (%s was skipped: %s)" % (target[:8], skip[target])
    for must in ("app/loki_app.py", "Cargo.toml", "crates/lokid/src/main.rs"):
        if git("cat-file", "-e", f"{target}:{must}")[0] != 0:
            return f"skipped {target[:8]}: it has no {must}"
    code, out = git("reset", "-q", "--keep", target)
    if code != 0:
        return "could not switch (local edits?): " + out.strip()[-200:]
    tag = source_hash()
    binary = build_driver(REPO, tag)
    if binary is None or not start_driver(binary, tag):
        log("new version %s failed; going back to %s" % (target[:8], before[:8]))
        git("reset", "-q", "--keep", before)
        old_tag = source_hash()
        if binary_path(old_tag).is_file():
            start_driver(binary_path(old_tag), old_tag)
        skip[target] = "its driver did not build or answer"
        try:
            skip_file.write_text(json.dumps(dict(list(skip.items())[-20:])), encoding="utf-8")
        except OSError:
            pass
        return f"rolled back from {target[:8]}"
    log("updated %s -> %s" % (before[:8], target[:8]))
    relaunch()
    return "updated"


def relaunch() -> None:
    """Start the new launcher (it waits for this one), then leave."""
    env = dict(os.environ, LOKI_APP_WAIT_PID=str(os.getpid()))
    args = [sys.executable, str(REPO / "app" / "loki_app.py")]
    if STATE.get("window") is None:
        args.append("--background")
    kw: dict = {"env": env, "cwd": str(REPO), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)  # noqa: S603
    w = STATE.get("window")
    if w is not None:
        try:
            w.destroy()
        except Exception:  # noqa: BLE001
            pass
    os._exit(0)


def update_loop() -> None:
    last = time.time()
    req = HOME / "update.request"
    while True:
        time.sleep(5)
        asked = req.exists()
        if asked or time.time() - last >= UPDATE_EVERY_S:
            if asked:
                try:
                    req.unlink()
                except OSError:
                    pass
            last = time.time()
            result = update(force=asked)
            status(last_update=result, last_update_t=time.time())
            if not result.startswith("up to date") or asked:
                log("update: " + result)
        # keep the driver alive (it resumes its jobs on restart)
        if STATE.get("phase") == "running" and not health(3):
            rec = driver_record()
            if rec.get("binary") and not pid_alive(int(rec.get("pid", 0))):
                log("driver was not running; starting it again")
                start_driver(Path(rec["binary"]), rec.get("tag", ""))


# ---------------------------------------------------------------- startup

def self_test() -> int:
    """`--self-test`: what the old updater's pre-flight runs. Checks the files the launcher needs."""
    missing = [p for p in ("Cargo.toml", "Cargo.lock", "crates/lokid/src/main.rs", "crates/loki-core/src/agent.rs",
                           "crates/lokid/providers.default.toml", "app/ui/index.html") if not (REPO / p).is_file()]
    print("Loki self-test: " + ("OK" if not missing else "FAILED - missing " + ", ".join(missing)), flush=True)
    return 0 if not missing else 1


def wait_for_old_app() -> None:
    pid = os.environ.pop("LOKI_APP_WAIT_PID", "")
    if pid.isdigit():
        end = time.time() + 40
        while time.time() < end and pid_alive(int(pid)):
            time.sleep(0.25)


def boot() -> None:
    """Everything after the window opens: driver build/start, then the proof jobs."""
    try:
        tag = source_hash()
        status(phase="starting the driver", version=(REPO / "VERSION").read_text().strip() if (REPO / "VERSION").exists() else "?",
               commit=head()[:12], tag=tag, platform=platform.platform())
        binary = build_driver(REPO, tag)
        if binary is None or not start_driver(binary, tag):
            status(phase="error: driver not running (see launcher.log)")
            show(error=True)
            return
        status(phase="running")
        show()
        probe_models()
        first_light()
    except Exception as e:  # noqa: BLE001
        log("boot failed: %r" % e)
        status(phase="error: %r" % e)
        show(error=True)


WAIT_HTML = """<html><body style="background:#0f1115;color:#e8eaf0;font:15px system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="text-align:center"><div style="font-weight:700;letter-spacing:.12em;font-size:20px">LOKI</div>
<p style="color:#9aa3b2">Starting the driver&hellip; the first start builds it on this machine and can take a few minutes.</p></div></body></html>"""


def show(error: bool = False) -> None:
    w = STATE.get("window")
    if w is None:
        if not error and "--background" not in sys.argv and not STATE.get("webview"):
            import webbrowser
            webbrowser.open(URL)
        return
    try:
        if error:
            w.load_html(WAIT_HTML.replace("Starting the driver&hellip; the first start builds it on this machine and can take a few minutes.",
                                          "The driver did not start. Details: " + str(LOG)))
        else:
            w.load_url(URL)
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return self_test()
    if argv[:1] == ["--update-now"]:
        print(update(force=True))
        return 0
    wait_for_old_app()
    HOME.mkdir(parents=True, exist_ok=True)
    lock = HOME / "launcher.pid"
    try:
        other = int(lock.read_text().strip())
    except (OSError, ValueError):
        other = 0
    if other and other != os.getpid() and pid_alive(other):
        # LOKI is already running here: just show it.
        if "--background" not in argv and health():
            try:
                import webview  # type: ignore
                webview.create_window("LOKI", URL, width=1320, height=880, min_size=(720, 520))
                webview.start()
            except Exception:  # noqa: BLE001
                import webbrowser
                webbrowser.open(URL)
        return 0
    lock.write_text(str(os.getpid()))
    log("launcher start %s (%s)" % (head()[:12] or "no git", platform.platform()))
    stop_old_engine()
    threading.Thread(target=update_loop, daemon=True).start()
    background = "--background" in argv
    webview = None
    if not background:
        try:
            import webview  # type: ignore  # pywebview, installed by setup
        except Exception:  # noqa: BLE001
            webview = None
    if webview is not None:
        STATE["webview"] = True
        STATE["window"] = webview.create_window("LOKI", html=WAIT_HTML, width=1320, height=880, min_size=(720, 520))
        webview.start(boot)
        STATE["window"] = None          # window closed: the driver keeps working, this keeps it updated
        log("window closed; LOKI keeps working in the background")
    else:
        boot()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
