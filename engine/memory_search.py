"""How LOKI finds the memories that matter: hybrid search with a token budget.

    score = relevance x recency(kind) x importance x usefulness

relevance is HYBRID when a local embedding model is there and plain BM25 when it is not:

  * BM25 (Okapi, k1=1.2, b=0.75) over the item text + tags, words lightly stemmed, with a small
    synonym table for LOKI's own world ("pc" also finds "windows", "mac" finds "macos"...).
  * Embeddings from a small LOCAL model, never a paid one: Ollama's /api/embed with an embedding
    model that is already installed (nomic-embed-text, all-minilm, mxbai-embed-large, bge-*,
    embeddinggemma, ...). LOKI_EMBED=auto (default) uses one if Ollama has it, LOKI_EMBED=off
    turns it off, LOKI_EMBED=<model> picks one. Nothing is ever downloaded for this. Vectors are
    cached on disk by text hash (memory_vectors.json), and at most EMBED_PER_CALL new texts are
    embedded per search, so a request never waits on a big backlog. Any failure -> BM25 only.

An item is a candidate only with real lexical evidence (enough of the query's rare words) or, with
embeddings, a high cosine similarity - so the pack stays empty rather than filled with noise.
Results are de-duplicated (near-identical texts collapse into the best one) and cut to a token
budget (tokens ~ chars / 4) as whole entries.

Recency depends on the kind: who the owner is, his preferences, people, projects and decisions do
not fade; facts fade slowly (half-life 180 days); episodes and lessons fade in 30 days.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

HALF_LIFE = {"fact": 180 * 86400, "episode": 30 * 86400, "lesson": 45 * 86400, "skill": 90 * 86400}
TIER_WEIGHT = {"semantic": 1.0, "episodic": 0.9, "procedural": 1.05, "working": 0.8}
EMBED_PER_CALL = 64
EMBED_TIMEOUT_S = 3.0
EMBED_MODELS = ("nomic-embed-text", "all-minilm", "mxbai-embed-large", "bge-m3", "bge-small", "bge-large",
                "snowflake-arctic-embed", "embeddinggemma", "granite-embedding", "qwen3-embedding", "paraphrase-multilingual")
STOP = set("""a an and are as at be but by can do for from has have how i in into is it its let
make me my of on or our please so that the their them then there this to up use using want was
we what when where which will with you your loki can could should would just also new add get
not no yes did does done about tell know remember any some again what's whats who whom whose""".split())

# A small synonym table for the owner's world; a query word also looks for these (at half weight).
SYNONYMS = {
    "pc": ["windows", "desktop", "tower"], "windows": ["pc"], "mac": ["macos", "mini", "macbook"],
    "macos": ["mac"], "gpu": ["rtx", "nvidia", "cuda", "graphics"], "rtx": ["gpu"], "graphics": ["gpu"],
    "editor": ["ide", "vscode", "zed", "vim"], "ide": ["editor"], "email": ["mail", "address"],
    "wife": ["partner", "spouse"], "partner": ["wife", "husband"], "husband": ["partner", "spouse"],
    "boss": ["manager"], "manager": ["boss"], "theme": ["dark", "light", "mode"], "colour": ["color"],
    "color": ["colour"], "reply": ["answer", "response"], "answer": ["reply"], "short": ["brief", "concise"],
    "brief": ["short", "concise"], "concise": ["short", "brief"], "game": ["godot", "mmo"],
    "model": ["llm", "ollama"], "llm": ["model"], "local": ["offline", "ollama"], "offline": ["local"],
    "phone": ["mobile", "ios", "android"], "mobile": ["phone"], "link": ["relay", "peer"],
    "relay": ["link", "peer"], "machine": ["computer", "pc", "mac"], "computer": ["machine", "pc", "mac"],
    "language": ["python", "javascript", "typescript"], "live": ["based", "city"], "city": ["live", "based"],
    "birthday": ["born"], "born": ["birthday"], "job": ["work", "role"], "work": ["job"],
    "decided": ["decision", "chose", "chosen"], "decision": ["decided", "chose"], "chose": ["decided", "choice"],
    "test": ["tests", "suite", "check"], "suite": ["test"], "ship": ["push", "publish", "release"],
    "engine": ["godot", "unity", "unreal"], "built": ["build"], "build": ["built"], "repo": ["repository", "github"],
    "repository": ["repo"], "public": ["private", "visibility"], "private": ["public"], "username": ["account"],
    "account": ["username"], "food": ["eat", "dish"],
    "push": ["ship"], "publish": ["ship"], "vault": ["obsidian", "notes"], "obsidian": ["vault"],
}
_EMBED_STATE: dict = {"model": None, "t": 0.0, "error": "", "lock": threading.Lock()}
EMBEDDER_OVERRIDE = None        # tests: fn(list[str]) -> list[list[float]]


