"""Loki's self-improvement loop: learn from verified work, fine-tune, promote only if better.

Run with Loki's own Python (harness_data/.venv). Training itself runs in the separate
training environment (tools/setup_training.bat / .sh), on the GPU.

    python tools/self_improve.py status     what has been gathered, GPU, last run
    python tools/self_improve.py dataset    write train/eval JSONL from verified trajectories
    python tools/self_improve.py train      fine-tune (needs enough NEW examples, or --force)
    python tools/self_improve.py eval       score the candidate against the current local models
    python tools/self_improve.py promote    make the candidate the one routing uses
    python tools/self_improve.py cycle      dataset -> train -> eval -> promote if it won
    python tools/self_improve.py schedule   run `cycle` nightly (Windows Task Scheduler / cron)

The rules that keep this honest:
* only DONE + every-file-verified requests become training data (experience.py);
* a candidate is PROMOTED only if it beats every model it would displace on held-out tasks
  by --margin, so a bad run can never make Loki worse; otherwise it is discarded;
* nothing trains while the GPU is busy (a game, a render) unless --force.

Evaluation is a cheap proxy, stated plainly: for each held-out task the model sees the
conversation up to the first assistant turn and must make the same KIND of first move the
verified run made - call the same tool, or answer in text. It does not replay whole tasks.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "addons" / "loki" / "harness"
sys.path.insert(0, str(HARNESS))

import experience  # noqa: E402


def load_env() -> None:
    """Read harness_data/.env (this script runs outside the bridge, which normally does it)."""
    path = experience.root_dir().parent / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

CANDIDATE = "loki-tuned-candidate"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MIN_NEW_EXAMPLES = int(os.getenv("LOKI_TRAIN_MIN_NEW", "200"))
MARGIN = float(os.getenv("LOKI_PROMOTE_MARGIN", "0.02"))
MIN_EVAL = int(os.getenv("LOKI_EVAL_MIN", "10"))


def data_root() -> Path:
    return experience.root_dir().parent


def exp_dir() -> Path:
    return experience.root_dir()


def dataset_dir() -> Path:
    return exp_dir() / "dataset"


def train_python() -> Path:
    venv = data_root() / "train_venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# --- GPU -------------------------------------------------------------------------

def gpu_state() -> dict:
    """{'name', 'used_mb', 'total_mb', 'util'} from nvidia-smi, or {} when there is none."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True,
                             timeout=15).stdout.strip().splitlines()
    except Exception:
        return {}
    if not out:
        return {}
    parts = [p.strip() for p in out[0].split(",")]
    try:
        return {"name": parts[0], "used_mb": int(parts[1]), "total_mb": int(parts[2]),
                "util": int(parts[3])}
    except (IndexError, ValueError):
        return {}


def gpu_busy(state: dict, max_used_mb: int = 1500, max_util: int = 30) -> str:
    """Why the GPU is not free right now, or "" when training may start."""
    if not state:
        return "no NVIDIA GPU found (nvidia-smi is not on PATH)"
    if state["used_mb"] > max_used_mb or state["util"] > max_util:
        return ("the GPU is in use (%d MB, %d%%) - a game or a render is probably running"
                % (state["used_mb"], state["util"]))
    return ""


# --- Ollama ----------------------------------------------------------------------

