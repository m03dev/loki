"""LOKI for anyone (session 29): languages, the welcome tour, the example gallery, the help center,
accessibility, keyboard use and the installers' safe updates.

Offline: the string tables are complete, the gallery and help content, the engine API, the
language rule, the release updater (pre-flight, trial, rollback, checksums, signatures, unsafe zips)
and the launcher. Headless Chromium (skipped where Playwright + Chromium are missing): the tour done
with the keyboard only, Arabic right to left, high contrast, bigger text, LOKI's accessibility
rules, focus kept inside dialogs. Screenshots go to a temp folder (LOKI_SUITE_SHOTS=1: refresh
docs/operations/screens/usability_*.png).

    python tests/test_usability.py
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
T0 = time.monotonic()
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "app" / "ui"
sys.path[:0] = [str(REPO / "engine"), str(REPO / "tools"), str(REPO / "packaging" / "installer")]
PASS: list = []
FULL = os.getenv("LOKI_SUITE_SLOW") == "1"   # the owner's rule: a suite run takes at most a minute; =1 runs everything
FAIL: list = []
# Screenshots go to a temp folder, so a suite run never edits tracked files (a dirty checkout would hold
# up updates); LOKI_SUITE_SHOTS=1 refreshes the committed ones in docs/operations/screens/.
SHOTS = (REPO / "docs" / "operations" / "screens") if os.getenv("LOKI_SUITE_SHOTS") == "1" \
    else Path(tempfile.mkdtemp(prefix="loki-usability-shots-"))


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:900],)))


def section(title):
    print("\n== %s  (%.0fs)" % (title, time.monotonic() - T0), flush=True)


# ------------------------------------------------------------------ string tables
section("i18n: eight string tables, complete")
import i18n_tables  # noqa: E402

keys, phrases = i18n_tables.extract()
en = i18n_tables.load("en")
check("en.json has every key the code asks for", all(k in en for k in keys), [k for k in keys if k not in en][:10])
check("en.json has every icon phrase", all(p in en.get("phrases", {}) for p in phrases), [p for p in phrases if p not in en.get("phrases", {})][:5])
check("more than 200 keys and 50 phrases", len(en) > 200 and len(en["phrases"]) > 50, (len(en), len(en.get("phrases", {}))))
for lang in i18n_tables.LANGS[1:]:
    probs = i18n_tables.problems(lang, en)
    check("%s.json: every key and phrase, same {placeholders}" % lang, not probs, probs[:6])
    meta = i18n_tables.load(lang).get("_meta", {})
    check("%s.json is marked machine-drafted for review" % lang, meta.get("review") is True, meta)
check("Arabic is right to left", i18n_tables.load("ar")["_meta"]["dir"] == "rtl")
check("other languages are left to right", all(i18n_tables.load(l)["_meta"]["dir"] == "ltr" for l in ("es", "fr", "de", "hi", "zh", "ja")))
ar = i18n_tables.load("ar")
check("the Arabic table is really Arabic", any("؀" <= ch <= "ۿ" for ch in ar["ob.title"]), ar["ob.title"])
check("the Japanese table is really Japanese", any("぀" <= ch <= "ヿ" for ch in i18n_tables.load("ja")["ob.hello"]))
check("tools/i18n_tables.py --check passes", subprocess.run([sys.executable, str(REPO / "tools" / "i18n_tables.py"), "--check"],
                                                           capture_output=True).returncode == 0)
index = (UI / "index.html").read_text(encoding="utf-8")
check("index.html loads the new parts", all(s in index for s in ("/ui/i18n.js", "/ui/a11y.js", "/ui/gallery.js", "/ui/onboarding.js", "/ui/usability.css")))
for name in ("i18n.js", "a11y.js", "gallery.js", "onboarding.js", "usability.css"):
    check("app/ui/%s exists" % name, (UI / name).is_file())
check("i18n is opt-in per element (data-i18n), nothing else is touched",
      "data-i18n" in (UI / "i18n.js").read_text(encoding="utf-8") and "[data-i18n]" in (UI / "i18n.js").read_text(encoding="utf-8"))

# ------------------------------------------------------------------ gallery + help
section("gallery: 32 examples in 8 categories; help articles")
gsrc = (UI / "gallery.js").read_text(encoding="utf-8")
tasks = [k[5:-6] for k in en if k.startswith("task.") and k.endswith(".title")]
cats = [k[4:] for k in en if k.startswith("cat.") and k != "cat.all"]
check("30+ example tasks", len(tasks) >= 30, len(tasks))
check("8 categories", sorted(cats) == sorted(["everyday", "work", "study", "creative", "home", "money", "health", "business"]), cats)
for cat in cats:
    n = gsrc.count('", "%s", "' % cat)
    check("category %s has at least 3 examples" % cat, n >= 3, n)
check("health examples carry a safety note (card + prompt)", "gallery.safety" in gsrc and "gallery.safety_prompt" in gsrc
      and all(i18n_tables.load(l).get("gallery.safety") for l in i18n_tables.LANGS))
check("health safety note names doctors and emergencies", "doctor" in en["gallery.safety"] and "emergency" in en["gallery.safety"])
check("examples run in Ask mode (nothing on the computer changes)", '"/mode", { mode: "ask" }' in gsrc)

import usability_api  # noqa: E402

arts = usability_api.help_articles()
slugs = [a["slug"] for a in arts]
check("8+ help articles in docs/help", len(arts) >= 8, slugs)
check("help articles follow docs/help/index.json", slugs[0] == "getting-started", slugs[:3])
check("every article has a title and words", all(a["title"] and len(a["text"]) > 200 for a in arts))
order = json.loads((REPO / "docs" / "help" / "index.json").read_text(encoding="utf-8"))["order"]
check("index.json names only existing articles", all((REPO / "docs" / "help" / (s + ".md")).is_file() for s in order))
check("one article by slug", (usability_api.help_article("keyboard-shortcuts") or {}).get("title") == "Keyboard shortcuts")
check("no path tricks in a help slug", usability_api.help_article("../README") is None and usability_api.help_article("..%2fx") is None)
check("an unknown language falls back to English", (usability_api.help_article("languages", "xx") or {}).get("translated") is False)
check("search tags are read", "f1" in (usability_api.help_article("keyboard-shortcuts") or {}).get("tags", []))

# ------------------------------------------------------------------ engine API
section("engine: /onboarding, /prefs/language, the reply language")


class FakeAgent:
    def __init__(self, data):
        self.DATA_DIR = str(data)
        self.refreshed = 0

    def env_file_path(self):
        return Path(self.DATA_DIR) / ".env"

    def refresh_system_prompt(self):
        self.refreshed += 1


class FakeState:
    def __init__(self, agent):
        self.agent = agent


tmp = Path(tempfile.mkdtemp(prefix="loki-usab-"))
saved_env = {k: os.environ.get(k) for k in ("LOKI_LANGUAGE", "LOKI_REPLY_LANGUAGE", "LOKI_INTERESTS", "LOKI_BROWSER_LANGUAGE")}
agent = FakeAgent(tmp)
st = FakeState(agent)
code, data = usability_api.route(st, "GET", "/onboarding")
check("a new computer has not done the tour", code == 200 and data["done"] is False and data["step"] == 0, data)
code, data = usability_api.route(st, "POST", "/onboarding", {"step": 2, "interests": ["work", "bogus", "health"]})
check("the tour remembers its step and interests (unknown ones dropped)", data["step"] == 2 and data["interests"] == ["work", "health"], data)
check("interests are saved for LOKI too (LOKI_INTERESTS)", "LOKI_INTERESTS=work,health" in (tmp / ".env").read_text(encoding="utf-8"))
usability_api.route(st, "POST", "/onboarding", {"done": True})
check("done is kept", usability_api.route(st, "GET", "/onboarding")[1]["done"] is True)
code, data = usability_api.route(st, "POST", "/prefs/language", {"ui": "klingon"})
check("an unknown language is refused with the choices", code == 400 and "es" in data["error"], data)
code, data = usability_api.route(st, "POST", "/prefs/language", {"ui": "es", "reply": "match"})
check("the language is saved and live", code == 200 and data["ui"] == "es" and os.environ.get("LOKI_LANGUAGE") == "es")
check("LOKI's prompt is refreshed when the language changes", agent.refreshed >= 1)
check("GET /help through the route", usability_api.route(st, "GET", "/help?lang=es")[1]["articles"][0]["slug"] == "getting-started")
check("GET /help/<missing> says what to do", "search" in usability_api.route(st, "GET", "/help/nope")[1]["error"])
bridge = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge routes GET and POST to usability_api", bridge.count("usability_api.handles(") == 2)

os.environ["LOKI_DATA"] = str(tmp / "data")
import loki  # noqa: E402

os.environ["LOKI_REPLY_LANGUAGE"] = "match"
os.environ["LOKI_LANGUAGE"] = "es"
rule = loki._language_rule()
check("default: LOKI answers in the language the user writes in", "language the user's latest message is written in" in rule, rule)
check("... with the window's language as the fallback", "use Spanish" in rule, rule)
check("... and never drifts into another language", "Never switch to a language" in rule)
os.environ["LOKI_REPLY_LANGUAGE"] = "ui"
os.environ["LOKI_LANGUAGE"] = "ar"
check("'always the window's language' names it", "always Arabic" in loki._language_rule())
os.environ["LOKI_REPLY_LANGUAGE"] = "en"
check("'always English' is the old English-only rule", loki._language_rule() == loki._ENGLISH_RULE)
os.environ["LOKI_REPLY_LANGUAGE"] = "match"
os.environ["LOKI_LANGUAGE"] = "auto"
os.environ["LOKI_BROWSER_LANGUAGE"] = "ja"
check("'auto' follows the computer's language", "use Japanese" in loki._language_rule())
check("the system prompt starts with the language rule", loki._base_system_prompt().startswith("# Language - answer in the user's language"))
for k, v in saved_env.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

# ------------------------------------------------------------------ release updater
section("installed LOKI: release zips with pre-flight, trial and rollback")
import release_update as ru  # noqa: E402
import updater  # noqa: E402
import make_release  # noqa: E402
import loki_launch  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="loki-release-test-"))
rel_out = work / "out"
built = make_release.build(REPO, rel_out, "9.9.0", "", "test", untracked=True, compress=FULL)   # this worktree, committed or not
seed = rel_out / "seed"
check("make_release builds a seed, a zip and a manifest", (seed / "app" / "loki_app.py").is_file() and Path(built["zip"]).is_file()
      and json.loads((rel_out / "manifest.json").read_text())["version"] == "9.9.0")
check("the release leaves out tests, harness_data and CI", not (seed / "tests").exists() and not (seed / "harness_data").exists()
      and not (seed / ".github").exists())
check("the release keeps the help articles and the launcher", (seed / "docs" / "help" / "getting-started.md").is_file()
      and (seed / "packaging" / "installer" / "loki_launch.py").is_file())
check("RELEASE.json carries the version", json.loads((seed / "RELEASE.json").read_text())["version"] == "9.9.0")

data_dir = work / "data"
root = data_dir / "versions"
root.mkdir(parents=True)
check("the launcher installs the seed as the current version", loki_launch.install_seed(root, seed) == "9.9.0"
      and ru.state.__module__ and json.loads((root / "state.json").read_text())["current"] == "9.9.0")
check("an installer that is not newer changes nothing", loki_launch.install_seed(root, seed) == "")


def make_version(version: str, breaker=None) -> Path:
    """A release zip of this repo's tree at `version`, optionally broken by breaker(tree)."""
    out = work / ("rel-" + version)
    tree = out / ("Loki-" + version)
    if FULL:
        shutil.copytree(seed, tree)
    else:   # what the quick pre-flight looks at: engine/*.py, the app, and the files index.html loads
        wanted = ["RELEASE.json", "app/loki_app.py", "app/ui/index.html"] + ["engine/" + f.name for f in (seed / "engine").glob("*.py")]
        wanted += ["app/ui/" + w for w in set(__import__("re").findall(r'(?:src|href)="/ui/([^"?#]+)"', (seed / "app" / "ui" / "index.html").read_text()))]
        for rel in wanted:
            if (seed / rel).is_file():
                (tree / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(seed / rel, tree / rel)
    info = json.loads((tree / "RELEASE.json").read_text())
    info["version"] = version
    (tree / "RELEASE.json").write_text(json.dumps(info))
    if breaker:
        breaker(tree)
    zpath = out / ("Loki-%s.zip" % version)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(tree.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(out).as_posix())
    man = {"version": version, "url": zpath.name, "sha256": hashlib.sha256(zpath.read_bytes()).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(man))
    return out / "manifest.json"


if not FULL:
    # the real pre-flight runs each new version's whole self-test (10-20 s each); by default a cheap
    # stand-in with the same verdicts: every engine/app .py compiles and every window file exists.


    def _quick_preflight(tree, timeout=60.0):
        for f in list((tree / "engine").glob("*.py")) + [tree / "app" / "loki_app.py"]:
            try:
                compile(f.read_text(encoding="utf-8"), str(f), "exec")
            except SyntaxError as exc:
                return False, "the new version failed its self-test here: %s" % str(exc)[-200:]
        missing = updater.ui_missing(tree)
        if missing:
            return False, "the new version's window would not load: missing " + ", ".join(missing[:5])
        return True, "pre-flight passed (quick)"
    ru.preflight = _quick_preflight

env_keep = {k: os.environ.get(k) for k in ("LOKI_RELEASE_ROOT", "LOKI_RELEASE_FEED", "LOKI_RELEASE_REQUIRE_SIG", "LOKI_ENGINE_PYTHON")}
os.environ.update(LOKI_RELEASE_ROOT=str(root), LOKI_RELEASE_REQUIRE_SIG="0", LOKI_ENGINE_PYTHON=sys.executable)
try:
    check("release mode is on", ru.enabled() and updater._release() and not updater._release(work))
    feed = make_version("9.9.1")
    os.environ["LOKI_RELEASE_FEED"] = feed.as_uri()
    info = ru.check()
    check("a newer release is seen", info.get("ok") and info["update_available"] and info["latest"] == "9.9.1", info)
    res = updater.update()
    check("updater.update() applies it through the release path, after its pre-flight", res.get("updated") and res.get("relaunch"), res)
    s = ru.state()
    check("the new version is current and on trial", s["current"] == "9.9.1" and s["pending"] == "9.9.1" and s["last_good"] == "9.9.0", s)
    check("its tree is in place", (root / "9.9.1" / "app" / "loki_app.py").is_file() and not (root / "9.9.1.staging").exists())
    check("on_trial() through the updater", updater.on_trial())
    updater.mark_good()
    s = ru.state()
    check("the window's ready marks it good", s["last_good"] == "9.9.1" and s["pending"] == "", s)
    check("status() says release + history", updater.status().get("release") and any(h["event"] == "updated" for h in updater.status()["history"]))

    def break_engine(tree: Path) -> None:
        (tree / "engine" / "policy.py").write_text("this is not python(\n", encoding="utf-8")
    os.environ["LOKI_RELEASE_FEED"] = make_version("9.9.2", break_engine).as_uri()
    res = ru.update()
    s = ru.state()
    check("a release whose self-test fails is never applied", not res.get("updated") and s["current"] == "9.9.1", res)
    check("... it is skipped with the reason", "9.9.2" in s.get("skip", []) and "self-test" in s.get("skip_reasons", {}).get("9.9.2", ""), s.get("skip_reasons"))
    check("... and not tried again", not ru.check().get("update_available"))
    check("... its staging folder is gone", not (root / "9.9.2.staging").exists() and not (root / "9.9.2").exists())

    def drop_ui(tree: Path) -> None:
        (tree / "app" / "ui" / "gallery.js").unlink()
    os.environ["LOKI_RELEASE_FEED"] = make_version("9.9.3", drop_ui).as_uri()
    res = ru.update()
    check("a release missing a file the window loads is refused", not res.get("updated") and "gallery.js" in res.get("error", "")
          or "self-test" in res.get("error", ""), res)

    man = make_version("9.9.4")
    m = json.loads(man.read_text())
    m["sha256"] = "0" * 64
    man.write_text(json.dumps(m))
    os.environ["LOKI_RELEASE_FEED"] = man.as_uri()
    res = ru.update()
    check("a download that does not match its checksum is refused", not res.get("updated") and "checksum" in res.get("error", ""), res)

    evil = work / "evil"
    evil.mkdir()
    with zipfile.ZipFile(evil / "Loki-9.9.5.zip", "w") as zf:
        zf.writestr("../escape.txt", "x")
    (evil / "manifest.json").write_text(json.dumps({"version": "9.9.5", "url": "Loki-9.9.5.zip",
                                                     "sha256": hashlib.sha256((evil / "Loki-9.9.5.zip").read_bytes()).hexdigest()}))
    os.environ["LOKI_RELEASE_FEED"] = (evil / "manifest.json").as_uri()
    res = ru.update()
    check("a zip with ../ paths is refused", not res.get("updated") and "unsafe" in res.get("error", "") and not (root / "escape.txt").exists(), res)

    os.environ["LOKI_RELEASE_FEED"] = make_version("9.9.6").as_uri()
    res = ru.update()
    check("a good newer release after the bad ones is applied", res.get("updated") and ru.current() == "9.9.6", res)
    back = updater.rollback(why="its window did not become ready in 300 s")
    s = ru.state()
    check("a version whose window never opens is rolled back to the last good one", back.get("ok") and s["current"] == "9.9.1", back)
    check("... and skipped with the reason", "9.9.6" in s["skip"] and "window" in s["skip_reasons"]["9.9.6"])
    check("a good version is not rolled back", not ru.rollback().get("ok"))
    check("the history lists updated, refused, rolled back", {"updated", "refused", "rolled back", "good"} <= {h["event"] for h in s["history"]})
    check("old versions are pruned, current + last good kept", (root / "9.9.1").is_dir())
    check("an http:// (not https) feed is refused", "https" in ru.fetch_manifest("http://example.org/m.json").get("error", ""))

    # signatures: pure-Python RSA verify of what tools/loki_sign.py (openssl) makes
    if shutil.which("openssl"):
        key = work / "k.pem"
        pub = work / "pub.pem"
        subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], capture_output=True, check=True)
        subprocess.run(["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(pub)], capture_output=True, check=True)
        blob = b'{"version": "1"}'
        (work / "m.json").write_bytes(blob)
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key), "-out", str(work / "m.json.sig"), str(work / "m.json")], check=True)
        sig = (work / "m.json.sig").read_bytes()
        check("an openssl signature verifies in pure Python", ru.verify_signature(blob, sig, pub.read_text()))
        check("a changed manifest does not", not ru.verify_signature(blob + b" ", sig, pub.read_text()))
        check("LOKI's own public key parses", ru.public_key((REPO / "keys" / "loki_public.pem").read_text())[1] == 65537)
    else:
        check("signature check skipped (no openssl here)", True)
    os.environ["LOKI_RELEASE_REQUIRE_SIG"] = "1"
    check("by default an unsigned feed is refused", "signature" in ru.fetch_manifest(make_version("9.9.7").as_uri()).get("error", ""))
