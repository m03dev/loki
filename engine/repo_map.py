"""Repo map: the most important definitions of a code base, ranked, in a few thousand characters.

Ported from aider's RepoMap (Aider-AI/aider, aider/repomap.py: get_ranked_tags,
get_ranked_tags_map_uncached, to_tree), Apache-2.0 - see engine/licenses/Aider-Apache-2.0.txt.

Why: a 7-9B local model cannot read a whole project, and grepping blind wastes its few turns.
aider's answer is a map - every file's important symbols (classes, functions, constants) with
the line that defines them - ranked by how much the rest of the code (and the current request)
depends on them, cut to a size budget. The model reads the map once and knows where to look.

What is kept from aider:
  * tags: a "def" for every definition and a "ref" for every use of an identifier
  * a graph file -> file, one edge per identifier a file uses that another file defines, weighted
    exactly like aider: x10 for an identifier the request mentions, x10 for a long
    snake/camel/kebab name, x0.1 for _private names, x0.1 for names defined in more than 5 files,
    x50 when the referencing file is one the request is about, sqrt(number of references)
  * personalized PageRank (the request's files and the files whose names it mentions get the
    restart probability), then each file's rank spread over its out-edges to rank definitions
  * a binary search for the number of tags that best fills the budget (15% tolerance)
What changed: aider uses tree-sitter grammars and networkx. LOKI has neither on every machine, so
Python files are read with `ast` and other languages with small regular expressions, and PageRank
is a 40-line power iteration with networkx's semantics (dangling nodes follow personalization).
Pure functions plus an mtime cache; no network.
"""
from __future__ import annotations

import ast
import builtins
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".godot", "dist", "build",
             "harness_data", ".mypy_cache", ".pytest_cache", ".tox", "vendor", ".next", "target",
             ".idea", ".vscode", "site-packages", ".claude"}
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".gd", ".go", ".rs", ".java", ".kt",
            ".cs", ".cpp", ".cc", ".c", ".h", ".hpp", ".rb", ".php", ".swift", ".lua", ".sh"}
# aider's filter_important_files: files a reader needs to see even without symbols.
IMPORTANT = {"readme.md", "readme", "package.json", "pyproject.toml", "setup.py", "requirements.txt",
             "cargo.toml", "go.mod", "makefile", "dockerfile", "agents.md", "claude.md", "project.godot"}
MAX_FILES = 3000
MAX_FILE_BYTES = 2_000_000
DEFAULT_CHARS = 6000

_KEYWORDS = set("""
if else elif for while return def class import from as with try except finally raise pass break
continue lambda yield async await not and or in is none true false self cls function const let var
new this super extends export default switch case typeof instanceof void delete static public
private protected interface type enum struct impl fn pub use mod match func package go defer chan
select map string int float bool list dict set tuple object null undefined print len range str
""".split())

_DEF_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
               r"(?:function\b|\([^()]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Z][A-Z0-9_]{2,})\s*="),
    re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:static\s+)?(?:func|fn|def|sub)\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)"),
    re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|trait|impl|mod)\s+([A-Za-z_][\w]*)"),
    re.compile(r"^\s*class_name\s+([A-Za-z_][\w]*)"),
    re.compile(r"^\s*signal\s+([A-Za-z_][\w]*)"),
    # a method inside a JS/TS class body: `  name(args) {`
    re.compile(r"^\s{2,}(?:async\s+|static\s+|get\s+|set\s+)*([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*\{\s*$"),
]
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# Names every language uses for its own things: a reference to them says nothing about the code.
_GENERIC = set(dir(builtins)) | {"get", "set", "items", "keys", "values", "append", "join", "split", "strip",
                                 "format", "update", "read", "write", "open", "close", "path", "name", "text",
                                 "value", "data", "result", "args", "kwargs", "error", "push", "length",
                                 "console", "log", "document", "window", "Math", "JSON", "Object", "Array",
                                 "Promise", "then", "catch", "replace", "lower", "upper", "startswith",
                                 "endswith", "exists", "main", "out", "run", "list", "ok", "state"}


