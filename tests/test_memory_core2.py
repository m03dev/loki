"""Session 28: memory & knowledge as ONE system, offline.

  the store (append-only log, last writer wins, tombstones, redaction, vectors, migration),
  kinds and contradictions, careful learning (dedupe, near-duplicates, supersede with history,
  restore, review), automatic writing (rules; secrets and junk never kept), hybrid search (BM25,
  synonyms, a fake local embedder, fallback), the token budget, sync between two and three
  machines (also over the real signed peer server), the owner's notes synced, the project index
  (incremental, path:line citations), the one pack, the bridge API, the agent's hooks, and
  THE EVAL: 30 questions against seeded memories - the right memory is recalled and the prompt
  stays under budget.

    python tests/test_memory_core2.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TMP = Path(tempfile.mkdtemp(prefix="loki-mem2-"))
os.environ["LOKI_DATA"] = str(TMP / "data")
os.environ["LOKI_WORKSPACE"] = str(TMP / "ws")
os.environ["LOKI_EMBED"] = "off"
os.environ["LOKI_PEER_NAME"] = "mac"
for _k in ("LOKI_JOB_ID", "LOKI_TEAM_ID", "LOKI_MEMORY_CORE", "LOKI_MEMORY_EXTRACT", "LOKI_PEERS", "LOKI_PEER_SECRET"):
    os.environ.pop(_k, None)
(TMP / "ws").mkdir(parents=True, exist_ok=True)

import knowledge  # noqa: E402
import memory  # noqa: E402
import memory_core  # noqa: E402
import memory_extract  # noqa: E402
import memory_kinds  # noqa: E402
import memory_search  # noqa: E402
import memory_store  # noqa: E402
import memory_sync  # noqa: E402
import peers  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:400],)))


def section(title):
    print("\n== " + title)


@contextmanager
def as_host(name):
    old = os.environ.get("LOKI_PEER_NAME")
    os.environ["LOKI_PEER_NAME"] = name
    try:
        yield
    finally:
        os.environ["LOKI_PEER_NAME"] = old or ""


def root(name):
    path = TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def texts(r):
    return [i["text"] for i in memory_core.items(r)]


# =========================================================================== the store
section("the store: append-only log, last writer wins, tombstones")
S = root("store")
a = {"id": "m1", "kind": "fact", "tier": "semantic", "text": "first words", "t": 1, "status": "active"}
memory_store.put(a, S)
memory_store.put(dict(a, text="second words"), S)
check("a put is an operation in the log; the newest wins", memory_store.get("m1", S)["text"] == "second words"
      and len(memory_store.ops(S)) == 2)
ops = memory_store.ops(S)
check("operations are named (host, n) and carry a clock", [o["n"] for o in ops] == [1, 2]
      and all(o["host"] == "mac" for o in ops) and ops[1]["v"] > ops[0]["v"], ops)
check("the vector says what this machine holds", memory_store.vector(S) == {"mac": 2})
memory_store.delete("m1", S)
raw = memory_store.log_path(S).read_text(encoding="utf-8")
check("forget writes a tombstone and removes the item", memory_store.get("m1", S) is None
      and memory_store.tombstones(S) == 1 and memory_store.items(S) == [])
check("forget redacts the text from every older operation", "first words" not in raw and "second words" not in raw, raw)
check("ops_since gives what a machine lacks", len(memory_store.ops_since({"mac": 1}, S)) == 2
      and memory_store.ops_since({"mac": 3}, S) == [])

section("merging: idempotent, order-independent, tombstones win when newer")
A, B = root("merge-a"), root("merge-b")
with as_host("pc"):
    memory_store.put({"id": "x1", "kind": "fact", "text": "pc wrote this", "status": "active", "t": 1}, B)
with as_host("mac"):
    memory_store.put({"id": "x1", "kind": "fact", "text": "mac wrote this later", "status": "active", "t": 1}, A)
pc_ops, mac_ops = memory_store.ops(B), memory_store.ops(A)
memory_store.merge(pc_ops, A)
memory_store.merge(mac_ops, B)
check("both machines agree on the winner (the later write)", memory_store.get("x1", A)["text"]
      == memory_store.get("x1", B)["text"] == "mac wrote this later")
again = memory_store.merge(pc_ops + mac_ops, A)
check("merging the same operations again changes nothing", again["received"] == 0 and len(memory_store.ops(A)) == 2)
C, D = root("order-c"), root("order-d")
memory_store.merge(mac_ops + pc_ops, C)
memory_store.merge(list(reversed(mac_ops + pc_ops)), D)
check("the order operations arrive in does not matter", memory_store.get("x1", C)["text"] == memory_store.get("x1", D)["text"])
with as_host("pc"):
    tomb = memory_store.delete("x1", B)
memory_store.merge([tomb], A)
check("a newer tombstone from the other machine forgets it here", memory_store.get("x1", A) is None)
late = dict(mac_ops[0], n=99, v=mac_ops[0]["v"] - 1000)
memory_store.merge([late], A)
check("a stale copy arriving late cannot bring a forgotten memory back", memory_store.get("x1", A) is None
      and "mac wrote this later" not in memory_store.log_path(A).read_text(encoding="utf-8"))
bad = memory_store.merge([{"op": "put", "id": "../etc", "host": "x", "n": 1, "v": 1, "item": {"id": "../etc"}},
                          {"op": "zap", "id": "a", "host": "x", "n": 1, "v": 1}, "nonsense"], A)
check("malformed operations are dropped", bad["dropped"] == 3 and bad["received"] == 0, bad)

section("compaction keeps the vector; migration from session 26's file")
K = root("compact")
for n in range(30):
    memory_store.put({"id": "c%d" % (n % 3), "kind": "fact", "text": "v%d" % n, "status": "active", "t": 1}, K)
vec_before = memory_store.vector(K)
memory_store.compact(K)
check("compaction keeps only each item's winner", len(memory_store.ops(K)) == 3 and memory_store.get("c2", K)["text"] == "v29")
check("...and the vector never goes backwards", memory_store.vector(K) == vec_before, (vec_before, memory_store.vector(K)))
memory_store.put({"id": "c9", "kind": "fact", "text": "after", "status": "active", "t": 1}, K)
check("new operations continue the counter", memory_store.ops(K)[-1]["n"] == 31, memory_store.ops(K)[-1])
M = root("migrate")
(M / "memory_core.jsonl").write_text(json.dumps({"id": "mold1", "tier": "semantic", "text": "old learning", "tags": [],
                                                 "t": 5, "uses": 3, "last_used": 6, "source": "agent", "meta": {}}) + "\n")
check("the session-26 file is migrated into the log, uses kept locally",
      texts(M) == ["old learning"] and memory_core.items(M)[0]["uses"] == 3
      and (M / "memory_core.jsonl.migrated").is_file() and not (M / "memory_core.jsonl").exists())

# =========================================================================== kinds
section("kinds and contradictions (memory_kinds)")
cases = {"Mia is the owner's sister": "person", "The owner prefers short answers": "preference",
         "The owner decided to use Godot for the racing game": "decision", "The owner's name is Mohamed": "profile",
         "The owner is working on Waypoint, a Maya companion app": "project", "The relay port is 41234": "fact"}
got = {t: memory_kinds.kind_of(t) for t in cases}
check("rules name the kind", got == cases, got)
check("an episodic learning with a lesson is a lesson", memory_kinds.kind_of("Next time run the tests first", "episodic") == "lesson")
pairs = [("The owner's editor is Zed", "The owner's editor is VS Code", True),
         ("The owner prefers dark mode", "The owner prefers light mode", True),
         ("The owner lives in Lisbon", "The owner lives in Porto", True),
         ("The owner no longer likes sushi", "The owner likes sushi", True),
         ("The owner prefers short answers", "The owner prefers dark mode", False),
         ("Sam is a designer", "Sam is the owner's friend", False),
         ("The owner's editor is Zed", "The owner's editor is Zed", False),
         ("The relay runs on bore.pub port 41234", "The owner likes tea", False)]
wrong = [(a_, b_) for a_, b_, want in pairs if memory_kinds.contradicts(a_, b_) != want]
check("contradictions: same attribute, new value - and only then", not wrong, wrong)
check("secrets are recognised", all(memory_kinds.is_secret(t) for t in (
    "my key is sk-abcdefghijklmnop1234", "password: hunter22", "ghp_abcdefghijklmnopqrstuvwx",
    "card 4111 1111 1111 1111", "-----BEGIN RSA PRIVATE KEY-----")) and not memory_kinds.is_secret("The relay port is 41234"))
check("junk is recognised", all(memory_kinds.is_junk(t) for t in ("thanks!", "what is my name?", "I am busy right now", "ok")))

# =========================================================================== learning
section("careful learning: dedupe, near-duplicates, supersede with history, restore, review")
L = root("learn")
r1 = memory_core.learn("The owner's editor is VS Code", root=L)
check("learn names the kind", r1["ok"] and r1["kind"] == "profile", r1)
dup = memory_core.learn("the owner's editor is vs code", root=L)
check("the same again refreshes it", dup.get("updated") and len(texts(L)) == 1)
near = memory_core.learn("The owner's editor is VS Code.", root=L)
check("a near-duplicate merges into it", near.get("updated") and len(texts(L)) == 1, near)
r2 = memory_core.learn("The owner's editor is Zed", root=L)
check("a contradiction supersedes the older memory", r2.get("superseded") == [r1["id"]] and texts(L) == ["The owner's editor is Zed"], r2)
newer = memory_core.get(r2["id"], L)
older = [i for i in memory_core.all_items(L) if i["id"] == r1["id"]][0]
check("history is kept on both sides", newer["history"][0]["text"].rstrip(".") == "The owner's editor is VS Code"
      and older["status"] == "superseded" and older["superseded_by"] == r2["id"])
found = memory_core.recall("which editor does the owner use", root=L)
check("recall finds the new value, never the superseded one", "Zed" in found["evidence"] and "VS Code" not in found["evidence"], found)
memory_core.restore(r1["id"], L)
check("restore makes the older one current again", [t.rstrip(".") for t in texts(L)] == ["The owner's editor is VS Code"])
memory_core.restore(r2["id"], L)
memory_core.edit(r2["id"], "The owner's editor is Zed, with vim keys", L)
check("edit keeps the old wording in the history", memory_core.get(r2["id"], L)["history"][-1]["text"] == "The owner's editor is Zed")
sec = memory_core.learn("deploy token: abcdefghijklmnopqrstuvwxyz0123456789", root=L)
check("an explicit learn stores a secret only as [secret]", "abcdefghij" not in memory_core.get(sec["id"], L)["text"])
auto = memory_core.learn("The owner prefers short answers", root=L, source="auto", review=True)
check("an automatic learning waits for review", [i["id"] for i in memory_core.learned_since(0, L)] == [auto["id"]])
memory_core.keep(auto["id"], L)
check("keep takes it off the review list", memory_core.learned_since(0, L) == [] and memory_core.get(auto["id"], L))
f = memory_core.forget(auto["id"], root=L)
check("forget by id leaves a tombstone", f["forgotten"] == 1 and memory_core.stats(L)["forgotten"] >= 1)
st = memory_core.stats(L)
check("stats count kinds, superseded and forgotten", st["by_kind"].get("profile") and "search" in st and st["host"] == "mac", st)
ep = memory_core.learn("Lesson: always run the suites before shipping", tier="episodic", root=L)
check("episodic learnings never supersede each other", ep["kind"] == "lesson" and not ep.get("superseded"))

# =========================================================================== automatic writing
section("automatic writing: selective, never secrets (memory_extract)")
msgs = [{"role": "system", "content": "you are LOKI"},
        {"role": "user", "content": "My name is Mohamed. I prefer short answers. Mia is my sister."},
        {"role": "assistant", "content": "I prefer long answers myself."},
        {"role": "tool", "content": "my name is Toolbot"},
        {"role": "user", "content": "my api key is sk-abcdefghijklmnopqrstuvwx and my password is hunter22"},
        {"role": "user", "content": "thanks! what's the weather today?"}]
found = memory_extract.extract(msgs)
check("the owner's durable statements are found, in the third person",
      [t for t, _ in found] == ["The owner's name is Mohamed.", "The owner prefers short answers.", "Mia is the owner's sister."], found)
check("...with their kinds", [k for _, k in found] == ["profile", "preference", "person"])
check("the model's words and tool output are never mined", not any("long" in t or "Toolbot" in t for t, _ in found))
check("a sentence with a secret is dropped whole", not any("hunter" in t or "sk-" in t for t, _ in found))
E = root("auto")
noted = memory.after_request(msgs, "done", root=E)
check("after_request learns them, marked for review", len(noted) == 3 and len(memory_core.learned_since(0, E)) == 3, noted)
check("the same chat again teaches nothing new", memory.after_request(msgs, "done", root=E) == [])
more = memory_extract.extract([{"role": "user", "content": "we decided to use Godot for the racing game. always answer in English. "
                                                          "remember that the relay port is 41234. I like pizza right now. "
                                                          "make me a landing page."}])
check("decisions, standing instructions and 'remember that' - not tasks or right-now things",
      [t for t, _ in more] == ["The owner decided to use Godot for the racing game.", "The owner wants LOKI to always answer in English.",
                               "The relay port is 41234."], more)
check("at most three per request", len(memory_extract.extract([{"role": "user", "content": "I like tea. I like jazz. I like cats. I like rain."}])) == 3)
os.environ["LOKI_MEMORY_EXTRACT"] = "off"
check("LOKI_MEMORY_EXTRACT=off stops it", memory_extract.extract(msgs) == [])
os.environ["LOKI_MEMORY_EXTRACT"] = "model"
fake = lambda prompt: '{"facts": [{"text": "The owner has a cat named Pixel", "kind": "person"}, {"text": "token is sk-abcdefghijklmnopqrstu"}, {"text": "hi"}]}'  # noqa: E731
check("a model's answers pass the same filters", memory_extract.extract(msgs[:2], ask=fake) == [("The owner has a cat named Pixel.", "person")])
os.environ.pop("LOKI_MEMORY_EXTRACT")
check("an errored request teaches nothing", memory.after_request(msgs, "error", root=root("auto-err")) == [])
os.environ["LOKI_JOB_ID"] = "job1"
check("a background job's prompt (written by LOKI, not said by the owner) teaches nothing",
      memory.after_request([{"role": "user", "content": "Always run check_loki before ship_loki."}], "done", root=root("auto-job")) == [])
os.environ.pop("LOKI_JOB_ID")

# =========================================================================== search
section("hybrid search: BM25, synonyms, a local embedder, fallback, dedupe, budget")
H = root("search")
for t in ("The owner's Windows PC has an RTX 3070 Ti", "The owner prefers dark mode everywhere",
          "Tomatoes on the balcony need water every two days", "The blue tin holds the coffee beans"):
    memory_core.learn(t, root=H)
check("synonyms: 'gpu' finds the RTX", "RTX" in memory_core.recall("what gpu is in the pc", root=H)["evidence"])
check("synonyms: 'theme' finds dark mode", "dark mode" in memory_core.recall("light or dark theme", root=H)["evidence"])
check("unrelated words find nothing", memory_core.recall("quantum chromodynamics", root=H)["items"] == [])
check("paraphrase without shared words: BM25 alone misses it",
      "coffee" not in memory_core.recall("where is the espresso kept", root=H)["evidence"])
VOCAB = {"coffee": 0, "espresso": 0, "beans": 0, "tin": 1, "kept": 1, "holds": 1, "tomato": 2, "balcony": 2,
         "water": 2, "gpu": 3, "rtx": 3, "pc": 3, "dark": 4, "mode": 4, "theme": 4}


VOCAB_S = {memory_search.stem(k): v for k, v in VOCAB.items()}


def fake_embed(batch):
    """A toy local embedder: a few hand-made topic dimensions (coffee/espresso share one)."""
    out = []
    for text in batch:
        v = [0.0] * 6
        for w in memory_search.words(text):
            v[VOCAB_S.get(w, 5)] += 1.0
        out.append(v)
    return out


memory_search.EMBEDDER_OVERRIDE = fake_embed
try:
    hy = memory_core.recall("where is the espresso kept", root=H)
    check("with a local embedder the paraphrase is found (hybrid)", "coffee" in hy["evidence"], hy)
    check("vectors are cached on disk by text", (H / "memory_vectors.json").is_file())
    check("the search reports hybrid mode", memory_search.status()["mode"] == "hybrid")
    memory_search.EMBEDDER_OVERRIDE = lambda batch: (_ for _ in ()).throw(OSError("embedder down"))
    (H / "memory_vectors.json").unlink()
    fb = memory_core.recall("what gpu is in the pc", root=H)
    check("an embedder that fails falls back to BM25", "RTX" in fb["evidence"], fb)
finally:
    memory_search.EMBEDDER_OVERRIDE = None
    memory_search._EMBED_STATE.update(model=None, t=0.0)
ranked = memory_search.dedupe([(1.0, {"text": "The owner likes tea a lot"}, {}), (0.9, {"text": "the owner likes tea a lot."}, {})])
check("near-identical results collapse into one", len(ranked) == 1)
kept, used, left = memory_search.fit([("x" * 400, None), ("y" * 400, None), ("z" * 40, None)], 120)
check("the token budget keeps whole entries that fit", used <= 120 and left == 1 and len(kept) == 2, (used, left))

# =========================================================================== sync
section("sync: a fact taught on the Mac is known on the PC (and back)")
MAC, PC = root("sync-mac"), root("sync-pc")


def wire(here, there, there_name):
    """A peers.call stand-in: the request lands in the other machine's memory_sync.receive."""
    def call(peer, method, path, payload, timeout=30):
        assert method == "POST" and path == "/peer/memory"
        with as_host(there_name):
            return memory_sync.receive(os.environ.get("_ORIGIN", "?"), json.loads(json.dumps(payload)), root=there)
    return call


