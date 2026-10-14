"""Video and audio with yt-dlp. stdin/stdout JSON, like every runner.

    {"op": "info" | "transcript" | "search" | "audio" | "video", "url": "...", "query": "...",
     "out_dir": "<workspace>/media", "lang": "en", "max_chars": 20000}

yt-dlp (github.com/yt-dlp/yt-dlp, Unlicense). YouTube needs a JavaScript runtime since
yt-dlp 2025.11: Deno is used when present, otherwise Node (which LOKI already uses for
Laya). Merging video+audio and converting audio need ffmpeg; without it LOKI downloads a
single-file format instead. Only download what the user has the right to use.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


def _opts(extra=None):
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "socket_timeout": 30}
    if not shutil.which("deno") and shutil.which("node"):
        opts["js_runtimes"] = {"node": {}}
    opts.update(extra or {})
    return opts


def _vtt_to_text(raw):
    lines, last = [], ""
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit() or line.startswith(("Kind:", "Language:", "NOTE")):
            stamp = re.match(r"^(\d\d:\d\d:\d\d)", line)
            if stamp:
                lines.append("[%s]" % stamp.group(1))
            continue
        text = re.sub(r"<[^>]+>", "", line)
        if text and text != last:
            lines.append(text)
            last = text
    out, pending = [], ""
    for item in lines:                       # keep one timestamp per paragraph
        if item.startswith("["):
            pending = item
        else:
            out.append((pending + " " if pending else "") + item)
            pending = ""
    return "\n".join(out)


def info(url):
    from yt_dlp import YoutubeDL
    with YoutubeDL(_opts({"skip_download": True})) as ydl:
        data = ydl.extract_info(url, download=False)
    keep = ("title", "uploader", "channel", "duration", "upload_date", "view_count", "webpage_url",
            "description", "tags")
    result = {k: data.get(k) for k in keep if data.get(k) is not None}
    if isinstance(result.get("description"), str):
        result["description"] = result["description"][:3000]
    chapters = data.get("chapters") or []
    if chapters:
        result["chapters"] = [{"start": int(c.get("start_time", 0)), "title": c.get("title", "")} for c in chapters[:60]]
    result["has_subtitles"] = sorted(set(list((data.get("subtitles") or {}).keys())[:10]))
    return result


def transcript(url, lang="en", limit=20000):
    from yt_dlp import YoutubeDL
    with tempfile.TemporaryDirectory(prefix="loki-subs-") as tmp:
        opts = _opts({"skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
                      "subtitleslangs": [lang + ".*", lang], "subtitlesformat": "vtt",
                      "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s")})
        with YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=True)
        files = sorted(Path(tmp).glob("*.vtt"))
        if not files:
            return {"title": data.get("title", ""), "text": "", "note": "this video has no %s subtitles" % lang}
        text = _vtt_to_text(files[0].read_text(encoding="utf-8", errors="replace"))
    return {"title": data.get("title", ""), "url": data.get("webpage_url", url), "text": text[:limit],
            "truncated": len(text) > limit}


def search(query, count=8):
    from yt_dlp import YoutubeDL
    with YoutubeDL(_opts({"skip_download": True, "extract_flat": True})) as ydl:
        data = ydl.extract_info("ytsearch%d:%s" % (count, query), download=False)
    return {"results": [{"title": e.get("title"), "url": e.get("url") or e.get("webpage_url"),
                         "channel": e.get("channel") or e.get("uploader"), "duration": e.get("duration")}
                        for e in (data.get("entries") or [])]}


def download(url, out_dir, audio_only):
    from yt_dlp import YoutubeDL
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    has_ffmpeg = bool(shutil.which("ffmpeg"))
    if audio_only:
        extra = {"format": "bestaudio/best"}
        if has_ffmpeg:
            extra["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
    else:
        extra = {"format": "bv*+ba/b" if has_ffmpeg else "b"}
    extra["outtmpl"] = str(out / "%(title).80s [%(id)s].%(ext)s")
    with YoutubeDL(_opts(extra)) as ydl:
        data = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(data)
    if audio_only and has_ffmpeg:
        path = str(Path(path).with_suffix(".m4a"))
    return {"title": data.get("title", ""), "file": path, "ffmpeg": has_ffmpeg}


def main():
    job = json.loads(sys.stdin.read() or "{}")
    op = str(job.get("op") or "transcript")
    url = str(job.get("url") or "").strip()
    try:
        if op != "search" and not re.match(r"^https?://", url):
            raise ValueError("give a video url (http/https)")
        if op == "info":
            result = info(url)
        elif op == "transcript":
            result = transcript(url, str(job.get("lang") or "en"), int(job.get("max_chars") or 20000))
        elif op == "search":
            result = search(str(job.get("query") or url), int(job.get("count") or 8))
        elif op in ("audio", "video"):
            result = download(url, str(job.get("out_dir") or "media"), op == "audio")
        else:
            raise ValueError("op must be info, transcript, search, audio or video")
        print(json.dumps({"ok": True, **result}, default=str))
    except ImportError:
        print(json.dumps({"ok": False, "error": "yt-dlp is not installed in LOKI's environment: "
                                                 "pip install -U \"yt-dlp[default]\""}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}))


if __name__ == "__main__":
    main()