class Tag(tuple):
    """(rel_fname, line, name, kind, text) - a tuple so tags sort by file then line like aider's."""
    __slots__ = ()

    def __new__(cls, rel_fname, line, name, kind, text=""):
        return tuple.__new__(cls, (rel_fname, line, name, kind, text))

    rel_fname = property(lambda self: self[0])
    line = property(lambda self: self[1])
    name = property(lambda self: self[2])
    kind = property(lambda self: self[3])
    text = property(lambda self: self[4])


# --------------------------------------------------------------------------- tags

def _python_tags(rel: str, code: str) -> list:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return _regex_tags(rel, code)
    lines = code.splitlines()
    tags = []

    def line_text(n):
        return lines[n - 1].rstrip() if 0 < n <= len(lines) else ""

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tags.append(Tag(rel, node.lineno, node.name, "def", line_text(node.lineno)))
        elif isinstance(node, ast.Assign) and node in getattr(tree, "body", []):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 2:
                    tags.append(Tag(rel, node.lineno, target.id, "def", line_text(node.lineno)))
        elif isinstance(node, ast.Name):
            tags.append(Tag(rel, node.lineno, node.id, "ref"))
        elif isinstance(node, ast.Attribute):
            # `module.name`: keep the qualifier so the reference goes to module.py only
            qual = node.value.id if isinstance(node.value, ast.Name) else ""
            tags.append(Tag(rel, node.lineno, node.attr, "ref", qual))
    return tags


def _regex_tags(rel: str, code: str) -> list:
    tags = []
    in_block_comment = False
    for n, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*") and "*/" not in stripped:
            in_block_comment = True
            continue
        if stripped.startswith(("//", "#", "--", "*")) and not stripped.startswith("#define"):
            continue
        defined = None
        for pattern in _DEF_PATTERNS:
            m = pattern.match(line)
            if m and m.group(1).lower() not in _KEYWORDS:
                defined = m.group(1)
                tags.append(Tag(rel, n, defined, "def", line.rstrip()))
                break
        for m in _IDENT.finditer(re.sub(r"(['\"`]).*?\1", "", line)):
            word = m.group(0)
            if word != defined and word.lower() not in _KEYWORDS and len(word) > 1:
                tags.append(Tag(rel, n, word, "ref"))
    return tags


def file_tags(rel: str, code: str) -> list:
    if rel.endswith(".py"):
        return _python_tags(rel, code)
    return _regex_tags(rel, code)


# --------------------------------------------------------------------------- pagerank

def pagerank(edges: dict, personalization: dict | None = None, alpha: float = 0.85,
             max_iter: int = 100, tol: float = 1.0e-6) -> dict:
    """networkx.pagerank semantics on {(src, dst): weight}; dangling nodes jump by personalization."""
    nodes = sorted({n for pair in edges for n in pair})
    if not nodes:
        return {}
    out_weight = defaultdict(float)
    for (src, _dst), w in edges.items():
        out_weight[src] += w
    if personalization:
        total = sum(personalization.get(n, 0.0) for n in nodes)
        p = {n: personalization.get(n, 0.0) / total for n in nodes} if total > 0 else None
    else:
        p = None
    if p is None:
        p = {n: 1.0 / len(nodes) for n in nodes}
    x = {n: 1.0 / len(nodes) for n in nodes}
    dangling = [n for n in nodes if out_weight[n] == 0]
    for _ in range(max_iter):
        last = x
        x = {n: 0.0 for n in nodes}
        danglesum = alpha * sum(last[n] for n in dangling)
        for (src, dst), w in edges.items():
            x[dst] += alpha * last[src] * w / out_weight[src]
        for n in nodes:
            x[n] += danglesum * p[n] + (1.0 - alpha) * p[n]
        if sum(abs(x[n] - last[n]) for n in nodes) < len(nodes) * tol:
            break
    return x


# --------------------------------------------------------------------------- ranking (aider)

def mentioned_idents(text: str) -> set:
    return {w for w in _IDENT.findall(text or "") if len(w) > 2}


