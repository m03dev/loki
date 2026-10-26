"""Voices for LOKI through VoiceStudio (github.com/debpalash/VoiceStudio, AGPL-3.0 - the same licence as LOKI; owner
2026-10-25: "add all the tools"). VoiceStudio is a whole local speech app (Electron + a Python backend with its own
PyTorch and models), so LOKI does not copy it in: it installs the app on request and talks to its local backend, the
way VoiceStudio's own MCP server does (backend/mcp_server.py: the same routes).

    http://127.0.0.1:3900 (VOICESTUDIO_URL, or OMNIVOICE_PORT)  loopback needs no key; OMNIVOICE_API_KEY when remote
    GET  /health                      {"status": "ok", "device", "version"} (503 while it starts)
    POST /generate   form: text, language?, profile_id?, instruct?, speed, num_step, seed?   -> WAV (X-Audio-Id ...)
    GET  /profiles                    saved voices          GET /personalities   style presets (instruct text)
    POST /profiles   form: name, kind=clone, ref_audio (file), ref_text, instruct, language       -> a cloned voice
    POST /design/describe {description} -> attrs; POST /profiles kind=design, vd_states=attrs     -> a designed voice
    POST /transcribe form: audio (file), language?, mode=accurate  -> {text, segments: [{start, end, text}]} (646 langs)
    MCP: /mcp/ (Streamable HTTP) - OpenCode gets it as the "voicestudio" MCP server when the backend answers

    status()                 reachable, version, device, how to install
    speak(text, out, ...)    a WAV file; voice= a profile id or name
    voices() / clone() / design() / transcribe(path, srt=True) -> text and a .srt beside the audio
    install_command()        the official installer for this OS (the owner allows it first - it is a download + run)
    tool(args)               LOKI's "voice" tool: action speak | voices | clone | design | transcribe | status
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_PORT = 3900
INSTALL_MAC_LINUX = ["sh", "-c", "curl -fsSL https://voicestudio.sh/install | sh"]
INSTALL_WINDOWS = ["powershell", "-NoProfile", "-Command", "irm https://voicestudio.sh/install | iex"]
HOME = "https://github.com/debpalash/VoiceStudio"


class VoiceError(RuntimeError):
    pass


def base_url(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    given = str(env.get("VOICESTUDIO_URL") or "").strip().rstrip("/")
    return given or "http://127.0.0.1:%s" % (env.get("OMNIVOICE_PORT") or DEFAULT_PORT)


def _opener():
    # loopback / LAN traffic never goes through a system proxy
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open


def _req(method: str, path: str, data: bytes | None = None, ctype: str = "", timeout: float = 30,
         opener=None) -> tuple:
    headers = {"X-OmniVoice-Client-Id": "loki"}
    if ctype:
        headers["Content-Type"] = ctype
    key = os.environ.get("OMNIVOICE_API_KEY")
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(base_url() + path, data=data, method=method, headers=headers)
    try:
        with (opener or _opener())(req, timeout=timeout) as resp:
            return resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body).get("detail")
            body = json.dumps(detail) if not isinstance(detail, str) else detail
        except (ValueError, AttributeError):
            pass
        raise VoiceError("VoiceStudio answered %s on %s: %s" % (exc.code, path, body[:300])) from None
    except (urllib.error.URLError, OSError) as exc:
        raise VoiceError("VoiceStudio is not running at %s (%s). Open VoiceStudio, or install it: voice "
                         "action=install." % (base_url(), getattr(exc, "reason", exc))) from None


def _json(method: str, path: str, payload: dict | None = None, timeout: float = 30, opener=None) -> Any:
    raw, _ = _req(method, path, json.dumps(payload).encode() if payload is not None else None,
                  "application/json" if payload is not None else "", timeout, opener)
    return json.loads(raw.decode("utf-8") or "null")


def _form(path: str, fields: dict, files: dict | None = None, timeout: float = 1800, opener=None) -> tuple:
    boundary = "----loki" + secrets.token_hex(10)
    parts = []
    for k, v in fields.items():
        if v is None or v == "":
            continue
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, k, v)).encode())
    for k, (name, data) in (files or {}).items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                      'Content-Type: application/octet-stream\r\n\r\n' % (boundary, k, name)).encode() + data + b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode())
    return _req("POST", path, b"".join(parts), "multipart/form-data; boundary=" + boundary, timeout, opener)


# ----------------------------------------------------------------------------- what is there
def installed_app() -> str:
    """Where the VoiceStudio app is on this computer ('' when not found)."""
    home = Path.home()
    for p in (Path("/Applications/VoiceStudio.app"), home / "Applications" / "VoiceStudio.app",
              Path(os.environ.get("LOCALAPPDATA", str(home))) / "Programs" / "VoiceStudio" / "VoiceStudio.exe",
              Path("/usr/bin/voicestudio"), home / ".local" / "bin" / "voicestudio"):
        if p.exists():
            return str(p)
    return ""


def status(opener=None) -> dict:
    out = {"url": base_url(), "app": installed_app(), "running": False, "home": HOME, "mcp": base_url() + "/mcp/"}
    try:
        raw, _ = _req("GET", "/health", timeout=3, opener=opener)
        h = json.loads(raw.decode("utf-8") or "{}")
        out.update(running=h.get("status") == "ok", version=h.get("version", ""), device=h.get("device", ""))
    except VoiceError as exc:
        out["note"] = str(exc) if out["app"] else "VoiceStudio is not installed - voice action=install installs it."
    return out


def install_command(platform: str | None = None) -> list:
    return INSTALL_WINDOWS if (platform or sys.platform) == "win32" else INSTALL_MAC_LINUX


# ----------------------------------------------------------------------------- the voice work
def voices(opener=None) -> list:
    got = _json("GET", "/profiles", opener=opener)
    return [{"id": p.get("id"), "name": p.get("name"), "kind": p.get("kind"), "language": p.get("language", "")}
            for p in (got or []) if isinstance(p, dict)]


def _voice_id(voice: str, opener=None) -> str:
    if not voice:
        return ""
    for v in voices(opener):
        if voice in (v["id"], v["name"]) or str(v["name"]).lower() == voice.lower():
            return v["id"]
    raise VoiceError("no saved voice called %r - voice action=voices lists them" % voice)


def speak(text: str, out: str | Path, voice: str = "", instruct: str = "", language: str = "", speed: float = 1.0,
          steps: int = 16, seed: int | None = None, opener=None) -> dict:
    text = str(text or "").strip()
    if not text:
        raise VoiceError("what should it say? (text)")
    fields = {"text": text, "speed": str(max(0.5, min(2.0, float(speed or 1.0)))),
              "num_step": str(int(steps or 16)), "language": language, "instruct": instruct,
              "profile_id": _voice_id(voice, opener), "seed": "" if seed is None else str(int(seed))}
    raw, headers = _form("/generate", fields, timeout=1800 + len(text) // 40, opener=opener)
    if raw[:4] != b"RIFF":
        raise VoiceError("VoiceStudio sent something that is not a WAV")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    lower = {k.lower(): v for k, v in headers.items()}
    return {"ok": True, "file": str(out), "seconds": lower.get("x-audio-duration", ""),
            "made_in": lower.get("x-gen-time", "")}


def clone(name: str, ref_audio: str | Path, ref_text: str = "", language: str = "Auto", opener=None) -> dict:
    p = Path(ref_audio)
    if not p.is_file():
        raise VoiceError("no recording at %s" % ref_audio)
    raw, _ = _form("/profiles", {"name": name, "kind": "clone", "ref_text": ref_text, "language": language or "Auto"},
                   {"ref_audio": (p.name, p.read_bytes())}, timeout=600, opener=opener)
    got = json.loads(raw.decode("utf-8") or "{}")
    return {"ok": True, "id": got.get("id"), "name": got.get("name"), "kind": got.get("kind")}


def design(name: str, description: str, language: str = "Auto", opener=None) -> dict:
    parsed = _json("POST", "/design/describe", {"description": description}, opener=opener) or {}
    if not parsed.get("matched"):
        raise VoiceError("VoiceStudio could not map that description (it knows gender, age, pitch, style, accent "
                         "words); not understood: %s" % ", ".join(parsed.get("unmatched") or []))
    raw, _ = _form("/profiles", {"name": name, "kind": "design", "vd_states": json.dumps(parsed["attrs"]),
                                 "instruct": parsed.get("instruct", ""), "language": language or "Auto"},
                   timeout=1800, opener=opener)
    got = json.loads(raw.decode("utf-8") or "{}")
    return {"ok": True, "id": got.get("id"), "name": got.get("name"), "attrs": parsed["attrs"],
            "unmatched": parsed.get("unmatched", [])}


def _stamp(t: float) -> str:
    ms = int(round(max(0.0, float(t)) * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def to_srt(segments: list) -> str:
    rows = []
    for i, s in enumerate([s for s in segments if str(s.get("text") or "").strip()], 1):
        rows.append("%d\n%s --> %s\n%s\n" % (i, _stamp(s.get("start", 0)), _stamp(s.get("end", s.get("start", 0))),
                                             str(s["text"]).strip()))
    return "\n".join(rows)


def transcribe(path: str | Path, language: str = "", srt: bool = True, opener=None) -> dict:
    p = Path(path)
    if not p.is_file():
        raise VoiceError("no audio or video at %s" % path)
    raw, _ = _form("/transcribe", {"language": language, "mode": "accurate" if srt else ""},
                   {"audio": (p.name, p.read_bytes())}, timeout=1800, opener=opener)
    got = json.loads(raw.decode("utf-8") or "{}")
    out = {"ok": True, "text": got.get("text", ""), "language": got.get("language", "")}
    segs = got.get("segments") or []
    if srt and segs:
        dest = p.with_suffix(".srt")
        dest.write_text(to_srt(segs), encoding="utf-8")
        out["srt"] = str(dest)
    return out


# ----------------------------------------------------------------------------- LOKI's tool
def tool(args: dict, workspace: Path | None = None, ask=None, run=None, opener=None) -> dict:
    """action: speak (text, voice?, instruct?, language?, speed?, out?) | voices | clone (name, audio, ref_text?) |
    design (name, description) | transcribe (audio, language?, srt=true) | status | install (asks the owner)."""
    action = str(args.get("action") or "speak").lower()
    ws = Path(workspace or os.getcwd())

    def inside(raw: str) -> Path:
        p = (ws / str(raw)).resolve() if not os.path.isabs(str(raw)) else Path(raw).resolve()
        return p

    try:
        if action == "status":
            return {"ok": True, **status(opener)}
        if action == "install":
            import big_storage  # pylint: disable=import-outside-toplevel
            if big_storage.low_space():
                return {"ok": False, "error": big_storage.install_note("VoiceStudio (it downloads several GB of voice "
                                                                         "models)")}
            cmd = install_command()
            detail = ("Install VoiceStudio (AGPL-3.0, %s) with its official installer - it downloads the app and runs "
                      "it:\n$ %s" % (HOME, " ".join(cmd)))
            if ask is not None and not ask("voice install", detail):
                return {"ok": False, "error": "not installed - the owner said no"}
            import subprocess  # pylint: disable=import-outside-toplevel
            env = dict(os.environ)
            big_storage.apply(env)           # its models go to the big drive, not the internal one
            proc = (run or subprocess.run)(cmd, capture_output=True, text=True, timeout=1800, env=env)
            return {"ok": proc.returncode == 0, "output": (proc.stdout or proc.stderr or "")[-3000:],
                    "next": "open VoiceStudio once; it downloads its voice model (about 2.3 GB) on first use"}
        if action == "voices":
            return {"ok": True, "voices": voices(opener)}
        if action == "speak":
            out = args.get("out") or "audio/%s.wav" % (
                "".join(c if c.isalnum() else "-" for c in str(args.get("text", ""))[:32].lower()).strip("-") or "voice")
            res = speak(args.get("text", ""), inside(out), str(args.get("voice") or ""),
                        str(args.get("instruct") or ""), str(args.get("language") or ""),
                        float(args.get("speed") or 1.0), int(args.get("steps") or 16), args.get("seed"), opener)
            res["file"] = os.path.relpath(res["file"], ws)
            return res
        if action == "clone":
            return clone(str(args.get("name") or "my voice"), inside(args.get("audio", "")),
                         str(args.get("ref_text") or ""), str(args.get("language") or "Auto"), opener)
        if action == "design":
            return design(str(args.get("name") or "designed voice"), str(args.get("description") or ""),
                          str(args.get("language") or "Auto"), opener)
        if action == "transcribe":
            res = transcribe(inside(args.get("audio", "")), str(args.get("language") or ""),
                             args.get("srt", True) not in (False, "false", 0, "0"), opener)
            if res.get("srt"):
                res["srt"] = os.path.relpath(res["srt"], ws)
            return res
    except VoiceError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "action is speak, voices, clone, design, transcribe, status or install"}


TOOL = {"name": "voice",
        "description": "Voices with VoiceStudio on this computer (local, 646 languages): action=speak text= [voice= a "
                       "saved voice, instruct='excited' / 'whisper' / 'narrator', language=, speed=] -> a WAV in audio/; "
                       "voices (the saved ones); clone name= audio= (a clean recording of the person - only with "
                       "their permission) ref_text=; design name= description='deep elderly male narrator, British'; "
                       "transcribe audio= (audio or video) -> text and a .srt captions file; status; install (asks the "
                       "owner first).",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["speak", "voices", "clone", "design", "transcribe", "status",
                                                  "install"]},
            "text": {"type": "string"}, "voice": {"type": "string"}, "instruct": {"type": "string"},
            "language": {"type": "string"}, "speed": {"type": "number"}, "out": {"type": "string"},
            "name": {"type": "string"}, "audio": {"type": "string"}, "ref_text": {"type": "string"},
            "description": {"type": "string"}, "srt": {"type": "boolean"}}, "required": ["action"]}}


def mcp_entry(timeout: float = 1.5) -> dict:
    """OpenCode's entry for VoiceStudio's own MCP server, when its backend answers right now."""
    try:
        _req("GET", "/health", timeout=timeout)
    except VoiceError:
        return {}
    return {"type": "remote", "url": base_url() + "/mcp/", "enabled": True,
            "headers": {"X-OmniVoice-Client-Id": "loki-opencode"}}
