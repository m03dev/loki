"""Voice input (EVOLVE E7): speech to text on this computer with Whisper - nothing leaves it.

Two local engines, whichever is installed (detect()):
  faster-whisper   pip package (Settings > Add-ons > whisper installs it). `WhisperModel(size,
                   device="auto", compute_type="int8")`, `model.transcribe(path)` -> (segments,
                   info), as its README shows. The model (LOKI_WHISPER_MODEL, default "base",
                   ~145 MB) downloads from Hugging Face on first use and is kept loaded.
                   It reads WAV, OGG/Opus (Telegram voice notes), MP3, M4A... through PyAV.
  whisper.cpp      a runner: the `whisper-cli` program (LOKI_WHISPER_CPP=<path>, or on PATH) and
                   a ggml model (LOKI_WHISPER_CPP_MODEL=<file>, or the first *.bin in
                   harness_data/models/whisper/). It reads 16 kHz WAV; anything else is converted
                   with ffmpeg first when ffmpeg is installed. Never a shell string.

Without either, the window falls back to the webview's own speech recognition when it has one
(app/ui/voice.js) and says how to install Whisper when it does not.

The window records 16 kHz mono WAV itself (WebAudio), so no codec differences between WebView2
and WKWebView reach this module. decode_wav_upload() checks what the window sends.
"""
from __future__ import annotations

import base64
import importlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

MAX_UPLOAD_BYTES = 12 * 1024 * 1024          # ~6 minutes of 16 kHz mono 16-bit WAV
DEFAULT_MODEL = "base"
INSTALL_HINT = ("Install Whisper for talking to LOKI: Settings > Add-ons > whisper (pip install "
                "faster-whisper), or whisper.cpp (set LOKI_WHISPER_CPP to whisper-cli and put a ggml "
                "model in harness_data/models/whisper/).")

_MODEL: dict = {}
_LOCK = threading.Lock()


def _data_dir() -> Path:
    explicit = os.getenv("LOKI_DATA", "").strip()
    return Path(explicit) if explicit else Path(__file__).resolve().parent.parent / "harness_data"


def _has_module(name: str, importer: Callable = importlib.util.find_spec) -> bool:
    try:
        return importer(name) is not None
    except (ImportError, ValueError):
        return False


def whisper_cpp(env: dict | None = None, which: Callable = shutil.which) -> tuple:
    """(program, model) for whisper.cpp, either "" when missing."""
    env = env if env is not None else os.environ
    program = str(env.get("LOKI_WHISPER_CPP") or "").strip()
    if program and not Path(program).is_file():
        program = which(program) or ""
    if not program:
        program = which("whisper-cli") or which("whisper-cpp") or ""
    model = str(env.get("LOKI_WHISPER_CPP_MODEL") or "").strip()
    if not model or not Path(model).is_file():
        folder = _data_dir() / "models" / "whisper"
        found = sorted(folder.glob("*.bin")) if folder.is_dir() else []
        model = str(found[0]) if found else ""
    return program, model


def detect(env: dict | None = None, which: Callable = shutil.which, importer: Callable = importlib.util.find_spec) -> dict:
    """{"engine": "faster-whisper" | "whisper.cpp" | "", "detail", "install"}."""
    env = env if env is not None else os.environ
    if str(env.get("LOKI_STT") or "").strip().lower() == "off":
        return {"engine": "", "detail": "turned off (LOKI_STT=off)", "install": ""}
    if _has_module("faster_whisper", importer):
        return {"engine": "faster-whisper", "detail": "model %s" % (env.get("LOKI_WHISPER_MODEL") or DEFAULT_MODEL),
                "install": ""}
    program, model = whisper_cpp(env, which)
    if program and model:
        return {"engine": "whisper.cpp", "detail": "%s with %s" % (Path(program).name, Path(model).name), "install": ""}
    detail = "whisper.cpp found but no ggml model in harness_data/models/whisper/" if program else "not installed"
    return {"engine": "", "detail": detail, "install": INSTALL_HINT}


def decode_wav_upload(data_url: str) -> bytes:
    """The WAV bytes from the window's `data:audio/wav;base64,...`, or ValueError."""
    text = str(data_url or "")
    if not text.startswith("data:audio/wav;base64,"):
        raise ValueError("send the recording as a WAV data URL")
    if len(text) > MAX_UPLOAD_BYTES * 4 // 3 + 64:
        raise ValueError("the recording is too long (about 6 minutes at most)")
    try:
        blob = base64.b64decode(text.split(",", 1)[1], validate=True)
    except ValueError:
        raise ValueError("that is not valid audio data") from None
    if len(blob) < 44 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("that is not a WAV recording")
    return blob


def _faster_whisper_model(size: str, loader: Callable | None = None):
    with _LOCK:
        if size not in _MODEL:
            if loader is None:
                from faster_whisper import WhisperModel  # type: ignore  # noqa: PLC0415
                loader = WhisperModel
            _MODEL.clear()
            _MODEL[size] = loader(size, device="auto", compute_type="int8")
        return _MODEL[size]


