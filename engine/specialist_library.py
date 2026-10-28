"""Real references and premade specialists for every task (owner 2026-10-28: "the prompt agent is bad, needs
improvement depending on the task, needs real ref ... find repo for skills agents, we need premade, just add them to
loki").

Everything here comes from proven open-source libraries that engine/ecc_sync.py downloads into harness_data/vendor:

  wshobson-agents      wshobson/agents (MIT) - ~180 agents + ~185 skills in plugins/<area>/{agents,skills}
  voltagent-subagents  VoltAgent/awesome-claude-code-subagents (MIT) - ~130 agents in categories/<area>/*.md
  nano-banana-prompts  YouMind-OpenLab/awesome-nano-banana-pro-prompts (CC BY 4.0) - real image prompts, each with
                       the pictures it really produced, author and source
  gpt-image-prompts    YouMind-OpenLab/awesome-gpt-image-2 (CC BY 4.0) - the same for GPT Image 2
  chatgpt-prompts      f/awesome-chatgpt-prompts (CC0) - ~2,700 role prompts ("act as ...") for any task
  wan-prompts          Wan-Video/Wan2.2 (Apache-2.0) - Alibaba's own prompt-extension rules for Wan text/image-to-video
  ... plus ECC, GodotPrompter, Superpowers and the game-dev packs that were already there, and skills/ in the repo.

    kind(task)                      -> "image" | "turnaround" | "3d" | "video" | "code" | "writing" | "marketing" |
                                       "research" | "general"
    best_specialists(task, n, what) -> [{"lib", "what": "agent"|"skill", "name", "desc", "path", "score"}]
    specialist_text(entry, limit)   -> that agent's / skill's instructions, cleaned and capped
    image_refs(task, n)             -> [{"title", "prompt", "images", "author", "source", "lib"}] real prompts + results
    role_prompt(task)               -> {"act", "prompt"} | None    the best "act as" prompt for a text task
    video_rules(image_to_video)     -> Wan2.2's official prompt-extension rules (English) or ""
    for_task(task)                  -> all of the above for one task, for prompts and the UI

Standard library only; every index is built once per process and rebuilt when the vendor folder changes.
"""
from __future__ import annotations

import ast
import csv
import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    explicit = (os.getenv("LOKI_DATA") or os.getenv("LOKI_DATA_DIR") or "").strip()
    return Path(explicit) if explicit else ROOT / "harness_data"


def vendor() -> Path:
    return _data_dir() / "vendor"


# ----------------------------------------------------------------------------- what kind of task
_KINDS = (
    ("turnaround", r"\b(turnaround|orthographic|t-?pose|front.{0,12}side.{0,12}back|model sheet|character sheet)\b"),
    ("video", r"\b(video|clip|shot|footage|animate|animation|text.to.video|trailer|cinematic)\b"),
    ("3d", r"\b(3d model|\.glb|mesh|retopo\w*|uv(?:s| unwrap)?|bake|sculpt\w*|blender|low.?poly|game.?ready|lods?)\b"),
    ("image", r"\b(image|picture|illustration|concept art|painting|drawing|sprite|icon|logo|poster|thumbnail|"
              r"portrait|wallpaper|render of|photo of|pixel art)\b"),
    ("code", r"\b(code|script|python|javascript|typescript|rust|c\+\+|gdscript|function|class|bug|refactor|api|"
             r"test(?:s|ing)?|repo|git|build|compile|endpoint|database|sql)\b"),
    ("marketing", r"\b(ad|ads|advert\w*|campaign|social media|tiktok|instagram|youtube|tweet|seo|newsletter|"
                  r"outreach|launch|brand\w*|marketing|copy ?writing)\b"),
    ("research", r"\b(research|compare|find out|look up|which is best|survey|sources|papers?|benchmarks?)\b"),
    ("writing", r"\b(write|essay|story|novel|blog|article|email|letter|script for|lyrics|summary|summari[sz]e|"
                r"report|docs?|documentation)\b"),
)


def kind(task: str) -> str:
    text = str(task or "")
    for name, rx in _KINDS:
        if re.search(rx, text, re.I):
            return name
    return "general"


# ----------------------------------------------------------------------------- a small BM25
_STOP = set("""a an the and or of to in on for with by at from as is are be this that it its into your you our we
use when need needs using used make makes made build create new any all can will should not but also more most very
write writes get our my me please want help task good great best act expert
like via than then them they their there these those which who what how why one two only just about over under""".split())


