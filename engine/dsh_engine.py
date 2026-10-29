"""DeepSeek Harness (dsh) as LOKI's agent when the model is DeepSeek.

Owner 2026-10-25 11:34: "when we're using deepseek4.1 use deepseek harness find it and use it its opensource".
DeepSeek Harness (github.com/deepseek-ai/deepseek-harness, MIT, npm @deepseek-ai/dsh, Node 22.19+) is DeepSeek's own
agent runtime: shell, read / write / grep / ls, plugins. LOKI runs it headless, one turn per message:

    dsh --profile headless "<the task>"        in the workspace (its default permission mode, workspace-write,
                                               confines writes to that folder); stdout = the final message; exit 0 =
                                               the turn completed

The model and the key: LOKI keeps its OWN dsh home (DATA/dsh, DSH_HOME) so the owner's ~/.dsh is never touched;
settings.yaml there names the model (DeepSeek's own API -> provider deepseek-official; any other base URL -> a custom
openai-completions provider), and the key goes in the environment (DEEPSEEK_API_KEY / LOKI_DSH_KEY - dsh reads the
environment first; never written to a file).

dsh prints only its final message, so LOKI checks what really happened: the workspace before and after the turn
(files made, changed, removed; a new .git). "Done" with nothing changed is NOT DONE (engine/loki.py run_opencode).

LOKI_DEEPSEEK_HARNESS = auto (default: dsh for a DeepSeek model when dsh is installed) | off | on
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

INSTALL = "npm install -g @deepseek-ai/dsh"
OFFICIAL_HOSTS = ("api.deepseek.com",)
SKIP_DIRS = {"node_modules", ".codegraph", "__pycache__", ".venv", "venv", ".dsh"}
MAX_FILES = 20000


def mode(env: dict | None = None) -> str:
    v = str((env if env is not None else os.environ).get("LOKI_DEEPSEEK_HARNESS", "auto")).strip().lower()
    return v if v in ("auto", "on", "off") else "auto"


def find_dsh(which: Callable = shutil.which) -> str:
    found = which("dsh")
    if found:
        return found
    try:
        import opencode_engine  # pylint: disable=import-outside-toplevel - the same global npm folders
        for d in opencode_engine._global_bins():   # noqa: SLF001
            for name in ("dsh", "dsh.cmd", "dsh.exe"):
                p = Path(d) / name
                if p.is_file():
                    return str(p)
    except Exception:  # noqa: BLE001
        pass
    return ""


def is_deepseek(p: dict) -> bool:
    return "deepseek" in str(p.get("base_url") or "").lower() or str(p.get("model") or "").lower().startswith("deepseek")


def pick(providers: dict, env: dict | None = None) -> tuple[str, dict] | None:
    """The DeepSeek provider dsh should run (the first DeepSeek one in LOKI's order), or None."""
    m = mode(env)
    if m == "off" or not providers:
        return None
    if m == "auto":                       # only when DeepSeek is the model answering (the first in LOKI's order)
        name, p = next(iter(providers.items()))
        return (name, p) if is_deepseek(p) else None
    for name, p in providers.items():     # on: whichever DeepSeek provider LOKI has
        if is_deepseek(p):
            return name, p
    return None


def settings_yaml(provider: dict) -> str:
    """dsh's settings.yaml for this model. YAML by hand (no dependency): the values are plain words and a URL."""
    base = str(provider.get("base_url") or "").rstrip("/")
    model = str(provider.get("model") or "deepseek-v4-flash")
    clean = lambda s: "".join(ch for ch in str(s) if ch.isalnum() or ch in "-_./:@")   # noqa: E731
    if not base or any(h in base for h in OFFICIAL_HOSTS):
        return "agent-default-model:\n  provider: deepseek-official\n  model: %s\n" % clean(model)
    if "/" in model and "127.0.0.1" in base and "/u/" in base:
        # dsh reads "a/b" as provider/model and never finds it (UNKNOWN_MODEL, benched on the Mac for days): it gets a
        # plain alias, and LOKI's proxy (which it already goes through) sends the real name upstream
        import dsml_proxy  # pylint: disable=import-outside-toplevel
        model = dsml_proxy.alias_for(model)
    return ("agent-default-model:\n  provider: loki-deepseek\n  model: %s\n"
            "llm-pi-ai:\n  providers:\n    loki-deepseek:\n      displayName: LOKI DeepSeek\n      apiKeyEnv: LOKI_DSH_KEY\n"
            "      api: openai-completions\n      baseURL: %s\n      defaultContextWindow: 131072\n"
            "      models:\n        - id: %s\n          name: %s\n" % (clean(model), clean(base), clean(model), clean(model)))


def patch_yaml(settings: str) -> str:
    """The same settings as dsh's own profile patch (profiles/headless/cordis.patch.yml), in the form dsh writes it when
    it imports settings.yaml: one entry per section, the section's lines under `config:`."""
    out, body = [], []

    def flush(sec):
        if sec:
            out.append('- id: %s\n  name: "@deepseek-ai/dsh-%s"\n  config:\n%s' % (sec, sec, "".join("  " + ln + "\n" for ln in body)))
    sec = ""
    for ln in settings.splitlines():
        if ln and not ln.startswith(" ") and ln.endswith(":"):
            flush(sec)
            sec, body = ln[:-1], []
        elif ln.strip():
            body.append(ln)
    flush(sec)
    return "".join(out)


def prepare_home(home: Path, provider: dict) -> Path:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    text = settings_yaml(provider)
    (home / "settings.yaml").write_text(text, encoding="utf-8")
    # dsh imports settings.yaml only after it has read its profile, so every run used the PREVIOUS run's model - the
    # requested model was never in the provider list (UNKNOWN_MODEL on the Mac, run after run). The profile is written
    # directly too, so this run's model is the one dsh starts with.
    prof = home / "profiles" / "headless"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "cordis.patch.yml").write_text(patch_yaml(text), encoding="utf-8")
    return home


