"""The owner signs off (owner 2026-10-27: "i never get prompted before they make an image i should be overseeing the
prompt and the images gen like check off should come through my eyes once i should see the hands offs"). Checked here,
no model, no GPU (the makers are faked):
  - an agent's make_image / make_turnaround waits: a prompt card, nothing drawn; the same prompt twice is one card
  - the owner approves (with their own words) -> LOKI draws it and a result card comes back; send it back with a note
    -> a new prompt card with the note, nothing redrawn on its own; say no -> nothing is drawn
  - the asset pipeline: the Concept Artist's prompt waits, then runs with the owner's words; a stage that passed its
    checks waits for the owner's check-off before the next agent gets it; a retake brings the prompt back first
  - the Concept Artist proposes the next asset only when nothing is in the pipeline and nothing waits for the owner
  - a job whose picture waits is "waits for you" (owner_review.waiting_for_jobs), standing goals are off by default
  - the routes: GET /review, POST /review/decide

    python tests/test_owner_review.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]
TMP = Path(tempfile.mkdtemp(prefix="loki-review-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_OWNER_REVIEW"] = "on"
os.environ.pop("LOKI_JOB_ID", None)
import owner_review as orv  # noqa: E402
import asset_pipeline as ap  # noqa: E402
import make_mcp  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok or detail == "" else "  <- %s" % (detail,)))
    if not ok:
        FAILED.append(name)


WS = TMP / "ws"
(WS / "images").mkdir(parents=True)
drawn = []


def fake_image(args, cwd, runner=None):
    drawn.append(dict(args))
    from PIL import Image  # noqa: PLC0415
    f = Path(cwd) / "images" / ("pic%d.png" % len(drawn))
    im = Image.new("RGB", (768, 1024), (230, 230, 230))
    from PIL import ImageDraw  # noqa: PLC0415
    ImageDraw.Draw(im).ellipse((180, 200, 600, 900), fill=(40 + len(drawn) * 20, 90, 60))   # a subject, not a flat colour
    im.save(f)
    return {"ok": True, "files": [str(f.relative_to(cwd))], "backend": "fake"}


make_mcp.make_image = fake_image
try:
    # ------------------------------------------------------------------ an agent's picture waits
    os.environ["LOKI_JOB_ID"] = "job42"
    os.environ["LOKI_JOB_TITLE"] = "concept painter"
    r = make_mcp.call("make_image", {"prompt": "a red baby dragon guarding gold"}, WS)
    check("an agent's make_image is NOT drawn: it waits for the owner", not r["ok"] and r.get("waiting_for_owner")
          and orv.MARK in r["error"] and not drawn, r)
    card = orv.get(r["review"])
    check("... as a prompt card that says who asks and what", card["kind"] == "prompt" and card["status"] == "waiting"
          and card["who"] == "Agent: concept painter" and card["args"]["prompt"].startswith("a red baby dragon"), card)
    r2 = make_mcp.call("make_image", {"prompt": "A red baby  dragon guarding gold"}, WS)
    check("the same prompt again (a retried job) is the same card, not a second one", r2["review"] == r["review"]
          and len(orv.waiting()) == 1)
    check("the job that asked is known: its task waits for the owner, it is not a failure",
          [c["id"] for c in orv.waiting_for_jobs(["job42", "other"])] == [r["review"]] and not orv.waiting_for_jobs([]))
    os.environ.pop("LOKI_JOB_ID")
    os.environ.pop("LOKI_JOB_TITLE")
    check("a call LOKI makes after the owner's OK goes through", make_mcp.call("make_image", {
        "prompt": "x", orv.OWNER_OK: True}, WS)["ok"] and orv.OWNER_OK not in drawn[-1])
    drawn.clear()
    check("other tools are not gated (a 3D model of an approved picture)", "make_3d" not in orv.GATED_TOOLS
          and "make_image" in orv.GATED_TOOLS and "make_turnaround" in orv.GATED_TOOLS)

    # ------------------------------------------------------------------ the owner approves, with their own words
    ran = []
    out = orv.decide(r["review"], "approve", prompt="a red baby dragon curled on a pile of gold coins, painterly",
                     runner=ran.append)
    check("approve with edited words: the card keeps the owner's words and is handed to the drawer",
          out["ok"] and ran and ran[0]["args"]["prompt"].endswith("painterly") and ran[0]["edited_from"]
          .startswith("a red baby dragon guarding"), out)
    done = orv.draw(ran[0], call=make_mcp.call)
    check("LOKI draws it itself with the owner's words", drawn and drawn[-1]["prompt"].endswith("painterly")
          and done["status"] == "done", done)
    res = orv.get(done["result"])
    check("the picture comes back to the owner as a result card (files + what was asked)", res["kind"] == "result"
          and res["status"] == "waiting" and res["files"] and "painterly" in res["handoff"], res)
    back = orv.decide(res["id"], "retake", note="more gold, less smoke")
    newp = [c for c in orv.waiting() if c["kind"] == "prompt"]
    check("send it back with a note: a NEW prompt card with the note - nothing redrawn on its own",
          back["ok"] and len(newp) == 1 and "more gold, less smoke" in newp[0]["args"]["prompt"] and len(drawn) == 1,
          newp)
    check("a card that is decided cannot be decided twice", not orv.decide(res["id"], "approve")["ok"])
    no = orv.decide(newp[0]["id"], "reject", note="not now")
    check("say no to a prompt: nothing is drawn", no["ok"] and orv.get(newp[0]["id"])["status"] == "rejected"
          and len(drawn) == 1 and not orv.waiting())
    check("a wrong action is refused", not orv.decide(r["review"], "explode")["ok"])

    # ------------------------------------------------------------------ the asset pipeline waits for the owner
    calls = []

    def fake_call(tool, args, cwd):
        calls.append((tool, dict(args)))
        if tool == "make_image":
            return fake_image(args, cwd)
        return {"ok": False, "error": "not faked"}

    a = ap.start(WS, "a moss golem guardian, grey stone body, glowing amber eyes", "creature")
    w = ap.advance(WS, a["id"], fake_call)
    st = ap.load(WS, a["id"])["stages"]["concept"]
    pc = orv.get(w.get("review", "")) or {}
    check("the Concept Artist's prompt waits for the owner - nothing drawn", w.get("waiting_for_owner") and not calls
          and st["status"] == "owner" and pc.get("who") == "Concept Artist" and pc.get("asset") == a["id"], (w, st))
    check("... its card says what the stage delivers", "Delivers:" in pc.get("handoff", ""), pc.get("handoff"))
    check("the autopilot does not run it again while it waits", ap.next_stage(ap.load(WS, a["id"])) == "")
    orv.decide(pc["id"], "approve", prompt="a moss golem guardian, mossy boulder body, amber eyes, front view",
               ws=WS)
    check("approved: the stage is ready again", ap.load(WS, a["id"])["stages"]["concept"]["status"] == "ready")
    w = ap.advance(WS, a["id"], fake_call)
    st = ap.load(WS, a["id"])["stages"]["concept"]
    check("it runs with the owner's words, marked as approved (not gated twice)", calls
          and calls[-1][1]["prompt"].endswith("front view") and calls[-1][1].get(orv.OWNER_OK), calls[-1:])
    rc = orv.get(st.get("review", "")) or {}
    check("its checks passed -> it waits for the owner's check-off, not approved yet", st["status"] == "owner"
          and st.get("pending") == "v001" and not st.get("approved") and rc.get("kind") == "result"
          and rc.get("files") and "## Checks" in rc.get("handoff", ""), (st, rc.get("handoff", "")[:200]))
    check("the next agent (Technical Artist) does not get it yet",
          ap.load(WS, a["id"])["stages"]["turnaround"]["status"] == "waiting")
    orv.decide(rc["id"], "retake", note="the eyes should glow brighter", ws=WS)
    st = ap.load(WS, a["id"])["stages"]["concept"]
    check("sent back: the stage is reopened with the note", st["status"] == "ready" and not st.get("prompt_ok")
          and "glow brighter" in st.get("retake_note", ""), st)
    w = ap.advance(WS, a["id"], fake_call)
    pc2 = orv.get(w.get("review", "")) or {}
    check("... and its prompt comes back to the owner first, with the note", w.get("waiting_for_owner")
          and "glow brighter" in pc2.get("note", "") and pc2["id"] != pc["id"], pc2)
    orv.decide(pc2["id"], "approve", ws=WS)
    ap.advance(WS, a["id"], fake_call)
    st = ap.load(WS, a["id"])["stages"]["concept"]
    orv.decide(st["review"], "approve", ws=WS)
    asset = ap.load(WS, a["id"])
    check("the owner's check-off approves it and hands it to the Technical Artist",
          asset["stages"]["concept"]["status"] == "approved" and asset["stages"]["concept"]["approved"] == "v002"
          and asset["stages"]["turnaround"]["status"] == "ready", ap.summary(asset))
    rec = json.loads((ap.asset_dir(WS, a["id"]) / "concept" / "v002" / "record.json").read_text())
    check("the hand-off record says the owner approved it and which notes it addressed", rec.get("owner") == "approved"
          and rec.get("notes_addressed"), rec.get("notes_addressed"))
    w = ap.advance(WS, a["id"], fake_call)
    tc = orv.get(w.get("review", "")) or {}
    check("the Technical Artist's turnaround prompt waits too", w.get("waiting_for_owner")
          and tc.get("who") == "Technical Artist" and tc.get("tool") == "make_turnaround", tc)

    # ------------------------------------------------------------------ the Concept Artist proposes the next asset
    asked = []
    idea = lambda p: asked.append(p) or '{"brief": "a fox spirit with three glowing tails, full body", "kind": "creature"}'
    check("no proposal while an asset is still in the pipeline", not ap.propose(WS, idea)["ok"] and not asked)
    for d in ap.assets(WS):
        for n in ap.ORDER:
            d["stages"][n]["status"] = "approved"
        ap.save(WS, d)
    for c in orv.waiting():
        orv.decide(c["id"], "reject" if c["kind"] == "prompt" else "approve")
    made = ap.propose(WS, idea)
    check("pipeline empty and nothing waiting: the Concept Artist proposes one asset (from the owner's taste, not a "
          "repeat)", made["ok"] and "three glowing tails" in made["brief"] and asked and "red baby dragon" in asked[0]
          and "moss golem" in asked[0], made)
    before = len(calls)
    w = ap.advance(WS, made["asset"], fake_call)
    check("... and its first prompt waits for the owner (nothing drawn)", w.get("waiting_for_owner")
          and len(calls) == before, calls[before:])
    check("no second proposal while the owner has a card", not ap.propose(WS, idea)["ok"])
    check("a model that answers nonsense starts nothing", not ap.propose(TMP / "empty", lambda p: "sure!")["ok"])

    # ------------------------------------------------------------------ the autopilot's pipeline duty proposes
    import autopilot  # noqa: E402,PLC0415
    WS2 = TMP / "ws2"
    (WS2 / "images").mkdir(parents=True)
    for c in orv.waiting():
        orv.decide(c["id"], "reject" if c["kind"] == "prompt" else "approve")
    fake_agent = types.SimpleNamespace(WORKSPACE=str(WS2))
    pilot = autopilot.Autopilot.__new__(autopilot.Autopilot)
    pilot.agent, pilot.data, pilot.clock = fake_agent, {"last": {}, "log": []}, lambda: 1e9
    pilot._log = lambda duty, text, **k: pilot.data["log"].append((duty, text))
    pilot.running_work = lambda: []
    pilot._concept_ask = lambda prompt: '{"brief": "a stone lantern with a sleeping moth spirit, full view", "kind": "prop"}'
    ap_tick = ap.tick
    ap.tick = lambda ws, call=None, thread=True: ap_tick(ws, fake_call, thread=False)
    try:
        said = pilot.duty_pipeline()
    finally:
        ap.tick = ap_tick
    cards = [c for c in orv.waiting() if c["kind"] == "prompt" and "moth spirit" in c["args"].get("prompt", "")]
    check("the autopilot's pipeline duty: the Concept Artist proposes, and its prompt card is waiting (2026-10-27: a "
          "name clash broke this on the PC)", "Concept Artist proposed" in said and cards
          and cards[0]["who"] == "Concept Artist", (said, pilot.data["log"][-2:]))
    # a 3D job on the GPU must not hold the proposal back (it blocked every proposal on the PC for hours, 2026-10-27)
    for c in orv.waiting():
        orv.decide(c["id"], "reject" if c["kind"] == "prompt" else "approve")
    WS3 = TMP / "ws3"
    (WS3 / "images").mkdir(parents=True)
    pilot.agent = types.SimpleNamespace(WORKSPACE=str(WS3))
    pilot.data = {"last": {}, "log": []}
    pilot.running_work = lambda: [{"lane": "gpu", "title": "TRELLIS proof"}]
    drawn = []
    ap.tick = lambda ws, call=None, thread=True: drawn.append("tick") or ""
    try:
        said = pilot.duty_pipeline()
    finally:
        ap.tick = ap_tick
    cards = [c for c in orv.waiting() if c["kind"] == "prompt" and c.get("asset")]
    check("the GPU busy with a 3D job: the Concept Artist still proposes and its card waits; nothing runs on the GPU",
          "Concept Artist proposed" in said and len(cards) == 1 and not drawn
          and not list((WS3 / "images").glob("*.png")), (said, cards, drawn))
    import inspect  # noqa: PLC0415
    check("the proposal's model call takes the prompt (not the self-review's ask)",
          list(inspect.signature(autopilot.Autopilot._concept_ask).parameters) == ["self", "prompt"])

    # ------------------------------------------------------------------ the Prompt Expert (engine/prompt_expert.py)
    import prompt_expert  # noqa: E402,PLC0415
    for c in orv.waiting():
        orv.decide(c["id"], "reject" if c["kind"] == "prompt" else "approve")
    seen = []

    def expert(system, user):
        seen.append((system, user))
        return ('{"prompt": "A small red baby dragon curled protectively around a heap of gold coins in a dim cave, '
                'amber eyes half closed, warm torchlight from the left, painterly", "why": "added pose, light and '
                'setting"}', "fake-model")
    os.environ["LOKI_JOB_ID"] = "job77"
    r = make_mcp.call("make_image", {"prompt": "dragon with gold", "style": "game-concept"}, WS)
    os.environ.pop("LOKI_JOB_ID")
    orv.EXPERT_ASK["ask"] = expert
    started = orv.kick_expert(None, WS, thread=False)
    card = orv.get(r["review"])
    check("a new prompt card goes through the Prompt Expert first: better words on the card, the agent's own kept",
          started == 1 and card["args"]["prompt"].startswith("A small red baby dragon curled") and
          card["agent_prompt"] == "dragon with gold" and card["expert"]["status"] == "done"
          and card["expert"]["by"] == "fake-model", card)
    check("... the expert was told the rules, the owner's taste and what the picture is for",
          "Never put words in the picture" in seen[-1][0] and "red baby dragon guarding its gold" in seen[-1][1]
          and "The agent's prompt: dragon with gold" in seen[-1][1] and "style game-concept" in seen[-1][1], seen[-1][1])
    check("... and it runs once per card", orv.kick_expert(None, WS, thread=False) == 0 and len(seen) == 1)
    ran.clear()
    orv.decide(card["id"], "approve", prompt=card["args"]["prompt"], runner=ran.append)
    check("approving draws the expert's words (the owner could still edit them)",
          ran and ran[0]["args"]["prompt"].startswith("A small red baby dragon"), ran[:1])
    r2 = make_mcp.call("make_image", {"prompt": "a lantern"}, WS)
    orv.EXPERT_ASK["ask"] = lambda system, user: ("no idea", "fake")
    orv.kick_expert(None, WS, thread=False)
    c2 = orv.get(r2["review"])
    check("an expert that answers nonsense: the card keeps the agent's words and says the expert could not run",
          c2["args"]["prompt"] == "a lantern" and c2["expert"]["status"] == "failed" and "agent_prompt" not in c2, c2)
    r3 = make_mcp.call("make_image", {"prompt": "a boat"}, WS)
    orv.decide(r3["review"], "reject")
    late = orv.run_expert(r3["review"], expert, WS)
    check("the owner's decision stands if they decided while the expert was writing",
          late["status"] == "rejected" and late["args"]["prompt"] == "a boat", late)
    os.environ["LOKI_PROMPT_EXPERT"] = "off"
    r4 = make_mcp.call("make_image", {"prompt": "a cup"}, WS)
    check("LOKI_PROMPT_EXPERT=off: cards stay as the agent wrote them", orv.kick_expert(None, WS, thread=False) == 0
          and "expert" not in orv.get(r4["review"]))
    os.environ.pop("LOKI_PROMPT_EXPERT")
    orv.EXPERT_ASK["ask"] = None
    import heavy  # noqa: E402,PLC0415
    _hb = heavy.busy
    heavy.busy = lambda *a, **k: True
    tried = []
    agent = types.SimpleNamespace(MODELS={"local": types.SimpleNamespace(model="qwen3:8b")},
                                  provider_configured=lambda n: n == "local",
                                  make_client=lambda n: tried.append(n))
    try:
        prompt_expert.asker(agent)("s", "u")
        local_skipped = False
    except RuntimeError as exc:
        local_skipped = "heavy work is running" in str(exc)
    heavy.busy = _hb
    check("never loads a local model beside heavy work (the Mac crashed 2026-10-26)", local_skipped and not tried, tried)

    # ------------------------------------------------------------------ the routes
    state = types.SimpleNamespace(agent=types.SimpleNamespace(WORKSPACE=str(WS)))
    code, body = orv.route(state, "GET", "/review", {}, {})
    check("GET /review lists what waits, with a summary", code == 200 and body["on"] and body["waiting"]
          and body["summary"]["prompts"] >= 1, body["summary"])
    code, body = orv.route(state, "POST", "/review/decide", {}, {"id": "nope00", "action": "approve"})
    check("POST /review/decide refuses an unknown card", code == 400)

    # ------------------------------------------------------------------ LOKI's own agent loop (chat and its jobs)
    try:
        import loki  # noqa: PLC0415
        loki.WORKSPACE = WS
        said = loki.conductor_tool("image", "a lantern on a mossy rock, game prop")
        check("LOKI's own agent asking its image specialist waits too (no picture, a card)", orv.MARK in said
              and any(c["args"].get("prompt", "").startswith("a lantern") for c in orv.waiting()), said[:200])
    except ImportError as exc:   # the engine's dependencies are missing in a bare checkout
        print("SKIP loki: %s" % exc)

    # ------------------------------------------------------------------ off switch and the standing goals
    os.environ["LOKI_OWNER_REVIEW"] = "off"
    os.environ["LOKI_JOB_ID"] = "job43"
    check("LOKI_OWNER_REVIEW=off draws at once (the old way)", make_mcp.call("make_image", {"prompt": "y"}, WS)["ok"])
    os.environ.pop("LOKI_JOB_ID")
    src = (REPO / "engine" / "autopilot.py").read_text(encoding="utf-8")
    check("the autopilot's standing goals are off unless turned on (owner: 'pause them for now')",
          '_env_on("LOKI_AUTOPILOT_ALWAYS", "off")' in src and "waiting_for_jobs" in src)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("%d failed" % len(FAILED) if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