_SHORT = {"3d", "2d", "ui", "ux", "ai", "qa", "uv", "ml", "db", "go", "js", "ts", "c#", "c++", "vr", "ar", "os"}
_SYN = {"ad": "advertising", "ads": "advertising", "advert": "advertising", "tiktok": "tiktok social video content",
        "instagram": "instagram social content", "reels": "social video content", "tweet": "twitter social",
        "blog": "blog content article", "seo": "seo search", "golem": "creature", "dragon": "creature",
        "retopologize": "retopology mesh topology", "retopo": "retopology mesh topology", "glb": "3d model mesh",
        "turnaround": "character sheet reference", "fastapi": "fastapi python api"}


def _tokens(text: str, expand: bool = False) -> list:
    out = []
    words = re.findall(r"[a-z0-9][a-z0-9+#.-]*", str(text or "").lower())
    if expand:
        words = [x for w in words for x in ([w] + _SYN.get(w.strip(".-"), "").split())]
    for w in words:
        w = w.strip(".-")
        if (len(w) < 3 and w not in _SHORT) or w in _STOP:
            continue
        for suf in ("ing", "ers", "er", "ed", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


class _Index:
    def __init__(self, docs: list, fields):
        self.docs = docs
        self.terms = []
        df: dict = {}
        for d in docs:
            tf: dict = {}
            for text, weight in fields(d):
                for t in _tokens(text):
                    tf[t] = tf.get(t, 0) + weight
            self.terms.append(tf)
            for t in tf:
                df[t] = df.get(t, 0) + 1
        n = max(1, len(docs))
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.avg = (sum(sum(tf.values()) for tf in self.terms) / n) or 1.0

    def search(self, query: str, n: int = 5, keep=None) -> list:
        q = set(_tokens(query, expand=True))
        if not q:
            return []
        scored = []
        for i, tf in enumerate(self.terms):
            if keep is not None and not keep(self.docs[i]):
                continue
            length = sum(tf.values()) or 1
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * length / self.avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: -x[0])
        top = scored[0][0] if scored else 0
        return [dict(self.docs[i], score=round(s, 2)) for s, i in scored[:n] if s >= 0.55 * top]


_CACHE: dict = {}


def _stamp() -> tuple:
    base = vendor()
    marks = sorted(base.glob("*/.loki_sync.json")) if base.is_dir() else []
    return tuple((str(p), p.stat().st_mtime) for p in marks) + ((str(ROOT / "skills"),),)


def _cached(name: str, build):
    key = (name, _stamp())
    if _CACHE.get(name, (None,))[0] != key:
        _CACHE[name] = (key, build())
    return _CACHE[name][1]