def env_for(home: Path, provider: dict, base: dict | None = None) -> dict:
    env = dict(base if base is not None else os.environ)
    key = str(provider.get("key") or "")
    env["DSH_HOME"] = str(home)
    env.setdefault("DSH_PERMISSION_MODE", "workspace-write")
    env.setdefault("DSH_TELEMETRY_DISABLED", "1")
    if key and key != "none":
        env["DEEPSEEK_API_KEY"] = key
        env["LOKI_DSH_KEY"] = key
    else:
        env.setdefault("LOKI_DSH_KEY", "none")
    try:
        import opencode_engine  # pylint: disable=import-outside-toplevel
        env["PATH"] = os.pathsep.join([env.get("PATH", "")] + [d for d in opencode_engine._global_bins() if Path(d).is_dir()])  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass
    return env


# ------------------------------------------------------------------ what really happened in the folder
def snapshot(root: Path) -> dict:
    """path -> (size, mtime) for the workspace's files (git's own objects left out, but .git/HEAD counted)."""
    out: dict = {}
    root = Path(root)
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        parts = set(Path(rel_dir).parts)
        if ".git" in parts:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for d in list(dirs):
            if d == ".git" and (Path(dirpath) / d / "HEAD").is_file():
                log = Path(dirpath) / d / "logs" / "HEAD"     # grows with every commit: a commit counts as a change
                try:
                    st = log.stat()
                    out[os.path.normpath(os.path.join(rel_dir, ".git/HEAD"))] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    out[os.path.normpath(os.path.join(rel_dir, ".git/HEAD"))] = (1, 0)
        for f in files:
            p = Path(dirpath) / f
            try:
                st = p.stat()
            except OSError:
                continue
            out[os.path.normpath(os.path.join(rel_dir, f))] = (st.st_size, st.st_mtime_ns)
            if len(out) >= MAX_FILES:
                return out
    return out


def changes(before: dict, after: dict) -> list:
    made = sorted(k for k in after if k not in before)
    changed = sorted(k for k in after if k in before and after[k] != before[k])
    gone = sorted(k for k in before if k not in after)
    return [("made", k) for k in made] + [("changed", k) for k in changed] + [("removed", k) for k in gone]


STALL_S = float(os.getenv("LOKI_DSH_STALL_S", "900") or 900)
MODEL_NAME_FIX_T = 1793240484.0     # 2026-10-29: dsh starts with this run's model (profile written directly) from here on
BENCH_S = float(os.getenv("LOKI_DSH_BENCH_S", "86400") or 86400)


def _health_file(home) -> Path:
    return Path(home) / "health.json"


