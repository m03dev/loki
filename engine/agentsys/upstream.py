"""Upstream: where every piece of open-source code in LOKI came from, and what changed there since (owner 2026-10-28:
"most of our code is from opensource and public repos you need to have a schedule task for loki to always check
where he got what hes using and seeing if they made updates thats why hes also improving").

The registry is built from what LOKI already writes down, never guessed:
  - docs/THIRD_PARTY.md         every row with a github.com link; a pinned commit (`abc1234`, "commit abc1234") or
                                a version (v1.6.2, r186, 2.2.4) found in the same row
  - engine/ecc_sync.py SOURCES  the agent / skill / prompt libraries (they follow a branch; the marker says when)
  - PROVENANCE.md / README.md   under contrib/ and engine/vendor_subagents/ (pinned commits)
  - engine/*.py docstrings      "Ported from <owner>/<repo>" lines (the code LOKI re-wrote from a project)
  - engine/toolshelf/*.json     installable tools with a repo and a tag
One entry per repository, with every place in LOKI that uses it.

The check (the autopilot's "upstream" duty, once a day, LOKI_UPSTREAM_S; or Lab > Upstream > Check now) asks GitHub's
API for each repo: the default branch head, the latest release, archived / moved, and - when LOKI pinned a commit -
how many commits it is behind (compare). A token (GITHUB_TOKEN / LOKI_GITHUB_TOKEN / gh's) lifts GitHub's 60-calls-
an-hour limit; without one it checks LOKI_UPSTREAM_BATCH (12) repos per run, the least recently checked first.

What changed goes into <data>/reports/upstream.md and, for each repo with something NEW since the last check, into
Home > For you as an "upstream" card: Adopt (a LOKI agent reviews the changes, ports what improves LOKI, updates the
pin, runs the tests and ships - rule 8: it asks first, the card is the ask), Skip (this version), or Not now.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import sub

REPO_ROOT = Path(__file__).resolve().parents[2]
_GH = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?=[/)\]#?\s`'\",]|$)")
_SLUG = re.compile(r"(?<![\w/.-])([A-Za-z0-9_-]{2,39})/([A-Za-z0-9_.-]{2,100})(?![\w/-])")
_COMMIT = re.compile(r"(?:commit|at|@|\()\s*`?([0-9a-f]{7,40})`?", re.I)
_VERSION = re.compile(r"(?<![\w.-])(v?\d+\.\d+(?:\.\d+)?(?:-(?:beta|rc|alpha|docking)[a-z0-9.]*)?|r\d{3})(?![\w.-])", re.I)
_SKIP_OWNERS = {"github", "user-attachments", "orgs", "settings", "features", "topics", "sponsors", "marketplace",
                "engine", "app", "docs", "tools", "tests", "native", "contrib", "skills", "harness_data", "packaging",
                "studio", "mobile", "capabilities", "keys", "third_party", "vendor", "licenses", "ui", "src", "runners",
                "examples", "include", "lib", "scripts", "data", "assets", "plugins", "categories", "agents"}


def _norm(owner: str, repo: str) -> str:
    return "%s/%s" % (owner, re.sub(r"\.git$", "", repo).rstrip("."))


def _add(reg: dict, slug: str, where: str, pin: str = "", version: str = "", follows: str = "", licence: str = "") -> None:
    owner = slug.split("/")[0].lower()
    if owner in _SKIP_OWNERS or slug.lower() == "m03dev/loki":      # LOKI itself is not an upstream
        return
    e = reg.setdefault(slug.lower(), {"repo": slug, "used_in": [], "pin": "", "version": "", "follows": "",
                                      "licence": ""})
    if where and where not in e["used_in"]:
        e["used_in"].append(where)
    e["pin"] = e["pin"] or pin
    e["version"] = e["version"] or version
    e["follows"] = e["follows"] or follows
    e["licence"] = e["licence"] or licence


def _third_party(reg: dict, root: Path) -> None:
    p = root / "docs" / "THIRD_PARTY.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        if not line.startswith("|") or "github.com" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        where = re.sub(r"[`*]", "", cells[0])[:160] if cells else "docs/THIRD_PARTY.md"
        lic = re.sub(r"\s+-\s+`.*$", "", cells[-1])[:60] if len(cells) >= 3 else ""
        body = " | ".join(cells[:-1]) if len(cells) >= 3 else line     # versions never from the licence column
        links = list(_GH.finditer(body))
        for i, m in enumerate(links):     # a pin / version belongs to the link right before it, not a neighbour's
            end = min(links[i + 1].start() if i + 1 < len(links) else len(body), m.end() + 140)
            seg = body[m.start(): end]
            cut = re.search(r"\)[,;] |; ", seg[m.end() - m.start():])     # ... and to its own clause
            seg = seg[:m.end() - m.start() + cut.start()] if cut else seg
            pin = next((c.group(1) for c in _COMMIT.finditer(seg)), "")
            ver = next((v.group(1) for v in _VERSION.finditer(seg)), "")
            _add(reg, _norm(m.group(1), m.group(2)), where, pin=pin, version=ver, licence=lic)


def _ecc(reg: dict) -> None:
    try:
        import ecc_sync  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        return
    for name, spec in ecc_sync.SOURCES.items():
        marker = ecc_sync.VENDOR / name / ".loki_sync.json"
        follows = "branch (downloaded %s)" % "never"
        sha = ""
        try:
            m = json.loads(marker.read_text(encoding="utf-8"))
            follows = "branch (downloaded %s)" % time.strftime("%Y-%m-%d", time.localtime(float(m.get("when") or 0)))
            sha = str(m.get("sha") or "")
        except (OSError, ValueError):
            pass
        _add(reg, spec["repo"], "harness_data/vendor/%s (engine/ecc_sync.py)" % name, pin=sha, follows=follows)


def _provenance(reg: dict, root: Path) -> None:
    files = list((root / "contrib").glob("*/PROVENANCE.md")) + list((root / "contrib").glob("*/README.md")) + \
        [root / "engine" / "vendor_subagents" / "README.md"]
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")[:6000]
        except OSError:
            continue
        rel = str(p.relative_to(root))
        for m in list(_GH.finditer(text)) or []:
            seg = text[m.start(): m.start() + 300]
            _add(reg, _norm(m.group(1), m.group(2)), rel, pin=next((c.group(1) for c in _COMMIT.finditer(seg)), ""))
        if "vendor_subagents" in rel:
            m = re.search(r"from ([\w.-]+/[\w.-]+)[^\n]*?commit ([0-9a-f]{7,40})", text)
            if m:
                _add(reg, m.group(1), rel, pin=m.group(2))


def _docstrings(reg: dict, root: Path) -> None:
    for p in sorted((root / "engine").glob("*.py")):
        try:
            head = p.read_text(encoding="utf-8")[:3000]
        except OSError:
            continue
        if not re.search(r"(ported|vendored|copied|taken|re-?written) from|github\.com/", head, re.I):
            continue
        rel = "engine/" + p.name
        for m in _GH.finditer(head):
            _add(reg, _norm(m.group(1), m.group(2)), rel)
        for m in re.finditer(r"(?:ported|vendored|copied|taken|re-?written|idea and flow are) from[^\n(]*?\(?"
                             r"([A-Za-z0-9_-]{2,39}/[A-Za-z0-9_.-]{2,100})", head, re.I):
            slug = m.group(1).rstrip(".,)")
            if "/" in slug and not slug.endswith((".py", ".md", ".js")):
                _add(reg, slug, rel)


def _toolshelf(reg: dict, root: Path) -> None:
    for p in (root / "engine" / "toolshelf").glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data if isinstance(data, list) else data.get("tools") or data.get("items") or [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            blob = json.dumps(it)
            for m in _GH.finditer(blob):
                _add(reg, _norm(m.group(1), m.group(2)), "engine/toolshelf/" + p.name,
                     version=str(it.get("tag") or it.get("version") or ""))


def registry(root: Path | None = None) -> list:
    root = root or REPO_ROOT
    reg: dict = {}
    _third_party(reg, root)
    _provenance(reg, root)
    _ecc(reg)
    _docstrings(reg, root)
    _toolshelf(reg, root)
    return sorted(reg.values(), key=lambda e: e["repo"].lower())


# ----------------------------------------------------------------------------- the check
def state_path() -> Path:
    return sub("upstream") / "state.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"repos": {}, "last_run": 0}


def save_state(st: dict) -> None:
    p = state_path()
    tmp = p.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def token() -> str:
    for name in ("LOKI_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _get(url: str, tok: str = "") -> tuple:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "loki-upstream",
               "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        headers["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "null")
        except ValueError:
            body = None
        return e.code, body, dict(e.headers or {})
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {"error": str(e)[:200]}, {}


def check_one(entry: dict, get: Callable = _get, tok: str = "") -> dict:
    """GitHub's view of one repo. Uses 2-4 API calls."""
    slug = entry["repo"]
    api = "https://api.github.com/repos/" + slug
    code, repo, headers = get(api, tok)
    if code != 200 or not isinstance(repo, dict):
        msg = (repo or {}).get("message", "") if isinstance(repo, dict) else ""
        limited = code == 429 or (code == 403 and ("rate limit" in str(msg).lower()
                                                   or str((headers or {}).get("X-RateLimit-Remaining", "")) == "0"))
        return {"ok": False, "code": code, "error": str(msg)[:200], "rate_limited": limited}
    out = {"ok": True, "full_name": repo.get("full_name") or slug, "archived": bool(repo.get("archived")),
           "branch": repo.get("default_branch") or "main", "pushed_at": repo.get("pushed_at") or "",
           "moved": (repo.get("full_name") or slug).lower() != slug.lower(), "stars": repo.get("stargazers_count", 0),
           "licence": ((repo.get("license") or {}).get("spdx_id") or "")}
    code, head, _ = get("%s/commits/%s" % (api, out["branch"]), tok)
    if code == 200 and isinstance(head, dict):
        out["head"] = (head.get("sha") or "")[:12]
        out["head_date"] = ((head.get("commit") or {}).get("committer") or {}).get("date", "")
        out["head_msg"] = ((head.get("commit") or {}).get("message") or "").split("\n")[0][:160]
    code, rel, _ = get(api + "/releases/latest", tok)
    if code == 200 and isinstance(rel, dict):
        out["release"] = rel.get("tag_name") or ""
        out["release_date"] = rel.get("published_at") or ""
    if entry.get("pin") and out.get("head") and not out["head"].startswith(entry["pin"][:7]):
        code, cmp_, _ = get("%s/compare/%s...%s" % (api, entry["pin"], out["branch"]), tok)
        if code == 200 and isinstance(cmp_, dict):
            out["behind"] = int(cmp_.get("ahead_by") or 0)
            out["changes"] = [((c.get("commit") or {}).get("message") or "").split("\n")[0][:140]
                              for c in (cmp_.get("commits") or [])[-8:]]
            out["compare_url"] = "https://github.com/%s/compare/%s...%s" % (slug, entry["pin"], out["branch"])
    elif entry.get("pin") and out.get("head"):
        out["behind"] = 0
    return out


