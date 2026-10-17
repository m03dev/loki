"""Capability manifests and discovery - read everything, run nothing.

Every pluggable capability (a tool, an adapter like herdr or cua, an API connector, a
memory or decision provider, a worker) is described by `capabilities/<name>/manifest.json`:

    {
      "name": "herdr", "version": "0.1.0", "kind": "adapter",
      "description": "...", "license": "MIT", "homepage": "https://herdr.dev",
      "permissions": ["process:agent"],
      "requires_cmd": ["herdr"], "requires_env": [],
      "health_endpoint": "",            # optional http(s) URL probed with a timeout
      "entrypoint": "workers.HerdrBackend"   # informational; discovery never imports it
    }

Discovery scans the repo's `capabilities/` (trusted, ships with Loki) and the user's
`harness_data/capabilities/` (untrusted). It only parses JSON. Nothing is imported or
executed, and a capability is unusable until the user enables it. Enabling records the
manifest's fingerprint and the permissions granted at that moment: if the manifest later
changes (new permission, new entrypoint) it drops back to "changed" and must be
re-approved - a capability cannot grant itself more. Rewording its description or bumping
its version does not count, and a built-in capability (shipped in the repo) stays enabled
across updates while it asks for no permission beyond what was granted.

Standard library only; pure functions plus one small JSON enablement store.
"""
from __future__ import annotations

import addons_install

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

KINDS = ("tool", "skill", "adapter", "api", "memory", "model", "decision", "worker")
REQUIRED = ("name", "version", "kind", "description")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_MANIFEST_BYTES = 64_000
# Permission vocabulary. "network:<host>" and "secret:<ENV>" are parameterised.
PERMISSIONS = {
    "network": "reach any network host",
    "network:loopback": "reach services on this computer only",
    "fs:workspace": "read and write inside the workspace",
    "fs:read": "read files inside the workspace",
    "process:agent": "start a known coding agent (Claude Code / Codex)",
    "process:spawn": "start other programs",
    "computer:virtual": "control a virtual computer (VM / container)",
    "computer:host": "control this computer's screen, mouse and keyboard",
}
HIGH_RISK = frozenset({"network", "process:spawn", "computer:host"})


def permission_ok(perm: str) -> bool:
    if perm in PERMISSIONS:
        return True
    if perm.startswith("network:"):
        return bool(re.match(r"^[a-z0-9.-]+(:\d+)?$", perm[len("network:"):]))
    if perm.startswith("secret:"):
        return bool(ENV_RE.match(perm[len("secret:"):]))
    return False


def describe_permission(perm: str) -> str:
    if perm in PERMISSIONS:
        return PERMISSIONS[perm]
    if perm.startswith("network:"):
        return "reach " + perm[len("network:"):]
    if perm.startswith("secret:"):
        return "read the secret " + perm[len("secret:"):]
    return perm