with as_host("mac"):
    taught = memory_core.learn("The owner's sister Mia lives in Oslo", root=MAC)
    out = memory_sync.exchange({"name": "pc"}, MAC, call=wire(MAC, PC, "pc"))
check("the Mac sends what the PC lacks", out["sent"] >= 1 and out["received"] == 0, out)
with as_host("pc"):
    on_pc = memory.retrieve("where does Mia live", root=PC, knowledge=False)
check("asked on the PC, the Mac's fact is recalled", any("Oslo" in i["text"] for i in on_pc["items"]), on_pc)
with as_host("pc"):
    memory_core.learn("The owner's PC is called PIXEL-TOWER", root=PC)
    memory_core.forget(taught["id"], root=PC)
with as_host("mac"):
    back = memory_sync.exchange({"name": "pc"}, MAC, call=wire(MAC, PC, "pc"))
check("the PC's new fact comes back to the Mac", any("PIXEL-TOWER" in t for t in texts(MAC)), back)
check("forgotten on the PC = forgotten on the Mac, text redacted", memory_core.get(taught["id"], MAC) is None
      and "Oslo" not in memory_store.log_path(MAC).read_text(encoding="utf-8"))
with as_host("mac"):
    nothing = memory_sync.exchange({"name": "pc"}, MAC, call=wire(MAC, PC, "pc"))
