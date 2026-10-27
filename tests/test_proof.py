"""Proof, not claims (engine/proof.py; owner 2026-10-27: "i dont like these fake results"). On the PC the music goal
said DONE 21 times with music/ empty; the sprite goal said DONE 25 times and made one sprite. Checked here with real
and fake files, no model:
  - what a request asks to make, from its words (sprite / 3D / audio / doc, named qa files; inputs are not outputs)
  - real-file checks: a real picture vs one flat colour / a weak draft / a 4x4 dot; a GLB with a mesh vs a broken one;
    a WAV with sound vs half a second; a real write-up vs the request pasted back
  - negative invariant: a file the answer claims must exist
  - the autopilot counts an unproven "done" as a failure, with the reason, and the request is tried again

    python tests/test_proof.py
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import time
import types
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
os.environ["LOKI_AUTOPILOT"] = "on"
os.environ["LOKI_AUTOPILOT_STORAGE"] = "off"
os.environ["LOKI_MACHINE_ROLE"] = "main"
T0 = time.time()
import proof  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


WS = Path(tempfile.mkdtemp(prefix="loki-proof-"))
for d in ("images", "sprites", "models", "music", "qa", "brand"):
    (WS / d).mkdir()

# ---- what is asked
e = proof.expect("Make one 30-60 second instrumental music loop for the game (make_music; a mood not made before)")
check("a music loop asks for a sound file", e["kinds"] == ["audio"], e)
e = proof.expect("Make a 64-pixel game sprite of the main subject of the newest concept picture in images/ and note it in brand/drafts/assets.md")
check("a sprite request asks for a sprite (the picture is its input)", e["kinds"] == ["sprite"], e)
e = proof.expect("[windows] Make one textured 3D prop for the game from the best picture in images/ (make_3d)")
check("a 3D prop asks for a 3D model, not the picture it starts from", e["kinds"] == ["3d"], e)
e = proof.expect("[windows] Check two more tools on this PC and write qa/tools-check.md: (1) dcc-mcp-blender")
check("a check's proof is its named qa file", e["named"] == ["qa/tools-check.md"] and e["check_only"], e)
e = proof.expect("Build the next rows of docs/FORGE_MAYA_PARITY.md from images/x.png")
check("files a request only reads are not things to make", "docs/FORGE_MAYA_PARITY.md" not in e["named"] and "images/x.png" not in e["named"], e)
e = proof.expect("Write one short devlog / social post draft about what changed in LOKI since yesterday (git log, new pictures)")
check("a devlog asks for writing", e["kinds"] == ["doc"], e)
e = proof.expect("Make now: read this line aloud with the voice tool and save it")
check("read aloud asks for a sound file", e["kinds"] == ["audio"], e)

# ---- files
real = WS / "images" / "fox.png"
im = Image.new("RGB", (256, 256), (30, 30, 40)); ImageDraw.Draw(im).ellipse((40, 40, 200, 220), fill=(220, 120, 40)); im.save(real)
Image.new("RGB", (256, 256), (128, 128, 128)).save(WS / "images" / "flat.png")
Image.new("RGB", (256, 256), (10, 200, 10)).save(WS / "images" / "x-weak-draft.png")
Image.new("RGB", (4, 4), (255, 0, 0)).save(WS / "images" / "dot.png")
check("a real picture passes", proof.check_image(real) == "")
check("one flat colour is not a picture", "flat colour" in proof.check_image(WS / "images" / "flat.png"))
check("a weak draft is not a real picture", "weak draft" in proof.check_image(WS / "images" / "x-weak-draft.png"))
check("a 4x4 dot is not a picture", "too small" in proof.check_image(WS / "images" / "dot.png"))
sp = Image.new("RGBA", (64, 64), (0, 0, 0, 0)); ImageDraw.Draw(sp).rectangle((20, 10, 44, 58), fill=(200, 60, 40, 255), outline=(20, 15, 10, 255)); sp.save(WS / "sprites" / "knight-sprite64.png")
Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(WS / "sprites" / "empty-sprite64.png")
check("a real sprite passes", proof.check_image(WS / "sprites" / "knight-sprite64.png", sprite=True) == "")
check("an empty sprite fails", proof.check_image(WS / "sprites" / "empty-sprite64.png", sprite=True) != "")


def glb(path, verts):
    doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}] if verts else [],
           "accessors": [{"count": verts, "type": "VEC3", "componentType": 5126}] if verts else []}
    js = json.dumps(doc).encode(); js += b" " * ((4 - len(js) % 4) % 4)
    body = struct.pack("<I", len(js)) + b"JSON" + js
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)


glb(WS / "models" / "prop.glb", 480)
glb(WS / "models" / "empty.glb", 0)
(WS / "models" / "broken.glb").write_bytes(b"not a model at all")
check("a GLB with a mesh passes", proof.check_model(WS / "models" / "prop.glb") == "")
check("a GLB with no mesh fails", "no mesh" in proof.check_model(WS / "models" / "empty.glb"))
check("a broken GLB fails", "not a valid glTF" in proof.check_model(WS / "models" / "broken.glb"))


def wav(path, secs):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\x01\x00" * int(22050 * secs))


wav(WS / "music" / "loop.wav", 30)
wav(WS / "music" / "blip.wav", 0.5)
check("30 s of sound passes", proof.check_audio(WS / "music" / "loop.wav") == "")
check("half a second fails", "only 0.5 s" in proof.check_audio(WS / "music" / "blip.wav"))
req = "Write one short devlog / social post draft about what changed in LOKI since yesterday"
(WS / "brand" / "devlog.md").write_text("# Devlog\n\n" + "LOKI's Home now fits a vertical screen, chats run side by side and the PC retries failed work. " * 3, encoding="utf-8")
(WS / "brand" / "echo.md").write_text(req, encoding="utf-8")
check("a real write-up passes", proof.check_text(WS / "brand" / "devlog.md", req) == "")
check("the request pasted back fails", proof.check_text(WS / "brand" / "echo.md", req) != "")

# ---- whole tasks (what happened on the PC overnight)
music = "Make one 30-60 second instrumental music loop for the game (make_music)"
r = proof.check(music, [], "DONE: made a calm loop for the forest level.", WS)
check("'DONE' with music/ empty is not done (the PC, 21 times)", not r["ok"] and "no sound file" in " ".join(r["problems"]), r)
r = proof.check(music, ["music/loop.wav"], "DONE: music/loop.wav", WS)
check("a real 30 s loop is done", r["ok"] and r["evidence"] == ["music/loop.wav"], r)
r = proof.check(music, ["music/blip.wav"], "DONE", WS)
check("half a second of sound is not a music loop", not r["ok"] and "not real" in " ".join(r["problems"]), r)
r = proof.check("Make a 64-pixel game sprite of the newest concept", ["images/fox.png"], "DONE: sprites/fox-sprite64.png", WS)
check("it says it made a sprite that does not exist", not r["ok"] and any("does not exist" in p for p in r["problems"]), r)
r = proof.check("[windows] Check two more tools on this PC and write qa/tools-check.md", [], "DONE", WS)
check("a check without its qa file is not done", not r["ok"] and "qa/tools-check.md" in " ".join(r["problems"]), r)
(WS / "qa" / "tools-check.md").write_text("dcc-mcp-blender: 205 tools answer.\n" * 10, encoding="utf-8")
r = proof.check("[windows] Check two more tools on this PC and write qa/tools-check.md", ["qa/tools-check.md"], "DONE", WS)
check("... with it, it is", r["ok"], r)

# ---- the autopilot: an unproven done is a failure, tried again
import autopilot  # noqa: E402
import task_board  # noqa: E402
REPOD = WS / "repo"; REPOD.mkdir()
(REPOD / "LOKI_TASKS.md").write_text("## Requests\n\n- [ ] [loki] " + music + "\n", encoding="utf-8")
TEAMS, JOBS = {}, {}


class Clock:
    t = time.time()

    def __call__(self):
        return self.t


clock = Clock()


def start_team(text):
    tid = "t%d" % (len(TEAMS) + 1)
    TEAMS[tid] = {"id": tid, "status": "working", "verdict": "", "jobs": {"builder": "j" + tid}, "workspace": str(WS), "finished": 0}
    JOBS["j" + tid] = {"id": "j" + tid, "status": "working", "output": ""}
    return "started team %s (Builder)" % tid


agent = types.SimpleNamespace(TEAMS=types.SimpleNamespace(get=TEAMS.get), WORKSPACE=str(WS), DATA_DIR=str(WS / "data"))
state = types.SimpleNamespace(jobs=types.SimpleNamespace(store=types.SimpleNamespace(get=JOBS.get, all=lambda: list(JOBS.values()))),
                              last_request_at=0.0, try_busy=lambda: ["x"], release_busy=lambda h: None)
(WS / "music" / "loop.wav").unlink(); (WS / "music" / "blip.wav").unlink()
auto = autopilot.Autopilot(data_dir=WS / "data", repo=REPOD, clock=clock, agent=agent, state=state, start_team=start_team)
auto.duty_inbox()
key = next(iter(auto.data["started"]))
clock.t += 120
TEAMS["t1"].update(status="done", verdict="finished", finished=clock.t)
JOBS["jt1"].update(status="done", output="DONE: a calm forest loop is ready.")
auto.settle()
row = {r["id"]: r for r in auto.board()["rows"]}[key]
check("the autopilot does not believe a team that made nothing", row["status"] == "retrying" and "Said it was done" in row["summary"], row)
check("... and says what is missing", "no sound file" in row["why"], row["why"])
check("... so the next try is told", "no sound file" in task_board.retry_text(music, auto.data["attempts"], key))
check("this suite stays under 60 s", time.time() - T0 < 60, round(time.time() - T0, 1))
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
