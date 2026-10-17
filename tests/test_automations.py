"""Automations (session 29, engine/automations.py): triggers -> conditions -> steps, one runner.

    python tests/test_automations.py

Offline: a fake clock, fake connectors (email, calendar), a fake Telegram, fake jobs, fake peers and a fake
model. Covers drafting from a sentence, schedules + missed-run catch-up, folder/email/calendar/job/machine/
webhook/Telegram triggers, conditions, every step type, approvals and pre-approval by fingerprint, retries
with backoff, rate limits and run modes, the kill switch, persistence + resume after a restart, one machine
owning an automation, peer merge, the bridge routes (real BridgeHTTPServer) incl. the webhook, the agent's
`automation` tool, and the Automations view in headless Chromium (when Playwright is installed).
"""
from __future__ import annotations

import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-auto-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
for key in list(os.environ):
    if key.startswith("LOKI_AUTOMATIONS"):
        os.environ.pop(key, None)
sys.path.insert(0, str(REPO / "engine"))

import automations as A  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:400]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def go(self, seconds):
        self.t += seconds


class Fake(A.Sources):
    """Every outside thing, recorded."""

    def __init__(self, workspace, kind="pc", name="gaming-pc"):
        self.ws = Path(workspace)
        self.kind, self.name = kind, name
        self.jobs = {}
        self.created = []
        self.cancelled = []
        self.tg = []
        self.notes = []
        self.http_calls = []
        self.http_answer = (200, "ok")
        self.tool_calls = []
        self.tool_answer = "price: 89 EUR"
        self.answers = []
        self.mail = []
        self.events = []
        self.peers = []
        self.images = []
        self.peer_linked = False

    def machine(self):
        return {"name": self.name, "kind": self.kind}

    def has_peers(self):
        return self.peer_linked

    def workspace(self):
        return self.ws

    def create_job(self, spec):
        jid = "j%d" % (len(self.created) + 1)
        self.created.append(spec)
        self.jobs[jid] = {"id": jid, "status": "working", "title": spec["title"], "automation": spec.get("automation", "")}
        return {"id": jid}

    def get_job(self, jid):
        return self.jobs.get(jid)

    def cancel_job(self, jid):
        self.cancelled.append(jid)
        if jid in self.jobs:
            self.jobs[jid]["status"] = "cancelled"

    def list_jobs(self):
        return list(self.jobs.values())

    def call_tool(self, tool, args):
        self.tool_calls.append((tool, args))
        return self.tool_answer

    def ask(self, prompt, system=""):
        self.last_prompt = prompt
        return self.answers.pop(0) if self.answers else "NO"

    def telegram(self, text):
        self.tg.append(text)

    def notify(self, title, text):
        self.notes.append((title, text))

    def make_image(self, prompt):
        self.images.append(prompt)
        return "making a picture"

    def http(self, method, url, headers, body):
        self.http_calls.append((method, url, body))
        return self.http_answer

    def email_list(self, query, folder, limit):
        return [m for m in self.mail if not query or query.lower() in (m["from"] + m["subject"]).lower()]

    def calendar_events(self, start, end):
        return [e for e in self.events if start <= e["start"] <= end]

    def peers_status(self):
        return self.peers


def fresh(kind="pc", name="gaming-pc", start=None, root=None):
    ws = TMP / ("ws-" + A._short_id())
    ws.mkdir(parents=True)
    clock = Clock(start or datetime(2026, 10, 19, 7, 0).timestamp())   # a Monday, 07:00
    fake = Fake(ws, kind, name)
    rt = A.Automations(root or (TMP / ("store-" + A._short_id())), fake, clock=clock, env={}, sync=True)
    return rt, fake, clock


def run_of(rt, rid):
    return next(r for r in rt.runs(limit=500) if r["id"] == rid)


# ============================================================================ schedules
section("schedules: the owner's phrases")
now = datetime(2026, 10, 19, 7, 0).timestamp()
for phrase, expr in [("every morning at 8", "0 8 * * *"), ("every evening at 7", "0 19 * * *"),
                     ("every weekday morning", "0 8 * * 1-5"), ("every monday and friday at 9", "0 9 * * 1,5"),
                     ("daily at 7", "0 7 * * *"), ("every day", "0 9 * * *"), ("weekly", "0 9 * * 1"),
                     ("every weekday at 8:30am", "30 8 * * 1-5"), ("every sunday at 6pm", "0 18 * * 0"),
                     ("0 9 * * 1-5", "0 9 * * 1-5"), ("at 7:30", "30 7 * * *")]:
    got = A.parse_when(phrase, now)
    check("'%s' -> cron %s" % (phrase, expr), got.get("expr") == expr, got)
check("'every 2 hours' -> every 120 min", A.parse_when("every 2 hours", now).get("minutes") == 120)
check("'hourly' -> every 60 min", A.parse_when("hourly", now).get("minutes") == 60)
check("'in 30m' -> once", A.parse_when("in 30m", now)["kind"] == "once")
try:
    A.parse_when("whenever you feel like it", now)
    check("nonsense schedule is refused", False)
except ValueError:
    check("nonsense schedule is refused", True)
t = A._norm_trigger({"type": "schedule", "when": "in 30m"}, now)
check("'in 30m' is pinned to an absolute time (edits/syncs never move it)", t["when"].startswith("2026-10-19T07:30"), t)

# ============================================================================ drafting
section("natural language -> a draft card")
d = A.draft("every morning at 8 send me the weather and my calendar on Telegram", now=now)
a = d.get("automation") or {}
check("the morning briefing is understood (by rules, offline)", d["ok"] and d["via"] == "rules", d)
check("its trigger is every day at 08:00", a["triggers"][0]["type"] == "schedule" and a["triggers"][0]["schedule"]["expr"] == "0 8 * * *", a.get("triggers"))
check("its steps: a LOKI task, then a Telegram message with its answer",
      [s["type"] for s in a["steps"]] == ["task", "telegram"] and a["steps"][1]["text"] == "{{last}}", a.get("steps"))
