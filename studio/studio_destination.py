"""Where is this going? - the Destination of a LOKI Studio project (docs/STUDIO.md "Where is this going?").

The owner (2026-10-17): "when loki is in someone else's hands the studio creates a new repo and a new app starts
getting developed ... you should have the option to choose where it's going". Four answers:

  loki   Improve LOKI itself   m03dev/loki master through tools/ship.py - the owner's case, exactly as before
  fork   My own LOKI           a fork on the user's GitHub (`gh repo fork`): origin = the fork, upstream = m03dev/loki;
                               ship.py then pushes to the fork (and the updater follows the fork)
  app    A new app from LOKI   a NEW repository (`gh repo create`) in ~/LOKI Projects/<name>: a small app skeleton with a
                               COPY of LOKI's engine/ (see NOTICE.md there), its own README and the AGPL licence
  local  Just this computer    ~/LOKI Projects/<name>: a local git clone of LOKI with no remote; Ship it commits there

Who is asking: the account signed in to the GitHub CLI (`gh`). Not m03dev -> the question defaults to "My own LOKI",
"Improve LOKI itself" is refused, and nothing is ever shipped to m03dev/loki from that machine (guard()).

Every git/gh call is an argv list (no shell strings, like engine/safe_exec.py) through one runner, so the tests drive
it with a fake gh/git and it works the same on macOS and Windows (gh.exe / git.exe are found with shutil.which).
The choice lives in harness_data/studio/destination.json; each session also records its own at creation.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

OWNER = "m03dev"
UPSTREAM = "m03dev/loki"
UPSTREAM_URL = "https://github.com/m03dev/loki.git"
KINDS = {
    "loki": ("Improve LOKI itself", "Work on m03dev/loki master and ship with tools/ship.py - for LOKI's owner."),
    "fork": ("My own LOKI", "Your own fork of LOKI on your GitHub; Ship it pushes to your fork, LOKI stays the upstream."),
    "app": ("A new app from LOKI", "A new repository in ~/LOKI Projects/<name>, started from LOKI's engine; Studio develops that app."),
    "local": ("Just this computer", "A local git copy of LOKI in ~/LOKI Projects/<name>; nothing goes to GitHub."),
}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
FILE = "destination.json"
_CACHE: dict = {}

Runner = Callable[..., tuple]


# ------------------------------------------------------------------ running git / gh (argv only, never a shell)
def run(argv: list, cwd: str | Path | None = None, timeout: float = 60.0) -> tuple:
    """(returncode, stdout+stderr). argv[0] is "git" or "gh"; found on PATH (git.exe/gh.exe on Windows)."""
    if not isinstance(argv, (list, tuple)) or not argv:
        raise ValueError("argv must be a non-empty list (no shell strings)")
    exe = shutil.which(str(argv[0]))
    if not exe:
        return 127, "%s is not installed" % argv[0]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GCM_INTERACTIVE="never")
    try:
        proc = subprocess.run([exe, *[str(a) for a in argv[1:]]], cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
                              stdin=subprocess.DEVNULL, shell=False)
    except subprocess.TimeoutExpired:
        return 124, "%s %s timed out" % (argv[0], argv[1] if len(argv) > 1 else "")
    except OSError as exc:
        return 126, str(exc)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def git(repo: str | Path, *args: str, runner: Runner = run, timeout: float = 120.0) -> tuple:
    return runner(["git", "-C", str(repo), *args], timeout=timeout)


# ------------------------------------------------------------------ who, and where this checkout points
def slug(url: str) -> str:
    """owner/name from a GitHub URL (https or ssh), lower-cased; "" when it is not GitHub."""
    m = re.search(r"github\.com[:/]+([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$", str(url or "").strip())
    return ("%s/%s" % (m.group(1), m.group(2))).lower() if m else ""


def origin(repo: str | Path, runner: Runner = run) -> str:
    code, out = git(repo, "remote", "get-url", "origin", runner=runner, timeout=20)
    return slug(out.splitlines()[-1]) if code == 0 and out else ""


def gh_user(runner: Runner = run) -> str:
    """The GitHub account signed in to gh, or "" (gh missing or not signed in)."""
    code, out = runner(["gh", "api", "user", "--jq", ".login"], timeout=20)
    login = out.strip().splitlines()[-1].strip() if code == 0 and out.strip() else ""
    if re.fullmatch(r"[A-Za-z0-9-]{1,39}", login or ""):
        return login
    code, out = runner(["gh", "auth", "status", "--hostname", "github.com"], timeout=20)
    m = re.search(r"account\s+([A-Za-z0-9-]{1,39})", out or "") if code == 0 else None
    return m.group(1) if m else ""


def default_kind(user: str) -> str:
    """The owner gets "loki"; anyone else (or someone gh does not know) gets "fork"."""
    return "loki" if user and user.lower() == OWNER else "fork"


def detect(repo: str | Path, runner: Runner = run, max_age: float = 300.0) -> dict:
    key = (str(repo), id(runner))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < max_age:
        return dict(hit[1])
    user = gh_user(runner)
    out = {"gh_user": user, "gh_ready": bool(user), "origin": origin(repo, runner),
           "is_owner": bool(user) and user.lower() == OWNER, "owner": OWNER, "upstream": UPSTREAM,
           "default": default_kind(user), "kinds": [{"id": k, "name": v[0], "what": v[1]} for k, v in KINDS.items()]}
    out["can_improve_loki"] = not user or out["is_owner"]
    _CACHE[key] = (time.time(), out)
    return dict(out)


def forget_cache() -> None:
    _CACHE.clear()


# ------------------------------------------------------------------ the stored choice
def load(home: str | Path) -> dict:
    try:
        data = json.loads((Path(home) / FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data.get("kind") in KINDS else {}
    except (OSError, ValueError):
        return {}


def save(home: str | Path, choice: dict) -> dict:
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / FILE).write_text(json.dumps(choice, indent=1), encoding="utf-8")
    return choice


def work_repo(choice: dict, loki_repo: str | Path) -> Path:
    """The git repository Studio's sessions branch from: the new app / the local copy, else LOKI's checkout."""
    if choice.get("kind") in ("app", "local") and choice.get("path"):
        return Path(choice["path"])
    return Path(loki_repo)


def projects_dir() -> Path:
    return Path(os.getenv("LOKI_PROJECTS_DIR") or (Path.home() / "LOKI Projects"))


# ------------------------------------------------------------------ the guard (every Ship it goes through it)
def guard(kind: str, origin_slug: str, user: str) -> str:
    """"" when shipping may go ahead, else why not. Never lets a non-owner ship to m03dev/loki."""
    kind = str(kind or "")
    target = str(origin_slug or "").lower()
    non_owner = bool(user) and user.lower() != OWNER
    if kind not in KINDS:
        return "Choose where this is going first (the \"Where is this going?\" card in Studio's rail)."
    if kind == "loki":
        if non_owner:
            return ("Only %s ships to %s - you are signed in to GitHub as %s. Choose \"My own LOKI\" or \"A new app "
                    "from LOKI\" under \"Where is this going?\"." % (OWNER, UPSTREAM, user))
        if target and target != UPSTREAM:
            return "\"Improve LOKI itself\" ships to %s, but this checkout's origin is %s." % (UPSTREAM, target or "not GitHub")
        return ""
    if target == UPSTREAM:
        return ("This %s still points at %s - Studio never ships it there. Set it up again under \"Where is this going?\"."
                % (KINDS[kind][0], UPSTREAM))
    if kind == "fork" and not target:
        return "\"My own LOKI\" needs your fork as origin - set it up under \"Where is this going?\"."
    return ""


# ------------------------------------------------------------------ setting a destination up
def choose(home: str | Path, loki_repo: str | Path, kind: str, name: str = "", visibility: str = "private",
           runner: Runner = run, user: str | None = None, base: Path | None = None) -> dict:
    """Set up `kind` and store it. {"ok", "choice", "note"} or {"ok": False, "error", "how"?}."""
    kind = str(kind or "")
    if kind not in KINDS:
        return {"ok": False, "error": "kind is one of %s" % ", ".join(KINDS)}
    user = gh_user(runner) if user is None else user
    repo = Path(loki_repo)
    choice = {"kind": kind, "name": KINDS[kind][0], "chosen_at": time.time(), "gh_user": user}
    if kind == "loki":
        if user and user.lower() != OWNER:
            return {"ok": False, "error": "Only %s can improve %s itself from Studio (you are %s). Choose \"My own LOKI\" "
                    "or \"A new app from LOKI\"." % (OWNER, UPSTREAM, user)}
        choice.update(repo=UPSTREAM, path=str(repo))
        note = "Studio works on %s and ships with tools/ship.py, as before." % UPSTREAM
    elif kind == "fork":
        res = setup_fork(repo, user, runner)
        if not res.get("ok"):
            return res
        choice.update(repo=res["fork"], path=str(repo))
        note = res["note"]
    else:
        name = str(name or "").strip()
        if not NAME.match(name):
            return {"ok": False, "error": "give a name: letters, digits, '.', '-' or '_' (up to 100), e.g. my-agent"}
        target = Path(base or projects_dir()) / name
        if target.exists() and any(target.iterdir()):
            return {"ok": False, "error": "%s already exists and is not empty - pick another name" % target}
        res = (create_app if kind == "app" else create_local)(repo, target, name, runner=runner, user=user,
                                                              visibility=visibility)
        if not res.get("ok"):
            return res
        choice.update(path=str(target), project=name, repo=res.get("repo", ""), branch=res.get("branch", "main"),
                      visibility=visibility if kind == "app" else "")
        note = res["note"]
    save(home, choice)
    forget_cache()
    return {"ok": True, "choice": choice, "note": note}


GH_HOW = ("Install the GitHub CLI (cli.github.com), run `gh auth login` once in a terminal, then choose again here.")


def setup_fork(repo: Path, user: str, runner: Runner = run) -> dict:
    if not user:
        return {"ok": False, "error": "gh is not signed in, so Studio cannot make your fork.",
                "how": GH_HOW + " Or by hand: press Fork on github.com/%s, then in the LOKI folder: "
                "`git remote rename origin upstream` and `git remote add origin https://github.com/<you>/loki.git`." % UPSTREAM}
    if user.lower() == OWNER:
        return {"ok": False, "error": "%s is your own repository - choose \"Improve LOKI itself\"." % UPSTREAM}
    code, out = runner(["gh", "repo", "fork", UPSTREAM, "--clone=false", "--remote=false"], timeout=120)
    if code != 0 and "already exists" not in out.lower():
        return {"ok": False, "error": "gh could not fork %s: %s" % (UPSTREAM, out[-300:])}
    fork = "%s/loki" % user
    fork_url = "https://github.com/%s.git" % fork
    code, remotes = git(repo, "remote", runner=runner, timeout=20)
    names = set(remotes.split()) if code == 0 else set()
    steps = []
    if "upstream" not in names:
        steps.append(("remote", "add", "upstream", UPSTREAM_URL))
    steps.append(("remote", "set-url", "origin", fork_url) if "origin" in names else ("remote", "add", "origin", fork_url))
    for step in steps:
        code, out = git(repo, *step, runner=runner, timeout=20)
        if code != 0:
            return {"ok": False, "error": "git %s failed: %s" % (" ".join(step[:2]), out[-300:])}
    return {"ok": True, "fork": fork.lower(),
            "note": "Your fork %s is origin now and %s is upstream. Ship it pushes to your fork; LOKI updates from it." % (fork, UPSTREAM)}


def _commit_identity(cwd: Path, runner: Runner) -> list:
    code, out = git(cwd, "config", "user.email", runner=runner, timeout=20)
    return [] if code == 0 and out.strip() else ["-c", "user.name=LOKI Studio", "-c", "user.email=studio@localhost"]


def _init_and_commit(target: Path, message: str, runner: Runner) -> tuple:
    for step in (("init",), ("symbolic-ref", "HEAD", "refs/heads/main"), ("add", "-A")):
        code, out = git(target, *step, runner=runner)
        if code != 0:
            return False, "git %s failed: %s" % (step[0], out[-300:])
    code, out = git(target, *_commit_identity(target, runner), "commit", "-q", "-m", message, runner=runner)
    return (code == 0), out


def repo_create_argv(name: str, visibility: str, source: Path) -> list:
    """The `gh repo create` command line - a list, never a shell string."""
    if not NAME.match(str(name or "")):
        raise ValueError("bad repository name %r" % name)
    flag = "--public" if visibility == "public" else "--private"
    return ["gh", "repo", "create", name, flag, "--source", str(source), "--remote", "origin", "--push",
            "--description", "%s - an app made with LOKI Studio from LOKI's engine (AGPL-3.0)" % name]


def create_app(loki_repo: Path, target: Path, name: str, runner: Runner = run, user: str = "",
               visibility: str = "private") -> dict:
    """A new app: the skeleton + a copy of LOKI's engine/ + LOKI's licence, its own git repo, then `gh repo create`."""
    code, files = git(loki_repo, "ls-files", "engine", runner=runner)
    if code != 0:
        return {"ok": False, "error": "could not list LOKI's engine files: %s" % files[-300:]}
    _, head = git(loki_repo, "rev-parse", "--short=12", "HEAD", runner=runner)
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for rel in [f.strip() for f in files.splitlines() if f.strip()]:
        src = Path(loki_repo) / rel
        if src.is_file() and "harness_data" not in rel and not rel.endswith((".env", ".token")):
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    lic = Path(loki_repo) / "LICENSE"
    if lic.is_file():
        shutil.copy2(lic, target / "LICENSE")
    for rel, text in skeleton(name, head.strip() or "unknown").items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    ok, out = _init_and_commit(target, "%s: start from LOKI's engine (%s)" % (name, head.strip()), runner)
    if not ok:
        return {"ok": False, "error": "could not make the first commit: %s" % out[-300:]}
    note = "%s is ready in %s (%d engine files copied from LOKI %s)." % (name, target, copied, head.strip())
    if not user:
        return {"ok": True, "repo": "", "branch": "main",
                "note": note + " It is only on this computer until gh is signed in: " + GH_HOW +
                " Then: `gh repo create %s --private --source \"%s\" --remote origin --push`." % (name, target)}
    code, out = runner(repo_create_argv(name, visibility, target), timeout=180)
    if code != 0:
        return {"ok": True, "repo": "", "branch": "main",
                "note": note + " GitHub said no (%s); it stays on this computer for now." % out[-200:]}
    return {"ok": True, "repo": ("%s/%s" % (user, name)).lower(), "branch": "main",
            "note": note + " New %s repository github.com/%s/%s." % (visibility if visibility == "public" else "private", user, name)}


def create_local(loki_repo: Path, target: Path, name: str, runner: Runner = run, **_kw) -> dict:
    """A local git copy of LOKI with no remote: nothing ever goes to GitHub."""
    target.parent.mkdir(parents=True, exist_ok=True)
    code, out = runner(["git", "clone", "-q", "--no-hardlinks", str(loki_repo), str(target)], timeout=600)
    if code != 0:
        return {"ok": False, "error": "git clone failed: %s" % out[-300:]}
    git(target, "remote", "remove", "origin", runner=runner, timeout=20)
    _, branch = git(target, "symbolic-ref", "--short", "HEAD", runner=runner, timeout=20)
    return {"ok": True, "repo": "", "branch": (branch.strip() or "master"),
            "note": "A local copy of LOKI is in %s (no GitHub). Ship it commits there after the tests pass." % target}


# ------------------------------------------------------------------ Ship it for app / local (loki and fork use tools/ship.py)
def publish(kind: str, tree: Path, repo: Path, branch: str, message: str, runner: Runner = run) -> str:
    """Commit the session's worktree, fast-forward the project's main branch to it, push an app to its origin."""
    code, out = git(tree, "add", "-A", runner=runner)
    if code != 0:
        return "NOT shipped:\ngit add failed: %s" % out[-300:]
    code, out = git(tree, *_commit_identity(tree, runner), "commit", "-q", "-m", message, runner=runner)
    if code != 0 and "nothing to commit" not in out:
        return "NOT shipped:\ngit commit failed: %s" % out[-300:]
    code, out = git(repo, "merge", "--ff-only", branch, runner=runner)
    if code != 0:
        return "NOT shipped:\ncould not bring %s into %s (local edits there?): %s" % (branch, repo, out[-300:])
    lines = ["committed and merged into %s" % repo]
    if kind == "app" and origin(repo, runner):
        if origin(repo, runner) == UPSTREAM:
            return "NOT shipped:\n" + guard(kind, UPSTREAM, "")
        _, main = git(repo, "symbolic-ref", "--short", "HEAD", runner=runner, timeout=20)
        code, out = git(repo, "push", "-q", "origin", "HEAD:refs/heads/%s" % (main.strip() or "main"), runner=runner, timeout=300)
        if code != 0:
            return "NOT shipped:\ncommitted locally, but the push failed: %s" % out[-300:]
        lines.append("pushed to %s" % origin(repo, runner))
    return "shipped:\n" + "\n".join(lines)


# ------------------------------------------------------------------ the app skeleton
def skeleton(name: str, loki_commit: str) -> dict:
    return {
        "README.md": f"""# {name}