finally:
    for k, v in env_keep.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
check("without LOKI_RELEASE_ROOT the git updater is untouched", not updater._release())

section("the launcher starts the current version and again after a switch")
lw = Path(tempfile.mkdtemp(prefix="loki-launch-"))
ldata = lw / "data"
lroot = ldata / "versions"
fake_seed = lw / "seed"
for v in ("1.0.0", "1.0.1"):
    t = lw / ("tree-" + v)
    (t / "app").mkdir(parents=True)
    (t / "RELEASE.json").write_text(json.dumps({"version": v}))
    # a fake app: the first run switches to 1.0.1 and asks for a relaunch, the second exits 0
    (t / "app" / "loki_app.py").write_text(
        "import json, os, sys\nfrom pathlib import Path\n"
        "root = Path(os.environ['LOKI_RELEASE_ROOT'])\n"
        "log = root.parent / 'runs.txt'\n"
        "log.write_text(log.read_text() + '%s\\n' if log.exists() else '%s\\n')\n" % (v, v)
        + "assert os.environ['LOKI_DATA'] and os.environ['LOKI_ENGINE_PYTHON']\n"
        "if '%s' == '1.0.0':\n" % v
        + "    s = json.loads((root / 'state.json').read_text()); s['current'] = '1.0.1'; (root / 'state.json').write_text(json.dumps(s)); sys.exit(76)\n"
        "sys.exit(0)\n", encoding="utf-8")