# ----------------------------------------------------------------------------- premade agents and skills
def _front(path: Path) -> tuple:
    """(name, description, body) of an agent / skill markdown file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", "", ""
    name, desc, body = "", "", text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        body = text[m.end():]
        head = m.group(1)
        nm = re.search(r"^name:\s*(.+)$", head, re.M)
        name = nm.group(1).strip().strip("'\"") if nm else ""
        dm = re.search(r"^description:\s*(>-?|\|-?)?\s*(.*?)(?=^\w[\w-]*:|\Z)", head, re.M | re.S)
        if dm:
            desc = " ".join(dm.group(2).split()).strip().strip("'\"")
    if not desc:   # no frontmatter: the first real paragraph
        for para in re.split(r"\n\s*\n", body):
            p = " ".join(para.split())
            if p and not p.startswith(("#", "```", "|", "<", "!")):
                desc = p
                break
    return name, desc[:400], body


def _roots() -> list:
    out = [("loki", ROOT / "skills")]
    base = vendor()
    if base.is_dir():
        out += [(p.name, p) for p in sorted(base.iterdir()) if p.is_dir()]
    return out


def _is_agent(path: Path, root: Path) -> bool:
    if path.name.lower() in ("readme.md", "contributing.md", "license.md", "changelog.md", "claude.md", "agents.md"):
        return False
    parts = path.relative_to(root).parts
    return "agents" in parts[:-1] or (len(parts) == 3 and parts[0] == "categories")


def _build_catalog() -> list:
    docs, seen = [], set()
    for lib, root in _roots():
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if path.name == "SKILL.md":
                what = "skill"
            elif _is_agent(path, root):
                what = "agent"
            else:
                continue
            name, desc, _ = _front(path)
            name = name or (path.parent.name if what == "skill" else path.stem)
            key = (what, name.lower())
            if key in seen:
                continue
            seen.add(key)
            area = path.relative_to(root).parts[1] if len(path.relative_to(root).parts) > 2 else ""
            docs.append({"lib": lib, "what": what, "name": name, "desc": desc, "path": str(path), "area": area})
    return docs


def catalog() -> list:
    return _cached("catalog", _build_catalog)


def _catalog_index() -> _Index:
    return _cached("catalog_index", lambda: _Index(
        catalog(), lambda d: ((d["name"].replace("-", " "), 3), (d["area"].replace("-", " "), 1), (d["desc"], 1))))


def best_specialists(task: str, n: int = 3, what: str = "") -> list:
    """The premade agents / skills that fit this task best (what = "agent" or "skill" to pick one sort)."""
    keep = (lambda d: d["what"] == what) if what else None
    return _catalog_index().search(task, n, keep)


def find(name: str) -> dict | None:
    """One catalog entry by exact name (agents and skills of every library)."""
    want = os.path.basename(str(name or "").strip()).lower()
    for d in catalog():
        if d["name"].lower() == want:
            return d
    return None


def specialist_text(entry: dict, limit: int = 2400) -> str:
    """Its instructions, safe to put in a prompt: no frontmatter, no tool lists LOKI does not have, capped."""
    if not entry:
        return ""
    path = Path(entry["path"])
    try:
        import skill_scan  # pylint: disable=import-outside-toplevel
        body = skill_scan.safe_doc(path) if entry["what"] == "agent" else skill_scan.safe_text(path)
    except Exception:  # noqa: BLE001 - the plain file still helps
        body = _front(path)[2]
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", str(body or ""), flags=re.S)
    body = re.sub(r"(?m)^\s*(tools|model):.*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > limit:
        body = body[:limit].rsplit("\n", 1)[0] + "\n..."
    return body


# ----------------------------------------------------------------------------- real image prompts (+ their pictures)
_ARG = re.compile(r"\{argument[^}]*?default=\"([^\"]*)\"[^}]*\}")


def _gallery(path: Path, lib: str) -> list:
    """The entries of a YouMind gallery README: '### No. N: title', a Prompt code block, the pictures, author."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for block in re.split(r"(?m)^### No\. \d+:\s*", text)[1:]:
        title = block.split("\n", 1)[0].strip()
        pm = re.search(r"#### .*?Prompt\s*\n+```[^\n]*\n(.*?)```", block, re.S)
        if not pm:
            continue
        prompt = " ".join(_ARG.sub(lambda m: m.group(1), pm.group(1)).split())
        if len(prompt) < 40 or len(re.findall(r"[一-鿿぀-ヿ]", prompt)) > 20:
            continue   # English prompts only: the image models LOKI drives read English best
        dm = re.search(r"#### .*?Description\s*\n+(.+?)\n\n", block, re.S)
        images = re.findall(r"<img src=\"(https://[^\"]+)\"", block)[:2]
        author = re.search(r"\*\*Author:\*\*\s*\[([^\]]+)\]", block)
        source = re.search(r"\*\*Source:\*\*\s*\[[^\]]*\]\((https?://[^)]+)\)", block)
        out.append({"title": title, "desc": " ".join((dm.group(1) if dm else "").split())[:300], "prompt": prompt,
                    "images": images, "author": author.group(1) if author else "", "lib": lib,
                    "source": source.group(1) if source else ""})
    return out


def _csv_rows() -> list:
    path = vendor() / "chatgpt-prompts" / "prompts.csv"
    if not path.is_file():
        return []
    csv.field_size_limit(1 << 30)
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as fh:
            return [r for r in csv.DictReader(fh) if r.get("act") and r.get("prompt")]
    except (OSError, csv.Error):
        return []


def _build_images() -> list:
    out = []
    for lib in ("nano-banana-prompts", "gpt-image-prompts"):
        p = vendor() / lib / "README.md"
        if p.is_file():
            out += _gallery(p, lib)
    for r in _csv_rows():
        if str(r.get("type") or "").upper() == "IMAGE":
            out.append({"title": r["act"], "desc": "", "prompt": " ".join(r["prompt"].split())[:2400], "images": [],
                        "author": r.get("contributor") or "", "lib": "chatgpt-prompts", "source": ""})
    return out


