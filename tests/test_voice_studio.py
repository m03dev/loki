"""Voices through VoiceStudio (engine/voice_studio.py): a fake VoiceStudio backend on 127.0.0.1 answers the same routes
the real one does (backend/main.py /health, api/routers generation /generate, profiles /profiles, capture /transcribe,
/design/describe). Offline, a few seconds.

    python tests/test_voice_studio.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-voice-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


WAV = b"RIFF" + b"\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28
SEEN: dict = {"forms": []}


def fields(body: bytes, ctype: str) -> dict:
    boundary = ctype.split("boundary=")[1].encode()
    out = {}
    for part in body.split(b"--" + boundary):
        if b"Content-Disposition" not in part:
            continue
        head, _, val = part.partition(b"\r\n\r\n")
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        out[name] = val[:-2] if val.endswith(b"\r\n") else val
    return out


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj=None, code=200, raw=None, headers=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send({"status": "ok", "device": "cuda", "version": "0.9.1"})
        if self.path == "/profiles":
            return self._send([{"id": "p1", "name": "Narrator Ann", "kind": "design", "language": "en"}])
        return self._send({"detail": "no"}, 404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        SEEN["client"] = self.headers.get("X-OmniVoice-Client-Id")
        if self.path == "/design/describe":
            d = json.loads(body)
            if "zzz" in d["description"]:
                return self._send({"matched": False, "unmatched": ["zzz"]})
            return self._send({"matched": True, "attrs": {"gender": "male", "age": "elderly"}, "instruct": "", "unmatched": []})
        f = fields(body, self.headers["Content-Type"])
        SEEN["forms"].append((self.path, f))
        if self.path == "/generate":
            return self._send(raw=WAV, headers={"X-Audio-Id": "a1", "X-Gen-Time": "1.2", "X-Audio-Duration": "2.5"})
        if self.path == "/profiles":
            return self._send({"id": "p9", "name": f["name"].decode(), "kind": f["kind"].decode()})
        if self.path == "/transcribe":
            return self._send({"text": "Hello there. General Kenobi.", "language": "en",
                               "segments": [{"start": 0.0, "end": 1.25, "text": "Hello there."},
                                            {"start": 1.25, "end": 3.5, "text": "General Kenobi."}]})
        return self._send({"detail": "no"}, 404)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["VOICESTUDIO_URL"] = "http://127.0.0.1:%d" % srv.server_address[1]

import voice_studio as vs  # noqa: E402

st = vs.status()
check("status: running, version, device, its MCP address", st["running"] and st["version"] == "0.9.1"
      and st["device"] == "cuda" and st["mcp"].endswith("/mcp/"), st)
ws = TMP / "ws"
ws.mkdir()
r = vs.tool({"action": "speak", "text": "Welcome, traveller!", "voice": "narrator ann", "instruct": "narrator"}, ws)
form = SEEN["forms"][-1][1]
check("speak: a WAV in audio/, the voice found by name, the style sent", r.get("ok") and (ws / r["file"]).read_bytes() == WAV
      and r["file"].startswith("audio/") and form["profile_id"] == b"p1" and form["instruct"] == b"narrator"
      and form["text"] == b"Welcome, traveller!" and r["seconds"] == "2.5", (r, form))
check("LOKI names itself to VoiceStudio (per-agent voices)", SEEN["client"] == "loki")
r = vs.tool({"action": "speak", "text": "x", "voice": "nobody"}, ws)
check("an unknown voice is said plainly", not r["ok"] and "no saved voice" in r["error"], r)
r = vs.tool({"action": "voices"}, ws)
check("voices lists the saved ones", r["ok"] and r["voices"][0]["name"] == "Narrator Ann", r)
rec = ws / "me.wav"
rec.write_bytes(WAV)
r = vs.tool({"action": "clone", "name": "Mo", "audio": "me.wav", "ref_text": "hello"}, ws)
form = SEEN["forms"][-1][1]
check("clone uploads the recording as a clone profile", r["ok"] and r["id"] == "p9" and form["kind"] == b"clone"
      and form["ref_audio"] == WAV, (r, list(form)))
r = vs.tool({"action": "design", "name": "Old wizard", "description": "elderly male narrator"}, ws)
form = SEEN["forms"][-1][1]
check("design maps the description, then saves a design profile with those attributes", r["ok"]
      and json.loads(form["vd_states"]) == {"gender": "male", "age": "elderly"} and form["kind"] == b"design", (r, form))
r = vs.tool({"action": "design", "name": "?", "description": "zzz"}, ws)
check("a description it cannot map is refused with the words it did not know", not r["ok"] and "zzz" in r["error"], r)
clip = ws / "trailer.mp4"
clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
r = vs.tool({"action": "transcribe", "audio": "trailer.mp4"}, ws)
srt = (ws / r["srt"]).read_text() if r.get("srt") else ""
check("transcribe: the text and a .srt beside the video with real timings", r["ok"] and r["text"].startswith("Hello")
      and "1\n00:00:00,000 --> 00:00:01,250\nHello there." in srt and "00:00:01,250 --> 00:00:03,500" in srt, (r, srt))
check("transcribe asks for word timing (accurate mode) when captions are wanted", SEEN["forms"][-1][1].get("mode") == b"accurate")
ran = []
r = vs.tool({"action": "install"}, ws, ask=lambda *_a: False, run=lambda *a, **k: ran.append(a))
check("install asks the owner first; 'no' installs nothing", not r["ok"] and not ran, r)


class P:
    returncode = 0
    stdout = "installed"
    stderr = ""


r = vs.tool({"action": "install"}, ws, ask=lambda *_a: True, run=lambda cmd, **k: (ran.append(cmd), P())[1])
check("install runs VoiceStudio's official installer for this OS", r["ok"] and ran and ran[-1] == vs.install_command(), ran)
check("Windows gets the PowerShell installer", "irm https://voicestudio.sh/install | iex" in " ".join(vs.install_command("win32")))
check("OpenCode gets VoiceStudio's MCP server while it runs", vs.mcp_entry()["url"].endswith("/mcp/"))
import make_mcp  # noqa: E402
check("the agents' tool server lists 'voice'", any(t["name"] == "voice" for t in make_mcp.TOOLS) and make_mcp.CLI["voice"] == "voice")
srv.shutdown()
srv.server_close()
r = vs.tool({"action": "speak", "text": "hi"}, ws)
check("VoiceStudio closed: it says so and how to get it", not r["ok"] and "not running" in r["error"], r)
check("and no MCP entry for OpenCode", vs.mcp_entry(timeout=0.5) == {})

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
