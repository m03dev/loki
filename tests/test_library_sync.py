"""One library on every machine (engine/library_sync.py; owner 2026-10-27: "they dont share the same library").
Two temp workspaces, a real signed peer server in between:
  - the Mac pulls the PC's pictures, models and sidecars it lacks; big files come in chunks and arrive whole
  - nothing here is overwritten (same name = ours stays), nothing in this machine's trash comes back
  - a newer sidecar (a like) replaces the older one; times are kept, so a second round copies nothing
  - the serving side answers only for library files (no ../, no hidden files, no other folders)
  - too big / disk nearly full / off: nothing is pulled. Under a minute.

    python tests/test_library_sync.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
os.environ["LOKI_PEER_SECRET"] = "s" * 40

import library_sync  # noqa: E402
import peers  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


TMP = Path(tempfile.mkdtemp(prefix="loki-libsync-"))
PC_WS, MAC_WS = TMP / "pc", TMP / "mac"
for ws in (PC_WS, MAC_WS):
    (ws / "images" / ".meta").mkdir(parents=True)
(PC_WS / "models").mkdir()
fox = PC_WS / "images" / "fox-fire.png"
fox.write_bytes(b"\x89PNG fox with fire")
(PC_WS / "images" / ".meta" / "fox-fire.png.json").write_text(json.dumps({"prompt": "a fox wreathed in fire"}))
big = PC_WS / "models" / "forge_00001_.glb"
big.write_bytes(os.urandom(9_000_000))                     # three chunks
(PC_WS / "images" / "same-name.png").write_bytes(b"the PC's version")
(MAC_WS / "images" / "same-name.png").write_bytes(b"the Mac's version")
(PC_WS / "images" / "thrown-away.png").write_bytes(b"the owner trashed this on the Mac")
(MAC_WS / "trash" / "images").mkdir(parents=True)
(MAC_WS / "trash" / "images" / "thrown-away-1793000000.png").write_bytes(b"x")
(PC_WS / "images" / ".hidden.png").write_bytes(b"secret")
(PC_WS / "images" / ".fox-fire.png.part").write_bytes(b"half")
(PC_WS / ".env").write_text("NVIDIA_API_KEY=nvapi-xxx")

server = peers.PeerServer({"hello": lambda: {"name": "pc"},
                           "library": lambda origin, data: library_sync.serve(PC_WS, data)},
                          host="127.0.0.1", port_number=0).start()
PC = {"name": "pc", "url": "http://127.0.0.1:%d" % server.address[1]}
try:
    t0 = time.time()
    got = library_sync.pull(PC, MAC_WS, data_dir=TMP)
    check("the Mac pulls what it lacks from the PC over the signed link", got["error"] == "" and got["pulled"] == 3,
          got)
    check("... the picture and its prompt arrive", (MAC_WS / "images" / "fox-fire.png").read_bytes() == fox.read_bytes()
          and json.loads((MAC_WS / "images" / ".meta" / "fox-fire.png.json").read_text())["prompt"] == "a fox wreathed in fire")
    check("... a 9 MB model comes in chunks and arrives whole",
          (MAC_WS / "models" / "forge_00001_.glb").read_bytes() == big.read_bytes())
    check("... its time is kept (the wall sorts it where it was made)",
          abs((MAC_WS / "images" / "fox-fire.png").stat().st_mtime - fox.stat().st_mtime) < 1)
    check("a file the Mac already has under that name is never overwritten",
          (MAC_WS / "images" / "same-name.png").read_bytes() == b"the Mac's version")
    check("a file the owner put in the Mac's trash is not pulled back", not (MAC_WS / "images" / "thrown-away.png").exists())
    check("hidden files and half downloads are never shared", not (MAC_WS / "images" / ".hidden.png").exists()
          and not list((MAC_WS / "images").glob("*.part")) and not list((MAC_WS / "images").glob(".*.part")))
    check("a second round copies nothing", library_sync.pull(PC, MAC_WS, data_dir=TMP)["pulled"] == 0)

    meta = PC_WS / "images" / ".meta" / "fox-fire.png.json"
    meta.write_text(json.dumps({"prompt": "a fox wreathed in fire", "liked": True}))
    os.utime(meta, (time.time() + 30, time.time() + 30))
    again = library_sync.pull(PC, MAC_WS, data_dir=TMP)
    check("a newer sidecar (a thumbs-up on the PC) replaces the Mac's older one", again["pulled"] == 1
          and json.loads((MAC_WS / "images" / ".meta" / "fox-fire.png.json").read_text()).get("liked") is True, again)
    check("... and then nothing ping-pongs", library_sync.pull(PC, MAC_WS, data_dir=TMP)["pulled"] == 0)
    check("the last round is recorded for Settings", library_sync.status(TMP)["peers"]["pc"]["error"] == "")

    code, out = library_sync.serve(PC_WS, {"op": "list"})
    rels = [f["rel"] for f in out["files"]]
    check("the PC lists only its library files", code == 200 and "images/fox-fire.png" in rels
          and "models/forge_00001_.glb" in rels and not any(r.startswith(".") or "/." in r.split("/", 1)[1].replace("/.meta/", "/") for r in rels), rels)
    bad = [library_sync.serve(PC_WS, {"op": "read", "rel": r})[0] for r in
           ("../.env", "images/../../.env", ".env", "images/.hidden.png", "workspace/x.png", "images/.meta/../fox-fire.png",
            "images/a/b.png", "C:\\x.png", "images/.meta/fox-fire.png")]
    check("... and reads nothing outside it (../, hidden, other folders, a sidecar that is not .json)",
          all(c == 404 for c in bad), bad)

    (PC_WS / "images" / "huge.png").write_bytes(b"x" * 3000)
    os.environ["LOKI_LIBRARY_SYNC_MAX_MB"] = "0.001"
    library_sync.pull(PC, MAC_WS, data_dir=TMP)
    check("a file over LOKI_LIBRARY_SYNC_MAX_MB is skipped", not (MAC_WS / "images" / "huge.png").exists())
    os.environ.pop("LOKI_LIBRARY_SYNC_MAX_MB")
    os.environ["LOKI_LIBRARY_SYNC_MIN_FREE_GB"] = "1000000"
    full = library_sync.pull(PC, MAC_WS, data_dir=TMP)
    check("nothing is pulled while the disk is nearly full (the Mac)", not (MAC_WS / "images" / "huge.png").exists()
          and "free" in full["error"], full)
    os.environ.pop("LOKI_LIBRARY_SYNC_MIN_FREE_GB")
    os.environ["LOKI_LIBRARY_SYNC"] = "off"
    off = library_sync.pull(PC, MAC_WS, data_dir=TMP)
    check("LOKI_LIBRARY_SYNC=off: the PC shares nothing", off["pulled"] == 0 and off["error"], off)
    os.environ.pop("LOKI_LIBRARY_SYNC")
    check("the wiring: the peer server routes /peer/library and the engine starts the loop",
          '"/peer/library"' in (REPO / "engine" / "peers.py").read_text(encoding="utf-8")
          and "library_sync.run_forever" in (REPO / "engine" / "peer_link.py").read_text(encoding="utf-8"))
    # ---- deletions follow (owner 2026-10-29: "when i removed those on mac the windows should have removed")
    import creations  # noqa: E402
    D = TMP / "del"
    DPC, DMAC = D / "pc", D / "mac"
    for w in (DPC, DMAC):
        (w / "images").mkdir(parents=True)
    for n in ("a.png", "b.png", "c.png", "keep.png"):
        (DPC / "images" / n).write_bytes(b"pic " + n.encode())
        (DMAC / "images" / n).write_bytes(b"pic " + n.encode())
    (DPC / "images" / "mine.png").write_bytes(b"made on the PC")          # the Mac never had it
    (DMAC / "images" / "same.png").write_bytes(b"the Mac's own")
    (DPC / "images" / "same.png").write_bytes(b"the PC's other picture")
    srv2 = peers.PeerServer({"hello": lambda: {"name": "mac"},
                             "library": lambda origin, data: library_sync.serve(DMAC, data)},
                            host="127.0.0.1", port_number=0).start()
    MAC = {"name": "mac", "url": "http://127.0.0.1:%d" % srv2.address[1]}
    try:
        library_sync.pull(MAC, DPC, data_dir=D)                           # round 1: the PC learns the Mac's list
        creations.delete_creation(DMAC, "images/a.png")                   # LOKI's delete on the Mac
        (DMAC / "images" / "b.png").unlink()                              # removed by hand in Finder
        (DMAC / "images" / "same.png").unlink()
        r = library_sync.pull(MAC, DPC, data_dir=D)
        check("a picture trashed on the Mac goes to the PC's trash", not (DPC / "images" / "a.png").exists()
              and (DPC / "trash" / "images" / "a.png").exists(), r)
        check("a picture removed by hand on the Mac goes to the PC's trash too",
              not (DPC / "images" / "b.png").exists() and (DPC / "trash" / "images" / "b.png").exists(), r)
        check("the rest stays: untouched, the PC's own, and a different picture under the same name",
              all((DPC / "images" / n).exists() for n in ("c.png", "keep.png", "mine.png", "same.png")), r)
        # the guard: most of the Mac's pictures vanishing at once (an unplugged drive) removes nothing here
        for i in range(12):
            for w in (DPC, DMAC):
                (w / "images" / ("g%02d.png" % i)).write_bytes(b"g%d" % i)
        library_sync.pull(MAC, DPC, data_dir=D)
        for i in range(10):
            (DMAC / "images" / ("g%02d.png" % i)).unlink()
        for n in ("c.png", "keep.png"):
            (DMAC / "images" / n).unlink()
        g = library_sync.pull(MAC, DPC, data_dir=D)
        check("most of a folder vanishing at once is held back, nothing removed",
              (DPC / "images" / "g00.png").exists() and (DPC / "images" / "keep.png").exists() and "held" in g["held"], g)
        os.environ["LOKI_LIBRARY_SYNC_MAX_REMOVE"] = "1"
        held = library_sync.removals(DPC, {"files": [{"rel": "images/x.png"}], "complete": True,
                                           "trashed": [{"rel": "images/c.png", "size": 9},
                                                       {"rel": "images/keep.png", "size": 12}]}, {})
        check("the removal limit holds too", held[0] == [] and "limit 1" in held[1], held)
        os.environ.pop("LOKI_LIBRARY_SYNC_MAX_REMOVE")
    finally:
        srv2.stop()
    check("this suite stays under 60 s", time.time() - t0 < 60)
finally:
    server.stop()

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
