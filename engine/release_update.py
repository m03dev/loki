"""Updates for installed LOKI (the Windows installer and the macOS .dmg): release zips instead of git.

A git checkout (the owner's Mac and PC) keeps updating with engine/updater.py. An installed LOKI
has no git and no GitHub sign-in, so it follows a RELEASE FEED - a small JSON manifest on any
static host (GitHub Releases of a public release repo, a bucket, a file:// path for tests):

    {"version": "0.17.3", "url": "https://.../Loki-0.17.3.zip", "sha256": "<hex>", "size": 123,
     "notes": "what changed", "min_launcher": 1}

with a detached signature next to it (<feed>.sig, RSA-2048/SHA-256 by tools/loki_sign.py, checked
here in pure Python against keys/loki_public.pem - no openssl needed on the user's computer).

The same safety as the git updater (HANDOFF session 28):
  1. pre-flight: the zip is checked (sha256, signature, no path tricks), unpacked into a staging
     folder, new requirements are installed into LOKI's Python, and the NEW version's own
     `app/loki_app.py --self-test` runs there and every file index.html loads must exist. A failure
     is never applied: the version is skipped with its reason and LOKI stays on what works.
  2. trial: after the switch the version is "pending" until the window posts /ui/ready
     (mark_good). If it does not, rollback() goes back to the last good version and skips it.
  3. a history of every event, shown in Settings > Machines & updates like the git updates.

Layout (LOKI_RELEASE_ROOT, set by the launcher - packaging/installer/loki_launch.py):
    <root>/<version>/        one full LOKI tree per version (app/, engine/, ..., RELEASE.json)
    <root>/state.json        {current, last_good, pending, skip, skip_reasons, history}
    <root>/downloads/        the zips while they are checked
The launcher always starts <root>/<current>/app/loki_app.py; a switch or a rollback makes the app
exit with RELAUNCH_EXIT_CODE so the launcher starts the right tree. Old versions beyond the newest
KEEP are removed (never the current or the last good one).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RELAUNCH_EXIT_CODE = 76          # "start me again from the current version" (the launcher loops)
KEEP = 3
REPO = Path(__file__).resolve().parent.parent
PUBLIC_KEY = REPO / "keys" / "loki_public.pem"
# The repo is public (2026-10-17): releases are GitHub Releases of m03dev/loki, built and published
# by .github/workflows/installers.yml on a v* tag. "latest/download/<name>" always serves the newest
# release's file; the manifest names its zip by an absolute .../releases/download/<tag>/ URL.
DEFAULT_FEED = "https://github.com/m03dev/loki/releases/latest/download/manifest.json"
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){0,3}([.-][A-Za-z0-9]+)?$")


# ------------------------------------------------------------------ where
def root() -> Path | None:
    value = os.environ.get("LOKI_RELEASE_ROOT", "").strip()
    return Path(value).expanduser().resolve() if value else None


def enabled() -> bool:
    return root() is not None


def _state_path() -> Path:
    return (root() or Path(tempfile.gettempdir())) / "state.json"


def state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)   # atomic: a crash never leaves half a state file


def note(event: str, **info) -> None:
    data = state()
    hist = [h for h in data.get("history", []) if isinstance(h, dict)][-29:]
    hist.append(dict(info, event=event, t=time.time()))
    data["history"] = hist
    _save(data)


def release_info(tree: Path) -> dict:
    try:
        data = json.loads((tree / "RELEASE.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def current() -> str:
    return str(state().get("current", "") or "")


def current_tree() -> Path | None:
    r, cur = root(), current()
    if r is None or not cur:
        return None
    tree = r / cur
    return tree if (tree / "app" / "loki_app.py").is_file() else None


def feed_url() -> str:
    """LOKI_RELEASE_FEED, else the feed the running release was built with (RELEASE.json), else
    LOKI's public GitHub Releases (DEFAULT_FEED). LOKI_RELEASE_FEED=off turns updates off."""
    explicit = os.environ.get("LOKI_RELEASE_FEED", "").strip()
    if explicit.lower() in ("off", "0", "none", "no"):
        return ""
    if explicit:
        return explicit
    tree = current_tree()
    built = str(release_info(tree).get("feed", "")) if tree else ""
    return built or (DEFAULT_FEED if tree else "")


def vkey(version: str) -> tuple:
    parts = re.split(r"[.-]", str(version))
    return tuple(int(p) if p.isdigit() else -1 for p in parts)


# ------------------------------------------------------------------ signatures (pure Python RSA)
def _der_read(data: bytes, i: int) -> tuple:
    tag = data[i]
    length = data[i + 1]
    i += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[i:i + n], "big")
        i += n
    return tag, data[i:i + length], i + length


