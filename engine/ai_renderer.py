"""Render Studio's engine side: render jobs (path traced in the window, AI through ComfyUI) and their folders.

Owner, 2026-10-21: Render is a top-level tab; the AI generation runs on the PC (RTX 3070 Ti, 8 GB) in ComfyUI with the
GGUF build of the VACE + SkyReels V3 R2V merge and city96's ComfyUI-GGUF loader. The creator's own workflow files are
on Patreon, so LOKI has its OWN graphs (engine/ai_renderer_workflows/*.json, AGPL), written from the node sources -
every node class, input name, route and model file is cited in docs/AI_RENDERER.md.

ComfyUI's API, as its server.py defines it (comfyanonymous/ComfyUI@7a28332):
    GET  /system_stats                     connection test (+ the GPU's VRAM)
    GET  /object_info                      every node class and its inputs; a loader's file list = installed models
    POST /upload/image   multipart: image, type=input, subfolder, overwrite  -> {name, subfolder, type}
    POST /prompt         {prompt, client_id, prompt_id}                      -> {prompt_id, number, node_errors}
    GET  /queue                            {queue_running: [...], queue_pending: [...]}  (item[1] = prompt id)
    GET  /history/{prompt_id}              {} until done, then {id: {prompt, outputs, status: {status_str, completed, messages}}}
    GET  /view?filename=&subfolder=&type=  an output file
    POST /interrupt      {prompt_id}       stop it if it is the running prompt
    POST /queue          {delete: [ids]}   drop it if it is still waiting
    GET  /ws?clientId=                     websocket: {"type": "progress", "data": {value, max, prompt_id, node}}

A job's folder is <data>/renders/<job>/ with manifest.json (the Home screen lists them, engine/home_projects.py):
    {name, kind: "ai" | "path", status, created, updated, frames, fps, size: [w, h], camera, passes: {depth, lineart, ...},
     outputs: [...], thumb, log: [{t, msg}], workflow, params, progress}
States: idle -> preflight -> preparing -> queued -> running -> succeeded | failed | cancelled. One running AI job per
workflow (the iterative graphs carry frames between runs, and one 8 GB GPU runs one video at a time anyway).

Safety: nothing is uploaded to a ComfyUI that is not on this computer or one of LOKI's own linked machines unless the
user turned on `consent_remote` in the settings; URLs are logged without user:password or query; file names coming back
from ComfyUI are checked (one plain name, no folders, no "..") before anything is written. Standard library only.

Bridge routes (engine/loki_bridge.py sends /render/* here; every one needs the bearer token):
    GET  /render/status                  {settings, workflows, jobs, active}
    GET  /render/job?id=                 one manifest
    GET  /render/file?job=&name=         a file of that job (passes/<pass>/<n>.png too)
    GET  /render/presets?project=        saved settings per project
    POST /render/settings  {url?, consent_remote?, timeout_s?}
    POST /render/test      {url?}        connection test
    POST /render/preflight {workflow, params, job?}   the readiness report
    POST /render/new       {kind, name, workflow?, params?, camera?, fps?, size?, frames?, passes?}  -> {job}
    POST /render/upload-pass?job=&pass=&index=   raw PNG body: one frame of a pass (pass=start: the start image)
    POST /render/start     {job}         run an AI job      POST /render/cancel {job}     POST /render/retry {job}
    POST /render/finish    {job, status, log?}   a path-traced job's frames are all in
    POST /render/presets   {project, name, params} (params null deletes)
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
import zlib
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse

REPO = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = Path(__file__).resolve().parent / "ai_renderer_workflows"
DEFAULT_URL = "http://127.0.0.1:8188"
MAX_BODY = 40_000_000                 # one pass frame or a start image
MAX_FRAMES = 2000
STATES = ("idle", "preflight", "preparing", "queued", "running", "succeeded", "failed", "cancelled")
FINAL = ("succeeded", "failed", "cancelled")
SAFE_JOB = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SAFE_PASS = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
OUT_TYPES = {".webm": "video/webm", ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4",
             ".gif": "image/gif", ".json": "application/json"}
HF = "https://huggingface.co/%s/resolve/%s/%s"
LOW_DISK = 2 * 1024 ** 3

_LOCK = threading.RLock()
_THREADS: dict = {}                   # job -> its running thread
_CANCEL: dict = {}                    # job -> threading.Event


class RenderError(Exception):
    """A plain reason for the user."""


# ------------------------------------------------------------------ where things live
def data_dir(state: Any = None) -> Path:
    agent = getattr(state, "agent", None)
    return Path(getattr(agent, "DATA_DIR", "") or os.getenv("LOKI_DATA") or (REPO / "harness_data"))


def renders_dir(state: Any = None) -> Path:
    return data_dir(state) / "renders"


def _settings_file(state: Any = None) -> Path:
    return data_dir(state) / "ai_renderer" / "settings.json"


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".%s.tmp" % secrets.token_hex(3))
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def safe_name(name: str) -> str | None:
    """One plain file name (what ComfyUI or the window hands us) or None: no folders, no '..', no control characters."""
    name = str(name or "")
    if not name or len(name) > 160 or name in (".", "..") or ".." in name:
        return None
    if any(c in name for c in "/\\:\0") or any(ord(c) < 32 for c in name):
        return None
    return name


def job_dir(state: Any, job: str) -> Path:
    if not SAFE_JOB.match(str(job or "")):
        raise RenderError("not a job name")
    return renders_dir(state) / job


# ------------------------------------------------------------------ settings and endpoints
def default_url(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    given = str(env.get("LOKI_COMFYUI_URL") or "").strip().rstrip("/")
    return given or DEFAULT_URL


def settings(state: Any = None) -> dict:
    s = _read_json(_settings_file(state), {}) or {}
    return {"url": str(s.get("url") or default_url()).rstrip("/"), "consent_remote": bool(s.get("consent_remote")),
            "timeout_s": int(s.get("timeout_s") or 6 * 3600)}


def save_settings(state: Any, data: dict) -> dict:
    s = settings(state)
    if "url" in data:
        url = str(data.get("url") or "").strip().rstrip("/") or default_url()
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise RenderError("The ComfyUI address must look like http://<computer>:8188")
        if p.username or p.password:
            raise RenderError("Put no user name or password in the ComfyUI address.")
        if p.path not in ("", "/") or p.query or p.fragment:
            raise RenderError("Give only the address and port of ComfyUI, e.g. http://192.168.1.50:8188")
        s["url"] = url
    if "consent_remote" in data:
        s["consent_remote"] = bool(data.get("consent_remote"))
    if "timeout_s" in data:
        s["timeout_s"] = max(60, min(48 * 3600, int(data.get("timeout_s") or 0)))
    _write_json(_settings_file(state), s)
    return s


def redact(url: str) -> str:
    """The address for a log: scheme://host:port, never a user, password or query."""
    p = urlparse(str(url or ""))
    host = p.hostname or "?"
    return "%s://%s%s" % (p.scheme or "http", host, (":%d" % p.port) if p.port else "")