def status_of(entry: dict, seen: dict) -> str:
    if not seen.get("ok"):
        return "unreachable"
    if seen.get("archived"):
        return "archived"
    if seen.get("moved"):
        return "moved"
    if entry.get("pin"):
        return "behind" if int(seen.get("behind") or 0) > 0 else "current"
    if entry.get("version") and seen.get("release") and seen["release"].lstrip("v") != entry["version"].lstrip("v"):
        return "new release"
    return "follows branch" if entry.get("follows") else "not pinned"


def check(limit: int | None = None, get: Callable = _get, now: float | None = None, root: Path | None = None) -> dict:
    """One pass: the least recently checked repos first. Returns {"checked", "new": [...], "report"}."""
    now = now or time.time()
    tok = token() if get is _get else ""
    limit = int(limit if limit is not None else os.environ.get("LOKI_UPSTREAM_BATCH", "") or (80 if tok else 12))
    st = load_state()
    reg = registry(root)
    order = sorted(reg, key=lambda e: float((st["repos"].get(e["repo"].lower()) or {}).get("checked") or 0))
    new = []
    checked = 0
    offline = 0
    for e in order[:limit]:
        key = e["repo"].lower()
        prev = st["repos"].get(key) or {}
        seen = check_one(e, get, tok)
        if seen.get("rate_limited"):                 # GitHub's hourly limit: stop this pass, the rest next time
            break
        offline = offline + 1 if seen.get("code") == 0 else 0
        if offline >= 2:                             # no network: don't spend minutes finding that out per repo
            break
        checked += 1
        status = status_of(e, seen)
        mark = "%s|%s|%s" % (seen.get("head", ""), seen.get("release", ""), status)
        rec = {**seen, "checked": now, "status": status, "mark": mark,
               "notified": prev.get("notified", ""), "skipped": prev.get("skipped", "")}
        if status in ("behind", "new release", "archived", "moved") and mark != prev.get("notified") \
                and mark != prev.get("skipped"):
            rec["notified"] = mark
            new.append({"entry": e, "seen": seen, "status": status})
        st["repos"][key] = rec
    st["last_run"] = now
    save_state(st)
    text = report(reg, st)
    try:
        rp = sub("reports") / "upstream.md"
        rp.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return {"checked": checked, "total": len(reg), "new": new, "report": text, "token": bool(tok)}


