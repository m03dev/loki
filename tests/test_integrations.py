"""Offline tests for the conductor and its specialists, the brain map, and the
third-party integrations (Perplexity, crawl4ai, Scrapling, Firecrawl, Browser Use,
Hindsight, Headroom, SkillSpector, Hermes Agent, Kiln). Every outside service is faked.

    python tests/test_integrations.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
sys.path.insert(0, str(REPO / "engine"))

import brain  # noqa: E402
import conductor  # noqa: E402
import manifests  # noqa: E402
import policy  # noqa: E402
import safe_exec  # noqa: E402
import skill_scan  # noqa: E402
import workers  # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (detail,)))


def section(title):
    print("\n" + title)


TMP = Path(tempfile.mkdtemp(prefix="loki-integrations-"))
NEW = ("perplexity", "crawl4ai", "scrapling", "firecrawl", "browser-use", "hindsight", "headroom",
       "skillspector", "hermes-agent", "kiln")

# ------------------------------------------------------------------ manifests
section("integration manifests")
real = manifests.default_registry(REPO, TMP / "data")
rows = {r["name"]: r for r in real.present()}
check("every new integration has a valid built-in manifest",
      all(n in rows and not rows[n]["errors"] for n in NEW), {n: rows.get(n, {}).get("errors") for n in NEW})
check("all of them start disabled", all(rows[n]["status"] == "disabled" for n in NEW))
check("Firecrawl's AGPL licence is stated", "AGPL" in rows["firecrawl"]["license"])
check("browser-use declares network access as high risk",
      any(p["id"] == "network" and p["high_risk"] for p in rows["browser-use"]["permissions"]))
reg_mod = manifests.Registry([("b", TMP / "m")], manifests.Enablement(TMP / "e.json"), env={}, which=lambda c: None)
check("python requirements are checked without importing",
      manifests.missing_requirements({"requires_python": ["definitely_not_a_module_xyz", "json"]}, {},
                                     lambda c: None) == ["python package `definitely_not_a_module_xyz`"])

# ------------------------------------------------------------------ conductor
section("the conductor")


class Reg:
    def __init__(self, on):
        self.on = on

    def get(self, name):
        return {"status": "enabled" if name in self.on else "disabled"}

    def granted(self, name):
        return set(self.on.get(name, ()))


def make(on, env=None, runner=None, opener=None):
    engine = policy.PolicyEngine(lambda p: p, lambda c: (True, "ok"), safe_exec.parse, set(), Reg(on), env=env or {})
    return conductor.Conductor(engine, Reg(on), env=env or {}, runner=runner or (lambda *a, **k: None),
                               opener=opener or (lambda *a, **k: None), python="python3")


c = make({})
check("with nothing enabled no role is ready", not any(r["ready"] for r in c.roster()))
check("an unready role explains why", "not enabled" in c.run("research", "q"))
check("with nothing ready the prompt adds no specialists", c.prompt_section() == "")
check("an unknown role is refused", "unknown role" in c.run("hack", "x"))


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


sent = []


def perplexity_opener(request, timeout):
    sent.append((request.full_url, json.loads(request.data), dict(request.headers)))
    return Resp(json.dumps({"choices": [{"message": {"content": "Paris is the capital [1]."}}],
                            "search_results": [{"url": "https://example.org/paris"}]}).encode())


c = make({"perplexity": ["network:api.perplexity.ai", "secret:PERPLEXITY_API_KEY"]},
         env={"PERPLEXITY_API_KEY": "pk-test"}, opener=perplexity_opener)
answer = c.run("research", "capital of France?")
check("research calls Perplexity Sonar with the key", sent and sent[0][0] == conductor.PERPLEXITY_URL
      and sent[0][1]["model"] == "sonar" and sent[0][2].get("Authorization") == "Bearer pk-test")
check("research returns the answer with numbered sources", "Paris" in answer and "[1] https://example.org/paris" in answer, answer)
check("a ready role is advertised in the system prompt", "research" in c.prompt_section())
c2 = make({"perplexity": []}, env={"PERPLEXITY_API_KEY": "k"}, opener=perplexity_opener)
check("research without the granted host is refused", "not granted" in c2.run("research", "q"))

calls = []


def fake_runner(argv, **kw):
    calls.append((argv, json.loads(kw["input"]), kw))
    job = json.loads(kw["input"])
    if argv[-1].endswith("web_read.py"):
        out = {"ok": True, "text": "# Example\nhello from " + job["backend"], "truncated": False}
    elif argv[-1].endswith("browse.py"):
        out = {"ok": True, "text": "found 42 stars"}
    else:
        out = {"ok": True, "result": {"memories": ["likes tests"]}}
    return types.SimpleNamespace(returncode=0, stdout="noise\n" + json.dumps(out) + "\n", stderr="")


c = make({"scrapling": ["network", "process:spawn"], "crawl4ai": ["network", "process:spawn"]},
         env={"LOKI_READ_ORDER": "scrapling,crawl4ai"}, runner=fake_runner)
text = c.run("read_web", url="https://example.com")
check("read_web uses the first enabled backend in LOKI_READ_ORDER", "hello from scrapling" in text, text)
check("runners run isolated (-I) without a shell and with a timeout",
      calls[-1][0][1] == "-I" and calls[-1][2]["shell"] is False and calls[-1][2]["timeout"] > 0)
check("read_web refuses a non-http url", "http(s)" in c.run("read_web", url="file:///etc/passwd"))
c = make({"crawl4ai": ["network", "process:spawn"]}, runner=fake_runner)
check("read_web falls back to crawl4ai when it is the one enabled", "hello from crawl4ai" in c.run("read_web", url="https://e.com"))

fire = []


def firecrawl_opener(request, timeout):
    fire.append((request.full_url, json.loads(request.data)))
    return Resp(json.dumps({"success": True, "data": {"markdown": "# Fire\ncrawled"}}).encode())


c = make({"firecrawl": ["network:loopback"]}, opener=firecrawl_opener)
text = c.run("read_web", url="https://example.com")
check("Firecrawl is called at the self-hosted /v2/scrape for markdown",
      fire and fire[0][0] == "http://localhost:3002/v2/scrape" and fire[0][1]["formats"] == ["markdown"] and "crawled" in text)
c = make({"firecrawl": ["network:loopback"]}, env={"LOKI_FIRECRAWL_URL": "https://firecrawl.remote.example"}, opener=firecrawl_opener)
check("a remote Firecrawl host needs LOKI_NET_ALLOW", "not allowed" in c.run("read_web", url="https://e.com"))

c = make({"browser-use": ["network", "process:spawn"]}, env={"LOKI_BROWSE_MODEL": "m"}, runner=fake_runner)
check("browse runs Browser Use in its runner", c.run("browse", "count stars") == "found 42 stars")
check("browse is flagged as needing approval", c.needs_approval("browse") and not c.needs_approval("research"))
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(), Reg({}), env={})
v = engine.tool_call("conductor", {"role": "browse", "task": "x"})
check("the policy always asks before a browser acts (not decidable)", v.decision == policy.ASK and not v.decidable)
check("other roles are not prompted", engine.tool_call("conductor", {"role": "research"}).allowed)

c = make({"hindsight": ["network:loopback"]}, runner=fake_runner)
check("remember stores through Hindsight", c.run("remember", "likes tests") == "stored in long-term memory"
      and calls[-1][1]["op"] == "retain" and calls[-1][1]["bank"] == "loki")
check("recall queries Hindsight", "likes tests" in c.run("recall", "what do they like?") and calls[-1][1]["op"] == "recall")


def timeout_runner(argv, **kw):
    import subprocess
    raise subprocess.TimeoutExpired(argv, kw["timeout"])


c = make({"browser-use": ["network", "process:spawn"]}, runner=timeout_runner)
check("a runner that hangs times out cleanly", "timed out" in c.run("browse", "x"))
c = make({"hindsight": ["network:loopback"]}, runner=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="boom"))
check("a runner with no result reports its stderr", "boom" in c.run("recall", "x"))

for script in ("web_read", "browse", "hindsight"):
    import subprocess as sp
    proc = sp.run([sys.executable, "-I", str(conductor.RUNNERS / (script + ".py"))],
                  input=json.dumps({"backend": "crawl4ai", "url": "https://e.com", "op": "recall", "task": "x"}),
                  capture_output=True, text=True, timeout=60)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    check("runner %s reports a missing library instead of crashing" % script,
          out["ok"] is False and "not installed" in out["error"], out)

# ------------------------------------------------------------------ vision-track
section("vision-track: object tracking in videos (Roboflow trackers + RF-DETR)")
import importlib.util  # noqa: E402
import subprocess  # noqa: E402

sys.path.insert(0, str(REPO / "engine" / "runners"))
import track  # noqa: E402

vt = rows.get("vision-track", {})
check("vision-track has a valid built-in manifest", vt and not vt["errors"], vt.get("errors"))
check("vision-track is off until the user turns it on", vt.get("status") == "disabled", vt.get("status"))
vt_manifest = json.loads((REPO / "capabilities" / "vision-track" / "manifest.json").read_text(encoding="utf-8"))
check("it needs trackers + supervision and points at its runner",
      vt_manifest["requires_python"] == ["trackers", "supervision"] and vt_manifest["entrypoint"] == "runners/track.py"
      and "fs:workspace" in vt_manifest["permissions"] and "weights" in vt_manifest["description"])
check("the runner imports nothing heavy at load time",
      not any(m in sys.modules for m in ("supervision", "trackers", "rfdetr", "cv2")))

ws = TMP / "vt-ws"
(ws / "clips").mkdir(parents=True)
(ws / "clips" / "street.mp4").write_bytes(b"\x00fake")
(TMP / "outside.mp4").write_bytes(b"\x00fake")
for bad in ("../outside.mp4", str(TMP / "outside.mp4")):
    try:
        track.track({"workspace": str(ws), "video": bad}, kit_factory=lambda *a: None)
        check("the runner refuses a video outside the workspace (%s)" % bad, False)
    except ValueError as exc:
        check("the runner refuses a video outside the workspace (%s)" % bad, "escapes workspace" in str(exc), exc)
try:
    track.track({"workspace": str(ws), "video": "clips/street.mp4", "out_dir": "../elsewhere"}, kit_factory=lambda *a: None)
    check("the runner refuses to write outside the workspace", False)
except ValueError as exc:
    check("the runner refuses to write outside the workspace", "escapes workspace" in str(exc), exc)


def missing_kit(*a):
    track._need("definitely_not_a_module_xyz", "trackers")


try:
    track.track({"workspace": str(ws), "video": "clips/street.mp4"}, kit_factory=missing_kit)
    check("a missing package says how to turn vision-track on", False)
except track.MissingPackage as exc:
    check("a missing package says how to turn vision-track on",
          "pip install trackers" in str(exc) and "setup_extras.py vision" in str(exc), exc)
if importlib.util.find_spec("supervision") is None:
    proc = subprocess.run([sys.executable, "-I", str(conductor.RUNNERS / "track.py")],
                          input=json.dumps({"workspace": str(ws), "video": "clips/street.mp4"}),
                          capture_output=True, text=True, timeout=60)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    check("the runner process reports the missing packages as JSON",
          out["ok"] is False and "setup_extras.py vision" in out["error"], out)


class FakeDets:
    """Just enough of supervision.Detections: len, boolean-mask indexing, xyxy/class_id/tracker_id/data."""
    def __init__(self, xyxy, class_id, tracker_id=None, names=None):
        self.xyxy, self.class_id, self.tracker_id = list(xyxy), list(class_id), tracker_id
        self.data = {"class_name": list(names)} if names is not None else {}

    def __len__(self):
        return len(self.xyxy)

    def __getitem__(self, mask):
        pick = [i for i, m in enumerate(mask) if m]
        names = self.data.get("class_name")
        return FakeDets([self.xyxy[i] for i in pick], [self.class_id[i] for i in pick],
                        None if self.tracker_id is None else [self.tracker_id[i] for i in pick],
                        None if names is None else [names[i] for i in pick])


class FakeTracker:
    """Gives each object the id of its class slot; confirms a track from its second frame on."""
    def __init__(self):
        self.calls = 0

    def update(self, detections, frame=None):
        self.calls += 1
        ids = [(-1 if self.calls == 1 else int(c) + 1) for c in detections.class_id]
        return FakeDets(detections.xyxy, detections.class_id, ids)


class FakeSink:
    def __init__(self, path):
        self.path, self.frames = path, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        Path(self.path).write_bytes(b"MP4" * len(self.frames))
        return False

    def write_frame(self, frame):
        self.frames.append(frame)


def fake_detect(index):
    # three objects: car 0 crosses left->right, car 1 stays put, a person (class 2) stays put
    x = 10 + index * 20
    return FakeDets([[x, 40, x + 10, 50], [100, 100, 110, 110], [150, 10, 160, 30]], [0, 1, 2])


names = {0: "car", 1: "car", 2: "person"}
fake_tracker = FakeTracker()
annotated = []


def fake_kit(video, tracker_name, model, threshold, max_frames):
    fake_kit.args = (video, tracker_name, model, threshold, max_frames)

    def keep(dets, wanted):
        return dets[[names[c] in wanted for c in dets.class_id]] if wanted else dets
    return track.Kit(frames=iter(range(12)), fps=10.0, width=200, height=200, detect=fake_detect,
                     tracker=fake_tracker, keep=keep, sink=FakeSink,
                     annotate=lambda frame, tracked: annotated.append(list(tracked.tracker_id)) or frame, names=names)


result = track.track({"workspace": str(ws), "video": "clips/street.mp4", "classes": "cars", "max_frames": 10},
                     kit_factory=fake_kit)
check("the pipeline runs detector -> class filter -> tracker -> annotator frame by frame",
      fake_tracker.calls == 10 and len(annotated) == 10 and annotated[-1] == [1, 2], (fake_tracker.calls, annotated[-1:]))
check("'cars' means the detector's 'car' class and the tracker defaults to ByteTrack",
      fake_kit.args[1] == "bytetrack" and result["tracker"] == "bytetrack")
check("a plain-English summary comes back", result["summary"] == "Found 2 cars; 1 crossed the frame (10 frames).",
      result["summary"])
data = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
first = {t["track_id"]: t for t in data["tracks"]}
check("the JSON has one row per track with class, first/last frame and frames seen",
      sorted(first) == [1, 2] and first[1]["class"] == "car" and first[1]["first_frame"] == 1
      and first[1]["last_frame"] == 9 and first[1]["frames_seen"] == 9 and first[1]["crossed"]
      and not first[2]["crossed"], data["tracks"])
csv_text = Path(result["csv"]).read_text(encoding="utf-8")
check("a CSV is written beside it", csv_text.startswith("track_id,class,first_frame") and csv_text.count("\n") == 3, csv_text)
check("the annotated MP4 and summaries land in the workspace's tracks/ folder",
      all(Path(result[k]).parent == (ws / "tracks").resolve() for k in ("video", "json", "csv"))
      and Path(result["video"]).name == "street-tracked.mp4" and Path(result["video"]).stat().st_size > 0)
fake_tracker = FakeTracker()
result = track.track({"workspace": str(ws), "video": "clips/street.mp4", "classes": "zebra"}, kit_factory=fake_kit)
check("nothing found is said plainly", result["summary"] == "Found no zebras in 12 frames.", result["summary"])
try:
    track.track({"workspace": str(ws), "video": "clips/street.mp4", "tracker": "magic"}, kit_factory=fake_kit)
    check("an unknown tracker is refused", False)
except ValueError as exc:
    check("an unknown tracker is refused", "tracker must be one of" in str(exc), exc)
check("tracker names match the trackers package",
      track.TRACKERS == {"sort": "SORTTracker", "bytetrack": "ByteTrackTracker", "ocsort": "OCSORTTracker",
                         "botsort": "BoTSORTTracker", "cbiou": "CBIoUTracker"})

# the conductor role, gated by the capability policy
c = make({})
check("with vision-track off, track is not offered and says why",
      "vision-track is not enabled" in c.run("track", "car", "clips/street.mp4")
      and "- track:" not in c.prompt_section())
track_jobs = []


def track_runner(argv, **kw):
    track_jobs.append((argv, json.loads(kw["input"]), kw))
    return types.SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
        "ok": True, "summary": "Found 7 cars; 5 crossed the frame (300 frames).", "video": "tracks/street-tracked.mp4",
        "json": "tracks/street-tracks.json", "csv": "tracks/street-tracks.csv"}))


c = make({"vision-track": ["fs:workspace", "network"]}, env={"LOKI_WORKSPACE": str(ws)}, runner=track_runner)
answer = c.run("track", "track the cars tracker=ocsort max_frames=300", "clips/street.mp4")
job = track_jobs[-1][1] if track_jobs else {}
check("with it on, track runs the isolated runner with the parsed job",
      track_jobs and track_jobs[-1][0][-1].endswith("track.py") and track_jobs[-1][0][1] == "-I"
      and job["video"] == "clips/street.mp4" and job["classes"] == ["cars"] and job["tracker"] == "ocsort"
      and job["max_frames"] == 300 and Path(job["workspace"]) == ws.resolve()
      and Path(job["out_dir"]) == ws.resolve() / "tracks", job)
check("and answers in plain English with the files", answer.startswith("Found 7 cars; 5 crossed the frame")
      and "street-tracked.mp4" in answer, answer)
check("the track role is advertised once enabled", "- track:" in c.prompt_section())
check("the conductor refuses a video outside the workspace before starting anything",
      "outside the workspace" in c.run("track", "car", "../../secret.mp4") and len(track_jobs) == 1)
check("track without a video asks for one", "needs url=" in c.run("track", "car"))
c = make({"vision-track": ["network"]}, env={"LOKI_WORKSPACE": str(ws)}, runner=track_runner)
check("track without the granted fs:workspace permission is refused", "not granted fs:workspace" in c.run("track", "car", "a.mp4"))


def _escape_check(path):
    if ".." in str(path) or str(path).startswith("/"):
        raise ValueError("path escapes workspace: %s" % path)


engine = policy.PolicyEngine(_escape_check, lambda x: (True, ""), safe_exec.parse, set(), Reg({}), env={})
check("the policy denies conductor track with a url outside the workspace",
      engine.tool_call("conductor", {"role": "track", "url": "../../etc/x.mp4"}).decision == policy.DENY)
check("a workspace video passes the policy", engine.tool_call("conductor", {"role": "track", "url": "clips/a.mp4"}).allowed)
check("web roles keep their http url", engine.tool_call("conductor", {"role": "read_web", "url": "https://e.com"}).allowed)
sys.path.insert(0, str(REPO / "tools"))
import setup_extras  # noqa: E402

check("setup_extras has a vision step", "vision" in setup_extras.STEPS and "vision" in (setup_extras.__doc__ or ""))
_pips = []
_saved_pip, _saved_nvidia = setup_extras.pip, setup_extras.nvidia
setup_extras.pip = lambda *p, index="": _pips.append((p, index)) or True
for gpu in (True, False):
    setup_extras.nvidia = lambda gpu=gpu: gpu
    setup_extras.vision()
setup_extras.pip, setup_extras.nvidia = _saved_pip, _saved_nvidia
check("vision installs CUDA torch on an NVIDIA PC, the default wheel elsewhere, then the tracking stack",
      _pips[0][1].startswith("https://download.pytorch.org/") and _pips[2] == (("torch", "torchvision"), "")
      and set(_pips[1][0]) == {"trackers", "supervision", "rfdetr", "opencv-python-headless"}, _pips)

# ------------------------------------------------------------------ in-loop helpers
section("Headroom and SkillSpector")
msgs = [{"role": "user", "content": "x" * 100}]
fake_headroom = types.SimpleNamespace(compress=lambda m, model: types.SimpleNamespace(
    messages=[{"role": "user", "content": "x"}], tokens_saved=99))
out, note = conductor.compress_messages(msgs, "m", importer=lambda n: fake_headroom)
check("Headroom compresses a copy of the messages", out[0]["content"] == "x" and "99" in note and msgs[0]["content"] == "x" * 100)
out, note = conductor.compress_messages(msgs, "m", importer=lambda n: (_ for _ in ()).throw(ImportError()))
check("without Headroom the messages pass through untouched", out is msgs and note == "")
out, _ = conductor.compress_messages(msgs, "m", importer=lambda n: types.SimpleNamespace(
    compress=lambda m, model: (_ for _ in ()).throw(RuntimeError())))
check("a Headroom error never breaks the call", out is msgs)

report = {"findings": [{"severity": "HIGH", "message": "curl | sh in install step"},
                       {"severity": "low", "message": "unpinned dependency"}]}
spector = conductor.skillspector_findings(TMP, which=lambda n: "/x/skillspector",
                                          runner=lambda argv, **k: types.SimpleNamespace(stdout=json.dumps(report)))
check("SkillSpector findings are parsed", ("high", "curl | sh in install step") in spector and len(spector) == 2)
check("no SkillSpector installed means no findings", conductor.skillspector_findings(TMP, which=lambda n: None) == [])
folder = TMP / "sk" / "demo"
folder.mkdir(parents=True)
(folder / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nSteps.\n", encoding="utf-8")
skill_scan.EXTERNAL_SCANNERS[:] = [lambda root: [("high", "dangerous install step")]]
check("a high SkillSpector finding blocks the skill", skill_scan.scan(folder / "SKILL.md")["verdict"] == "blocked")
skill_scan.EXTERNAL_SCANNERS[:] = [lambda root: [("low", "minor")]]
check("a low finding only asks for review", skill_scan.scan(folder / "SKILL.md")["verdict"] == "review")
skill_scan.EXTERNAL_SCANNERS[:] = [lambda root: (_ for _ in ()).throw(RuntimeError())]
check("a crashing external scanner does not block", skill_scan.scan(folder / "SKILL.md")["verdict"] == "ok")
skill_scan.EXTERNAL_SCANNERS[:] = []

# ------------------------------------------------------------------ Hermes
section("Hermes Agent")
check("Hermes starts interactively", workers.agent_argv("hermes", "", interactive=True, env={}) == ["hermes"])
check("Hermes runs one-shot with -z (final answer only)",
      workers.agent_argv("hermes", "fix it", env={}) == ["hermes", "-z", "fix it"])
check("Hermes never gets --yolo", "--yolo" not in workers.agent_argv("hermes", "x", env={}))
check("LOKI_HERMES_MODEL / _PROVIDER become Hermes' own flags",
      workers.agent_argv("hermes", "x", env={"LOKI_HERMES_MODEL": "m1", "LOKI_HERMES_PROVIDER": "openrouter"})
      == ["hermes", "-m", "m1", "--provider", "openrouter", "-z", "x"])
sup = workers.Supervisor(workers.JobStore(TMP / "j.json"), {n: workers.Backend() for n in workers.BACKENDS}, TMP)
check("a Hermes job on the local backend is accepted",
      sup.create({"backend": "local", "agent": "hermes", "workspace": str(TMP), "prompt": "x"})["agent"] == "hermes")
check("a Hermes job on herdr is accepted",
      sup.create({"backend": "herdr", "agent": "hermes", "workspace": str(TMP), "prompt": "x"})["agent"] == "hermes")
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(),
                             Reg({"herdr": ["process:agent"]}), env={})
check("a Hermes job needs the hermes-agent capability", not engine.job("herdr", "hermes").allowed)
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(),
                             Reg({"herdr": ["process:agent"], "hermes-agent": ["process:agent"]}), env={})
check("with both on, a Hermes herdr job is allowed", engine.job("herdr", "hermes").allowed)
engine = policy.PolicyEngine(lambda p: p, lambda x: (True, ""), safe_exec.parse, set(), Reg({}), env={})
check("a local Hermes job still needs the hermes-agent capability", not engine.job("local", "hermes").allowed)
check("Hermes counts as a local agent when installed",
      "hermes" in workers.LocalBackend(TMP, which=lambda n: "/bin/" + n).available()[1])

# ------------------------------------------------------------------ brain map
section("brain map")
data = TMP / "bdata"
(data / "memory").mkdir(parents=True)
(data / "memory.md").write_text("- prefers small PRs\n- uses a Mac mini\n", encoding="utf-8")
(data / "memory" / "people.md").write_text("Sam is a friend. #friends\n", encoding="utf-8")
(data / "jobs.json").write_text(json.dumps({"jobs": [{"id": "j1", "title": "add tests", "status": "done",
                                                      "backend": "herdr", "created": 1}]}), encoding="utf-8")
ws = TMP / "ws"
(ws / "docs" / "sub").mkdir(parents=True)
(ws / "docs" / "a.md").write_text("See [[b]] and [c](sub/c.md).", encoding="utf-8")
(ws / "docs" / "b.md").write_text("Back to [[a|the start]].", encoding="utf-8")
(ws / "docs" / "sub" / "c.md").write_text("leaf", encoding="utf-8")
vault = TMP / "vault"
(vault / ".obsidian").mkdir(parents=True)
(vault / ".obsidian" / "hidden.md").write_text("[[Ideas]]", encoding="utf-8")
(vault / "Ideas.md").write_text("Build Loki. [[Projects/Loki]] #ai", encoding="utf-8")
(vault / "Projects").mkdir()
(vault / "Projects" / "Loki.md").write_text("The conductor. [[Ideas#Top]] #ai", encoding="utf-8")
(vault / "Lonely.md").write_text("no links", encoding="utf-8")
outside = TMP / "secret.txt"
outside.write_text("do not leak", encoding="utf-8")
roster = [{"role": "research", "ready": True, "via": "perplexity", "why": ""}]
skills = [("Loki", "loki-testing", REPO / "skills" / "loki-testing" / "SKILL.md")]
graph = brain.build(data, ws, real, roster, skills, str(vault))
nodes = {n["id"]: n for n in graph["nodes"]}
labels = {n["label"]: n for n in graph["nodes"]}
edges = {tuple(e) for e in graph["edges"]}


def linked(a, b):
    ia, ib = labels[a]["id"], labels[b]["id"]
    return (ia, ib) in edges or (ib, ia) in edges


check("Loki is the centre", "loki" in nodes and nodes["loki"]["degree"] > 5)
def linked_ids(a, b):
    return (a, b) in edges or (b, a) in edges


check("roles hang off Loki and link their capabilities",
      linked_ids("loki", "role:research") and linked_ids("role:research", "cap:perplexity"))
check("memory facts are nodes", "prefers small PRs" in labels and linked("Memory", "prefers small PRs"))
check("viking://memory notes and their #tags are mapped", "people" in labels and linked("people", "#friends"))
check("skills group under their library", linked_ids("hub:skills", "lib:Loki")
      and any(linked_ids("lib:Loki", n["id"]) for n in graph["nodes"] if n["label"] == "loki-testing"))
check("jobs link to the backend capability", linked("add tests", "herdr"))
check("docs [[wikilinks]] become edges", linked("a", "b"))
check("relative markdown links become edges", linked("a", "c"))
check("vault notes link by [[path]] and [[name#heading]]", linked("Ideas", "Loki") or ("Ideas" in labels and "Projects/Loki.md" in str([n["detail"] for n in graph["nodes"]])))
check("shared #tags connect vault notes", linked("Ideas", "#ai"))
check("an unlinked note hangs off its vault", linked(vault.name, "Lonely"))
check(".obsidian internals are skipped", "hidden" not in labels)
check("groups are labelled for the legend", graph["groups"].get("vault") == "Your vault")
note_id = labels["Ideas"]["id"]
check("a listed note's text can be read", "Build Loki" in brain.note_text(graph, note_id))
check("anything not listed cannot be read", brain.note_text(graph, "vault:" + "0" * 12) is None)
check("the public graph does not expose file paths", "_files" not in brain.public(graph)
      and str(outside) not in json.dumps(brain.public(graph)))
try:
    brain.save_vault(data, str(TMP / "nope"))
    ok = False
except ValueError:
    ok = True
check("linking a missing vault folder is refused", ok)
check("a vault folder is remembered", brain.save_vault(data, str(vault)) == str(vault.resolve())
      and brain.load_settings(data)["vault"] == str(vault.resolve()))

import loki_bridge  # noqa: E402

agent = types.SimpleNamespace(DATA_DIR=data, WORKSPACE=ws, CAPABILITIES=real,
                              CONDUCTOR=types.SimpleNamespace(roster=lambda: roster),
                              _skill_entries=lambda: skills)
state = types.SimpleNamespace(agent=agent, brain={}, project=ws, jobs=None)
code, body = loki_bridge.brain_graph(state)
check("GET /brain returns the graph with the linked vault", code == 200 and body["vault"] == str(vault.resolve())
      and any(n["label"] == "Ideas" for n in body["nodes"]))
code, body = loki_bridge.brain_note(state, {"id": [note_id]})
check("GET /brain/note serves a mapped note", code == 200 and "Build Loki" in body["text"])
check("GET /brain/note refuses an unmapped id", loki_bridge.brain_note(state, {"id": ["../../etc"]})[0] == 404)
check("POST /brain/vault refuses a bad folder", loki_bridge.brain_vault(state, {"path": "/no/such/dir"})[0] == 400)
ui = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("the Brain tab is gone (knowledge stays reachable over the API)",
      "brain" not in ui.lower() and not (REPO / "app" / "ui" / "brain.js").exists())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
