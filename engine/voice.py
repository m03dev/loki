"""Voice: LOKI reads text aloud into an audio file - Kokoro when installed, the OS voice otherwise.

Kokoro (hexgrad/kokoro, Apache-2.0 code and weights - see engine/licenses/Kokoro-Apache-2.0.txt) is
an 82M-parameter TTS model: near-studio quality, many times faster than real time on a GPU and
fine on a CPU or Apple Silicon. The calls are its README's: `KPipeline(lang_code=...)`,
`pipeline(text, voice=...)` yields (graphemes, phonemes, audio) chunks at 24 kHz, written with
soundfile. No Kokoro code is copied; it is used as a library when `pip install kokoro soundfile`
has been run (it also wants espeak-ng for words it does not know).

Without Kokoro LOKI still speaks, with what each OS already has - never a shell string:
  macOS    say -o out.aiff -f text.txt [-v voice]
  Windows  PowerShell + System.Speech (SpeechSynthesizer.SetOutputToWaveFile); the text and the
           path reach the script through environment variables, never inside the script
  Linux    espeak-ng (or espeak) -w out.wav -f text.txt
The runner and the Kokoro loader are injected; tests use fakes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KOKORO_VOICES = {"a": ["af_heart", "af_bella", "af_nicole", "am_michael", "am_fenrir", "am_puck"],
                 "b": ["bf_emma", "bf_isabella", "bm_george", "bm_fable"]}
DEFAULT_VOICE = "af_heart"
SAMPLE_RATE = 24000
MAX_CHARS = 20000
PS_SCRIPT = ("Add-Type -AssemblyName System.Speech; "
             "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             "if ($env:LOKI_TTS_VOICE) { try { $s.SelectVoice($env:LOKI_TTS_VOICE) } catch {} }; "
             "$s.SetOutputToWaveFile($env:LOKI_TTS_OUT); "
             "$s.Speak([IO.File]::ReadAllText($env:LOKI_TTS_IN)); $s.Dispose()")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "speech"


def _kokoro_lang(voice: str) -> str:
    return (voice or DEFAULT_VOICE)[0] if (voice or DEFAULT_VOICE)[:1] in "abefhijpz" else "a"


def load_kokoro():
    """(KPipeline, soundfile) or None when Kokoro is not installed."""
    try:
        from kokoro import KPipeline  # type: ignore  # noqa: PLC0415
        import soundfile  # type: ignore  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - not installed (or a broken install): use the OS voice
        return None
    return KPipeline, soundfile


def speak_kokoro(text: str, out: Path, voice: str, kokoro) -> Path:
    KPipeline, soundfile = kokoro
    pipeline = KPipeline(lang_code=_kokoro_lang(voice))
    chunks = []
    for _gs, _ps, audio in pipeline(text, voice=voice or DEFAULT_VOICE):
        if audio is not None:
            chunks.append(audio)
    if not chunks:
        raise RuntimeError("Kokoro produced no audio")
    try:
        import numpy  # type: ignore  # noqa: PLC0415
        data = numpy.concatenate([numpy.asarray(c) for c in chunks])
    except Exception:  # noqa: BLE001 - torch tensors / lists: write them one after another
        data = [x for c in chunks for x in list(c)]
    out = out.with_suffix(".wav")
    soundfile.write(str(out), data, SAMPLE_RATE)
    return out


def os_command(text_file: Path, out: Path, voice: str = "", platform: str = sys.platform, which=shutil.which):
    """(argv, env additions, output path) for the OS voice, or None when there is none."""
    if platform == "darwin":
        out = out.with_suffix(".aiff")
        argv = ["say", "-o", str(out), "-f", str(text_file)]
        if voice and not voice.startswith(("af_", "am_", "bf_", "bm_")):
            argv[1:1] = ["-v", voice]
        return argv, {}, out
    if platform == "win32":
        out = out.with_suffix(".wav")
        ps = which("powershell") or which("pwsh") or "powershell"
        env = {"LOKI_TTS_IN": str(text_file), "LOKI_TTS_OUT": str(out)}
        if voice and not voice.startswith(("af_", "am_", "bf_", "bm_")):
            env["LOKI_TTS_VOICE"] = voice
        return [ps, "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT], env, out
    engine = which("espeak-ng") or which("espeak")
    if not engine:
        return None
    out = out.with_suffix(".wav")
    return [engine, "-w", str(out), "-f", str(text_file)], {}, out


def speak(text: str, out_dir: Path, voice: str = "", kokoro_loader=load_kokoro, runner=subprocess.run,
          platform: str = sys.platform, which=shutil.which) -> dict:
    """Write `text` as speech into out_dir. Returns {"ok", "file", "engine"} or {"ok": False, "error"}."""
    text = " ".join(str(text or "").split())[:MAX_CHARS]
    if not text:
        return {"ok": False, "error": "give the text to speak"}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), slug(text)))
    use_kokoro = str(os.getenv("LOKI_TTS", "auto")).lower() != "os"
    kokoro = kokoro_loader() if use_kokoro else None
    if kokoro:
        try:
            path = speak_kokoro(text, out, voice or DEFAULT_VOICE, kokoro)
            return {"ok": True, "file": path, "engine": "kokoro"}
        except Exception as exc:  # noqa: BLE001 - fall through to the OS voice
            kokoro_error = str(exc)
    else:
        kokoro_error = ""
    handle, name = tempfile.mkstemp(suffix=".txt", prefix="loki-tts-")
    text_file = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
        plan = os_command(text_file, out, voice, platform, which)
        if not plan:
            return {"ok": False, "error": "no voice on this machine: pip install kokoro soundfile (best), or install "
                                          "espeak-ng" + ("; Kokoro failed: %s" % kokoro_error if kokoro_error else "")}
        argv, extra_env, path = plan
        proc = runner(argv, capture_output=True, text=True, timeout=600, env=dict(os.environ, **extra_env))
        if getattr(proc, "returncode", 1) != 0 or not Path(path).exists():
            detail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[:300]
            return {"ok": False, "error": "the %s voice failed: %s" % (Path(argv[0]).name, detail or "no audio written")}
        return {"ok": True, "file": Path(path), "engine": Path(argv[0]).stem.lower()}
    finally:
        try:
            text_file.unlink()
        except OSError:
            pass