An app made with **LOKI Studio**, started from the engine of [LOKI](https://github.com/{UPSTREAM})
(commit `{loki_commit}`).

- `app/main.py` - the app. Run it: `python app/main.py`
- `engine/` - a **copy** of LOKI's Python engine (see NOTICE.md). Use any module from it: `app/main.py` puts it on
  `sys.path`. To take a newer LOKI engine, copy `engine/` again from a LOKI checkout.
- `tests/` - `python tools/ship.py --check` runs them (LOKI Studio's Tests button does the same).

Develop it in LOKI Studio: it was created by Studio's "Where is this going? -> A new app from LOKI".

Licence: GNU AGPL-3.0 (LICENSE), like LOKI.
""",
        "NOTICE.md": f"""# Notice

`engine/` is copied from LOKI (https://github.com/{UPSTREAM}, commit `{loki_commit}`),
Copyright (C) 2026 m03dev and LOKI contributors, under the GNU AGPL-3.0 (LICENSE). Parts of it come from other
projects under their own compatible licences; their texts are in `engine/licenses/`.
This app is a modified version of that work and is distributed under the same licence. If people use it over a
network, offer them its source (AGPL-3.0 section 13).
""",
        "AGENTS.md": f"""# AGENTS.md - rules for agents working on {name}

- This is {name}, an app built from a copy of LOKI's engine (engine/). It is NOT LOKI: do not ship it to {UPSTREAM}.
- macOS and Windows from the same code: pathlib, both sides of every sys.platform branch, no shell strings.
- Small steps; add a test in tests/ for what you change; `python tools/ship.py --check` must pass.
- Never commit keys, tokens, .env files or personal data. Licence: AGPL-3.0 - take code only under compatible licences.
""",
        ".gitignore": "__pycache__/\n*.pyc\n.env\n*.token\nharness_data/\n.venv/\n",
        "app/__init__.py": "",
        "app/main.py": f'''"""{name} - started from LOKI's engine (engine/ is a copy of LOKI's; see NOTICE.md)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))


