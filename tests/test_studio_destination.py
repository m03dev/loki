"""LOKI Studio's "Where is this going?", its LOKI settings panel, the Studio tab, the Godot tab and the mode bar.

Offline, < 60 s, no `openai` needed (unlike tests/test_studio.py). Fake gh/git runners record every command line:
  1. destination: owner vs non-owner defaults, the guard (a non-owner never ships to m03dev/loki), argv-only commands,
     fork / new app / local set-up, the stored choice, a Studio session that remembers it, Ship it refused / allowed
  2. Studio's server: /api/destination, /api/loki/settings (fake LOKI bridge), roadmap lines in docs/EVOLVE.md;
     every /api path studio.js requests is a route (no 404s)
  3. the Studio tab: POST /studio/embed starts Studio's server once
  4. the Godot tab: COOP/COEP headers, the checksum-checked download, traversal refused, project zip round trip
  5. the mode bar in headless Chromium (when Playwright is here): the modes, Ctrl+1..5, state kept across switches
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "studio"))
sys.path.insert(0, str(REPO / "engine"))
PASS, FAIL = [], []
T0 = time.time()


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -> %s" % (detail,)))


TMP = Path(tempfile.mkdtemp(prefix="loki-dest-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_PROJECTS_DIR"] = str(TMP / "projects")
os.environ["LOKI_STUDIO_PIN_REFRESH"] = "0"

import studio_destination as D  # noqa: E402


class FakeRunner:
    """Answers gh and records every argv; git commands really run (on temp repos) unless `fake_git`."""

    def __init__(self, user="", fake_git=False, fail=()):
        self.user, self.fake_git, self.fail, self.calls = user, fake_git, set(fail), []

    def __call__(self, argv, cwd=None, timeout=60.0):
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), argv
        self.calls.append(list(argv))
        if argv[0] == "gh":
            if " ".join(argv[1:3]) in self.fail:
                return 1, "gh said no"
            if argv[1:3] == ["api", "user"]:
                return (0, self.user + "\n") if self.user else (1, "not logged in")
            if argv[1:3] == ["auth", "status"]:
                return (0, "Logged in to github.com account %s" % self.user) if self.user else (1, "not logged in")
            return 0, "ok"
        if self.fake_git:
            return 0, ""
        return D.run(argv, timeout=timeout)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)


def make_loki(path: Path, origin="https://github.com/m03dev/loki.git") -> Path:
    path.mkdir(parents=True)
    (path / "engine").mkdir()
    (path / "engine" / "safe_exec.py").write_text("# LOKI's runner\n", encoding="utf-8")
    (path / "engine" / "core.py").write_text("X = 1\n", encoding="utf-8")
    (path / "docs").mkdir()
    (path / "docs" / "EVOLVE.md").write_text("# EVOLVE\n\n## Roadmap\n\n- [ ] E15 Ground - fix it\n- [x] E3 Subagents\n", encoding="utf-8")
    (path / "LICENSE").write_text("GNU AFFERO GENERAL PUBLIC LICENSE\n", encoding="utf-8")
    for args in (("init", "-q"), ("symbolic-ref", "HEAD", "refs/heads/master"), ("add", "-A"),
                 ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "loki")):
        git(path, *args)
    if origin:
        git(path, "remote", "add", "origin", origin)
    return path


# ------------------------------------------------------------------ 1. destination logic
print("== 1. where is this going")
check("owner gets 'Improve LOKI itself' by default", D.default_kind("m03dev") == "loki" and D.default_kind("M03DEV") == "loki")
check("anyone else (or nobody signed in) gets 'My own LOKI'", D.default_kind("alice") == "fork" and D.default_kind("") == "fork")
check("slug reads https and ssh GitHub URLs", D.slug("https://github.com/m03dev/loki.git") == "m03dev/loki"
      and D.slug("git@github.com:Alice/Loki") == "alice/loki" and D.slug("/tmp/x") == "")
g = D.guard
check("guard: the owner ships LOKI to m03dev/loki", g("loki", "m03dev/loki", "m03dev") == "")
check("guard: a non-owner is refused for 'Improve LOKI itself'", "Only m03dev" in g("loki", "m03dev/loki", "alice"))
check("guard: a fork/app that still points at m03dev/loki is refused (owner or not)",
      all(g(k, "m03dev/loki", u) for k in ("fork", "app", "local") for u in ("alice", "m03dev", "")))
check("guard: a fork to the user's own repo ships", g("fork", "alice/loki", "alice") == "")
check("guard: no choice yet is refused", g("", "alice/loki", "alice") != "")
argv = D.repo_create_argv("my-agent", "private", Path("/x/my agent"))
check("gh repo create is an argv list (no shell), private by default, the path one argument",
      argv[:5] == ["gh", "repo", "create", "my-agent", "--private"] and "/x/my agent" in argv and "--push" in argv, argv)
check("...public when asked", "--public" in D.repo_create_argv("a", "public", Path("p")))
for bad in ("a;rm -rf /", "../x", "", "-flag", "a b"):
    try:
        D.repo_create_argv(bad, "private", Path("p"))
        ok = False
    except ValueError:
        ok = True
    check("a bad name is refused before any command: %r" % bad, ok)
try:
    D.run("git status")
    check("run() refuses a shell string", False)
except ValueError:
    check("run() refuses a shell string", True)
check("run() never uses a shell", "shell=False" in (REPO / "studio" / "studio_destination.py").read_text(encoding="utf-8")
      and "shell=True" not in (REPO / "studio" / "studio_destination.py").read_text(encoding="utf-8"))

loki = make_loki(TMP / "loki")
home = TMP / "home"
r = FakeRunner("alice")
res = D.choose(home, loki, "loki", runner=r)
check("a non-owner cannot choose 'Improve LOKI itself'", not res["ok"] and "Only m03dev" in res["error"], res)
check("...and nothing was stored", D.load(home) == {})
res = D.choose(home, loki, "fork", runner=r)
check("'My own LOKI' with gh signed in: forks and stores the choice", res["ok"] and D.load(home)["kind"] == "fork", res)
check("...gh repo fork m03dev/loki was run as argv", ["gh", "repo", "fork", "m03dev/loki", "--clone=false", "--remote=false"] in r.calls, r.calls)
check("...origin is the user's fork, upstream is m03dev/loki",
      D.origin(loki) == "alice/loki" and "m03dev/loki" in git(loki, "remote", "get-url", "upstream").stdout)
check("...and now the guard lets the fork ship, but never to m03dev/loki",
      g("fork", D.origin(loki), "alice") == "" and g("fork", "m03dev/loki", "alice"))
res = D.choose(TMP / "home2", make_loki(TMP / "loki2"), "fork", runner=FakeRunner(""))
check("'My own LOKI' without gh: says how (gh auth login, or by hand)", not res["ok"] and "gh auth login" in res.get("how", ""), res)

r = FakeRunner("alice")
res = D.choose(TMP / "home3", loki, "app", name="my-agent", runner=r, base=TMP / "projects")
app = TMP / "projects" / "my-agent"
check("'A new app from LOKI': a new folder with the skeleton", res["ok"] and all((app / f).is_file() for f in
      ("README.md", "NOTICE.md", "AGENTS.md", "LICENSE", "app/main.py", "tests/test_app.py", "tools/ship.py", "engine/safe_exec.py")), res)
check("...a git repo with one commit on main", git(app, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
      and git(app, "rev-list", "--count", "HEAD").stdout.strip() == "1")
check("...gh repo create <name> --private --source <folder> as argv", D.repo_create_argv("my-agent", "private", app) in r.calls, r.calls)
check("...the stored choice points at the new folder and the user's repo",
      D.load(TMP / "home3").get("path") == str(app) and D.load(TMP / "home3").get("repo") == "alice/my-agent")
p = subprocess.run([sys.executable, str(app / "tools" / "ship.py"), "--check"], capture_output=True, text=True, timeout=30, cwd=str(app))
check("...the new app's own tests pass (engine copy is usable as a library)", p.returncode == 0, p.stdout + p.stderr)
res = D.choose(TMP / "home3", loki, "app", name="my-agent", runner=r, base=TMP / "projects")
check("...a second app with the same name is refused", not res["ok"] and "already exists" in res["error"])
check("...bad names are refused", not D.choose(TMP / "h", loki, "app", name="../evil", runner=r, base=TMP / "projects")["ok"])

res = D.choose(TMP / "home4", loki, "local", name="mine", runner=FakeRunner(""), base=TMP / "projects")
check("'Just this computer': a local clone with no remote", res["ok"] and (TMP / "projects" / "mine" / ".git").exists()
      and git(TMP / "projects" / "mine", "remote").stdout.strip() == "", res)

# a Studio session remembers its destination; Ship it goes through the guard
import studio_core  # noqa: E402


def fake_ship(tree, msg):
    SHIPPED.append((str(tree), msg))
    return "shipped:\nok"


SHIPPED = []
own = make_loki(TMP / "owner-loki")
data = TMP / "sdata"
st = studio_core.Studio(repo=own, data=data, ship_runner=fake_ship, check_runner=lambda t, s: "ALL PASSED\n",
                        dest_runner=FakeRunner("m03dev"))
d = st.destination()
check("Studio for the owner: 'Improve LOKI itself' without asking", d["choice"].get("kind") == "loki" and d["is_owner"], d)
s = st.new("Fix a typo", start=False)
check("a session records where it goes", s.meta["destination"]["kind"] == "loki" and s.summary()["destination"]["kind"] == "loki")
out = st.ship(s.id, "fix", approved=True)
check("the owner's Ship it goes to tools/ship.py", out.startswith("shipped") and SHIPPED, out)

SHIPPED.clear()
st2 = studio_core.Studio(repo=make_loki(TMP / "alice-loki"), data=TMP / "sdata2", ship_runner=fake_ship,
                         check_runner=lambda t, s: "ALL PASSED\n", dest_runner=FakeRunner("alice"))
d2 = st2.destination()
check("Studio for a non-owner: nothing chosen yet, the default is 'My own LOKI'", not d2["chosen"] and d2["default"] == "fork"
      and not d2["can_improve_loki"], d2)
try:
    st2.new("Do a thing", start=False)
    check("a non-owner must choose before the first session", False)
except ValueError as exc:
    check("a non-owner must choose before the first session", "Where is this going" in str(exc))
# a non-owner session that somehow carries 'loki' (an old session file) is still refused
s2 = studio_core.Session(TMP / "sdata2" / "studio" / "sessions" / "x", {"id": "x", "kind": "loki", "status": "idle", "branch": "b",
                         "worktree": str(TMP / "alice-loki"), "root": str(TMP / "alice-loki"), "messages": [],
                         "destination": {"kind": "loki"}})
st2.sessions["x"] = s2
out = st2.ship("x", "msg", approved=True)
check("Ship it refuses a non-owner's work to m03dev/loki - nothing is run", out.startswith("NOT shipped") and "Only m03dev" in out
      and not SHIPPED, out)

st3 = studio_core.Studio(repo=TMP / "loki", data=TMP / "home3data", ship_runner=fake_ship,
                         check_runner=lambda t, s: "ALL PASSED\n", dest_runner=FakeRunner("alice"))
D.save(st3.home, D.load(TMP / "home3"))
s3 = st3.new("Add a feature", start=False)
check("an app session's worktree is made from the NEW app's repo", s3.meta["base_repo"] == str(app)
      and (Path(s3.meta["worktree"]) / "app" / "main.py").is_file(), s3.meta.get("base_repo"))
(Path(s3.meta["worktree"]) / "app" / "feature.py").write_text("Y = 2\n", encoding="utf-8")
calls = FakeRunner("alice")
st3.dest_runner = calls
out = st3.ship(s3.id, "add a feature", approved=True)
check("Ship it for an app: tests, commit, merge into the app, push its origin - not ship.py",
      out.startswith("shipped") and not SHIPPED and (app / "app" / "feature.py").is_file(), out)

# ------------------------------------------------------------------ 2. Studio's server routes
print("== 2. Studio's server")
import studio_server  # noqa: E402
import studio_control  # noqa: E402
import urllib.request  # noqa: E402
import urllib.error  # noqa: E402


class FakeBridge:
    def __init__(self):
        self.posts = []

    def up(self):
        return True

    def bridge(self, method, path, body=None, timeout=8.0):
        if method == "POST":
            self.posts.append((path, body))
            return 200, {"ok": True}
        return 200, {"/providers": {"ok": True, "providers": [{"id": "nvidia", "name": "NVIDIA", "available": True, "enabled": True, "model": "m"}]},
                     "/settings/general": {"ok": True, "settings": {"LOKI_ALLOW_PAID": {"kind": "bool", "label": "Paid"},
                                                                    "TELEGRAM_BOT_TOKEN": {"kind": "secret", "label": "Bot"}},
                                           "values": {"LOKI_ALLOW_PAID": "0", "TELEGRAM_BOT_TOKEN": ""}},
                     "/capabilities/manifests": {"ok": True, "capabilities": [{"name": "cad", "status": "enabled"}]},
                     "/evolve": {"ok": True, "items": []}}.get(path, {"ok": False})


fb = FakeBridge()
ov = studio_control.settings_overview(own, data, a=fb)
check("settings overview: providers, general (no secrets), capabilities, evolve",
      ov["providers"]["providers"][0]["id"] == "nvidia" and "TELEGRAM_BOT_TOKEN" not in ov["general"]["settings"]
      and "TELEGRAM_BOT_TOKEN" not in ov["general"]["values"] and ov["capabilities"]["capabilities"] and ov["evolve"]["ok"], ov)
check("a provider on/off goes to /providers/enable",
      studio_control.settings_change("provider_enable", {"id": "groq", "on": False}, own, data, a=fb)["ok"]
      and fb.posts[-1] == ("/providers/enable", {"id": "groq", "on": False, "model": ""}))
check("a model choice goes to /providers/model", studio_control.settings_change("provider_model", {"id": "nvidia", "model": "x"}, own, data, a=fb)["ok"]
      and fb.posts[-1][0] == "/providers/model")
check("a General value goes to /settings/general", studio_control.settings_change("general", {"key": "LOKI_ALLOW_PAID", "value": "1"}, own, data, a=fb)["ok"]
      and fb.posts[-1] == ("/settings/general", {"values": {"LOKI_ALLOW_PAID": "1"}}))
n = len(fb.posts)
check("a secret is refused and never sent", not studio_control.settings_change("general", {"key": "TELEGRAM_BOT_TOKEN", "value": "x"}, own, data, a=fb)["ok"]
      and not studio_control.settings_change("general", {"key": "NVIDIA_API_KEY", "value": "x"}, own, data, a=fb)["ok"] and len(fb.posts) == n)
check("a capability toggle goes to /capabilities/enable", studio_control.settings_change("capability", {"name": "cad", "on": False}, own, data, a=fb)["ok"]
      and fb.posts[-1] == ("/capabilities/enable", {"name": "cad", "enabled": False}))
check("an evolve idea goes to /evolve/idea", studio_control.settings_change("evolve_idea", {"text": "make it faster please"}, own, data, a=fb)["ok"]
      and fb.posts[-1][0] == "/evolve/idea")
res = studio_control.settings_change("roadmap", {"text": "Make the island bigger and greener"}, own, data, a=fb)
ev = (own / "docs" / "EVOLVE.md").read_text(encoding="utf-8")
check("a task line goes into docs/EVOLVE.md's Roadmap with the next E number", res["ok"] and res["id"] == "E16"
      and "## Roadmap\n\n- [ ] E16 Make the island bigger and greener\n- [ ] E15" in ev, (res, ev))
check("unknown changes are refused", not studio_control.settings_change("rm", {}, own, data, a=fb)["ok"])

srv = studio_server.StudioServer(st, port=0)
srv.start()


def http(method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (srv.port, path), method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + srv.token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw or b"{}") if path.startswith("/api/") else {}), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}"), dict(exc.headers)


code, body, _ = http("GET", "/api/destination")
check("GET /api/destination", code == 200 and body["choice"]["kind"] == "loki" and body["gh_user"] == "m03dev", body)
code, body, _ = http("POST", "/api/destination", {"kind": "local", "name": "x"})
check("POST /api/destination needs confirm", code == 400)
code, body, hdr = http("GET", "/")
check("Studio may be framed by LOKI's window (frame-ancestors loopback), scripts still 'self' only",
      "frame-ancestors 'self' http://127.0.0.1:*" in hdr.get("Content-Security-Policy", "")
      and "script-src 'self';" in hdr.get("Content-Security-Policy", ""), hdr.get("Content-Security-Policy"))
code, body, _ = http("POST", "/api/loki/settings", {"what": "roadmap", "args": {"text": "abc defgh ijk"}})
check("POST /api/loki/settings needs confirm", code == 400)
# every path studio.js asks for is a route of Studio's server (the owner's "error 404 http not found")
js = (REPO / "studio" / "ui" / "studio.js").read_text(encoding="utf-8")
paths = sorted(set(re.findall(r'"(/api/[a-z_/]+)', js)))
missing = []
for pth in paths:
    for method in ("GET", "POST"):
        try:
            c, b = (srv.get(pth, {}) if method == "GET" else srv.post(pth, {}))
        except KeyError:
            c, b = 404, {"error": "session"}   # a real route, just no such session
        except Exception:  # noqa: BLE001 - a real route that wanted arguments
            c, b = 400, {}
        if c != 404 or "unknown endpoint" not in str(b.get("error", "")):
            break
    else:
        missing.append(pth)
check("every /api path studio.js requests is served (%d paths)" % len(paths), not missing and len(paths) > 20, missing)
srv.stop()

# ------------------------------------------------------------------ 3. the Studio tab
print("== 3. the Studio tab")
import studio_api  # noqa: E402
spawned = []
clock = [1000.0]
studio_api._EMBED["t"] = 0.0
r1 = studio_api.embed(TMP / "embed-data", popen=lambda argv, **kw: spawned.append(argv), clock=lambda: clock[0])
clock[0] += 3
r2 = studio_api.embed(TMP / "embed-data", popen=lambda argv, **kw: spawned.append(argv), clock=lambda: clock[0])
check("the Studio tab starts Studio's server once (headless, no window) while it comes up",
      r1.get("started") and r2.get("starting") and not r2.get("started") and len(spawned) == 1 and "--headless" in spawned[0], (r1, r2, spawned))
check(".../studio/embed is an engine route", studio_api.handles("POST", "/studio/embed"))
check("studio_app.py has --headless (serve only)", "--headless" in (REPO / "studio" / "studio_app.py").read_text(encoding="utf-8"))

# ------------------------------------------------------------------ 4. the Godot tab
print("== 4. the Godot tab")
import godot_web  # noqa: E402
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as zf:
    zf.writestr("godot.editor.html", "<html>editor</html>")
    zf.writestr("godot.editor.wasm", b"\0asm")
    zf.writestr("../../evil.js", "x")
    zf.writestr("/abs.js", "x")
    zf.writestr("sub/../../up.html", "x")
    zf.writestr("run.sh", "x")
blob = buf.getvalue()


class Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


gdata = TMP / "gdata"
bad = godot_web.install(gdata, opener=lambda req, timeout=0: Resp(blob), sha512="0" * 128)
check("a download whose checksum does not match is refused and nothing is kept",
      not bad["ok"] and "checksum" in bad["error"] and not godot_web.editor_dir(gdata).exists(), bad)
good = godot_web.install(gdata, opener=lambda req, timeout=0: Resp(blob), sha512=hashlib.sha512(blob).hexdigest())
files = sorted(p.name for p in godot_web.editor_dir(gdata).iterdir())
check("a matching download is unpacked; traversal / absolute / odd files refused",
      good["ok"] and files == ["godot.editor.html", "godot.editor.wasm", "installed.json"]
      and not (TMP / "evil.js").exists() and not (gdata / "addons" / "up.html").exists(), (good, files))
check("the pinned checksum is the release's SHA-512", len(godot_web.SHA512) == 128 and godot_web.VERSION in godot_web.URL)
check("static: traversal refused", godot_web.static_file("/godot-editor/app/../installed.json", gdata) is None
      and godot_web.static_file("/godot-editor/app/..%2Fx.js", gdata) is None
      and godot_web.static_file("/godot-editor/app/installed.json", gdata) is not None)
h = godot_web.static_headers(godot_web.editor_dir(gdata) / "godot.editor.html")
check("the editor page has COOP same-origin + COEP require-corp", h.get("Cross-Origin-Opener-Policy") == "same-origin"
      and h.get("Cross-Origin-Embedder-Policy") == "require-corp" and "wasm-unsafe-eval" in h.get("Content-Security-Policy", ""), h)
check(".wasm is served as application/wasm with COEP", godot_web.static_headers(Path("a.wasm"))["Content-Type"] == "application/wasm"
      and godot_web.static_headers(Path("a.wasm"))["Cross-Origin-Embedder-Policy"] == "require-corp")


class FakeHandler:
    """Just enough of loki_bridge's handler for godot_web.http."""

    def __init__(self, path, host="127.0.0.1:8767", auth=True):
        self.path, self.headers, self.auth = path, {"Host": host, "Content-Length": "0"}, auth
        self.code, self.sent, self.wfile = 0, {}, io.BytesIO()

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        self.sent[k] = v

    def end_headers(self):
        pass

    def _authorized(self):
        if not self.auth:
            self.code = 401
        return self.auth

    def _read_json(self):
        return {}