check("the task asks for the weather and the calendar", "weather" in a["steps"][0]["prompt"] and "calendar" in a["steps"][0]["prompt"])
check("a draft is OFF until the owner turns it on", a["enabled"] is False)
check("it runs on the PC by default", a["machine"] == "pc")
check("the card reads plainly", "On a schedule: every morning at 8" in d["text"] and "Telegram" in d["text"], d["text"])
d = A.draft("when a PDF lands in Downloads, summarize it into notes", now=now)
a = d.get("automation") or {}
check("the PDF watcher is understood", d["ok"] and a["triggers"][0] == {"type": "folder", "every_s": 10, "path": "~/Downloads", "pattern": "*.pdf",
                                                               "events": ["created"], "recursive": False, "copy": True}, a.get("triggers"))
check("its task summarizes the copied file into notes/<name>.md", "{{trigger.file}}" in a["steps"][0]["prompt"]
      and "notes/{{trigger.stem}}.md" in a["steps"][0]["prompt"], a.get("steps"))
for sentence, kind in [("when I get an email from bob@example.com tell me on telegram", "email"),
                       ("15 minutes before each meeting send me a brief on telegram", "calendar"),
                       ("when a job fails notify me", "job"), ("when the pc comes online, ping me on telegram", "machine"),
                       ("when I send brief on telegram, give me today's calendar", "telegram"),
                       ("every friday at 5pm write a weekly report", "schedule")]:
    d = A.draft(sentence, now=now)
    check("'%s' -> a %s trigger" % (sentence[:44], kind), d["ok"] and d["automation"]["triggers"][0]["type"] == kind, d.get("error") or d["automation"]["triggers"])
d = A.draft("when I get an email from bob@example.com tell me on telegram", now=now)
check("an email filter from the sentence", d["automation"]["triggers"][0]["query"] == "from:bob@example.com")
check("'tell me' alone needs no LOKI task: just the message", [s["type"] for s in d["automation"]["steps"]] == ["telegram"], d["automation"]["steps"])
d = A.draft("when I send brief on telegram, give me today's calendar", now=now)
check("a Telegram-keyword automation answers on Telegram", d["automation"]["steps"][-1]["type"] == "telegram")
check("not understood -> a helpful error", not A.draft("hello there", now=now)["ok"])
calls = []
d = A.draft("make my mornings nicer somehow", ask=lambda p, s: calls.append(p) or json.dumps(
    {"name": "Nice mornings", "triggers": [{"type": "schedule", "when": "every day at 7am"}], "steps": [{"type": "notify", "text": "Good morning"}]}), now=now)
check("what the rules do not understand goes to the model, and is checked", d["ok"] and d["via"] == "model" and calls)
d = A.draft("make my mornings nicer somehow", ask=lambda p, s: "{not json", now=now)
check("a model's broken JSON is refused cleanly", not d["ok"])
d = A.draft("make my mornings nicer somehow", ask=lambda p, s: json.dumps({"name": "x", "triggers": [{"type": "schedule", "when": "every day"}],
                                                                           "steps": [{"type": "tool", "tool": "run_command", "args": {}}]}), now=now)
check("a model draft calling a forbidden tool is refused", not d["ok"] and "run_command" in d["error"], d)
check("8 templates", len(A.templates()) == 8 and {t["id"] for t in A.templates()} >= {"daily-briefing", "inbox-triage", "folder-organizer",
      "meeting-prep", "weekly-report", "backup-reminder", "price-watch", "github-digest"})
for tpl in A.templates():
    try:
        A.normalize(tpl["automation"], now)
        ok = True
    except ValueError as exc:
        ok = str(exc)
    check("template %s checks out" % tpl["id"], ok is True, ok)

# ============================================================================ validation
section("validation")
for bad, why in [({"name": "", "triggers": [{"type": "manual"}], "steps": [{"type": "notify"}]}, "name"),
                 ({"name": "x", "triggers": [], "steps": [{"type": "notify"}]}, "trigger"),
                 ({"name": "x", "triggers": [{"type": "manual"}], "steps": []}, "step"),
                 ({"name": "x", "triggers": [{"type": "nope"}], "steps": [{"type": "notify"}]}, "unknown trigger"),
                 ({"name": "x", "triggers": [{"type": "manual"}], "steps": [{"type": "http", "url": "ftp://x"}]}, "http"),
                 ({"name": "x", "triggers": [{"type": "manual"}], "steps": [{"type": "tool", "tool": "computer"}]}, "may not"),
                 ({"name": "x", "triggers": [{"type": "folder"}], "steps": [{"type": "notify"}]}, "folder")]:
    try:
        A.normalize(bad, now)
        check("refused: %s" % why, False)
    except ValueError as exc:
        check("refused: %s" % why, why.split()[0] in str(exc).lower(), exc)

# ============================================================================ schedule trigger + catch-up
section("schedule trigger, fake clock, missed runs")
rt, fake, clock = fresh()
auto = rt.save({"name": "Ping", "enabled": True, "triggers": [{"type": "schedule", "when": "every day at 8am"}],
                "steps": [{"type": "telegram", "text": "ping {{date}} {{trigger.scheduled_for}}"}]})