def transcribe(path: Path | str, language: str = "", env: dict | None = None, which: Callable = shutil.which,
               importer: Callable = importlib.util.find_spec, runner: Callable = subprocess.run,
               loader: Callable | None = None) -> dict:
    """Speech in an audio file -> {"ok", "text", "engine"} or {"ok": False, "error"}."""
    env = env if env is not None else os.environ
    path = Path(path)
    found = detect(env, which, importer)
    engine = found["engine"]
    if not engine:
        return {"ok": False, "error": INSTALL_HINT}
    language = "".join(ch for ch in str(language or env.get("LOKI_WHISPER_LANG") or "") if ch.isalpha())[:8]
    if engine == "faster-whisper":
        try:
            model = _faster_whisper_model(str(env.get("LOKI_WHISPER_MODEL") or DEFAULT_MODEL), loader)
            segments, _info = model.transcribe(str(path), language=language or None, vad_filter=True)
            text = " ".join(str(getattr(s, "text", "")).strip() for s in segments).strip()
        except Exception as exc:  # noqa: BLE001 - reported to the window
            return {"ok": False, "error": "Whisper failed: %s" % str(exc)[:300], "engine": engine}
        return {"ok": True, "text": text, "engine": engine}
    program, model = whisper_cpp(env, which)
    wav, temp = path, None
    try:
        if path.suffix.lower() != ".wav":
            ffmpeg = which("ffmpeg")
            if not ffmpeg:
                return {"ok": False, "error": "whisper.cpp reads WAV only; install ffmpeg for voice notes", "engine": engine}
            handle, name = tempfile.mkstemp(suffix=".wav", prefix="loki-stt-")
            os.close(handle)
            temp = wav = Path(name)
            conv = runner([ffmpeg, "-y", "-loglevel", "error", "-i", str(path), "-ar", "16000", "-ac", "1", str(wav)],
                          capture_output=True, text=True, timeout=120)
            if getattr(conv, "returncode", 1) != 0:
                return {"ok": False, "error": "ffmpeg could not read that audio", "engine": engine}
        argv = [program, "-m", model, "-f", str(wav), "-nt", "-np", "-l", language or "auto"]
        proc = runner(argv, capture_output=True, text=True, timeout=600)
        if getattr(proc, "returncode", 1) != 0:
            detail = (getattr(proc, "stderr", "") or "").strip().splitlines()[-1:] or ["no output"]
            return {"ok": False, "error": "whisper.cpp failed: %s" % detail[0][:300], "engine": engine}
        text = " ".join(line.strip() for line in (proc.stdout or "").splitlines() if line.strip())
        return {"ok": True, "text": text, "engine": engine}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": "whisper.cpp could not run: %s" % str(exc)[:200], "engine": engine}
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except OSError:
                pass


def transcribe_upload(data_url: str, language: str = "", **kwargs: Any) -> dict:
    """The window's recording (a WAV data URL) -> text. Nothing is kept on disk."""
    try:
        blob = decode_wav_upload(data_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "bad_upload": True}
    handle, name = tempfile.mkstemp(suffix=".wav", prefix="loki-mic-")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(blob)
        return transcribe(Path(name), language, **kwargs)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


# ------------------------------------------------------------------- spoken replies (voice.py)
AUDIO_TYPES = {".wav": "audio/wav", ".aiff": "audio/aiff", ".mp3": "audio/mpeg"}
MAX_SPOKEN_CHARS = 1500


def speakable(text: str) -> str:
    """A reply as it should be read aloud: no code blocks, no Markdown marks, not too long."""
    import re  # pylint: disable=import-outside-toplevel
    text = re.sub(r"```.*?```", " (code shown on screen) ", str(text or ""), flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^[#>\-*\s]+", "", text, flags=re.M)
    text = text.replace("**", "").replace("__", "")
    text = " ".join(text.split())
    if len(text) > MAX_SPOKEN_CHARS:
        cut = text[:MAX_SPOKEN_CHARS].rfind(". ")
        text = text[:cut + 1 if cut > 200 else MAX_SPOKEN_CHARS]
    return text


def tts_status() -> dict:
    import voice  # pylint: disable=import-outside-toplevel
    kokoro = _has_module("kokoro") and _has_module("soundfile")
    return {"kokoro": kokoro, "engine": "kokoro" if kokoro else "os",
            "detail": "Kokoro voice" if kokoro else "this computer's own voice (pip install kokoro soundfile for a better one)",
            "voices": voice.KOKORO_VOICES if kokoro else {}}


def speak_reply(text: str, voice_name: str = "", speaker: Callable | None = None) -> dict:
    """A reply read aloud -> {"ok", "audio": data URL, "engine"}; the file is not kept."""
    import voice  # pylint: disable=import-outside-toplevel
    words = speakable(text)
    if not words:
        return {"ok": False, "error": "nothing to say"}
    folder = Path(tempfile.mkdtemp(prefix="loki-say-"))
    try:
        result = (speaker or voice.speak)(words, folder, voice_name)
        if not result.get("ok"):
            return {"ok": False, "error": str(result.get("error", "no voice"))[:300]}
        path = Path(result["file"])
        kind = AUDIO_TYPES.get(path.suffix.lower(), "audio/wav")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"ok": True, "audio": "data:%s;base64,%s" % (kind, data), "engine": result.get("engine", "")}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def ui_route(state: Any, method: str, route: str, data: dict):
    """GET /voice, POST /voice/transcribe {audio}, POST /voice/speak {text, voice} - or None."""
    if route != "/voice" and not route.startswith("/voice/"):
        return None
    if method == "GET" and route == "/voice":
        return 200, {"ok": True, "stt": detect(), "tts": tts_status()}
    if method == "POST" and route == "/voice/transcribe":
        result = transcribe_upload(str(data.get("audio") or ""), str(data.get("language") or ""))
        return (400 if result.pop("bad_upload", False) else 200), result
    if method == "POST" and route == "/voice/speak":
        text = str(data.get("text") or "")
        if not text.strip():
            return 400, {"ok": False, "error": "give the text to speak"}
        return 200, speak_reply(text[:20000], str(data.get("voice") or "")[:40])
    return 404, {"ok": False, "error": "Unknown endpoint."}
