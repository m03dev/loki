"""Every model downloaded on THIS computer, and removing one (owner 2026-10-25 12:37: "i should be able to see what
models i have downloaded and i can uninstall them from my system from loki in that local tab").

  GET  /local/models          [{id, kind, name, size_gb, where, loaded, used_by}] + the disk's free space
                              kind: ollama (Ollama's own list; LOKI's "loki-<name>" long-context copies are shown with
                              the model they belong to), image (LOKI's image models: sd.cpp GGUFs), hf (the Hugging Face
                              cache: mflux / MLX / diffusers downloads)
  POST /local/models/remove   {id}  Ollama: its own DELETE /api/delete (plus LOKI's loki-<name> copy of it, which
                              shares the same files - otherwise no space comes back); a folder or file: deleted, only
                              inside those model folders, never anything else
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434").rstrip("/")


def _req(method: str, path: str, body: dict | None = None, timeout: float = 10, opener=urllib.request.urlopen) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(OLLAMA + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with opener(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8") or "{}"
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for dirpath, _, files in os.walk(p):
        for f in files:
            try:
                total += (Path(dirpath) / f).stat().st_size
            except OSError:
                pass
    return total


def hf_cache() -> Path:
    env = os.environ
    if env.get("HF_HUB_CACHE"):
        return Path(env["HF_HUB_CACHE"]).expanduser()
    return Path(env.get("HF_HOME") or Path.home() / ".cache" / "huggingface").expanduser() / "hub"


def image_dir() -> Path:
    import creative  # pylint: disable=import-outside-toplevel
    return Path(creative.models_dir())


def _ollama(opener) -> tuple:
    try:
        tags = _req("GET", "/api/tags", opener=opener).get("models") or []
    except Exception as exc:  # noqa: BLE001
        return [], "Ollama is not running (%s) - start it to see and remove its models." % str(exc)[:80]
    try:
        loaded = {m.get("name") for m in (_req("GET", "/api/ps", opener=opener).get("models") or [])}
    except Exception:  # noqa: BLE001
        loaded = set()
    import model_setup  # pylint: disable=import-outside-toplevel - its loki-<model> naming
    names = [str(m.get("name") or "") for m in tags]
    copies = {}
    for n in names:                      # which base model each LOKI long-context copy belongs to
        for cand in (n, n.split(":")[0], n[:-len(":latest")] if n.endswith(":latest") else n):
            copies.setdefault(model_setup.derived_name(cand), n)
    out = []
    for m in tags:
        name = str(m.get("name") or "")
        if not name:
            continue
        d = m.get("details") or {}
        short = name[:-len(":latest")] if name.endswith(":latest") else name
        out.append({"id": "ollama:" + name, "kind": "ollama", "name": name, "size_gb": round(float(m.get("size") or 0) / 2**30, 2),
                    "params": d.get("parameter_size", ""), "quant": d.get("quantization_level", ""),
                    "family": d.get("family", ""), "loaded": name in loaded, "modified": m.get("modified_at", ""),
                    "where": "Ollama", "copy_of": copies.get(short, "") if short.startswith("loki-") else ""})
    return out, ""


def _files() -> list:
    out = []
    try:
        d = image_dir()
        for p in sorted(d.glob("*.gguf")) + sorted(d.glob("*.safetensors")) if d.is_dir() else []:
            out.append({"id": "image:" + p.name, "kind": "image", "name": p.name, "size_gb": round(_size(p) / 2**30, 2),
                        "where": str(d)})
    except Exception:  # noqa: BLE001
        pass
    hub = hf_cache()
    if hub.is_dir():
        for p in sorted(hub.glob("models--*")):
            out.append({"id": "hf:" + p.name, "kind": "hf", "name": p.name[len("models--"):].replace("--", "/"),
                        "size_gb": round(_size(p) / 2**30, 2), "where": str(hub)})
    return out


def listing(opener=urllib.request.urlopen) -> dict:
    ollama, note = _ollama(opener)
    files = _files()
    try:
        free = round(shutil.disk_usage(str(Path.home())).free / 2**30, 1)
    except OSError:
        free = None
    total = round(sum(m["size_gb"] for m in ollama if not m["name"].startswith("loki-")) +
                  sum(m["size_gb"] for m in files), 1)
    return {"ok": True, "models": ollama + files, "ollama_note": note, "free_gb": free, "total_gb": total}


def remove(model_id: str, opener=urllib.request.urlopen, rm=shutil.rmtree) -> dict:
    kind, _, name = str(model_id or "").partition(":")
    if not name:
        raise ValueError("which model?")
    if kind == "ollama":
        gone = []
        for m in _ollama(opener)[0]:          # this model, and LOKI's loki-<name> copy of it (same files)
            if m["name"] == name or (m["name"].startswith("loki-") and m.get("copy_of") == name):
                _req("DELETE", "/api/delete", {"model": m["name"]}, timeout=60, opener=opener)
                gone.append(m["name"])
        if not gone:
            raise ValueError("Ollama has no model called %s" % name)
        return {"ok": True, "removed": gone}
    if kind in ("image", "hf"):
        base = image_dir() if kind == "image" else hf_cache()
        target = (base / name).resolve()
        if base.resolve() not in target.parents or not target.exists():
            raise ValueError("no such model file: %s" % name)
        size = _size(target)
        if target.is_dir():
            rm(target)
        else:
            target.unlink()
        return {"ok": True, "removed": [name], "freed_gb": round(size / 2**30, 2)}
    raise ValueError("unknown model kind %s" % kind)


def route(state: Any, method: str, path: str, query: dict, body: dict) -> tuple:  # noqa: ARG001
    try:
        if method == "GET" and path == "/local/models":
            return 200, listing()
        if method == "POST" and path == "/local/models/remove":
            return 200, remove(str(body.get("id") or ""))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}
    return 404, {"ok": False, "error": "Unknown endpoint."}