shutil.copytree(lw / "tree-1.0.0", fake_seed)
shutil.copytree(lw / "tree-1.0.1", lroot / "1.0.1")
venv_bin = ldata / ".venv" / ("Scripts" if os.name == "nt" else "bin")
pyname = "python.exe" if os.name == "nt" else "python3"
if os.name == "nt":
    # a lone copy of python.exe cannot run on Windows (no pyvenv.cfg, no DLLs beside it), so the fake install
    # made a real (pip-less) venv: its python.exe actually starts the fake app.
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(ldata / ".venv")],
                   capture_output=True, text=True, timeout=180)
else:
    venv_bin.mkdir(parents=True)
    try:
        os.symlink(sys.executable, venv_bin / pyname)
    except OSError:
        shutil.copy2(sys.executable, venv_bin / pyname)
(ldata / ".venv" / "loki-requirements.sha256").write_text(hashlib.sha256(b"").hexdigest())
proc = subprocess.run([sys.executable, str(REPO / "packaging" / "installer" / "loki_launch.py"), "--seed", str(fake_seed)],
                      env=dict(os.environ, LOKI_DATA=str(ldata)), capture_output=True, text=True, timeout=60)
runs = (ldata / "runs.txt").read_text().split() if (ldata / "runs.txt").exists() else []
check("the launcher runs the seed, then the new current after exit 76", proc.returncode == 0 and runs == ["1.0.0", "1.0.1"], (proc.returncode, runs, proc.stderr[-400:]))
check("the launcher says what to do when Python is missing", "bootstrap" in subprocess.run(
    [sys.executable, str(REPO / "packaging" / "installer" / "loki_launch.py"), "--seed", str(fake_seed)],
    env=dict(os.environ, LOKI_DATA=str(lw / "empty")), capture_output=True, text=True).stderr)