def benched(home, name: str, now: float | None = None) -> str:
    """Why dsh is benched for this provider on this computer ("" = use it). A run that failed or stalled benches it
    for a day (LOKI_DSH_BENCH_S); OpenCode does the work meanwhile."""
    import json  # pylint: disable=import-outside-toplevel
    try:
        data = json.loads(_health_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    entry = data.get(name) or {}
    if "UNKNOWN_MODEL" in str(entry.get("why") or "") and float(entry.get("t") or 0) < MODEL_NAME_FIX_T:
        return ""     # benched by LOKI's own model-name bug (fixed: slash-free alias); try it again
    if entry.get("ok") is False and (now or time.time()) - float(entry.get("t") or 0) < BENCH_S:
        return str(entry.get("why") or "it failed")
    return ""


def record(home, name: str, ok: bool, why: str = "") -> None:
    import json  # pylint: disable=import-outside-toplevel
    f = _health_file(home)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[name] = {"ok": bool(ok), "t": time.time(), "why": str(why)[:300]}
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass
TICK_S = 60.0


def run_turn(prompt: str, workspace: str, *, exe: str, env: dict, timeout: float = 3600.0,
             cancelled: Callable[[], bool] | None = None, popen: Callable = subprocess.Popen,
             on_line: Callable[[str], None] | None = None, on_tick: Callable[[str], None] | None = None,
             stall_s: float | None = None, tick_s: float | None = None) -> dict:
    """One headless dsh turn in the workspace -> {text, exit, changes, error, seconds}.

    dsh prints nothing until its final message, so a watchdog looks at the folder every minute: `on_tick` gets a
    "still working - N files changed" line, and a turn with no output and no change in the folder for `stall_s`
    (LOKI_DSH_STALL_S, default 15 min) is stopped instead of running to the hour (2026-10-25: a pixel check sat
    silent on the Mac while dsh could not read DeepSeek's text tool calls)."""
    ws = Path(workspace)
    before = snapshot(ws)
    started = time.time()
    stall = STALL_S if stall_s is None else stall_s
    tick = TICK_S if tick_s is None else tick_s
    try:
        proc = popen([exe, "--profile", "headless", prompt], cwd=str(ws), env=env, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"text": "", "exit": -1, "changes": [], "error": "dsh did not start: %s" % exc, "seconds": 0.0}
    out_lines: list = []
    err_box: list = []

    def read_err() -> None:
        try:
            err_box.append(proc.stderr.read() or "")
        except Exception:  # noqa: BLE001
            pass
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    stalled: list = []
    done = threading.Event()

    def watch() -> None:
        last_seen, last_change, last_lines = before, time.time(), 0
        while not done.wait(tick):
            now_snap = snapshot(ws)
            if now_snap != last_seen or len(out_lines) != last_lines:
                last_seen, last_change, last_lines = now_snap, time.time(), len(out_lines)
            if on_tick:
                try:
                    on_tick("DeepSeek Harness still working (%d min, %d file(s) changed so far)"
                            % ((time.time() - started) // 60, len(changes(before, now_snap))))
                except Exception:  # noqa: BLE001
                    pass
            if stall and time.time() - last_change > stall:
                stalled.append(int(time.time() - last_change))
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                return
    w = threading.Thread(target=watch, daemon=True)
    w.start()
    try:
        for line in proc.stdout:
            out_lines.append(line)
            if on_line:
                on_line(line.rstrip("\n"))
            if cancelled and cancelled():
                proc.terminate()
                break
            if time.time() - started > timeout:
                proc.terminate()
                break
        proc.wait(timeout=30)
    except Exception:  # noqa: BLE001 - a hung harness never hangs LOKI
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    done.set()
    t.join(2)
    text = "".join(out_lines).strip()
    code = proc.returncode if proc.returncode is not None else -1
    err = ""
    if stalled:
        err = "dsh made no progress for %d min (no output, nothing changed in the folder) - stopped" % (stalled[0] // 60)
    elif cancelled and cancelled():
        err = "stopped"
    elif time.time() - started > timeout:
        err = "dsh ran past %d s" % timeout
    elif code != 0 and not text:
        err = ("dsh exited %s: %s" % (code, ("".join(err_box) or "").strip()[-400:])).strip()
    return {"text": text, "exit": code, "changes": changes(before, snapshot(ws)), "error": err,
            "seconds": round(time.time() - started, 1)}


def describe(chs: list, limit: int = 12) -> str:
    if not chs:
        return "nothing changed in the folder"
    shown = ["%s %s" % (k, p) for k, p in chs[:limit]]
    return "; ".join(shown) + (" (and %d more)" % (len(chs) - limit) if len(chs) > limit else "")
