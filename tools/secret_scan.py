"""Refuse to package anything that looks like a key, token, password or private file.

Used by tools/make_release.py before it zips a release (every build; `--friends` too), and on its own:

    python tools/secret_scan.py <dir>          # exit 1 and list the findings when something looks secret

What counts (session 30, the repo is public and friends get zips):
  * files that must never ship: .env (anything but *.env.example), harness_data/, private keys
    (*.pem/*.key holding "PRIVATE KEY"), *.p12 / *.pfx / *.keystore, id_rsa / id_ed25519, engine.token,
    the GitHub/Google token files LOKI writes (token.json, credentials.json, *.sqlite of chats)
  * text that looks like a real credential: OpenRouter / OpenAI / Anthropic / Groq / Google /
    NVIDIA / GitHub / Hugging Face / Slack / Telegram / AWS / Stripe keys, private-key blocks,
    "password = ..." with a long literal
Placeholders are fine ("sk-or-...", "<your key>", "xxxx", the docs' examples): a match must look
random (long, mixed, not a run of x/0/.). A line can opt out with "secret-scan: ok" - for
deliberately fake test keys only; every such line is printed when the scan runs with --verbose.
Standard library only.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519", "id_ecdsa", "engine.token", "token.json", "credentials.json",
                   "studio_connect.json", "loki_conversations.json", "loki_history.json", ".netrc", ".pypirc"}
FORBIDDEN_SUFFIXES = (".p12", ".pfx", ".keystore", ".jks", ".kdbx")
FORBIDDEN_DIRS = ("harness_data", ".venv", "node_modules", ".git")
TEXT_SUFFIXES_SKIP = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".woff", ".woff2", ".ttf", ".otf",
                      ".mp3", ".wav", ".ogg", ".mp4", ".webm", ".glb", ".gltf", ".bin", ".zip", ".gz", ".pdf",
                      ".pyc", ".dll", ".so", ".dylib", ".exe", ".wasm")
MAX_TEXT = 2_000_000

# (name, regex). The secret part is group "s" when present (checked for randomness).
PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    ("OpenRouter key", re.compile(r"(?P<s>sk-or-v1-[0-9a-f]{40,})")),
    ("Anthropic key", re.compile(r"(?P<s>sk-ant-[A-Za-z0-9_\-]{30,})")),
    ("OpenAI key", re.compile(r"(?<![A-Za-z0-9_\-])(?P<s>sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,}|[A-Za-z0-9]{40,}))")),
    ("Groq key", re.compile(r"(?P<s>gsk_[A-Za-z0-9]{40,})")),
    ("Google API key", re.compile(r"(?P<s>AIza[0-9A-Za-z_\-]{35})")),
    ("NVIDIA key", re.compile(r"(?P<s>nvapi-[A-Za-z0-9_\-]{40,})")),
    ("GitHub token", re.compile(r"(?P<s>(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})")),
    ("Hugging Face token", re.compile(r"(?P<s>hf_[A-Za-z0-9]{34,})")),
    ("Slack token", re.compile(r"(?P<s>xox[abposr]-[A-Za-z0-9\-]{20,})")),
    ("Telegram bot token", re.compile(r"(?P<s>\b[0-9]{8,10}:AA[A-Za-z0-9_\-]{33}\b)")),
    ("AWS access key", re.compile(r"(?P<s>\bAKIA[0-9A-Z]{16}\b)")),
    ("Stripe key", re.compile(r"(?P<s>\b[sr]k_live_[A-Za-z0-9]{20,})")),
    ("password literal", re.compile(r"(?i)\b(?:password|passwd|secret|api_key|apikey)\s*[:=]\s*[\"'](?P<s>[^\"'\s]{16,})[\"']")),
]
OPT_OUT = "secret-scan: ok"


def _entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {c: text.count(c) for c in set(text)}
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def looks_random(secret: str) -> bool:
    """A real key is long and mixed; placeholders (xxxx, 0000, ...., <...>, your_key) are not."""
    core = re.sub(r"^(sk-or-v1-|sk-ant-|sk-proj-|sk-|gsk_|nvapi-|ghp_|github_pat_|hf_|xox.-|AIza)", "", secret)
    if len(core) < 16 or re.search(r"(x{6,}|X{6,}|0{8,}|\.{3}|\*{4,}|<|>|your|example|placeholder|dummy|fake|test)", core, re.I):
        return False
    if len(set(core)) < 10:
        return False
    return _entropy(core) >= 3.3


def file_problem(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1]
    if any(p in FORBIDDEN_DIRS or p.startswith("harness_data") for p in parts[:-1]):
        return "a private folder (%s)" % next(p for p in parts[:-1] if p in FORBIDDEN_DIRS or p.startswith("harness_data"))
    if name in FORBIDDEN_NAMES or (name.endswith(".env") and not name.endswith(".env.example")) or name.startswith(".env."):
        if not name.endswith((".example", ".sample", ".template")):
            return "a private file (%s)" % name
    if name.lower().endswith(FORBIDDEN_SUFFIXES):
        return "a certificate/key store (%s)" % name
    return ""


def scan_text(text: str) -> list:
    """[(line number, what)] for every credential-looking string."""
    found = []
    for no, line in enumerate(text.splitlines(), 1):
        if OPT_OUT in line:
            continue
        for what, rx in PATTERNS:
            for m in rx.finditer(line):
                secret = m.groupdict().get("s")
                if secret is None or looks_random(secret):
                    found.append((no, what))
                    break
    return found


def scan(root: Path, files: list | None = None) -> list:
    """[{path, line, what}] for everything under `root` (or just `files`, relative paths) that must not ship."""
    root = Path(root)
    rels = files if files is not None else [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file() or p.is_symlink()]
    out = []
    for rel in rels:
        path = root / rel
        why = file_problem(rel)
        if why:
            out.append({"path": rel, "line": 0, "what": why})
            continue
        if path.is_symlink():
            out.append({"path": rel, "line": 0, "what": "a link (releases carry real files only)"})
            continue
        if rel.lower().endswith(TEXT_SUFFIXES_SKIP):
            continue
        try:
            if path.stat().st_size > MAX_TEXT:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if rel.lower().endswith((".pem", ".key")) and "PRIVATE KEY" in text:
            out.append({"path": rel, "line": 0, "what": "a private key file"})
            continue
        for no, what in scan_text(text):
            out.append({"path": rel, "line": no, "what": what})
    return out


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refuse key-like files and strings (a release must carry none).")
    ap.add_argument("root")
    ap.add_argument("--verbose", action="store_true", help="also list the lines marked '%s'" % OPT_OUT)
    args = ap.parse_args(argv)
    root = Path(args.root)
    found = scan(root)
    for f in found:
        print("%s%s: %s" % (f["path"], (":%d" % f["line"]) if f["line"] else "", f["what"]))
    if args.verbose:
        for p in sorted(root.rglob("*")):
            if p.is_file() and not p.name.lower().endswith(TEXT_SUFFIXES_SKIP):
                for no, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if OPT_OUT in line:
                        print("opted out: %s:%d" % (p.relative_to(root).as_posix(), no))
    print("secret scan: %s" % ("clean" if not found else "%d problem(s) - nothing may be packaged" % len(found)))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