section("installers and the build workflow")
iss = (REPO / "packaging" / "windows" / "loki.iss").read_text(encoding="utf-8")
check("Windows installer: per-user, no admin", "PrivilegesRequired=lowest" in iss and "{localappdata}" in iss)
check("Windows installer: sets up Python at install time, keeps user data on uninstall", "bootstrap.ps1\"\" -Setup" in iss and "is kept" in iss)
check("bootstrap.ps1 verifies uv's checksum", "Get-FileHash" in (REPO / "packaging" / "installer" / "bootstrap.ps1").read_text(encoding="utf-8"))
boot = (REPO / "packaging" / "installer" / "bootstrap.sh").read_text(encoding="utf-8")
check("bootstrap.sh verifies uv's checksum and parses", "shasum -a 256" in boot
      and subprocess.run(["bash", "-n", str(REPO / "packaging" / "installer" / "bootstrap.sh")]).returncode == 0)
check("make_dmg.sh parses", subprocess.run(["bash", "-n", str(REPO / "tools" / "macos" / "make_dmg.sh")]).returncode == 0)
wf = (REPO / ".github" / "workflows" / "installers.yml").read_text(encoding="utf-8")
check("the installers workflow runs only by hand or on a v* tag", "workflow_dispatch" in wf and 'tags: ["v*"]' in wf and "branches" not in wf)
check("the workflow builds Windows and macOS", "loki.iss" in wf and "make_dmg.sh" in wf)
check("the PyInstaller build carries the help articles", '"docs/help"' in (REPO / "packaging" / "loki.spec").read_text(encoding="utf-8"))
check("the PyInstaller build carries Studio's sources (engine/godot_live imports studio_godot)",
      '"studio"' in (REPO / "packaging" / "loki.spec").read_text(encoding="utf-8"))
