"""Measure how fast LOKI starts (docs/SPEED.md). Standard library only; nothing is changed.

    python tools/measure_start.py            # 3 runs of each step, median printed
    python tools/measure_start.py --runs 1 --json

Steps (each in a fresh process, with a throwaway data folder, so nothing of yours is touched):
  python      a bare interpreter start (the floor)
  import      `import loki_bridge` (the engine module)
  import_loki `import loki` (the agent, the biggest module)
  engine      engine process start -> GET /health answers 200 (what the window waits for)
  launcher    packaging/installer/loki_launch.py --check (an installed LOKI's launcher, venv + packages check)
The window itself (pywebview) cannot be timed headless; the app opens it the moment the engine answers.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _env(data: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LOKI_")}
    env.update(LOKI_DATA=str(data), LOKI_HEALTH_PROBES="0", LOKI_AUTO_UPDATE="0", LOKI_AUTOPILOT="off",
               LOKI_EMBED="off", LOKI_TIMESFM_APPROVED="0", PYTHONDONTWRITEBYTECODE="")
    return env


def timed(args: list, env: dict, cwd: Path = REPO) -> float:
    t0 = time.perf_counter()
    subprocess.run(args, cwd=str(cwd), env=env, capture_output=True, timeout=120)
    return time.perf_counter() - t0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def engine_to_health(env: dict, data: Path, timeout: float = 90.0) -> float:
    port = free_port()
    secret = data / "engine.token"
    work = data / "ws"
    work.mkdir(parents=True, exist_ok=True)
    env = dict(env, LOKI_PORT=str(port), LOKI_PEER_PORT=str(free_port()), LOKI_PHONE_PORT=str(free_port()))
    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, str(REPO / "engine" / "loki_bridge.py"), "--loki-root", str(REPO / "engine"),
                             "--project-dir", str(work), "--secret-file", str(secret), "--state-dir", str(data / "app"),
                             "--ui-dir", str(REPO / "app" / "ui")], cwd=str(REPO), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
    try:
        while time.perf_counter() - t0 < timeout:
            if proc.poll() is not None:
                return float("nan")
            token = secret.read_text(encoding="utf-8").strip() if secret.is_file() else ""
            if token:
                req = urllib.request.Request("http://127.0.0.1:%d/health" % port, headers={"Authorization": "Bearer " + token})
                try:
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        if resp.status == 200:
                            return time.perf_counter() - t0
                except (urllib.error.URLError, OSError):
                    pass
            time.sleep(0.02)
        return float("nan")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def engine_imports(top: int = 20) -> list:
    """The engine's slowest imports up to /health (python -X importtime), cumulative ms."""
    with tempfile.TemporaryDirectory(prefix="loki-speed-") as tmp:
        data = Path(tmp)
        env = dict(_env(data), PYTHONPROFILEIMPORTTIME="1")
        log = data / "imports.txt"
        port = free_port()
        with log.open("w") as err:
            proc = subprocess.Popen([sys.executable, str(REPO / "engine" / "loki_bridge.py"), "--loki-root", str(REPO / "engine"),
                                     "--project-dir", str(data / "ws"), "--secret-file", str(data / "tok"),
                                     "--state-dir", str(data / "app"), "--ui-dir", str(REPO / "app" / "ui")],
                                    cwd=str(REPO), env=dict(env, LOKI_PORT=str(port)), stdout=subprocess.DEVNULL, stderr=err)
            t0 = time.time()
            while time.time() - t0 < 30 and not (data / "tok").is_file():
                time.sleep(0.05)
            time.sleep(0.5)
            proc.terminate()
            proc.wait(timeout=10)
        rows = []
        for line in log.read_text(errors="replace").splitlines():
            parts = line.split("|")
            if line.startswith("import time:") and len(parts) == 3 and parts[1].strip().isdigit():
                rows.append((int(parts[1]) / 1000.0, parts[2].rstrip()))
        rows.sort(reverse=True)
        return rows[:top]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", default="", help="comma list of steps")
    ap.add_argument("--cold", action="store_true", help="no cached bytecode: every module is compiled (a first start)")
    ap.add_argument("--imports", action="store_true", help="list the engine's slowest imports instead")
    args = ap.parse_args()
    if args.imports:
        for ms, name in engine_imports():
            print("%8.1f ms  %s" % (ms, name))
        return 0
    steps = {
        "python": lambda env, d: timed([sys.executable, "-c", "pass"], env),
        "import": lambda env, d: timed([sys.executable, "-c", "import sys; sys.path.insert(0, 'engine'); import loki_bridge"], env),
        "import_loki": lambda env, d: timed([sys.executable, "-c", "import sys; sys.path.insert(0, 'engine'); import loki"], env),
        "engine": lambda env, d: engine_to_health(env, d),
        "launcher": lambda env, d: timed([sys.executable, str(REPO / "packaging" / "installer" / "loki_launch.py"), "--check",
                                          "--seed", str(REPO)], dict(env, LOKI_LAUNCH_NO_PIP="1")),
    }
    want = [s for s in (args.only.split(",") if args.only else steps) if s in steps]
    out = {}
    for name in want:
        vals = []
        for _ in range(max(1, args.runs)):
            with tempfile.TemporaryDirectory(prefix="loki-speed-") as tmp:
                env = _env(Path(tmp))
                if args.cold:
                    env["PYTHONPYCACHEPREFIX"] = str(Path(tmp) / "pycache")
                vals.append(steps[name](env, Path(tmp)))
        good = [v for v in vals if v == v]
        out[name] = {"median_s": round(statistics.median(good), 3) if good else None, "runs": [round(v, 3) for v in vals]}
        if not args.json:
            print("%-12s %s s   (runs: %s)" % (name, out[name]["median_s"], ", ".join("%.3f" % v for v in vals)), flush=True)
    if args.json:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
