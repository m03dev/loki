"""One-click install (session 30): release builds, the secret scan, the feed, the bundled-Python
launcher, background updates, the native launcher, Send feedback, faster starts, the tour's 3 ways.

Offline, under a minute (the owner's rule):
  * `make_release.py --friends` builds from `git archive HEAD` into a temp dir: nothing from
    harness_data, no .env, no tests, no private keys inside; the zips are listed in FRIENDS.txt
  * the secret scan refuses key-like files and strings (real-looking keys are made up at run time,
    so this file holds none) and lets placeholders through
  * the feed: GitHub Releases of m03dev/loki by default, absolute asset URLs, https-only redirects
  * release_update.prepare() downloads + checks in the background, apply_ready() switches at start
  * loki_launch.py makes <data>/.venv from a bundled runtime, offline, once; again after a move
  * the Rust launcher (when cargo is here) starts the bundled Python on loki_launch.py
  * feedback zips carry no keys, chats or .env; the issue / email links are right
  * `import loki` no longer imports the MCP client; the app opens its window before the engine
  * headless Chromium (when Playwright is here): the tour's "Connect an account" way starts no
    download; Settings > General > Send feedback posts a bundle request

    python tests/test_install.py
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

T0 = time.monotonic()
REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path[:0] = [str(REPO / "engine"), str(REPO / "tools"), str(REPO / "packaging" / "installer"), str(REPO / "app")]
PASS: list = []
FAIL: list = []
TMP = Path(tempfile.mkdtemp(prefix="loki-install-test-"))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:900],)), flush=True)


def section(title):
    print("\n== %s  (%.0fs)" % (title, time.monotonic() - T0), flush=True)


def clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LOKI_", "HARNESS_"))}
    env.update(extra)
    return env


import make_release  # noqa: E402
import secret_scan  # noqa: E402
import release_update  # noqa: E402

# ------------------------------------------------------------------ the friends build
section("make_release --friends: from git archive HEAD, scanned")
dist = TMP / "dist"
proc = subprocess.run([sys.executable, str(REPO / "tools" / "make_release.py"), "--friends", "--dist", str(dist), "--version", "9.9.1"],
                      capture_output=True, text=True, timeout=50, env=clean_env())
check("the friends build succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-800:])
portable = sorted(dist.glob("Loki-9.9.1-*-portable.zip"))
update_zip = dist / "release" / "Loki-9.9.1.zip"
check("it makes this OS's portable zip and the update zip", len(portable) == 1 and update_zip.is_file(), [p.name for p in dist.glob("*")])
check("FRIENDS.txt says what to send and that the scan is clean", (dist / "FRIENDS.txt").is_file()
      and "Secret scan: clean" in (dist / "FRIENDS.txt").read_text(encoding="utf-8"))
names = []
if portable:
    with zipfile.ZipFile(portable[0]) as zf:
        names = zf.namelist()
with zipfile.ZipFile(update_zip) as zf:
    unames = zf.namelist()
allnames = names + unames


def bad_name(n: str) -> bool:
    parts = n.split("/")
    base = parts[-1]
    return ("harness_data" in parts or (base == ".env") or (base.endswith(".env") and not base.endswith(".env.example"))
            or "tests" in parts[:3] or base.endswith((".pfx", ".p12")) or base in ("engine.token", "loki_conversations.json"))


check("no harness_data, .env, tests, tokens or chats inside", allnames and not [n for n in allnames if bad_name(n)],
      [n for n in allnames if bad_name(n)][:5])
check("the seed carries the launcher, the window and the help", any(n.endswith("app/loki_app.py") for n in names)
      and any(n.endswith("app/ui/index.html") for n in names) and any(n.endswith("loki_launch.py") for n in names))
check("only tracked files: no untracked scratch file of this run", not any("loki-install-test" in n for n in allnames))
seed_dir = dist / "release" / "seed"
info = json.loads((seed_dir / "RELEASE.json").read_text(encoding="utf-8"))
check("RELEASE.json points at LOKI's GitHub Releases feed", info.get("feed") == release_update.DEFAULT_FEED, info)
check("the seed passes the secret scan on its own", not secret_scan.scan(seed_dir), secret_scan.scan(seed_dir)[:3])
with zipfile.ZipFile(update_zip) as zf:
    pem = [n for n in zf.namelist() if n.endswith(".pem")]
    texts = {n: zf.read(n).decode("utf-8", "ignore") for n in pem}
check("the only key file inside is the PUBLIC release key", all("PRIVATE KEY" not in t for t in texts.values()) and
      all(n.endswith("keys/loki_public.pem") for n in pem), pem)
man = json.loads((dist / "release" / "manifest.json").read_text(encoding="utf-8"))
check("the manifest has the zip's sha256", man["sha256"] == hashlib.sha256(update_zip.read_bytes()).hexdigest())

# ------------------------------------------------------------------ the secret scan
section("the secret scan refuses anything key-like")
fake = TMP / "fake-tree"
(fake / "app").mkdir(parents=True)
(fake / "app" / "loki_app.py").write_text("print('hi')\n", encoding="utf-8")
(fake / "app" / "notes.md").write_text("Paste your key: sk-or-v1-... or <your key> or gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n", encoding="utf-8")
check("placeholders are fine", not secret_scan.scan(fake), secret_scan.scan(fake))
real_or = "sk-or-v1-" + secrets.token_hex(32)
real_nv = "nvapi-" + secrets.token_urlsafe(48)
real_gh = "ghp_" + "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789") for _ in range(36))
for name, text, what in (("config.py", "KEY = '%s'\n" % real_or, "OpenRouter key"), ("x.json", '{"k": "%s"}' % real_nv, "NVIDIA key"),
                         ("y.txt", "token %s\n" % real_gh, "GitHub token")):
    (fake / "app" / name).write_text(text, encoding="utf-8")
    found = secret_scan.scan(fake)
    check("a real-looking %s is found" % what, any(f["what"] == what and f["path"] == "app/" + name for f in found), found)
    (fake / "app" / name).unlink()
(fake / ".env").write_text("GROQ_API_KEY=abc\n", encoding="utf-8")
(fake / "harness_data").mkdir()
(fake / "harness_data" / "memory.json").write_text("{}", encoding="utf-8")
(fake / "app" / "signing.pem").write_text("-----BEGIN " + "PRIVATE KEY-----\nMIIE\n-----END " + "PRIVATE KEY-----\n", encoding="utf-8")
found = {f["path"] for f in secret_scan.scan(fake)}
check(".env, harness_data/ and a private key file are refused", {".env", "harness_data/memory.json", "app/signing.pem"} <= found, found)
try:
    make_release.build(fake, TMP / "refused", "0.0.1", "", "")
    refused = False
except make_release.SecretFound as exc:
    refused = "refusing to package" in str(exc)
check("make_release.build refuses to package them", refused and not (TMP / "refused" / "Loki-0.0.1.zip").exists())
cli = subprocess.run([sys.executable, str(REPO / "tools" / "secret_scan.py"), str(fake)], capture_output=True, text=True, timeout=20)
check("tools/secret_scan.py exits 1 and lists them", cli.returncode == 1 and ".env" in cli.stdout, cli.stdout[-300:])
check("the release refuses to scan nothing away: tests are not shipped, so their fake keys never are",
      not make_release.wanted("tests/test_channels.py") and make_release.wanted("engine/loki.py"))

# ------------------------------------------------------------------ feed + background updates
section("the feed: GitHub Releases, absolute assets, https only")
check("the default feed is m03dev/loki's latest release", release_update.DEFAULT_FEED == "https://github.com/m03dev/loki/releases/latest/download/manifest.json"
      and make_release.DEFAULT_FEED == release_update.DEFAULT_FEED)
r2 = make_release.build(REPO, TMP / "rel2", "9.9.2", make_release.DEFAULT_FEED, "", asset_base="https://github.com/m03dev/loki/releases/download/v9.9.2")
check("--asset-base makes the zip URL absolute (a tag's download folder)",
      r2["url"] == "https://github.com/m03dev/loki/releases/download/v9.9.2/Loki-9.9.2.zip", r2["url"])
red = release_update._HttpsOnlyRedirects()
try:
    red.redirect_request(None, None, 302, "Found", {}, "http://evil.example/manifest.json")
    downgrade = False
except Exception as exc:  # noqa: BLE001
    downgrade = "https" in str(exc)
check("a redirect away from https is refused", downgrade)

rr = TMP / "rr"
os.environ["LOKI_RELEASE_ROOT"] = str(rr)
os.environ["LOKI_RELEASE_REQUIRE_SIG"] = "0"
for v in ("1.0.0",):
    t = rr / v
    (t / "app").mkdir(parents=True)
    (t / "app" / "loki_app.py").write_text("print('v')\n")
    (t / "RELEASE.json").write_text(json.dumps({"version": v}))
(rr / "state.json").write_text(json.dumps({"current": "1.0.0", "last_good": "1.0.0"}))
check("no feed in RELEASE.json -> LOKI's GitHub feed", release_update.feed_url() == release_update.DEFAULT_FEED)
os.environ["LOKI_RELEASE_FEED"] = "off"
check("LOKI_RELEASE_FEED=off turns updates off", release_update.feed_url() == "")
newtree = TMP / "newtree" / "Loki-1.0.1"
(newtree / "app").mkdir(parents=True)
(newtree / "app" / "loki_app.py").write_text("print('new')\n")
(newtree / "RELEASE.json").write_text(json.dumps({"version": "1.0.1"}))
zbytes = io.BytesIO()
with zipfile.ZipFile(zbytes, "w") as zf:
    for f in newtree.rglob("*"):
        if f.is_file():
            zf.write(f, "Loki-1.0.1/" + f.relative_to(newtree).as_posix())
(TMP / "feed").mkdir()
(TMP / "feed" / "Loki-1.0.1.zip").write_bytes(zbytes.getvalue())
(TMP / "feed" / "manifest.json").write_text(json.dumps({"version": "1.0.1", "url": "Loki-1.0.1.zip",
                                                        "sha256": hashlib.sha256(zbytes.getvalue()).hexdigest(), "size": 1}))
os.environ["LOKI_RELEASE_FEED"] = str(TMP / "feed" / "manifest.json")
real_preflight = release_update.preflight
release_update.preflight = lambda tree, timeout=0: (True, "pre-flight passed (test stand-in)")
got = release_update.prepare()
st = release_update.state()
check("prepare(): downloaded and checked, NOT switched", got.get("ready") == "1.0.1" and st.get("current") == "1.0.0"
      and (rr / "1.0.1" / "app" / "loki_app.py").is_file(), (got, st))
check("prepare() again: nothing to download", release_update.prepare().get("ready") == "1.0.1")
sw = release_update.apply_ready()
st = release_update.state()
check("apply_ready() at start: switched at once, on trial, no network", sw.get("updated") and sw.get("relaunch")
      and st.get("current") == "1.0.1" and st.get("pending") == "1.0.1" and st.get("last_good") == "1.0.0" and not st.get("ready"), (sw, st))
check("apply_ready() with nothing waiting does nothing", release_update.apply_ready().get("updated") is False)
release_update.preflight = real_preflight
for k in ("LOKI_RELEASE_ROOT", "LOKI_RELEASE_REQUIRE_SIG", "LOKI_RELEASE_FEED"):
    os.environ.pop(k, None)
app_src = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
check("an installed LOKI only switches at start (apply_ready), never downloads before its window",
      "release_update.apply_ready()" in app_src and "LOKI_UPDATE_AT_START" in app_src)
check("the engine's background check prepares the update", "prepare(info=info)" in (REPO / "engine" / "updater.py").read_text(encoding="utf-8"))

# ------------------------------------------------------------------ the launcher with a bundled runtime
section("loki_launch.py: the bundled Python, offline, once")
inst = TMP / "installed"
shutil.copytree(seed_dir, inst / "seed")
shutil.copy2(REPO / "packaging" / "installer" / "loki_launch.py", inst / "loki_launch.py")
rt = inst / "runtime" / "python"
if os.name == "nt":
    # a real relocatable copy of this Python, without its packages, tests and docs (a few seconds)
    shutil.copytree(Path(sys.base_prefix), rt, ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "Doc",
                                                                             "tcl", "Tools", "Scripts", "include", "idlelib", "turtledemo"))
else:
    (rt / "bin").mkdir(parents=True)
    os.symlink(sys.executable, rt / "bin" / "python3")
import loki_launch  # noqa: E402
(inst / "runtime" / "loki-requirements.sha256").write_text(loki_launch.requirements_digest(seed_dir), encoding="utf-8")
ldata = TMP / "ldata"
env = clean_env(LOKI_DATA=str(ldata), LOKI_NO_DIALOGS="1")
t1 = time.monotonic()
run1 = subprocess.run([sys.executable, str(inst / "loki_launch.py"), "--seed", str(inst / "seed"), "--check"], capture_output=True,
                      text=True, timeout=60, env=env)
first_s = time.monotonic() - t1
out1 = json.loads((run1.stdout.strip().splitlines() or ["{}"])[-1] or "{}") if run1.returncode == 0 else {}
check("first start: the seed is installed and a venv made from the bundled Python", run1.returncode == 0 and out1.get("bundled") is True
      and (ldata / ".venv" / "pyvenv.cfg").is_file(), (run1.returncode, run1.stderr[-500:]))
cfg = (ldata / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8") if (ldata / ".venv" / "pyvenv.cfg").is_file() else ""
check("the venv sees the bundled packages (include-system-site-packages)", "include-system-site-packages = true" in cfg, cfg)
check("no pip at first start: the bundle's packages are marked installed", "installing LOKI's Python packages" not in run1.stderr, run1.stderr[-300:])
check("first start set-up is quick (%.1fs)" % first_s, first_s < 20)
run2 = subprocess.run([sys.executable, str(inst / "loki_launch.py"), "--seed", str(inst / "seed"), "--check"], capture_output=True,
                      text=True, timeout=60, env=env)
check("second start: the venv is kept", run2.returncode == 0 and "making LOKI's Python environment" not in run2.stderr, run2.stderr[-300:])
moved = TMP / "moved"
shutil.move(str(inst), str(moved))
run3 = subprocess.run([sys.executable, str(moved / "loki_launch.py"), "--seed", str(moved / "seed"), "--check"], capture_output=True,
                      text=True, timeout=60, env=env)
check("the app was moved: the venv is made again from the new place", run3.returncode == 0 and "making LOKI's Python environment" in run3.stderr
      and str(moved) in (ldata / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8") + str(Path(os.path.realpath(moved))), run3.stderr[-300:])
check("no console windows on Windows: children get CREATE_NO_WINDOW", "0x08000000" in (REPO / "packaging" / "installer" / "loki_launch.py").read_text(encoding="utf-8"))

# ------------------------------------------------------------------ the native launcher
section("the Rust launcher (packaging/launcher)")
cargo = shutil.which("cargo")
if cargo and os.environ.get("LOKI_SUITE_NO_CARGO") != "1":
    target = TMP / "cargo-target"
    b = subprocess.run([cargo, "build", "--release", "--offline", "--manifest-path", str(REPO / "packaging" / "launcher" / "Cargo.toml")],
                       capture_output=True, text=True, timeout=45, env=dict(os.environ, CARGO_TARGET_DIR=str(target)))
    exe = target / "release" / ("Loki.exe" if os.name == "nt" else "Loki")
    check("it builds with the standard library only (no crates)", b.returncode == 0 and exe.is_file(), b.stderr[-500:])
    if exe.is_file():
        shutil.copy2(exe, moved / exe.name)
        pc = subprocess.run([str(moved / exe.name), "--print-command"], capture_output=True, text=True, timeout=10)
        check("it starts the bundled Python on loki_launch.py with the seed", "runtime" in pc.stdout and "loki_launch.py" in pc.stdout
              and "seed" in pc.stdout, pc.stdout[-300:])
else:
    print("  SKIP: no cargo here")
src = (REPO / "packaging" / "launcher" / "src" / "main.rs").read_text(encoding="utf-8")
check("Loki.exe never shows a console (windows subsystem + CREATE_NO_WINDOW)", 'windows_subsystem = "windows"' in src and "0x0800_0000" in src)

# ------------------------------------------------------------------ installers + CI
section("the installers carry Python; CI publishes GitHub Releases on a tag")
iss = (REPO / "packaging" / "windows" / "loki.iss").read_text(encoding="utf-8")
check("Windows installer: per-user, the bundled runtime and Loki.exe inside", "PrivilegesRequired=lowest" in iss
      and "{#RuntimeDir}" in iss and "Loki.exe" in iss)
dmg = (REPO / "tools" / "macos" / "make_dmg.sh").read_text(encoding="utf-8")
check("macOS app: bundled runtime, ad-hoc signed, a zip too; the script parses", "Resources/runtime" in dmg and "--sign -" in dmg
      and "ditto -c -k" in dmg and subprocess.run(["bash", "-n", str(REPO / "tools" / "macos" / "make_dmg.sh")]).returncode == 0)
check("the clean-Mac fallback never calls python3 (it would ask to install Xcode tools)",
      "never `python3` here" in dmg)
wf = (REPO / ".github" / "workflows" / "installers.yml").read_text(encoding="utf-8")
check("CI bundles Python on both OSes, smoke-tests the install, publishes on v* tags",
      wf.count("bundle_runtime.py") >= 2 and "/VERYSILENT" in wf and "gh release create" in wf and "--draft" in wf
      and "github.ref_type == 'tag'" in wf and 'tags: ["v*"]' in wf)
check("only the publish job may write to the repo", wf.count("contents: write") == 1 and "contents: read" in wf)
check("the signing key comes from a secret and is deleted after use", "secrets.LOKI_SIGNING_KEY_PEM" in wf and 'rm -f "$RUNNER_TEMP/loki_signing.pem"' in wf)
import bundle_runtime  # noqa: E402
check("bundle_runtime and the launcher agree on the requirements digest", bundle_runtime.requirements_digest(REPO) == loki_launch.requirements_digest(REPO))
fake_py = TMP / "fakepy" / "lib" / "python3.12"
(fake_py / "test").mkdir(parents=True)
(fake_py / "idlelib").mkdir()
(fake_py / "json").mkdir()
check("the bundle drops CPython's test suite and IDLE, keeps the rest", bundle_runtime.strip(TMP / "fakepy") == 2
      and (fake_py / "json").is_dir() and not (fake_py / "test").exists())

# ------------------------------------------------------------------ feedback
section("Send feedback: logs without keys or chats")
import feedback  # noqa: E402
fdata = TMP / "fdata"
(fdata / "app").mkdir(parents=True)
leak = "nvapi-" + secrets.token_urlsafe(48)
(fdata / "app" / "loki_app.log").write_text("started\nusing key %s\nAuthorization: Bearer abc.def.ghi123456\nmail me at someone@example.org\n"
                                            "GROQ_API_KEY=gsk_%s\nurl http://127.0.0.1:8767/#token=SECRETTOKEN123\n%s/Documents/x\n"
                                            % (leak, secrets.token_hex(24), str(Path.home())), encoding="utf-8")
(fdata / "app" / "engine.token").write_text("tok", encoding="utf-8")
(fdata / ".env").write_text("GROQ_API_KEY=x\n", encoding="utf-8")
(fdata / "app" / "loki_conversations.json").write_text('{"chat": "private"}', encoding="utf-8")
os.environ["LOKI_DATA"] = str(fdata)
bundle = feedback.make_bundle("It froze when I clicked Both. my key is " + leak, True, None, out_dir=TMP / "fb")
with zipfile.ZipFile(bundle["zip"]) as zf:
    fnames = zf.namelist()
    body = "\n".join(zf.read(n).decode("utf-8", "ignore") for n in fnames)
check("the bundle has system.json, the note and the app log", {"system.json", "note.txt", "logs/app-loki_app.log"} <= set(fnames), fnames)
check("no .env, token file or chats in it", not any(n.endswith((".env", "engine.token", "loki_conversations.json")) for n in fnames), fnames)
check("keys, bearer tokens, #token=, KEY=value, e-mails and the home folder are redacted",
      leak not in body and "abc.def.ghi123456" not in body and "SECRETTOKEN123" not in body and "someone@example.org" not in body
      and "gsk_" not in body and str(Path.home()) + "/Documents" not in body and "[redacted]" in body, body[:600])
url = feedback.issue_url("It froze", {"loki": "v9", "os": "TestOS", "machine": "x"}, "LOKI-feedback.zip")
check("the GitHub link is a new issue on m03dev/loki, prefilled", url.startswith("https://github.com/m03dev/loki/issues/new?") and "It+froze" in url)
check("the email link is a mailto draft", feedback.mail_url("x", {}, "f.zip").startswith("mailto:?subject="))
opened = []
code, res = feedback.send({"how": "github", "note": "hi"}, None, opener=opened.append, revealer=lambda p: opened.append(str(p)))
time.sleep(0.2)
check("send(): saves, shows the file, opens the issue", code == 200 and res["ok"] and any(str(o).startswith("https://github.com/") for o in opened), (code, opened))
code, res = feedback.send({"how": "upload-everything"}, None)
check("send(): only github / email / folder", code == 400)
os.environ.pop("LOKI_DATA", None)
import usability_api  # noqa: E402
check("the routes: GET /feedback, POST /feedback/send", usability_api.handles("GET", "/feedback") and usability_api.handles("POST", "/feedback/send"))

# ------------------------------------------------------------------ speed
section("speed: lazy MCP, the window before the engine")
lazy = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'engine'); import loki; print('mcp' in sys.modules)"],
                      cwd=str(REPO), capture_output=True, text=True, timeout=40, env=clean_env(LOKI_DATA=str(TMP / "lazy")))
check("import loki does not import the MCP client (~0.7 s saved)", lazy.stdout.strip().endswith("False"), (lazy.stdout + lazy.stderr)[-300:])
import loki_app  # noqa: E402
check("the start screen: app/ui/splash.html when LOKI's E12 adds it, else a plain one with a status hook",
      loki_app.SPLASH_FILE == UI / "splash.html" and "lokiSplashStatus" in loki_app.splash_html())
os.environ["LOKI_SPLASH"] = "off"
check("LOKI_SPLASH=off keeps the old order", loki_app.splash_wanted() is False)
os.environ.pop("LOKI_SPLASH", None)
check("the window opens first, the engine starts behind it", "run_with_splash" in app_src and "open_window(html=splash_html(), main=True, then=behind_the_window)" in app_src)
import model_setup  # noqa: E402
machine = {"ram_gb": 16, "budget_gb": 8, "unified": False, "vram_gb": 0, "disk_free_gb": 200, "ollama_version": "0.41.0"}
plan = model_setup.plan(machine, [])
q = plan.get("quick") or {}
check("the tour's first model is a quick one (Bonsai 2, a few GB)", "bonsai" in q.get("tag", "").lower() and q.get("size_gb", 99) <= model_setup.QUICK_MAX_GB, q)
b4 = "hf.co/prism-ml/Ternary-Bonsai-2-4B-gguf:Ternary-Bonsai-2-4B-Q2_0"
inst_plan = model_setup.plan(machine, [b4])
check("a model already on the computer wins (nothing to download)", (inst_plan.get("quick") or {}).get("tag") == b4
      and (inst_plan.get("quick") or {}).get("installed") is True, inst_plan.get("quick"))
check("Ollama installs silently: Windows /VERYSILENT, macOS the headless server", "/VERYSILENT" in (REPO / "engine" / "model_setup.py").read_text(encoding="utf-8")
      and "serve_headless" in (REPO / "engine" / "model_setup.py").read_text(encoding="utf-8"))

# ------------------------------------------------------------------ headless: the tour's ways + feedback
def chromium_path() -> str:
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None


class Engine:
    def __init__(self):
        self.posts = []

    def answer(self, method, path, body):
        p = path.split("?")[0]
        if method == "POST":
            self.posts.append((p, body))
        if p == "/health":
            return {"ok": True, "service": "loki", "mode": "build", "provider": "groq", "model": "x", "providers": "", "route": [],
                    "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v9"}, "ui_errors": [], "workspace": "/w"}
        if p == "/onboarding":
            return {"ok": True, "done": False, "step": 1, "interests": [], "ui": "auto", "reply": "match"}
        if p == "/prefs/language":
            return {"ok": True, "ui": "auto", "reply": "match", "languages": usability_api.LANGUAGES}
        if p == "/setup":
            return {"ok": True, "needs_setup": True, "active": {"local": ""}, "cloud_ready": [],
                    "hardware": {"ram_gb": 16, "gpu": "Apple Silicon (unified memory)"}, "scan": {"disk_free_gb": 120},
                    "ollama": {"installed": False, "running": False, "models": []},
                    "auto": {"tag": "qwen3:14b", "size_gb": 9.3, "installed": False},
                    "quick": {"tag": "hf.co/prism-ml/Ternary-Bonsai-2-9B-gguf:Ternary-Bonsai-2-9B-Q2_0", "size_gb": 2.6, "installed": False,
                              "tags": ["x"], "upgrade": "qwen3:14b"}, "picks": {}, "recommend": []}
        if p == "/setup/progress":
            if not any(x[0] == "/setup/auto" for x in self.posts):
                return {"ok": True, "progress": {"op": "", "done": False}}
            return {"ok": True, "progress": {"op": "auto", "done": False, "message": "Downloading", "total": 100, "completed": 40, "percent": 40}}
        if p == "/settings/general":
            return {"ok": True, "settings": {"LOKI_PREFER": {"kind": "choice", "default": "local", "choices": ["local", "cloud"], "label": "Prefer"}},
                    "values": {"LOKI_PREFER": "local"}, "secrets_saved": {}}
        if p == "/feedback/send":
            return {"ok": True, "zip": "/home/u/Desktop/LOKI-feedback-1.zip", "how": (body or {}).get("how"), "url": "https://github.com/m03dev/loki/issues/new"}
        if p == "/conversations":
            return {"ok": True, "conversations": [{"id": "c1", "title": "New chat"}], "active": "c1", "messages": []}
        if p == "/world":
            return {"ok": True, "agents": [], "machines": [], "self": {"name": "t"}, "creations": {"count": 0, "latest": []}}
        return {"ok": True}


async def headless() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium_path(), args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        eng = Engine()
        page = await browser.new_page(viewport={"width": 1240, "height": 820})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            path = r.request.url.split("8898", 1)[1].split("#")[0]
            bare = path.split("?")[0]
            if bare == "/":
                return await r.fulfill(path=str(UI / "index.html"))
            if bare.startswith("/ui/") and r.request.method == "GET" and (UI / bare[4:]).is_file():
                return await r.fulfill(path=str(UI / bare[4:]))
            body = None
            if r.request.method == "POST":
                try:
                    body = json.loads(r.request.post_data or "{}")
                except ValueError:
                    body = {}
            return await r.fulfill(json=eng.answer(r.request.method, path, body))

        await page.route("http://127.0.0.1:8898/**", route)
        await page.add_init_script("localStorage.setItem('loki-lang','en')")
        await page.goto("http://127.0.0.1:8898/#token=t")
        await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
        await page.wait_for_selector("#u-onboarding .u-way", timeout=10000)
        ways = await page.inner_text("#u-onboarding .u-ways")
        check("the tour recommends the quick model by name and size", "Bonsai 2 9B" in ways and "2.6 GB" in ways, ways)
        await page.click("#u-onboarding .u-way[data-way=cloud]")
        await page.wait_for_selector("#u-ob-cloud")
        check("'Connect an account': the accounts, no local card, no download started",
              not await page.is_visible("#u-ob-local") and not any(x[0] == "/setup/auto" for x in eng.posts))
        txt = await page.inner_text("section[aria-labelledby=u-ob-cloud]")
        check("NVIDIA NIM (DeepSeek V4.1 Flash) is offered with a key box", "NVIDIA NIM" in txt and "DeepSeek V4.1 Flash" in txt)
        await page.click("#u-onboarding .u-way[data-way=local]")
        await page.wait_for_timeout(1700)
        bgtext = await page.inner_text("#u-bgsetup") if await page.is_visible("#u-bgsetup") else ""
        check("'Run AI on this computer': the quick download starts, progress at the bottom right",
              any(x[0] == "/setup/auto" and (x[1] or {}).get("quick") for x in eng.posts) and "40%" in bgtext, (bgtext, eng.posts[-3:]))
        check("it mentions the bigger model for later", "qwen3:14b" in await page.inner_text("section[aria-labelledby=u-ob-local]"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        check("the download card stays after the tour closes", await page.is_visible("#u-bgsetup"))
        await page.evaluate("document.getElementById('open-settings').click()")
        await page.evaluate("document.querySelector('[data-tab=general]').click()")
        await page.wait_for_selector("#fb-card", timeout=8000)
        await page.fill("#fb-note", "The tour was great")
        await page.click("#fb-card button.send")
        await page.wait_for_timeout(400)
        sent = [b for x, b in eng.posts if x == "/feedback/send"]
        check("Settings > General > Send feedback asks the engine for a GitHub bundle", sent and sent[-1].get("how") == "github"
              and sent[-1].get("note") == "The tour was great" and sent[-1].get("logs") is True, sent)
        check("... and says where the file is", "LOKI-feedback-1.zip" in await page.inner_text("#fb-card"))
        check("no script errors", not errors, errors[:3])
        await browser.close()


if async_playwright is not None and chromium_path():
    asyncio.run(headless())
else:
    print("\nSKIP: headless part (no Playwright/Chromium here)")

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed  (%.0fs)" % (len(PASS), len(FAIL), time.monotonic() - T0))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