def ranked_tags(tags_by_file: dict, chat_files=(), mentioned_files=(), mentioned=()) -> list:
    """aider's get_ranked_tags on pre-computed tags. Returns Tag objects and (fname,) tuples."""
    chat_files, mentioned_files, mentioned = set(chat_files), set(mentioned_files), set(mentioned)
    defines, references, definitions = defaultdict(set), defaultdict(list), defaultdict(set)
    qualified = defaultdict(list)   # ident -> [(referencer, qualifier)] for `module.ident`
    fnames = sorted(tags_by_file)
    if not fnames:
        return []
    personalize = 100 / len(fnames)
    personalization = {}
    for rel in fnames:
        current = 0.0
        if rel in chat_files:
            current += personalize
        if rel in mentioned_files:
            current = max(current, personalize)
        path = Path(rel)
        parts = set(path.parts) | {path.name, path.stem}
        if parts & mentioned:
            current += personalize
        if current > 0:
            personalization[rel] = current
        for tag in tags_by_file[rel]:
            if tag.kind == "def":
                defines[tag.name].add(rel)
                definitions[(rel, tag.name)].add(tag)
            else:
                references[tag.name].append(rel)
                if tag.text:
                    qualified[tag.name].append((rel, tag.text))
    # LOKI addition: a file that DEFINES an identifier the request names is part of the request
    # (aider gets this from the files the user /adds; LOKI's model only names symbols).
    for ident in mentioned:
        if len(ident) >= 6 and ident in defines and len(defines[ident]) <= 5:
            for rel in defines[ident]:
                personalization[rel] = personalization.get(rel, 0.0) + personalize
    if not references:
        references = {k: list(v) for k, v in defines.items()}
    edges = defaultdict(float)
    edge_idents = defaultdict(lambda: defaultdict(float))
    for ident, definers in defines.items():
        if ident in references:
            continue
        for definer in definers:
            edges[(definer, definer)] += 0.1
            edge_idents[(definer, definer)][ident] += 0.1
    for ident in set(defines) & set(references):
        mul = 1.0
        is_snake = "_" in ident and any(c.isalpha() for c in ident)
        is_kebab = "-" in ident and any(c.isalpha() for c in ident)
        is_camel = any(c.isupper() for c in ident) and any(c.islower() for c in ident)
        if ident in mentioned:
            mul *= 10
        if (is_snake or is_kebab or is_camel) and len(ident) >= 8:
            mul *= 10
        if ident.startswith("_"):
            mul *= 0.1
        if len(defines[ident]) > 5:
            mul *= 0.1
        # LOKI: without tree-sitter's scoping every short or generic name looks like a reference.
        if ident in _GENERIC or len(ident) <= 4:
            mul *= 0.05
        stems = {Path(d).stem: d for d in defines[ident]}
        quals = Counter(qualified.get(ident, ()))
        for referencer, num_refs in Counter(references[ident]).items():
            # LOKI: `laya.base_url()` names its module - point only at laya.py when it defines it
            targets = [stems[q] for (r, q) in quals if r == referencer and q in stems]
            if not targets and referencer in defines[ident] and len(defines[ident]) > 1:
                continue   # its own copy of a common name: no dependency on the other copies
            for definer in (sorted(set(targets)) if targets else defines[ident]):
                if referencer == definer and len(defines[ident]) > 1:
                    # a file using its OWN copy of a name another file also defines (data_dir,
                    # TIMEOUT_S) is not a dependency; aider has this test commented out
                    continue
                use_mul = mul * (50 if referencer in chat_files else 1)
                weight = use_mul * math.sqrt(num_refs)
                edges[(referencer, definer)] += weight
                edge_idents[(referencer, definer)][ident] += weight
    ranked = pagerank(dict(edges), personalization or None)
    ranked_defs = defaultdict(float)
    out_total = defaultdict(float)
    for (src, _dst), w in edges.items():
        out_total[src] += w
    for (src, dst), idents in edge_idents.items():
        for ident, w in idents.items():
            ranked_defs[(dst, ident)] += ranked.get(src, 0.0) * w / out_total[src]
    # Definitions the request names exactly come first, then aider's order.
    result = []
    for ident in sorted(mentioned):
        if len(ident) >= 6 and len(defines.get(ident, ())) <= 5:
            for fname in sorted(defines.get(ident, ())):
                if fname not in chat_files:
                    result += sorted(definitions.get((fname, ident), []))
    for (fname, ident), _rank in sorted(ranked_defs.items(), reverse=True, key=lambda x: (x[1], x[0])):
        if fname in chat_files:
            continue
        result += sorted(definitions.get((fname, ident), []))
    seen: set = set()
    result = [t for t in result if not (t in seen or seen.add(t))]
    included = {t[0] for t in result}
    for _rank, fname in sorted(((r, n) for n, r in ranked.items()), reverse=True):
        if fname not in included and fname not in chat_files:
            result.append((fname,))
            included.add(fname)
    for fname in fnames:
        if fname not in included and fname not in chat_files:
            result.append((fname,))
    return result