def where(url: str, env: dict | None = None) -> dict:
    """Is this ComfyUI on this computer, on one of LOKI's own linked machines, or somewhere else?"""
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.startswith("127."):
        return {"place": "local", "own": True, "note": "this computer"}
    try:
        import peers  # pylint: disable=import-outside-toplevel
        for peer in peers.peers(env):
            if peer.get("relay"):
                continue
            if (urlparse(peer["url"]).hostname or "").lower() == host:
                return {"place": "peer", "own": True, "note": "LOKI's linked machine '%s'" % peer["name"], "peer": peer["name"]}
    except Exception:  # noqa: BLE001 - peers is optional here
        pass
    return {"place": "remote", "own": False, "note": "another computer (not one of LOKI's linked machines)"}


def may_upload(s: dict, env: dict | None = None) -> tuple[bool, str]:
    w = where(s["url"], env)
    if w["own"] or s.get("consent_remote"):
        return True, w["note"]
    return False, ("%s is %s. Turn on 'allow uploads to this server' in Render Studio's settings first - your passes "
                   "and start image would be sent there." % (redact(s["url"]), w["note"]))


# ------------------------------------------------------------------ the ComfyUI client
class Comfy:
    """A small urllib client for one ComfyUI server (routes: see the module doc)."""

    def __init__(self, url: str, timeout: float = 20.0, opener: Callable | None = None):
        self.url = str(url).rstrip("/")
        self.timeout = timeout
        host = urlparse(self.url).hostname or ""
        try:
            import peers  # pylint: disable=import-outside-toplevel
            private = peers.private_host(host)
        except Exception:  # noqa: BLE001
            private = host in ("localhost", "127.0.0.1")
        # the agent proxy / a system proxy must never see LAN traffic; a remote server goes the normal way
        self._open = opener or (urllib.request.build_opener(urllib.request.ProxyHandler({})).open if private
                                else urllib.request.urlopen)

    def _req(self, method: str, path: str, body: bytes | None = None, ctype: str = "application/json",
             raw: bool = False, timeout: float | None = None) -> Any:
        req = urllib.request.Request(self.url + path, data=body, method=method,
                                     headers={"Content-Type": ctype} if body is not None else {})
        try:
            with self._open(req, timeout=timeout or self.timeout) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                got = json.loads(exc.read().decode("utf-8") or "{}")
                err = got.get("error") if isinstance(got, dict) else None
                detail = (err.get("message") if isinstance(err, dict) else str(err or "")) or ""
                ne = got.get("node_errors") if isinstance(got, dict) else None
                if ne:
                    parts = []
                    for nid, e in list(ne.items())[:4]:
                        for x in (e.get("errors") or [])[:2]:
                            parts.append("node %s (%s): %s %s" % (nid, e.get("class_type", "?"), x.get("message", ""), x.get("details", "")))
                    detail += (" - " if detail else "") + "; ".join(parts)
            except Exception:  # noqa: BLE001
                pass
            raise RenderError("ComfyUI answered HTTP %s on %s%s" % (exc.code, path.split("?")[0], (": " + detail) if detail else "")) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RenderError("cannot reach ComfyUI at %s (%s)" % (redact(self.url), getattr(exc, "reason", exc))) from exc
        if raw:
            return data
        try:
            return json.loads(data.decode("utf-8") or "{}")
        except ValueError as exc:
            raise RenderError("ComfyUI sent something that is not JSON on %s" % path.split("?")[0]) from exc

    def system_stats(self) -> dict:
        return self._req("GET", "/system_stats")

    def object_info(self) -> dict:
        return self._req("GET", "/object_info", timeout=max(self.timeout, 60))

    def upload_image(self, filename: str, data: bytes, subfolder: str = "loki") -> dict:
        boundary = "----loki" + secrets.token_hex(12)
        parts = []
        for k, v in (("type", "input"), ("subfolder", subfolder), ("overwrite", "true")):
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n"
                      % (boundary, filename)).encode() + data + b"\r\n")
        parts.append(("--%s--\r\n" % boundary).encode())
        return self._req("POST", "/upload/image", b"".join(parts), "multipart/form-data; boundary=" + boundary, timeout=max(self.timeout, 120))

    def queue_prompt(self, prompt: dict, client_id: str, prompt_id: str) -> dict:
        return self._req("POST", "/prompt", json.dumps({"prompt": prompt, "client_id": client_id, "prompt_id": prompt_id}).encode())

    def queue(self) -> dict:
        return self._req("GET", "/queue")

    def history(self, prompt_id: str) -> dict:
        return self._req("GET", "/history/" + quote(prompt_id, safe=""))

    def view(self, filename: str, subfolder: str, kind: str) -> bytes:
        return self._req("GET", "/view?" + urlencode({"filename": filename, "subfolder": subfolder, "type": kind}), raw=True,
                         timeout=max(self.timeout, 300))

    def interrupt(self, prompt_id: str) -> None:
        self._req("POST", "/interrupt", json.dumps({"prompt_id": prompt_id}).encode(), raw=True)

    def delete_pending(self, prompt_id: str) -> None:
        self._req("POST", "/queue", json.dumps({"delete": [prompt_id]}).encode(), raw=True)


