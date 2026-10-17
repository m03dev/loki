"""Loki's local context store, addressed with viking:// URIs.

OpenViking (volcengine/OpenViking) organises an agent's context as a filesystem behind
`viking://` URIs. Loki adopts the same addressing over plain local folders, so the memory
layer has one shape now and an OpenViking server can be dropped in later behind the same
`MemoryProvider` protocol (interfaces.py) without touching callers:

    viking://memory/...      harness_data/memory/      (lasting facts, notes)
    viking://skills/...      <repo>/skills/ + vendored skill libraries (read-only)
    viking://project/...     <workspace>/docs/         (the project's own docs, read-only)
    viking://state/...       harness_data/state/       (resumable task state)

Every URI is resolved inside its root; anything that escapes is refused. Writes are only
allowed under memory/ and state/. Standard library only.

Graphiti (a temporal knowledge graph) is deliberately not wired in: add it behind the same
protocol only when Loki needs "what was true before decision X" questions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

SCHEME = "viking://"
WRITABLE = {"memory", "state"}
MAX_READ = 200_000


class KnowledgeError(ValueError):
    pass


class LocalViking:
    """MemoryProvider over local folders."""

    name = "local-viking"

    def __init__(self, roots: dict[str, list[Path]]) -> None:
        self.roots = {k: [Path(p) for p in v] for k, v in roots.items()}

    def _parse(self, uri: str) -> tuple[str, str]:
        uri = str(uri or "").strip()
        if not uri.startswith(SCHEME):
            raise KnowledgeError("not a viking:// URI: %r" % uri)
        rest = uri[len(SCHEME):].strip("/")
        space, _, path = rest.partition("/")
        if space not in self.roots:
            raise KnowledgeError("unknown namespace %r (have %s)" % (space, ", ".join(sorted(self.roots))))
        return space, path

    def _resolve(self, space: str, path: str, must_exist: bool) -> Path:
        for root in self.roots[space]:
            root = root.resolve()
            target = (root / path).resolve() if path else root
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise KnowledgeError("%r escapes viking://%s" % (path, space)) from exc
            if not must_exist or target.exists():
                return target
        if must_exist:
            raise KnowledgeError("not found: viking://%s/%s" % (space, path))
        return (self.roots[space][0].resolve() / path).resolve()

    def read(self, uri: str) -> str:
        space, path = self._parse(uri)
        target = self._resolve(space, path, must_exist=True)
        if target.is_dir():
            return "\n".join(self.list(uri))
        return target.read_text(encoding="utf-8", errors="replace")[:MAX_READ]

    def write(self, uri: str, text: str) -> None:
        space, path = self._parse(uri)
        if space not in WRITABLE:
            raise KnowledgeError("viking://%s is read-only" % space)
        if not path:
            raise KnowledgeError("a file path is required")
        target = self._resolve(space, path, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(str(text), encoding="utf-8")
        os.replace(tmp, target)

    def list(self, uri: str) -> list[str]:
        space, path = self._parse(uri)
        seen: dict[str, None] = {}
        for root in self.roots[space]:
            root = root.resolve()
            folder = (root / path).resolve() if path else root
            try:
                folder.relative_to(root)
            except ValueError:
                raise KnowledgeError("%r escapes viking://%s" % (path, space)) from None
            if folder.is_dir():
                for child in sorted(folder.iterdir()):
                    if child.name.startswith("."):
                        continue
                    rel = child.relative_to(root).as_posix() + ("/" if child.is_dir() else "")
                    seen[SCHEME + space + "/" + rel] = None
        return list(seen)


def default_store(repo: Path, data_dir: Path, workspace: Path) -> LocalViking:
    data_dir = Path(data_dir)
    return LocalViking({
        "memory": [data_dir / "memory"],
        "state": [data_dir / "state"],
        "skills": [Path(repo) / "skills", data_dir / "vendor"],
        "project": [Path(workspace) / "docs"],
    })


# --------------------------------------------------------------------------- project knowledge
# Session 28: the workspace project's docs and code, indexed INCREMENTALLY so LOKI can answer
# from them and cite where it read it (path:line). The index lives in
# harness_data/knowledge/<workspace-hash>.json (local to this machine: each machine indexes its own
# checkout). refresh() only re-reads files whose size or modification time changed, drops files
# that are gone, and stops after a time budget (it continues next time), so it can run before
# requests in the background. The Obsidian vault stays separate (brain.py, read-only).

INDEX_SUFFIXES = {".md", ".txt", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".yaml", ".yml",
                  ".toml", ".ini", ".cfg", ".gd", ".go", ".rs", ".java", ".cs", ".c", ".h", ".cpp", ".hpp",
                  ".sh", ".bat", ".ps1", ".sql", ".tex", ".org", ".json", ".swift", ".kt", ".rb", ".php", ".lua"}
INDEX_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", ".godot",
                   "harness_data", ".claude", ".idea", ".vscode", ".next", "target", "vendor", "Library",
                   ".import", "exports", "export", "out", "coverage", ".pytest_cache", ".mypy_cache"}
SECRET_FILES = re.compile(r"(^\.env|secret|credential|password|\.pem$|\.key$|id_rsa|id_ed25519|token)", re.I)
MAX_INDEX_FILES = 3000
MAX_INDEX_BYTES = 400_000
# Session 29: documents are a SOURCE of this same index (not a second index): PDFs, Word, Excel,
# PowerPoint, e-books, emails and CSVs are converted to Markdown by doc_read (cached by size + mtime in
# harness_data/documents/cache/) and chunked per page / slide / sheet / section, so a hit cites
# `report.pdf#p3` instead of path:line. Bigger files are allowed than for text.
DOC_INDEX_SUFFIXES = {".pdf", ".docx", ".xlsx", ".pptx", ".epub", ".eml", ".csv", ".tsv", ".odt", ".doc", ".rtf"}
MAX_DOC_BYTES = int(os.getenv("LOKI_DOC_INDEX_MAX_BYTES", str(60 * 1024 * 1024)))
MAX_INDEX_CHUNKS = 20_000
CHUNK_CHARS = 900
_INDEX_CACHE: dict = {}
_INDEX_LOCK = threading.Lock()


def _doc_chunks(path: Path, data_dir: Path | None, ocr: bool = False) -> list:
    """[(n, text, anchor)] for a document (doc_read), through the conversion cache."""
    import doc_read  # pylint: disable=import-outside-toplevel
    opts = {"ocr": "auto" if ocr else "off"}
    if data_dir is not None:
        doc = doc_read.convert_cached(path, Path(data_dir) / "documents" / "cache", **opts)
    else:
        doc = doc_read.convert(path, **opts)
    if not doc.get("ok"):
        return []
    return [(n, t[:CHUNK_CHARS * 2], a) for n, t, a in doc_read.chunks(doc, CHUNK_CHARS)]


def _chunks(path: Path) -> list:
    """[(start_line, text)] - Markdown split at headings, code and text in ~900-char windows."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".html":
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    out, buf, start, used = [], [], 1, 0
    heading = path.suffix.lower() == ".md"
    for n, line in enumerate(text.split("\n"), 1):
        if heading and line.startswith("#") and buf and used > 20:
            out.append((start, "\n".join(buf).strip()))
            buf, used = [], 0
        if not buf:
            start = n
        buf.append(line)
        used += len(line) + 1
        if used >= CHUNK_CHARS and (not line.strip() or used >= CHUNK_CHARS * 2):
            out.append((start, "\n".join(buf).strip()))
            buf, used = [], 0
    if buf and "\n".join(buf).strip():
        out.append((start, "\n".join(buf).strip()))
    return [(s, t[:CHUNK_CHARS * 2]) for s, t in out if t.strip()]