def to_tree(tags: list, chat_files=()) -> str:
    """aider's to_tree, with each file's definition lines in place of tree-sitter context."""
    by_file: dict = defaultdict(list)
    order = []
    for tag in sorted(tags, key=lambda t: (t[0], t[1] if len(t) > 1 else 0)):
        rel = tag[0]
        if rel in chat_files:
            continue
        if rel not in by_file:
            order.append(rel)
            by_file[rel] = []
        if len(tag) > 1 and tag[4]:
            by_file[rel].append(tag)
    out = []
    for rel in order:
        lines = by_file[rel]
        if not lines:
            out.append(rel)
            continue
        out.append(rel + ":")
        last = 0
        for tag in lines:
            if tag[1] == last:
                continue
            if last and tag[1] > last + 1:
                out.append("⋮")
            out.append("│" + tag[4][:100])
            last = tag[1]
        out.append("⋮")
    return "\n".join(out) + ("\n" if out else "")


def fit(ranked: list, max_chars: int, chat_files=(), special=()) -> str:
    """aider's binary search: the most tags whose tree fits max_chars (within 15%)."""
    ranked = [(f,) for f in special if f not in {t[0] for t in ranked}] + list(ranked)
    lower, upper = 0, len(ranked)
    best, best_len = "", 0
    middle = min(max(1, max_chars // 100), len(ranked))
    while lower <= upper:
        tree = to_tree(ranked[:middle], chat_files)
        size = len(tree)
        err = abs(size - max_chars) / max(1, max_chars)
        if (size <= max_chars and size > best_len) or err < 0.15:
            best, best_len = tree, size
            if err < 0.15:
                break
        if size < max_chars:
            lower = middle + 1
        else:
            upper = middle - 1
        middle = (lower + upper) // 2
    return best


# --------------------------------------------------------------------------- the files

_CACHE: dict = {}


def source_files(root: Path, subdir: str = ".") -> list:
    """Every source file under root/subdir, RESOLVED (a symlinked root - macOS /tmp is
    /private/tmp - walks the real tree, so callers that compare against the root must resolve
    theirs too; build() does)."""
    base = (Path(root) / subdir).resolve()
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() in CODE_EXT or name.lower() in IMPORTANT:
                found.append(path)
                if len(found) >= MAX_FILES:
                    return found
    return found


def tags_for(path: Path, rel: str) -> list:
    try:
        stat = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _CACHE.get(key)
    if hit and hit[0] == stat.st_mtime_ns:
        return hit[1]
    if stat.st_size > MAX_FILE_BYTES or path.suffix.lower() not in CODE_EXT:
        tags = []
    else:
        try:
            tags = file_tags(rel, path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            tags = []
    _CACHE[key] = (stat.st_mtime_ns, tags)
    return tags


def build(root: Path, focus: str = "", chat_files=(), max_chars: int = DEFAULT_CHARS, subdir: str = ".") -> str:
    """The ranked map of `root` (or root/subdir) for a request about `focus`."""
    root = Path(root).resolve()
    files = source_files(root, subdir)
    tags_by_file, rels = {}, []
    for path in files:
        rel = path.relative_to(root).as_posix()
        rels.append(rel)
        tags_by_file[rel] = tags_for(path, rel)
    words = mentioned_idents(focus)
    mentioned_files = {r for r in rels if r in (focus or "") or Path(r).name in (focus or "")}
    chat = {str(c).replace("\\", "/").lstrip("./") for c in chat_files or ()}
    ranked = ranked_tags(tags_by_file, chat, mentioned_files, words)
    special = [r for r in rels if Path(r).name.lower() in IMPORTANT and "/" not in r]
    tree = fit(ranked, int(max_chars or DEFAULT_CHARS), chat, special)
    if not tree:
        return "(no source files found)"
    return tree
