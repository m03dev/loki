"""Type a line, get a video (engine/text_video.py, app/ui/video_cmd.js; owner 2026-10-27: "i have still to receive a
render ... a way where I can just type something and it renders a video").

Offline (ComfyUI and the PC faked): the text-to-video graph is Wan VACE with NO control passes, its three model files
are checked by ComfyUI's loader list, the seconds become Wan's 4n+1 frames; on the PC it runs ComfyUI's graph; on the
Mac it is handed to the PC ("video" offload kind) and comes back; the video lands in <workspace>/videos with its
prompt; the PC only advertises "video" when the files are on its disk (it never starts ComfyUI for a hello); a finished
Render Studio job also lands in videos/; and in the real window `/video ...` ends with a playing <video>.

    python tests/test_text_video.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path.insert(0, str(REPO / "engine"))
import comfy_jobs  # noqa: E402
import comfy_workflow  # noqa: E402
import offload  # noqa: E402
import text_video  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


wf = comfy_jobs.graph("video")
api = comfy_jobs.build("video", {"prompt": "a red fox in snow", "frames": 49, "width": 640, "height": 368, "seed": 5})
vace = next(n for n in api.values() if n["class_type"] == "WanVaceToVideo")
check("the graph is Wan VACE text-to-video: no control video, no reference image",
      "control_video" not in vace["inputs"] and "reference_image" not in vace["inputs"], vace["inputs"])
check("... the prompt, size, frames and seed reach their nodes",
      api["5"]["inputs"]["text"] == "a red fox in snow" and vace["inputs"]["length"] == 49 and vace["inputs"]["width"] == 640
      and api["12"]["inputs"]["seed"] == 5, (api["5"]["inputs"], vace["inputs"]))
files = sorted(name for _, _, _, name, _ in comfy_workflow.loaders(api))
check("... ComfyUI's model check sees all three Wan files (the GGUF loader included)", len(files) == 3
      and any(f.endswith(".gguf") for f in files), files)
check("seconds -> Wan's 4n+1 frames at 16 fps", text_video.frames_for(3) == 49 and text_video.frames_for(5) == 81
      and all((text_video.frames_for(s) - 1) % 4 == 0 for s in (1, 2, 3, 7, 8, 20)))
check("the shot words keep motion clean", text_video.full_prompt("a fox. ").startswith("a fox. single continuous shot"))

WS = Path(tempfile.mkdtemp(prefix="loki-t2v-ws-"))
calls = []


def fake_comfy(name, params, out, **k):
    calls.append(("comfy", name, params))
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "t2v_00001_.webm").write_bytes(b"\x1aE\xdf\xa3 fake webm")
    return {"ok": True, "files": [str(Path(out) / "t2v_00001_.webm")], "seconds": 1.0}


real = (comfy_jobs.run, text_video._local_ready, offload.target, offload.run)
comfy_jobs.run = fake_comfy
text_video._local_ready = lambda: (True, "")
offload.target = lambda kind, **k: None
try:
    res = text_video.make("a red fox running through snow at dusk", seconds=3, ws=WS)
    check("on the PC: ComfyUI's text-to-video graph runs", calls and calls[-1][1] == "video"
          and calls[-1][2]["frames"] == 49, calls[-1:])
    vid = WS / res.get("rel", "x")
    check("... the video lands in <workspace>/videos for Home", res.get("ok") and vid.is_file()
          and vid.parent.name == "videos" and vid.name.endswith("a-red-fox-running-through-snow.webm"), res)
    meta = json.loads((WS / "videos" / ".meta" / (vid.name + ".json")).read_text())
    check("... with its prompt and where it was made", meta["prompt"].startswith("a red fox running")
          and meta["machine"] == "here" and meta["frames"] == 49, meta)

    sent = []

    def fake_run(kind, params, inputs, dest, peer=None, **k):
        sent.append((kind, params, peer["name"]))
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "t2v.webm").write_bytes(b"from the pc")
        return {"files": [str(Path(dest) / "t2v.webm")], "peer": peer["name"]}
    offload.target = lambda kind, **k: {"name": "pc", "url": "https://x.trycloudflare.com"} if kind == "video" else None
    offload.run = fake_run
    calls.clear()
    res = text_video.make("a lighthouse in a storm 5s", seconds=5, ws=WS)
    check("on the Mac: the job goes to the PC as a 'video' job, never runs here", sent and sent[-1][0] == "video"
          and sent[-1][2] == "pc" and not calls, (sent, calls))
    check("... the PC's video comes back into the Mac's library", res.get("ok") and (WS / res["rel"]).read_bytes()
          == b"from the pc" and res["machine"] == "pc", res)
    check("only whitelisted settings can be sent for a video job", offload.KINDS["video"][0] ==
          {"prompt", "negative", "width", "height", "frames", "seed", "steps"})
finally:
    comfy_jobs.run, text_video._local_ready, offload.target, offload.run = real

started = []
import comfy_autostart  # noqa: E402
real_ensure = comfy_autostart.ensure
comfy_autostart.ensure = lambda *a, **k: started.append(1) or {"ok": True}
try:
    offload._serves({"LOKI_MACHINE_ROLE": "main"})
finally:
    comfy_autostart.ensure = real_ensure
check("advertising 'video' never starts ComfyUI (only the files on disk are looked at)", not started, started)

# a finished Render Studio job also lands in videos/
import ai_renderer  # noqa: E402
job = WS / "renderjob"
job.mkdir()
(job / "result.webm").write_bytes(b"render")


class St:
    class agent:
        WORKSPACE = str(WS)


ai_renderer._to_home(St, "abc123", job, ["result.webm", "result.png"], {"prompt": "castle at dawn", "workflow": "vace_render"})
check("a finished render is copied into videos/ so Home plays it", (WS / "videos" / "render-abc123-result.webm").is_file())


async def ui():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  (no Playwright - window check skipped)")
        return
    async with async_playwright() as p:
        exe = next((x for x in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if x and os.path.exists(x)), "")
        try:
            browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())
        except Exception as exc:  # noqa: BLE001
            print("  (no Chromium: %s)" % str(exc)[:80])
            return
        page = await browser.new_page(viewport={"width": 1200, "height": 900})
        errors, posts, polls = [], [], [0]
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            bare = r.request.url.split("8896", 1)[1].split("#")[0].split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and (UI / bare[4:]).is_file():
                ct = "text/javascript" if bare.endswith(".js") else None
                return await r.fulfill(path=str(UI / bare[4:]), **({"content_type": ct} if ct else {}))
            if bare == "/video/make":
                posts.append(json.loads(r.request.post_data or "{}"))
                return await r.fulfill(json={"ok": True, "job": {"id": "j1"}, "where": "pc", "engine": "Wan VACE"})
            if bare == "/video/jobs":
                polls[0] += 1
                job = {"id": "j1", "status": "working"} if polls[0] < 2 else \
                    {"id": "j1", "status": "done", "rel": "videos/fox.webm", "size": "640x368", "frames": 49, "machine": "pc",
                     "seconds_taken": 95}
                return await r.fulfill(json={"ok": True, "jobs": [job]})
            if bare == "/chat":
                posts.append({"chat": True})
            return await r.fulfill(json={"ok": True})
        await page.route("http://127.0.0.1:8896/**", route)
        await page.goto("http://127.0.0.1:8896/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.evaluate("send('/video a red fox running through snow 5s', {direct: true})")
        await page.wait_for_selector(".lk-video video", timeout=15000)
        got = await page.evaluate("""(() => { const v = document.querySelector('.lk-video video');
          return { src: v.getAttribute('src'), cap: document.querySelector('.lk-video-cap').textContent,
                   user: [...document.querySelectorAll('#transcript .turn.user')].pop().textContent }; })()""")
        check("window: /video goes straight to the renderer (not the chat model), with the seconds",
              posts and posts[0] == {"prompt": "a red fox running through snow", "seconds": 5}
              and not any(x.get("chat") for x in posts), posts)
        check("... and the chat ends with the video playing, saying where it was made",
              got["src"] == "/creations/videos/fox.webm" and "pc" in got["cap"] and "Home" in got["cap"], got)
        check("no script errors", not errors, errors[:3])
        await browser.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(asyncio.wait_for(ui(), 45))
    check("this suite stays under 60 s", time.time() - t0 < 60, round(time.time() - t0, 1))
    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    sys.exit(1 if FAIL else 0)