# --------------------------------------------------------------------------- words

def stem(word: str) -> str:
    """A light stemmer: change/changes/changed/changing -> chang, ship/ships/shipped -> ship,
    local/locally -> local, story/stories -> story."""
    for suffix in ("ingly", "ing", "ies", "edly", "ed", "ly", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix) and not word.endswith("ss"):
            if suffix == "es" and word[-3] not in "sxzh":
                suffix = "s"            # changes -> change (not chang-es), boxes -> box
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]                # shipp -> ship
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]                # change -> chang, like changed/changing
    return word


def words(text: str) -> list:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9_.+-]{1,}|\d", str(text).lower()):
        w = w.strip(".-+")
        if not w or w in STOP or (len(w) <= 1 and not w.isdigit()):
            continue
        out.append(w if any(c in w for c in "._+") or w.isdigit() else stem(w))
    return out


def numbers(text: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)*", str(text)))


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a or b) else 1.0


def near_duplicate(a: str, b: str, threshold: float = 0.9) -> bool:
    """Two texts that say the same thing (same words, same numbers)."""
    if " ".join(str(a).lower().split()) == " ".join(str(b).lower().split()):
        return True
    return numbers(a) == numbers(b) and jaccard(words(a), words(b)) >= threshold


def tokens_of(text: str) -> int:
    """About how many model tokens a text costs (4 characters a token, the usual rule)."""
    return (len(str(text)) + 3) // 4


# --------------------------------------------------------------------------- BM25

class BM25:
    def __init__(self, docs: list, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [list(d) for d in docs]
        self.n = len(self.docs)
        self.avgdl = (sum(len(d) for d in self.docs) / self.n) if self.n else 0.0
        self.tf = []
        self.df: dict = {}
        for d in self.docs:
            f: dict = {}
            for w in d:
                f[w] = f.get(w, 0) + 1
            self.tf.append(f)
            for w in f:
                self.df[w] = self.df.get(w, 0) + 1

    def idf(self, w: str) -> float:
        df = self.df.get(w, 0)
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, i: int, query: dict) -> float:
        """query: {word: weight}."""
        f, dl, total = self.tf[i], len(self.docs[i]) or 1, 0.0
        for w, weight in query.items():
            tf = f.get(w, 0)
            if not tf:
                continue
            total += weight * self.idf(w) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
        return total


def expand(query: str) -> dict:
    """{word: weight} - the query's own words at 1.0, their synonyms at 0.5."""
    if not _STEMMED:
        for key, alts in SYNONYMS.items():
            _STEMMED.setdefault(stem(key), set()).update(stem(a) for a in alts)
    out: dict = {}
    for w in words(query):
        out[w] = 1.0
    for w in list(out):
        for s in sorted(_STEMMED.get(w, ())):
            out.setdefault(s, 0.5)
    return out


_STEMMED: dict = {}


def coverage(bm: BM25, i: int, query: dict) -> tuple:
    """(share of the query's rarity this document matches, matched own words)."""
    own = [w for w, wt in query.items() if wt >= 1.0]
    if not own:
        return 0.0, 0
    unknown = math.log(1.0 + (bm.n + 0.5) / 0.5)
    total = sum(bm.idf(w) if w in bm.df else unknown for w in own)
    f = bm.tf[i]
    got = [w for w in own if w in f]
    syn = [w for w, wt in query.items() if wt < 1.0 and w in f]
    matched = sum(bm.idf(w) for w in got) + 0.5 * sum(bm.idf(w) for w in syn)
    return (matched / total if total else 0.0), len(got) + (1 if syn else 0)