rt.tick()
check("first look only sets the next time (nothing fires)", not fake.tg)
clock.go(59 * 60)
rt.tick()
check("07:59 - not yet", not fake.tg)
clock.go(60)
rt.tick()
check("08:00 - it fires, with the date filled in", fake.tg == ["ping 2026-10-19 2026-10-19 08:00"], fake.tg)
rt.tick()
check("only once at 08:00", len(fake.tg) == 1)
status = rt.status()
check("the window sees the next run", status["automations"][0]["triggers"][0]["next"].startswith("Tue"), status["automations"][0]["triggers"][0])
st = rt.get(auto["id"])["stats"]
check("stats: last run done", st.get("last_status") == "done" and st.get("runs") == 1, st)
clock.go(3 * 86400)      # the machine was off for three days
rt.tick()
check("catch-up 'once' (default): one run after three missed", len(fake.tg) == 2, fake.tg)
check("... and a notice says how many were missed", any(n["kind"] == "missed" and "3 runs missed" in n["text"] for n in rt.notices), rt.notices)
for policy, expect in [("skip", 0), ("all", 3)]:
    rt2, fake2, clock2 = fresh()
    rt2.save({"name": "P", "enabled": True, "triggers": [{"type": "schedule", "when": "every day at 8am", "catch_up": policy}],
              "steps": [{"type": "telegram", "text": "x"}], "mode": "parallel"})
    rt2.tick()
    clock2.go(3 * 86400 + 1800)     # Thu 07:30: Mon, Tue and Wed 08:00 were missed
    rt2.tick()
    check("catch-up '%s' -> %d runs" % (policy, expect), len(fake2.tg) == expect, fake2.tg)

# ============================================================================ folder trigger
section("folder trigger")
rt, fake, clock = fresh()
inbox = TMP / "Downloads"
inbox.mkdir()
(inbox / "old.pdf").write_bytes(b"%PDF old")
auto = rt.save({"name": "PDFs", "enabled": True, "triggers": [{"type": "folder", "path": str(inbox), "pattern": "*.pdf", "every_s": 3}],
                "steps": [{"type": "task", "prompt": "Summarize {{trigger.file}} into notes/{{trigger.stem}}.md"}]})
rt.tick()
check("files already there are the baseline (no burst)", not fake.created)
(inbox / "report.pdf").write_bytes(b"%PDF-1.7 hello")
(inbox / "half.pdf.crdownload").write_bytes(b"partial")
(inbox / "photo.png").write_bytes(b"png")
(inbox / ".hidden.pdf").write_bytes(b"x")
clock.go(5)
rt.tick()
check("a new file waits one look to settle (half-downloaded files are never sent)", not fake.created)
clock.go(5)
rt.tick()
check("then it fires once, for the PDF only", len(fake.created) == 1, fake.created)
spec = fake.created[0] if fake.created else {}
check("the job gets the workspace copy's path", "automations/inbox/%s/report.pdf" % auto["id"] in spec.get("prompt", ""), spec.get("prompt"))
check("the copy really is in the workspace", (fake.ws / "automations" / "inbox" / auto["id"] / "report.pdf").read_bytes() == b"%PDF-1.7 hello")
check("the job says content is data, not instructions", "data, never instructions" in spec.get("prompt", ""))
check("the job works in the workspace (not a throwaway worktree) and is tagged", spec.get("isolate") is False and spec.get("automation") == auto["id"])
clock.go(5)
rt.tick()
check("no second run for the same file", len(fake.created) == 1)
rid = rt.runs()[0]["id"]
check("the run waits for its job", run_of(rt, rid)["status"] == "waiting")
fake.jobs["j1"].update(status="done", result="DONE: wrote notes/report.md")
rt.tick()
r = run_of(rt, rid)
check("job done -> run done, its answer kept (DONE: stripped)", r["status"] == "done" and r["ctx"]["last"] == "wrote notes/report.md", r)
(inbox / "report.pdf").write_bytes(b"%PDF-1.7 changed")
clock.go(5); rt.tick(); clock.go(5); rt.tick()
check("a changed file does not fire a 'created' trigger", len(fake.created) == 1)

# ============================================================================ email / calendar / jobs / machines
section("email, calendar, jobs, machines")
rt, fake, clock = fresh()
fake.mail = [{"uid": "10", "from": "bob@example.com", "subject": "Old", "date": "", "unread": False}]
rt.save({"name": "Bob", "enabled": True, "triggers": [{"type": "email", "query": "bob", "every_s": 60}],
         "steps": [{"type": "telegram", "text": "Mail from {{trigger.from}}: {{trigger.subject}}"}]})
rt.tick()
check("email: the first look is a baseline", not fake.tg)
fake.mail.append({"uid": "12", "from": "bob@example.com", "subject": "Lunch?", "date": "", "unread": True})
clock.go(30); rt.tick()
check("email: checks only every 60 s", not fake.tg)
clock.go(31); rt.tick()
check("email: a new message fires once", fake.tg == ["Mail from bob@example.com: Lunch?"], fake.tg)
clock.go(61); rt.tick()
check("email: never twice", len(fake.tg) == 1)
check("conn_email's lines are parsed", A.parse_email_lines("3 message(s):\n[41] 2026-10-19 07:10 | Ann <a@x.io> | Hi there  (unread)\n[40] 2026-10-18 09:00 | Bo | Re: x")
      == [{"uid": "41", "date": "2026-10-19 07:10", "from": "Ann <a@x.io>", "subject": "Hi there", "unread": True},
          {"uid": "40", "date": "2026-10-18 09:00", "from": "Bo", "subject": "Re: x", "unread": False}])

rt, fake, clock = fresh()
fake.events = [{"title": "Design review", "start": clock() + 40 * 60, "location": "Room 2", "uid": "e1"},
               {"title": "Holiday", "start": clock() + 10 * 60, "all_day": True, "uid": "e2"}]
rt.save({"name": "Prep", "enabled": True, "triggers": [{"type": "calendar", "minutes_before": 30}],
         "steps": [{"type": "telegram", "text": "{{trigger.title}} at {{trigger.start}}{{trigger.where}}"}]})