def watch_progress(url: str, client_id: str, on_msg: Callable[[dict], None], stop: threading.Event, timeout: float = 5.0) -> bool:
    """Read ComfyUI's /ws for this client (progress of the sampler steps). Best effort: False when it cannot connect.
    A minimal RFC 6455 client: one GET with Upgrade, then unmasked server frames (text = JSON); we never send data."""
    p = urlparse(url)
    if p.scheme != "http" or not p.hostname:
        return False   # https would need TLS; the PC's ComfyUI is plain http on the LAN / loopback
    try:
        sock = socket.create_connection((p.hostname, p.port or 80), timeout=timeout)
    except OSError:
        return False
    try:
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        sock.sendall(("GET /ws?clientId=%s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (quote(client_id), p.hostname, p.port or 80, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                return False
            head += chunk
            if len(head) > 65536:
                return False
        line = head.split(b"\r\n", 1)[0]
        if b" 101 " not in line + b" ":
            return False
        buf = head.split(b"\r\n\r\n", 1)[1]
        sock.settimeout(1.0)

        def need(n):
            nonlocal buf
            while len(buf) < n:
                if stop.is_set():
                    raise EOFError
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    raise EOFError
                buf += chunk
            out, buf = buf[:n], buf[n:]
            return out

        while not stop.is_set():
            b0, b1 = need(2)
            op, ln = b0 & 0x0F, b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", need(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", need(8))[0]
            mask = need(4) if b1 & 0x80 else b""
            payload = need(ln) if ln else b""
            if mask:
                payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
            if op == 8:
                break
            if op == 1:
                try:
                    msg = json.loads(payload.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    on_msg(msg)
        return True
    except (EOFError, OSError, struct.error):
        return True
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------ workflows
def workflows() -> dict:
    out = {}
    for f in sorted(WORKFLOW_DIR.glob("*.json")):
        wf = _read_json(f)
        if isinstance(wf, dict) and isinstance(wf.get("prompt"), dict):
            out[wf.get("name") or f.stem] = wf
    return out


def workflow(name: str) -> dict:
    wf = workflows().get(str(name or "vace_render"))
    if not wf:
        raise RenderError("no such workflow: %s" % name)
    return json.loads(json.dumps(wf))


def describe(wf: dict) -> dict:
    """What the window needs to build its controls: the verified parameters, uploads, models, constraints."""
    return {k: wf.get(k) for k in ("name", "label", "about", "version", "license", "params", "uploads", "constraints",
                                   "custom_nodes", "sources", "control_switch", "post")} | {
        "models": [{**m, "url": HF % (m["repo"], m["revision"], m["path"])} for m in wf.get("models", [])]}


def graph(wf: dict) -> dict:
    """The workflow's node graph for Render Studio's Nodes view, derived from the graph's own prompt JSON.
    Each node carries its non-link inputs, the links into it (from node id -> this input) and the model file(s)
    it loads, so the window can draw the wiring and colour a node the server/preflight says is missing."""
    prompt = wf.get("prompt") or {}
    models_by_node: dict = {}
    for m in wf.get("models") or []:
        models_by_node.setdefault(str(m.get("node")), []).append(
            {"file": m.get("file"), "folder": m.get("folder"), "size": m.get("size"), "license": m.get("license"),
             "alternatives": [{"file": a.get("file"), "size": a.get("size")} for a in (m.get("alternatives") or [])]})
    nodes = []
    for nid, node in prompt.items():
        ins, links = {}, []
        for name, val in (node.get("inputs") or {}).items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str) and isinstance(val[1], int):
                links.append({"from": str(val[0]), "input": name})
            else:
                ins[name] = val
        nodes.append({"id": str(nid), "class": node.get("class_type"),
                      "title": (node.get("_meta") or {}).get("title") or node.get("class_type"),
                      "inputs": ins, "links": links, "models": models_by_node.get(str(nid), [])})
    return {"workflow": wf.get("name"), "nodes": nodes}


def _option_list(spec: Any) -> list | None:
    """A combo input's options from /object_info: V1 [[a, b], {...}] or V3 ["COMBO", {"options": [...]}]."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return list(spec[1].get("options") or [])
    return None


def _input_spec(info: dict, cls: str, name: str) -> Any:
    node = info.get(cls) or {}
    inp = node.get("input") or {}
    return (inp.get("required") or {}).get(name, (inp.get("optional") or {}).get(name))


def check_graph(prompt: dict, info: dict | None = None) -> list:
    """Problems with an API-format graph: links to missing nodes / outputs, unknown classes, missing required inputs."""
    problems = []
    for nid, node in prompt.items():
        if not isinstance(node, dict) or "class_type" not in node:
            problems.append("node %s has no class_type" % nid)
            continue
        cls = node["class_type"]
        for k, v in (node.get("inputs") or {}).items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                src = prompt.get(v[0])
                if src is None:
                    problems.append("node %s.%s links to missing node %s" % (nid, k, v[0]))
                elif info is not None and src.get("class_type") in info:
                    outs = info[src["class_type"]].get("output") or []
                    if not isinstance(v[1], int) or v[1] >= len(outs):
                        problems.append("node %s.%s links to output %s of %s, which has %d" % (nid, k, v[1], src["class_type"], len(outs)))
        if info is None:
            continue
        if cls not in info:
            problems.append("node %s: %s is not a node class this ComfyUI has" % (nid, cls))
            continue
        req = (info[cls].get("input") or {}).get("required") or {}
        opt = (info[cls].get("input") or {}).get("optional") or {}
        for k in req:
            if k not in (node.get("inputs") or {}):
                problems.append("node %s (%s) misses the required input %s" % (nid, cls, k))
        for k in node.get("inputs") or {}:
            if k not in req and k not in opt:
                problems.append("node %s (%s) has an input %s the node does not take" % (nid, cls, k))
    return problems


def adapt(prompt: dict, wf: dict, info: dict | None) -> dict:
    """A node pack whose inputs change between versions (RIFE VFI gained dtype / torch_compile / batch_size): for the
    nodes the workflow marks "adaptive", drop the listed inputs this server's node does not take, and give any
    required input it wants but the graph lacks the server's own default. Other nodes are never touched."""
    if not info:
        return prompt
    for nid, names in (wf.get("adaptive") or {}).items():
        node = prompt.get(nid)
        spec = (info.get(node["class_type"]) or {}).get("input") if node else None
        if not spec:
            continue
        req, opt = spec.get("required") or {}, spec.get("optional") or {}
        for k in list(node["inputs"]):
            if k in names and k not in req and k not in opt:
                del node["inputs"][k]
        for k, sp in req.items():
            if k not in node["inputs"] and isinstance(sp, (list, tuple)) and len(sp) > 1 and isinstance(sp[1], dict) and "default" in sp[1]:
                node["inputs"][k] = sp[1]["default"]
    return prompt


def _num(v, kind):
    return int(v) if kind == "int" else float(v)


def build_prompt(wf: dict, params: dict, uploaded: dict, control: str = "both") -> tuple[dict, list]:
    """The graph with the user's values put into the verified inputs. Returns (prompt, problems)."""
    prompt = json.loads(json.dumps(wf["prompt"]))
    problems = []
    for key, spec in (wf.get("params") or {}).items():
        if key not in params or params[key] is None or params[key] == "":
            continue
        val = params[key]
        kind = spec.get("type")
        try:
            if kind in ("int", "float"):
                val = _num(val, kind)
                if "min" in spec and val < spec["min"] or "max" in spec and val > spec["max"]:
                    problems.append("%s must be between %s and %s" % (key, spec.get("min"), spec.get("max")))
                    continue
            else:
                val = str(val)[:8000]
        except (TypeError, ValueError):
            problems.append("%s is not a number" % key)
            continue
        targets = spec.get("nodes") or [[spec["node"], spec["input"]]]
        for nid, inp in targets:
            if nid in prompt:
                prompt[nid]["inputs"][inp] = val
    for key, up in (wf.get("uploads") or {}).items():
        if key in uploaded and up["node"] in prompt:
            prompt[up["node"]]["inputs"][up["input"]] = uploaded[key]
    sw = wf.get("control_switch")
    if sw:
        if control not in ("both", "depth", "lineart"):
            control = "both"
        nid, inp = sw["target"]
        prompt[nid]["inputs"][inp] = list(sw[control])
        for drop in (sw.get("drop") or {}).get(control, []):
            prompt.pop(drop, None)
    # the start image is optional for VACE (reference_image): without one, take the loader out
    start = (wf.get("uploads") or {}).get("start")
    if start and "start" not in uploaded:
        prompt.pop(start["node"], None)
        for node in prompt.values():
            for k, v in list(node["inputs"].items()):
                if isinstance(v, list) and len(v) == 2 and v[0] == start["node"]:
                    del node["inputs"][k]
    for up_key, up in (wf.get("uploads") or {}).items():
        if up_key != "start" and up["node"] in prompt and up_key not in uploaded:
            problems.append("the %s pass is missing" % up["pass"])
    return prompt, problems


# ------------------------------------------------------------------ PNG frames -> one APNG (ComfyUI's LoadImage reads
# every frame through PyAV/FFmpeg's apng demuxer: nodes.py LoadImage -> InputImpl.VideoFromFile(...).get_components())
def png_info(data: bytes) -> dict:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise RenderError("not a PNG")
    w, h, depth, color = struct.unpack(">IIBB", data[16:26])
    return {"width": w, "height": h, "depth": depth, "color": color, "ihdr": data[16:29]}


def _chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        ln, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + ln]
        pos += 12 + ln


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def apng(frames: list, fps: float) -> bytes:
    """Same-size PNG frames -> an animated PNG, frame for frame (no merging of equal frames, unlike Pillow)."""
    if not frames:
        raise RenderError("no frames")
    first = png_info(frames[0])
    num, den = max(1, int(round(1000 / max(0.01, float(fps))))), 1000
    out = [b"\x89PNG\r\n\x1a\n", _chunk(b"IHDR", first["ihdr"]), _chunk(b"acTL", struct.pack(">II", len(frames), 0))]
    seq = 0
    for i, f in enumerate(frames):
        if png_info(f)["ihdr"] != first["ihdr"]:
            raise RenderError("frame %d differs in size or colour type from the first frame" % i)
        out.append(_chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, first["width"], first["height"], 0, 0, num, den, 0, 0)))
        seq += 1
        for kind, body in _chunks(f):
            if kind == b"IDAT":
                if i == 0:
                    out.append(_chunk(b"IDAT", body))
                else:
                    out.append(_chunk(b"fdAT", struct.pack(">I", seq) + body))
                    seq += 1
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


