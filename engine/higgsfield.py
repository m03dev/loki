"""Higgsfield - images and video from Higgsfield's cloud (https://cloud.higgsfield.ai).

The protocol is the one the official SDK speaks (github.com/higgsfield-ai/higgsfield-client,
Apache-2.0), written here with the standard library so LOKI needs no extra package:

    POST https://api.higgsfield.ai/<application>         body = the arguments (JSON)
         Authorization: Key <api-key>:<api-secret>
      -> {"request_id", "status_url", "cancel_url"}
    GET  <status_url>  -> {"status": queued|in_progress|completed|failed|nsfw|canceled,
                           "images": [{"url"}], "video": {"url"}, ...}

The key is the user's: pasted in Settings > General ("Higgsfield key") and saved as
HIGGSFIELD_KEY in LOKI's own .env. The SDK's names (HF_KEY, or HF_API_KEY + HF_API_SECRET)
work too. LOKI never looks for keys anywhere else. Every generation spends the user's
Higgsfield credits, so nothing here runs on its own - only when the user or the agent asks.
Results are downloaded into the workspace (Higgsfield keeps outputs for a limited time).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://api.higgsfield.ai"
IMAGE_APP = "bytedance/seedream/v4/text-to-image"   # the SDK's own example application
USER_AGENT = "loki-higgsfield/1.0"
DONE = {"completed", "failed", "nsfw", "canceled", "cancelled"}
MAX_DOWNLOAD = 200 * 1024 * 1024
_APP_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)+$", re.I)


def credential(env: dict | None = None) -> str:
    env = env if env is not None else os.environ
    for name in ("HIGGSFIELD_KEY", "HF_KEY"):
        value = str(env.get(name, "")).strip()
        if value:
            return value
    key, secret = str(env.get("HF_API_KEY", "")).strip(), str(env.get("HF_API_SECRET", "")).strip()
    return "%s:%s" % (key, secret) if key and secret else ""


def configured(env: dict | None = None) -> bool:
    return bool(credential(env))


def _call(method: str, url: str, key: str, body: dict | None = None, timeout: float = 60.0,
          opener=urllib.request.urlopen) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Key " + key, "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
            detail = detail.get("detail") or detail.get("error") or detail.get("message") or detail
        except Exception:  # noqa: BLE001
            detail = exc.reason
        hint = " - check the Higgsfield key in Settings > General" if exc.code in (401, 403) else ""
        raise RuntimeError("Higgsfield said %s: %s%s" % (exc.code, str(detail)[:300], hint)) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError("could not reach Higgsfield: %s" % exc) from None


def outputs(result: dict) -> list:
    """Every media URL in a finished request, images first."""
    urls = []
    for item in result.get("images") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    for key in ("video", "image", "audio"):
        item = result.get(key)
        if isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    for item in result.get("videos") or []:
        if isinstance(item, dict) and item.get("url"):
            urls.append(item["url"])
    return urls


def submit(application: str, arguments: dict, env: dict | None = None, opener=urllib.request.urlopen) -> dict:
    key = credential(env)
    if not key:
        return {"ok": False, "error": "no Higgsfield key yet - paste KEY:SECRET from cloud.higgsfield.ai "
                                      "into Settings > General > Higgsfield key"}
    application = (application or IMAGE_APP).strip().strip("/")
    if not _APP_RE.match(application):
        return {"ok": False, "error": "not a Higgsfield application id: %r" % application}
    try:
        data = _call("POST", "%s/%s" % (BASE_URL, application), key, arguments, opener=opener)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    rid = data.get("request_id")
    if not rid:
        return {"ok": False, "error": "Higgsfield gave no request id: %s" % str(data)[:200]}
    return {"ok": True, "request_id": rid,
            "status_url": data.get("status_url") or "%s/requests/%s/status" % (BASE_URL, rid)}


def wait(status_url: str, env: dict | None = None, timeout: float = 600.0, delay: float = 2.0,
         opener=urllib.request.urlopen, sleep=time.sleep) -> dict:
    key = credential(env)
    if not status_url.startswith(BASE_URL + "/"):
        return {"ok": False, "error": "refusing a status URL outside Higgsfield"}
    deadline = time.monotonic() + timeout
    last = {}
    while True:
        try:
            last = _call("GET", status_url, key, opener=opener)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        status = str(last.get("status", "")).lower()
        if status in DONE:
            break
        if time.monotonic() > deadline:
            return {"ok": False, "error": "still %s after %d s - ask again later" % (status or "waiting", timeout),
                    "status_url": status_url}
        sleep(delay)
        delay = min(delay * 1.5, 10.0)
    if status != "completed":
        return {"ok": False, "error": {"nsfw": "Higgsfield refused it as NSFW", "failed": "Higgsfield failed it"}
                .get(status, "the request was %s" % status), "result": last}
    return {"ok": True, "result": last, "urls": outputs(last)}


def _download(url: str, folder: Path, stem: str, opener=urllib.request.urlopen) -> str:
    if not url.startswith("https://"):
        return ""
    ext = os.path.splitext(url.split("?", 1)[0])[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mp3", ".wav"):
        ext = ".bin"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (stem + ext)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(req, timeout=120) as resp, target.open("wb") as out:
        total = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                break
            out.write(chunk)
    return str(target)


def generate(prompt: str, kind: str = "image", application: str = "", workspace: Path | None = None,
             aspect_ratio: str = "16:9", extra: dict | None = None, env: dict | None = None,
             opener=urllib.request.urlopen, sleep=time.sleep, timeout: float = 600.0) -> dict:
    """Make an image (or a video, with a video application id) and save it in the workspace."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "give a prompt"}
    kind = (kind or "image").lower()
    if kind != "image" and not application:
        return {"ok": False, "error": "for %s, give model= the Higgsfield application id from "
                                      "cloud.higgsfield.ai (for example the one its docs show for text-to-video)" % kind}
    args = {"prompt": prompt[:4000]}
    if kind == "image" and (application or IMAGE_APP) == IMAGE_APP:
        args.update({"resolution": "2K", "aspect_ratio": aspect_ratio or "16:9", "camera_fixed": False})
    elif aspect_ratio:
        args["aspect_ratio"] = aspect_ratio
    args.update(extra or {})
    sent = submit(application or IMAGE_APP, args, env=env, opener=opener)
    if not sent["ok"]:
        return sent
    done = wait(sent["status_url"], env=env, opener=opener, sleep=sleep, timeout=timeout)
    if not done["ok"]:
        done["request_id"] = sent["request_id"]
        return done
    files = []
    if workspace is not None:
        folder = Path(workspace) / ("videos" if kind == "video" else "images")
        stem = "higgsfield-" + time.strftime("%Y%m%d-%H%M%S")
        for i, url in enumerate(done["urls"]):
            try:
                path = _download(url, folder, stem + ("-%d" % i if i else ""), opener=opener)
            except (OSError, urllib.error.URLError):
                path = ""
            if path:
                files.append(str(Path(path).relative_to(Path(workspace))).replace("\\", "/"))
    return {"ok": True, "request_id": sent["request_id"], "urls": done["urls"], "files": files,
            "application": application or IMAGE_APP}


def status() -> dict:
    return {"configured": configured(), "image_app": IMAGE_APP, "base_url": BASE_URL}