def hello() -> str:
    import safe_exec  # noqa: F401  LOKI's no-shell command runner - one of the engine pieces this app can use
    return "{name} is running on LOKI's engine (%s)." % ENGINE


def main(argv=None) -> int:
    print(hello())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
        "tests/test_app.py": f'''"""{name}'s first test: the app starts and finds LOKI's engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import main  # noqa: E402

assert "{name}" in main.hello(), main.hello()
assert (main.ENGINE / "safe_exec.py").is_file()
print("1 passed, 0 failed")
''',
        "tools/ship.py": '''"""Tests for this app: `python tools/ship.py --check [--repo DIR] [--only test_x]` runs tests/test_*.py.
LOKI Studio's Tests button and its agent's run_tests call it; Studio's Ship it commits and pushes."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--only", default="")
    ap.add_argument("-m", "--message", default="")
    args = ap.parse_args(argv)
    if not args.check:
        print("Ship from LOKI Studio (the Ship it button); this script only runs the tests (--check).")
        return 2
    wanted = {w for w in args.only.split(",") if w}
    failed = 0
    for test in sorted((Path(args.repo) / "tests").glob("test_*.py")):
        if wanted and test.stem not in wanted:
            continue
        try:
            p = subprocess.run([sys.executable, str(test)], capture_output=True, text=True, timeout=60, cwd=args.repo)
            ok, out = p.returncode == 0, (p.stdout + p.stderr)[-1500:]
        except subprocess.TimeoutExpired:
            ok, out = False, "took over 60 s"
        print(("PASS " if ok else "FAIL ") + test.name + ("" if ok else "\\n" + out))
        failed += 0 if ok else 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    }