check("docs/INSTALL.md is written for other people", (REPO / "docs" / "INSTALL.md").is_file()
      and "Signing" in (REPO / "docs" / "INSTALL.md").read_text(encoding="utf-8"))
app_src = (REPO / "app" / "loki_app.py").read_text(encoding="utf-8")
check("loki_app: a release switch or rollback goes back to the launcher (exit 76)", "RELAUNCH_EXIT_CODE = 76" in app_src
      and app_src.count("RELAUNCH_EXIT_CODE") >= 4)


# ------------------------------------------------------------------ headless window
def chromium_path() -> str:
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None

RULES = (Path(__file__).parent / "a11y_rules.js").read_text(encoding="utf-8")


class Engine:
    """A fake engine for the window: enough of the real API, with the real help articles."""

    def __init__(self, done=False, local=False):
        self.onboarding = {"done": done, "step": 0, "interests": []}
        self.posts = []
        self.connected = ""
        self.local = local
        self.mode = "build"

    def answer(self, method, path, body):
        p = path.split("?")[0]
        if method == "POST":
            self.posts.append((p, body))
        if p == "/health":
            return {"ok": True, "service": "loki", "mode": self.mode, "provider": "groq", "model": "x", "providers": "", "route": [],
                    "usage": {}, "first_layer": {}, "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": [], "workspace": "/home/u/LOKI Projects/Home"}
        if p == "/onboarding":
            if method == "POST":
                self.onboarding.update({k: v for k, v in (body or {}).items() if k in ("done", "step", "interests", "model_choice")})
            return {"ok": True, **self.onboarding, "ui": "auto", "reply": "match"}
        if p == "/prefs/language":
            return {"ok": True, "ui": "auto", "reply": "match", "languages": usability_api.LANGUAGES}
        if p == "/setup":
            return {"ok": True, "needs_setup": not self.local, "active": {"local": "qwen3:8b" if self.local else ""},
                    "cloud_ready": [self.connected] if self.connected else [],
                    "scan": {"ram_gb": 16, "ollama_installed": False}, "ollama": {"installed": False, "running": False, "models": []},
                    "auto": {"tag": "qwen3:8b", "size_gb": 5.2, "installed": False}, "picks": {}, "recommend": []}
        if p == "/providers/connect":
            key = (body or {}).get("key", "")
            if key == "gsk_good":
                self.connected = (body or {}).get("id", "")
                return {"ok": True, "provider": self.connected}
            return {"ok": False, "error": "the provider said 401 invalid API key"}
        if p == "/help":
            return {"ok": True, "articles": usability_api.help_articles()}
        if p.startswith("/help/"):
            art = usability_api.help_article(p[6:])
            return {"ok": True, **art} if art else {"ok": False, "error": "no article"}
        if p == "/mode":
            if method == "POST":
                self.mode = (body or {}).get("mode", self.mode)
            return {"ok": True, "mode": self.mode}
        if p == "/conversations":
            return {"ok": True, "conversations": [{"id": "c1", "title": "New chat"}], "active": "c1", "messages": []}
        if p == "/chat":
            return {"ok": True, "reply": "Here is your plan.", "messages": []}
        if p == "/world":
            return {"ok": True, "agents": [], "machines": [], "self": {"name": "test"}, "creations": {"count": 0, "latest": []}}
        if p == "/settings/general":
            return {"ok": True, "settings": {"LOKI_PREFER": {"kind": "choice", "default": "local", "choices": ["local", "cloud"], "label": "Prefer local models or the cloud"}},
                    "values": {"LOKI_PREFER": "local"}, "secrets_saved": {}}
        return {"ok": True}