def _image_index() -> _Index:
    return _cached("image_index", lambda: _Index(
        _cached("images", _build_images), lambda d: ((d["title"], 3), (d["desc"], 1), (d["prompt"], 1))))


_HINTS = {"turnaround": "character sheet model sheet front side back view orthographic full body turnaround",
          "3d": "3d render game asset isometric miniature clay",
          "image": "concept art illustration painting character",
          "video": "cinematic film still shot"}


def image_refs(task: str, n: int = 3, task_kind: str = "") -> list:
    """Real prompts that made great pictures in real image models, closest to this task first; pictures first
    (an entry with its real results beats one without)."""
    idx = _image_index()
    q = "%s %s" % (task, _HINTS.get(task_kind or kind(task), ""))
    hits = idx.search(q, max(n * 3, 6))
    hits.sort(key=lambda d: -(d["score"] + (0.5 if d["images"] else 0)))
    return hits[:n]


# ----------------------------------------------------------------------------- role prompts for text tasks
def _role_index() -> _Index:
    rows = _cached("roles", lambda: [{"act": r["act"], "prompt": " ".join(r["prompt"].split())}
                                     for r in _csv_rows() if str(r.get("type") or "TEXT").upper() != "IMAGE"])
    return _cached("role_index", lambda: _Index(rows, lambda d: ((d["act"], 4), (d["prompt"][:600], 1))))


def role_prompt(task: str) -> dict | None:
    hits = _role_index().search(task, 1)
    if not hits:
        return None
    # the role's own name must share words with the task, or it is a stray match ("PLC controller" for a Godot one)
    shared = len(set(_tokens(hits[0]["act"])) & set(_tokens(task, expand=True)))
    return hits[0] if shared >= 2 or (shared == 1 and hits[0]["score"] >= 12) else None


# ----------------------------------------------------------------------------- Wan's own video prompt rules
def video_rules(image_to_video: bool = False) -> str:
    """Alibaba's prompt-extension system prompt for Wan2.2 (wan/utils/system_prompt.py), read without running it."""
    def build():
        path = vendor() / "wan-prompts" / "wan" / "utils" / "system_prompt.py"
        found = {}
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return found
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                try:
                    found[node.targets[0].id] = str(ast.literal_eval(node.value))
                except ValueError:
                    continue
        return found
    rules = _cached("wan", build)
    # Wan's rules are written in Chinese; the *_EN_* ones ask for an English prompt (the one LOKI's models read)
    return rules.get("I2V_A14B_EN_SYS_PROMPT" if image_to_video else "T2V_A14B_EN_SYS_PROMPT", "").strip()


# ----------------------------------------------------------------------------- everything for one task
def for_task(task: str, n: int = 3) -> dict:
    k = kind(task)
    out = {"kind": k, "agents": best_specialists(task, n, "agent"), "skills": best_specialists(task, n, "skill")}
    if k in ("image", "turnaround", "3d", "video"):
        out["refs"] = image_refs(task, n, k)
        out["agents"] = [a for a in out["agents"] if a["score"] >= 8]   # the art skills lead; stray coders stay out
    elif k in ("writing", "marketing", "research", "general"):
        out["role"] = role_prompt(task)
    return out


def summary_text(task: str, n: int = 3) -> str:
    """What for_task found, as short lines an agent can act on (load_ecc_agent / load_ecc_skill by name)."""
    f = for_task(task, n)
    lines = ["Task kind: %s" % f["kind"]]
    for what in ("agents", "skills"):
        for d in f[what]:
            lines.append("- %s %s (%s): %s" % (what[:-1], d["name"], d["lib"], d["desc"][:160]))
    for r in f.get("refs") or []:
        lines.append("- reference prompt '%s'%s: %s" % (r["title"], (" by " + r["author"]) if r["author"] else "",
                                                       r["prompt"][:240]))
    if f.get("role"):
        lines.append("- role prompt '%s': %s" % (f["role"]["act"], f["role"]["prompt"][:240]))
    if len(lines) == 1:
        lines.append("nothing in the libraries fits (call sync_ecc to download them)")
    lines.append("Load an agent with load_ecc_agent(name) or a skill with load_ecc_skill(name) and follow it.")
    return "\n".join(lines)