# ------------------------------------------------------------------ jobs and their manifests
def _now() -> float:
    return round(time.time(), 3)


def manifest(state: Any, job: str) -> dict | None:
    m = _read_json(job_dir(state, job) / "manifest.json")
    return m if isinstance(m, dict) else None


def _save(state: Any, job: str, m: dict) -> dict:
    m["updated"] = _now()
    _write_json(job_dir(state, job) / "manifest.json", m)
    return m


def _log(m: dict, msg: str) -> None:
    m.setdefault("log", []).append({"t": _now(), "msg": str(msg)[:600]})
    del m["log"][:-200]


def update(state: Any, job: str, fn: Callable[[dict], None]) -> dict:
    with _LOCK:
        m = manifest(state, job)
        if m is None:
            raise RenderError("no such job")
        fn(m)
        return _save(state, job, m)


def new_job(state: Any, data: dict) -> dict:
    kind = "path" if data.get("kind") == "path" else "ai"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job = "%s-%s-%s" % (kind, stamp, secrets.token_hex(2))
    size = data.get("size") or [0, 0]
    try:
        size = [max(0, int(size[0])), max(0, int(size[1]))]
    except (TypeError, ValueError, IndexError):
        size = [0, 0]
    wf_name = str(data.get("workflow") or "vace_render") if kind == "ai" else None
    if wf_name:
        workflow(wf_name)
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    m = {"name": str(data.get("name") or ("AI render " if kind == "ai" else "Path traced ") + stamp)[:120], "kind": kind,
         "status": "idle", "created": _now(), "updated": _now(), "frames": int(data.get("frames") or 0),
         "fps": float(data.get("fps") or 16), "size": size, "camera": str(data.get("camera") or "persp")[:40],
         "range": data.get("range") if isinstance(data.get("range"), dict) else None,
         "passes": {}, "outputs": [], "thumb": None, "log": [], "workflow": wf_name,
         "params": {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool)) or v is None},
         "control": str(data.get("control") or "both"), "progress": 0.0, "machine": None, "prompt_id": None,
         "project": str(data.get("project") or "")[:80]}
    _log(m, "created")
    job_dir(state, job).mkdir(parents=True, exist_ok=False)
    with _LOCK:
        _save(state, job, m)
    return {"job": job, "manifest": m}


def save_pass(state: Any, job: str, name: str, index: int, body: bytes) -> dict:
    if not SAFE_PASS.match(str(name or "")):
        raise RenderError("not a pass name")
    if not (0 <= int(index) < MAX_FRAMES):
        raise RenderError("frame index out of range")
    info = png_info(body)
    m = manifest(state, job)
    if m is None:
        raise RenderError("no such job")
    if m["status"] not in ("idle", "running") or (m["kind"] == "ai" and m["status"] != "idle"):
        raise RenderError("the job has started; passes can no longer change")
    folder = job_dir(state, job) / "passes" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("%04d.png" % int(index))).write_bytes(body)

    def note(mm):
        count = len(list(folder.glob("*.png")))
        mm["passes"][name] = {"frames": count, "width": info["width"], "height": info["height"], "folder": "passes/" + name}
        if mm.get("thumb") is None and name in ("beauty", "start") and int(index) == 0:
            mm["thumb"] = "thumb.png"
            (job_dir(state, job) / "thumb.png").write_bytes(body)
    return update(state, job, note)


def _pass_frames(state: Any, job: str, name: str) -> list:
    folder = job_dir(state, job) / "passes" / name
    return [p.read_bytes() for p in sorted(folder.glob("*.png"))] if folder.is_dir() else []


def list_jobs(state: Any) -> list:
    root = renders_dir(state)
    out = []
    if root.is_dir():
        for f in root.iterdir():
            if f.is_dir() and SAFE_JOB.match(f.name):
                m = _read_json(f / "manifest.json")
                if isinstance(m, dict):
                    out.append({"job": f.name, **{k: m.get(k) for k in ("name", "kind", "status", "created", "updated", "progress",
                                                                          "frames", "fps", "size", "camera", "outputs", "thumb",
                                                                          "workflow", "machine")},
                                "last": (m.get("log") or [{}])[-1].get("msg", "")})
    out.sort(key=lambda j: j.get("created") or 0, reverse=True)
    return out


def active(state: Any) -> list:
    return [j for j in list_jobs(state) if j["status"] not in FINAL and j["status"] != "idle"]