def _ollama(path: str, payload: dict | None = None, url: str = "", timeout: float = 300) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request((url or OLLAMA_URL) + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def ollama_models(url: str = "") -> list:
    try:
        return [m.get("name", "") for m in _ollama("/api/tags", url=url, timeout=5).get("models", [])]
    except Exception:
        return []


def has_model(name: str, url: str = "") -> bool:
    names = ollama_models(url)
    return any(n == name or n.split(":")[0] == name or n == name + ":latest" for n in names)


# --- evaluation ------------------------------------------------------------------

def first_move(messages: list) -> tuple:
    """(prefix messages, expected move) - the move is ('tool', name) or ('text', '')."""
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            calls = message.get("tool_calls") or []
            if calls:
                return messages[:index], ("tool", calls[0].get("function", {}).get("name", ""))
            return messages[:index], ("text", "")
    return messages, ("text", "")


def score_move(expected: tuple, reply: dict) -> float:
    """1 for the same move, 0.5 for a different but well-formed tool call, else 0."""
    calls = reply.get("tool_calls") or []
    if expected[0] == "tool":
        if not calls:
            return 0.0
        name = (calls[0].get("function") or {}).get("name", "")
        return 1.0 if name == expected[1] else 0.5
    if calls:
        return 0.0
    return 1.0 if str(reply.get("content") or "").strip() else 0.0


def evaluate(model: str, eval_file: Path, url: str = "", limit: int = 0) -> dict:
    """Average first-move score of `model` over the held-out set."""
    rows = [json.loads(l) for l in eval_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    if limit > 0:
        rows = rows[:limit]
    scores, errors = [], 0
    for row in rows:
        prefix, expected = first_move(row["messages"])
        try:
            answer = _ollama("/api/chat", {"model": model, "messages": prefix,
                                          "tools": row.get("tools") or [], "stream": False, "think": False,
                                          "options": {"temperature": 0}}, url=url)
            scores.append(score_move(expected, answer.get("message") or {}))
        except Exception:
            errors += 1
            scores.append(0.0)
    mean = round(sum(scores) / len(scores), 4) if scores else 0.0
    return {"model": model, "n": len(scores), "score": mean, "errors": errors}


def decide(candidate: dict, baselines: list, margin: float = MARGIN, min_eval: int = MIN_EVAL) -> tuple:
    """(promote?, reason). The candidate must beat EVERY baseline by `margin`."""
    if candidate["n"] < min_eval:
        return False, "only %d held-out tasks (need %d) - not enough evidence" % (candidate["n"], min_eval)
    if candidate["errors"] > candidate["n"] // 4:
        return False, "the candidate failed to answer %d of %d tasks" % (candidate["errors"], candidate["n"])
    for base in baselines:
        if candidate["score"] < base["score"] + margin:
            return False, ("%.3f does not beat %s (%.3f) by %.2f"
                           % (candidate["score"], base["model"], base["score"], margin))
    best = max((b["score"] for b in baselines), default=0.0)
    return True, "%.3f beats the best current local model (%.3f)" % (candidate["score"], best)


# --- the steps ---------------------------------------------------------------------

def tool_schemas() -> dict:
    """Loki's own tool schemas by name (MCP tools are added at runtime, not here)."""
    try:
        import loki  # noqa: E402
        return {t["function"]["name"]: t for t in loki.TOOL_SCHEMAS}
    except Exception as exc:
        print("[self-improve] could not load Loki's tool schemas: %s" % exc)
        return {}


def baseline_models() -> list:
    """The local models a promoted candidate would displace."""
    names = [os.getenv("LOKI_EVAL_BASELINE", "qwen3:8b")]
    if str(os.getenv("LOKI_TUNED_PROMOTED", "0")).strip() == "1":
        names.append(os.getenv("LOKI_TUNED_MODEL", "loki-tuned"))
    return [n for n in names if n]


def set_env_value(key: str, value: str) -> Path:
    """Set KEY=value in harness_data/.env, keeping every other line."""
    path = data_root() / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append("%s=%s" % (key, value))
            done = True
        else:
            out.append(line)
    if not done:
        out.append("%s=%s" % (key, value))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def cmd_status(_args) -> int:
    info = experience.summary()
    state = experience.train_state()
    gpu = gpu_state()
    print("requests logged:     %d  %s" % (info["requests"], json.dumps(info["outcomes"])))
    print("verified examples:   %d  (%d new since the last training run; training starts at %d)"
          % (info["trajectories"], experience.new_examples(), MIN_NEW_EXAMPLES))
    print("GPU:                 %s" % (("%s, %d/%d MB used, %d%% busy" % (gpu["name"], gpu["used_mb"],
                                         gpu["total_mb"], gpu["util"])) if gpu else "none found"))
    print("training env:        %s" % ("ready" if train_python().is_file() else
                                       "not set up - run tools/setup_training.bat or .sh"))
    print("Ollama models:       %s" % (", ".join(ollama_models()) or "Ollama not reachable"))
    print("promoted model:      %s" % (os.getenv("LOKI_TUNED_MODEL", "loki-tuned")
                                       if os.getenv("LOKI_TUNED_PROMOTED") == "1" else "none yet"))
    for run in state.get("history", [])[-5:]:
        print("  run %s: %s" % (time.strftime("%Y-%m-%d %H:%M", time.localtime(run.get("t", 0))),
                                run.get("result", "")))
    stats = experience.provider_stats()
    if stats:
        print("provider success (requests that wrote files):")
        for name, s in sorted(stats.items(), key=lambda kv: -(kv[1]["samples"])):
            print("  %-14s %3d judged  success %s" % (name, s["samples"],
                  "-" if s["success_rate"] is None else "%.0f%%" % (100 * s["success_rate"])))
    return 0


def cmd_dataset(_args) -> int:
    info = experience.build_dataset(dataset_dir(), tool_schemas())
    print("[self-improve] dataset: %d train, %d eval -> %s" % (info["train"], info["eval"], dataset_dir()))
    return 0


def cmd_train(args) -> int:
    new = experience.new_examples()
    if new < MIN_NEW_EXAMPLES and not args.force:
        print("[self-improve] %d new verified examples; training starts at %d (or use --force)"
              % (new, MIN_NEW_EXAMPLES))
        return 0
    reason = gpu_busy(gpu_state())
    if reason and not args.force:
        print("[self-improve] not training: " + reason)
        return 0
    if not train_python().is_file():
        print("[self-improve] the training environment is missing - run tools/setup_training.bat (Windows) "
              "or tools/setup_training.sh first")
        return 3
    cmd_dataset(args)
    run_dir = exp_dir() / "runs" / time.strftime("%Y%m%d-%H%M%S")
    cmd = [str(train_python()), str(REPO / "tools" / "train_lora.py"), "--data", str(dataset_dir()),
           "--out", str(run_dir)]
    if args.max_steps:
        cmd += ["--max-steps", str(args.max_steps)]
    print("[self-improve] training: " + " ".join(cmd))
    code = subprocess.call(cmd)
    if code != 0:
        print("[self-improve] training failed (exit %d)" % code)
        return code
    modelfile = run_dir / "gguf" / "Modelfile"
    if not modelfile.is_file() or not shutil.which("ollama"):
        print("[self-improve] trained, but there is no Modelfile or no ollama on PATH to register it")
        return 6
    code = subprocess.call(["ollama", "create", CANDIDATE, "-f", str(modelfile)], cwd=str(modelfile.parent))
    if code != 0:
        return code
    state = experience.train_state()
    state["trained_on"] = len(experience.trajectories())
    state["last_run"] = str(run_dir)
    state.setdefault("history", []).append({"t": time.time(), "run": str(run_dir),
                                            "result": "trained; candidate registered"})
    experience.save_train_state(state)
    print("[self-improve] candidate registered in Ollama as %s" % CANDIDATE)
    return 0


def cmd_eval(args) -> int:
    eval_file = dataset_dir() / "eval.jsonl"
    if not eval_file.is_file():
        print("[self-improve] no eval set - run `dataset` first")
        return 2
    if not has_model(CANDIDATE):
        print("[self-improve] no candidate in Ollama - run `train` first")
        return 2
    candidate = evaluate(CANDIDATE, eval_file, limit=args.limit)
    baselines = [evaluate(m, eval_file, limit=args.limit) for m in baseline_models() if has_model(m)]
    promote, reason = decide(candidate, baselines)
    result = {"t": time.time(), "candidate": candidate, "baselines": baselines,
              "promote": promote, "reason": reason}
    (exp_dir() / "last_eval.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("[self-improve] candidate %.3f vs %s -> %s (%s)" % (
        candidate["score"], ", ".join("%s %.3f" % (b["model"], b["score"]) for b in baselines) or "no baseline",
        "PROMOTE" if promote else "keep current", reason))
    return 0 if promote else 1


def cmd_promote(args) -> int:
    last = exp_dir() / "last_eval.json"
    verdict = json.loads(last.read_text(encoding="utf-8")) if last.is_file() else {}
    if not verdict.get("promote") and not args.force:
        print("[self-improve] the last evaluation did not clear the bar (%s); not promoting"
              % verdict.get("reason", "no evaluation yet"))
        return 1
    target = os.getenv("LOKI_TUNED_MODEL", "loki-tuned")
    if subprocess.call(["ollama", "cp", CANDIDATE, target]) != 0:
        return 1
    set_env_value("LOKI_TUNED_MODEL", target)
    path = set_env_value("LOKI_TUNED_PROMOTED", "1")
    state = experience.train_state()
    state.setdefault("history", []).append({"t": time.time(), "result": "PROMOTED: " + verdict.get("reason", "forced")})
    experience.save_train_state(state)
    print("[self-improve] promoted: smart routing now tries %s before the stock local model "
          "(%s). Restart Loki to pick it up." % (target, path))
    return 0


def cmd_cycle(args) -> int:
    new = experience.new_examples()
    if new < MIN_NEW_EXAMPLES and not args.force:
        print("[self-improve] %d new verified examples (need %d) - nothing to do tonight" % (new, MIN_NEW_EXAMPLES))
        return 0
    code = cmd_train(args)
    if code != 0 or not has_model(CANDIDATE):
        return code
    if cmd_eval(args) == 0:
        return cmd_promote(args)
    state = experience.train_state()
    state.setdefault("history", []).append({"t": time.time(), "result": "candidate did not beat the current model; kept the current one"})
    experience.save_train_state(state)
    return 0


def cmd_schedule(args) -> int:
    python = sys.executable
    script = str(Path(__file__).resolve())
    if os.name == "nt":
        # schtasks wants the program and its arguments as ONE /TR string, with inner quotes
        # escaped as \" - the documented form for paths that contain spaces.
        command = ('schtasks /Create /F /SC DAILY /ST %s /TN "LOKI self-improve" '
                   '/TR "\\"%s\\" \\"%s\\" cycle"' % (args.at, python, script))
        print("[self-improve] " + command)
        return subprocess.call(command)
    hour, minute = args.at.split(":")
    line = '%s %s * * * "%s" "%s" cycle >> "%s" 2>&1' % (int(minute), int(hour), python, script,
                                                       exp_dir() / "cycle.log")
    print("[self-improve] add this line with `crontab -e`:\n" + line)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "dataset", "train", "eval", "promote", "cycle", "schedule"])
    ap.add_argument("--force", action="store_true", help="ignore the example threshold / busy GPU / failed gate")
    ap.add_argument("--max-steps", type=int, default=0, help="cap training steps (a quick trial run)")
    ap.add_argument("--limit", type=int, default=0, help="evaluate on at most N held-out tasks")
    ap.add_argument("--at", default="03:30", help="schedule time, HH:MM (default 03:30)")
    args = ap.parse_args(argv)
    load_env()
    return {"status": cmd_status, "dataset": cmd_dataset, "train": cmd_train, "eval": cmd_eval,
            "promote": cmd_promote, "cycle": cmd_cycle, "schedule": cmd_schedule}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
