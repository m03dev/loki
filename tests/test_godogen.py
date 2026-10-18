"""Godogen, Nanocoder and the Cozy Blanket research in LOKI (2026-10-17 owner request).

    python tests/test_godogen.py      (< 5 s, offline: temp folders, fake `which`/git, no agent runs)

Godogen (htdt/godogen, MIT): publish.sh ported to Python (engine/godogen.py) writes the runtime
manifest, the engine guide and the asset-gen skill into ~/LOKI Projects/<name> and returns a background
job spec; make_godot_game is gated by the godogen add-on and always asks. Nanocoder (MIT): a job agent
with a fixed argument list. Every new add-on's manifest passes engine/manifests.py, and the licences
are recorded in docs/THIRD_PARTY.md.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-godogen-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
sys.path.insert(0, str(REPO / "engine"))

import agents  # noqa: E402
import godogen  # noqa: E402
import manifests  # noqa: E402
import policy  # noqa: E402
import workers  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


def section(title):
    print("\n" + title)


def read(path):
    return (REPO / path).read_text(encoding="utf-8")


# ------------------------------------------------------------------ manifests
section("add-on manifests (engine/manifests.py rules)")
for name in ("godogen", "wechaty", "nanocoder"):
    path = REPO / "capabilities" / name / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    check("%s: valid manifest" % name, manifests.validate(data) == [], manifests.validate(data))
    check("%s: names its licence and homepage" % name, data.get("license") and data.get("homepage", "").startswith("https://github.com/"))
    check("%s: off until the owner turns it on (no default_enabled)" % name, not data.get("default_enabled"))
found = {e["name"]: e for e in manifests.discover([("builtin", REPO / "capabilities")])}
reg = manifests.Registry([("builtin", REPO / "capabilities")], manifests.Enablement(TMP / "enabled.json"), env={})
check("discovered and disabled by default", all(reg.get(n)["status"] == "disabled" for n in ("godogen", "wechaty", "nanocoder")),
      {n: reg.get(n)["status"] for n in ("godogen", "wechaty", "nanocoder")})
third = read("docs/THIRD_PARTY.md")
check("THIRD_PARTY.md lists godogen, wechaty, nanocoder and the Cozy Blanket notes",
      all(s in third for s in ("htdt/godogen", "wechaty/wechaty", "Nano-Collective/nanocoder", "COZY_BLANKET.md")))

# ------------------------------------------------------------------ godogen's text, vendored
section("contrib/godogen (MIT, copied unchanged)")
src = REPO / "contrib" / "godogen"
check("licence and provenance beside it", (src / "LICENSE.md").is_file() and "MIT" in (src / "LICENSE.md").read_text(encoding="utf-8")
      and "40542b6c8efbdc40112c2b004fbaa6d67141846d" in (src / "PROVENANCE.md").read_text(encoding="utf-8"))
check("every engine guide and the runtime manifest", all((src / "engines" / ("%s.md" % e)).is_file() for e in godogen.ENGINES)
      and (src / "prompts" / "runtime.md").is_file() and (src / "asset-gen" / "SKILL.md").is_file())
check("no Godot project files in the repo from it", not any(p.suffix in (".gd", ".tscn", ".godot") for p in src.rglob("*")))
check("no shell script copied (publish.sh is ported)", not (src / "publish.sh").exists() and not list(src.rglob("*.sh")))

# ------------------------------------------------------------------ the port of publish.sh
section("publish (publish.sh + render_dir.py + generate_codex_metadata.py in Python)")
check("render_text fills only the given ${KEY} tokens", godogen.render_text("a ${X} ${Y}", {"X": "1"}) == "a 1 ${Y}")
calls = []
fake_git = lambda argv, **kw: calls.append((argv, kw.get("cwd")))  # noqa: E731
target = TMP / "games" / "claude-game"
out = godogen.publish("godot-gdscript", "claude", target, env={}, runner=fake_git)
claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
check("CLAUDE.md is godogen's runtime manifest for Godot", claude_md.startswith("# Build Godot game from a description")
      and "godot-gdscript.md" in claude_md and "/asset-gen" in claude_md and "${" not in claude_md, claude_md[:200])
check("the engine guide is copied as godot-gdscript.md", (target / "godot-gdscript.md").read_text(encoding="utf-8")
      == (src / "engines" / "godot-gdscript.md").read_text(encoding="utf-8"))
skill = (target / ".claude" / "skills" / "asset-gen" / "SKILL.md").read_text(encoding="utf-8")
check("the asset-gen skill is rendered (no tokens left, assets dir, no godogen_assets = none)",
      "${" not in skill and "assets/glb/crate.glb" in skill and "is `none`" in skill, skill[:300])
check("tools copied", (target / ".claude" / "skills" / "asset-gen" / "tools" / "grid_slice.py").is_file())
ignore = (target / ".gitignore").read_text(encoding="utf-8").split()
check(".gitignore as publish.sh writes it", ignore[:4] == [".claude", "CLAUDE.md", "godot-gdscript.md", "/tripo-out"]
      and ".godot" in ignore and "*.import" in ignore, ignore)
check("git init with an argument list in the game folder (no shell)",
      (not shutil.which("git")) or (calls and calls[0][0][1:] == ["init", "-q"] and calls[0][1] == str(target)), calls)
check("publish reports what it wrote", out["ok"] and out["manifest"] == "CLAUDE.md" and ".gitignore" in out["written"])
(target / ".claude" / "skills" / "asset-gen" / "stale.txt").write_text("old", encoding="utf-8")
godogen.publish("godot-gdscript", "claude", target, env={}, runner=fake_git)
check("re-publishing replaces the skill (rsync --delete)", not (target / ".claude" / "skills" / "asset-gen" / "stale.txt").exists())

codex_target = TMP / "games" / "web-game"
godogen.publish("threejs", "codex", codex_target, env={}, runner=fake_git)
agents_md = (codex_target / "AGENTS.md").read_text(encoding="utf-8")
yaml = (codex_target / ".agents" / "skills" / "asset-gen" / "agents" / "openai.yaml").read_text(encoding="utf-8")
check("codex flavour: AGENTS.md + $asset-gen + .agents/skills", "three.js" in agents_md and "$asset-gen" in agents_md
      and (codex_target / "threejs.md").is_file())
check("codex metadata from the SKILL.md frontmatter", yaml.startswith("interface:\n  display_name: \"Asset Generator\"")
      and "allow_implicit_invocation: true" in yaml, yaml)
check("browser engines load assets from src/assets",
      "src/assets/glb/crate.glb" in (codex_target / ".agents" / "skills" / "asset-gen" / "SKILL.md").read_text(encoding="utf-8"))
fake_assets = TMP / "godogen_assets"
(fake_assets / "bin").mkdir(parents=True)
(fake_assets / "README.md").write_text("x", encoding="utf-8")
check("LOKI_GODOGEN_ASSETS is used only when it is a real checkout",
      godogen.assets_checkout({"LOKI_GODOGEN_ASSETS": str(fake_assets)}) == str(fake_assets)
      and godogen.assets_checkout({"LOKI_GODOGEN_ASSETS": str(TMP)}) == "none")
for bad in (("unreal", "claude"), ("godot", "gemini")):
    try:
        godogen.publish(bad[0], bad[1], TMP / "x", env={})
        check("refuses %s/%s" % bad, False)
    except godogen.GodogenError:
        check("refuses %s/%s" % bad, True)

# ------------------------------------------------------------------ make_godot_game
section("make_godot_game: ~/LOKI Projects/<name> + a background job spec")
env = {"LOKI_PROJECTS_DIR": str(TMP / "LOKI Projects")}
none = lambda exe: None  # noqa: E731
only_codex = lambda exe: "/usr/bin/codex" if exe == "codex" else None  # noqa: E731
check("auto picks an installed agent, LOKI's own when none is", godogen.pick_agent("auto", none) == "loki"
      and godogen.pick_agent("auto", only_codex) == "codex")
made = godogen.make_godot_game("A fox collects berries; avoid the owls!", "", env=env, which=only_codex, runner=fake_git)
ws = Path(made["workspace"])
check("the game folder is ~/LOKI Projects/<slug>", ws == TMP / "LOKI Projects" / "a-fox-collects-berries-avoid-the-owls", ws)
check("codex reads AGENTS.md", (ws / "AGENTS.md").is_file() and made["manifest"] == "AGENTS.md")
job = made["job"]
check("the job runs the chosen agent in that folder, not isolated (it is the owner's game, not a repo)",
      job["backend"] == "local" and job["agent"] == "codex" and job["workspace"] == str(ws) and job["isolate"] is False)
check("the prompt points the agent at godogen's files", "AGENTS.md" in job["prompt"] and "godot-gdscript.md" in job["prompt"]
      and "Ask before any paid asset generation" in job["prompt"])
sup = workers.Supervisor(workers.JobStore(TMP / "jobs" / "jobs.json"), {"local": workers.LocalBackend(TMP / "jobs", which=lambda e: None)},
                         TMP / "jobs")
queued = sup.create(job)
check("the job spec is one the job supervisor accepts", queued["status"] == "queued" and queued["agent"] == "codex", queued)
check("its command line is an argument list with the prompt as one argument",
      workers.agent_argv("codex", job["prompt"])[-1] == job["prompt"])
named = godogen.make_godot_game("space shooter", "My Shooter!", engine="godot", agent="claude-code", env=env, runner=fake_git)
check("a given name and the C# engine", named["name"] == "my-shooter" and (Path(named["workspace"]) / "CLAUDE.md").is_file()
      and (Path(named["workspace"]) / "godot.md").is_file())
other = TMP / "LOKI Projects" / "taken"
other.mkdir(parents=True)
(other / "notes.txt").write_text("mine", encoding="utf-8")
try:
    godogen.make_godot_game("x", "taken", env=env, which=none, runner=fake_git)
    check("never writes into someone's existing folder", False)
except godogen.GodogenError:
    check("never writes into someone's existing folder", (other / "notes.txt").read_text(encoding="utf-8") == "mine"
          and not (other / "AGENTS.md").exists())
for bad in ({"description": ""}, {"description": "x" * 5000}, {"description": "x", "engine": "unity"}, {"description": "x", "agent": "rm"}):
    try:
        godogen.plan_game(env=env, which=none, **bad)
        check("refuses %s" % list(bad.items())[-1][0], False)
    except godogen.GodogenError:
        check("refuses bad %s" % list(bad.items())[-1][0], True)
check("slug keeps folder names safe", godogen.slug("../../etc/passwd") == "etc-passwd" and godogen.slug("!!!") == "game")

section("make_godot_game in the engine (policy + loki.py)")
check("the tool needs the godogen add-on", policy.CAPABILITY_TOOLS.get("make_godot_game") == "godogen")
check("and always asks first", "make_godot_game" in policy.ALWAYS_ASK)
tree = ast.parse(read("engine/loki.py"))
defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
loki_src = read("engine/loki.py")
check("loki.py registers the tool, its schema and Plan-mode exclusion", "make_godot_game" in defs
      and 'LOCAL_TOOLS["make_godot_game"] = make_godot_game' in loki_src and 'DELEGATING |= {"make_godot_game"}' in loki_src
      and "POLICY.job(spec[\"backend\"], spec[\"agent\"])" in loki_src)
if importlib.util.find_spec("openai") is not None:
    import loki  # noqa: E402
    check("live: the tool is offered with its schema", "make_godot_game" in loki.LOCAL_TOOLS
          and any(t["function"]["name"] == "make_godot_game" for t in loki.MODEL_TOOL_SCHEMAS))
    check("live: denied while the add-on is off", not loki.POLICY.tool_call("make_godot_game", {"description": "x"}).allowed)
else:
    print("  (openai not installed here: the live loki.py checks are skipped)")

# ------------------------------------------------------------------ nanocoder
section("Nanocoder as a job / saved-agent engine")
check("an agent everywhere agents are listed", "nanocoder" in workers.AGENTS and "nanocoder" in agents.ENGINES
      and "nanocoder" in agents.ENGINE_LABELS)
check("its jobs need the nanocoder add-on", policy.AGENT_CAPABILITY.get("nanocoder") == "nanocoder")
argv = workers.agent_argv("nanocoder", "fix the bug; rm -rf /", env={})
check("one-shot command line: auto-accept, trusted job folder, plain output, the prompt as one argument",
      argv == ["nanocoder", "--mode", "auto-accept", "--trust-directory", "--plain", "run", "fix the bug; rm -rf /"], argv)
argv = workers.agent_argv("nanocoder", "go", env={"LOKI_NANOCODER_PROVIDER": "ollama", "LOKI_NANOCODER_MODEL": "qwen3:8b"})
check("provider and model from LOKI_NANOCODER_*", argv[:5] == ["nanocoder", "--provider", "ollama", "--model", "qwen3:8b"], argv)
check("never yolo", "yolo" not in workers.agent_argv("nanocoder", "x", env={}))
check("interactive (herdr pane) is just the CLI", workers.agent_argv("nanocoder", "", interactive=True, env={}) == ["nanocoder"])

spec_x = importlib.util.spec_from_file_location("_setup_extras", REPO / "tools" / "setup_extras.py")
extras = importlib.util.module_from_spec(spec_x)
spec_x.loader.exec_module(extras)
check("setup_extras: wechaty and nanocoder are opt-in, by name only",
      {"wechaty", "nanocoder"} <= set(extras.OPT_IN) and not ({"wechaty", "nanocoder"} & set(extras.STEPS)))
check("nanocoder install: a pinned npm package, argument list", extras.nanocoder_argv("npm") ==
      ["npm", "i", "-g", "@nanocollective/nanocoder@1.31.0"])
wargv = extras.wechaty_argv("npm", TMP / "addons" / "wechaty")
check("wechaty install: into LOKI's data folder, pinned, no install scripts",
      wargv[:4] == ["npm", "install", "--prefix", str(TMP / "addons" / "wechaty")] and "--ignore-scripts" in wargv
      and "wechaty@1.20.2" in wargv and all("@" in p for p in wargv if p.startswith("wechaty")), wargv)

# ------------------------------------------------------------------ Cozy Blanket
section("Cozy Blanket: research only (commercial, closed source)")
notes = read("docs/research/COZY_BLANKET.md")
check("the research notes say what it is and that nothing is copied", "Sparseal" in notes and "copies nothing" in notes
      and "Uniform" in notes and "Godot 4 C++ module" in notes)
check("and give Forge a concrete feature list", notes.count("\n1. ") == 1 and "Retopo" in notes and "LSCM" in notes)
evolve = read("docs/EVOLVE.md")
check("one roadmap line, E22, open", "- [ ] E22 Forge retopology" in evolve and evolve.count(" E22 ") == 1)
check("no Cozy Blanket code or assets in the repo", not any("cozy" in p.name.lower() for p in (REPO / "app").rglob("*")))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