check("nothing new -> nothing sent", nothing["sent"] == 0 and nothing["received"] == 0, nothing)
check("both machines hold the same memory", sorted(texts(MAC)) == sorted(texts(PC)))
THIRD = root("sync-laptop")
with as_host("laptop"):
    memory_sync.exchange({"name": "pc"}, THIRD, call=wire(THIRD, PC, "pc"))
check("a third machine gets the Mac's memories through the PC", sorted(texts(THIRD)) == sorted(texts(PC)))
with as_host("mac"):
    memory_core.edit([i for i in memory_core.items(MAC) if "PIXEL" in i["text"]][0]["id"], "The owner's PC is called PIXEL-TOWER-2", MAC)
with as_host("pc"):
    time.sleep(0.01)
    memory_core.edit([i for i in memory_core.items(PC) if "PIXEL" in i["text"]][0]["id"], "The owner's PC is called NOVA", PC)
with as_host("mac"):
    memory_sync.exchange({"name": "pc"}, MAC, call=wire(MAC, PC, "pc"))
check("a concurrent edit: the later writer wins on both machines",
      [t for t in texts(MAC) if "PC is called" in t] == [t for t in texts(PC) if "PC is called" in t] == ["The owner's PC is called NOVA"])
evil = [{"op": "put", "id": "mevil1", "host": "pc", "n": 900, "v": time.time(),
         "item": {"id": "mevil1", "kind": "fact", "text": "the root password: hunter2hunter2", "status": "active", "t": 1}}]
