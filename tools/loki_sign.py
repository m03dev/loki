"""Sign and verify Loki release artifacts with the bundled public key.

Verification needs only ``keys/loki_public.pem``, which ships with the repo.
Signing needs the matching PRIVATE key, which never lives here - point
``LOKI_SIGNING_KEY`` at it (or pass --key).

    python tools/loki_sign.py fingerprint
    python tools/loki_sign.py verify <file> [<file>.sig]
    python tools/loki_sign.py verify-all <dir>
    python tools/loki_sign.py sign <file>          # needs LOKI_SIGNING_KEY

A signature is a detached RSA-2048 / SHA-256 signature (openssl dgst -sha256),
stored beside the file as ``<file>.sig``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUBLIC_KEY = REPO / "keys" / "loki_public.pem"
DEFAULT_PRIVATE_ENV = "LOKI_SIGNING_KEY"


def _openssl() -> str:
    return os.getenv("OPENSSL_EXE", "openssl")


def _run(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def fingerprint() -> str:
    """A short, pinnable fingerprint of the public key (SHA256 of its DER)."""
    if not PUBLIC_KEY.is_file():
        return "no public key at %s" % PUBLIC_KEY
    # DER is binary - capture bytes, never decode as text.
    der = subprocess.run([_openssl(), "rsa", "-pubin", "-in", str(PUBLIC_KEY),
                          "-outform", "DER"], capture_output=True).stdout
    if not der:
        return "could not read the public key (is openssl on PATH?)"
    digest = hashlib.sha256(der).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def verify(target: str, signature: str = "", pubkey: str = "") -> tuple:
    path = Path(target)
    sig = Path(signature) if signature else Path(str(path) + ".sig")
    key = Path(pubkey) if pubkey else PUBLIC_KEY
    if not key.is_file():
        return False, "public key missing: %s" % key
    if not path.is_file():
        return False, "no such file: %s" % path
    if not sig.is_file():
        return False, "no signature at %s" % sig
    result = _run([_openssl(), "dgst", "-sha256", "-verify", str(key),
                   "-signature", str(sig), str(path)])
    text = (result.stdout + result.stderr).strip()
    return (result.returncode == 0 and "Verified OK" in text), text


def sign(target: str, key: str = "") -> tuple:
    private = key or os.getenv(DEFAULT_PRIVATE_ENV, "")
    if not private:
        return False, ("signing needs the private key: set %s or pass --key "
                       "(the private key is never stored in this repo)" % DEFAULT_PRIVATE_ENV)
    if not Path(private).is_file():
        return False, "private key not found: %s" % private
    path = Path(target)
    out = Path(str(path) + ".sig")
    result = _run([_openssl(), "dgst", "-sha256", "-sign", private, "-out", str(out), str(path)])
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, str(out)


def verify_all(directory: str) -> int:
    root = Path(directory)
    signatures = sorted(root.rglob("*.sig"))
    if not signatures:
        print("no .sig files under %s" % root)
        return 1
    failures = 0
    for sig in signatures:
        target = Path(str(sig)[:-4])
        ok, message = verify(str(target), str(sig))
        print("  %s %s" % ("OK  " if ok else "FAIL", target))
        if not ok:
            failures += 1
            print("       %s" % message)
    print("%d/%d verified" % (len(signatures) - failures, len(signatures)))
    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign and verify Loki release artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fingerprint", help="print the trusted public-key fingerprint")
    v = sub.add_parser("verify", help="verify one file against a signature")
    v.add_argument("file")
    v.add_argument("sig", nargs="?", default="")
    v.add_argument("--pubkey", default="", help="verify against a different public key")
    s = sub.add_parser("sign", help="sign one file (needs the private key)")
    s.add_argument("file")
    s.add_argument("--key", default="", help="path to the private key")
    va = sub.add_parser("verify-all", help="verify every *.sig under a directory")
    va.add_argument("dir")
    args = parser.parse_args()

    if args.command == "fingerprint":
        print(fingerprint())
        return 0
    if args.command == "verify":
        ok, message = verify(args.file, args.sig, args.pubkey)
        print("%s  %s" % ("OK" if ok else "FAIL", message))
        return 0 if ok else 1
    if args.command == "sign":
        ok, message = sign(args.file, args.key)
        print("%s  %s" % ("signed ->" if ok else "FAIL", message))
        return 0 if ok else 1
    if args.command == "verify-all":
        return verify_all(args.dir)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