# ------------------------------------------------------------------ preflight
def preflight(state: Any, wf_name: str, params: dict, job: str | None = None, client: Comfy | None = None,
              env: dict | None = None, control: str = "both") -> dict:
    """The readiness report. `blockers` stop a run; `warnings` do not. Never claims more than it checked."""
    s = settings(state)
    rep = {"ok": False, "url": redact(s["url"]), "where": where(s["url"], env), "blockers": [], "warnings": [],
           "missing_nodes": [], "missing_models": [], "checked": [], "gpu": None}
    try:
        wf = workflow(wf_name)
    except RenderError as exc:
        rep["blockers"].append(str(exc))
        return rep
    rep["workflow"] = wf["name"]
    ok_up, note = may_upload(s, env)
    if not ok_up:
        rep["blockers"].append(note)
    # the numbers the graph's nodes allow (the node sources: docs/AI_RENDERER.md)
    merged = {k: v.get("default") for k, v in (wf.get("params") or {}).items()}
    merged.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
    c = wf.get("constraints") or {}
    if (c.get("frames") or {}).get("rule") == "4n+1":
        try:
            n = int(merged.get("frames"))
            if n < 1 or (n - 1) % 4:
                lo, hi = max(1, n - (n - 1) % 4), n + (4 - (n - 1) % 4) % 4
                rep["blockers"].append("frames must be 4n+1 for Wan (e.g. %d or %d), not %d" % (lo, hi, n))
        except (TypeError, ValueError):
            rep["blockers"].append("frames is not a number")
    for dim in ("width", "height"):
        if dim in merged and c.get("size_step"):
            try:
                v = int(merged[dim])
                if v % c["size_step"] or not c["size_min"] <= v <= c["size_max"]:
                    rep["blockers"].append("%s must be a multiple of %d between %d and %d, not %d" % (dim, c["size_step"], c["size_min"], c["size_max"], v))
            except (TypeError, ValueError):
                rep["blockers"].append("%s is not a number" % dim)
    _, problems = build_prompt(wf, merged, {k: "x" for k in (wf.get("uploads") or {})}, control)
    rep["blockers"].extend(problems)
    # the job's passes: present, readable, same size, enough frames
    if job:
        m = manifest(state, job)
        if m is None:
            rep["blockers"].append("no such job")
        else:
            needed = [u for k, u in (wf.get("uploads") or {}).items() if k != "start" and _pass_used(wf, k, control)]
            sizes = set()
            for up in needed:
                p = (m.get("passes") or {}).get(up["pass"])
                if not p or not p.get("frames"):
                    rep["blockers"].append("the %s pass has not been rendered (Render passes in Forge's camera first)" % up["pass"])
                    continue
                sizes.add((p["width"], p["height"]))
                if up.get("frames") and "frames" in merged:
                    try:
                        want = int(merged["frames"])
                        if p["frames"] < want:
                            rep["warnings"].append("the %s pass has %d frames but %d are asked for: VACE pads the rest with grey "
                                                   "(nodes_wan.py), so the end has no guide" % (up["pass"], p["frames"], want))
                        elif p["frames"] > want:
                            rep["warnings"].append("the %s pass has %d frames; only the first %d are used" % (up["pass"], p["frames"], want))
                    except (TypeError, ValueError):
                        pass
            if len(sizes) > 1:
                rep["blockers"].append("the passes differ in size: %s" % ", ".join("%dx%d" % s_ for s_ in sorted(sizes)))
            if sizes and "width" in merged:
                (pw, ph), = list(sizes)[:1]
                try:
                    if abs(pw / ph - int(merged["width"]) / int(merged["height"])) > 0.02:
                        rep["warnings"].append("the passes are %dx%d but the render is %sx%s: VACE scales and centre-crops them" % (pw, ph, merged["width"], merged["height"]))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            if "start" in (wf.get("uploads") or {}) and not (m.get("passes") or {}).get("start"):
                rep["warnings"].append("no start image: the look comes from the prompt alone (VACE's reference_image is optional)")
    # the output folder
    try:
        root = renders_dir(state)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / (".probe-%s" % secrets.token_hex(3))
        probe.write_text("x")
        probe.unlink()
        free = shutil.disk_usage(root).free
        if free < LOW_DISK:
            rep["warnings"].append("only %.1f GB free where renders are saved" % (free / 1024 ** 3))
    except OSError as exc:
        rep["blockers"].append("cannot write render files: %s" % exc)
    # the server: reachable, the node classes, the model files
    cl = client or Comfy(s["url"])
    try:
        stats = cl.system_stats()
        rep["checked"].append("connected to ComfyUI %s at %s" % (((stats.get("system") or {}).get("comfyui_version") or "?"), rep["url"]))
        dev = (stats.get("devices") or [{}])[0]
        if dev:
            rep["gpu"] = {"name": dev.get("name"), "vram_total": dev.get("vram_total"), "vram_free": dev.get("vram_free")}
    except RenderError as exc:
        rep["blockers"].append(str(exc) + ". Start ComfyUI on that computer (tools/setup_comfyui.py --start) or fix the address.")
        return rep
    try:
        info = cl.object_info()
    except RenderError as exc:
        rep["blockers"].append(str(exc))
        return rep
    prompt, _ = build_prompt(wf, merged, {k: "x" for k in (wf.get("uploads") or {})}, control)
    prompt = adapt(prompt, wf, info)
    for nid, node in prompt.items():
        cls = node["class_type"]
        if cls not in info and cls not in [x["class"] for x in rep["missing_nodes"]]:
            pack = (wf.get("custom_nodes") or {}).get(cls)
            rep["missing_nodes"].append({"class": cls, "pack": pack and pack["repo"], "license": pack and pack.get("license"),
                                         "commit": pack and pack.get("commit"), "core": not pack})
    for mn in rep["missing_nodes"]:
        rep["blockers"].append("ComfyUI has no %s node%s" % (mn["class"], (" - install %s into ComfyUI/custom_nodes" % mn["pack"]) if mn["pack"]
                                                            else " - this ComfyUI is older than the graph needs; update it"))
    if not rep["missing_nodes"]:
        rep["checked"].append("all %d node classes are there" % len({n["class_type"] for n in prompt.values()}))
        gp = check_graph(prompt, info)
        rep["blockers"].extend(gp)
    for mdl in wf.get("models") or []:
        node = prompt.get(mdl["node"])
        if node is None:
            continue
        chosen = node["inputs"].get(mdl["input"], mdl["file"])
        opts = _option_list(_input_spec(info, node["class_type"], mdl["input"]))
        if opts is None:
            continue   # its node is missing (reported above)
        if chosen not in opts:
            rep["missing_models"].append({"file": chosen, "folder": mdl["folder"], "size": mdl.get("size"), "license": mdl.get("license"),
                                          "url": HF % (mdl["repo"], mdl["revision"], mdl["path"]) if chosen == mdl["file"] else None,
                                          "installed": [o for o in opts if isinstance(o, str)][:30]})
            rep["blockers"].append("model file %s is not in ComfyUI/%s" % (chosen, mdl["folder"]))
        else:
            rep["checked"].append("%s is installed" % chosen)
    # sampler / scheduler names come from the server's own lists
    for key in ("sampler", "scheduler"):
        spec = (wf.get("params") or {}).get(key)
        if spec and merged.get(key):
            opts = _option_list(_input_spec(info, prompt[spec["node"]]["class_type"], spec["input"])) if spec["node"] in prompt else None
            if opts is not None and merged[key] not in opts:
                rep["blockers"].append("%s '%s' is not one this ComfyUI has" % (key, merged[key]))
    # memory: an estimate only (the GGUF file vs the card); ComfyUI offloads what does not fit
    gpu = rep.get("gpu") or {}
    big = max([m.get("size") or 0 for m in wf.get("models") or [] if prompt.get(m["node"])] or [0])
    if gpu.get("vram_total") and big and big > gpu["vram_total"]:
        rep["warnings"].append("the largest model file (%.1f GB) is bigger than the GPU's %.1f GB: ComfyUI will offload part of it to "
                               "system RAM, which is slower; the smaller Q3_K_M file may help. LOKI cannot tell in advance whether it fits."
                               % (big / 1e9, gpu["vram_total"] / 1e9))
    elif not gpu.get("vram_total"):
        rep["warnings"].append("ComfyUI did not report the GPU's memory; whether this job fits cannot be told in advance")
    rep["ok"] = not rep["blockers"]
    return rep


def _pass_used(wf: dict, key: str, control: str) -> bool:
    sw = wf.get("control_switch")
    up = (wf.get("uploads") or {}).get(key) or {}
    if not sw:
        return True
    return up.get("node") not in ((sw.get("drop") or {}).get(control) or [])


