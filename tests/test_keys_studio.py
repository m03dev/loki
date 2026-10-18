"""Keys that stay saved, and a Studio that answers (owner, 2026-10-18: "why arnt my api keys saving ...
it needs to save per user"; Studio said "model 'qwen3:8b' not found" to every message).

    python tests/test_keys_studio.py      (< 5 s, offline: temp folders, no network, no real Studio)

engine/user_keys.py keeps every provider key in one per-user file that every copy of LOKI on the
account loads; Connect saves there, Disconnect forgets there; a key LOKI could not check (offline)
is saved anyway. Studio re-reads keys per request, picks an INSTALLED local model, and LOKI's tab
replaces a Studio server that runs old code (unless a session is working).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-keys-"))
os.environ["LOKI_USER_KEYS"] = str(TMP / "home" / ".loki" / "keys.env")
os.environ["LOKI_DATA"] = str(TMP / "data")
(TMP / "data").mkdir(parents=True)
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "studio"))

import user_keys  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


# ---------------------------------------------------------------- the per-user key file
check("provider keys are keys", all(user_keys.is_key(n) for n in
                                    ("NVIDIA_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN", "CLOUDFLARE_ACCOUNT_ID")))
check("machine settings are not", not any(user_keys.is_key(n) for n in
                                          ("LOKI_PEER_SECRET", "LOKI_MODEL", "GEMINI_MODEL", "LOKI_PEERS", "PATH")))
user_keys.update({"NVIDIA_API_KEY": "nvapi-test-1", "LOKI_MODEL": "smart"})
check("a saved key is in the per-user file", user_keys.read() == {"NVIDIA_API_KEY": "nvapi-test-1"}, user_keys.read())
if sys.platform != "win32":
    check("the file is private (600)", (user_keys.path().stat().st_mode & 0o777) == 0o600)
env = {}
check("a fresh LOKI process gets it", user_keys.load_into(env) == ["NVIDIA_API_KEY"] and env["NVIDIA_API_KEY"] == "nvapi-test-1")
env = {"NVIDIA_API_KEY": "from-checkout"}
user_keys.load_into(env)
check("a checkout's own key still wins", env["NVIDIA_API_KEY"] == "from-checkout")
dotenv = TMP / "old.env"
dotenv.write_text("# comment\nGEMINI_API_KEY=g-1\nGROQ_API_KEY=\nLOKI_PEER_SECRET=s\nNVIDIA_API_KEY=other\n", encoding="utf-8")
check("keys already in a .env are adopted (never overwriting)", user_keys.adopt(dotenv) == ["GEMINI_API_KEY"]
      and user_keys.read() == {"NVIDIA_API_KEY": "nvapi-test-1", "GEMINI_API_KEY": "g-1"}, user_keys.read())
user_keys.update({"GEMINI_API_KEY": None})
check("Disconnect forgets it", "GEMINI_API_KEY" not in user_keys.read())

# ---------------------------------------------------------------- write_env (Disconnect, Cloudflare id) keeps them in step
import peer_link  # noqa: E402

peer_link.write_env(TMP / "data" / ".env", {"MISTRAL_API_KEY": "m-1", "LOKI_UPDATE_EVERY_S": "300"})
check("a key written to .env is saved per user", user_keys.read().get("MISTRAL_API_KEY") == "m-1"
      and "LOKI_UPDATE_EVERY_S" not in user_keys.read())
peer_link.write_env(TMP / "data" / ".env", {"MISTRAL_API_KEY": None})
check("removing it from .env forgets it per user", "MISTRAL_API_KEY" not in user_keys.read())

# ---------------------------------------------------------------- connect: an unreachable check still saves
src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("Connect saves a key it could not check", 'unchecked = reason.startswith("Could not reach")' in src
      and "if reason and not unchecked:" in src)
check("Connect saves per user", "user_keys.update({name: value})" in src)
check("the engine loads per-user keys at start", "_user_keys.load_into()" in src)

# ---------------------------------------------------------------- Studio: keys per request, an installed local model
import studio_paths  # noqa: E402
import studio_models  # noqa: E402
import model_setup  # noqa: E402

os.environ.pop("NVIDIA_API_KEY", None)
user_keys.update({"NVIDIA_API_KEY": "nvapi-test-2"})
nim = [p for p in studio_models.providers() if p.id == "nvidia"][0]
check("Studio sees a key saved after it started", os.environ.get("NVIDIA_API_KEY") == "nvapi-test-2" and nim.ready(),
      os.environ.get("NVIDIA_API_KEY"))
(TMP / "data" / "app").mkdir(parents=True, exist_ok=True)
(TMP / "data" / "app" / "status.json").write_text(json.dumps({"local": {"name": "loki-qwen3.5-9b-agent"}}), encoding="utf-8")


def pick(installed, env=None):
    model_setup.ollama_models = lambda: None if installed is None else [{"name": n} for n in installed]
    studio_models._LOCAL_PICK.update(at=0.0, name="")
    return studio_models.local_model(env or {})


check("Studio uses the engine's model when it is installed",
      pick(["qwen3.5:9b-q4_K_M", "loki-qwen3.5-9b-agent:latest"]) == "loki-qwen3.5-9b-agent")
check("never a model that is not installed (the Mac had no qwen3:8b)",
      pick(["nomic-embed-text:latest", "qwen3.5:9b-q4_K_M"]) == "qwen3.5:9b-q4_K_M")
check("a pinned model still wins", pick(["x"], {"LOKI_STUDIO_LOCAL_MODEL": "mine"}) == "mine")

# ---------------------------------------------------------------- LOKI's tab replaces a stale Studio
import studio_api  # noqa: E402

data = TMP / "data"
(data / "studio" / "pinned" / "studio").mkdir(parents=True)
(data / "studio" / "pinned" / "studio" / "studio_app.py").write_text("", encoding="utf-8")
(data / "studio" / "pin.json").write_text(json.dumps({"commit": "aaa", "next": "bbb"}), encoding="utf-8")
check("the Studio it should run is the cleared pin move", studio_api.wanted_code(data) == "bbb")
check("old code is stale", studio_api.stale({"code": "aaa"}, data))
check("a Studio too old to say is stale", studio_api.stale({}, data))
check("the right code is not", not studio_api.stale({"code": "bbb"}, data))
sess = data / "studio" / "sessions" / "s1"
sess.mkdir(parents=True)
(sess / "session.json").write_text(json.dumps({"status": "working", "updated": time.time()}), encoding="utf-8")
check("never restarted under a working session", studio_api.busy(data))
(sess / "session.json").write_text(json.dumps({"status": "idle", "updated": time.time()}), encoding="utf-8")
check("an idle Studio can be restarted", not studio_api.busy(data))
calls = []
studio_api.running = lambda d: ({"port": 1, "pid": 99999999, "token": "t", "code": "aaa"} if not calls else {})
studio_api.stop = lambda info, wait_s=4.0: calls.append(info["pid"])
studio_api._EMBED["t"] = 0.0
out = studio_api.embed(data, popen=lambda *a, **k: calls.append("spawn"))
check("the tab stops the stale Studio and starts a fresh one", calls == [99999999, "spawn"] and out.get("starting"), (calls, out))
server_src = (REPO / "studio" / "studio_server.py").read_text(encoding="utf-8")
check("Studio says which code it runs", '"code": _code_commit()' in server_src)

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