def validate(data: object) -> list[str]:
    """Readable problems with a manifest; empty when it is valid."""
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"]
    errors = ["missing %r" % key for key in REQUIRED if not str(data.get(key, "")).strip()]
    name = str(data.get("name", ""))
    if name and not NAME_RE.match(name):
        errors.append("name must be lowercase letters, digits, - or _ (max 48)")
    if data.get("kind") and data.get("kind") not in KINDS:
        errors.append("kind must be one of " + ", ".join(KINDS))
    for key in ("permissions", "requires_cmd", "requires_env", "requires_python"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            errors.append("%s must be a list of strings" % key)
    for perm in data.get("permissions", []) if isinstance(data.get("permissions"), list) else []:
        if isinstance(perm, str) and not permission_ok(perm):
            errors.append("unknown permission %r" % perm)
    for env in data.get("requires_env", []) if isinstance(data.get("requires_env"), list) else []:
        if isinstance(env, str) and not ENV_RE.match(env):
            errors.append("bad env name %r" % env)
    health = str(data.get("health_endpoint", "") or "")
    if health and urlparse(health).scheme not in ("http", "https"):
        errors.append("health_endpoint must be an http(s) URL")
    return errors


def fingerprint(data: dict) -> str:
    """Stable hash of every field (canonical JSON)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# Fields that only describe a capability. Rewording a description or bumping a version does
# not change what it may do, so it must not switch an enabled capability off.
COSMETIC = ("description", "version", "license", "homepage")


def trust_fingerprint(data: dict) -> str:
    """Hash of what matters for trust: permissions, requirements, entrypoint, endpoints, kind."""
    return fingerprint({k: v for k, v in data.items() if k not in COSMETIC})


def _still_trusted(entry: dict, record: dict) -> bool:
    """Enabled earlier, manifest edited since: does the earlier approval still cover it?"""
    manifest = entry["manifest"]
    if record.get("trust") and record["trust"] == trust_fingerprint(manifest):
        return True                       # only cosmetic fields changed
    # A capability that ships with LOKI (repo capabilities/, published through ship.py's
    # tests) stays on after an update as long as it asks for nothing beyond what was granted.
    perms = set(p for p in manifest.get("permissions", []) if isinstance(p, str))
    return entry.get("source") == "builtin" and "granted" in record and perms <= set(record["granted"])


def discover(roots: list[tuple[str, Path]]) -> list[dict]:
    """[(source, folder)] -> one entry per `<folder>/<name>/manifest.json`. Parses only."""
    found: dict[str, dict] = {}
    for source, root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/manifest.json")):
            entry = {"source": source, "path": str(path), "errors": [], "manifest": {}}
            try:
                if path.stat().st_size > MAX_MANIFEST_BYTES:
                    raise ValueError("manifest is larger than %d bytes" % MAX_MANIFEST_BYTES)
                data = json.loads(path.read_text(encoding="utf-8"))
                entry["errors"] = validate(data)
                entry["manifest"] = data if isinstance(data, dict) else {}
            except (OSError, ValueError) as exc:
                entry["errors"] = ["could not read: %s" % exc]
            name = str(entry["manifest"].get("name") or path.parent.name)
            if entry["manifest"].get("name") and name != path.parent.name:
                entry["errors"].append("folder name must match manifest name")
            entry["name"] = name
            if name in found:
                # The trusted copy wins; a user manifest cannot shadow a built-in one.
                if found[name]["source"] == "builtin":
                    continue
            found[name] = entry
    return [found[n] for n in sorted(found)]


class Enablement:
    """harness_data/capabilities_enabled.json: {name: {fingerprint, granted, at}}."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def enable(self, entry: dict) -> None:
        if entry.get("errors"):
            raise ValueError("cannot enable an invalid manifest: " + "; ".join(entry["errors"]))
        manifest = entry["manifest"]
        with self.lock:
            data = self.load()
            data[entry["name"]] = {"fingerprint": fingerprint(manifest), "trust": trust_fingerprint(manifest),
                                   "granted": list(manifest.get("permissions", [])),
                                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            self._save(data)

    def disable(self, name: str) -> None:
        # Recorded explicitly so a built-in default-on capability can be switched off too.
        with self.lock:
            data = self.load()
            data[name] = {"disabled": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            self._save(data)


def _module_present(name: str) -> bool:
    """Installed? Uses find_spec on the top-level name, which locates without importing."""
    import importlib.util
    try:
        return importlib.util.find_spec(name.split(".")[0]) is not None
    except (ImportError, ValueError):
        return False


def _which(cmd: str, which=shutil.which) -> str | None:
    """PATH, then LOKI's own venv bin: a console script pip installed for an add-on (agent-reach,
    hermes, ...) is in harness_data/.venv/bin, which is not on the app process's PATH."""
    found = which(cmd)
    if found:
        return found
    candidate = os.path.join(os.path.dirname(sys.executable), cmd)
    return candidate if os.path.exists(candidate) else None


def missing_requirements(manifest: dict, env: dict | None = None, which=shutil.which,
                         module_present=_module_present) -> list[str]:
    env = env if env is not None else os.environ
    missing = ["command `%s`" % c for c in manifest.get("requires_cmd", []) if not _which(c, which)]
    missing += ["python package `%s`" % m for m in manifest.get("requires_python", []) if not module_present(m)]
    missing += ["env %s" % e for e in manifest.get("requires_env", []) if not str(env.get(e, "")).strip()]
    return missing


def status_of(entry: dict, enabled: dict, env: dict | None = None, which=shutil.which) -> str:
    """invalid | disabled | changed | missing | enabled"""
    if entry.get("errors"):
        return "invalid"
    record = enabled.get(entry["name"])
    if record is not None and record.get("disabled"):
        return "disabled"
    builtin_default = entry.get("source") == "builtin" and entry["manifest"].get("default_enabled") is True \
        and not (set(entry["manifest"].get("permissions", [])) & HIGH_RISK)
    if record is None and not builtin_default:
        return "disabled"
    if record is not None and record.get("fingerprint") != fingerprint(entry["manifest"]) \
            and not _still_trusted(entry, record):
        return "changed"
    if missing_requirements(entry["manifest"], env, which):
        return "missing"
    return "enabled"


class Registry:
    """Discovered manifests + who is enabled. The policy engine asks this."""

    def __init__(self, roots: list[tuple[str, Path]], enablement: Enablement,
                 env: dict | None = None, which=shutil.which) -> None:
        self.roots = roots
        self.enablement = enablement
        self.env = env if env is not None else os.environ
        self.which = which

    def entries(self) -> list[dict]:
        enabled = self.enablement.load()
        out = []
        for entry in discover(self.roots):
            entry = dict(entry)
            entry["status"] = status_of(entry, enabled, self.env, self.which)
            entry["missing"] = missing_requirements(entry["manifest"], self.env, self.which) \
                if not entry["errors"] else []
            out.append(entry)
        return out

    def get(self, name: str) -> dict | None:
        for entry in self.entries():
            if entry["name"] == name:
                return entry
        return None

    def is_enabled(self, name: str) -> bool:
        entry = self.get(name)
        return bool(entry) and entry["status"] == "enabled"

    def granted(self, name: str) -> set[str]:
        entry = self.get(name)
        if not entry or entry["status"] != "enabled":
            return set()
        record = self.enablement.load().get(name)
        if record and "granted" in record:
            return set(record["granted"])
        return set(entry["manifest"].get("permissions", []))  # built-in default-on

    def set_enabled(self, name: str, on: bool) -> dict:
        entry = self.get(name)
        if entry is None:
            raise ValueError("no capability named %r" % name)
        if on:
            self.enablement.enable(entry)
        else:
            self.enablement.disable(name)
        return self.get(name) or {}

    def present(self) -> list[dict]:
        rows = []
        for entry in self.entries():
            m = entry["manifest"]
            rows.append({
                "name": entry["name"], "status": entry["status"], "source": entry["source"],
                "kind": m.get("kind", ""), "version": m.get("version", ""),
                "description": m.get("description", ""), "license": m.get("license", ""),
                "homepage": m.get("homepage", ""),
                "permissions": [{"id": p, "text": describe_permission(p), "high_risk": p in HIGH_RISK}
                                for p in m.get("permissions", []) if isinstance(p, str)],
                "missing": entry.get("missing", []), "errors": entry.get("errors", []),
                "install": addons_install.plan(entry["name"]),
            })
        return rows

    def health(self, name: str, timeout: float = 3.0, opener=urllib.request.urlopen) -> dict:
        """Probe the manifest's health_endpoint - only for an enabled capability, and only a
        non-loopback host when the capability was granted network access to it."""
        entry = self.get(name)
        if not entry or entry["status"] != "enabled":
            return {"ok": False, "detail": "not enabled"}
        url = str(entry["manifest"].get("health_endpoint", "") or "")
        if not url:
            return {"ok": None, "detail": "no health endpoint"}
        host = (urlparse(url).hostname or "").lower()
        granted = self.granted(name)
        if not is_loopback(host) and "network" not in granted and "network:" + host not in granted:
            return {"ok": False, "detail": "health endpoint host %s not granted" % host}
        try:
            with opener(url, timeout=timeout) as response:
                return {"ok": 200 <= response.status < 400, "detail": "HTTP %d" % response.status}
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"ok": False, "detail": str(exc)[:200]}


def is_loopback(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


def default_registry(repo: Path, data_dir: Path) -> Registry:
    roots = [("builtin", Path(repo) / "capabilities"), ("user", Path(data_dir) / "capabilities")]
    return Registry(roots, Enablement(Path(data_dir) / "capabilities_enabled.json"))
