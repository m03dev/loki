"""Rebuild LOKI World from game/loki-world (engine/world_build.py) - no network, no real Godot.

    python tests/test_world_build.py      (< 5 s)

A Godot download that does not match its SHA-512 keeps nothing; the web template is read out of the big pack with
Range requests (a small part of it, not the whole pack) and checked; the export runs LOKI's own Godot with a private
data folder (the owner's Godot settings are never touched), keeps big files gzipped and fails without a game pack;
the route needs confirm.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import types
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-wbuild-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
import world_build as wb  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def zip_of(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o755 << 16
            z.writestr(info, data)
    return buf.getvalue()


key = wb.platform_key()
editor_name = {"darwin": "Godot.app/Contents/MacOS/Godot", "win32": "Godot_v4.7.2-stable_win64.exe",
               "linux": "Godot_v4.7.2-stable_linux.x86_64"}[key]
editor_zip = zip_of({editor_name: b"#!fake godot"})
template = b"web template " * 1000
pack = zip_of({"templates/version.txt": b"4.7.2.stable", "templates/" + wb.WEB_TEMPLATE: template,
               "templates/big_other_platform.zip": os.urandom(8_000_000)})
served = {"bytes": 0, "ranges": 0}


class Resp(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(req, timeout=0):
    url = req.full_url
    if url.endswith(wb.TEMPLATES_TPZ):
        if req.get_method() == "HEAD":
            return Resp(b"", {"Content-Length": str(len(pack))})
        a, b = req.headers["Range"].split("=")[1].split("-")
        chunk = pack[int(a):int(b) + 1]
        served["bytes"] += len(chunk)
        served["ranges"] += 1
        return Resp(chunk)
    return Resp(editor_zip)


wb.EDITORS = dict(wb.EDITORS)
wb.EDITORS[key] = (wb.EDITORS[key][0], "0" * 128)
r = wb.install(opener=opener)
check("a Godot download that does not match its SHA-512 is refused", not r["ok"] and "SHA-512" in r["error"], r)
check("...and nothing is kept", wb.editor_binary() is None)
wb.EDITORS[key] = (wb.EDITORS[key][0], hashlib.sha512(editor_zip).hexdigest())
wb.WEB_TEMPLATE_SHA512 = "f" * 128
r = wb.install(opener=opener)
check("a web template that does not match its SHA-512 is refused", not r["ok"] and "web template" in r["error"], r)
check("...and not kept", not (wb.template_target() / wb.WEB_TEMPLATE).exists())
wb.WEB_TEMPLATE_SHA512 = hashlib.sha512(template).hexdigest()
served.update(bytes=0, ranges=0)
r = wb.install(opener=opener)
check("Godot and the web template install", r["ok"] and wb.ready(), r)
check("only part of the template pack is read (Range requests)", 0 < served["bytes"] < len(pack) * 0.8, (served, len(pack)))
check("the editor is executable", os.name == "nt" or os.access(wb.editor_binary(), os.X_OK))
env = wb.export_env()
owner = {"darwin": "HOME", "win32": "APPDATA", "linux": "XDG_DATA_HOME"}[key]
check("Godot runs with LOKI's own data folder, never the owner's", str(TMP) in env[owner], env.get(owner))

out = TMP / "out"
out.mkdir()
calls = []


def fake_run(argv, **kw):
    calls.append(argv)
    if "--export-release" in argv:
        (out / "index.html").write_text("<html>", encoding="utf-8")
        (out / "index.pck").write_bytes(b"GDPC")
        (out / "index.wasm").write_bytes(b"\0asm" + b"\0" * (wb.GZIP_ABOVE + 10))
    return types.SimpleNamespace(returncode=0, stdout="\x1b[92m[ DONE ]\x1b[0m", stderr="")


r = wb.export(run=fake_run, out=out)
check("export imports then exports the Web preset with LOKI's Godot", r["ok"] and calls[0][-1] == "--import"
      and calls[1][-2:] == ["--export-release", "Web"] and calls[1][0] == str(wb.editor_binary()), (r, calls))
check("the big engine file is kept gzipped", (out / "index.wasm.gz").is_file() and not (out / "index.wasm").exists())
check("the log has no terminal colour codes", "\x1b" not in r["log"])
(out / "index.pck").unlink()
r = wb.export(run=lambda argv, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""), out=out)
check("no game pack is a failure", not r["ok"] and "index.pck" in r["error"], r)
r = wb.export(run=lambda argv, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="boom"), out=out)
check("Godot stopping is a failure with its log", not r["ok"] and "boom" in r["log"], r)
check("rebuilding needs confirm", wb.route("POST", "/world/build", {})[0] == 400)
check("status says whether the build is out of date", "out_of_date" in wb.route("GET", "/world/build", {})[1])
src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine answers /world/build", src.count("world_build.route(") == 2)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
