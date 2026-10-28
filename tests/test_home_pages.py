"""Home pages reach EVERY picture (owner 2026-10-27: "add pages so i can see more images, i should always be able to
see the images" - the old answer held only the newest 48, older pictures fell off Home)."""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import home_projects as hp
ws = Path(tempfile.mkdtemp()); (ws / "images").mkdir()
for i in range(150):
    f = ws / "images" / ("pic_%03d.png" % i); f.write_bytes(b"\x89PNG\r\n\x1a\n"); os.utime(f, (1e9 + i, 1e9 + i))
class A: WORKSPACE = str(ws); DATA_DIR = str(ws / "data")
class St: agent = A(); jobs = None
old = hp.collect(St())
got, n = [], 1
while True:
    r = hp.page(St(), "made", n, 60)
    got += [it["path_or_id"] for it in r["items"]]
    if n >= r["pages"]: break
    n += 1
FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- " + str(detail)[:200]))
    if not ok:
        FAILS.append(name)
check("the old one-shot answer still sends only the newest (fast Home refresh)", sum(1 for i in old["items"] if i["kind"] == "made") == 48)
check("150 pictures -> 3 pages of 60", r["pages"] == 3 and r["total"] == 150, r["total"])
check("every picture is on some page", len(set(got)) == 150, len(set(got)))
check("the oldest picture can still be seen", "images/pic_000.png" in got)
check("newest first", got[0] == "images/pic_149.png", got[0])
code, body = hp.route(St(), "/home/projects", {"page": "3", "kind": "made"})
check("GET /home/projects?page=3&kind=made -> page 3 with the last 30", code == 200 and body["page"] == 3 and len(body["items"]) == 30)
code, body = hp.route(St(), "/home/projects", {"page": "99"})
check("a page past the end shows the last page", body["page"] == body["pages"])
check("bad numbers are refused, not a crash", hp.route(St(), "/home/projects", {"page": "x"})[0] == 400)
print("\n%d passed, %d failed" % (8 - len(FAILS), len(FAILS)))
sys.exit(1 if FAILS else 0)