def report(reg: list, st: dict) -> str:
    lines = ["# Where LOKI's code comes from - and what changed upstream", "",
             "Checked %s. %d sources. Adopt / Skip each change in Home > For you." % (
                 time.strftime("%Y-%m-%d %H:%M", time.localtime(st.get("last_run") or time.time())), len(reg)), "",
             "| Source | Used in | LOKI has | Upstream now | Status |", "| --- | --- | --- | --- | --- |"]
    rank = {"behind": 0, "new release": 1, "archived": 2, "moved": 3, "unreachable": 4, "follows branch": 5,
            "not pinned": 6, "current": 7, "": 8}
    rows = []
    for e in reg:
        s = st["repos"].get(e["repo"].lower()) or {}
        have = e["pin"][:10] or e["version"] or e["follows"] or "-"
        now_ = " ".join(x for x in (s.get("release", ""), s.get("head", "")[:8]) if x) or "-"
        status = s.get("status", "")
        if status == "behind":
            status = "behind by %d" % int(s.get("behind") or 0)
        rows.append((rank.get(s.get("status", ""), 8), "| [%s](https://github.com/%s) | %s | %s | %s | %s |" % (
            e["repo"], e["repo"], "; ".join(e["used_in"])[:120], have, now_, status or "not checked yet")))
    lines += [r for _, r in sorted(rows)]
    return "\n".join(lines) + "\n"