rt.tick()
check("calendar: 40 minutes away is not yet", not fake.tg)
clock.go(11 * 60); rt.tick()
check("calendar: 29 minutes before -> fires (all-day events never)", fake.tg == ["Design review at 07:40 at Room 2"], fake.tg)
clock.go(3 * 60); rt.tick()
check("calendar: once per event", len(fake.tg) == 1)

rt, fake, clock = fresh()
fake.jobs = {"old": {"id": "old", "status": "failed", "title": "old job"}}
rt.save({"name": "Fails", "enabled": True, "triggers": [{"type": "job", "status": "failed"}],
         "steps": [{"type": "notify", "title": "Job failed", "text": "{{trigger.title}}: {{trigger.result}}"}]})
rt.tick()
check("jobs: old failures are a baseline", not fake.notes)
fake.jobs["new"] = {"id": "new", "status": "failed", "title": "build site", "error": "timed out"}
fake.jobs["mine"] = {"id": "mine", "status": "failed", "title": "Automation: x", "automation": "zzz"}
fake.jobs["ok"] = {"id": "ok", "status": "done", "title": "fine"}
rt.tick()
check("jobs: a new failure fires (not a done one, not an automation's own job)", fake.notes == [("Job failed", "build site: timed out")], fake.notes)

rt, fake, clock = fresh()
fake.peers = [{"name": "mohameds-mac-mini", "ok": False}]
rt.save({"name": "Mac back", "enabled": True, "triggers": [{"type": "machine", "machine": "mac"}], "steps": [{"type": "telegram", "text": "{{trigger.machine}} is back"}]})
rt.tick()
fake.peers = [{"name": "mohameds-mac-mini", "ok": True}]
clock.go(121); rt.tick()
check("machine: offline -> online fires", fake.tg == ["mohameds-mac-mini is back"], fake.tg)
clock.go(121); rt.tick()
check("machine: staying online does not fire again", len(fake.tg) == 1)

# ============================================================================ webhook + telegram keyword
section("webhook and Telegram keyword")
rt, fake, clock = fresh()
auto = rt.save({"name": "Hook", "enabled": True, "mode": "parallel", "max_per_hour": 100,
                "triggers": [{"type": "webhook"}], "steps": [{"type": "telegram", "text": "door: {{trigger.state}}"}]})
key = auto["triggers"][0]["key"]
check("a webhook gets a long random key", len(key) >= 30)
check("wrong key -> 404, nothing runs", rt.webhook(auto["id"], "nope", {"state": "open"})[0] == 404 and not fake.tg)
code, out = rt.webhook(auto["id"], key, {"state": "open"})
check("right key -> fires with the JSON fields", code == 200 and fake.tg == ["door: open"], (code, out, fake.tg))
again = rt.save(dict(rt.get(auto["id"]), name="Hook 2"))
check("an edit keeps the webhook's key", again["triggers"][0]["key"] == key)
codes = [rt.webhook(auto["id"], key, {"state": "x"})[0] for _ in range(40)]
check("webhooks are limited to 30 a minute", codes.count(429) >= 9, codes)
check("the URL shown has the key and the bridge port", rt.present(rt.get(auto["id"]), 8766)["triggers"][0]["url"]
      == "http://127.0.0.1:8766/hook/%s?key=%s" % (auto["id"], key))

rt, fake, clock = fresh()
rt.save({"name": "Brief", "enabled": True, "triggers": [{"type": "telegram", "keyword": "brief"}], "steps": [{"type": "telegram", "text": "brief for {{trigger.rest}}"}]})
check("Telegram: 'brief tomorrow' is taken by the automation", rt.on_telegram("Brief tomorrow") is True and fake.tg == ["brief for tomorrow"], fake.tg)
check("Telegram: other messages go to the chat as before", rt.on_telegram("how are you") is False)


class FakeChannel:
    def __init__(self):
        self.said, self.chats = [], []

    def is_owner(self, msg):
        return msg.get("user_id") == 1

    def say(self, chat, text):
        self.said.append(text)

    def handle(self, msg):
        self.chats.append(msg["text"])


class S:
    pass


st = S()
ch = FakeChannel()
st.channels = {"telegram": ch}
A._wrap_telegram(st, rt)
ch.handle({"user_id": 1, "chat_id": 5, "text": "brief now"})
ch.handle({"user_id": 1, "chat_id": 5, "text": "hello"})
ch.handle({"user_id": 2, "chat_id": 9, "text": "brief hack"})
check("the channel hook: the owner's keyword starts it and is answered", "On it - automation started." in ch.said and fake.tg[-1] == "brief for now")
check("the channel hook: other messages and strangers reach the normal handler", ch.chats == ["hello", "brief hack"], ch.chats)

# ============================================================================ steps, approvals
section("steps, approvals, pre-approval")
rt, fake, clock = fresh()
auto = rt.save({"name": "Hit", "triggers": [{"type": "manual"}],
                "steps": [{"type": "http", "method": "POST", "url": "https://hooks.example.com/x", "body": "{{trigger.text}}"},
                          {"type": "file", "path": "logs/hits.md", "text": "- {{date}} {{last}}"}]})