hh = FakeHandler("/godot-editor/app/godot.editor.html", auth=False)
godot_web.http(hh, "GET", ("127.0.0.1:8767",), gdata)
check("GET /godot-editor/app/godot.editor.html over the bridge handler: 200 with COOP/COEP (no token needed)",
      hh.code == 200 and hh.sent.get("Cross-Origin-Embedder-Policy") == "require-corp" and b"editor" in hh.wfile.getvalue(), (hh.code, hh.sent))
hh = FakeHandler("/godot-editor/app/godot.editor.html", host="evil.com")
godot_web.http(hh, "GET", ("127.0.0.1:8767",), gdata)
check("...a foreign Host is refused", hh.code == 403)
hh = FakeHandler("/godot-editor/status", auth=False)
godot_web.http(hh, "GET", ("127.0.0.1:8767",), gdata)
check("...status needs LOKI's token", hh.code == 401)
proj = TMP / "projects" / "game1"
(proj / "scenes").mkdir(parents=True)
(proj / "project.godot").write_text("[application]\nconfig/name=\"game1\"\n", encoding="utf-8")
(proj / "scenes" / "main.tscn").write_text("[gd_scene]\n", encoding="utf-8")
(proj / ".godot").mkdir()
(proj / ".godot" / "cache").write_text("x", encoding="utf-8")
names = zipfile.ZipFile(io.BytesIO(godot_web.project_zip("game1"))).namelist()
check("project.zip packs the project (not .godot/)", "game1/project.godot" in names and "game1/scenes/main.tscn" in names
      and not any(".godot/" in n for n in names), names)
