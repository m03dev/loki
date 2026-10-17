"""Screenshots of Settings > Lab (speed watch + jobs view) and Settings > Tools (LOKI's own tools) in
headless Chromium, against the REAL engine code (engine/self_api.py, evolve.py, job_stats.py,
speed_watch.py, user_tools.py) with seeded data in a temp folder.

    python tests/lab_preview/shot.py [out_dir]

Needs Playwright + Chromium (not part of the suites). Prints console errors; exit 1 if any.
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TMP = Path(tempfile.mkdtemp(prefix="loki-lab-preview-"))
os.environ["LOKI_DATA"] = str(TMP)
sys.path.insert(0, str(REPO / "engine"))

import evolve  # noqa: E402
import self_api  # noqa: E402
import speed_watch  # noqa: E402
import user_tools  # noqa: E402

TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}


class Store:
    def __init__(self, jobs):
        self.jobs = {j["id"]: j for j in jobs}

    def all(self):
        return list(self.jobs.values())

    def get(self, job_id):
        return self.jobs.get(job_id)


class Jobs:
    def __init__(self, jobs):
        self.store = Store(jobs)

    def create(self, spec):
        job = {"id": "new%d" % len(self.store.jobs), "status": "queued", **spec}
        self.store.jobs[job["id"]] = job
        return job


class Agent:
    DATA_DIR = str(TMP)
    USER_TOOLS = None
    MODELS = {"local": 1, "groq": 1, "gemini": 1}
    SMART_ORDER = ["local", "groq", "gemini"]

    @staticmethod
    def routing_order(order):
        return list(order)

    @staticmethod
    def provider_tier(name):
        return "free"

    @staticmethod
    def paid_allowed_automatically():
        return False

    @staticmethod
    def provider_configured(name):
        return True


def seed() -> tuple:
    rng = random.Random(7)
    now = time.time()
    (TMP / "jobs").mkdir(parents=True, exist_ok=True)
    jobs = []
    titles = [("Make a picture of a fox asleep in the snow", "picture"), ("Research free image models for the PC", "research"),
              ("Build a landing page for the bakery", "build"), ("Builder: write the tests", "team"),
              ("Self-test: write a file", "selftest")]
    fails = ["timed out after 900s", "BLOCKED: Builder's role unavailable", "The model returned empty replies repeatedly; task halted.",
             "BLOCKED: I was stuck in a loop"]
    for i in range(70):
        days_ago = rng.uniform(0, 29)
        # the job loop got better after the session-27 fixes (two weeks ago)
        p_ok = 0.25 if days_ago > 14 else 0.82
        title, kind = rng.choice(titles)
        model = "local" if rng.random() < 0.7 else rng.choice(["groq", "gemini"])
        ok = rng.random() < (p_ok + (0.12 if model != "local" else 0))
        jid = "j%03d" % i
        t = now - days_ago * 86400
        dur = rng.uniform(60, 900) * (2.5 if kind == "build" else 1)
        (TMP / "jobs" / ("%s.log" % jid)).write_text("[loki-job] %s | model %s | workspace x\n%s" % (
            jid, model, "  [thinking] The local model is stuck (it kept returning empty replies) - switching this task to groq.\n"
            if (not ok and model == "local" and rng.random() < 0.3) else ""), encoding="utf-8")
        (TMP / "jobs" / ("%s.result.txt" % jid)).write_text("DONE: finished it" if ok else rng.choice(fails), encoding="utf-8")
        jobs.append({"id": jid, "title": title, "prompt": title, "status": "done" if ok else "failed", "agent": "loki",
                     "backend": "local", "model": "", "created": t - dur - 5, "started": t - dur, "finished": t,
                     "team": "t1" if kind == "team" else "", "error": "" if ok else "", "output": "", "exit_code": 0 if ok else 2})
    jobs.append({"id": "q01", "title": "Make a picture of the island at night", "prompt": "Make a picture of the island at night",
                 "status": "queued", "agent": "loki", "backend": "local", "created": now})
    jobs.append({"id": "q02", "title": "Build a small game where the fox collects berries", "prompt": "Build a small game where the fox collects berries",
                 "status": "working", "agent": "loki", "backend": "local", "created": now - 200, "started": now - 180})
    # speed watch: two weeks of timings
    for i in range(160):
        t = now - rng.uniform(0, 13) * 86400
        speed_watch.record("model_call", rng.lognormvariate(8.0, 0.5), clock=lambda: t, note="local")
        if i % 2 == 0:
            speed_watch.record("tools", rng.lognormvariate(5.5, 1.0), clock=lambda: t,
                               note=rng.choice(["read_file", "edit_file", "web_search", "conductor", "write_file"]))
        if i % 4 == 0:
            speed_watch.record("triage", rng.lognormvariate(5.0, 0.4), clock=lambda: t)
            speed_watch.record("request", rng.lognormvariate(10.0, 0.6), clock=lambda: t, note="chat")
        if i % 8 == 0:
            speed_watch.record("verification", rng.lognormvariate(6.0, 0.5), clock=lambda: t)
        if i % 20 == 0:
            speed_watch.record("startup", rng.uniform(4000, 9000), clock=lambda: t)
            speed_watch.record("first_paint", rng.uniform(250, 600), clock=lambda: t)
            speed_watch.record("ui_ready", rng.uniform(900, 2200), clock=lambda: t)
    # daily self-test history
    runs = []
    for d in range(10, 0, -1):
        rate = 1.0 if d not in (6, 3) else round(2 / 3, 3)
        runs.append({"t": now - d * 86400, "day": time.strftime("%Y-%m-%d-0400", time.localtime(now - d * 86400)),
                     "folder": "", "jobs": {}, "expected": {}, "rate": rate, "regression": d == 3,
                     "results": [{"task": "write", "ok": True}, {"task": "sum", "ok": rate == 1.0, "why": "wrong total"},
                                 {"task": "list", "ok": True}]})
    (TMP / "selftest.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")
    # evolve: the real roadmap + ideas
    ev = evolve.Evolve(REPO, TMP)
    ev.add_idea("Show the PC's GPU temperature in the Machines tab")
    ev.add_idea("LOKI's idea (job dashboard): Make picture jobs work: 6 of 14 failed this week. Look at how a picture job is set "
                "up (tools offered, prompt, model) and change what makes it fail.", by="loki", kind="review")
    ev.add_idea("LOKI's idea (speed watch): " + speed_watch.idea_for(speed_watch.summary()["slowest"]), by="loki", approved=True, kind="speed")
    # tools LOKI wrote
    user_tools.make("word_count", "Count the words in a text.", "def run(args):\n    return str(len(str(args.get('text', '')).split()))\n",
                    parameters={"text": {"type": "string"}}, required=["text"], tests=[{"args": {"text": "a b"}, "expect": "2"}])
    user_tools.make("csv_columns", "List the column names of a CSV file in the workspace.",
                    "import csv\ndef run(args):\n    with open(args['path'], newline='') as fh:\n        return ', '.join(next(csv.reader(fh)))\n",
                    parameters={"path": {"type": "string"}}, required=["path"],
                    tests=[{"args": {"path": "missing.csv"}, "expect": "name"}])
    state = type("S", (), {})()
    state.agent = Agent()
    state.jobs = Jobs(jobs)
    state.evolve = ev
    return state, ev


def make_handler(state, ev):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            for prefix, folder in (("/ui/", REPO / "app" / "ui"), ("/preview/", HERE)):
                if path.startswith(prefix):
                    f = (folder / path[len(prefix):]).resolve()
                    if folder.resolve() in f.parents and f.is_file():
                        self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
                    else:
                        self._send(404, {"ok": False})
                    return
            if path == "/evolve":
                self._send(200, ev.status() | {"log": []})
                return
            self._send(*self_api.route(state, "GET", self.path, {}))

        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
            self._send(*self_api.route(state, "POST", self.path, data, lambda s, r, spec: (200, {"ok": True, "id": "x"})))
    return H


def main(out: Path) -> int:
    from playwright.sync_api import sync_playwright  # pylint: disable=import-outside-toplevel
    out.mkdir(parents=True, exist_ok=True)
    state, ev = seed()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, ev))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/preview/preview.html" % srv.server_address[1]
    errors: list = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1040, "height": 900}, device_scale_factor=1)
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_function("window.previewReady === true", timeout=30000)
        page.wait_for_timeout(300)
        if page.evaluate("window.previewError || ''"):
            errors.append(page.evaluate("window.previewError"))
        page.locator("#lab-jobs").screenshot(path=str(out / "lab_jobs.png"))
        page.locator("#lab-speed").screenshot(path=str(out / "lab_speed.png"))
        page.locator("#lab-panel").screenshot(path=str(out / "lab_full.png"))
        page.locator("#user-tools").screenshot(path=str(out / "tools_user_tools.png"))
        info = page.evaluate("""() => ({sparks: document.querySelectorAll('#lab-speed svg.spark polyline').length,
            bars: document.querySelectorAll('#lab-jobs svg.daybars rect').length,
            retry: [...document.querySelectorAll('#lab-jobs button')].filter(b => b.textContent.includes('stronger')).length,
            lokiIdeas: [...document.querySelectorAll('.lab-row b')].filter(b => b.textContent.includes("LOKI's idea")).length,
            tools: document.querySelectorAll('#user-tools .lab-row').length})""")
        print("rendered:", info)
        page.locator("#lab-jobs button", has_text="stronger").first.click()
        page.wait_for_timeout(300)
        print("retry click notice:", page.evaluate("window.notices"))
        browser.close()
    srv.shutdown()
    for e in errors:
        print("CONSOLE ERROR", e)
    ok = not errors and info["sparks"] >= 5 and info["bars"] >= 30 and info["retry"] >= 1 and info["lokiIdeas"] >= 2 and info["tools"] == 2
    print("screenshots in", out, "OK" if ok else "PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("lab_shots")))
