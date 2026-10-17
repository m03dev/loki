"""Code maps: see a file's (or a folder's) structure without reading every line.

Ported into LOKI (session 27 harvest) from SWE-agent's `filemap` tool
(github.com/SWE-agent/SWE-agent, tools/filemap/bin/filemap: print a Python file with every
function body of 5+ lines elided as "... eliding lines a-b ...") and its `search_dir`
(per-file match counts, "More than N files matched ... narrow your search"), MIT License -
see engine/licenses/SWE-agent-MIT.txt. SWE-agent uses tree-sitter; LOKI uses Python's own
`ast` for .py and a line-pattern outline for other languages, so it needs nothing installed.

  outline(path)        a numbered skeleton: classes, functions, methods (signatures kept,
                       long bodies elided) - for .py exact, for JS/TS/Go/Rust/Java/C#/GDScript/
                       Ruby/PHP/Swift/Kotlin/C/C++ by declaration patterns.
  repo_map(root)       every source file with its top-level symbols and line numbers,
                       bounded, biggest files first - a small model's map of a project.
  search_dir(root, s)  which files mention `s`, with counts (SWE-agent search_dir).
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

ELIDE_MIN_LINES = 5
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".godot",
             "harness_data", ".idea", ".vscode", "target", ".mypy_cache", ".pytest_cache", "vendor"}
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".cs", ".gd",
                   ".rb", ".php", ".swift", ".kt", ".c", ".h", ".cc", ".cpp", ".hpp", ".lua", ".dart", ".scala"}
MAX_FILE_BYTES = 1_500_000

# Declaration lines worth showing, per language family (first group = the name).
_DECL = {
    "js": re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+([A-Za-z_$][\w$]*)|"
                     r"class\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
                     r"(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)|interface\s+([A-Za-z_$][\w$]*)|"
                     r"type\s+([A-Za-z_$][\w$]*)\s*=|enum\s+([A-Za-z_$][\w$]*))"),
    "js_method": re.compile(r"^\s{2,}(?:static\s+|async\s+|get\s+|set\s+|public\s+|private\s+|protected\s+)*"
                            r"([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{\s*$"),
    "go": re.compile(r"^(?:func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)|type\s+([A-Za-z_]\w*)\s+(?:struct|interface))"),
    "rs": re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:fn\s+([A-Za-z_]\w*)|struct\s+([A-Za-z_]\w*)|"
                     r"enum\s+([A-Za-z_]\w*)|trait\s+([A-Za-z_]\w*)|impl(?:<[^>]*>)?\s+([A-Za-z_][\w:<>, ]*))"),
    "java": re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|override|internal|sealed|async|"
                       r"virtual|partial|open|data|suspend)\s+)*(?:class|interface|enum|record|struct|object|fun)\s+"
                       r"([A-Za-z_]\w*)|^\s*(?:(?:public|private|protected|static|final|abstract|override|async|"
                       r"virtual|internal)\s+)+[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\([^;]*$"),
    "gd": re.compile(r"^\s*(?:static\s+)?(?:func\s+([A-Za-z_]\w*)|class_name\s+([A-Za-z_]\w*)|"
                     r"class\s+([A-Za-z_]\w*)|signal\s+([A-Za-z_]\w*))"),
    "rb": re.compile(r"^\s*(?:def\s+([A-Za-z_][\w.?!]*)|class\s+([A-Z]\w*)|module\s+([A-Z]\w*))"),
    "php": re.compile(r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*(?:function\s+([A-Za-z_]\w*)|"
                      r"class\s+([A-Za-z_]\w*)|interface\s+([A-Za-z_]\w*)|trait\s+([A-Za-z_]\w*))"),
    "swift": re.compile(r"^\s*(?:(?:public|private|internal|fileprivate|open|static|final|override|mutating)\s+)*"
                        r"(?:func\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)|struct\s+([A-Za-z_]\w*)|"
                        r"enum\s+([A-Za-z_]\w*)|protocol\s+([A-Za-z_]\w*)|extension\s+([A-Za-z_]\w*))"),
    "c": re.compile(r"^(?:[A-Za-z_][\w\s\*&:<>,]*?)\b([A-Za-z_][\w:~]*)\s*\([^;{]*\)\s*(?:const\s*)?\{?\s*$|"
                    r"^\s*(?:class|struct|namespace|enum)\s+([A-Za-z_]\w*)"),
    "lua": re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_][\w.:]*)"),
}
_FAMILY = {".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".go": "go",
           ".rs": "rs", ".java": "java", ".cs": "java", ".kt": "java", ".scala": "java", ".dart": "java",
           ".gd": "gd", ".rb": "rb", ".php": "php", ".swift": "swift", ".c": "c", ".h": "c", ".cc": "c",
           ".cpp": "c", ".hpp": "c", ".lua": "lua"}
_NOT_NAMES = {"if", "for", "while", "switch", "catch", "return", "else", "do", "sizeof", "new", "delete"}


def _read(path: Path) -> str:
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("%s is too big to outline (%d bytes)" % (path.name, path.stat().st_size))
    return path.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- python (SWE-agent filemap)
def python_elisions(text: str) -> list:
    """(start, end) 0-based line ranges of function bodies of ELIDE_MIN_LINES+ lines."""
    tree = ast.parse(text)
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            start = first.lineno - 1
            # keep a docstring's first line visible: it says what the function does
            if (isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant)
                    and isinstance(first.value.value, str)):
                start = first.end_lineno if len(node.body) > 1 else first.end_lineno
            end = (node.end_lineno or node.body[-1].lineno) - 1
            if end - start + 1 >= ELIDE_MIN_LINES:
                ranges.append((start, end))
    # nested functions sit inside an outer elided range: keep only the outermost
    ranges.sort()
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            continue
        merged.append((start, end))
    return merged


def python_filemap(text: str) -> str:
    lines = text.splitlines()
    elide = python_elisions(text)
    hidden = {i for start, end in elide for i in range(start, end + 1)}
    messages = [(start, "... eliding lines %d-%d ..." % (start + 1, end + 1)) for start, end in elide]
    rows = messages + [(i, line) for i, line in enumerate(lines) if i not in hidden]
    return "\n".join("%6d %s" % (i + 1, line) for i, line in sorted(rows, key=lambda r: (r[0], not r[1].startswith("..."))))


def python_symbols(text: str) -> list:
    """[(line, kind, name, signature)] for classes, functions and methods."""
    out = []
    tree = ast.parse(text)

    def sig(fn) -> str:
        try:
            return "(%s)" % ast.unparse(fn.args)
        except Exception:  # noqa: BLE001
            return "(...)"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.lineno, "def", node.name, sig(node)))
        elif isinstance(node, ast.ClassDef):
            out.append((node.lineno, "class", node.name, ""))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((item.lineno, "  def", node.name + "." + item.name, sig(item)))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id.isupper():
            out.append((node.lineno, "const", node.targets[0].id, ""))
    return out


# --------------------------------------------------------------------------- other languages
def pattern_symbols(text: str, suffix: str) -> list:
    family = _FAMILY.get(suffix)
    if not family:
        return []
    rx = _DECL[family]
    method_rx = _DECL["js_method"] if family == "js" else None
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 300:
            continue
        m = rx.match(line)
        kind = "decl"
        if not m and method_rx is not None:
            m = method_rx.match(line)
            kind = "  method"
        if not m:
            continue
        name = next((g for g in m.groups() if g), "")
        if not name or name in _NOT_NAMES:
            continue
        out.append((i, kind, name.strip(), line.strip()[:120]))
    return out


def symbols(path: Path) -> list:
    path = Path(path)
    text = _read(path)
    suffix = path.suffix.lower()
    if suffix == ".py":
        try:
            return python_symbols(text)
        except SyntaxError:
            return []
    return pattern_symbols(text, suffix)


def outline(path: Path, label: str = "") -> str:
    """A file's skeleton, numbered. Python: SWE-agent's filemap. Others: its declarations."""
    path = Path(path)
    label = label or path.name
    if not path.is_file():
        return "error: no file %s" % label
    try:
        text = _read(path)
    except (OSError, ValueError) as exc:
        return "error: %s" % exc
    total = len(text.splitlines())
    if path.suffix.lower() == ".py":
        try:
            body = python_filemap(text)
            return ("%s (%d lines; function bodies of %d+ lines elided - read_file with start_line/end_line "
                    "to see one):\n%s" % (label, total, ELIDE_MIN_LINES, body))
        except SyntaxError as exc:
            return "error: %s does not parse (line %s: %s) - read it with read_file" % (label, exc.lineno, exc.msg)
    syms = pattern_symbols(text, path.suffix.lower())
    if not syms:
        return "%s (%d lines): no declarations recognised - read it with read_file and a line range" % (label, total)
    rows = ["%6d %s" % (line, sig) for line, _kind, _name, sig in syms]
    return "%s (%d lines), declarations:\n%s" % (label, total, "\n".join(rows))


def _walk(root: Path, suffixes: set | None = None):
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if suffixes is None or p.suffix.lower() in suffixes:
                yield p


def repo_map(root: Path, max_files: int = 60, max_symbols: int = 12, max_chars: int = 12000) -> str:
    """Every source file and its top-level symbols with line numbers, biggest files first."""
    root = Path(root)
    if not root.is_dir():
        return "error: no folder %s" % root
    files = []
    for p in _walk(root, SOURCE_SUFFIXES):
        try:
            files.append((p.stat().st_size, p))
        except OSError:
            continue
    if not files:
        return "no source files under %s" % root.name
    files.sort(key=lambda t: (-t[0], str(t[1])))
    shown = sorted(files[:max_files], key=lambda t: str(t[1]))
    out, used = [], 0
    for _size, p in shown:
        rel = p.relative_to(root).as_posix()
        try:
            syms = [s for s in symbols(p) if not s[1].startswith("  ") and s[1] != "const"]
            # public names first (what other files call), then private helpers; line order within
            syms = sorted(syms, key=lambda s: (s[2].startswith("_"), s[0]))[:max_symbols]
            syms.sort(key=lambda s: s[0])
            lines = len(_read(p).splitlines())
        except (OSError, ValueError):
            continue
        entry = rel + " (%d lines)" % lines + "".join(
            "\n    %d: %s %s%s" % (line, kind.strip(), name, sig if kind.strip() == "def" else "")
            for line, kind, name, sig in syms)
        if used + len(entry) > max_chars:
            out.append("... %d more files (repo_map a subfolder to see them)" % (len(shown) - len(out)))
            break
        out.append(entry)
        used += len(entry) + 1
    more = len(files) - len(shown)
    head = "Map of %s: %d source files%s.\n" % (root.name or str(root), len(files),
                                               (", the %d biggest shown" % len(shown)) if more > 0 else "")
    return head + "\n".join(out)


def search_dir(root: Path, term: str, max_files: int = 100) -> str:
    """SWE-agent search_dir: files that contain `term` (plain text), with match counts."""
    root = Path(root)
    term = str(term or "")
    if not term:
        return "error: give a search term"
    counts = []
    for p in _walk(root):
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        n = data.decode("utf-8", errors="replace").count(term)
        if n:
            counts.append((p.relative_to(root).as_posix(), n))
    if not counts:
        return 'No matches found for "%s" in %s' % (term, root.name or root)
    if len(counts) > max_files:
        return 'More than %d files matched for "%s" in %s. Please narrow your search.' % (max_files, term, root.name or root)
    total = sum(n for _p, n in counts)
    body = "\n".join("%s (%d matches)" % (p, n) for p, n in counts)
    return 'Found %d matches for "%s" in %s:\n%s\nEnd of matches for "%s"' % (total, term, root.name or root, body, term)