class ProjectIndex:
    """An incremental BM25 index of one workspace's docs and code - and, since session 29, its documents
    (documents=True, the default) - or of one document collection folder (the same class, see below)."""

    def __init__(self, workspace: Path, data_dir: Path, documents: bool = True, ocr: bool = False) -> None:
        self.root = Path(workspace).expanduser().resolve()
        key = hashlib.sha1(str(self.root).encode("utf-8", "replace")).hexdigest()[:12]
        self.path = Path(data_dir) / "knowledge" / ("%s.json" % key)
        self.data_dir = Path(data_dir)
        self.documents = bool(documents) and os.getenv("LOKI_DOC_INDEX", "on").strip().lower() not in ("0", "off", "no")
        self.ocr = bool(ocr)
        self.busy = False

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("workspace") == str(self.root):
                return data
        except (OSError, ValueError):
            pass
        return {"workspace": str(self.root), "files": {}, "t": 0, "complete": False}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        _INDEX_CACHE.pop(str(self.path), None)

    def _walk(self):
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in INDEX_SKIP_DIRS and not d.startswith("."))
            for name in sorted(filenames):
                p = Path(dirpath) / name
                suffix = p.suffix.lower()
                if (suffix not in INDEX_SUFFIXES and not (self.documents and suffix in DOC_INDEX_SUFFIXES)) \
                        or SECRET_FILES.search(name) or name.startswith(("~$", ".~lock")):
                    continue
                yield p
                count += 1
                if count >= MAX_INDEX_FILES:
                    return

    def refresh(self, budget_s: float = 3.0, clock=time.monotonic) -> dict:
        """Re-read what changed since last time. Returns counts; `complete` False = budget ran out
        (the next refresh continues where this one stopped)."""
        if not self.root.is_dir():
            return {"ok": False, "error": "no such folder: %s" % self.root}
        try:
            import memory_core  # pylint: disable=import-outside-toplevel
            scrub = memory_core.scrub
        except Exception:  # noqa: BLE001
            def scrub(text):
                return text
        started = clock()
        data = self.load()
        files = data.get("files") or {}
        was_complete = bool(data.get("complete"))
        seen, added, changed, complete = set(), 0, 0, True
        total_chunks = sum(len(f.get("chunks") or []) for f in files.values())
        for p in self._walk():
            rel = p.relative_to(self.root).as_posix()
            seen.add(rel)
            try:
                st = p.stat()
            except OSError:
                continue
            is_doc = p.suffix.lower() in DOC_INDEX_SUFFIXES
            if st.st_size > (MAX_DOC_BYTES if is_doc else MAX_INDEX_BYTES):
                continue
            old = files.get(rel)
            if old and old.get("mtime") == st.st_mtime_ns and old.get("size") == st.st_size:
                continue
            if clock() - started > budget_s or total_chunks >= MAX_INDEX_CHUNKS:
                complete = False
                continue
            try:
                if is_doc:
                    pieces = [[n, scrub(t), a] for n, t, a in _doc_chunks(p, self.data_dir, self.ocr)]
                else:
                    pieces = [[s, scrub(t)] for s, t in _chunks(p)]
            except OSError:
                continue
            except Exception:  # noqa: BLE001 - one unreadable document never stops the index
                pieces = []
            total_chunks += len(pieces) - len((old or {}).get("chunks") or [])
            files[rel] = {"mtime": st.st_mtime_ns, "size": st.st_size, "chunks": pieces}
            if old:
                changed += 1
            else:
                added += 1
        removed = 0
        for rel in list(files):
            if rel not in seen:
                files.pop(rel)
                removed += 1
        data.update(files=files, t=time.time(), complete=complete)
        if added or changed or removed or not self.path.is_file() or complete != was_complete:
            self._save(data)
        return {"ok": True, "added": added, "changed": changed, "removed": removed, "files": len(files),
                "chunks": sum(len(f.get("chunks") or []) for f in files.values()), "complete": complete}

    def ensure_fresh(self, max_age_s: float = 120.0, background: bool = True) -> None:
        """Refresh when the index is older than max_age_s - in a background thread by default, so a
        request never waits on a walk of a big project."""
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            age = float("inf")
        if self.busy or age < max_age_s:
            return

        def run() -> None:
            with _INDEX_LOCK:
                self.busy = True
                try:
                    self.refresh()
                    os.utime(self.path) if self.path.is_file() else None
                except Exception:  # noqa: BLE001 - the index is a bonus; it must never break a request
                    pass
                finally:
                    self.busy = False
        if background:
            threading.Thread(target=run, daemon=True, name="loki-knowledge-index").start()
        else:
            run()

    def _bm25(self):
        import memory_search  # pylint: disable=import-outside-toplevel
        data = self.load()
        stamp = (data.get("t"), len(data.get("files") or {}))
        cached = _INDEX_CACHE.get(str(self.path))
        if cached and cached[0] == stamp:
            return cached[1], cached[2]
        where, docs = [], []
        for rel, info in sorted((data.get("files") or {}).items()):
            for chunk in info.get("chunks") or []:
                line, text = chunk[0], chunk[1]
                anchor = chunk[2] if len(chunk) > 2 else ""
                where.append((rel, int(line), text, anchor))
                docs.append(memory_search.words(rel.replace("/", " ").replace("_", " ") + " " + text))
        bm = memory_search.BM25(docs) if docs else None
        _INDEX_CACHE[str(self.path)] = (stamp, bm, where)
        return bm, where

    def search(self, query: str, top: int = 4) -> list:
        """[{path, line, text, score, cite}] best first (BM25), only passages with real evidence."""
        import memory_search  # pylint: disable=import-outside-toplevel
        bm, where = self._bm25()
        q = memory_search.expand(query)
        if not bm or not where or not q:
            return []
        own = len([w for w, wt in q.items() if wt >= 1.0])
        scored = []
        for i in range(len(where)):
            s = bm.score(i, q)
            if s <= 0:
                continue
            cov, hits = memory_search.coverage(bm, i, q)
            if cov >= 0.4 or hits >= 3 or (own <= 2 and cov >= 0.3):
                scored.append((s * (0.6 + 0.4 * cov), i))
        scored.sort(reverse=True)
        out = []
        for s, i in scored[:max(1, int(top))]:
            rel, line, text, anchor = where[i]
            hit = {"path": rel, "line": line, "text": text, "score": round(s, 3),
                   "cite": ("%s#%s" % (rel, anchor)) if anchor else "%s:%d" % (rel, line)}
            if anchor:
                hit["anchor"] = anchor
                m = re.match(r"^(?:p|slide-|ch-)(\d+)$", anchor)
                if m:
                    hit["page"] = int(m.group(1))
            out.append(hit)
        return out

    def status(self) -> dict:
        data = self.load()
        files = data.get("files") or {}
        return {"workspace": str(self.root), "files": len(files),
                "documents": sum(1 for f in files if Path(f).suffix.lower() in DOC_INDEX_SUFFIXES),
                "chunks": sum(len(f.get("chunks") or []) for f in files.values()),
                "t": data.get("t", 0), "complete": bool(data.get("complete")), "indexing": self.busy}