# ------------------------------------------------------------------ running an AI job
def _set(state, job, status=None, msg=None, **fields):
    def fn(m):
        if status:
            m["status"] = status
        m.update(fields)
        if msg:
            _log(m, msg)
    return update(state, job, fn)


def start(state: Any, job: str, client_factory: Callable[[str], Comfy] | None = None, env: dict | None = None,
          poll_s: float = 1.0, wait: bool = False, url: str | None = None) -> dict:
    """Run an AI job. `url` = the ComfyUI it runs on (the Studio's farm picks a worker); default: the saved one."""
    m = manifest(state, job)
    if m is None:
        raise RenderError("no such job")
    if m["kind"] != "ai":
        raise RenderError("only AI jobs run in ComfyUI")
    if m["status"] != "idle":
        raise RenderError("this job has already run (status %s) - use retry" % m["status"])
    target = str(url or settings(state)["url"]).rstrip("/")
    with _LOCK:
        for other in active(state):      # one job at a time per ComfyUI (other machines of the farm run in parallel)
            om = manifest(state, other["job"]) or {}
            if other["job"] != job and other["kind"] == "ai" and other.get("workflow") == m.get("workflow") and \
                    str(om.get("comfy_url") or settings(state)["url"]).rstrip("/") == target:
                raise RenderError("%s is still %s on this workflow; one at a time" % (other["name"], other["status"]))
        stop = threading.Event()
        _CANCEL[job] = stop
        _set(state, job, "preflight", "preflight", comfy_url=target)
    t = threading.Thread(target=_run, args=(state, job, stop, client_factory or (lambda u: Comfy(u)), env, poll_s),
                         name="ai-render-" + job, daemon=True)
    _THREADS[job] = t
    t.start()
    if wait:
        t.join()
    return manifest(state, job)


def _run(state, job, stop, factory, env, poll_s):
    try:
        _run_inner(state, job, stop, factory, env, poll_s)
    except RenderError as exc:
        _set(state, job, "cancelled" if stop.is_set() else "failed", str(exc))
    except Exception as exc:  # noqa: BLE001 - never leave a job hanging in "running"
        _set(state, job, "failed", "%s: %s" % (type(exc).__name__, exc))
    finally:
        _THREADS.pop(job, None)
        _CANCEL.pop(job, None)


