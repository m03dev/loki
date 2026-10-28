"""Tunnel link - the Mac and the PC reach each other on DIFFERENT networks, no account, no port guessing.

Owner 2026-10-27: "pc is not on the same network figure it out". The bore relay (relay_link.py) kept resetting:
it guesses fixed public ports on a free shared server, and its hop is not encrypted. This is the first choice now;
the relay stays as the fallback.

How it works:
  * publish: each machine runs `cloudflared tunnel --url http://127.0.0.1:<peer port>` (Cloudflare's free quick
    tunnel, Apache-2.0, no sign-up). Cloudflare hands back an https://<random>.trycloudflare.com address.
  * rendezvous: that address is posted to a private ntfy.sh topic (free, no account). The topic name is derived
    from the shared link secret, so only machines holding the secret know it, and every post is signed with the
    secret (HMAC), so a stranger who finds the topic cannot plant an address.
  * resolve: the other machine reads the newest correctly signed address for that name and calls it over HTTPS.
    Requests and answers are still signed end to end by peers.py, exactly as on the LAN.
The address changes when cloudflared restarts; it is re-posted on every start and every REPOST_S.

Settings (harness_data/.env):
  LOKI_TUNNEL=auto|off        auto (default): publish while the peer server listens, dial peers set to `relay`
  LOKI_TUNNEL_NTFY=https://ntfy.sh   any ntfy server
  LOKI_CLOUDFLARED=<path>     a cloudflared binary to use instead of the one LOKI downloads
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(os.getenv("LOKI_DATA_DIR") or Path(__file__).resolve().parent.parent / "harness_data")
BIN = DATA / "bin"
REPOST_S = 20 * 60          # ntfy keeps posts ~12 h; re-post well inside that
CACHE_S = 120               # how long a resolved address is trusted before looking again
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RELEASES = "https://github.com/cloudflare/cloudflared/releases/latest/download/"

STATUS: dict = {"publishing": False, "url": "", "error": "", "posted_at": 0.0, "resolved": {}}
_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_cache: dict = {}            # name -> (url, fetched_at)


def mode() -> str:
    m = (os.getenv("LOKI_TUNNEL") or "auto").strip().lower()
    return m if m in ("auto", "on", "off") else "auto"


def ntfy() -> str:
    return (os.getenv("LOKI_TUNNEL_NTFY") or "https://ntfy.sh").rstrip("/")


def topic(shared: str) -> str:
    """Unguessable without the secret; the same on both machines."""
    return "loki-" + hmac.new(shared.encode(), b"loki-tunnel-rendezvous-v1", hashlib.sha256).hexdigest()[:32]


def sign_post(shared: str, name: str, url: str, t: float) -> str:
    return hmac.new(shared.encode(), ("%s|%s|%.0f" % (name, url, t)).encode(), hashlib.sha256).hexdigest()


def make_post(shared: str, name: str, url: str, t: float | None = None) -> str:
    t = float(int(t if t is not None else time.time()))
    return json.dumps({"name": name, "url": url, "t": t, "sig": sign_post(shared, name, url, t)})


def pick(shared: str, name: str, messages: list, now: float | None = None, max_age_s: float = 13 * 3600) -> str:
    """The newest correctly signed, fresh trycloudflare address posted for `name`, or ''."""
    now = now if now is not None else time.time()
    best, best_t = "", 0.0
    for m in messages:
        try:
            d = json.loads(m) if isinstance(m, str) else m
            name_, url, t, sig = d["name"], d["url"], float(d["t"]), d["sig"]
        except (ValueError, KeyError, TypeError):
            continue
        if name_ != name or not URL_RE.fullmatch(str(url)) or now - t > max_age_s or t - now > 300:
            continue
        if not hmac.compare_digest(str(sig), sign_post(shared, name_, url, t)):
            continue          # a stranger on the topic: ignored
        if t > best_t:
            best, best_t = url, t
    return best


# ---------------------------------------------------------------- cloudflared itself

def _asset() -> str:
    sysname, arch = platform.system(), platform.machine().lower()
    if sysname == "Darwin":
        return "cloudflared-darwin-%s.tgz" % ("arm64" if arch in ("arm64", "aarch64") else "amd64")
    if sysname == "Windows":
        return "cloudflared-windows-amd64.exe"
    return "cloudflared-linux-%s" % ("arm64" if arch in ("arm64", "aarch64") else "amd64")


def binary(download: bool = True) -> str:
    """Path to cloudflared: LOKI_CLOUDFLARED, one on PATH, LOKI's own copy, or download it once (~20 MB)."""
    own = os.getenv("LOKI_CLOUDFLARED") or shutil.which("cloudflared")
    if own:
        return own
    exe = BIN / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
    if exe.is_file():
        return str(exe)
    if not download:
        return ""
    BIN.mkdir(parents=True, exist_ok=True)
    asset = _asset()
    part = BIN / (asset + ".part")
    with urllib.request.urlopen(RELEASES + asset, timeout=120) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f)
    if asset.endswith(".tgz"):
        with tarfile.open(part) as tar:
            member = next(m for m in tar.getmembers() if m.name.rsplit("/", 1)[-1] == "cloudflared")
            with tar.extractfile(member) as src, open(exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
        part.unlink()
    else:
        part.replace(exe)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(exe)


def _post(shared: str, name: str, url: str) -> None:
    req = urllib.request.Request("%s/%s" % (ntfy(), topic(shared)), data=make_post(shared, name, url).encode(),
                                 method="POST", headers={"Title": "loki-tunnel"})
    with urllib.request.urlopen(req, timeout=15):
        pass
    STATUS["posted_at"] = time.time()


def _read(shared: str) -> list:
    url = "%s/%s/json?poll=1&since=13h" % (ntfy(), topic(shared))
    with urllib.request.urlopen(url, timeout=15) as r:
        lines = r.read().decode("utf-8", "replace").splitlines()
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "message" and ev.get("message"):
            out.append(ev["message"])
    return out


def _run(local_port: int, shared: str, name: str) -> None:
    global _proc
    while mode() != "off":
        try:
            exe = binary()
            flags = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW: no terminal on the PC
            _proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:%d" % local_port],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, **flags)
            url = ""
            deadline = time.time() + 60
            for line in _proc.stderr:            # cloudflared prints the address on stderr
                m = URL_RE.search(line)
                if m:
                    url = m.group(0)
                    break
                if time.time() > deadline:
                    break
            if not url:
                raise RuntimeError("cloudflared gave no address")
            STATUS.update(publishing=True, url=url, error="")
            threading.Thread(target=lambda: [None for _ in _proc.stderr], daemon=True).start()   # keep the pipe drained
            while _proc.poll() is None and mode() != "off":
                try:
                    _post(shared, name, url)
                except Exception as exc:  # noqa: BLE001 - ntfy down: try again next round
                    STATUS["error"] = "could not post the address: %s" % exc
                for _ in range(REPOST_S):
                    if _proc.poll() is not None:
                        break
                    time.sleep(1)
            STATUS["publishing"] = False
        except Exception as exc:  # noqa: BLE001
            STATUS.update(publishing=False, error=str(exc)[:200])
        time.sleep(30)


def publish(local_port: int, shared: str, name: str) -> threading.Thread | None:
    """Start the tunnel in the background (it downloads cloudflared on first use). None when off / no secret."""
    if mode() == "off" or not shared or not name:
        return None
    t = threading.Thread(target=_run, args=(local_port, shared, name), daemon=True, name="loki-tunnel")
    t.start()
    return t


def resolve(name: str, shared: str, refresh: bool = False) -> str:
    """The other machine's current https address, or '' (then the caller falls back to the relay)."""
    if mode() == "off" or not shared:
        return ""
    with _lock:
        hit = _cache.get(name)
        if hit and not refresh and time.time() - hit[1] < CACHE_S:
            return hit[0]
    try:
        url = pick(shared, name, _read(shared))
    except Exception as exc:  # noqa: BLE001
        STATUS["error"] = "could not read addresses: %s" % exc
        url = hit[0] if hit else ""
    with _lock:
        _cache[name] = (url, time.time())
    STATUS["resolved"][name] = url
    return url


def cached(name: str, shared: str) -> str:
    """Never blocks: the last known address now, a fresh lookup in the background when it is stale."""
    if mode() == "off" or not shared:
        return ""
    hit = _cache.get(name)
    if not hit or time.time() - hit[1] >= CACHE_S:
        _cache[name] = (hit[0] if hit else "", time.time())      # one lookup at a time
        threading.Thread(target=resolve, args=(name, shared, True), daemon=True).start()
    return (hit or ("", 0))[0]


def stop() -> None:
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
    _proc = None
    STATUS["publishing"] = False


def status() -> dict:
    return {"mode": mode(), "ntfy": ntfy(), **STATUS}


if __name__ == "__main__":   # python engine/tunnel_link.py <name>: what this machine sees for that peer
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import peers  # noqa: E402
    print(resolve(sys.argv[1] if len(sys.argv) > 1 else "pc", peers.secret(), refresh=True) or "(no address posted)")