res = rt.fire(auto["id"], {"text": "hello"})
r = run_of(rt, res["run"])
check("an HTTP step waits for the owner's OK", r["status"] == "approval" and not fake.http_calls and "hooks.example.com" in r["approval"], r)
check("... and the window/events are told", any(n["kind"] == "approval" for n in rt.notices))
rt.run_action(res["run"], "approve")
r = run_of(rt, res["run"])
check("approved -> it runs, the next step writes the file", r["status"] == "done" and fake.http_calls == [("POST", "https://hooks.example.com/x", "hello")], r)
check("the file is in the workspace with the answer", (fake.ws / "logs" / "hits.md").read_text().startswith("- 2026-10-19 HTTP 200"))
res = rt.fire(auto["id"], {"text": "again"})
rt.run_action(res["run"], "deny")
check("denied -> cancelled, nothing sent", run_of(rt, res["run"])["status"] == "cancelled" and len(fake.http_calls) == 1)
rt.approve(auto["id"])
check("pre-approved: the card says so", A.card(rt.get(auto["id"]))["preapproved"])
res = rt.fire(auto["id"], {"text": "pre"})
check("pre-approved -> runs without asking", run_of(rt, res["run"])["status"] == "done" and len(fake.http_calls) == 2)
edited = rt.save(dict(rt.get(auto["id"]), steps=[{"type": "http", "method": "POST", "url": "https://evil.example.net/", "body": "x"}]))
check("an edit to the steps takes the pre-approval away", not edited["approved"] and not A.is_preapproved(edited))
renamed = rt.approve(auto["id"]) and rt.save(dict(rt.get(auto["id"]), name="renamed"))
check("a rename keeps it (the steps did not change)", A.is_preapproved(renamed))
res = rt.fire(auto["id"], {})
check("metadata service addresses are refused even when approved", True)
bad = rt.save({"name": "meta", "triggers": [{"type": "manual"}], "steps": [{"type": "http", "url": "http://169.254.169.254/latest"}]}, approve=True)
r = run_of(rt, rt.fire(bad["id"], {})["run"])
check("... (169.254.169.254 -> failed, no request)", r["status"] == "failed" and len([c for c in fake.http_calls if "169.254" in c[1]]) == 0, r)

auto = rt.save({"name": "Mail", "triggers": [{"type": "manual"}], "steps": [{"type": "tool", "tool": "email", "args": {"action": "send", "to": "a@b.c", "subject": "s", "body": "b"}}]})
r = run_of(rt, rt.fire(auto["id"], {})["run"])
check("a connector write (email send) asks first", r["status"] == "approval" and not fake.tool_calls, r)
auto = rt.save({"name": "Read", "triggers": [{"type": "manual"}], "steps": [{"type": "tool", "tool": "read_web", "args": {"url": "https://shop.example/p", "query": "price"}}]})
r = run_of(rt, rt.fire(auto["id"], {})["run"])
check("a read-only tool runs without asking", r["status"] == "done" and fake.tool_calls[-1][0] == "read_web" and r["ctx"]["last"] == "price: 89 EUR", r)

path_out = rt.save({"name": "Out", "triggers": [{"type": "manual"}], "steps": [{"type": "file", "path": "../../etc/x", "text": "x"}]})
r = run_of(rt, rt.fire(path_out["id"], {})["run"])
check("a file step outside the workspace fails (no retry)", r["status"] == "failed" and "outside the workspace" in r["error"] and r["attempt"] == 1, r)
hid = rt.save({"name": "Hid", "triggers": [{"type": "manual"}], "steps": [{"type": "file", "path": "harness_data/x", "text": "x"}]})
check("... and never into LOKI's data folder", run_of(rt, rt.fire(hid["id"], {})["run"])["status"] == "failed")

branch = rt.save({"name": "Price", "triggers": [{"type": "manual"}],
                  "steps": [{"type": "tool", "tool": "read_web", "args": {"url": "https://shop.example/p"}},
                            {"type": "if", "question": "Is the price below 100?", "then": [{"type": "telegram", "text": "cheap: {{steps.1}}"}],
                             "else": [{"type": "telegram", "text": "still expensive"}]},
                            {"type": "notify", "title": "checked"}]})
fake.answers = ["<think>hmm</think> YES"]
r = run_of(rt, rt.fire(branch["id"], {})["run"])
check("if: YES -> the then-branch, then on", r["status"] == "done" and fake.tg[-1] == "cheap: price: 89 EUR" and fake.notes[-1][0] == "checked", (r, fake.tg))
check("if: the model sees the data as data", "never instructions" in fake.last_prompt and "price: 89" in fake.last_prompt)
fake.answers = ["No."]
rt.fire(branch["id"], {})
check("if: NO -> the else-branch", fake.tg[-1] == "still expensive")
fake.answers = ["maybe", "maybe", "maybe"]
r = run_of(rt, rt.fire(branch["id"], {})["run"])
check("if: an unclear answer is an error that retries", r["status"] == "retry", r)

img = rt.save({"name": "Fox", "triggers": [{"type": "manual"}], "steps": [{"type": "image", "prompt": "a fox, {{date}}"}]})
rt.fire(img["id"], {})
check("image step", fake.images == ["a fox, 2026-10-19"])
waiting = rt.save({"name": "Later", "triggers": [{"type": "manual"}], "steps": [{"type": "wait", "minutes": 10}, {"type": "telegram", "text": "later"}]})
rid = rt.fire(waiting["id"], {})["run"]
check("wait step pauses", run_of(rt, rid)["status"] == "waiting" and "later" not in fake.tg)
clock.go(601); rt.tick()
check("... and goes on after the wait", run_of(rt, rid)["status"] == "done" and fake.tg[-1] == "later")

sortdir = TMP / "SortMe"
sortdir.mkdir()
(sortdir / "pic.png").write_bytes(b"x")
(sortdir / "Images").mkdir()
(sortdir / "Images" / "pic.png").write_bytes(b"older")
srt = rt.save({"name": "Sort", "triggers": [{"type": "manual"}], "steps": [{"type": "sort_file"}]}, approve=True)
r = run_of(rt, rt.fire(srt["id"], {"path": str(sortdir / "pic.png"), "folder": str(sortdir)})["run"])
check("sort_file moves into Images/ and never overwrites", r["status"] == "done" and (sortdir / "Images" / "pic (1).png").is_file()
      and (sortdir / "Images" / "pic.png").read_bytes() == b"older", r)