def _run_inner(state, job, stop, factory, env, poll_s):
    m = manifest(state, job)
    s = settings(state)
    wf = workflow(m["workflow"])
    cl = factory(m.get("comfy_url") or s["url"])
    rep = preflight(state, wf["name"], m["params"], job=job, client=cl, env=env, control=m.get("control") or "both")
    if not rep["ok"]:
        _set(state, job, "failed", "preflight: " + "; ".join(rep["blockers"])[:560], preflight=rep)
        return
    _set(state, job, "preparing", "preflight ok (%s)" % rep["where"]["note"], machine=rep["url"], preflight=rep, progress=0.02)
    if stop.is_set():
        raise RenderError("cancelled before upload")
    uploaded = {}
    fps = float(m.get("fps") or 16)
    for key, up in (wf.get("uploads") or {}).items():
        if not _pass_used(wf, key, m.get("control") or "both"):
            continue
        frames = _pass_frames(state, job, up["pass"])
        if not frames:
            continue
        if up.get("frames"):
            data, fname = apng(frames, fps), "%s_%s.png" % (job, key)
        else:
            data, fname = frames[0], "%s_%s.png" % (job, key)
        got = cl.upload_image(fname, data, "loki")
        name = safe_name(got.get("name") or "")
        sub = str(got.get("subfolder") or "")
        if not name or not re.match(r"^[A-Za-z0-9_-]*$", sub):
            raise RenderError("ComfyUI stored the upload under an unexpected name")
        uploaded[key] = (sub + "/" + name) if sub else name
        _set(state, job, None, "uploaded %s (%d frame%s, %d KB)" % (key, len(frames) if up.get("frames") else 1,
                                                                    "s" if up.get("frames") and len(frames) != 1 else "", len(data) // 1024))
    params = dict(m["params"])
    params["prefix"] = "loki_render/" + job
    prompt, problems = build_prompt(wf, params, uploaded, m.get("control") or "both")
    if problems:
        raise RenderError("; ".join(problems))
    if wf.get("adaptive"):
        try:
            prompt = adapt(prompt, wf, cl.object_info())
        except Exception:  # noqa: BLE001 - the graph as written is still valid for the version it was written from
            pass
    _write_json(job_dir(state, job) / "prompt.json", prompt)
    pid = str(uuid.uuid4())
    client_id = "loki-" + job
    _set(state, job, "queued", "queued as %s" % pid, prompt_id=pid, progress=0.05)
    if stop.is_set():
        raise RenderError("cancelled before queueing")
    cl.queue_prompt(prompt, client_id, pid)

    # step progress from the websocket, best effort
    prog = {"value": 0, "max": 0, "node": None}

    def on_msg(msg):
        d = msg.get("data") or {}
        if d.get("prompt_id") not in (None, pid):
            return
        if msg.get("type") == "progress":
            prog.update(value=d.get("value", 0), max=d.get("max", 0), node=d.get("node"))
        elif msg.get("type") == "executing":
            prog["node"] = d.get("node")
    ws_stop = threading.Event()
    threading.Thread(target=watch_progress, args=(cl.url, client_id, on_msg, ws_stop), daemon=True).start()

    deadline = time.time() + s["timeout_s"]
    last = None
    try:
        while True:
            if stop.is_set():
                _stop_remote(cl, pid)
                _set(state, job, "cancelled", "cancelled; ComfyUI was asked to stop it")
                return
            if time.time() > deadline:
                _stop_remote(cl, pid)
                raise RenderError("timed out after %d s" % s["timeout_s"])
            hist = cl.history(pid)
            entry = hist.get(pid) if isinstance(hist, dict) else None
            if entry:
                break
            q = cl.queue()
            running = any(isinstance(it, list) and len(it) > 1 and it[1] == pid for it in q.get("queue_running") or [])
            pending = [it[1] for it in q.get("queue_pending") or [] if isinstance(it, list) and len(it) > 1]
            if running:
                frac = (prog["value"] / prog["max"]) if prog["max"] else 0.0
                p = 0.1 + 0.85 * max(0.0, min(1.0, frac))
                now = ("running", round(p, 3), prog["node"])
                if now != last:
                    _set(state, job, "running", None if last and last[0] == "running" else "running on %s" % rep["url"], progress=now[1],
                         step={"value": prog["value"], "max": prog["max"], "node": prog["node"]})
                    last = now
            elif pid in pending:
                pos = pending.index(pid)
                if last != ("queued", pos):
                    _set(state, job, "queued", "waiting in ComfyUI's queue (%d ahead)" % pos)
                    last = ("queued", pos)
            stop.wait(poll_s)
    finally:
        ws_stop.set()
    status = entry.get("status") or {}
    msgs = status.get("messages") or []
    names = [x[0] for x in msgs if isinstance(x, list) and x]
    if status.get("status_str") != "success":
        if "execution_interrupted" in names:
            _set(state, job, "cancelled", "ComfyUI stopped it (interrupted)")
            return
        err = next((x[1] for x in msgs if isinstance(x, list) and len(x) > 1 and x[0] == "execution_error"), {}) or {}
        raise RenderError("ComfyUI failed in node %s (%s): %s" % (err.get("node_id", "?"), err.get("node_type", "?"),
                                                                    str(err.get("exception_message") or "no message").strip()[:400]))
    _set(state, job, None, "finished in ComfyUI; fetching the result", progress=0.97)
    outputs, thumb = [], None
    folder = job_dir(state, job)
    for key, nid in (wf.get("outputs") or {}).items():
        out = (entry.get("outputs") or {}).get(nid) or {}
        for item in (out.get("images") or []) + (out.get("gifs") or []) + (out.get("videos") or []):
            fname = safe_name(item.get("filename"))
            sub = str(item.get("subfolder") or "")
            kind = str(item.get("type") or "output")
            if not fname or kind not in ("output", "temp") or ".." in sub or sub.startswith(("/", "\\")) or ":" in sub:
                _set(state, job, None, "refused an output with an unsafe name: %r" % str(item.get("filename"))[:80])
                continue
            ext = Path(fname).suffix.lower()
            if ext not in OUT_TYPES:
                _set(state, job, None, "skipped %s (not a picture or video)" % fname)
                continue
            data = cl.view(fname, sub, kind)
            local = ("result" if key in ("video", "image", "frames") else key)
            local = "%s%s%s" % (local, "" if len([o for o in outputs if o.startswith(local)]) == 0 else "_%d" % len(outputs), ext)
            (folder / local).write_bytes(data)
            if key == "thumb" or (thumb is None and ext in (".png", ".jpg", ".webp") and key != "frames"):
                thumb = local
            if key != "thumb":
                outputs.append(local)
    if not outputs:
        raise RenderError("ComfyUI finished but sent no picture or video back")
    _set(state, job, "succeeded", "done: %s" % ", ".join(outputs), outputs=outputs, thumb=thumb or m.get("thumb"), progress=1.0)
    _to_home(state, job, folder, outputs, m)


def _to_home(state: Any, job: str, folder: Path, outputs: list, m: dict) -> None:
    """A finished render also lands in the workspace's videos/ (or images/) - Home plays those; a <video> on Home
    cannot send the token /render/file needs, so a render never showed there (owner 2026-10-27: "i have still to
    receive a render")."""
    try:
        ws = Path(getattr(getattr(state, "agent", None), "WORKSPACE", "") or ".")
        for name in outputs:
            ext = Path(name).suffix.lower()
            sub = "videos" if ext in (".webm", ".mp4", ".mov") else "images" if ext in (".png", ".jpg", ".webp") else ""
            if not sub or not (folder / name).is_file():
                continue
            dest = ws / sub / ("render-%s-%s" % (job, name))
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(folder / name, dest)
            side = dest.parent / ".meta" / (dest.name + ".json")
            side.parent.mkdir(exist_ok=True)
            if not side.exists():
                side.write_text(json.dumps({"prompt": str(m.get("prompt") or "")[:1800], "engine": str(m.get("workflow") or ""),
                                            "render_job": job, "t": time.time()}), encoding="utf-8")
            if sub == "videos":
                break          # one video per render is enough on Home
    except Exception:  # noqa: BLE001 - the render itself succeeded; Home is a nicety
        pass


def _stop_remote(cl: Comfy, pid: str) -> None:
    for fn in (cl.interrupt, cl.delete_pending):
        try:
            fn(pid)
        except RenderError:
            pass


def cancel(state: Any, job: str) -> dict:
    m = manifest(state, job)
    if m is None:
        raise RenderError("no such job")
    if m["status"] in FINAL:
        return m
    ev = _CANCEL.get(job)
    if ev:
        ev.set()
        _set(state, job, None, "cancel asked")
        return manifest(state, job)
    if m["kind"] == "ai" and m.get("prompt_id") and m["status"] in ("queued", "running"):   # e.g. after a restart
        _stop_remote(Comfy(m.get("comfy_url") or settings(state)["url"]), m["prompt_id"])
    return _set(state, job, "cancelled", "cancelled")


def retry(state: Any, job: str) -> dict:
    m = manifest(state, job)
    if m is None:
        raise RenderError("no such job")
    made = new_job(state, {**m, "name": (m["name"] + " (retry)")[:120]})
    src, dst = job_dir(state, job) / "passes", job_dir(state, made["job"]) / "passes"
    if src.is_dir():
        shutil.copytree(src, dst)
    if (job_dir(state, job) / "thumb.png").is_file() and m["kind"] == "ai":
        shutil.copy2(job_dir(state, job) / "thumb.png", job_dir(state, made["job"]) / "thumb.png")

    def fn(mm):
        mm["passes"] = m.get("passes") or {}
        mm["thumb"] = "thumb.png" if (job_dir(state, made["job"]) / "thumb.png").is_file() else None
        _log(mm, "retry of %s" % job)
    return {"job": made["job"], "manifest": update(state, made["job"], fn)}


def finish(state: Any, job: str, data: dict) -> dict:
    """A path-traced job (rendered in the window by forge_render.js): its beauty frames are in; list them as outputs."""
    m = manifest(state, job)
    if m is None:
        raise RenderError("no such job")
    if m["kind"] != "path":
        raise RenderError("finish is for path-traced jobs")
    status = data.get("status") if data.get("status") in FINAL else "succeeded"
    frames = sorted((job_dir(state, job) / "passes" / "beauty").glob("*.png"))
    outputs = ["passes/beauty/" + p.name for p in frames]
    if frames and len(frames) > 1:
        try:
            (job_dir(state, job) / "result.png").write_bytes(apng([p.read_bytes() for p in frames], float(m.get("fps") or 24)))
            outputs.insert(0, "result.png")
        except RenderError:
            pass
    elif frames:
        shutil.copy2(frames[0], job_dir(state, job) / "result.png")
        outputs.insert(0, "result.png")

    def fn(mm):
        mm["status"] = status
        mm["outputs"] = outputs
        mm["progress"] = 1.0 if status == "succeeded" else mm.get("progress", 0)
        for line in (data.get("log") or [])[:20]:
            _log(mm, str(line))
        _log(mm, "%s: %d frame%s" % (status, len(frames), "" if len(frames) == 1 else "s"))
    return update(state, job, fn)


# ------------------------------------------------------------------ AI speed-ups of a finished path-traced render
# Owner 2026-10-25: "i want ai to speed up my renders". Render less with the path tracer, let AI do the rest on the
# farm's GPU: upscale = path-trace at half width and height (4x fewer pixels), Real-ESRGAN brings it back;
# interpolate = path-trace every 2nd / 4th frame, RIFE makes the in-betweens.
POST_OPS = {"upscale": "ai_upscale", "interpolate": "ai_interpolate"}


def post_job(state: Any, source: str, op: str, factor: int = 2) -> dict:
    """A new AI job that takes `source`'s path-traced frames (its beauty pass) through an AI speed-up graph."""
    m = manifest(state, source)
    if m is None:
        raise RenderError("no such job")
    if m.get("kind") != "path" or m.get("status") != "succeeded":
        raise RenderError("AI speed-ups work on a finished path-traced render")
    frames = sorted((job_dir(state, source) / "passes" / "beauty").glob("*.png"))
    if not frames:
        raise RenderError("that render has no frames")
    if op not in POST_OPS:
        raise RenderError("unknown speed-up %r (upscale or interpolate)" % op)
    factor = int(factor)
    fps = float(m.get("fps") or 24)
    if op == "upscale":
        if factor not in (2, 4):
            raise RenderError("upscale is 2x or 4x")
        params = {"scale_by": 0.5 if factor == 2 else 1.0, "fps": fps}
        size = [int(x) * factor for x in (m.get("size") or [0, 0])]
        n, label = len(frames), "AI upscale %dx" % factor
    else:
        if factor not in (2, 3, 4):
            raise RenderError("in-betweens are x2, x3 or x4")
        if len(frames) < 2:
            raise RenderError("in-betweens need at least two frames")
        params = {"multiplier": factor, "fps": fps * factor}
        size = list(m.get("size") or [0, 0])
        n, label = (len(frames) - 1) * factor + 1, "AI in-betweens x%d" % factor
    made = new_job(state, {"kind": "ai", "workflow": POST_OPS[op], "name": "%s - %s" % (m.get("name") or source, label),
                           "frames": n, "fps": params["fps"], "size": size, "camera": m.get("camera"), "params": params,
                           "project": m.get("project")})
    job = made["job"]
    dst = job_dir(state, job) / "passes" / "beauty"
    shutil.copytree(job_dir(state, source) / "passes" / "beauty", dst)
    info = png_info(frames[0].read_bytes())

    def fn(mm):
        mm["passes"] = {"beauty": {"frames": len(frames), "width": info["width"], "height": info["height"], "folder": "passes/beauty"}}
        mm["source"] = source
        mm["post"] = {"op": op, "factor": factor}
        if (job_dir(state, source) / "thumb.png").is_file():
            shutil.copy2(job_dir(state, source) / "thumb.png", job_dir(state, job) / "thumb.png")
            mm["thumb"] = "thumb.png"
        elif frames:
            shutil.copy2(frames[0], job_dir(state, job) / "thumb.png")
            mm["thumb"] = "thumb.png"
        _log(mm, "%s of %s (%d frames in)" % (label, source, len(frames)))
    return {"job": job, "manifest": update(state, job, fn)}


# ------------------------------------------------------------------ presets per project
def _preset_file(state: Any, project: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(project or "default"))[:60].strip("._") or "default"
    return renders_dir(state) / ".presets" / (slug + ".json")


def presets(state: Any, project: str) -> dict:
    p = _read_json(_preset_file(state, project), {})
    return p if isinstance(p, dict) else {}


def save_preset(state: Any, project: str, name: str, params: Any) -> dict:
    name = str(name or "").strip()[:60]
    if not name:
        raise RenderError("a preset needs a name")
    allp = presets(state, project)
    if params is None:
        allp.pop(name, None)
    elif isinstance(params, dict):
        allp[name] = {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool)) or v is None}
    else:
        raise RenderError("params must be an object")
    _write_json(_preset_file(state, project), allp)
    return allp