memory_store.merge(evil, MAC, clean=memory_core.clean_item)
check("a received memory is scrubbed again before it is stored", "hunter2hunter2" not in memory_core.get("mevil1", MAC)["text"])
st = memory_sync.status(MAC)
check("the sync status says when each machine last synced", any(p["peer"] == "pc" and p["t"] > 0 for p in st["peers"]), st)

section("the owner's notes (memory.md) ride along")
NM, NP = root("notes-mac"), root("notes-pc")
(NM / "memory.md").write_text("- likes small PRs\n", encoding="utf-8")
(NP / "memory.md").write_text("- uses a Mac mini\n", encoding="utf-8")
with as_host("mac"):
    memory_sync.exchange({"name": "pc"}, NM, call=wire(NM, NP, "pc"))
with as_host("mac"):
    memory_sync.exchange({"name": "pc"}, NM, call=wire(NM, NP, "pc"))
both = [(NM / "memory.md").read_text(encoding="utf-8"), (NP / "memory.md").read_text(encoding="utf-8")]
check("the first sync of two notes files keeps every line of both", all("small PRs" in b and "Mac mini" in b for b in both), both)
(NP / "memory.md").write_text("- uses a Mac mini\n- prefers tabs\n", encoding="utf-8")
with as_host("mac"):
    memory_sync.exchange({"name": "pc"}, NM, call=wire(NM, NP, "pc"))
check("an edit on one machine reaches the other", "prefers tabs" in (NM / "memory.md").read_text(encoding="utf-8"))
check("the notes document is not listed as a memory", not any(i["id"] == memory_sync.NOTES_ID for i in memory_core.all_items(NM)))

section("over the real signed peer link (peers.PeerServer, HMAC)")
SECRET = "s" * 40
SM, SP = root("signed-mac"), root("signed-pc")