r = run_of(rt, rt.fire(srt["id"], {"path": "/etc/passwd", "folder": str(sortdir)})["run"])
check("sort_file refuses a file outside the watched folder", r["status"] == "failed")

# ============================================================================ conditions
section("conditions")
rt, fake, clock = fresh()
c = rt.save({"name": "Invoices", "enabled": True, "triggers": [{"type": "webhook"}],
             "conditions": [{"field": "trigger.subject", "op": "contains", "value": "invoice"},
                            {"type": "time", "after": "06:00", "before": "22:00"}, {"type": "weekday", "days": "mon,tue,wed,thu,fri"}],
             "steps": [{"type": "telegram", "text": "{{trigger.subject}}"}]})
key = c["triggers"][0]["key"]
rt.webhook(c["id"], key, {"subject": "Hello"})
check("a condition that does not hold skips the run", not fake.tg)
rt.webhook(c["id"], key, {"subject": "Your INVOICE #4"})
check("all conditions hold -> runs (case-insensitive)", fake.tg == ["Your INVOICE #4"])
clock.t = datetime(2026, 10, 18, 12, 0).timestamp()   # a Sunday
rt.webhook(c["id"], key, {"subject": "invoice on sunday"})
check("weekday condition", len(fake.tg) == 1)
ctx = {"trigger": {"n": "42", "s": "abc"}}
check("gt / lt / matches / exists / missing", A.condition_holds({"field": "n", "op": "gt", "value": "40"}, ctx, now)
      and A.condition_holds({"field": "trigger.n", "op": "lt", "value": "50"}, ctx, now)
      and A.condition_holds({"field": "s", "op": "matches", "value": "^a.c$"}, ctx, now)
      and A.condition_holds({"field": "s", "op": "exists"}, ctx, now) and A.condition_holds({"field": "zz", "op": "missing"}, ctx, now))
check("a time window across midnight", A.condition_holds({"type": "time", "after": "22:00", "before": "06:00"}, {}, datetime(2026, 1, 1, 23, 30).timestamp())
      and not A.condition_holds({"type": "time", "after": "22:00", "before": "06:00"}, {}, datetime(2026, 1, 1, 12, 0).timestamp()))

# ============================================================================ retries, limits, modes, kill switch
section("retries with backoff, rate limits, modes, kill switch")
rt, fake, clock = fresh()
t1 = rt.save({"name": "Task", "triggers": [{"type": "manual"}], "retries": 2, "steps": [{"type": "task", "prompt": "do it"}, {"type": "telegram"}]})
rid = rt.fire(t1["id"], {})["run"]
fake.jobs["j1"]["status"] = "failed"
fake.jobs["j1"]["error"] = "model down"
rt.tick()
r = run_of(rt, rid)
check("a failed job -> retry in 30 s", r["status"] == "retry" and abs(r["next_try"] - clock() - 30) < 1, r)
clock.go(31); rt.tick()
check("the retry starts a new job", len(fake.created) == 2)
fake.jobs["j2"]["status"] = "failed"
rt.tick()
check("second failure -> 60 s backoff", abs(run_of(rt, rid)["next_try"] - clock() - 60) < 1)
clock.go(61); rt.tick()
fake.jobs["j3"].update(status="done", result="BLOCKED: no model")
rt.tick()
r = run_of(rt, rid)
check("after the retries: failed, with a notice and a desktop notification", r["status"] == "failed" and fake.notes
      and any(n["kind"] == "failed" for n in rt.notices), r)
check("a BLOCKED job counts as a failure", "blocked" in r["error"], r["error"])
check("the run's log has every step", len(r["log"]) >= 6, r["log"])

rt, fake, clock = fresh()
lim = rt.save({"name": "Lim", "enabled": True, "mode": "parallel", "max_per_hour": 3, "triggers": [{"type": "manual"}], "steps": [{"type": "notify"}]})
results = [rt.fire(lim["id"], {}) for _ in range(5)]
check("at most max_per_hour runs an hour", sum(1 for x in results if x.get("run")) == 3 and "rate limit" in results[-1]["error"], results)
clock.go(3601)
check("... the next hour works again", rt.fire(lim["id"], {}).get("run"))
single = rt.save({"name": "One", "triggers": [{"type": "manual"}], "steps": [{"type": "task", "prompt": "long"}]})
rt.fire(single["id"], {})
check("mode single: a second event while it runs is skipped", "still running" in rt.fire(single["id"], {}).get("skipped", ""))
out = rt.set_stopped(True)
check("Stop all cancels running runs and their jobs", out["cancelled"] >= 1 and fake.cancelled, (out, fake.cancelled))
check("while stopped nothing fires", not rt.fire(lim["id"], {})["ok"])
rt.set_stopped(False)
check("turned back on, it fires again", rt.fire(lim["id"], {}).get("run"))

# ============================================================================ persistence, restart
section("persistence and resume after a restart")
root = TMP / "persist"
rt, fake, clock = fresh(root=root)
p = rt.save({"name": "Persist", "triggers": [{"type": "manual"}], "steps": [{"type": "task", "prompt": "x"}, {"type": "telegram", "text": "after: {{last}}"}]})
rid = rt.fire(p["id"], {})["run"]
check("saved to disk", (root / "automations.json").is_file() and (root / "runs.json").is_file())
rt2 = A.Automations(root, fake, clock=clock, env={}, sync=True)        # the engine restarted
rt2.resume()
fake.jobs["j1"].update(status="done", result="DONE: 7 things")
rt2.tick()
check("a run waiting for its job carries on after a restart (same job, no new one)", run_of(rt2, rid)["status"] == "done"
      and fake.tg == ["after: 7 things"] and len(fake.created) == 1, (run_of(rt2, rid), fake.tg))