# ------------------------------------------------------------------ the bridge's entry points
def status(state: Any) -> dict:
    s = settings(state)
    return {"ok": True, "settings": {**s, "url_shown": redact(s["url"]), "where": where(s["url"])},
            "workflows": [describe(w) for w in workflows().values()], "jobs": list_jobs(state)[:200],
            "active": [j["job"] for j in active(state)]}


def handle_get(state: Any, path: str) -> tuple:
    route = urlparse(path).path
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    try:
        if route == "/render/status":
            return 200, status(state)
        if route == "/render/job":
            m = manifest(state, q.get("id", ""))
            return (200, {"ok": True, "job": q["id"], "manifest": m}) if m else (404, {"ok": False, "error": "no such job"})
        if route == "/render/file":
            folder = job_dir(state, q.get("job", ""))
            rel = str(q.get("name") or "")
            parts = rel.split("/")
            if not 1 <= len(parts) <= 3 or any(safe_name(p) is None for p in parts) or (len(parts) > 1 and parts[0] != "passes"):
                return 400, {"ok": False, "error": "bad file name"}
            f = folder.joinpath(*parts)
            if not f.is_file() or f.suffix.lower() not in OUT_TYPES:
                return 404, {"ok": False, "error": "no such file"}
            return 200, f.read_bytes(), OUT_TYPES[f.suffix.lower()]
        if route == "/render/presets":
            return 200, {"ok": True, "presets": presets(state, q.get("project", ""))}
        if route == "/render/workflows":
            return 200, {"ok": True, "workflows": [describe(w) for w in workflows().values()]}
        if route == "/render/graph":
            return 200, {"ok": True, **graph(workflow(q.get("workflow") or "vace_render"))}
    except RenderError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}


def handle_post(state: Any, path: str, body: bytes, client_factory: Callable | None = None) -> tuple:
    route = urlparse(path).path
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    try:
        if route == "/render/upload-pass":
            try:
                index = int(q.get("index", "0"))
            except ValueError:
                return 400, {"ok": False, "error": "index must be a number"}
            m = save_pass(state, q.get("job", ""), q.get("pass", ""), index, body)
            return 200, {"ok": True, "passes": m["passes"]}
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            return 400, {"ok": False, "error": "Invalid JSON body."}
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "JSON body must be an object."}
        if route == "/render/settings":
            s = save_settings(state, data)
            return 200, {"ok": True, "settings": {**s, "url_shown": redact(s["url"]), "where": where(s["url"])}}
        if route == "/render/test":
            url = str(data.get("url") or settings(state)["url"]).rstrip("/")
            cl = (client_factory or Comfy)(url)
            stats = cl.system_stats()
            dev = (stats.get("devices") or [{}])[0]
            return 200, {"ok": True, "url": redact(url), "where": where(url), "version": (stats.get("system") or {}).get("comfyui_version"),
                         "os": (stats.get("system") or {}).get("os"), "gpu": dev.get("name"), "vram_total": dev.get("vram_total")}
        if route == "/render/preflight":
            cl = (client_factory or Comfy)(settings(state)["url"])
            rep = preflight(state, str(data.get("workflow") or "vace_render"), data.get("params") or {}, job=data.get("job") or None,
                            client=cl, control=str(data.get("control") or "both"))
            return 200, {"ok": True, "report": rep}
        if route == "/render/new":
            return 200, {"ok": True, **new_job(state, data)}
        if route == "/render/start":
            m = start(state, str(data.get("job") or ""), client_factory=client_factory)
            return 200, {"ok": True, "manifest": m}
        if route == "/render/cancel":
            return 200, {"ok": True, "manifest": cancel(state, str(data.get("job") or ""))}
        if route == "/render/retry":
            return 200, {"ok": True, **retry(state, str(data.get("job") or ""))}
        if route == "/render/post":
            return 200, {"ok": True, **post_job(state, str(data.get("job") or ""), str(data.get("op") or ""), int(data.get("factor") or 2))}
        if route == "/render/finish":
            return 200, {"ok": True, "manifest": finish(state, str(data.get("job") or ""), data)}
        if route == "/render/presets":
            return 200, {"ok": True, "presets": save_preset(state, str(data.get("project") or ""), data.get("name"), data.get("params"))}
    except RenderError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