_INDEXES: dict = {}


def project_index(workspace: Path, data_dir: Path) -> ProjectIndex:
    """One ProjectIndex per (workspace, data folder) per process."""
    key = (str(Path(workspace).expanduser().resolve()), str(data_dir))
    if key not in _INDEXES:
        _INDEXES[key] = ProjectIndex(Path(workspace), Path(data_dir))
    return _INDEXES[key]


# --------------------------------------------------------------------------- document collections
# Session 29: "chat with your documents". A collection is a FOLDER the owner adds (Files view or the
# `documents` tool); each is indexed by the same ProjectIndex (documents on, OCR when the collection asks for
# it) and searched with the same BM25; memory.pack() adds the best passages with their citations
# (Contracts/lease.pdf#p3). The list is harness_data/documents/collections.json.

def collections_file(data_dir: Path) -> Path:
    return Path(data_dir) / "documents" / "collections.json"


def list_collections(data_dir: Path) -> list:
    try:
        data = json.loads(collections_file(data_dir).read_text(encoding="utf-8"))
        return [c for c in data if isinstance(c, dict) and c.get("folder")] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_collections(data_dir: Path, items: list) -> None:
    path = collections_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def add_collection(data_dir: Path, folder: Path, name: str = "", ocr: bool = False) -> dict:
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        return {"ok": False, "error": "no such folder: %s" % folder}
    home = Path.home().resolve()
    if folder in (Path(folder.anchor), home):
        return {"ok": False, "error": "pick a folder of documents, not the whole disk or home folder"}
    items = [c for c in list_collections(data_dir) if Path(c["folder"]).resolve() != folder]
    name = re.sub(r"[^\w .-]+", "", str(name or folder.name)).strip() or "Documents"
    taken = {c["name"].lower() for c in items}
    base, n = name, 2
    while name.lower() in taken:
        name = "%s %d" % (base, n)
        n += 1
    item = {"name": name, "folder": str(folder), "ocr": bool(ocr), "added": time.time()}
    items.append(item)
    _save_collections(data_dir, items)
    return {"ok": True, "collection": item}