check("runs are kept per automation (capped)", len(rt2.runs(limit=999)) <= A.MAX_RUNS_KEPT)

# ============================================================================ one machine owns it; peers
section("one machine owns each automation; shared between machines")
pc, pcf, pcc = fresh("pc", "gaming-pc")
mac, macf, macc = fresh("mac", "mohameds-mac-mini", start=pcc())
check("on the PC new automations default to the PC", pc.default_machine() == "pc")
check("on a lone Mac they default to the Mac itself", mac.default_machine() == "mohameds-mac-mini")
macf.peer_linked = True
check("on a Mac linked to the PC they default to the PC", mac.default_machine() == "pc")
shared = mac.save({"name": "Morning", "enabled": True, "triggers": [{"type": "schedule", "when": "every day at 8am"}],
                   "steps": [{"type": "telegram", "text": "gm"}]})
check("the Mac does not fire a PC automation", not mac.runs_here(shared) and not mac.fire(shared["id"], {})["ok"])
check("... unless asked to run it here once", mac.fire(shared["id"], {}, force_here=True)["ok"])
changed = pc.merge(mac.export(), "mac")
check("the PC receives it over the peer exchange", changed == 1 and pc.get(shared["id"])["name"] == "Morning")
pc.tick()
pcc.go(3600); pc.tick()
macc.go(3600); mac.tick()
check("at 08:00 only the PC sends the briefing", pcf.tg == ["gm"] and macf.tg == ["gm"][:0] + [t for t in macf.tg if t == "gm"][:1], (pcf.tg, macf.tg))
check("the Mac never fired it on its schedule", len(macf.tg) == 1)   # the one is the forced run above
mac.merge(pc.export(), "pc")
check("the PC's run stats travel back to the Mac", (mac.get(shared["id"]).get("stats") or {}).get("last_status") == "done", mac.get(shared["id"]).get("stats"))
macc.go(10)
mac.save(dict(mac.get(shared["id"]), name="Morning v2"))
pc.merge(mac.export(), "mac")
check("a newer edit wins", pc.get(shared["id"])["name"] == "Morning v2")
pcc.go(60)                        # the PC's clock is past the Mac's edit
pc.delete(shared["id"])
mac.merge(pc.export(), "pc")
check("a delete travels as a tombstone", mac.get(shared["id"]) is None)
mac.merge([{"id": shared["id"], "name": "zombie", "updated": 1, "triggers": [{"type": "manual"}], "steps": [{"type": "notify"}]}], "old")
check("an older copy never brings it back", mac.get(shared["id"]) is None)
answers = []
n = A.sync_peers(mac, call=lambda peer, m, path, body, timeout: answers.append((peer["name"], path, len(body["items"]))) or {"items": pc.export()},
                 peer_list=[{"name": "pc", "url": "http://x"}])
check("sync_peers posts /peer/automations and merges the answer", answers and answers[0][1] == "/peer/automations", answers)
A.RUNTIME = pc
check("peer_receive merges and answers with ours", "items" in A.peer_receive("mac", {"items": mac.export()}))
import peers  # noqa: E402
cb = {"automations": lambda origin, data: {"items": [1]}}
server = peers.PeerServer.__new__(peers.PeerServer)
server.callbacks = cb
check("the peer server routes POST /peer/automations", peers.PeerServer.route(server, "POST", "/peer/automations", {}, "mac") == (200, {"ok": True, "items": [1]}))
import peer_link  # noqa: E402
check("peer_link offers the automations callback", "automations" in peer_link.callbacks(S(), S()))

# ============================================================================ the agent's tool
section("the agent's `automation` tool")
rt, fake, clock = fresh()
A.RUNTIME = rt
out = A.tool("draft", "every morning at 8 send me the weather on telegram")
check("draft saves it OFF and shows the card", "switched OFF" in out and len(rt.list()) == 1 and not rt.list()[0]["enabled"], out)
check("list", rt.list()[0]["id"] in A.tool("list"))
os.environ["LOKI_JOB_ID"] = "j9"
check("a background job cannot draft or run automations", A.tool("draft", "every day at 9 notify me").startswith("error") and A.tool("run", id=rt.list()[0]["id"]).startswith("error"))
os.environ.pop("LOKI_JOB_ID")
src = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")
check("loki.py registers the tool (one block): schema, MODEL_TOOL_NAMES, planning, not in Plan mode",
      'LOCAL_TOOLS["automation"] = automation' in src and 'MODEL_TOOL_NAMES.add("automation")' in src
      and 'TOOL_CATEGORIES["planning"] += ["automation"]' in src and 'NETWORK_WRITES |= {"automation"}' in src)
check("an automation can never call the automation tool itself (no loops)", "automation" in A.FORBIDDEN_TOOLS and "schedule_task" in A.FORBIDDEN_TOOLS)
check("notification argv per OS (text never inside a script string)",
      A.notify_argv("T", "x'; rm", "darwin")[0][-1] == "x'; rm" and A.notify_argv("T", "x", "win32")[1]["LOKI_NOTE_TEXT"] == "x"
      and "$env:LOKI_NOTE_TEXT" in A.notify_argv("T", "x", "win32")[0][-1] and A.notify_argv("T", "x", "linux")[0][0] == "notify-send")

# ============================================================================ the bridge
section("over the real bridge HTTP server")
import loki_bridge  # noqa: E402


class BridgeAgent:
    model_name = "local"
    WORKSPACE = TMP

    def env_file_path(self):
        return str(TMP / "data" / ".env")