def free_port() -> int:
    """PeerServer treats port 0 as 'not set' (-> the fixed default 8768), so pick a free one here."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


server = peers.PeerServer({"hello": lambda: {"name": "pc"},
                           "memory_sync": lambda origin, data: memory_sync.receive(origin, data, root=SP)},
                          env={"LOKI_PEER_SECRET": SECRET}, host="127.0.0.1", port_number=free_port()).start()
try:
    peer = {"name": "pc", "url": "http://127.0.0.1:%d" % server.address[1]}
    menv = {"LOKI_PEER_SECRET": SECRET, "LOKI_PEER_NAME": "mac"}
    memory_core.learn("The owner prefers tea over coffee", root=SM)
    res = memory_sync.exchange(peer, SM, call=lambda p, m, path, payload, timeout=30: peers.call(p, m, path, payload, env=menv, timeout=timeout))
    check("a signed exchange delivers the memory to the other machine", res["sent"] >= 1
          and any("tea over coffee" in t for t in texts(SP)), res)
    try:
        peers.call(peer, "POST", "/peer/memory", {"have": {}, "ops": []}, env={"LOKI_PEER_SECRET": "w" * 40, "LOKI_PEER_NAME": "x"})
        refused = False
    except peers.PeerError:
        refused = True
    check("a machine without the secret is refused", refused)
finally:
    server.stop()

# =========================================================================== project knowledge
section("project knowledge: incremental index with path:line citations")
WS = TMP / "proj"
(WS / "docs").mkdir(parents=True)
(WS / "src").mkdir()
(WS / "node_modules" / "x").mkdir(parents=True)
(WS / "docs" / "SETUP.md").write_text("# Setup\n\nInstall Python 3.12.\n\n## Deploy\n\nThe staging server deploys from the "
                                      "release branch every night at 02:00 UTC.\n", encoding="utf-8")
(WS / "src" / "billing.py").write_text("def invoice_total(lines):\n    \"\"\"Sum invoice lines with VAT at 21 percent.\"\"\"\n"
                                       "    return sum(l * 1.21 for l in lines)\n", encoding="utf-8")
(WS / ".env").write_text("API_KEY=sk-should-never-be-indexed-1234567890\n", encoding="utf-8")
(WS / "node_modules" / "x" / "junk.js").write_text("deploy deploy deploy", encoding="utf-8")
KD = root("kdata")
idx = knowledge.project_index(WS, KD)
first = idx.refresh()
check("the first refresh indexes docs and code (not .env, not node_modules)", first["added"] == 2 and first["files"] == 2, first)
blob = idx.path.read_text(encoding="utf-8")
check("no secret file is indexed", "should-never" not in blob and "junk.js" not in blob)
check("nothing changed -> nothing re-read", idx.refresh()["added"] == idx.refresh()["changed"] == 0)
time.sleep(0.01)
(WS / "src" / "billing.py").write_text("def invoice_total(lines):\n    \"\"\"Sum invoice lines with VAT at 19 percent.\"\"\"\n"
                                       "    return sum(l * 1.19 for l in lines)\n", encoding="utf-8")
os.utime(WS / "src" / "billing.py", (time.time() + 5, time.time() + 5))
second = idx.refresh()
check("a changed file is re-read alone", second["changed"] == 1 and second["added"] == 0, second)
hits = idx.search("when does staging deploy")
check("search cites path:line (the section, not the file's top)", hits and hits[0]["cite"] == "docs/SETUP.md:5"
      and "02:00" in hits[0]["text"], hits)
check("code is searchable and current", any("19 percent" in h["text"] for h in idx.search("what VAT rate does invoice_total use")))
(WS / "docs" / "SETUP.md").unlink()
check("a deleted file leaves the index", idx.refresh()["removed"] == 1 and not idx.search("when does staging deploy"))
check("the index is bounded by a time budget (continues next time)",
      knowledge.ProjectIndex(WS, root("kdata2")).refresh(budget_s=-1)["complete"] is False)

# =========================================================================== the one pack
section("the one pack: profile always on, the rest per request, under budget")
P = root("pack")
(P / "memory.md").write_text("\n".join("- note number %d about the owner's habits and tools" % n for n in range(80)) + "\n"
                             + "- The owner keeps backups on a NAS called VAULT-9\n", encoding="utf-8")
prof = memory.profile_block(P)
check("the always-on profile is bounded", prof["tokens"] <= memory.PROFILE_TOKENS and prof["left_out"] > 0, prof["tokens"])
pk = memory.pack("where are the owner's backups kept", root=P, lessons=False)
check("a note that did not fit the profile is still found when it matters", "VAT" not in pk["text"] and "VAULT-9" in pk["text"], pk["text"][:400])
memory_core.learn("The owner prefers short answers", root=P)
prof2 = memory.profile_block(root("pack-small"))
check("an empty profile is empty", prof2["text"] == "")
S2 = root("pack-small")
memory_core.learn("The owner prefers short answers", root=S2, kind="preference")
memory_core.learn("The owner's sister Mia lives in Oslo", root=S2)
prof3 = memory.profile_block(S2)
check("important preferences are always in the profile", "short answers" in prof3["text"] and "Oslo" not in prof3["text"], prof3)
pk3 = memory.pack("short answers please", root=S2, lessons=False)
check("a relevant profile memory is still cited by the pack (memories_used)", any("short answers" in u["text"] for u in pk3["used"]), pk3)
(S2 / "memory.md").write_text("- The owner keeps receipts in a green folder\n", encoding="utf-8")
pk3b = memory.pack("where are the receipts kept", root=S2, lessons=False)
check("a line of the owner's notes (always in the profile) is not repeated in the pack",
      "green folder" in memory.profile_block(S2)["text"] and "green folder" not in pk3b["text"], pk3b["text"])
pk4 = memory.pack("how deploy staging", root=root("pack-ws"), workspace=TMP / "proj2", lessons=False)
(TMP / "proj2" / "docs").mkdir(parents=True, exist_ok=True)
(TMP / "proj2" / "docs" / "OPS.md").write_text("# Ops\n\nStaging deploys every night from the release branch.\n", encoding="utf-8")
knowledge.project_index(TMP / "proj2", root("pack-ws")).refresh()
pk5 = memory.pack("how does staging deploy", root=root("pack-ws"), workspace=TMP / "proj2", lessons=False)
check("the pack cites the project's own files", "docs/OPS.md:1" in pk5["text"] and pk5["sources"] == ["docs/OPS.md:1"], pk5)

# =========================================================================== bridge + agent hooks
section("Settings > Memory API (loki_bridge.memory_core_api)")
import loki_bridge  # noqa: E402

BR = root("bridge")
(BR / "memory.md").write_text("- likes the fox\n", encoding="utf-8")
agent = types.SimpleNamespace(DATA_DIR=BR, WORKSPACE=WS, MEMORY_FILE=BR / "memory.md")
st_ = types.SimpleNamespace(agent=agent)
memory.after_request([{"role": "user", "content": "I prefer short answers. Mia is my sister."}], root=BR)
code, listing = loki_bridge.memory_core_api(st_, "GET", {})
check("GET lists memories, today's learnings, kinds, sync, index, profile",
      code == 200 and len(listing["today"]) == 2 and listing["kinds"] and "sync" in listing and "index" in listing
      and "fox" in listing["profile"]["text"], {k: listing.get(k) for k in ("today", "index")})
code, search = loki_bridge.memory_core_api(st_, "GET", {"q": ["who is mia"]})
check("GET ?q= shows what a request would recall, with scores", code == 200 and search["items"]
      and "Mia" in search["items"][0]["text"] and "score" in search["items"][0], search.get("items"))
code, kinds = loki_bridge.memory_core_api(st_, "GET", {"kind": ["person"]})
check("GET ?kind= filters", code == 200 and all(i["kind"] == "person" for i in kinds["items"]) and kinds["items"])
mia = [i for i in listing["today"] if "Mia" in i["text"]][0]
code, _ = loki_bridge.memory_core_api(st_, "POST", {"action": "undo", "id": mia["id"]})
check("Undo forgets an automatic learning", code == 200 and not any("Mia" in t for t in texts(BR)))
code, _ = loki_bridge.memory_core_api(st_, "POST", {"action": "keep_all"})
check("Keep all clears today's review list", code == 200 and memory_core.learned_since(0, BR) == [])
code, made = loki_bridge.memory_core_api(st_, "POST", {"action": "learn", "text": "The owner's laptop is a ThinkPad", "kind": "profile"})
code2, _ = loki_bridge.memory_core_api(st_, "POST", {"action": "edit", "id": made["id"], "text": "The owner's laptop is a Framework", "kind": "profile"})
check("learn and edit with a kind", code == code2 == 200 and memory_core.get(made["id"], BR)["text"].endswith("Framework"))
code, rx = loki_bridge.memory_core_api(st_, "POST", {"action": "reindex"})
check("Reindex runs the project index", code == 200 and rx.get("ok"), rx)
code, sy = loki_bridge.memory_core_api(st_, "POST", {"action": "sync"})
check("Sync now with no linked machine is a calm no-op", code == 200 and sy["results"] == [], sy)
code, bad_ = loki_bridge.memory_core_api(st_, "POST", {"action": "explode"})
check("an unknown action is refused", code == 400)

section("the agent uses the one path (loki._triage, _record_experience, the profile)")
import loki  # noqa: E402

AG = Path(os.environ["LOKI_DATA"])
memory_core.learn("The owner's NAS is called VAULT-9 and holds the backups", root=AG)
loki._start_request()
saved = loki.first_layer.triage
loki.first_layer.triage = lambda text, mode: {"route": "agent", "source": "rules", "kind": "chat"}
try:
    loki._triage("which NAS holds the owner's backups")
    note = loki.TRIAGE_NOTE + loki.system_prompt()
finally:
    loki.first_layer.triage = saved
    loki._end_triage()
check("a request gets its memories (the profile + memory.pack)", "VAULT-9" in note, note[-300:])
loki._start_request()
memory_core.learn("Lesson: the staging deploy breaks when the cache folder is missing", tier="episodic", root=AG)
loki.first_layer.triage = lambda text, mode: {"route": "agent", "source": "rules", "kind": "chat"}
try:
    loki._triage("why does the staging deploy break")
    note2 = loki.TRIAGE_NOTE
finally:
    loki.first_layer.triage = saved
    loki._end_triage()
check("...and per-request memories land in the request note with citations", "cache folder" in note2
      and any("cache folder" in c["text"] for c in loki.LAST_RECALL), note2[-300:])
loki.MEMORY_FILE.write_text("- prefers tabs over spaces\n", encoding="utf-8")
check("the always-on profile comes from memory.profile_block", "tabs over spaces" in loki.load_memory())
loki._start_request()
start = len(loki.messages)
loki.messages.append({"role": "user", "content": "I prefer answers with a short summary first."})
loki.messages.append({"role": "assistant", "content": "DONE: noted"})
loki._record_experience("chat", "I prefer answers with a short summary first.", "done", time.time(), start)
check("a finished chat teaches LOKI what the owner said (reply metadata)",
      loki.LAST_NOTED and "summary first" in loki.LAST_NOTED[0]["text"]
      and loki_bridge.memory_metadata(loki).get("memories_learned"), loki.LAST_NOTED)
gm = __import__("brain").build(AG, WS)
check("the brain map shows memories by kind, editable by id",
      any(n["id"].startswith("kind:") for n in gm["nodes"]) and any(n.get("mem") for n in gm["nodes"]))

# =========================================================================== THE EVAL
section("the memory eval: 30 questions, seeded memories, the right one recalled, under budget")
EV = root("eval")
SEED = {
    "name": "The owner's name is Mohamed.",
    "short": "The owner prefers short, direct answers without filler.",
    "icons": "The owner wants LOKI's UI to use icons with hover tooltips instead of words.",
    "gpu": "The owner's Windows PC has an RTX 3070 Ti with 8 GB and is on 24/7.",
    "macmini": "The owner works on a Mac mini; LOKI lives in ~/Documents/loki there.",
    "mia": "Mia is the owner's sister and lives in Oslo.",
    "dana": "Dana is the owner's manager at the studio.",
    "waypoint": "The owner is working on Waypoint, a background companion for Maya, ZBrush and Substance Painter.",
    "godot": "The owner decided to build his racing game in Godot 4 so it can ship on Steam.",
    "relay": "The owner decided to use LOKI's built-in public relay instead of Tailscale to link the Mac and the PC.",
    "editor_old": "The owner's editor is VS Code.",
    "editor": "The owner's editor is Zed.",
    "look": "The owner likes the pixel cel-shaded look of the Play games.",
    "costs": "The owner hates surprise costs: free and local models first, paid providers behind a budget.",
    "ship": "LOKI ships changes only with tools/ship.py, which runs every test suite first.",
    "tasks": "Tasks for LOKI go in LOKI_TASKS.md in git, not in the chat reply.",
    "port": "The relay runs on bore.pub port 41234.",
    "lang": "The owner speaks English and Arabic.",
    "city": "The owner lives in Dubai.",
    "bday": "The owner's birthday is March 3.",
    "job": "The owner works as a 3D artist and game developer.",
    "sam": "Sam is the owner's friend who tests LOKI builds.",
    "github": "The owner's GitHub account is m03dev.",
    "dark": "The owner prefers dark mode everywhere.",
    "bonsai": "Bonsai 2 on the PC needs Ollama 0.40.6 or newer.",
    "phone": "The owner wants an iOS and Android app that chats with LOKI on the Mac or the PC.",
    "food": "The owner's favourite food is sushi.",
    "wprepo": "Waypoint's repository is private on GitHub at m03dev/waypoint.",
    "maya": "The owner uses Maya daily and Blender rarely.",
}
EPISODES = {
    "white": "Fixed the Mac's white window: boot.js now shows a rescue screen with the errors.",
    "qwen": "Lesson: local qwen3 models need /no_think or they spend the whole budget thinking.",
}
NOISE = ["Tomato plants on the balcony need water every two days.", "Coffee beans are kept in the blue tin.",
         "The neighbour's dog is called Biscuit.", "The gym closes at ten on Sundays.",
         "Recycling goes out on Tuesday mornings.", "The car's tyres were changed in spring.",
         "A good sourdough needs a twelve hour rise.", "The library card expires next year.",
         "Basil grows better on the kitchen window.", "The router sits behind the television.",
         "Chess openings: the Italian game starts with e4 e5 Nf3 Nc6 Bc4.", "The bike lock code is written in the hallway."]
IDS = {}
clock = [time.time() - 40 * 86400]


def tick_clock():
    clock[0] += 3600
    return clock[0]


for key, text in list(SEED.items()):
    IDS[key] = memory_core.learn(text, root=EV, clock=tick_clock)["id"]
for key, text in EPISODES.items():
    IDS[key] = memory_core.learn(text, tier="episodic", root=EV, clock=tick_clock)["id"]
for text in NOISE:
    memory_core.learn(text, root=EV, clock=tick_clock)
QUERIES = [("what's my name", "name"), ("how long should your answers be", "short"),
           ("should the interface show icons or words", "icons"), ("what GPU does the PC have", "gpu"),
           ("where does LOKI live on the mac", "macmini"), ("who is Mia", "mia"), ("who is my boss", "dana"),
           ("what is Waypoint", "waypoint"), ("which engine is the racing game built in", "godot"),
           ("how are the Mac and PC linked", "relay"), ("which editor does the owner use", "editor"),
           ("what look do the Play games have", "look"), ("can I use paid models", "costs"),
           ("how do I publish a change", "ship"), ("where should tasks for LOKI go", "tasks"),
           ("what port is the relay on", "port"), ("what languages do I speak", "lang"),
           ("which city do I live in", "city"), ("when is my birthday", "bday"), ("what is my job", "job"),
           ("who tests LOKI builds", "sam"), ("what's my github username", "github"),
           ("light or dark theme?", "dark"), ("which Ollama version does Bonsai need", "bonsai"),
           ("what happened with the white window on the Mac", "white"), ("how should I run qwen3 locally", "qwen"),
           ("phone app plans", "phone"), ("what food do I like", "food"), ("is the waypoint repo public", "wprepo"),
           ("do I use Maya or Blender more", "maya")]
hits, misses, worst = 0, [], 0
PROFILE = memory.profile_block(EV)
for q, want in QUERIES:
    pk = memory.pack(q, root=EV, lessons=False)
    used = [u["id"] for u in pk["used"]] + PROFILE["ids"]          # what the prompt carries
    worst = max(worst, pk["tokens"] + PROFILE["tokens"])
    if IDS[want] in used:
        hits += 1
    else:
        misses.append((q, want, [u["text"][:50] for u in pk["used"]]))
    if want == "editor" and IDS["editor_old"] in used:
        misses.append((q, "superseded VS Code was recalled", used))
print("  eval: %d/30 recalled; largest memory context %d tokens (profile %d + pack; budget %d)"
      % (hits, worst, PROFILE["tokens"], memory.PACK_TOKENS + memory.PROFILE_TOKENS))
check("eval: the right memory is in the prompt (profile or pack) for at least 28 of 30 questions", hits >= 28, misses)
check("eval: profile + pack stay under the token budget", worst <= memory.PACK_TOKENS + memory.PROFILE_TOKENS, worst)
only_pack = sum(1 for q, want in QUERIES if IDS[want] in [u["id"] for u in memory.pack(q, root=EV, lessons=False)["used"]])
print("  eval: %d/30 came through the per-request pack (cited in memories_used)" % only_pack)
search_only = [(q, want) for q, want in QUERIES
               if IDS[want] not in [i["id"] for i in memory_core.retrieve(q, root=EV, limit=5, mark_used=False)["items"]]]
print("  eval, search alone (no profile help, top 5): %d/30" % (30 - len(search_only)))
check("eval: search alone puts the right memory in its top 5 for at least 27 of 30", len(search_only) <= 3, search_only)
check("eval: unrelated questions recall nothing", all(not memory.pack(q, root=EV, lessons=False)["used"] for q in
                                                     ("quantum chromodynamics on a lattice", "translate bonjour", "integral of x squared")))
prof_eval = memory.profile_block(EV)
check("eval: the always-on profile stays under its budget", prof_eval["tokens"] <= memory.PROFILE_TOKENS, prof_eval["tokens"])

memory_search.EMBEDDER_OVERRIDE = fake_embed
try:
    hy_hits = sum(1 for q, want in QUERIES
                  if IDS[want] in [u["id"] for u in memory.pack(q, root=EV, lessons=False)["used"]] + PROFILE["ids"])
finally:
    memory_search.EMBEDDER_OVERRIDE = None
    memory_search._EMBED_STATE.update(model=None, t=0.0)
print("  eval with a (toy) local embedder: %d/30" % hy_hits)
check("eval: hybrid mode does not lose what BM25 finds", hy_hits >= hits - 1, (hy_hits, hits))

# =========================================================================== the window
section("Settings > Memory in a real (headless) browser, against the real memory API")


def chromium_path() -> str:
    for p in (os.getenv("LOKI_SUITE_CHROMIUM", ""), "/opt/pw-browsers/chromium"):
        if p and os.path.exists(p):
            return p
    return ""


try:
    from playwright.async_api import async_playwright  # type: ignore
except ImportError:
    async_playwright = None

if async_playwright is None or not chromium_path():
    print("  SKIP: no Playwright/Chromium here")
else:
    import asyncio
    from urllib.parse import parse_qs, urlparse

    UI = REPO / "app" / "ui"
    WIN = root("window")
    (WIN / "memory.md").write_text("- LOKI tasks go in LOKI_TASKS.md, never in the chat reply\n", encoding="utf-8")
    for text in ("The owner's editor is VS Code", "The owner's editor is Zed", "Dana is the owner's manager at the studio",
                 "The owner decided to build his racing game in Godot 4 for Steam"):
        memory_core.learn(text, root=WIN)
    memory_core.learn("Lesson: local qwen3 models need /no_think", tier="episodic", root=WIN)
    memory.after_request([{"role": "user", "content": "I prefer short answers. Mia is my sister. "
                                                      "I'm working on Waypoint, a Maya companion."}], root=WIN)
    wagent = types.SimpleNamespace(DATA_DIR=WIN, WORKSPACE=WS, MEMORY_FILE=WIN / "memory.md")
    knowledge.project_index(WS, WIN).refresh()
    shot = os.getenv("LOKI_SUITE_SHOT", "")

    async def window() -> list:
        errors: list = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chromium_path(),
                                              args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            page = await browser.new_page(viewport={"width": 1240, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
            page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))

            async def route(r):
                url = r.request.url.split("8899", 1)[1]
                path = url.split("?")[0].split("#")[0]
                if path == "/":
                    return await r.fulfill(path=str(UI / "index.html"))
                if path.startswith("/ui/"):
                    f = UI / path[4:]
                    return await (r.fulfill(path=str(f)) if f.is_file() else r.fulfill(json={"ok": True}))
                if path == "/memory/core":
                    if r.request.method == "POST":
                        code, body = loki_bridge.memory_core_api(types.SimpleNamespace(agent=wagent), "POST",
                                                                 json.loads(r.request.post_data or "{}"))
                    else:
                        code, body = loki_bridge.memory_core_api(types.SimpleNamespace(agent=wagent), "GET",
                                                                 parse_qs(urlparse(url).query))
                    return await r.fulfill(status=code, json=body)
                if path == "/memory":
                    return await r.fulfill(json={"ok": True, "memory": (WIN / "memory.md").read_text(encoding="utf-8")})
                if path == "/health":
                    return await r.fulfill(json={"ok": True, "service": "loki", "mode": "smart", "provider": "x", "model": "x",
                                                 "providers": "", "route": [], "usage": {}, "first_layer": {},
                                                 "update": {"commit": "abc", "label": "v0.16"}, "ui_errors": []})
                return await r.fulfill(json={"ok": True})

            await page.route("http://127.0.0.1:8899/**", route)
            await page.goto("http://127.0.0.1:8899/#token=t")
            try:
                await page.wait_for_function("window.LOKI_READY === true", timeout=20000)
            except Exception:  # noqa: BLE001
                errors.append("window never became ready")
            await page.click("#open-settings")
            await page.click(".tabs button[data-tab=memory]")
            await page.wait_for_selector(".mem-today .mem-row", timeout=8000)
            today = await page.inner_text(".mem-today")
            rows = await page.query_selector_all("#memory-core .rows .mem-row")
            if shot:
                await page.screenshot(path=shot, full_page=False)
            undo = await page.query_selector(".mem-today .mem-row button[aria-label^='Undo']")
            await undo.click()
            await page.wait_for_timeout(600)
            after = await page.inner_text(".mem-today")
            await page.fill("#memory-core form input", "who is my boss")
            await page.click("#memory-core form button")
            await page.wait_for_timeout(600)
            found = await page.inner_text("#memory-core")
            await browser.close()
        return [errors, today, len(rows), after, found]

    errors, today, nrows, after, found = asyncio.run(window())
    check("the Memory tab renders without a script error", not errors, errors[:5])
    check("it says what LOKI learned today, with Keep and Undo", "LOKI learned 3 things today" in today, today[:200])
    check("every memory is listed with its kind", nrows >= 6, nrows)
    check("Undo in the window forgets one", "LOKI learned 2 things today" in after, after[:200])
    check("search in the window shows what LOKI would recall (boss -> manager)", "Dana" in found, found[:300])
    if shot:
        print("  screenshot: " + shot)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
