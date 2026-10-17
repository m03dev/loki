"""Music: songs made on this computer with ACE-Step 1.5 (free, local, MIT).

The protocol is ACE-Step 1.5's REST API (ace-step/ACE-Step-1.5, docs/en/API.md; the server is
`uv run acestep-api`, http://localhost:8001): POST /release_task with the prompt, lyrics and
settings -> {"data": {"task_id", "status": "queued"}}; POST /query_result with task_id_list until
a task's status is 1 (done) or 2 (failed), its `result` being a JSON string of entries with a
`file`; GET /v1/audio?path=<file> for the audio. Optional `Authorization: Bearer` when the
server has a key. MIT - see engine/licenses/ACE-Step-MIT.txt. Written on the standard library;
no ACE-Step code is copied (it runs as its own program).

Why ACE-Step: an MIT music model that runs in under 4 GB of VRAM (2B turbo DiT; the 0.6B LM fits
the PC's 8 GB RTX 3070 Ti) and on Apple Silicon (MPS/MLX), with lyrics, BPM, key and duration.
Install once per machine: git clone https://github.com/ace-step/ACE-Step-1.5 ; cd ACE-Step-1.5 ;
uv sync ; uv run acestep-api. LOKI_ACESTEP_URL points elsewhere (another machine on the LAN).
The opener and sleep are injected; tests use a fake server.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8001"
POLL_S = 3.0
TIMEOUT_S = 900          # a song on a small GPU can take minutes
SETUP_HINT = ("ACE-Step is not running. Install it once on this machine: git clone "
              "https://github.com/ace-step/ACE-Step-1.5 && cd ACE-Step-1.5 && uv sync, then start "
              "`uv run acestep-api` (http://localhost:8001). Set LOKI_ACESTEP_URL to use another machine.")


def base_url(env=None) -> str:
    env = os.environ if env is None else env
    return str(env.get("LOKI_ACESTEP_URL", "") or DEFAULT_URL).rstrip("/")


def _headers(env=None) -> dict:
    env = os.environ if env is None else env
    key = str(env.get("LOKI_ACESTEP_KEY", "") or "").strip()
    head = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        head["Authorization"] = "Bearer " + key
    return head


def _post(opener, url: str, body: dict, env=None, timeout: float = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=_headers(env), method="POST")
    with opener(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


def task_body(prompt: str, lyrics: str = "", duration: float = 0, bpm: int = 0, key_scale: str = "",
              language: str = "en", audio_format: str = "mp3", seed: int = -1) -> dict:
    body = {"prompt": str(prompt or "").strip(), "lyrics": str(lyrics or "").strip(), "task_type": "text2music",
            "vocal_language": language or "en", "audio_format": audio_format or "mp3", "batch_size": 1,
            "inference_steps": 8, "guidance_scale": 7.0}
    if duration and float(duration) > 0:
        body["audio_duration"] = max(5.0, min(float(duration), 240.0))
    if bpm and int(bpm) > 0:
        body["bpm"] = int(bpm)
    if key_scale:
        body["key_scale"] = str(key_scale)
    if seed is not None and int(seed) >= 0:
        body["use_random_seed"], body["seed"] = False, int(seed)
    return body


def parse_result(entry: dict) -> list:
    """The audio file paths of one finished task (`result` is a JSON string in ACE-Step's reply)."""
    raw = entry.get("result")
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        items = []
    if isinstance(items, dict):
        items = [items]
    return [str(i.get("file")) for i in items if isinstance(i, dict) and i.get("file")]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48] or "song"


def make(prompt: str, out_dir: Path, lyrics: str = "", duration: float = 0, bpm: int = 0, key_scale: str = "",
         language: str = "en", seed: int = -1, opener=None, sleep=time.sleep, clock=time.monotonic,
         env=None, timeout: float = TIMEOUT_S) -> dict:
    """Submit, wait, download. Returns {"ok", "files": [paths], "task_id"} or {"ok": False, "error"}."""
    if not str(prompt or "").strip() and not str(lyrics or "").strip():
        return {"ok": False, "error": "say what the music should be (genre, mood, instruments) or give lyrics"}
    opener = opener or urllib.request.urlopen
    url = base_url(env)
    try:
        submitted = _post(opener, url + "/release_task",
                          task_body(prompt, lyrics, duration, bpm, key_scale, language, "mp3", seed), env)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": "%s (%s)" % (SETUP_HINT, exc)}
    data = submitted.get("data") or {}
    task_id = data.get("task_id")
    if not task_id:
        return {"ok": False, "error": "ACE-Step did not accept the task: %s" % (submitted.get("error") or submitted)}
    started = clock()
    files: list = []
    while True:
        try:
            polled = _post(opener, url + "/query_result", {"task_id_list": [task_id]}, env)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"ok": False, "error": "lost ACE-Step while it worked: %s" % exc, "task_id": task_id}
        entries = polled.get("data") or []
        entry = next((e for e in entries if isinstance(e, dict) and e.get("task_id") == task_id), None) or \
            (entries[0] if entries and isinstance(entries[0], dict) else {})
        status = int(entry.get("status", 0) or 0)
        if status == 1:
            files = parse_result(entry)
            break
        if status == 2:
            return {"ok": False, "error": "ACE-Step could not make it: %s" % (entry.get("result") or "failed"),
                    "task_id": task_id}
        if clock() - started > timeout:
            return {"ok": False, "error": "ACE-Step took longer than %d s" % timeout, "task_id": task_id}
        sleep(POLL_S)
    if not files:
        return {"ok": False, "error": "ACE-Step finished but returned no audio", "task_id": task_id}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for i, remote in enumerate(files, 1):
        ext = Path(urllib.parse.urlparse(remote).path).suffix or ".mp3"
        target = out_dir / ("%s-%s%s%s" % (stamp, slug(prompt or lyrics), "" if i == 1 else "-%d" % i, ext))
        src = remote if remote.startswith("http") else url + "/v1/audio?" + urllib.parse.urlencode({"path": remote})
        req = urllib.request.Request(src, headers={k: v for k, v in _headers(env).items() if k == "Authorization"})
        try:
            with opener(req, timeout=120) as resp:
                target.write_bytes(resp.read())
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "error": "could not download the song: %s" % exc, "task_id": task_id}
        saved.append(target)
    return {"ok": True, "files": saved, "task_id": task_id}
