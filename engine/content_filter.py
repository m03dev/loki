"""Keep only what matters: BM25 relevance, link-density pruning, link citations, document search.

Ported into LOKI (session 27 harvest) from Crawl4AI (github.com/unclecode/crawl4ai), Apache-2.0,
by UncleCode and the Crawl4AI contributors - see engine/licenses/Crawl4AI-Apache-2.0.txt:
  - BM25ContentFilter (content_filter_strategy.py): split a page into chunks, score them against
    the user's query with BM25 Okapi, weight headings/code higher (`priority_tags`), keep those
    above a threshold IN DOCUMENT ORDER, de-duplicated. rank_bm25's BM25Okapi (k1 1.5, b 0.75,
    epsilon 0.25) is re-written here; snowball stemming is replaced by a light suffix stemmer.
  - clean_tokens (utils.py): the noise and stop word lists.
  - PruningContentFilter's link-density idea: a chunk that is mostly link text is navigation.
  - convert_links_to_citations (markdown_generation_strategy.py): inline links become
    text⟨n⟩ with a numbered reference list at the end - fewer tokens, sources still traceable.

Why it matters for LOKI: a small local model given a whole 20k-character page loses the
question; given the 3k characters that answer it, it does not. `focus()` is what read_web uses
when the model passes a query; `search_files_bm25()` is a no-install RAG over the workspace.
Pure standard library.
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path

NOISE = {"ccp", "up", "↑", "▲", "⬆️", "a", "an", "at", "by", "in", "of", "on", "to", "the"}
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he", "in", "is", "it", "its", "of",
    "on", "that", "the", "to", "was", "were", "will", "with",
    "i", "you", "she", "we", "they", "me", "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "mine", "yours", "hers", "ours", "theirs", "myself", "yourself", "himself", "herself", "itself",
    "ourselves", "themselves",
    "am", "been", "being", "have", "had", "having", "do", "does", "did", "doing",
    "about", "above", "across", "after", "against", "along", "among", "around", "before", "behind", "below",
    "beneath", "beside", "between", "beyond", "down", "during", "except", "inside", "into", "near", "off",
    "out", "outside", "over", "past", "through", "toward", "under", "underneath", "until", "upon", "within",
    "but", "or", "nor", "yet", "so", "although", "because", "since", "unless",
    "this", "these", "those", "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such",
}
# crawl4ai BM25ContentFilter.priority_tags, mapped onto markdown chunk kinds
PRIORITY = {"h1": 5.0, "h2": 4.0, "h3": 3.0, "h4": 2.0, "title": 4.0, "quote": 2.0, "code": 2.0, "table": 1.5}
BM25_THRESHOLD = 1.0
LINK_PATTERN = re.compile(r'!?\[((?:[^\[\]]|\[(?:[^\[\]]|\[[^\]]*\])*\])*)\]\(((?:[^()\s]|\([^()]*\))*)(?:\s+"([^"]*)")?\)')
_WORD = re.compile(r"[A-Za-z0-9_À-￿]+")


# --------------------------------------------------------------------------- tokens
def stem(word: str) -> str:
    """A light English suffix stemmer (stand-in for snowball: 'running'/'runs' -> 'run')."""
    w = word
    if len(w) <= 3:
        return w
    for suffix, keep in (("ational", "ate"), ("ization", "ize"), ("fulness", "ful"), ("iveness", "ive"),
                         ("ically", "ic"), ("ments", "ment"), ("ingly", ""), ("edly", ""), ("sses", "ss"),
                         ("ies", "y"), ("shes", "sh"), ("ches", "ch"), ("xes", "x"), ("ing", ""), ("ed", ""),
                         ("ly", ""), ("ss", "ss"), ("us", "us"), ("is", "is"), ("s", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= (2 if suffix in ("ies", "xes", "ches", "shes", "sses") else 3):
            w = w[: len(w) - len(suffix)] + keep
            if suffix in ("ing", "ed") and len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
                w = w[:-1]          # running -> runn -> run
            break
    return w


def tokens(text: str) -> list:
    out = []
    for raw in _WORD.findall(str(text or "").lower()):
        if len(raw) < 2 or raw in NOISE or raw in STOP_WORDS:
            continue
        out.append(stem(raw))
    return out


# --------------------------------------------------------------------------- BM25 Okapi
class BM25:
    """rank_bm25.BM25Okapi, re-written (k1=1.5, b=0.75) with Lucene's positive idf; the epsilon
    floor for negative idf is kept for safety but no longer triggers."""

    def __init__(self, corpus: list, k1: float = 1.5, b: float = 0.75, epsilon: float = 0.25):
        self.k1, self.b, self.epsilon = k1, b, epsilon
        self.doc_len = [len(d) for d in corpus]
        self.n = len(corpus)
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        self.freqs = []
        df: dict = {}
        for doc in corpus:
            f: dict = {}
            for w in doc:
                f[w] = f.get(w, 0) + 1
            self.freqs.append(f)
            for w in f:
                df[w] = df.get(w, 0) + 1
        self.idf: dict = {}
        negatives, total = [], 0.0
        for w, freq in df.items():
            # Lucene's always-positive idf: rank_bm25's Okapi idf is 0 or negative for a word in half
            # the chunks, which on a small page (or a two-file folder) hides the only match there is.
            idf = math.log(1.0 + (self.n - freq + 0.5) / (freq + 0.5))
            self.idf[w] = idf
            total += idf
            if idf < 0:
                negatives.append(w)
        floor = self.epsilon * (total / len(self.idf)) if self.idf else 0.0
        for w in negatives:
            self.idf[w] = floor

    def scores(self, query: list) -> list:
        out = [0.0] * self.n
        for q in query:
            idf = self.idf.get(q)
            if idf is None:
                continue
            for i, f in enumerate(self.freqs):
                tf = f.get(q, 0)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
                out[i] += idf * tf * (self.k1 + 1) / denom
        return out


# --------------------------------------------------------------------------- markdown chunks
def chunks(markdown: str) -> list:
    """[(kind, text)] - headings, paragraphs, list blocks, code blocks, tables, quotes - in order."""
    out, buf, kind = [], [], "p"
    in_code = False

    def flush():
        nonlocal buf, kind
        text = "\n".join(buf).strip()
        if text:
            out.append((kind, text))
        buf, kind = [], "p"
    for line in str(markdown or "").split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                buf.append(line)
                in_code = False
                flush()
            else:
                flush()
                in_code, kind = True, "code"
                buf.append(line)
            continue
        if in_code:
            buf.append(line)
            continue
        m = re.match(r"^(#{1,6})\s+\S", line)
        if m:
            flush()
            out.append(("h%d" % min(len(m.group(1)), 4), line.strip()))
            continue
        if not line.strip():
            flush()
            continue
        this = "table" if line.lstrip().startswith("|") else "quote" if line.lstrip().startswith(">") else None
        if this and kind != this and buf:
            flush()
        if this:
            kind = this
        buf.append(line)
    if in_code:
        kind = "code"
    flush()
    return out


def link_density(text: str) -> float:
    """Share of a chunk's visible text that sits inside links (PruningContentFilter's metric)."""
    total = len(LINK_PATTERN.sub(lambda m: m.group(1), text)) or 1
    linked = sum(len(m.group(1)) for m in LINK_PATTERN.finditer(text))
    return linked / total


def focus(markdown: str, query: str, max_chars: int = 6000, threshold: float = BM25_THRESHOLD) -> str:
    """The chunks of `markdown` relevant to `query`, in document order (crawl4ai BM25ContentFilter).

    Each kept chunk brings the nearest heading above it, so the model still knows where it is.
    Returns "" when nothing scores - the caller falls back to the whole page."""
    parts = chunks(markdown)
    if not parts or not str(query or "").strip():
        return ""
    corpus = [tokens(t) for _k, t in parts]
    q = tokens(query)
    if not q or not any(corpus):
        return ""
    raw = BM25(corpus).scores(q)
    scored = []
    for i, ((kind, text), s) in enumerate(zip(parts, raw)):
        s *= PRIORITY.get(kind, 1.0)
        if kind == "p" and len(text) > 40 and link_density(text) > 0.7:
            s *= 0.2          # navigation / link lists
        scored.append((s, i))
    keep = sorted(i for s, i in scored if s >= threshold)
    if not keep:
        return ""
    # best first until the budget is used, then back to document order
    by_score = sorted(((s, i) for s, i in scored if i in set(keep)), reverse=True)
    chosen, used, seen = set(), 0, set()
    for _s, i in by_score:
        text = parts[i][1]
        if text in seen:
            continue
        if used + len(text) > max_chars and chosen:
            continue
        seen.add(text)
        chosen.add(i)
        used += len(text) + 2
        # the heading this chunk belongs to
        for j in range(i - 1, -1, -1):
            if parts[j][0].startswith("h"):
                if j not in chosen:
                    chosen.add(j)
                    used += len(parts[j][1]) + 2
                break
    out, last = [], -2
    for i in sorted(chosen):
        if out and i != last + 1:
            out.append("[...]")
        out.append(parts[i][1])
        last = i
    return "\n\n".join(out)


def citations(markdown: str, base_url: str = "") -> tuple:
    """crawl4ai convert_links_to_citations: (text with links as text⟨n⟩, "## References" list)."""
    import urllib.parse
    link_map: dict = {}
    parts, last = [], 0
    for m in LINK_PATTERN.finditer(markdown):
        parts.append(markdown[last:m.start()])
        text, url, title = m.groups()
        if base_url and not url.startswith(("http://", "https://", "mailto:")):
            url = urllib.parse.urljoin(base_url, url)
        if url not in link_map:
            desc = [d for d in (title, text if text != title else "") if d]
            link_map[url] = (len(link_map) + 1, (": " + " - ".join(desc)) if desc else "")
        num = link_map[url][0]
        parts.append("%s⟨%d⟩" % (text, num) if not m.group(0).startswith("!") else "![%s⟨%d⟩]" % (text, num))
        last = m.end()
    parts.append(markdown[last:])
    refs = "".join("⟨%d⟩ %s%s\n" % (num, url, desc) for url, (num, desc) in link_map.items())
    return "".join(parts), ("\n\n## References\n\n" + refs) if refs else ""


# --------------------------------------------------------------------------- workspace RAG
TEXT_SUFFIXES = {".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".html", ".htm",
                 ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".gd", ".go", ".rs", ".java", ".cs",
                 ".c", ".h", ".cpp", ".sh", ".bat", ".ps1", ".sql", ".log", ".tex", ".org", ".pdf"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".godot", "harness_data"}
MAX_FILES = 2000
MAX_FILE_BYTES = 2_000_000


def _pdf_text(path: Path) -> str:
    """Text of a PDF when pypdf is installed (optional), else ""."""
    try:
        import pypdf  # type: ignore
    except ImportError:
        return ""
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages[:200])
    except Exception:  # noqa: BLE001
        return ""


def _file_chunks(path: Path, size: int = 900) -> list:
    """[(start_line, text)] windows of a text file, split on blank lines near `size` chars."""
    if path.suffix.lower() == ".pdf":
        text = _pdf_text(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    out, buf, start, used = [], [], 1, 0
    for n, line in enumerate(text.split("\n"), 1):
        if not buf:
            start = n
        buf.append(line)
        used += len(line) + 1
        if used >= size and (not line.strip() or used >= size * 2):
            out.append((start, "\n".join(buf).strip()))
            buf, used = [], 0
    if buf and "\n".join(buf).strip():
        out.append((start, "\n".join(buf).strip()))
    return out


def search_files_bm25(root: Path, query: str, top: int = 6, max_chars: int = 7000) -> str:
    """The passages under `root` that best answer `query` (BM25 over ~900-char chunks)."""
    root = Path(root)
    q = tokens(query)
    if not q:
        return "error: give a query with some real words in it"
    docs, where = [], []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                pieces = _file_chunks(p)
            except OSError:
                continue
            count += 1
            for line, text in pieces:
                docs.append(tokens(text))
                where.append((p.relative_to(root).as_posix(), line, text))
            if count >= MAX_FILES:
                break
    if not docs:
        return "no readable documents under %s" % (root.name or root)
    scores = BM25(docs).scores(q)
    ranked = sorted(((s, i) for i, s in enumerate(scores) if s > 0), reverse=True)[:max(1, int(top))]
    if not ranked:
        return 'nothing under %s matches "%s" (try other words)' % (root.name or root, query)
    out, used = [], 0
    for s, i in ranked:
        rel, line, text = where[i]
        piece = "[%d] %s (from line %d, score %.1f)\n%s" % (len(out) + 1, rel, line, s, text[:1500])
        if used + len(piece) > max_chars and out:
            break
        out.append(piece)
        used += len(piece)
    return ("%d passage(s) for \"%s\" (BM25 over %d files):\n\n" % (len(out), query, count)) + "\n\n".join(out)