back = TMP / "game1-src.zip"
with zipfile.ZipFile(back, "w") as zf:
    zf.writestr("game1/scenes/new.tscn", "[gd_scene new]\n")
    zf.writestr("game1/../../escape.txt", "x")
res = godot_web.import_back("game1", str(back))
check("bringing a project back writes inside the folder only", res["ok"] and (proj / "scenes" / "new.tscn").is_file()
      and not (TMP / "escape.txt").exists() and res["skipped"] == 1, res)
try:
    godot_web.project_zip("../loki")
    check("an unknown project name is refused", False)
except KeyError:
    check("an unknown project name is refused", True)
src = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the engine routes /godot-editor/* (GET and POST) to godot_web", src.count('startswith("/godot-editor/")') == 2)

# ------------------------------------------------------------------ 5. the mode bar (DOM)
print("== 5. the mode bar")
index = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
mb = (REPO / "app" / "ui" / "modebar.js").read_text(encoding="utf-8")
check("index.html loads modebar.js", '<script src="/ui/modebar.js" defer></script>' in index)
check("modebar.js has the five modes", all('id: "%s"' % m in mb for m in ("loki", "studio", "godot", "world", "forge")))
try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None
chromium = next((p for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if p and Path(p).exists()), "")
if sync_playwright is None or time.time() - T0 > 40:
    print("  SKIP the DOM check: no Playwright here (or out of time)")
else:
    ui = REPO / "app" / "ui"
    posts = []

    def route(r):
        pth = r.request.url.split("8897", 1)[1].split("?")[0].split("#")[0]
        if pth == "/":
            return r.fulfill(path=str(ui / "index.html"))
        if pth.startswith("/ui/") and (ui / pth[4:]).is_file():
            return r.fulfill(path=str(ui / pth[4:]))
        if pth.endswith(".wasm") and (ui / (pth[4:] + ".gz")).is_file():   # LOKI World's engine (the bridge sends the .gz)
            import gzip  # pylint: disable=import-outside-toplevel
            return r.fulfill(body=gzip.decompress((ui / (pth[4:] + ".gz")).read_bytes()), headers={"Content-Type": "application/wasm"})
        if r.request.method == "POST":
            posts.append(pth)
        if pth == "/studio/embed":
            return r.fulfill(json={"ok": True, "running": True, "url": "about:blank#studio"})
        if pth == "/godot-editor/status":
            return r.fulfill(json={"ok": True, "installed": False, "projects": [{"name": "g", "label": "g"}], "native": "", "flow": "x",
                                   "projects_dir": "p", "job": {"state": "idle"}})
        return r.fulfill(json={"ok": True})

    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(**({"executable_path": chromium} if chromium else {}))
            page = b.new_page(viewport={"width": 1240, "height": 820})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.route("http://127.0.0.1:8897/**", route)
            page.goto("http://127.0.0.1:8897/#token=t")
            page.wait_for_selector("#modebar .modebar-tab", timeout=15000)
            tabs = page.eval_on_selector_all("#modebar .modebar-tab", "els => els.map(e => e.dataset.mode)")
            check("the mode bar shows LOKI, Studio, Godot, World, Forge", tabs == ["loki", "studio", "godot", "world", "forge"], tabs)
            page.evaluate("document.getElementById('prompt').value = 'half-typed message'")
            page.keyboard.press("Control+2")
            page.wait_for_timeout(500)
            check("Ctrl+2 switches to Studio and frames it", page.evaluate("document.body.dataset.mode") == "studio"
                  and page.evaluate("!!document.querySelector('[data-mode-pane=studio] iframe[src*=studio]')") and "/studio/embed" in posts)
            page.keyboard.press("Control+3")
            page.wait_for_timeout(400)
            check("Ctrl+3 switches to Godot (the install button when the editor is missing)",
                  page.evaluate("document.body.dataset.mode") == "godot" and page.is_visible("[data-mode-pane=godot] select"))
            page.click("#mode-loki")
            page.keyboard.press("Control+2")
            page.keyboard.press("Control+1")
            page.wait_for_timeout(300)
            check("switching keeps each mode's state (the message, Studio's one frame, one embed call)",
                  page.evaluate("document.getElementById('prompt').value") == "half-typed message" and posts.count("/studio/embed") == 1
                  and page.evaluate("document.querySelectorAll('[data-mode-pane=studio] iframe').length") == 1, posts)
            check("aria-selected follows the mode", page.get_attribute("#mode-loki", "aria-selected") == "true")
            page.keyboard.press("Control+4")
            page.wait_for_timeout(300)
            check("Ctrl+4: World shows LOKI World's panel in its tab", page.evaluate(
                "!!document.querySelector('[data-mode-pane=world] [data-panel=world]:not([hidden])')"))
            page.keyboard.press("Control+5")
            page.wait_for_timeout(500)
            check("Ctrl+5: Forge opens forge.js (or says it is coming); World's panel went back home",
                  page.evaluate("document.body.dataset.mode") == "forge" and page.evaluate(
                      "!!document.querySelector('#settings [data-panel=world]') || !document.querySelector('[data-mode-pane=world] [data-panel=world]')"))
            page.keyboard.press("Control+1")
            check("no script errors", not errs, errs[:3])
            b.close()
    except Exception as exc:  # noqa: BLE001
        check("the mode bar in headless Chromium", False, exc)

check("this suite stays under 60 s", time.time() - T0 < 60, time.time() - T0)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
