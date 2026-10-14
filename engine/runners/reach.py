"""Agent Reach: the internet for LOKI's agents. stdin/stdout JSON, like every runner.

    {"op": "doctor" | "read" | "github", "url": "...", "query": "...", "max_chars": 20000}

Agent Reach (github.com/Panniantong/Agent-Reach, MIT) installs and health-checks the best
current tool for each platform and tells agents which command to use. This runner uses it
the same way:
  doctor   `agent-reach doctor --json`: which channels work here and through what
  read     any web page as clean text through Jina Reader (the channel Agent Reach uses
           for the web, no key needed)
  github   `gh` search / repo view (Agent Reach's GitHub channel)
YouTube goes to the `media` specialist (yt-dlp, which Agent Reach also uses).
"""
import json
import re
import shutil
import subprocess
import sys
import urllib.request

JINA = "https://r.jina.ai/"


def _run(argv, timeout=90):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def doctor():
    exe = shutil.which("agent-reach")
    if not exe:
        return {"installed": False, "hint": "pipx install https://github.com/Panniantong/agent-reach/archive/main.zip"}
    code, out, err = _run([exe, "doctor", "--json"], timeout=120)
    try:
        return {"installed": True, "channels": json.loads(out)}
    except ValueError:
        return {"installed": True, "report": (out or err)[-6000:], "exit": code}


def read(url, limit):
    if not re.match(r"^https?://", url):
        raise ValueError("read needs an http(s) url")
    req = urllib.request.Request(JINA + url, headers={"User-Agent": "Loki/1.0", "Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8", "replace")
    return {"url": url, "text": text[:limit], "truncated": len(text) > limit, "via": "jina-reader"}


def github(query, url):
    exe = shutil.which("gh")
    if not exe:
        raise RuntimeError("the GitHub CLI (gh) is not installed")
    match = re.match(r"^https?://github\.com/([^/\s]+/[^/\s#?]+)", url or "")
    if match:
        code, out, err = _run([exe, "repo", "view", match.group(1)])
    else:
        code, out, err = _run([exe, "search", "repos", query, "--limit", "10"])
    if code != 0:
        raise RuntimeError((err or out)[-400:])
    return {"text": out[:20000]}


def main():
    job = json.loads(sys.stdin.read() or "{}")
    op = str(job.get("op") or "doctor")
    try:
        if op == "doctor":
            result = doctor()
        elif op == "read":
            result = read(str(job.get("url") or ""), int(job.get("max_chars") or 20000))
        elif op == "github":
            result = github(str(job.get("query") or ""), str(job.get("url") or ""))
        else:
            raise ValueError("op must be doctor, read or github")
        print(json.dumps({"ok": True, **result}, default=str))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}))


if __name__ == "__main__":
    main()