# --------------------------------------------------------------------------- embeddings

def _ollama_base() -> str:
    host = os.getenv("OLLAMA_HOST", "").strip() or "127.0.0.1:11434"
    if host.startswith("0.0.0.0"):
        host = "127.0.0.1" + host[len("0.0.0.0"):]
    return host if host.startswith("http") else "http://" + host


def embed_model() -> str:
    """The local embedding model to use, or "" (BM25 only). Probed at most every 5 minutes."""
    if EMBEDDER_OVERRIDE is not None:
        return "test-embedder"
    choice = os.getenv("LOKI_EMBED", "auto").strip()
    if choice.lower() in ("off", "0", "no", "false", ""):
        return ""
    state = _EMBED_STATE
    if state["model"] is not None and time.time() - state["t"] < 300:
        return state["model"]
    model = ""
    try:
        with urllib.request.urlopen(_ollama_base() + "/api/tags", timeout=0.6) as resp:
            names = [m.get("name", "") for m in json.loads(resp.read().decode("utf-8")).get("models", [])]
        if choice.lower() != "auto":
            model = next((n for n in names if n == choice or n.split(":")[0] == choice.split(":")[0]), "")
        else:
            model = next((n for want in EMBED_MODELS for n in names if n.split(":")[0].startswith(want)), "")
        state["error"] = "" if model else "no embedding model installed in Ollama"
    except Exception as exc:  # noqa: BLE001
        state["error"] = "Ollama not reachable (%s)" % type(exc).__name__
    state.update(model=model, t=time.time())
    return model


def _embed_remote(model: str, texts: list) -> list:
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(_ollama_base() + "/api/embed", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT_S) as resp:
        vecs = json.loads(resp.read().decode("utf-8")).get("embeddings") or []
    if len(vecs) != len(texts):
        raise ValueError("embedding count mismatch")
    return vecs


def _norm(vec: list) -> list:
    length = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [round(x / length, 5) for x in vec]


class VectorCache:
    def __init__(self, root: Path) -> None:
        self.path = Path(root) / "memory_vectors.json"
        self.data: dict = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            pass
        self.dirty = False

    def get(self, model: str, key: str):
        return (self.data.get(model) or {}).get(key)

    def put(self, model: str, key: str, vec: list) -> None:
        self.data.setdefault(model, {})[key] = vec
        self.dirty = True

    def save(self, keep: set | None = None) -> None:
        if not self.dirty:
            return
        if keep is not None:
            for model in self.data:
                self.data[model] = {k: v for k, v in self.data[model].items() if k in keep}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass


def text_key(text: str) -> str:
    return hashlib.sha1(str(text).encode("utf-8", "replace")).hexdigest()[:16]


def embed(texts: list, root: Path, budget: int = EMBED_PER_CALL) -> tuple:
    """(model, [vector | None]) for texts - cached ones free, at most `budget` new ones."""
    model = embed_model()
    if not model:
        return "", [None] * len(texts)
    cache = VectorCache(root)
    out, missing = [], []
    for i, text in enumerate(texts):
        vec = cache.get(model, text_key(text))
        out.append(vec)
        if vec is None and len(missing) < budget:
            missing.append(i)
    if missing:
        try:
            batch = [texts[i][:2000] for i in missing]
            vecs = EMBEDDER_OVERRIDE(batch) if EMBEDDER_OVERRIDE is not None else _embed_remote(model, batch)
            for i, vec in zip(missing, vecs):
                vec = _norm([float(x) for x in vec])
                out[i] = vec
                cache.put(model, text_key(texts[i]), vec)
            cache.save()
        except Exception as exc:  # noqa: BLE001 - embeddings are a bonus; BM25 still answers
            _EMBED_STATE.update(model="", t=time.time(), error="embedding failed (%s)" % type(exc).__name__)
            return "", [None] * len(texts)
    return model, out


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def status() -> dict:
    model = embed_model()
    if model:
        note = ""
    elif EMBEDDER_OVERRIDE is None and os.getenv("LOKI_EMBED", "auto").strip().lower() in ("off", "0", "no", "false", ""):
        note = "turned off (LOKI_EMBED=off)"
    else:
        note = _EMBED_STATE.get("error", "")
    return {"mode": "hybrid" if model else "bm25", "model": model, "note": note}