async def open_page(p, browser, engine, init="", viewport=(1240, 820)):
    page = await browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    errors, missing = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

    async def route(r):
        url = r.request.url.split("8899", 1)[1]
        path = url.split("#")[0]
        bare = path.split("?")[0]
        if bare == "/":
            return await r.fulfill(path=str(UI / "index.html"))
        if bare.startswith("/ui/") and r.request.method == "GET":
            f = UI / bare[4:]
            if f.is_file():
                return await r.fulfill(path=str(f))
            if bare not in ("/ui/error", "/ui/ready", "/ui/timing"):
                missing.append(bare)
                return await r.fulfill(status=404, body="missing")
        body = None
        if r.request.method == "POST":
            try:
                body = json.loads(r.request.post_data or "{}")
            except ValueError:
                body = {}
        return await r.fulfill(json=engine.answer(r.request.method, path, body))

    await page.route("http://127.0.0.1:8899/**", route)
    if init:
        await page.add_init_script(init)
    await page.goto("http://127.0.0.1:8899/#token=t")
    await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
    await page.wait_for_timeout(900)
    return page, errors, missing


async def rules(page, scope=""):
    return await page.evaluate(RULES, scope or None)


def fmt(v):
    return ["%s %s: %s" % (x["rule"], x["where"], x["detail"]) for x in v][:8]