def remove_collection(data_dir: Path, name: str) -> dict:
    items = list_collections(data_dir)
    keep = [c for c in items if c["name"].lower() != str(name or "").lower()]
    if len(keep) == len(items):
        return {"ok": False, "error": "no collection called %s" % name}
    _save_collections(data_dir, keep)
    return {"ok": True}


def collection_index(data_dir: Path, coll: dict) -> ProjectIndex:
    key = (str(Path(coll["folder"]).resolve()), str(data_dir), "docs", bool(coll.get("ocr")))
    if key not in _INDEXES:
        _INDEXES[key] = ProjectIndex(Path(coll["folder"]), Path(data_dir), documents=True, ocr=bool(coll.get("ocr")))
    return _INDEXES[key]


def search_documents(data_dir: Path, query: str, top: int = 5, collection: str = "", fresh: bool = True,
                     wait: bool = False) -> list:
    """[{collection, path, cite, text, score, page?}] across the owner's collections, best first."""
    hits = []
    for coll in list_collections(data_dir):
        if collection and coll["name"].lower() != str(collection).lower():
            continue
        index = collection_index(data_dir, coll)
        if fresh:
            index.ensure_fresh(background=not wait)
        for hit in index.search(query, top=top):
            hit = dict(hit, collection=coll["name"], folder=coll["folder"])
            hit["cite"] = "%s/%s" % (coll["name"], hit["cite"])
            hits.append(hit)
    hits.sort(key=lambda h: -h["score"])
    return hits[:max(1, int(top))]
