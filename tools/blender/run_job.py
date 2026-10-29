"""Run one LOKI Blender job in a background Blender (no window) with the same core a window uses:

    blender --background --factory-startup --python run_job.py -- <loki_blender_core.py> <job.json> <answer.json>

engine/blender_link.py run() uses it when no Blender window with LOKI's loader is open, so LOKI never needs the owner
to open Blender. The answer file is written even when the job fails (with the traceback).
"""
import importlib.util
import json
import sys
import time
import traceback
from pathlib import Path

args = sys.argv[sys.argv.index("--") + 1:]
core_path, job_path, answer_path = args[:3]
answer = {"job": Path(job_path).name, "ok": False}
try:
    spec = importlib.util.spec_from_file_location("loki_blender_core", core_path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    core.start(lambda *p: print("LOKI:", *p), Path(answer_path).parent)
    answer = core.run_job_file(job_path)
except Exception:  # noqa: BLE001
    answer["error"] = traceback.format_exc()[-3000:]
answer["finished"] = time.time()
Path(answer_path).write_text(json.dumps(answer, indent=2, default=str), encoding="utf-8")
print("LOKI_JOB_DONE", json.dumps({"ok": answer.get("ok"), "answer": answer_path}))
