"""GitHub connector: repos, issues and pull requests - through the GitHub CLI (`gh`) when it is
installed and signed in, else the REST API with a token pasted in Settings (a fine-grained token).

Read actions: repos, issues, issue, prs, pr, search. Write actions (each asks the owner; never from a
background job): create_issue, comment, close_issue, create_pr.
`gh` is run with an argument list (no shell); the request body goes on stdin. Standard library only.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import connectors

SPEC = {
    "id": "github",
    "label": "GitHub (issues, PRs, repos)",
    "about": "Read your repositories, issues and pull requests. Opening, commenting on or closing anything asks you first.",
    "tool": "github",
    "writes": ["create_issue", "comment", "close_issue", "create_pr"],
    "help": "Easiest: install the GitHub CLI and run `gh auth login` once on this machine. Or paste a fine-grained "
            "token (github.com/settings/personal-access-tokens: your repos; Issues + Pull requests read/write, "
            "Contents read).",
    "fields": [
        {"key": "GITHUB_REPO", "label": "Default repository (owner/name)", "kind": "text", "default": ""},
        {"key": "GITHUB_TOKEN", "label": "Token (blank = use the gh CLI)", "kind": "secret"},
        {"key": "GITHUB_VIA", "label": "Use", "kind": "choice", "choices": ["auto", "gh", "token"], "default": "auto"},
    ],
}
API = "https://api.github.com"
OPENER = urllib.request.urlopen
RUN = subprocess.run
WHICH = shutil.which
TIMEOUT_S = 30
_GH_OK: dict = {}


class GitHubError(Exception):
    pass


def gh_ready(force: bool = False) -> bool:
    exe = WHICH("gh")
    if not exe:
        return False
    if not force and exe in _GH_OK:
        return _GH_OK[exe]
    try:
        ok = RUN([exe, "auth", "status"], capture_output=True, text=True, timeout=15).returncode == 0
    except Exception:  # noqa: BLE001
        ok = False
    _GH_OK[exe] = ok
    return ok


def via(source: dict | None = None) -> str:
    mode = connectors.get("GITHUB_VIA", source, "auto").lower()
    token = bool(connectors.get("GITHUB_TOKEN", source))
    if mode == "token" or (mode == "auto" and token):
        return "token" if token else ""
    if mode in ("gh", "auto") and gh_ready():
        return "gh"
    return "token" if token else ""


def status(source: dict | None = None) -> dict:
    how = via(source)
    if not how:
        return {"configured": False, "detail": "install the GitHub CLI and run `gh auth login`, or paste a token"}
    repo = connectors.get("GITHUB_REPO", source)
    return {"configured": True, "detail": "via %s%s" % ("the gh CLI" if how == "gh" else "a token",
                                                       (", default repo " + repo) if repo else "")}


def api(method: str, path: str, body: dict | None = None, source: dict | None = None):
    """One GitHub REST call (`path` like /repos/o/r/issues?state=open). Raises GitHubError."""
    how = via(source)
    if not how:
        raise GitHubError("GitHub is not set up: " + status(source)["detail"])
    if how == "gh":
        argv = [WHICH("gh") or "gh", "api", "--method", method.upper(), path.lstrip("/"),
                "-H", "Accept: application/vnd.github+json"]
        if body is not None:
            argv += ["--input", "-"]
        try:
            proc = RUN(argv, input=json.dumps(body) if body is not None else None, capture_output=True,
                       text=True, timeout=TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            raise GitHubError("gh failed to run (%s)" % exc) from exc
        if proc.returncode != 0:
            last = ((proc.stderr or proc.stdout or "").strip().splitlines() or ["failed"])[-1]
            raise GitHubError("gh api: %s" % connectors.redact(last)[:240])
        try:
            return json.loads(proc.stdout or "null")
        except ValueError as exc:
            raise GitHubError("gh api returned something that is not JSON") from exc
    req = urllib.request.Request(API + path, method=method.upper(),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + connectors.get("GITHUB_TOKEN", source),
                                          "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                                          "User-Agent": "LOKI", "Content-Type": "application/json"})
    try:
        with OPENER(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8") or "{}").get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        hint = " (the token may lack access to this repo)" if exc.code in (401, 403, 404) else ""
        raise GitHubError("GitHub answered HTTP %s %s%s" % (exc.code, msg, hint)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GitHubError("cannot reach GitHub (%s)" % getattr(exc, "reason", exc)) from exc


def test(source: dict | None = None) -> dict:
    try:
        me = api("GET", "/user", source=source)
    except GitHubError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": "signed in as %s" % (me or {}).get("login", "?")}


def _repo(repo: str, source: dict | None = None) -> str:
    repo = str(repo or "").strip().removeprefix("https://github.com/").strip("/") or connectors.get("GITHUB_REPO", source)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise GitHubError("give repo='owner/name' (or set a default repository in Settings > Tools > GitHub)")
    return repo


def _num(number) -> int:
    try:
        n = int(str(number).lstrip("#"))
    except (TypeError, ValueError):
        raise GitHubError("give the issue or PR number (number=12)") from None
    if n <= 0:
        raise GitHubError("give the issue or PR number (number=12)")
    return n


def _clip(text: str, n: int = 1500) -> str:
    text = str(text or "").strip()
    return text if len(text) <= n else text[:n] + " ..."


def _issue_line(item: dict) -> str:
    labels = ",".join(l.get("name", "") for l in item.get("labels", []) if isinstance(l, dict))
    return "#%s %s [%s]%s by %s, %s" % (item.get("number"), item.get("title", ""), item.get("state", ""),
                                        (" {" + labels + "}") if labels else "", (item.get("user") or {}).get("login", "?"),
                                        str(item.get("updated_at", ""))[:10])


def preview(args: dict) -> str:
    action = str(args.get("action", ""))
    repo = args.get("repo") or connectors.get("GITHUB_REPO") or "?"
    if action == "create_issue":
        return "GITHUB: open an issue in %s titled %r: %s" % (repo, args.get("title", ""), str(args.get("body", ""))[:300])
    if action == "comment":
        return "GITHUB: comment on %s#%s: %s" % (repo, args.get("number", "?"), str(args.get("body", ""))[:300])
    if action == "close_issue":
        return "GITHUB: close %s#%s" % (repo, args.get("number", "?"))
    if action == "create_pr":
        return "GITHUB: open a pull request in %s from %s into %s titled %r" % (
            repo, args.get("head", "?"), args.get("base", "") or "the default branch", args.get("title", ""))
    return "GITHUB %s" % action


ACTIONS = ("repos", "issues", "issue", "prs", "pr", "search", "create_issue", "comment", "close_issue", "create_pr")


def tool(action: str = "issues", repo: str = "", number: int = 0, query: str = "", title: str = "", body: str = "",
         head: str = "", base: str = "", state: str = "open", limit: int = 15) -> str:
    """The `github` tool."""
    action = str(action or "issues").strip().lower()
    limit = max(1, min(int(limit or 15), 50))
    state = state if state in ("open", "closed", "all") else "open"
    try:
        if action == "repos":
            items = api("GET", "/user/repos?sort=updated&per_page=%d" % limit) or []
            return "\n".join("%s%s - %s (updated %s)" % (r.get("full_name"), " [private]" if r.get("private") else "",
                                                          _clip(r.get("description") or "", 90), str(r.get("updated_at", ""))[:10])
                             for r in items) or "no repositories"
        if action == "issues":
            r = _repo(repo)
            items = [i for i in (api("GET", "/repos/%s/issues?state=%s&per_page=%d" % (r, state, limit)) or [])
                     if "pull_request" not in i]
            return ("%s issues in %s:\n" % (state, r)) + ("\n".join(_issue_line(i) for i in items) or "(none)")
        if action == "issue":
            r, n = _repo(repo), _num(number)
            item = api("GET", "/repos/%s/issues/%d" % (r, n))
            comments = api("GET", "/repos/%s/issues/%d/comments?per_page=20" % (r, n)) or []
            text = _issue_line(item) + "\n\n" + _clip(item.get("body") or "(no description)", 4000)
            for c in comments[-10:]:
                text += "\n\n--- %s, %s:\n%s" % ((c.get("user") or {}).get("login", "?"), str(c.get("created_at", ""))[:10],
                                                 _clip(c.get("body") or "", 1200))
            return connectors.untrusted("a GitHub issue", text)
        if action == "prs":
            r = _repo(repo)
            items = api("GET", "/repos/%s/pulls?state=%s&per_page=%d" % (r, state, limit)) or []
            return ("%s pull requests in %s:\n" % (state, r)) + ("\n".join(
                "#%s %s [%s -> %s] by %s%s" % (p.get("number"), p.get("title", ""), (p.get("head") or {}).get("ref", "?"),
                                               (p.get("base") or {}).get("ref", "?"), (p.get("user") or {}).get("login", "?"),
                                               " (draft)" if p.get("draft") else "") for p in items) or "(none)")
        if action == "pr":
            r, n = _repo(repo), _num(number)
            p = api("GET", "/repos/%s/pulls/%d" % (r, n))
            files = api("GET", "/repos/%s/pulls/%d/files?per_page=50" % (r, n)) or []
            text = "#%s %s [%s] %s -> %s, +%s -%s, mergeable: %s\n\n%s\n\nFiles:\n%s" % (
                p.get("number"), p.get("title", ""), p.get("state", ""), (p.get("head") or {}).get("ref", "?"),
                (p.get("base") or {}).get("ref", "?"), p.get("additions", "?"), p.get("deletions", "?"), p.get("mergeable"),
                _clip(p.get("body") or "(no description)", 3000),
                "\n".join("  %s (+%s -%s)" % (f.get("filename"), f.get("additions"), f.get("deletions")) for f in files))
            return connectors.untrusted("a GitHub pull request", text)
        if action == "search":
            if not str(query or "").strip():
                return "error: search needs query='...' (GitHub issue search syntax, e.g. 'is:open label:bug')"
            q = str(query)
            if repo or connectors.get("GITHUB_REPO"):
                try:
                    q += " repo:" + _repo(repo)
                except GitHubError:
                    pass
            data = api("GET", "/search/issues?per_page=%d&q=%s" % (limit, urllib.parse.quote(q))) or {}
            return "%s result(s) for %r:\n%s" % (data.get("total_count", 0), q,
                                                 "\n".join(_issue_line(i) for i in data.get("items", [])) or "(none)")
        # ---- writes: the policy asked the owner before we got here
        if action == "create_issue":
            if not str(title or "").strip():
                return "error: create_issue needs title='...' (and body='...')"
            r = _repo(repo)
            made = api("POST", "/repos/%s/issues" % r, {"title": title, "body": body or ""})
            return "opened %s#%s: %s" % (r, made.get("number"), made.get("html_url", ""))
        if action == "comment":
            if not str(body or "").strip():
                return "error: comment needs body='...'"
            r, n = _repo(repo), _num(number)
            made = api("POST", "/repos/%s/issues/%d/comments" % (r, n), {"body": body})
            return "commented on %s#%d: %s" % (r, n, made.get("html_url", ""))
        if action == "close_issue":
            r, n = _repo(repo), _num(number)
            api("PATCH", "/repos/%s/issues/%d" % (r, n), {"state": "closed"})
            return "closed %s#%d" % (r, n)
        if action == "create_pr":
            if not str(title or "").strip() or not str(head or "").strip():
                return "error: create_pr needs title='...' and head='<branch>' (base defaults to the main branch)"
            r = _repo(repo)
            if not base:
                base = (api("GET", "/repos/%s" % r) or {}).get("default_branch", "main")
            made = api("POST", "/repos/%s/pulls" % r, {"title": title, "body": body or "", "head": head, "base": base})
            return "opened pull request %s#%s: %s" % (r, made.get("number"), made.get("html_url", ""))
    except GitHubError as exc:
        return "error: %s" % exc
    return "error: unknown action %r - use one of %s" % (action, ", ".join(ACTIONS))


connectors.register(__import__(__name__))