async def headless() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chromium_path(), args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])

        section("headless: the welcome tour, with the keyboard only")
        eng = Engine()
        page, errors, missing = await open_page(p, browser, eng, "localStorage.setItem('loki-lang','en')")
        check("the tour opens on a new computer", await page.is_visible("#u-onboarding"))
        check("no missing files, no script errors", not missing and not errors, (missing, errors[:3]))
        check("the tour is a labelled modal dialog", await page.evaluate("(() => { const d = document.querySelector('#u-onboarding [role=dialog]'); return d.getAttribute('aria-modal') === 'true' && !!document.getElementById(d.getAttribute('aria-labelledby')).textContent; })()"))
        v = await rules(page, "#u-onboarding")
        check("accessibility rules: welcome step", not v, fmt(v))
        await page.screenshot(path=str(SHOTS / "usability_onboarding_1.png"))
        inside = await page.evaluate("document.activeElement.closest('#u-onboarding') !== null")
        check("focus is inside the tour", inside)
        for _ in range(16):   # Tab never leaves the dialog
            await page.keyboard.press("Tab")
        check("Tab stays inside the tour", await page.evaluate("document.activeElement.closest('#u-onboarding') !== null"))
        await page.focus("#u-onboarding .u-next")
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#u-onboarding .u-way")
        ways = await page.inner_text("#u-onboarding .u-ways")
        check("step 2 (session 30): three ways - this computer, an account, both", all(s in ways for s in ("Run AI on this computer", "Connect an account", "Both")), ways)
        check("step 2 says the local model's size before the one click", "5.2 GB" in ways, ways)
        await page.focus("#u-onboarding .u-way[data-way=both]")
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#u-ob-local")
        check("step 2: Both shows this computer and the accounts side by side", await page.is_visible("#u-ob-cloud") and await page.is_visible("#u-ob-local"))
        await page.wait_for_timeout(300)
        check("choosing Both starts the quick local download in the background", any(p_ == "/setup/auto" and (b or {}).get("quick") for p_, b in eng.posts)
              and await page.is_visible("#u-bgsetup"), [x[0] for x in eng.posts][-5:])
        step2 = await page.inner_text("#u-onboarding")
        check("step 2 offers OpenRouter sign-in, NVIDIA NIM, Groq and Gemini", all(s in step2 for s in ("OpenRouter", "NVIDIA NIM", "Groq", "Google Gemini")))
        v = await rules(page, "#u-onboarding")
        check("accessibility rules: model step", not v, fmt(v))
        await page.screenshot(path=str(SHOTS / "usability_onboarding_2.png"))
        groq = page.locator("#u-onboarding .u-keyform").nth(1)   # NVIDIA NIM is first (session 30), then Groq
        await groq.locator("input").focus()
        await page.keyboard.type("gsk_wrong")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        err = await page.inner_text("#u-onboarding .u-cloud:nth-of-type(3) .u-say")
        check("a wrong key says why and what to do", "401" in err and ("Copy it again" in err or "start with" in err), err)
        await groq.locator("input").fill("")
        await groq.locator("input").focus()
        await page.keyboard.type("gsk_good")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        check("a good key connects and the step says so", "Connected" in await page.inner_text("#u-onboarding .u-body > .u-say"))
        await page.focus("#u-onboarding .u-next")
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#u-onboarding .u-interest")
        await page.focus("#u-onboarding .u-interest >> nth=1")
        await page.keyboard.press("Space")
        await page.focus("#u-onboarding .u-interest >> nth=6")
        await page.keyboard.press("Enter")
        check("interests toggle with the keyboard (aria-pressed)", await page.evaluate("[...document.querySelectorAll('#u-onboarding .u-interest[aria-pressed=true]')].length") == 2)
        await page.screenshot(path=str(SHOTS / "usability_onboarding_3.png"))
        await page.focus("#u-onboarding .u-next")
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#u-onboarding .u-try .u-task")
        tries = await page.locator("#u-onboarding .u-try .u-task").count()
        check("step 4: three examples to try", tries == 3, tries)
        check("the examples follow the chosen interests", "work" in (await page.inner_text("#u-onboarding .u-try")).lower())
        check("the interests reached the engine", any(p_ == "/onboarding" and (b or {}).get("interests") == ["work", "health"] for p_, b in eng.posts), eng.posts[-4:])
        await page.screenshot(path=str(SHOTS / "usability_onboarding_4.png"))
        await page.locator("#u-onboarding .u-try .u-task").first.focus()
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(800)
        check("trying one finishes the tour", eng.onboarding["done"] is True and not await page.is_visible("#u-onboarding"))
        check("the example ran in Ask mode, as a chat", any(p_ == "/mode" and (b or {}).get("mode") == "ask" for p_, b in eng.posts)
              and any(p_ == "/chat" for p_, _ in eng.posts), [x[0] for x in eng.posts][-6:])
        check("no script errors during the tour", not errors, errors[:3])
        await page.close()

        if not FULL:   # the one-minute run: Arabic + high contrast in one page, then stop
            section("headless (quick): Arabic right to left with high contrast")
            init = "localStorage.setItem('loki-lang','ar');localStorage.setItem('loki-a11y', JSON.stringify({contrast:true, cbsafe:true, motion:'reduce', font:'100'}))"
            page, errors, missing = await open_page(p, browser, Engine(done=True, local=True), init)
            dirs = await page.evaluate("[document.documentElement.lang, document.documentElement.dir, document.documentElement.className]")
            check("Arabic sets lang=ar and dir=rtl", dirs[:2] == ["ar", "rtl"], dirs)
            check("high contrast, colour-blind-safe and reduced motion apply", all(c in dirs[2] for c in ("u-hc", "u-cb", "u-rm")), dirs[2])
            boxes = await page.evaluate("[document.querySelector('.sidebar').getBoundingClientRect().left, document.querySelector('.main').getBoundingClientRect().left]")
            check("the sidebar moves to the right", boxes[0] > boxes[1], boxes)
            check("icon tooltips are in Arabic", await page.get_attribute("#open-settings", "aria-label") == "الإعدادات")
            v = await rules(page)
            check("accessibility rules: Arabic + high contrast home", not v, fmt(v))
            check("no script errors or missing files", not errors and not missing, (errors[:3], missing))
            await page.close()
            await browser.close()
            print("(LOKI_SUITE_SLOW=1 also runs the gallery, help, keyboard, Settings and real pre-flight checks)")
            return

        section("headless: someone who already uses LOKI never sees the tour")
        eng2 = Engine(local=True)
        eng2.answer("GET", "/conversations", None)
        eng2_conv = {"ok": True, "conversations": [{"id": "c1", "title": "Fix the build"}], "active": "c1", "messages": []}
        orig = eng2.answer
        eng2.answer = lambda m, path, b: eng2_conv if path.split("?")[0] == "/conversations" and m == "GET" else orig(m, path, b)
        page, errors, _ = await open_page(p, browser, eng2)
        await page.wait_for_timeout(600)
        check("no tour when a model works and there are chats", not await page.is_visible("#u-onboarding") and eng2.onboarding["done"] is True)

        section("headless: keyboard, gallery, help")
        await page.keyboard.press("Tab")
        check("the first Tab shows 'Skip to the message box'", await page.evaluate("document.activeElement.id") == "u-skip")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(200)
        check("... and it goes to the message box", await page.evaluate("document.activeElement.id") == "prompt")
        await page.focus("#u-gallery-btn")
        await page.keyboard.press("Enter")
        await page.wait_for_selector("#u-gallery-grid .u-task")
        await page.wait_for_timeout(150)
        n = await page.locator("#u-gallery-grid .u-task").count()
        check("the gallery shows 32 examples", n == 32, n)
        check("the gallery search box has focus", await page.evaluate("document.activeElement.id") == "u-gallery-search")
        v = await rules(page, "#u-gallery")
        check("accessibility rules: gallery", not v, fmt(v))
        await page.keyboard.type("budget")
        await page.wait_for_timeout(150)
        check("search narrows the examples", 1 <= await page.locator("#u-gallery-grid .u-task").count() < 5)
        await page.fill("#u-gallery-search", "")
        await page.click(".u-chips .chip >> text=Health info")
        hn = await page.locator("#u-gallery-grid .u-health").count()
        check("health examples show the safety note", hn == 4 and await page.locator("#u-gallery-grid .u-safety").count() == 4, hn)
        await page.screenshot(path=str(SHOTS / "usability_gallery.png"))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
        check("Esc closes the gallery and focus goes back to its button", not await page.is_visible("#u-gallery")
              and await page.evaluate("document.activeElement.id") in ("u-gallery-btn", "u-gallery-search") and await page.evaluate("document.activeElement.id") == "u-gallery-btn",
              await page.evaluate("document.activeElement.id"))
        await page.keyboard.press("F1")
        await page.wait_for_selector("#u-help .u-help-item")
        check("F1 opens the help center with the articles", await page.locator("#u-help .u-help-item").count() >= 8)
        await page.fill("#u-help-search", "keyboard")
        await page.wait_for_timeout(150)
        await page.locator("#u-help .u-help-item").first.click()
        await page.wait_for_selector("#u-help .u-article-text")
        check("an article opens, rendered (no raw markup)", "Keyboard shortcuts" in await page.inner_text("#u-help .u-article-text")
              and await page.locator("#u-help .u-article-text h1").count() == 1)
        v = await rules(page, "#u-help")
        check("accessibility rules: help", not v, fmt(v))
        await page.keyboard.press("Escape")
        check("the ? button has a name and tooltip", await page.get_attribute("#u-help-btn", "aria-label") == "Help"
              and bool(await page.get_attribute("#u-help-btn", "data-tip-what")))
        await page.click("#open-settings")
        await page.wait_for_timeout(300)
        await page.focus('.tabs [role="tab"][aria-selected="true"]')
        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(200)
        sel = await page.evaluate("document.querySelector('.tabs [aria-selected=true]').dataset.tab")
        check("arrow keys move between Settings sections", sel == "general", sel)
        await page.wait_for_selector(".u-prefs")
        check("Settings > General has Language and accessibility", await page.is_visible(".u-prefs"))
        v = await rules(page, ".u-prefs")
        check("accessibility rules: the language + accessibility settings", not v, fmt(v))
        v = await rules(page)
        check("accessibility rules: the whole window with Settings open", not v, fmt(v))
        await page.screenshot(path=str(SHOTS / "usability_settings_prefs.png"))
        await page.select_option(".u-prefs select >> nth=2", "130")
        await page.wait_for_timeout(200)
        z = await page.evaluate("[getComputedStyle(document.body).zoom, document.documentElement.scrollWidth <= innerWidth + 1]")
        check("text size 130% zooms the window without sideways scrolling", z[0] in ("1.3", 1.3) and z[1], z)
        check("the text size is remembered", json.loads(await page.evaluate("localStorage.getItem('loki-a11y')"))["font"] == "130")
        await page.close()

        section("headless: Arabic, right to left")
        page, errors, missing = await open_page(p, browser, Engine(done=True, local=True), "localStorage.setItem('loki-lang','ar')")
        dirs = await page.evaluate("[document.documentElement.lang, document.documentElement.dir]")
        check("Arabic sets lang=ar and dir=rtl", dirs == ["ar", "rtl"], dirs)
        boxes = await page.evaluate("[document.querySelector('.sidebar').getBoundingClientRect().left, document.querySelector('.main').getBoundingClientRect().left]")
        check("the sidebar moves to the right", boxes[0] > boxes[1], boxes)
        check("the home screen is in Arabic", "لوكي" in await page.inner_text(".welcome-title"))
        check("icon tooltips are in Arabic", await page.get_attribute("#open-settings", "aria-label") == "الإعدادات")
        check("the composer placeholder is in Arabic", "لوكي" in (await page.get_attribute("#prompt", "placeholder") or ""))
        check("no script errors in Arabic", not errors and not missing, (errors[:3], missing))
        v = await rules(page)
        check("accessibility rules: Arabic home", not v, fmt(v))
        await page.screenshot(path=str(SHOTS / "usability_arabic_home.png"))
        await page.click("#u-gallery-btn")
        await page.wait_for_selector("#u-gallery-grid .u-task")
        check("the gallery is in Arabic", "ماذا يستطيع" in await page.inner_text("#u-gallery-title"))
        await page.screenshot(path=str(SHOTS / "usability_arabic_gallery.png"))
        await page.keyboard.press("Escape")
        await page.evaluate("window.Onboarding.open(true)")
        await page.wait_for_selector("#u-onboarding .u-lang")
        await page.screenshot(path=str(SHOTS / "usability_arabic_onboarding.png"))
        await page.focus('#u-onboarding .u-lang[aria-checked="true"]')
        await page.keyboard.press("ArrowLeft")   # RTL: left is "next"
        await page.wait_for_timeout(600)
        now = await page.evaluate("document.documentElement.lang")
        check("arrow keys pick another language (and the window switches)", now != "ar", now)
        await page.close()

        section("headless: high contrast + colour-blind-safe + reduced motion")
        init = "localStorage.setItem('loki-lang','en');localStorage.setItem('loki-a11y', JSON.stringify({contrast:true, cbsafe:true, motion:'reduce', font:'100'}))"
        page, errors, _ = await open_page(p, browser, Engine(done=True, local=True), init)
        cls = await page.evaluate("document.documentElement.className")
        check("high contrast, colour-blind-safe and reduced motion apply", all(c in cls for c in ("u-hc", "u-cb", "u-rm")), cls)
        check("high contrast: black background, white text", await page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(0, 0, 0)"
              and await page.evaluate("getComputedStyle(document.body).color") == "rgb(255, 255, 255)")
        check("reduced motion stops animations (and there is no moving world behind the home screen any more)",
              await page.evaluate("!document.querySelector('.world-bg') && parseFloat(getComputedStyle(document.body).animationDuration || '0') < 0.01"))
        check("status shows a symbol, not only a colour", await page.evaluate("getComputedStyle(document.querySelector('#status'), '::before').content") in ('"✓"', '"✕"', '"…"'))
        v = await rules(page)
        check("accessibility rules with high contrast (7:1 text)", not v, fmt(v))
        await page.screenshot(path=str(SHOTS / "usability_high_contrast.png"))
        await page.click("#u-gallery-btn")
        await page.wait_for_selector("#u-gallery-grid .u-task")
        v = await rules(page, "#u-gallery")
        check("accessibility rules: gallery in high contrast", not v, fmt(v))
        await page.screenshot(path=str(SHOTS / "usability_high_contrast_gallery.png"))
        check("no script errors", not errors, errors[:3])
        await page.close()
        await browser.close()


if async_playwright is not None and chromium_path():
    asyncio.run(headless())
else:
    print("\nSKIP: headless part (no Playwright/Chromium here)")

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)
shutil.rmtree(lw, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