def public_key(pem: str) -> tuple:
    """(n, e) from a PEM RSA public key (SubjectPublicKeyInfo or PKCS#1)."""
    body = "".join(l for l in pem.strip().splitlines() if not l.startswith("-----"))
    der = base64.b64decode(body)
    _, seq, _ = _der_read(der, 0)
    tag, first, nxt = _der_read(seq, 0)
    if tag == 0x30:   # SubjectPublicKeyInfo: AlgorithmIdentifier, BIT STRING(RSAPublicKey)
        _, bits, _ = _der_read(seq, nxt)
        _, rsa, _ = _der_read(bits[1:], 0)
        _, n, j = _der_read(rsa, 0)
        _, e, _ = _der_read(rsa, j)
    else:             # PKCS#1 RSAPublicKey: INTEGER n, INTEGER e
        n = first
        _, e, _ = _der_read(seq, nxt)
    return int.from_bytes(n, "big"), int.from_bytes(e, "big")


SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def verify_signature(data: bytes, signature: bytes, pem: str) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256 (what `openssl dgst -sha256 -sign` makes)."""
    try:
        n, e = public_key(pem)
    except (ValueError, IndexError):
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    digest = hashlib.sha256(data).digest()
    want = b"\x00\x01" + b"\xff" * (k - 3 - len(SHA256_PREFIX) - len(digest)) + b"\x00" + SHA256_PREFIX + digest
    return em == want


def _require_sig() -> bool:
    return str(os.environ.get("LOKI_RELEASE_REQUIRE_SIG", "1")).strip().lower() not in ("0", "off", "false", "no")


# ------------------------------------------------------------------ fetching
def _get(url: str, timeout: float) -> bytes:
    if url.startswith("file://"):
        return Path(urllib.request.url2pathname(url[len("file://"):])).read_bytes()
    if "://" not in url:
        return Path(url).read_bytes()
    if not url.startswith("https://"):
        raise ValueError("release downloads must use https (got %s)" % url.split("://")[0])
    req = urllib.request.Request(url, headers={"User-Agent": "LOKI-release-updater"})
    # GitHub answers release downloads with a redirect (to its file host): follow https ones only
    opener = urllib.request.build_opener(_HttpsOnlyRedirects)
    with opener.open(req, timeout=timeout) as resp:   # noqa: S310 - https only, checked above and on every redirect
        return resp.read()


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, PLR0913 - urllib's signature
        if not str(newurl).startswith("https://"):
            raise urllib.error.URLError("refused a redirect away from https (%s)" % str(newurl).split("://")[0])
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _join(base: str, rel: str) -> str:
    if "://" in rel or os.path.isabs(rel):
        return rel
    return base.rsplit("/", 1)[0] + "/" + rel


def fetch_manifest(feed: str = "", timeout: float = 20.0) -> dict:
    feed = feed or feed_url()
    if not feed:
        return {"ok": False, "error": "no release feed is set (LOKI_RELEASE_FEED or RELEASE.json)"}
    try:
        raw = _get(feed, timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "could not read the release feed: %s" % exc, "problem": "release feed unreachable"}
    if _require_sig():
        try:
            sig = _get(feed + ".sig", timeout)
            pem = PUBLIC_KEY.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "the release feed has no signature (%s); not updating" % exc, "problem": "unsigned release"}
        if not verify_signature(raw, sig, pem):
            return {"ok": False, "error": "the release feed's signature does not match LOKI's key; not updating",
                    "problem": "bad signature"}
    try:
        man = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"ok": False, "error": "the release feed is not valid JSON"}
    for field in ("version", "url", "sha256"):
        if not str(man.get(field, "")).strip():
            return {"ok": False, "error": "the release feed has no %s" % field}
    if not VERSION_RE.match(str(man["version"])):
        return {"ok": False, "error": "the release feed's version %r is not a version" % man["version"]}
    man["url"] = _join(feed, str(man["url"]))
    return {"ok": True, **man}


def check(timeout: float = 20.0) -> dict:
    man = fetch_manifest(timeout=timeout)
    cur = current()
    if not man.get("ok"):
        return {"ok": False, "current": cur, "error": man.get("error", ""), "problem": man.get("problem", "update failed")}
    latest = str(man["version"])
    skipped = latest in state().get("skip", [])
    newer = vkey(latest) > vkey(cur) if cur else True
    return {"ok": True, "current": cur, "latest": latest, "behind": 1 if newer and not skipped else 0,
            "update_available": bool(newer and not skipped), "skipped": skipped, "notes": man.get("notes", ""),
            "manifest": man}


# ------------------------------------------------------------------ apply
def _safe_extract(zip_path: Path, dest: Path) -> Path:
    """Unpack, refusing absolute paths, '..', and links; returns the LOKI tree inside."""
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name.split("/")[0]:
                raise ValueError("the release zip has an unsafe path: %s" % name)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("the release zip contains a link: %s" % name)
        zf.extractall(dest)
    if (dest / "app" / "loki_app.py").is_file():
        return dest
    kids = [p for p in dest.iterdir() if p.is_dir()]
    if len(kids) == 1 and (kids[0] / "app" / "loki_app.py").is_file():
        return kids[0]
    raise ValueError("the release zip does not contain a LOKI tree (no app/loki_app.py)")


def engine_python() -> str:
    return os.environ.get("LOKI_ENGINE_PYTHON") or sys.executable


def preflight(tree: Path, timeout: float = 240.0) -> tuple:
    """(ok, why): the new version's own self-test with this machine's Python, and its window files."""
    python = engine_python()
    old = current_tree()
    for req in ("engine/requirements.txt", "app/requirements.txt"):
        new_req = tree / req
        old_req = (old / req) if old else None
        try:
            if new_req.is_file() and (old_req is None or not old_req.is_file() or new_req.read_bytes() != old_req.read_bytes()):
                subprocess.run([python, "-m", "pip", "install", "-q", "-r", str(new_req)],
                               capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.SubprocessError):
            pass
    tmp = Path(tempfile.mkdtemp(prefix="loki-release-preflight-"))
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LOKI_", "HARNESS_"))}
        env.update(LOKI_DATA=str(tmp / "data"), LOKI_WORKSPACE=str(tmp / "ws"), PYTHONDONTWRITEBYTECODE="1",
                   LOKI_TIMESFM_APPROVED="0")
        (tmp / "ws").mkdir()
        try:
            proc = subprocess.run([python, str(tree / "app" / "loki_app.py"), "--self-test"], cwd=str(tree), env=env,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "the new version's self-test did not finish in %ds" % timeout
        except OSError as exc:
            return False, "could not run the new version's self-test: %s" % exc
        text = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0 or "FAILED" in text:
            return False, "the new version failed its self-test here: " + " ".join(text.split())[-400:]
        import updater  # pylint: disable=import-outside-toplevel - the same window-file check as git updates
        missing = updater.ui_missing(tree)
        if missing:
            return False, "the new version's window would not load: missing " + ", ".join(missing[:5])
        return True, "pre-flight passed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def skip(version: str, why: str) -> None:
    data = state()
    sk = [v for v in data.get("skip", []) if v][-20:]
    if version not in sk:
        sk.append(version)
    data["skip"] = sk
    reasons = dict(data.get("skip_reasons", {}))
    reasons[version] = why[:400]
    data["skip_reasons"] = dict(list(reasons.items())[-20:])
    _save(data)


def prepare(timeout: float = 120.0, info: dict | None = None) -> dict:
    """Download, check and pre-flight a newer release WITHOUT switching to it (session 30).

    The engine's background updater calls this while LOKI runs, so the next start only switches
    (apply_ready: instant, offline) instead of downloading and pre-flighting before the window
    opens. {updated: False, ready: version | "", note, error, problem}."""
    r = root()
    if r is None:
        return {"updated": False, "ready": "", "note": "", "error": "not an installed LOKI", "problem": "not installed"}
    info = info or check(timeout=min(timeout, 30.0))
    if not info.get("ok"):
        return {"updated": False, "ready": "", "note": "", "error": info.get("error", ""), "problem": info.get("problem", "update failed")}
    if not info.get("update_available"):
        why = " (%s was skipped: %s)" % (info["latest"], state().get("skip_reasons", {}).get(info["latest"], "")) if info.get("skipped") else ""
        return {"updated": False, "ready": "", "note": "up to date (%s)%s" % (info["current"], why), "error": "", "problem": ""}
    man = info["manifest"]
    version = str(man["version"])
    final = r / version
    if state().get("ready") == version and (final / "app" / "loki_app.py").is_file():
        return {"updated": False, "ready": version, "note": "%s is downloaded and checked; LOKI uses it at the next start" % version,
                "error": "", "problem": ""}
    downloads = r / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    zpath = downloads / ("Loki-%s.zip" % version)
    staging = r / (version + ".staging")
    shutil.rmtree(staging, ignore_errors=True)

    def refuse(why: str, problem: str = "update refused") -> dict:
        skip(version, why)
        note("refused", version=version, why=why)
        shutil.rmtree(staging, ignore_errors=True)
        try:
            zpath.unlink()
        except OSError:
            pass
        return {"updated": False, "ready": "", "note": "stayed on %s: %s" % (info["current"], why), "error": why, "problem": problem}

    try:
        data = _get(str(man["url"]), timeout)
    except Exception as exc:  # noqa: BLE001 - a network problem is not the version's fault: no skip
        return {"updated": False, "ready": "", "note": "", "error": "could not download %s: %s" % (version, exc), "problem": "download failed"}
    if hashlib.sha256(data).hexdigest().lower() != str(man["sha256"]).strip().lower():
        return refuse("the download of %s does not match its checksum" % version, "bad download")
    zpath.write_bytes(data)
    try:
        tree = _safe_extract(zpath, staging)
    except (ValueError, zipfile.BadZipFile, OSError) as exc:
        return refuse(str(exc), "bad release zip")
    ok, why = preflight(tree)
    if not ok:
        return refuse(why, "new version failed its pre-flight")
    if version in (current(), state().get("last_good", "")):
        return refuse("refusing to replace the version %s this computer runs" % version)
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tree, final)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        zpath.unlink()
    except OSError:
        pass
    data_state = state()
    data_state["ready"] = version
    _save(data_state)
    note("ready", version=version)
    return {"updated": False, "ready": version, "note": "%s is downloaded and checked; LOKI uses it at the next start" % version,
            "error": "", "problem": ""}


def _switch(version: str) -> dict:
    data_state = state()
    previous = data_state.get("current", "")
    if previous and not data_state.get("pending"):
        data_state["last_good"] = previous
    data_state.update({"current": version, "pending": version, "ready": "", "updated_at": time.time()})
    _save(data_state)
    note("updated", **{"from": previous, "to": version})
    prune()
    return {"updated": True, "relaunch": True, "note": "updated %s -> %s (on trial until the window opens)" % (previous or "-", version),
            "error": "", "problem": ""}


def apply_ready() -> dict:
    """At start: switch to a version prepare() already checked - no network, no pre-flight, instant.
    {updated, relaunch, note, error, problem}; updated is False when nothing is waiting."""
    r = root()
    if r is None:
        return {"updated": False, "note": "", "error": "not an installed LOKI", "problem": "not installed"}
    data = state()
    ready = str(data.get("ready") or "")
    if not ready:
        return {"updated": False, "note": "no update waiting", "error": "", "problem": ""}
    cur = str(data.get("current") or "")
    usable = (ready not in data.get("skip", []) and (r / ready / "app" / "loki_app.py").is_file()
              and (not cur or vkey(ready) > vkey(cur)))
    if not usable:
        data["ready"] = ""
        _save(data)
        return {"updated": False, "note": "the waiting update %s is no longer usable" % ready, "error": "", "problem": ""}
    return _switch(ready)


def update(timeout: float = 120.0) -> dict:
    """Download, check and switch to a newer release now (Update everything).
    {updated, relaunch, note, error, problem}."""
    if root() is None:
        return {"updated": False, "note": "", "error": "not an installed LOKI", "problem": "not installed"}
    got = prepare(timeout=timeout)
    if not got.get("ready"):
        return {"updated": False, "note": got.get("note", ""), "error": got.get("error", ""), "problem": got.get("problem", "")}
    return _switch(got["ready"])


def on_trial() -> bool:
    data = state()
    return bool(data.get("pending") and data.get("pending") == data.get("current"))


def mark_good() -> dict:
    data = state()
    cur = data.get("current", "")
    if not cur:
        return data
    was = data.get("pending") == cur
    data.update({"last_good": cur, "pending": "", "good_at": time.time()})
    _save(data)
    if was:
        note("good", version=cur)
    return data


def rollback(why: str = "it did not start") -> dict:
    data = state()
    cur, good = data.get("current", ""), data.get("last_good", "")
    if not data.get("pending") or data.get("pending") != cur:
        return {"ok": False, "error": "the running version is not a fresh update; nothing to roll back"}
    if not good or good == cur or not (root() / good / "app" / "loki_app.py").is_file():
        return {"ok": False, "error": "no earlier good version is kept on this computer"}
    data.update({"current": good, "pending": "", "rolled_back_at": time.time(), "rolled_back_from": cur})
    _save(data)
    skip(cur, why)
    note("rolled back", **{"from": cur, "to": good, "why": why})
    return {"ok": True, "from": cur, "to": good, "relaunch": True}


def prune() -> list:
    """Keep the newest KEEP versions plus the current and last good ones."""
    r = root()
    if r is None:
        return []
    data = state()
    keep = {data.get("current", ""), data.get("last_good", "")}
    trees = sorted((p for p in r.iterdir() if p.is_dir() and VERSION_RE.match(p.name) and (p / "app").is_dir()),
                   key=lambda p: vkey(p.name), reverse=True)
    removed = []
    for p in trees[KEEP:]:
        if p.name not in keep:
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name)
    return removed


def status() -> dict:
    data = state()
    return {"enabled": True, "release": True, "branch": "release", "commit": data.get("current", ""),
            "label": "v" + data.get("current", "?"), "current": data.get("current", ""),
            "last_good": data.get("last_good", ""), "pending": data.get("pending", ""),
            "skip": data.get("skip", []), "skip_reasons": data.get("skip_reasons", {}),
            "history": data.get("history", [])[-30:], "feed": feed_url(), "ready": data.get("ready", "")}
