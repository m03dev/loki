"""Session 28 creative pipelines - offline, fakes only (no download, no GPU, no model).

stable-diffusion.cpp (PC) and mflux (Mac) as local image backends, chosen per machine and
installed from Settings > Add-ons; Creations: styles, enhance, aspect, x4, make more like this,
the star, prompt on hover, delete to the trash; Wan2GP / Higgsfield video and "animate this";
music and voice on the wall; the autopilot's daily creation.

    python tests/test_creative.py
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import time
import types
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "engine" / "runners"))
TMP = Path(tempfile.mkdtemp(prefix="loki-creative-"))
DATA = TMP / "data"
WS = TMP / "ws"
WS.mkdir(parents=True, exist_ok=True)
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_WORKSPACE"] = str(WS)
for _k in ("LOKI_IMAGE_BACKEND", "LOKI_DAILY_CREATION", "LOKI_SDCPP_MODEL", "LOKI_SDCPP_TAG", "LOKI_WAN2GP_MODEL",
           "HIGGSFIELD_KEY", "HF_KEY", "HF_API_KEY", "HF_API_SECRET", "MODELSCOPE_API_KEY"):
    os.environ.pop(_k, None)

import addons_install  # noqa: E402
import autopilot  # noqa: E402
import conductor  # noqa: E402
import creations  # noqa: E402
import creative  # noqa: E402
import image_prompt  # noqa: E402
import imagegen  # noqa: E402
import manifests  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def section(title):
    print("\n" + title)


ENV = {"LOKI_DATA": str(DATA)}
PC = {"os": "win32", "apple_silicon": False, "nvidia": True, "gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8.0,
      "ram_gb": 32.0}
MAC = {"os": "darwin", "apple_silicon": True, "nvidia": False, "gpu": "", "vram_gb": 0.0, "ram_gb": 16.0}


class Proc:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


# ---------------------------------------------------------------------------- the machine
section("which machine is this: nvidia-smi on the PC, Apple Silicon on the Mac")
seen = []


def fake_smi(argv, **kw):
    seen.append(argv)
    return Proc(0, "NVIDIA GeForce RTX 3070 Ti, 8192\n")


pc = creative.machine(run=fake_smi, which=lambda c: "C:/nvidia-smi.exe" if c == "nvidia-smi" else None,
                      platform="win32", arch="AMD64", ram_gb=32)
check("the PC: an NVIDIA GPU with 8 GB", pc["nvidia"] and pc["vram_gb"] == 8.0 and "3070" in pc["gpu"], pc)
check("nvidia-smi is asked with a CSV query (no shell)", seen and seen[0][1].startswith("--query-gpu="), seen)
mac = creative.machine(run=fake_smi, which=lambda c: None, platform="darwin", arch="arm64", ram_gb=16)
check("the Mac: Apple Silicon, no NVIDIA (nvidia-smi not even looked for)", mac["apple_silicon"] and not mac["nvidia"], mac)
check("one local backend per machine: sd.cpp on the PC, mflux on the Mac",
      creative.local_image_backend(PC) == "sdcpp" and creative.local_image_backend(MAC) == "mflux")

section("models that fit: Z-Image Turbo GGUF by VRAM")
check("8 GB (the 3070 Ti) -> Q4_K", creative.pick_sdcpp_model(PC, {}) == "zimage-q4")
check("4 GB -> Q3_K, 16 GB -> Q6_K", creative.pick_sdcpp_model(dict(PC, vram_gb=4), {}) == "zimage-q3"
      and creative.pick_sdcpp_model(dict(PC, vram_gb=16), {}) == "zimage-q6")
check("LOKI_SDCPP_MODEL overrides it", creative.pick_sdcpp_model(PC, {"LOKI_SDCPP_MODEL": "zimage-q3"}) == "zimage-q3")
files = creative.model_files("zimage-q4", ENV)
check("Q4 = the GGUF + Qwen3-4B text encoder + the FLUX VAE, all from Hugging Face over https",
      [f[2].name for f in files] == ["z_image_turbo-Q4_K.gguf", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "ae.safetensors"]
      and all(f[1].startswith("https://huggingface.co/") and "/resolve/main/" in f[1] for f in files), files)
check("about 6.7 GB in all - fits the PC's disk and (with offload) its 8 GB GPU",
      6 < sum(f[3] for f in files) < 7.5, sum(f[3] for f in files))

section("the right stable-diffusion.cpp build per machine (real asset names of master-920-2f88688)")
ASSETS = ["cudart-sd-bin-win-cu12-x64.zip", "sd-master-2f88688-bin-Darwin-macOS-26.6.2-arm64.zip",
          "sd-master-2f88688-bin-Linux-Ubuntu-24.04-x86_64-rocm-7.14.0.zip",
          "sd-master-2f88688-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip", "sd-master-2f88688-bin-Linux-Ubuntu-24.04-x86_64.zip",
          "sd-master-2f88688-bin-win-cpu-x64.zip", "sd-master-2f88688-bin-win-cuda12-x64.zip",
          "sd-master-2f88688-bin-win-rocm-7.14.0-x64.zip", "sd-master-2f88688-bin-win-vulkan-x64.zip"]


def matching(info):
    import re
    return [[a for a in ASSETS if re.match(p, a)] for p in creative.sdcpp_asset_patterns(info)]


check("the PC: the CUDA 12 build + its CUDA runtime DLLs",
      matching(PC) == [["sd-master-2f88688-bin-win-cuda12-x64.zip"], ["cudart-sd-bin-win-cu12-x64.zip"]], matching(PC))
check("a Windows PC without NVIDIA: the Vulkan build",
      matching(dict(PC, nvidia=False)) == [["sd-master-2f88688-bin-win-vulkan-x64.zip"]])
check("the Mac: the arm64 Metal build", matching(MAC) == [["sd-master-2f88688-bin-Darwin-macOS-26.6.2-arm64.zip"]])
check("Linux: plain or Vulkan, never ROCm by accident",
      matching(dict(PC, os="linux", nvidia=False)) == [["sd-master-2f88688-bin-Linux-Ubuntu-24.04-x86_64.zip"]]
      and matching(dict(PC, os="linux")) == [["sd-master-2f88688-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip"]])

# ---------------------------------------------------------------------------- command lines
section("the command lines (no shell strings)")
argv = creative.sdcpp_argv("C:/sd/sd-cli.exe", "zimage-q4", "a fox", "blurry", 1344, 768, 42, Path("out.png"),
                           count=4, info=PC, env=ENV)
check("sd.cpp: Z-Image's three files, cfg 1.0, 8 steps, size, seed, output",
      argv[0] == "C:/sd/sd-cli.exe" and argv[argv.index("--diffusion-model") + 1].endswith("z_image_turbo-Q4_K.gguf")
      and argv[argv.index("--llm") + 1].endswith("Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
      and argv[argv.index("--vae") + 1].endswith("ae.safetensors") and argv[argv.index("--cfg-scale") + 1] == "1.0"
      and argv[argv.index("--steps") + 1] == "8" and argv[argv.index("-W") + 1] == "1344"
      and argv[argv.index("-H") + 1] == "768" and argv[argv.index("-s") + 1] == "42", argv)
check("8 GB: --offload-to-cpu and flash attention; a batch of 4 is -b 4; the negative is -n",
      "--offload-to-cpu" in argv and "--diffusion-fa" in argv and argv[argv.index("-b") + 1] == "4"
      and argv[argv.index("-n") + 1] == "blurry", argv)
check("16 GB GPU: no offload", "--offload-to-cpu" not in creative.sdcpp_argv("sd", "zimage-q6", "x", "", 1024, 1024, 1,
                                                                             Path("o.png"), info=dict(PC, vram_gb=16), env=ENV))
margv = creative.mflux_argv("mflux-generate-z-image-turbo", creative.MFLUX_DEFAULT, "a fox", 1024, 1024, 7, Path("o.png"),
                            low_ram=True)
check("mflux: the pre-quantized 4-bit Z-Image, 9 steps, seed, output, --low-ram on 16 GB",
      margv[:3] == ["mflux-generate-z-image-turbo", "--model", "filipstrand/Z-Image-Turbo-mflux-4bit"]
      and margv[margv.index("--steps") + 1] == "9" and margv[margv.index("--seed") + 1] == "7"
      and margv[margv.index("--output") + 1] == "o.png" and "--low-ram" in margv, margv)

# ---------------------------------------------------------------------------- installing
section("Settings > Add-ons > local-image > Install (the PC): download, unzip, models - all fakes")


def make_zip(path: Path, members: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


fetched, downloaded = [], []


def fake_fetch(url):
    fetched.append(url)
    return {"tag_name": "master-920-2f88688",
            "assets": [{"name": n, "browser_download_url": "https://github.com/x/releases/download/t/" + n} for n in ASSETS]}


def fake_download(url, target, progress=None):
    downloaded.append((url, Path(target).name))
    target = Path(target)
    if target.suffix == ".zip":
        inner = {"bin/sd-cli.exe": b"MZ"} if "cuda12" in target.name else {"cudart64_12.dll": b"MZ"}
        make_zip(target, inner)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"GGUF")
    if progress:
        progress(4, 4)
    return target


check("before: not installed, the plan says what it will download",
      not creative.local_image_status(ENV, PC)["ready"]
      and any("cuda12" in s for s in creative.install_plan("local-image", PC, ENV)["steps"])
      and any("z_image_turbo-Q4_K.gguf" in s for s in creative.install_plan("local-image", PC, ENV)["steps"]))
out = creative.install_local_image(PC, ENV, download=fake_download, fetch=fake_fetch)
check("it asks GitHub for the latest release", fetched == ["https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest"], fetched)
check("it downloads the CUDA build, the runtime and the three model files",
      [n for _u, n in downloaded] == ["sd-master-2f88688-bin-win-cuda12-x64.zip", "cudart-sd-bin-win-cu12-x64.zip",
                                      "z_image_turbo-Q4_K.gguf", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "ae.safetensors"],
      downloaded)
status = creative.local_image_status(ENV, PC)
check("after: ready, the binary found inside the zip, everything under harness_data (never the repo)",
      out["ok"] and status["ready"] and status["bin"].endswith("sd-cli.exe")
      and str(DATA) in status["bin"] and status["model"] == "zimage-q4", (out, status))
check("the CUDA runtime DLLs sit next to sd-cli.exe (Windows finds them there)",
      (Path(status["bin"]).parent / "cudart64_12.dll").is_file())
check("LOKI_SDCPP_TAG pins a release", creative.release_assets("master-1", lambda u: fetched.append(u) or
                                                                 {"tag_name": "master-1", "assets": []})[0] == "master-1"
      and fetched[-1].endswith("/releases/tags/master-1"))
evil = make_zip(TMP / "evil.zip", {"../escape.txt": b"x"})
try:
    creative.safe_extract(evil, TMP / "x")
    check("an archive that climbs out of its folder is refused", False)
except ValueError:
    check("an archive that climbs out of its folder is refused", not (TMP / "escape.txt").exists())
try:
    creative._download("http://example.com/x", TMP / "plain.bin")
    check("only https downloads", False)
except ValueError:
    check("only https downloads", True)

section("the Mac: mflux into LOKI's venv (pip, no shell)")
MAC_ENV = {"LOKI_DATA": str(TMP / "macdata")}
pip_calls = []
venv_bin = TMP / "venv" / "bin"
venv_bin.mkdir(parents=True)
(venv_bin / "python").write_text("", encoding="utf-8")


def fake_pip(argv, **kw):
    pip_calls.append(argv)
    (venv_bin / "mflux-generate-z-image-turbo").write_text("#!", encoding="utf-8")
    return Proc(0, "Successfully installed mflux-0.23.0")


mout = creative.install_local_image(MAC, MAC_ENV, run=fake_pip, python=str(venv_bin / "python"))
mstat = creative.local_image_status(MAC_ENV, MAC)
check("pip install -U mflux, then its z-image-turbo command is found in the venv",
      pip_calls[0][1:] == ["-m", "pip", "install", "--disable-pip-version-check", "-U", "mflux"]
      and mstat["ready"] and mstat["cmd"].endswith("mflux-generate-z-image-turbo"), (pip_calls, mstat))

section("installs run in the background with progress for Settings > Creations")
r = creative.start_install("local-image", env=ENV, info=PC, worker=lambda info, env: {"ok": True}, thread=False)
prog = creative.load_state(ENV)["install"]["local-image"]
check("start_install records step and result", r["ok"] and prog["done"] and prog["ok"], (r, prog))


def boom(info, env):
    raise RuntimeError("disk full")


creative.start_install("local-image", env=ENV, info=PC, worker=boom, thread=False)
prog = creative.load_state(ENV)["install"]["local-image"]
check("a failed install says why (and never raises into the bridge)", prog["done"] and not prog["ok"]
      and "disk full" in prog["error"], prog)
check("local-video on the Mac: not offered (Wan2GP is CUDA-only), with the reason",
      not creative.start_install("local-video", env=ENV, info=MAC)["ok"]
      and "NVIDIA" in creative.install_plan("local-video", MAC, ENV)["why"])
summary = creative.summary(ENV, PC)
check("the summary for the wall: machine, image/video maker, installs, daily",
      summary["image"]["ready"] and summary["machine"]["vram_gb"] == 8.0 and "local-image" in summary["install"]
      and summary["daily"] is True, summary)

section("Wan2GP install (the PC): git clone, its own venv, torch cu128, requirements")
wan_calls = []


def fake_wan_run(argv, cwd=None, **kw):
    wan_calls.append(argv)
    if "clone" in argv:
        Path(argv[-1]).mkdir(parents=True, exist_ok=True)
        (Path(argv[-1]) / "wgp.py").write_text("", encoding="utf-8")
    if argv[-2:] == ["venv", str(DATA / "tools" / "Wan2GP" / ".venv")] or "venv" in argv:
        py = DATA / "tools" / "Wan2GP" / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_text("", encoding="utf-8")
    return Proc(0)


wout = creative.install_local_video(PC, dict(ENV, LOKI_WAN2GP_PYTHON="python3.11"), run=fake_wan_run,
                                    which=lambda c: "/usr/bin/" + c)
check("clone --depth 1, venv with Python 3.11, torch from the CUDA 12.8 index, then requirements.txt",
      wan_calls[0][1:4] == ["clone", "--depth", "1"] and wan_calls[1][:3] == ["python3.11", "-m", "venv"]
      and "https://download.pytorch.org/whl/cu128" in wan_calls[2] and wan_calls[3][-2:][0] == "-r", wan_calls)
vstat = creative.video_status(ENV, PC)
check("then video is ready on the PC through Wan2GP", wout["ok"] and vstat["ready"] and vstat["backend"] == "wan2gp", vstat)

# ---------------------------------------------------------------------------- making pictures
section("a batch of 4 with sd.cpp: one run, files renamed, seeds recorded")
runs = []


def fake_sd(argv, **kw):
    runs.append(argv)
    out = Path(argv[argv.index("-o") + 1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x89PNG")
    for i in (2, 3, 4):
        out.with_name("%s_%d.png" % (out.stem, i)).write_bytes(b"\x89PNG")
    return Proc(0)


res = creative.run_local_image("a red fox in snow", "", 1024, 1024, 100, 4, WS / "images", run=fake_sd, env=ENV, info=PC)
check("4 pictures from ONE sd.cpp run", len(runs) == 1 and len(res["files"]) == 4 and all(Path(f).is_file() for f in res["files"]),
      res)
check("seeds 100..103, names LOKI's own (newest-first wall reads them)", res["seeds"] == [100, 101, 102, 103]
      and all("a-red-fox-in-snow" in Path(f).name for f in res["files"]) and res["backend"] == "sdcpp", res)
for f in res["files"]:
    Path(f).unlink()


def fake_fail(argv, **kw):
    return Proc(1, "", "CUDA error: out of memory")


try:
    creative.run_local_image("x", "", 1024, 1024, 1, 1, WS / "images", run=fake_fail, env=ENV, info=PC)
    check("a failed run raises with sd.cpp's own error (the runner then tries the next backend)", False)
except RuntimeError as exc:
    check("a failed run raises with sd.cpp's own error (the runner then tries the next backend)", "out of memory" in str(exc))

section("the image runner: the local backend first once installed; any backend can make 4")
os.environ["LOKI_DATA"] = str(DATA)
orig_status = creative.local_image_status
creative.local_image_status = lambda env=None, info=None, which=None: {"backend": "sdcpp", "ready": True, "why": ""}
imagegen._creative = lambda: creative
order = imagegen.plan_order("auto")["order"]
check("auto order: sdcpp, ..., pollinations last", order[0] == "sdcpp" and order[-1] == "pollinations", order)
creative.local_image_status = lambda env=None, info=None, which=None: {"backend": "mflux", "ready": False, "why": "not installed"}
plan = imagegen.plan_order("auto")
check("not installed: skipped with the reason (System check shows it)", "mflux" not in plan["order"]
      and plan["skipped"].get("mflux") == "not installed", plan)
creative.local_image_status = orig_status
calls = []


def fake_backend(prompt, w, h, out_dir, seed):
    calls.append(seed)
    return {"file": "%s/%d.png" % (out_dir, seed), "backend": "pollinations"}


multi = imagegen.one_by_one(fake_backend, "fox", 1024, 1024, "images", 7, 3)
check("one picture per call backends: seeds 7, 8, 9", calls == [7, 8, 9] and multi["seeds"] == [7, 8, 9]
      and len(multi["files"]) == 3 and multi["file"] == "images/7.png", multi)
calls.clear()


def flaky(prompt, w, h, out_dir, seed):
    if seed > 7:
        raise RuntimeError("rate limited")
    return fake_backend(prompt, w, h, out_dir, seed)


check("a batch that fails half way keeps what was made", imagegen.one_by_one(flaky, "f", 64, 64, "i", 7, 4)["files"] == ["i/7.png"])

section("the conductor passes size, seed, count and negative to the runner (policy first)")
jobs = []


class Allow:
    def capability(self, cap, perm=""):
        return types.SimpleNamespace(allowed=True, reason="")


class Deny:
    def capability(self, cap, perm=""):
        return types.SimpleNamespace(allowed=False, reason="image-gen is not enabled")


def fake_runner(argv, input=None, **kw):
    jobs.append(json.loads(input))
    return Proc(0, json.dumps({"ok": True, "file": "x.png", "files": ["x.png"], "seeds": [5]}))


cond = conductor.Conductor(Allow(), None, env={"LOKI_WORKSPACE": str(WS)}, runner=fake_runner, python="python")
got = cond.make_image("a fox", {"width": 1344, "height": 768, "seed": 5, "count": 4, "negative": "blurry", "evil": "x"})
check("the job carries them; unknown options are dropped", got["ok"] and jobs[0]["width"] == 1344 and jobs[0]["count"] == 4
      and jobs[0]["negative"] == "blurry" and "evil" not in jobs[0], jobs)
check("a disabled image-gen is refused before anything runs",
      not conductor.Conductor(Deny(), None, env={}, runner=fake_runner, python="python").make_image("x")["ok"] and len(jobs) == 1)

# ---------------------------------------------------------------------------- Creations
section("Creations: style, enhance, aspect, x4 -> pictures with their story (metadata sidecars)")


class FakeConductor:
    def __init__(self):
        self.calls = []

    def make_image(self, prompt, options):
        self.calls.append((prompt, dict(options)))
        out = []
        for i in range(options.get("count", 1)):
            p = WS / "images" / ("20261017-12000%d-fox-%d.png" % (len(self.calls), i))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\x89PNG")
            out.append(str(p))
        seed = options.get("seed") or 1234
        return {"ok": True, "files": out, "seeds": [seed + i for i in range(len(out))], "backend": "sdcpp",
                "model": "zimage-q4"}


async def fake_ask(prompt, *a, **k):
    return "a small red fox curled asleep in fresh powder snow, soft golden dawn light, gentle mist, cosy and calm"


agent = types.SimpleNamespace(WORKSPACE=WS, CONDUCTOR=FakeConductor(), _port_ask=fake_ask)
r1 = creations.make_image(agent, "a fox asleep", style="pixel art", aspect="16:9", count=4, thread=False)
call_prompt, opts = agent.CONDUCTOR.calls[0]
check("pixel art style applied (Fooocus template + negative), 16:9 = 1344x768, x4",
      "pixel" in call_prompt.lower() and "a fox asleep" in call_prompt and opts["negative"]
      and (opts["width"], opts["height"]) == (1344, 768) and opts["count"] == 4, (call_prompt, opts))
items = [c for c in creations.list_creations(WS) if c["kind"] == "images"]
check("the four are on the wall with prompt, style, backend, seed, aspect; not starred",
      len(items) == 4 and all(c.get("prompt") == call_prompt and c.get("style") == "pixel art" and c.get("backend") == "sdcpp"
                              and c.get("aspect") == "16:9" and c["liked"] is False for c in items)
      and sorted(c["seed"] for c in items) == [1234, 1235, 1236, 1237], items[:1])
check("the sidecar is <kind>/.meta/<file>.json and never shows as a creation",
      (WS / "images" / ".meta").is_dir() and not any(".meta" in c["path"] for c in creations.list_creations(WS)))
done = [m for m in creations.making() if m["id"] == r1["id"]][0]
check("the status line knows it made 4 pictures", done["ok"] and len(done["files"]) == 4 and done["count"] == 4, done)

creations.make_image(agent, "a fox asleep", style="cinematic", enhance=True, thread=False)
enh_prompt = agent.CONDUCTOR.calls[1][0]
check("Enhance: LOKI's model rewrote the idea, then the style was applied",
      "powder snow" in enh_prompt and "cinematic" in enh_prompt.lower(), enh_prompt)
creations.make_image(types.SimpleNamespace(WORKSPACE=WS, CONDUCTOR=agent.CONDUCTOR), "a fox", enhance=True, seed=9, thread=False)
check("Enhance without a model: the seeded offline expansion (Fooocus' words)",
      agent.CONDUCTOR.calls[2][0].startswith("a fox, ") and agent.CONDUCTOR.calls[2][1]["seed"] == 9, agent.CONDUCTOR.calls[2])

section("the star, make more like this, delete (to the trash, never gone)")
first = sorted(items, key=lambda c: c["seed"])[0]
check("star it", creations.set_liked(WS, first["path"], True)["liked"]
      and [c for c in creations.list_creations(WS) if c["path"] == first["path"]][0]["liked"])
check("liked_meta feeds the daily creation", any(m.get("style") == "pixel art" for m in creations.liked_meta(WS)))
check("starring something that is not a creation is refused", not creations.set_liked(WS, "images/../../x.png")["ok"])
more = creations.more_like(agent, first["path"], thread=False)
again_prompt, again_opts = agent.CONDUCTOR.calls[-1]
check("more like this: the SAME prompt and negative, 16:9, 4 variations from the next seed",
      more["ok"] and again_prompt == first["prompt"] and again_opts["negative"] == first["negative"]
      and (again_opts["width"], again_opts["height"]) == (1344, 768) and again_opts["count"] == 4
      and again_opts["seed"] == first["seed"] + 1, (again_prompt, again_opts))
child = [c for c in creations.list_creations(WS) if c.get("parent") == first["path"]]
check("...and they remember where they came from", len(child) == 4 and all(c["style"] == "pixel art" for c in child), child[:1])
old = WS / "images" / "20261014-201742-red-fox-in-studio-light.jpg"
old.write_bytes(b"\xff\xd8\xff")
creations.more_like(agent, "images/" + old.name, thread=False)
check("a picture from before session 28 (no sidecar): more like it from its title",
      agent.CONDUCTOR.calls[-1][0].startswith("Red fox in studio light"), agent.CONDUCTOR.calls[-1])
gone = creations.delete_creation(WS, first["path"])
check("delete moves the file and its sidecar to trash/images/",
      gone["ok"] and (WS / gone["trash"]).is_file() and not (WS / first["path"]).exists()
      and (WS / "trash" / "images" / ".meta" / (Path(gone["trash"]).name + ".json")).is_file(), gone)
check("...and it is off the wall", not any(c["path"] == first["path"] for c in creations.list_creations(WS)))
check("the trash itself is never a creation folder", creations.creation_file(WS, "/creations/trash/" + Path(gone["trash"]).name) is None)
check("delete refuses paths outside the creations", not creations.delete_creation(WS, "../ws/x.png")["ok"]
      and not creations.delete_creation(WS, "images/../../secret.png")["ok"])
check("the old API still works: make_image(agent, prompt) with only conductor_tool",
      creations.make_image(types.SimpleNamespace(conductor_tool=lambda role, task: "made images/x.jpg with pollinations"),
                           "a fox", thread=False)["ok"])

section("music and voice show on the wall with a player")
(WS / "music").mkdir(exist_ok=True)
(WS / "music" / "20261017-101010-lofi-fox-beats.mp3").write_bytes(b"ID3")
(WS / "voice").mkdir(exist_ok=True)
(WS / "voice" / "20261017-101011-hello-mohamed.wav").write_bytes(b"RIFF")
audio = [c for c in creations.list_creations(WS) if c["show"] == "audio"]
check("music/ and voice/ are listed as audio", {c["kind"] for c in audio} == {"music", "voice"}
      and any(c["title"] == "Lofi fox beats" for c in audio), audio)
check("and served", creations.creation_file(WS, "/creations/music/20261017-101010-lofi-fox-beats.mp3") is not None)

# ---------------------------------------------------------------------------- video
section("video: Wan2GP headless on the PC (LTX-Video distilled, profile 4), image-to-video")
pic = [c for c in creations.list_creations(WS) if c["kind"] == "images"][0]
wan_runs = []


def fake_wgp(argv, cwd=None, **kw):
    wan_runs.append((argv, json.loads(Path(argv[argv.index("--process") + 1]).read_text(encoding="utf-8"))))
    out_dir = Path(argv[argv.index("--output-dir") + 1])
    (out_dir / "2026-10-17-12h00m00s_seed5_fox.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return Proc(0)


vid = creative.make_video("a fox waking up", WS, image=pic["path"], seconds=3, seed=5, env=ENV, info=PC, run=fake_wgp)
wargv, settings = wan_runs[0]
check("wgp.py --process <settings.json> --output-dir ... --profile 4 (8 GB), no web UI",
      wargv[1].endswith("wgp.py") and "--process" in wargv and wargv[wargv.index("--profile") + 1] == "4", wargv)
check("settings: LTX distilled, the prompt, the seed, 3 s = 73 frames at 24 fps, the picture as the first frame",
      settings["model_type"] == "ltxv_distilled" and settings["prompt"] == "a fox waking up" and settings["seed"] == 5
      and settings["video_length"] == 73 and settings["image_prompt_type"] == "S"
      and Path(settings["image_start"]).name == Path(pic["path"]).name, settings)
check("the video lands in videos/ with LOKI's name; the settings file is cleaned up",
      vid["ok"] and vid["file"].startswith("videos/") and (WS / vid["file"]).is_file()
      and not list((WS / "videos" / ".wan2gp").glob("job-*.json")), vid)
tpl = creative.wan2gp_settings("x", 1, 2, "", ENV, template={"model_type": "t2v_1.3B", "resolution": "480x832", "prompt": "old"})
check("a template exported from Wan2GP's UI wins (model, resolution); Wan at 16 fps: 2 s = 33 frames; no image keys",
      tpl["model_type"] == "t2v_1.3B" and tpl["resolution"] == "480x832" and tpl["prompt"] == "x"
      and tpl["video_length"] == 33 and "image_start" not in tpl, tpl)
bad = creative.make_video("x", WS, env=ENV, info=PC, run=lambda a, **k: Proc(1, "", "torch.OutOfMemoryError"))
check("Wan2GP failing says why", not bad["ok"] and "OutOfMemory" in bad["error"], bad)

section("video falls back to Higgsfield (the Mac), and says what to do without a key")
nokey = creative.make_video("a fox", WS, env={"LOKI_DATA": str(TMP / "macdata")}, info=MAC)
check("no Wan2GP, no key: a clear reason", not nokey["ok"] and "Higgsfield" in nokey["error"], nokey)
higgs_calls = []


def fake_higgs(prompt, **kw):
    higgs_calls.append((prompt, kw))
    (WS / "videos" / "higgsfield-1.mp4").write_bytes(b"x")
    return {"ok": True, "files": ["videos/higgsfield-1.mp4"]}


hv = creative.make_video("a fox", WS, image=pic["path"], env={"LOKI_DATA": str(TMP / "macdata"), "HIGGSFIELD_KEY": "k:s"},
                         info=MAC, higgs=fake_higgs)
check("with a key: Higgsfield video (duration), and it says the picture was not sent",
      hv["ok"] and hv["backend"] == "higgsfield" and higgs_calls[0][1]["kind"] == "video"
      and higgs_calls[0][1]["extra"] == {"duration": 3} and "prompt only" in hv["note"], hv)

section("Animate this (from the wall)")
anim_calls = []


def fake_maker(prompt, workspace, image="", seconds=3, seed=0):
    anim_calls.append((prompt, image, seconds, seed))
    p = Path(workspace) / "videos" / "20261017-130000-anim.mp4"
    p.write_bytes(b"x")
    return {"ok": True, "file": "videos/" + p.name, "backend": "wan2gp", "seed": seed}


a = creations.animate(agent, pic["path"], seconds=3, thread=False, maker=fake_maker)
check("the picture's own idea + gentle motion, its seed, 3 s", a["ok"] and anim_calls[0][1] == pic["path"]
      and "gentle natural motion" in anim_calls[0][0] and anim_calls[0][3] == pic["seed"], anim_calls)
vmeta = creations.read_meta(WS, "videos/20261017-130000-anim.mp4")
check("the video's sidecar points back at the picture", vmeta.get("parent") == pic["path"] and vmeta.get("backend") == "wan2gp", vmeta)
check("only pictures can be animated", not creations.animate(agent, "music/20261017-101010-lofi-fox-beats.mp3")["ok"])

# ---------------------------------------------------------------------------- daily creation
section("the daily creation: on for the PC, off for the Mac, one a day, from the stars")
check("auto: on with an NVIDIA GPU, off on the Mac", creative.daily_enabled({}, PC) and not creative.daily_enabled({}, MAC))
check("LOKI_DAILY_CREATION on/off wins", creative.daily_enabled({"LOKI_DAILY_CREATION": "on"}, MAC)
      and not creative.daily_enabled({"LOKI_DAILY_CREATION": "off"}, PC))
fox = creative.daily_idea([], "2026-10-17")
check("with no stars: a fox, in a style LOKI knows", "fox" in fox["prompt"] and image_prompt.find_style(fox["style"]), fox)
check("the same day gives the same idea", creative.daily_idea([], "2026-10-17") == fox)
liked = [{"idea": "a lighthouse on a cliff", "style": "pixel art"}]
picks = [creative.daily_idea(liked, "2026-10-%02d" % d) for d in range(1, 29)]
check("with stars: their styles and subjects come back most days",
      sum(p["style"] == "pixel art" for p in picks) > 12 and any("lighthouse" in p["prompt"] for p in picks), picks[:3])
made_today = []
DAILY_ENV = {"LOKI_DATA": str(TMP / "daily")}
first_run = creative.daily_creation(lambda p, **kw: made_today.append((p, kw)) or {"ok": True, "id": "1"}, liked,
                                    env=DAILY_ENV, info=PC, clock=lambda: 1792224000)
second = creative.daily_creation(lambda p, **kw: made_today.append((p, kw)) or {"ok": True}, liked, env=DAILY_ENV,
                                 info=PC, clock=lambda: 1792224000 + 3600)
check("one picture a day, enhanced and marked daily", first_run.startswith("started today's picture") and second == ""
      and len(made_today) == 1 and made_today[0][1]["enhance"] and made_today[0][1]["daily"], (first_run, made_today))
check("the next day: another", creative.daily_creation(lambda p, **kw: made_today.append(p) or {"ok": True}, liked,
                                                        env=DAILY_ENV, info=PC, clock=lambda: 1792224000 + 90000) != "")
check("off on the Mac by default", creative.daily_creation(lambda p, **kw: {"ok": True}, [], env={"LOKI_DATA": str(TMP / "m")},
                                                           info=MAC) == "")

section("the autopilot runs it when idle (and only where it is on)")
os.environ["LOKI_DAILY_CREATION"] = "on"
os.environ["LOKI_DATA"] = str(TMP / "auto")


class IdleState:
    last_request_at = 0
    jobs = None


made_by_autopilot = []
orig_make = creations.make_image
creations.make_image = lambda ag, prompt, **kw: made_by_autopilot.append((prompt, kw)) or {"ok": True, "id": "a"}
pilot = autopilot.Autopilot(state=IdleState(), agent=types.SimpleNamespace(WORKSPACE=WS, DATA_DIR=str(TMP / "auto")),
                            data_dir=TMP / "auto", clock=lambda: 1792224000.0)
pilot.data["last"].update({"health": 1792224000.0, "inbox": 1792224000.0, "report": 1792224000.0,
                            "selftest": 1792224000.0, "task_bench": 1792224000.0})
ran = pilot.tick()
check("an idle pass makes today's picture", ran and ran[0][0] == "creation" and made_by_autopilot
      and made_by_autopilot[0][1]["daily"], (ran, made_by_autopilot))
os.environ["LOKI_DAILY_CREATION"] = "off"
pilot2 = autopilot.Autopilot(state=IdleState(), agent=types.SimpleNamespace(WORKSPACE=WS), data_dir=TMP / "auto2",
                             clock=lambda: 1792224000.0)
pilot2.data["last"].update({"health": 1792224000.0, "inbox": 1792224000.0, "report": 1792224000.0,
                             "selftest": 1792224000.0, "task_bench": 1792224000.0})
check("switched off: no creation duty at all", pilot2.tick() == [])
creations.make_image = orig_make
os.environ.pop("LOKI_DAILY_CREATION", None)
os.environ["LOKI_DATA"] = str(DATA)

# ---------------------------------------------------------------------------- add-ons, bridge, UI
section("Settings > Add-ons: local-image and local-video cards with an Install button")
registry = manifests.default_registry(REPO, TMP / "catalog")
rows = {r["name"]: r for r in registry.present()}
check("both manifests are valid and off by default", all(n in rows and not rows[n]["errors"]
                                                         and rows[n]["status"] in ("disabled", "reference")
                                                         for n in ("local-image", "local-video")),
      {n: rows.get(n, {}).get("errors") for n in ("local-image", "local-video")})
check("local-video says it is for Windows/Linux (NVIDIA)", "win32" in json.loads(
    (REPO / "capabilities" / "local-video" / "manifest.json").read_text(encoding="utf-8"))["platforms"])
plan = addons_install.plan("local-image")
check("the install plan has steps (shown before anything runs)", plan["steps"] and "installed" in plan, plan)
started = []
orig_start = creative.start_install
creative.start_install = lambda name, **kw: started.append(name) or {"ok": True, "started": True, "specs": [], "log": []}
res = addons_install.install("local-image")
creative.start_install = orig_start
check("Install starts the background installer (not pip)", started == ["local-image"] and res["started"], res)
check("setup_extras has the same two installers", "local-image" in (REPO / "tools" / "setup_extras.py").read_text(encoding="utf-8"))

bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge: like / delete / more / animate, video from the Make box, styles + aspects + backends in GET /creations",
      all(s in bridge for s in ('"/creations/like"', '"/creations/delete"', '"/creations/more"', '"/creations/animate"',
                                'data.get("kind") == "video"', '"styles": creations.styles()', '"creative": creative_summary()')))
js = (REPO / "app" / "ui" / "creations.js").read_text(encoding="utf-8")
check("the Make box: style picker (pixel art first), Enhance, aspect, x4",
      all(s in js for s in ("creations-style", '"pixel art"', "creations-enhance", "creations-aspect", "creations-four",
                            "count: four.checked ? 4 : 1")))
check("the wall: prompt on hover, the star, audio player, filters, Make more like this, Animate this, Delete",
      all(s in js for s in ("creation-prompt", "creation-star", 'document.createElement("audio")', "creations-filter",
                            "Make more like this", "Animate this", "/creations/delete", "trash folder")))
css = (REPO / "app" / "ui" / "app.css").read_text(encoding="utf-8")
check("hover shows the prompt", ".creation:hover .creation-prompt" in css)
app_js = (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8")
check("the Add-ons card shows the steps and an Install button for download installers",
      "cap.install.supported && !cap.install.installed" in app_js)
loki_src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("the agent has make_local_video (one small tool block)", 'LOCAL_TOOLS["make_local_video"]' in loki_src
      and 'MODIFYING |= {"make_local_video"}' in loki_src)
ship = (REPO / "tools" / "ship.py").read_text(encoding="utf-8")
check("this suite runs in ship.py", '"test_creative"' in ship)
third = (REPO / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
check("THIRD_PARTY names stable-diffusion.cpp, mflux and Wan2GP",
      all(s in third for s in ("stable-diffusion.cpp", "mflux", "Wan2GP")))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
