"""Loki the conductor - one agent in charge, specialists on call.

Everything starts with Loki. It plans, keeps the conversation and owns the tools; when a
step needs a specialist it calls the `conductor` tool with a ROLE, and this module routes
the call to whichever enabled capability can do it:

    research   Perplexity Sonar - a cited web answer          (capability: perplexity)
    read_web   one page as markdown: crawl4ai, scrapling or a self-hosted Firecrawl,
               first one enabled wins (LOKI_READ_ORDER)          (crawl4ai/scrapling/firecrawl)
    browse     a real browser does a task (browser-use)        (browser-use) - always asks
    remember   store a lasting fact in Hindsight               (hindsight)
    recall     ask Hindsight what it knows                     (hindsight)
    media      video/audio: transcripts, details, downloads     (media: yt-dlp)
    image      make an image                                   (image-gen: Z-Image Turbo / Pollinations)
    reach      the web through Agent Reach: pages, GitHub      (agent-reach)
    track      track objects in a workspace video (RF-DETR + Roboflow trackers)  (vision-track)
    scrape     one page as markdown, or crawl a site into scraped/<domain>/ (scrapling);
               without Scrapling it falls back to read_web and says how to install it

Specialists that run for minutes (Claude Code, Codex, Hermes Agent) are background jobs the
USER starts (workers.py); the model cannot spawn them. Headroom (context compression) and
SkillSpector (deep skill scanning) are not roles: they sit in the loop - Headroom shrinks the
messages before each model call, SkillSpector adds findings to the skill scan.

Every role is checked by the policy engine first (capability on, permission granted,
network host allowed). Heavy libraries run in `runners/` child processes with a timeout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import policy

RUNNERS = Path(__file__).resolve().parent / "runners"
READ_BACKENDS = ("crawl4ai", "scrapling", "firecrawl")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
MAX_TEXT = 20_000

ROLES: dict[str, dict] = {
    "research": {"capabilities": ("vane", "perplexity"), "permission": "",
                 "permissions": {"vane": "network:loopback", "perplexity": "network:api.perplexity.ai"},
                 "summary": "a cited answer from the live web (Vane, private and local; or Perplexity)",
                 "ask": False},
    "read_web": {"capabilities": READ_BACKENDS, "permission": "",
                 "summary": "read one web page as markdown (url=...)", "ask": False},
    "browse": {"capabilities": ("browser-use",), "permission": "network",
               "summary": "let a real browser do a task on websites (asks you first)", "ask": True},
    "remember": {"capabilities": ("hindsight",), "permission": "",
                 "summary": "store a lasting fact in long-term memory (Hindsight)", "ask": False},
    "recall": {"capabilities": ("hindsight",), "permission": "",
               "summary": "ask long-term memory what it knows (Hindsight)", "ask": False},
    "media": {"capabilities": ("media",), "permission": "network",
              "summary": "video/audio via yt-dlp: url=..., task='transcript' (default), 'info', "
                         "'audio', 'video', or 'search: <words>'", "ask": False},
    "image": {"capabilities": ("image-gen",), "permission": "fs:workspace",
              "summary": "make an image from task=<prompt> (locally: stable-diffusion.cpp on the PC, mflux on "
                         "the Mac, or Z-Image Turbo; else Pollinations); "
                         "saved in images/", "ask": False},
    "reach": {"capabilities": ("agent-reach",), "permission": "network",
              "summary": "Agent Reach: url=<page> reads it as text; task='github: <words or repo url>'; "
                         "task='doctor' lists the channels that work here", "ask": False},
    "track": {"capabilities": ("vision-track",), "permission": "fs:workspace",
              "summary": "track objects in a video in the workspace: url=<video path>, task='car' (what to "
                         "track; empty = everything; optional 'tracker=ocsort' 'max_frames=300'); writes an "
                         "annotated MP4 and a JSON/CSV per track into tracks/", "ask": False},
    "scrape": {"capabilities": ("scrapling",), "permission": "network",
               "summary": "Scrapling: url=<page> as markdown; task='crawl max_pages=20' crawls the site into "
                          "scraped/<domain>/; task='dynamic' renders JavaScript first", "ask": False},
}
SCRAPE_INSTALL = ("install Scrapling for full scraping and crawling: python tools/setup_extras.py scrapling "
                  "(then turn on scrapling in Settings > Add-ons)")


class Conductor:
    def __init__(self, engine: policy.PolicyEngine, registry: Any, env: dict | None = None,
                 runner: Callable[..., Any] = subprocess.run, opener: Callable[..., Any] = urllib.request.urlopen,
                 python: str | list | None = None) -> None:
        self.policy = engine
        self.registry = registry
        self.env = env if env is not None else os.environ
        self.runner = runner
        self.opener = opener
        self.python = python_command() if python is None else ([python, "-I"] if isinstance(python, str) else list(python))

    # ------------------------------------------------------------- roster
    def _ready(self, capability: str, permission: str = "") -> policy.Verdict:
        return self.policy.capability(capability, permission)

    def pick(self, role: str) -> tuple[str, str]:
        """(capability to use, "") or ("", why none can)."""
        spec = ROLES.get(role)
        if spec is None:
            return "", "unknown role %r (roles: %s)" % (role, ", ".join(ROLES))
        candidates = list(spec["capabilities"])
        if role == "read_web":
            order = [c.strip() for c in str(self.env.get("LOKI_READ_ORDER", "")).split(",") if c.strip()]
            candidates = [c for c in order if c in READ_BACKENDS] + [c for c in READ_BACKENDS if c not in order]
        if role == "research":
            order = [c.strip() for c in str(self.env.get("LOKI_RESEARCH_ORDER", "")).split(",") if c.strip()]
            candidates = [c for c in order if c in spec["capabilities"]] + \
                [c for c in spec["capabilities"] if c not in order]
        reasons = []
        for capability in candidates:
            verdict = self._ready(capability, spec.get("permissions", {}).get(capability, spec["permission"]))
            if verdict.allowed:
                return capability, ""
            reasons.append(verdict.reason)
        return "", "; ".join(reasons)

    def roster(self) -> list[dict]:
        rows = []
        for role, spec in ROLES.items():
            via, why = self.pick(role)
            rows.append({"role": role, "summary": spec["summary"], "ready": bool(via), "via": via, "why": why})
        return rows

    def prompt_section(self) -> str:
        roster = self.roster()
        ready = [r for r in roster if r["ready"]]
        off = [r for r in roster if not r["ready"]]
        # A specialist that WAS on but is blocked now (its add-on changed, lost a requirement)
        # must be explained even when no other specialist is ready: otherwise the model invents
        # a reason ("requires approval for external calls") instead of saying the real one.
        blocked = [r for r in off if "not enabled" not in r["why"]]
        if not ready and not blocked:
            return ""
        lines = ["# Specialists you can call"]
        if ready:
            lines.append("You are the conductor. For these steps call the `conductor` tool with a role "
                         "instead of guessing:")
            lines += ["- %s: %s (via %s)" % (r["role"], r["summary"], r["via"]) for r in ready]
        else:
            lines.append("No specialist is ready right now.")
        if off:   # so the model tells the user the real reason instead of inventing one
            lines.append("Not available right now (say this reason if the user asks for one of these):")
            lines += ["- %s: %s" % (r["role"], r["why"][:160]) for r in off]
        return "\n".join(lines)

    def needs_approval(self, role: str) -> bool:
        return bool(ROLES.get(role, {}).get("ask"))

    # ------------------------------------------------------------- dispatch
    def run(self, role: str, task: str = "", url: str = "") -> str:
        if role == "scrape":   # has its own fallback, so it never stops at pick()
            return self.scrape(url or task, task)
        capability, why = self.pick(role)
        if not capability:
            return "error: no specialist for %r is ready - %s" % (role, why)
        try:
            if role == "research":
                return self.vane(task) if capability == "vane" else self.research(task)
            if role == "read_web":
                return self.read_web(capability, url or task)
            if role == "browse":
                return self.browse(task)
            if role in ("remember", "recall"):
                return self.hindsight("retain" if role == "remember" else "recall", task)
            if role == "media":
                return self.media(task, url)
            if role == "image":
                return self.image(task)
            if role == "reach":
                return self.reach(task, url)
            if role == "track":
                return self.track(task, url)
        except Exception as exc:  # noqa: BLE001 - a specialist failing must not end the turn
            return "error: %s failed: %s: %s" % (capability, type(exc).__name__, exc)
        return "error: role %r is not wired" % role

    # ------------------------------------------------------------- specialists
    def _post_json(self, url: str, body: dict, headers: dict, timeout: float) -> dict:
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", **headers})
        try:
            with self.opener(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else ""
            raise RuntimeError("HTTP %s %s" % (exc.code, detail)) from None

    def research(self, question: str) -> str:
        if not question.strip():
            return "error: research needs a question"
        key = str(self.env.get("PERPLEXITY_API_KEY", "")).strip()
        model = str(self.env.get("LOKI_PERPLEXITY_MODEL", "sonar")) or "sonar"
        data = self._post_json(PERPLEXITY_URL, {"model": model, "messages": [
            {"role": "system", "content": "Answer concisely with sources."},
            {"role": "user", "content": question}]}, {"Authorization": "Bearer " + key}, timeout=90)
        answer = ""
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            answer = json.dumps(data)[:2000]
        sources = [s.get("url", "") for s in data.get("search_results", []) if isinstance(s, dict)] \
            or [c for c in data.get("citations", []) if isinstance(c, str)]
        if sources:
            answer += "\n\nSources:\n" + "\n".join("[%d] %s" % (i + 1, u) for i, u in enumerate(sources[:12]))
        return answer

    def _get_json(self, url: str, timeout: float) -> Any:
        with self.opener(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def vane(self, question: str) -> str:
        """Vane (ItzCrazyKns/Vane, MIT): a self-hosted answering engine over SearxNG that can
        run on local Ollama models - private research with no API key.
        GET /api/providers picks the models; POST /api/search returns {message, sources}."""
        if not question.strip():
            return "error: research needs a question"
        base = str(self.env.get("VANE_URL", "http://127.0.0.1:3000")).rstrip("/")
        providers = self._get_json(base + "/api/providers", timeout=10)
        providers = providers.get("providers", providers) if isinstance(providers, dict) else providers
        chat, embed = pick_vane_models(providers if isinstance(providers, list) else [],
                                       str(self.env.get("LOKI_VANE_CHAT", "")))
        if not chat or not embed:
            return "error: Vane has no chat or embedding model set up - open it at %s and add one" % base
        data = self._post_json(base + "/api/search", {
            "chatModel": chat, "embeddingModel": embed, "sources": ["web"],
            "optimizationMode": str(self.env.get("LOKI_VANE_MODE", "speed")),
            "query": question, "history": [], "stream": False}, {}, timeout=180)
        answer = str(data.get("message", "")).strip() or "(Vane returned no answer)"
        sources = [((s.get("metadata") or {}).get("url", ""), (s.get("metadata") or {}).get("title", ""))
                   for s in data.get("sources", []) if isinstance(s, dict)]
        sources = [s for s in sources if s[0]]
        if sources:
            answer += "\n\nSources:\n" + "\n".join("[%d] %s %s" % (i + 1, t, u) for i, (u, t) in enumerate(sources[:12]))
        return answer

    def _runner(self, name: str, job: dict, timeout: int) -> dict:
        script = RUNNERS / (name + ".py")
        try:
            proc = self.runner([*self.python, str(script)], input=json.dumps(job), capture_output=True,
                               text=True, timeout=timeout, shell=False)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "%s timed out after %ds" % (name, timeout)}
        lines = [l for l in (proc.stdout or "").splitlines() if l.strip().startswith("{")]
        if not lines:
            return {"ok": False, "error": "%s produced no result: %s" % (name, (proc.stderr or "").strip()[-300:])}
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return {"ok": False, "error": "%s returned bad JSON" % name}

    def read_web(self, capability: str, url: str) -> str:
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "error: read_web needs an http(s) url"
        if capability == "firecrawl":
            base = str(self.env.get("LOKI_FIRECRAWL_URL", "http://localhost:3002")).rstrip("/")
            verdict = self.policy.network(base, "firecrawl")
            if not verdict.allowed:
                return "error: " + verdict.reason
            headers = {}
            if self.env.get("FIRECRAWL_API_KEY"):
                headers["Authorization"] = "Bearer " + self.env["FIRECRAWL_API_KEY"]
            data = self._post_json(base + "/v2/scrape", {"url": url, "formats": ["markdown"]}, headers, timeout=120)
            body = data.get("data", data) if isinstance(data, dict) else {}
            text = str(body.get("markdown", "") or "")
            return text[:MAX_TEXT] if text else "error: firecrawl returned no markdown: %s" % json.dumps(data)[:300]
        result = self._runner("web_read", {"backend": capability, "url": url, "max_chars": MAX_TEXT}, timeout=120)
        if not result.get("ok"):
            return "error: " + str(result.get("error"))
        return str(result.get("text", "")) + ("\n[truncated]" if result.get("truncated") else "")

    def browse(self, task: str) -> str:
        job = {"task": task, "model": self.env.get("LOKI_BROWSE_MODEL", ""),
               "base_url": self.env.get("LOKI_BROWSE_BASE_URL", ""),
               "api_key": self.env.get("LOKI_BROWSE_API_KEY", "") or self.env.get("OPENAI_API_KEY", ""),
               "max_steps": int(self.env.get("LOKI_BROWSE_MAX_STEPS", "25") or 25)}
        result = self._runner("browse", job, timeout=int(self.env.get("LOKI_BROWSE_TIMEOUT", "600") or 600))
        return str(result.get("text")) if result.get("ok") else "error: " + str(result.get("error"))

    def hindsight(self, op: str, text: str) -> str:
        base = str(self.env.get("HINDSIGHT_URL", "http://localhost:8888")).rstrip("/")
        verdict = self.policy.network(base, "hindsight")
        if not verdict.allowed:
            return "error: " + verdict.reason
        job = {"op": op, "base_url": base, "bank": self.env.get("LOKI_HINDSIGHT_BANK", "loki"),
               "content": text, "query": text}
        result = self._runner("hindsight", job, timeout=120)
        if not result.get("ok"):
            return "error: " + str(result.get("error"))
        return "stored in long-term memory" if op == "retain" else json.dumps(result.get("result"), default=str)[:MAX_TEXT]


# ---------------------------------------------------------------- media / image / reach
def _workspace(env) -> Path:
    return Path(str(env.get("LOKI_WORKSPACE") or Path.cwd()))


def _conductor_media(self, task: str, url: str) -> str:
    task = (task or "").strip()
    low = task.lower()
    if low.startswith("search"):
        job = {"op": "search", "query": task.split(":", 1)[-1].strip() if ":" in task else task[6:].strip()}
    else:
        op = next((o for o in ("info", "audio", "video", "transcript") if low.startswith(o)), "transcript")
        target = url or next((w for w in task.split() if w.startswith(("http://", "https://"))), "")
        job = {"op": op, "url": target, "out_dir": str(_workspace(self.env) / "media"), "max_chars": MAX_TEXT}
    result = self._runner("media", job, timeout=int(self.env.get("LOKI_MEDIA_TIMEOUT", "900") or 900))
    if not result.get("ok"):
        return "error: " + str(result.get("error"))
    result.pop("ok", None)
    if "text" in result:
        head = "# %s\n" % result.get("title", "")
        return head + str(result["text"]) + ("\n[truncated]" if result.get("truncated") else "")
    return json.dumps(result, default=str)[:MAX_TEXT]


IMAGE_OPTIONS = ("width", "height", "seed", "count", "negative", "backend")


def _conductor_make_image(self, task: str, options: dict | None = None) -> dict:
    """The image specialist as data: {"ok", "file", "files", "seed", "seeds", "backend"} or
    {"ok": False, "error"}. options: width, height, seed, count (1-4), negative, backend
    (Settings > Creations passes them; the policy check is the same as the tool's)."""
    if not (task or "").strip():
        return {"ok": False, "error": "image needs task=<what to draw>"}
    capability, why = self.pick("image")
    if not capability:
        return {"ok": False, "error": "no specialist for 'image' is ready - %s" % why}
    job = {"prompt": task.strip(), "out_dir": str(_workspace(self.env) / "images"),
           "backend": str(self.env.get("LOKI_IMAGE_BACKEND", "auto"))}
    for key, value in (options or {}).items():
        if key in IMAGE_OPTIONS and value not in (None, ""):
            job[key] = value
    timeout = int(self.env.get("LOKI_IMAGE_TIMEOUT", "900") or 900) * max(1, min(int(job.get("count") or 1), 4))
    return self._runner("imagegen", job, timeout=timeout)


def _conductor_image(self, task: str) -> str:
    if not (task or "").strip():
        return "error: image needs task=<what to draw>"
    job = {"prompt": task.strip(), "out_dir": str(_workspace(self.env) / "images"),
           "backend": str(self.env.get("LOKI_IMAGE_BACKEND", "auto"))}
    result = self._runner("imagegen", job, timeout=int(self.env.get("LOKI_IMAGE_TIMEOUT", "900") or 900))
    if not result.get("ok"):
        return "error: " + str(result.get("error"))
    return "made %s with %s%s" % (result.get("file"), result.get("backend"),
                                  (" (%s)" % result["note"]) if result.get("note") else "")


def _conductor_reach(self, task: str, url: str) -> str:
    task = (task or "").strip()
    low = task.lower()
    if low.startswith("doctor") or (not task and not url):
        job = {"op": "doctor"}
    elif low.startswith("github"):
        rest = task.split(":", 1)[-1].strip() if ":" in task else task[6:].strip()
        job = {"op": "github", "query": rest, "url": url or (rest if rest.startswith("http") else "")}
    else:
        target = url or next((w for w in task.split() if w.startswith(("http://", "https://"))), "")
        if "youtube.com" in target or "youtu.be" in target:
            return self.media("transcript", target) if self._ready("media").allowed else \
                "error: turn on the media capability (yt-dlp) for YouTube"
        job = {"op": "read", "url": target, "max_chars": MAX_TEXT}
    result = self._runner("reach", job, timeout=180)
    if not result.get("ok"):
        return "error: " + str(result.get("error"))
    result.pop("ok", None)
    return str(result.get("text")) if "text" in result else json.dumps(result, default=str)[:MAX_TEXT]


Conductor.media = _conductor_media
Conductor.image = _conductor_image
Conductor.make_image = _conductor_make_image
Conductor.reach = _conductor_reach


# ---------------------------------------------------------------- track (vision-track)
VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv")
_TRACK_FILLER = {"track", "tracking", "follow", "count", "the", "a", "an", "all", "in", "on", "of", "from",
                 "this", "that", "my", "video", "clip", "footage", "file", "please", "every", "and", "with"}


def parse_track_task(task: str, url: str = "") -> dict:
    """'track the cars in clips/a.mp4 tracker=ocsort max_frames=300' -> job fields."""
    job: dict = {"video": (url or "").strip(), "classes": [], "tracker": "bytetrack", "max_frames": 0}
    for word in (task or "").replace(",", " , ").split():
        low = word.lower().strip(".!?")
        if "=" in low:
            key, _, value = low.partition("=")
            if key in ("tracker", "model"):
                job[key] = value
            elif key in ("max_frames", "frames"):
                job["max_frames"] = int(value) if value.isdigit() else 0
            elif key in ("threshold", "confidence"):
                try:
                    job["threshold"] = float(value)
                except ValueError:
                    pass
            continue
        if low.endswith(VIDEO_EXT):
            job["video"] = job["video"] or word.strip("\"'")
            continue
        if low and low != "," and low not in _TRACK_FILLER:
            job["classes"].append(low)
    return job


def _conductor_track(self, task: str, url: str) -> str:
    job = parse_track_task(task, url)
    if not job["video"]:
        return "error: track needs url=<video file in the workspace>, e.g. url=clips/street.mp4"
    workspace = _workspace(self.env).resolve()
    candidate = (workspace / job["video"]).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        return "error: refused: %s is outside the workspace" % job["video"]
    job.update({"workspace": str(workspace), "out_dir": str(workspace / "tracks")})
    result = self._runner("track", job, timeout=int(self.env.get("LOKI_TRACK_TIMEOUT", "1800") or 1800))
    if not result.get("ok"):
        return "error: " + str(result.get("error"))
    return "%s\nAnnotated video: %s\nPer-track summary: %s and %s" % (
        result.get("summary"), result.get("video"), result.get("json"), result.get("csv"))


Conductor.track = _conductor_track


# ---------------------------------------------------------------- scrape (Scrapling)
def parse_scrape_task(task: str) -> dict:
    """'crawl max_pages=30 dynamic' -> {"crawl": True, "max_pages": 30, "dynamic": True}."""
    low = str(task or "").lower()
    pages = re.search(r"(?:max_pages|pages)\s*=\s*(\d+)", low)
    return {"crawl": bool(re.search(r"\bcrawl\b", low)), "dynamic": bool(re.search(r"\b(dynamic|javascript|js)\b", low)),
            "max_pages": int(pages.group(1)) if pages else 20}


def _conductor_scrape(self, url: str, task: str = "", crawl: bool | None = None, max_pages: int | None = None,
                      workspace: Path | None = None, dynamic: bool | None = None) -> str:
    """Scrapling when it is on and installed; otherwise one page through read_web (crawl4ai /
    a self-hosted Firecrawl / LOKI's own) with a line saying how to get Scrapling."""
    url = next((w for w in str(url or "").split() if w.startswith(("http://", "https://"))), str(url or "").strip())
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "error: scrape needs an http(s) url"
    opts = parse_scrape_task(task)
    if crawl is not None:
        opts["crawl"] = bool(crawl)
    if max_pages:
        opts["max_pages"] = int(max_pages)
    if dynamic is not None:
        opts["dynamic"] = bool(dynamic)
    opts["max_pages"] = max(1, min(int(opts["max_pages"]), 200))
    ws = Path(workspace) if workspace else _workspace(self.env)
    host = (parsed.hostname or "site").lower()
    out_dir = ws / "scraped" / re.sub(r"[^a-z0-9.-]+", "-", host)
    capability, why = self.pick("scrape")
    note = ""
    if capability:
        job = {"url": url, "crawl": opts["crawl"], "max_pages": opts["max_pages"], "dynamic": opts["dynamic"],
               "out_dir": str(out_dir), "max_chars": MAX_TEXT}
        timeout = int(self.env.get("LOKI_SCRAPE_TIMEOUT", "900" if opts["crawl"] else "180") or 180)
        result = self._runner("scrape", job, timeout=timeout)
        if result.get("ok"):
            if result.get("crawl"):
                return ("crawled %d page(s) of %s into %s%s" % (
                    result.get("pages", 0), host, result.get("out_dir"),
                    ("; index " + result["jsonl"]) if result.get("jsonl") else ""))
            return str(result.get("text", "")) + ("\n[truncated]" if result.get("truncated") else "")
        if not result.get("missing"):
            return "error: scrapling failed: " + str(result.get("error"))
        note = str(result.get("error"))
    else:
        note = why
    # Fallback: one page through the read_web specialist (never Scrapling itself here).
    fallback = ""
    for backend in [c for c in READ_BACKENDS if c != "scrapling"]:
        if self._ready(backend).allowed:
            fallback = backend
            break
    hint = "note: %s; %s" % (note or "Scrapling is not ready", SCRAPE_INSTALL)
    if opts["crawl"]:
        hint += ". Crawling needs Scrapling, so only the first page was read"
    if not fallback:
        return "error: no scraper is ready (%s). Turn on crawl4ai or firecrawl in Settings > Add-ons, or %s" % (
            note or "Scrapling is not ready", SCRAPE_INSTALL)
    text = self.read_web(fallback, url)
    if text.startswith("error:"):
        return text + "\n" + hint
    return text + "\n\n[read with %s] %s" % (fallback, hint)


Conductor.scrape = _conductor_scrape


def python_command() -> list:
    """How to start a runner: `python -I` from source, or the packaged app's own runner mode
    (a frozen build has no separate interpreter; see app/loki_app.py --run-script)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-script"]
    return [sys.executable, "-I"]


# --------------------------------------------------------------------- in-loop helpers
def compress_messages(messages: list, model: str, importer=importlib.import_module) -> tuple[list, str]:
    """Headroom (Apache-2.0): shrink the context before a model call. Any failure returns the
    messages untouched - compression is an optimisation, never a requirement."""
    try:
        headroom = importer("headroom")
        result = headroom.compress(messages, model=model)
        compressed = list(getattr(result, "messages", messages))
        if not compressed:
            return messages, ""
        saved = getattr(result, "tokens_saved", 0) or 0
        return compressed, ("headroom saved %d tokens" % saved) if saved else ""
    except Exception:  # noqa: BLE001
        return messages, ""


def skillspector_findings(folder: Path, runner=subprocess.run, which=None) -> list[tuple[str, str]]:
    """NVIDIA SkillSpector static scan (`--no-llm`). [(severity, message)]. Empty on any failure."""
    import shutil
    exe = (which or shutil.which)("skillspector")
    if not exe:
        return []
    try:
        proc = runner([exe, "scan", str(folder), "--format", "json", "--no-llm"], capture_output=True,
                      text=True, timeout=120, shell=False)
        data = json.loads(proc.stdout or "{}")
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return []
    found: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            severity = node.get("severity") or node.get("level")
            message = node.get("message") or node.get("title") or node.get("description") or node.get("rule")
            if severity and message:
                found.append((str(severity).lower(), str(message)[:200]))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(data)
    return found


def python_module_present(name: str) -> bool:
    """True when a top-level module is installed - found, not imported."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def pick_vane_models(providers: list, prefer: str = "") -> tuple[dict | None, dict | None]:
    """Choose Vane's chat and embedding models: a local (Ollama) provider first, or the one
    whose model key contains `prefer`. Returns ({providerId, key}, {providerId, key})."""
    def models(p: dict, field: str) -> list:
        items = p.get(field) or []
        return [m for m in items if isinstance(m, dict) and m.get("key")]
    ordered = sorted([p for p in providers if isinstance(p, dict) and p.get("id")],
                     key=lambda p: 0 if "ollama" in str(p.get("name", "") + p.get("type", "")).lower() else 1)
    chat = embed = None
    for p in ordered:
        chats = models(p, "chatModels")
        if prefer:
            chats = sorted(chats, key=lambda m: 0 if prefer.lower() in m["key"].lower() else 1)
        if chats and chat is None:
            chat = {"providerId": p["id"], "key": chats[0]["key"]}
        embeds = models(p, "embeddingModels")
        if embeds and embed is None:
            embed = {"providerId": p["id"], "key": embeds[0]["key"]}
    return chat, embed