# --------------------------------------------------------------------------- ranking

_WORDS_CACHE: dict = {}


def _cached_words(text: str) -> list:
    """words() of a memory, remembered between requests (thousands of memories stay cheap)."""
    got = _WORDS_CACHE.get(text)
    if got is None:
        if len(_WORDS_CACHE) > 20000:
            _WORDS_CACHE.clear()
        got = _WORDS_CACHE[text] = words(text)
    return got


def recency(item: dict, now: float) -> float:
    life = HALF_LIFE.get(item.get("kind", "fact"))
    if not life:
        return 1.0
    age = max(0.0, now - float(item.get("updated") or item.get("t") or now))
    return 0.5 + 0.5 * (0.5 ** (age / life))


def rank(query: str, pool: list, root: Path | None = None, now: float | None = None,
         use_embeddings: bool = True) -> list:
    """[(score, item, detail)] best first. Items without real evidence are left out."""
    q = expand(query)
    if not pool or not q:
        return []
    now = time.time() if now is None else now
    docs = [_cached_words(i.get("text", "") + " " + " ".join(i.get("tags") or [])) for i in pool]
    bm = BM25(docs)
    raw = [bm.score(i, q) for i in range(len(pool))]
    top = max(raw) if raw else 0.0
    vecs, qvec = [None] * len(pool), None
    if use_embeddings and root is not None:
        model, got = embed([query] + [i.get("text", "") for i in pool], Path(root))
        if model:
            qvec, vecs = got[0], got[1:]
    own = len([w for w, wt in q.items() if wt >= 1.0])
    out = []
    for idx, item in enumerate(pool):
        cov, hits = coverage(bm, idx, q)
        lexical = raw[idx] > 0 and (cov >= 0.34 or hits >= 2 or (own <= 2 and cov >= 0.2))
        cos = cosine(qvec, vecs[idx]) if qvec is not None else 0.0
        semantic = qvec is not None and cos >= 0.6
        if not (lexical or semantic):
            continue
        rel = (raw[idx] / top if top else 0.0) * (0.6 + 0.4 * cov)
        if qvec is not None:
            rel = 0.55 * rel + 0.45 * max(0.0, (cos - 0.3) / 0.7)
        importance = float(item.get("importance", 0.5) or 0.5)
        useful = 1.0 + 0.05 * min(int(item.get("uses", 0) or 0), 10)
        s = rel * recency(item, now) * (0.75 + 0.5 * importance) * useful * TIER_WEIGHT.get(item.get("tier", "semantic"), 1.0)
        out.append((s, item, {"bm25": round(raw[idx], 3), "coverage": round(cov, 2), "cosine": round(cos, 3)}))
    out.sort(key=lambda s: (-s[0], -float(s[1].get("t", 0) or 0)))
    return out


def dedupe(ranked: list, keep: int = 200) -> list:
    """Near-identical texts collapse into the best-ranked one. Stops after `keep` results (a search
    never needs more), so a broad query over thousands of memories stays fast."""
    kept: list = []
    for entry in ranked:
        text = entry[1].get("text", "")
        if any(near_duplicate(text, k[1].get("text", ""), 0.8) for k in kept):
            continue
        kept.append(entry)
        if len(kept) >= keep:
            break
    return kept


def fit(entries: list, budget_tokens: int) -> tuple:
    """(kept entries, tokens used, left out) - whole entries in rank order within the budget."""
    kept, used = [], 0
    for entry in entries:
        cost = tokens_of(entry[0]) + 1
        if used + cost > budget_tokens:
            continue
        kept.append(entry)
        used += cost
    return kept, used, len(entries) - len(kept)