def adopt_prompt(entry: dict, seen: dict, status: str) -> str:
    """The request a LOKI agent gets when the owner taps Adopt."""
    used = "; ".join(entry.get("used_in") or [])
    what = ("%d new commits since LOKI's pin %s (%s)" % (int(seen.get("behind") or 0), entry.get("pin"), seen.get("compare_url", ""))
            if status == "behind" else "a new release %s (LOKI has %s)" % (seen.get("release"), entry.get("version") or "?")
            if status == "new release" else "the repository is %s" % status)
    changes = "\n".join("- " + c for c in (seen.get("changes") or [])) or "(see the link)"
    return ("Upstream update: %s has %s. LOKI uses it in: %s.\nRecent changes:\n%s\n\n"
            "1. Read what changed (the compare link / the release notes) and decide which changes matter for LOKI: "
            "fixes for code LOKI copied, features LOKI's version lacks, security fixes. Ignore the rest.\n"
            "2. Port only those into LOKI's copy (keep LOKI's own changes, they are marked LOKI: where they exist), "
            "check the licence is still compatible with AGPL-3.0.\n"
            "3. Update the pin / version in docs/THIRD_PARTY.md (and PROVENANCE.md / engine/ecc_sync.py if it is there).\n"
            "4. Run the suites for what you touched (tools/ship.py --check --only <suite>, 1-minute budget), then ship "
            "with tools/ship.py -m \"upstream: %s -> %s\".\n"
            "If nothing in the update matters for LOKI, only move the pin and say why in the commit message."
            % (entry["repo"], what, used, changes, entry["repo"], seen.get("head") or seen.get("release") or "latest"))


def queue_cards(new: list, cwd: str = ".") -> list:
    """One For you card per repo with something new (the owner adopts, skips or parks it)."""
    out = []
    try:
        import owner_review  # pylint: disable=import-outside-toplevel
    except Exception:  # noqa: BLE001
        return out
    for n in new[:10]:
        e, seen, status = n["entry"], n["seen"], n["status"]
        out.append(owner_review.queue("upstream", "upstream", {
            "repo": e["repo"], "status": status, "pin": e.get("pin") or e.get("version") or "",
            "head": seen.get("head", ""), "release": seen.get("release", ""), "behind": seen.get("behind", 0),
            "changes": seen.get("changes") or [], "compare_url": seen.get("compare_url", ""),
            "used_in": e.get("used_in") or [], "prompt": adopt_prompt(e, seen, status), "mark": seen.get("head", "") + "|"
            + seen.get("release", "") + "|" + status}, cwd, who="Upstream check"))
    return out


def skip(repo: str, mark: str) -> None:
    st = load_state()
    rec = st["repos"].setdefault(str(repo).lower(), {})
    rec["skipped"] = mark
    save_state(st)