loki_bridge.PORT = 0
bstate = loki_bridge.BridgeState(BridgeAgent(), "auto-secret")
rt, fake, clock = fresh()
bstate.automations = rt
bserver = loki_bridge.BridgeHTTPServer(bstate)
threading.Thread(target=bserver.serve_forever, daemon=True).start()


def http_call(method, path, body=None, token="auto-secret", raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", bserver.server_address[1], timeout=10)
    data = raw if raw is not None else (json.dumps(body) if body is not None else None)
    conn.request(method, path, body=data, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", **(headers or {})})
    resp = conn.getresponse()
    out = resp.read()
    try:
        return resp.status, json.loads(out)
    except ValueError:
        return resp.status, out


code, out = http_call("POST", "/automations/draft", {"text": "every morning at 8 send me the weather and my calendar on Telegram"})
check("POST /automations/draft", code == 200 and out["ok"] and out["card"]["when"], out)
code, saved = http_call("POST", "/automations/save", {"automation": dict(out["automation"], enabled=True)})
check("POST /automations/save", code == 200 and saved["automation"]["enabled"], saved)
aid = saved["automation"]["id"]
code, listing = http_call("GET", "/automations")
check("GET /automations lists it with its card, templates and the machine", code == 200 and listing["automations"][0]["id"] == aid
      and len(listing["templates"]) == 8 and listing["machine"]["kind"] == "pc", listing.keys() if isinstance(listing, dict) else listing)
check("without the bridge token: 401", http_call("GET", "/automations", token="x")[0] == 401)
code, out = http_call("POST", "/automations/run", {"id": aid})
check("POST /automations/run starts a run", code == 200 and out.get("run"), out)
code, out = http_call("GET", "/automations/runs?id=" + aid)
check("GET /automations/runs?id= gives its runs with logs", code == 200 and out["runs"] and out["runs"][0]["log"], out)
check("POST /automations/toggle", http_call("POST", "/automations/toggle", {"id": aid, "enabled": False})[1]["automation"]["enabled"] is False)
code, out = http_call("POST", "/automations/template", {"template": "price-watch"})
check("POST /automations/template gives a draft + what it needs", code == 200 and out["automation"]["template"] == "price-watch" and out["needs"] == ["telegram"])
check("bad input -> 400 with the reason", http_call("POST", "/automations/save", {"automation": {"name": ""}})[0] == 400)
check("POST /automations/stop is the kill switch", http_call("POST", "/automations/stop", {"stopped": True})[1]["stopped"] is True)
http_call("POST", "/automations/stop", {"stopped": False})
hook = rt.save({"name": "Hook", "enabled": True, "triggers": [{"type": "webhook"}], "steps": [{"type": "telegram", "text": "hook {{trigger.n}}"}]})
hkey = hook["triggers"][0]["key"]
code, out = http_call("POST", "/hook/%s?key=%s" % (hook["id"], hkey), {"n": 5}, token="")
check("POST /hook/<id>?key= fires WITHOUT the bridge token", code == 200 and fake.tg[-1] == "hook 5", (code, out, fake.tg))
code, out = http_call("POST", "/hook/%s" % hook["id"], {"n": 6}, token="", headers={"X-Loki-Hook-Key": hkey})
check("... or with the X-Loki-Hook-Key header", code == 200 and fake.tg[-1] == "hook 6", (code, out))
check("a wrong key -> 404", http_call("POST", "/hook/%s?key=bad" % hook["id"], {"n": 7}, token="")[0] == 404)
check("a plain-text body is the trigger's body", http_call("POST", "/hook/%s?key=%s" % (hook["id"], hkey), raw="hi there", token="",
                                                           headers={"Content-Type": "text/plain"})[0] == 200)
check("a body over 64 KB is refused", http_call("POST", "/hook/%s?key=%s" % (hook["id"], hkey), raw="x" * 70000, token="")[0] == 413)
bserver.shutdown()
bsrc = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
check("the bridge starts the runner once at start-up", bsrc.count("automations.start(state, loki)") == 1)

# ============================================================================ the window
section("the Automations view")
html = (REPO / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("index.html loads automations.js after icons.js, and its stylesheet",
      html.index("/ui/icons.js") < html.index("/ui/automations.js") and "/ui/automations.css" in html)
check("a Settings rail tab + panel", 'data-tab="automations"' in html and 'data-panel="automations"' in html)
js = (REPO / "app" / "ui" / "automations.js").read_text(encoding="utf-8")
check("the tab gets an icon with a tooltip (icons.js pattern)", "TAB_ICONS.automations" in js and "ICON_PATHS.bolt" in js and "dataset.icon" in js)
check("app.js loads the view when the tab opens", 'name === "automations" && window.Automations' in (REPO / "app" / "ui" / "app.js").read_text(encoding="utf-8"))
check("no inline handlers or eval (CSP script-src 'self')", "onclick=" not in js and "eval(" not in js and "innerHTML" not in js)

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None
chromium = next((p for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium") if p and os.path.exists(p)), "")
if sync_playwright is None or not chromium:
    print("  (skip: no Playwright/Chromium here - the view is checked statically only)")
else:
    sys.path.insert(0, str(REPO / "tests" / "automations_preview"))
    import shot  # noqa: E402
    result = shot.run(TMP / "shots")
    check("the view renders in headless Chromium with no script error", not result["errors"], result["errors"][:5])
    check("the list shows the seeded automations with switches", result["rows"] >= 3, result)
    check("hovering the rail icon shows its tooltip", "Automations" in result["tip"], result["tip"])
    check("drafting from a sentence shows the card", "On a schedule" in result["draft"], result["draft"][:300])
    check("History opens a run's log", "started by" in result["history"], result["history"][:300])
    check("a screenshot was written", Path(result["png"]).is_file() and Path(result["png"]).stat().st_size > 10000, result["png"])

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
