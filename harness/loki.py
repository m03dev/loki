import sys

sys.stdout.reconfigure(encoding="utf-8")  # so emoji don't crash the Windows console

import ast
import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

ROOT = Path(__file__).parent

# --- configuration (override with environment variables) --------------------
# GAME_PROJECT  : path to the Godot game project the agent should work on.
# LOKI_WORKSPACE : the folder the file tools are allowed to touch (defaults
#                     to GAME_PROJECT if set, else ./workspace).
# GODOT_EXE     : path to the Godot executable.
GAME_PROJECT = os.getenv("GAME_PROJECT", "")
WORKSPACE = Path(
    os.getenv("LOKI_WORKSPACE")
    or os.getenv("HARNESS_WORKSPACE")  # legacy name, still honoured
    or GAME_PROJECT
    or str(ROOT / "workspace")
)
GODOT_EXE = os.getenv("GODOT_EXE", "G:/Godot_v4.8-dev7_win64.exe/Godot_v4.8-dev7_win64.exe")

MEMORY_FILE = ROOT / "memory.md"
PLAN_FILE = ROOT / "plan.md"
MCP_CONFIG = ROOT / "mcp_servers.json"

# LOKI_AUTO_APPROVE=1 runs dangerous tools without asking (for unattended runs).
AUTO_APPROVE = (os.getenv("LOKI_AUTO_APPROVE") or os.getenv("HARNESS_AUTO_APPROVE", "")) == "1"

MAX_OUTPUT = 8000   # characters of command output handed back to the model
GOAL_STEPS = 0      # 0 = run a goal until it says DONE/BLOCKED (no step limit)
MAX_TURNS_PER_REQUEST = int(os.getenv("LOKI_MAX_TURNS", "0"))       # model<->tool cycles per request (0 = UNLIMITED)
REQUEST_DEADLINE_S = float(os.getenv("LOKI_REQUEST_DEADLINE", "0"))    # wall-clock seconds per request (0 = no deadline)

# Transient model failures (429 rate limits, 5xx, dropped connections) are retried
# with exponential backoff instead of killing the whole task.
MODEL_RETRIES = int(os.getenv("LOKI_MODEL_RETRIES", "4"))
RETRY_BASE_S = float(os.getenv("LOKI_RETRY_BASE_S", "1.5"))
RETRY_MAX_S = float(os.getenv("LOKI_RETRY_MAX_S", "20"))
MAX_CONTEXT_MESSAGES = int(os.getenv("LOKI_MAX_CONTEXT", "0"))      # context window (0 = keep everything)


# ---------------------------------------------------------------------------
# Pillar: the model registry. Every entry is an OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Load KEY=VALUE pairs from harness/.env so users can store API keys."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_env_file()


class ModelConfig(BaseModel):
    base_url: str
    api_key: str = "none"
    model: str


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import godot_tools  # noqa: E402  (Godot API + project editing tools)

godot_tools.ROOT = ROOT
godot_tools.WORKSPACE = WORKSPACE


MODELS = {
    # Offline default. qwen3:8b is the ONLY local model verified to emit real
    # structured tool_calls through Ollama; qwen2.5-coder only *writes* the call
    # as JSON text, so it cannot drive the agent. Ollama: `ollama pull qwen3:8b`.
    # SMART: automatically use the best available free provider (see SMART_ORDER).
    "smart": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:8b"),
    "local": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:8b"),
    "local-small": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:8b"),
    "local-coder": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen2.5-coder:7b"),
    # Second verified offline tool-caller that fits 8 GB. Hermes is tool-focused with no
    # long hidden-reasoning phase, so it can be steadier on long agent loops.
    "local-hermes": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="hermes3:8b"),
    "local-reasoning": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3.5:9b"),
    "gpt": ModelConfig(base_url="https://api.openai.com/v1", api_key=os.getenv("OPENAI_API_KEY", ""), model="gpt-5.2"),
    "claude": ModelConfig(base_url="https://api.anthropic.com/v1/", api_key=os.getenv("ANTHROPIC_API_KEY", ""), model="claude-sonnet-5"),
    # OmniRoute: local AI gateway (one OpenAI-compatible endpoint -> many providers,
    # free tiers and auto-fallback). Run it, set a provider key, then use LOKI_MODEL=omniroute.
    # Free tiers (put the key in harness/.env). OpenAI-compatible endpoints.
    "gemini": ModelConfig(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                          api_key=os.getenv("GEMINI_API_KEY", ""), model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash")),
    "groq": ModelConfig(base_url="https://api.groq.com/openai/v1",
                        api_key=os.getenv("GROQ_API_KEY", ""), model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")),
    "openrouter": ModelConfig(base_url="https://openrouter.ai/api/v1",
                              api_key=os.getenv("OPENROUTER_API_KEY", ""), model=os.getenv("OPENROUTER_MODEL", "poolside/laguna-s-2.1:free")),
    "cerebras": ModelConfig(base_url="https://api.cerebras.ai/v1",
                            api_key=os.getenv("CEREBRAS_API_KEY", ""), model=os.getenv("CEREBRAS_MODEL", "llama-3.3-70b")),
    "mistral": ModelConfig(base_url="https://api.mistral.ai/v1",
                           api_key=os.getenv("MISTRAL_API_KEY", ""), model=os.getenv("MISTRAL_MODEL", "mistral-large-latest")),
    "together": ModelConfig(base_url="https://api.together.xyz/v1",
                            api_key=os.getenv("TOGETHER_API_KEY", ""), model=os.getenv("TOGETHER_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free")),
    "deepseek": ModelConfig(base_url="https://api.deepseek.com/v1",
                            api_key=os.getenv("DEEPSEEK_API_KEY", ""), model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat")),
    # Vireonix: OpenAI-compatible, needs NO key, NO account and NO card, and mixes
    # MiniMax/Nemotron/GLM/Qwen/GPT-OSS behind "auto". 20M input tokens/hour, 1M
    # context. This is the "nothing to set up at all" option - note that prompts
    # and file contents are sent to a third-party service.
    "vireonix": ModelConfig(base_url=os.getenv("VIREONIX_BASE_URL", "https://vireonix.ai/v1"),
                            api_key=os.getenv("VIREONIX_API_KEY", "vireonix"),
                            model=os.getenv("VIREONIX_MODEL", "auto")),
    # GitHub Models - free with a GitHub personal access token (models.github.ai).
    "github": ModelConfig(base_url=os.getenv("GITHUB_MODELS_URL", "https://models.github.ai/inference"),
                          api_key=os.getenv("GITHUB_TOKEN", ""),
                          model=os.getenv("GITHUB_MODEL", "openai/gpt-4o")),
    "omniroute": ModelConfig(
        base_url=os.getenv("OMNIROUTE_BASE_URL", "http://localhost:20128/v1"),
        api_key=os.getenv("OMNIROUTE_API_KEY", "omniroute"),
        model=os.getenv("OMNIROUTE_MODEL", "auto"),
    ),
}

model_name = os.getenv("LOKI_MODEL", "local")

# --- Smart mode -------------------------------------------------------------
# "smart" picks the best available FREE provider on its own: the first in this
# order that has a key configured (or a reachable Ollama), and it falls back to
# the next one whenever a provider fails, so the user never chooses.
# Ordered most-suitable-first for a big agent prompt. Gemini leads because its free
# tier allows 1M input tokens/min; Groq's free tier caps at 7k/min and returns 413
# on Loki's ~8k-token request, so it sits lower.
SMART_ORDER = ("gemini", "cerebras", "groq", "openrouter", "github", "mistral",
               "deepseek", "together", "vireonix", "local", "local-hermes")
_SMART_FAILED = set()


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def provider_configured(name: str) -> bool:
    cfg = MODELS.get(name)
    if cfg is None:
        return False
    if "11434" in cfg.base_url:
        return _ollama_reachable()
    return bool(str(cfg.api_key or "").strip())


def active_model_name() -> str:
    """The provider actually in use - SMART resolves to the best available."""
    if model_name != "smart":
        return model_name
    for candidate in SMART_ORDER:
        if candidate not in _SMART_FAILED and provider_configured(candidate):
            return candidate
    return "local"


def smart_report() -> str:
    marks = []
    for candidate in SMART_ORDER:
        state = "used-up" if candidate in _SMART_FAILED else ("ready" if provider_configured(candidate) else "-")
        marks.append("%s=%s" % (candidate, state))
    return "smart uses %s | %s" % (active_model_name(), ", ".join(marks))


def _mark_smart_failure() -> None:
    if model_name == "smart":
        _SMART_FAILED.add(active_model_name())


# ---------------------------------------------------------------------------
# Memory and the plan: two markdown files in the prompt + tools to edit them.
# ---------------------------------------------------------------------------

def load_memory() -> str:
    if MEMORY_FILE.is_file():
        return MEMORY_FILE.read_text(encoding="utf-8")
    return "(nothing saved yet)"


def save_memory(fact: str) -> str:
    with MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- {fact}\n")
    refresh_system_prompt()  # take effect this session, not next restart
    return f"saved: {fact}"


def todo_list() -> str:
    if not PLAN_FILE.is_file():
        return "(no plan yet - use todo_add to start one)"
    text = PLAN_FILE.read_text(encoding="utf-8").strip()
    return text or "(empty plan)"


def todo_clear() -> str:
    if PLAN_FILE.is_file():
        PLAN_FILE.unlink()
    return "plan cleared"


def todo_add(item: str) -> str:
    with PLAN_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- [ ] {item}\n")
    return f"added to plan: {item}"


def todo_done(index: int) -> str:
    if not PLAN_FILE.is_file():
        return "error: no plan yet"
    lines = PLAN_FILE.read_text(encoding="utf-8").splitlines()
    seen = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("- [ ]"):
            seen += 1
            if seen == index:
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                PLAN_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return f"done: {line.strip()[6:].strip()}"
    return f"error: no open plan item number {index}"


# ---------------------------------------------------------------------------
# Sandbox: every file tool resolves inside WORKSPACE, so a stray '../../'
# cannot read or overwrite the rest of the disk.
# ---------------------------------------------------------------------------

def resolve_in_workspace(name: str) -> Path:
    # Models sometimes wrap paths in quotes or add a res:// prefix.
    cleaned = str(name).strip().strip('"').strip("'").strip()
    for prefix in ("res://", "res:/", "./"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    path = (WORKSPACE / cleaned).resolve()
    if path != WORKSPACE.resolve() and WORKSPACE.resolve() not in path.parents:
        raise ValueError(f"path escapes workspace: {name}")
    return path


# ---------------------------------------------------------------------------
# Local tools: read the code, edit it precisely, search it, run it, verify it.
# ---------------------------------------------------------------------------

def list_files() -> str:
    return "\n".join(p.name for p in WORKSPACE.iterdir()) or "(empty)"


def list_tree(subdir: str = ".", max_depth: int = 3) -> str:
    base = resolve_in_workspace(subdir)
    lines = []

    def walk(d: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        for e in sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if e.name in (".git", "__pycache__", ".venv", ".godot", "node_modules"):
                continue
            lines.append(prefix + e.name + ("/" if e.is_dir() else ""))
            if e.is_dir():
                walk(e, prefix + "   ", depth + 1)

    walk(base, "", 1)
    return "\n".join(lines) if lines else "(empty)"


def read_file(filename: str) -> str:
    path = resolve_in_workspace(filename)
    return path.read_text(encoding="utf-8") if path.is_file() else f"error: no {filename}"


def write_file(filename: str, content: str) -> str:
    path = resolve_in_workspace(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    note = chr(10) + check_script(filename) if str(filename).endswith(".gd") else ""
    return f"wrote {filename}{note}"


def append_file(filename: str, content: str) -> str:
    path = resolve_in_workspace(filename)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)
    return f"appended to {filename}"


def edit_file(filename: str, old: str, new: str) -> str:
    path = resolve_in_workspace(filename)
    if not path.is_file():
        return f"error: no {filename}"
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return f"error: that exact text was not found in {filename}"
    path.write_text(text.replace(old, new), encoding="utf-8")
    note = chr(10) + check_script(filename) if str(filename).endswith(".gd") else ""
    return f"edited {filename} ({count} replacement(s)){note}"


def search_files(pattern: str, subdir: str = ".", glob: str = "*") -> str:
    base = resolve_in_workspace(subdir)
    rx = re.compile(pattern)
    hits = []
    for path in sorted(base.rglob(glob)):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                rel = path.relative_to(WORKSPACE)
                hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                if len(hits) >= 200:
                    hits.append("...[truncated at 200 matches]")
                    return "\n".join(hits)
    return "\n".join(hits) if hits else "(no matches)"


def make_dir(path: str) -> str:
    resolve_in_workspace(path).mkdir(parents=True, exist_ok=True)
    return f"created {path}"


def move_file(src: str, dst: str) -> str:
    s = resolve_in_workspace(src)
    d = resolve_in_workspace(dst)
    if not s.exists():
        return f"error: no {src}"
    d.parent.mkdir(parents=True, exist_ok=True)
    s.replace(d)
    return f"moved {src} -> {dst}"


def delete_file(path: str) -> str:
    p = resolve_in_workspace(path)
    if not p.exists():
        return f"error: no {path}"
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return f"deleted {path}"


def _pad(values, *defaults):
    values = list(values or [])
    while len(values) < len(defaults):
        values.append(defaults[len(values)])
    return values


def _v3(values) -> str:
    a = _pad(values, 0, 0, 0)
    return f"{float(a[0])}, {float(a[1])}, {float(a[2])}"


def _color(values) -> str:
    c = _pad(values, 0.8, 0.8, 0.8, 1.0)
    return f"Color({float(c[0])}, {float(c[1])}, {float(c[2])}, {float(c[3])})"


_PRIMITIVES = {
    "box": ("BoxMesh", lambda o: ["size = Vector3(%s)" % _v3(_pad(o.get("size"), 1, 1, 1))]),
    "sphere": ("SphereMesh", lambda o: [
        "radius = %s" % float(o.get("radius", 0.5)),
        "height = %s" % (float(o.get("radius", 0.5)) * 2)]),
    "cylinder": ("CylinderMesh", lambda o: [
        "top_radius = %s" % float(o.get("radius", 0.5)),
        "bottom_radius = %s" % float(o.get("radius", 0.5)),
        "height = %s" % float(o.get("height", 2.0))]),
    "capsule": ("CapsuleMesh", lambda o: [
        "radius = %s" % float(o.get("radius", 0.5)),
        "height = %s" % float(o.get("height", 2.0))]),
    "plane": ("PlaneMesh", lambda o: ["size = Vector2(%s, %s)" % (
        float(_pad(o.get("size"), 10, 10)[0]), float(_pad(o.get("size"), 10, 10)[1]))]),
    "torus": ("TorusMesh", lambda o: [
        "inner_radius = %s" % float(o.get("inner_radius", 0.5)),
        "outer_radius = %s" % float(o.get("outer_radius", 1.0))]),
}


def open_in_editor(path: str, run: bool = False) -> str:
    """Ask the running Godot editor to open (and optionally run) a scene.

    Writes a line to <project>/.godot/loki_editor_ops.jsonl, which the Loki dock
    polls inside the editor. This is how file-based work becomes visible on screen.
    """
    if not path.startswith("res://"):
        path = "res://" + path.lstrip("/")
    ops = WORKSPACE / ".godot" / "loki_editor_ops.jsonl"
    ops.parent.mkdir(parents=True, exist_ok=True)
    payload = {"id": int(time.time() * 1000), "op": "open_scene", "path": path, "run": bool(run)}
    ops.write_text(json.dumps(payload) + chr(10), encoding="utf-8")
    return "asked the editor to open %s" % path


def _loads_lenient(text):
    """Parse model-supplied JSON, also accepting Python-style literals.

    Models very often emit single quotes, True/False/None and trailing commas.
    json.loads rejects those; Python's literal_eval accepts them.
    """
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError):
        return None


def build_3d_scene(filename: str, objects: str, camera: bool = True, light: bool = True) -> str:
    """Write a guaranteed-valid Godot 4 .tscn of primitive meshes, then verify it.

    objects is a JSON array like [{"type":"box","name":"Box","pos":[0,1,0],
    "size":[1,1,1],"color":[0.8,0.2,0.2]}]. Types: box, sphere, cylinder,
    capsule, plane, torus. Exists so the model never hand-writes .tscn text.
    """
    spec = objects
    if isinstance(objects, str):
        spec = _loads_lenient(objects)
        if spec is None:
            return ('error: objects is not a valid JSON array. Pass a JSON string like '
                    '[{"type":"box","name":"Box","pos":[0,1,0],"size":[1,1,1]}] '
                    'with double quotes. Supported types: %s.' % ", ".join(_PRIMITIVES))
    if isinstance(spec, dict):
        spec = spec.get("objects", spec)
    if not isinstance(spec, list) or not spec:
        return "error: objects must be a non-empty JSON array of {type,name,pos,size,color}"
    if not filename.endswith(".tscn"):
        filename += ".tscn"
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")

    subs = []
    blocks = []
    root_name = "Scene3D"
    for index, obj in enumerate(spec, 1):
        if not isinstance(obj, dict):
            return "error: object %d is not a JSON object" % index
        kind = str(obj.get("type", "box")).lower()
        if kind not in _PRIMITIVES:
            return ("error: unknown primitive '%s'. build_3d_scene can only make %s. "
                    "It cannot add scripts, collision shapes, spring arms or node hierarchies - "
                    "for a scene like that, author the .tscn with write_file and prove it with "
                    "validate_scene." % (kind, ", ".join(_PRIMITIVES)))
        if index == 1:
            root_name = re.sub(r"[^A-Za-z0-9_]", "_", str(obj.get("root") or "Scene3D"))
        mesh_type, prop_fn = _PRIMITIVES[kind]
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(obj.get("name") or (kind.capitalize() + str(index))))
        mesh_id = "Mesh_" + name
        mat_id = "Mat_" + name
        subs.append((mesh_id, mesh_type, prop_fn(obj)))
        subs.append((mat_id, "StandardMaterial3D", ["albedo_color = %s" % _color(obj.get("color"))]))
        blocks.append((name, "MeshInstance3D", ".", [
            'mesh = SubResource("%s")' % mesh_id,
            'material_override = SubResource("%s")' % mat_id,
            "transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, %s)" % _v3(obj.get("pos"))]))

    if camera:
        blocks.insert(0, ("Camera3D", "Camera3D", ".",
                          ["transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 4, 10)"]))
    if light:
        blocks.insert(0, ("DirectionalLight3D", "DirectionalLight3D", ".",
                          ["transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 8, 4)"]))

    lines = ["[gd_scene load_steps=%d format=3]" % (len(subs) + 1), ""]
    for sid, stype, props in subs:
        lines.append('[sub_resource type="%s" id="%s"]' % (stype, sid))
        lines.extend(props)
        lines.append("")
    lines.append('[node name="%s" type="Node3D"]' % root_name)
    lines.append("")
    for name, ntype, parent, props in blocks:
        lines.append('[node name="%s" type="%s" parent="%s"]' % (name, ntype, parent))
        lines.extend(props)
        lines.append("")
    lines.append("")

    path = resolve_in_workspace(filename[len("res://"):])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")
    check = validate_scene(filename)
    opened = open_in_editor(filename)
    return "wrote %s (%d primitives)%s%s%s%s" % (filename, len(spec), chr(10), check, chr(10), opened)


_SCENE_MESH = {"box": "BoxMesh", "sphere": "SphereMesh", "cylinder": "CylinderMesh",
               "capsule": "CapsuleMesh", "plane": "PlaneMesh", "torus": "TorusMesh"}
_SCENE_SHAPE = {"box": "BoxShape3D", "sphere": "SphereShape3D", "cylinder": "CylinderShape3D",
                "capsule": "CapsuleShape3D", "plane": "WorldBoundaryShape3D"}


def _gd_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return "Vector3(%s, %s, %s)" % (float(value[0]), float(value[1]), float(value[2]))
    if value is None:
        return "null"
    return '"' + str(value).replace('"', "") + '"'


def _vec3(value, default=(0.0, 0.0, 0.0)):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return "Vector3(%s, %s, %s)" % (float(value[0]), float(value[1]), float(value[2]))
    return "Vector3(%s, %s, %s)" % (float(default[0]), float(default[1]), float(default[2]))


def build_scene(filename: str, nodes, light: bool = True, camera: bool = False) -> str:
    """Create AND verify a Godot 4 scene from a NODE TREE - use this for anything
    richer than primitives: players, cameras, collision shapes, scripts, instancing.

    nodes is a JSON array, one object per node, parents BEFORE children:
      {"name": "Player", "type": "CharacterBody3D", "parent": ".",
       "script": "res://scripts/player.gd", "pos": [0, 2, 0],
       "shape": "capsule", "mesh": "capsule", "props": {"current": true}}
      {"name": "PlayerInstance", "parent": ".", "instance": "res://scenes/player.tscn"}
    Keys: name, type, parent, script, instance, pos (or position), rot (degrees),
    scale, shape, mesh, and props (any extra Godot property -> value).
    Node types: Node3D, Node, CharacterBody3D, StaticBody3D, RigidBody3D, Area3D,
    Camera3D, SpringArm3D, MeshInstance3D, CollisionShape3D, DirectionalLight3D,
    OmniLight3D, Marker3D, RayCast3D, WorldEnvironment, CanvasLayer, Control.
    shape/mesh values: box, sphere, cylinder, capsule, plane, torus.
    """
    NL = chr(10)
    spec = nodes
    if isinstance(nodes, str):
        spec = _loads_lenient(nodes)
    if isinstance(spec, dict):
        spec = spec.get("nodes", spec.get("objects", spec))
    if not isinstance(spec, list) or not spec:
        return ('error: nodes must be a non-empty JSON array of node specs, e.g. '
                '[{"name":"Player","type":"CharacterBody3D","parent":"."}]')
    if not filename.endswith(".tscn"):
        filename += ".tscn"
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")

    ext, sub, blocks, counts = [], [], [], {}

    def next_id(kind):
        counts[kind] = counts.get(kind, 0) + 1
        return "%s_%d" % (kind, counts[kind])

    for index, node in enumerate(spec):
        if not isinstance(node, dict):
            return "error: node %d is not a JSON object" % (index + 1)
        ntype = str(node.get("type") or "Node3D")
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(node.get("name") or (ntype + str(index + 1))))
        head_parent = "" if index == 0 else ' parent="%s"' % str(node.get("parent", "."))
        if node.get("instance"):
            rid = next_id("scene")
            ext.append((rid, "PackedScene", str(node["instance"])))
            blocks.append('[node name="%s"%s instance=ExtResource("%s")]' % (name, head_parent, rid))
            continue
        lines = []
        if node.get("script"):
            sid = next_id("script")
            ext.append((sid, "Script", str(node["script"])))
            lines.append('script = ExtResource("%s")' % sid)
        if node.get("shape"):
            key = str(node["shape"]).lower()
            if key not in _SCENE_SHAPE:
                return "error: unknown shape '%s' (use %s)" % (node["shape"], ", ".join(_SCENE_SHAPE))
            sub_id = next_id("shape")
            shape_lines = []
            if "radius" in node:
                shape_lines.append("radius = %s" % float(node["radius"]))
            if "height" in node:
                shape_lines.append("height = %s" % float(node["height"]))
            if isinstance(node.get("size"), (list, tuple)) and len(node["size"]) == 3:
                shape_lines.append("size = %s" % _vec3(node["size"], (1.0, 1.0, 1.0)))
            sub.append((sub_id, _SCENE_SHAPE[key], shape_lines))
            lines.append('shape = SubResource("%s")' % sub_id)
        if node.get("mesh"):
            key = str(node["mesh"]).lower()
            if key not in _SCENE_MESH:
                return "error: unknown mesh '%s' (use %s)" % (node["mesh"], ", ".join(_SCENE_MESH))
            sub_id = next_id("mesh")
            sub.append((sub_id, _SCENE_MESH[key], []))
            lines.append('mesh = SubResource("%s")' % sub_id)
        if node.get("pos") is not None or node.get("position") is not None:
            lines.append("position = " + _vec3(node.get("pos", node.get("position"))))
        rot = node.get("rot", node.get("rotation_degrees"))
        if isinstance(rot, (list, tuple)) and len(rot) == 3:
            lines.append("rotation_degrees = " + _vec3(rot))
        if isinstance(node.get("scale"), (list, tuple)) and len(node["scale"]) == 3:
            lines.append("scale = " + _vec3(node["scale"], (1.0, 1.0, 1.0)))
        props = node.get("props")
        if isinstance(props, dict):
            for key, value in props.items():
                lines.append("%s = %s" % (key, _gd_value(value)))
        block = '[node name="%s" type="%s"%s]' % (name, ntype, head_parent)
        if lines:
            block += NL + NL.join(lines)
        blocks.append(block)

    parts = ["[gd_scene load_steps=%d format=3]" % (len(ext) + len(sub) + 1)]
    for rid, rtype, path in ext:
        parts.append('[ext_resource type="%s" path="%s" id="%s"]' % (rtype, path, rid))
    for sid, stype, shape_lines in sub:
        body = (NL + NL.join(shape_lines)) if shape_lines else ""
        parts.append('[sub_resource type="%s" id="%s"]%s' % (stype, sid, body))
    parts.extend(blocks)
    text = (NL + NL).join(parts) + NL

    written = write_file(filename, text)
    checked = validate_scene(filename)
    return "build_scene: %s%s%s" % (written, NL, checked)


def validate_scene(filename: str, timeout: int = 90) -> str:
    """Run a scene headless and report whether Godot loaded it without errors."""
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")
    # run_godot uses shlex.split(posix=False), which keeps literal quotes,
    # so the res:// path must be passed unquoted here.
    res = run_godot("--headless --quit-after 1 " + filename, timeout=timeout)
    low = res.lower()
    bad = "error:" in low or "failed loading" in low or "parse error" in low
    verdict = "INVALID - fix these errors:" if bad else "valid - Godot loaded it cleanly."
    return chr(10).join(["validate_scene %s: %s" % (filename, verdict), res])


def _shorten(text: str) -> str:
    if len(text) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        return text[:half] + "\n...[output truncated]...\n" + text[-half:]
    return text


def check_script(filename: str) -> str:
    """Compile-check a GDScript file with Godot and report any parse errors."""
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")
    cmd = [GODOT_EXE, "--headless", "--path", GAME_PROJECT, "--check-only", "--script", filename]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return "check_script %s: timed out" % filename
    except Exception as exc:
        return "check_script %s: error %s" % (filename, exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    bad = ("Parse Error" in out) or ("Failed to load script" in out) or ("SCRIPT ERROR" in out)
    verdict = "ERRORS - fix these:" if bad else "compiles OK"
    return "check_script %s: %s%s%s" % (filename, verdict, chr(10), _shorten(out))


def play_scene(filename: str, seconds: int = 5) -> str:
    """Actually RUN a game scene headless for a few seconds and report errors/output.

    This is how to test a controller, shooting system, physics or any runtime
    behaviour for real instead of assuming it works.
    """
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")
    cmd = [GODOT_EXE, "--headless", "--path", GAME_PROJECT, filename]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            out, _ = proc.communicate(timeout=max(1, int(seconds)))
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
    except Exception as exc:
        return "error: %s" % exc
    out = (out or "").strip()
    errors = [line for line in out.splitlines()
              if "error" in line.lower() or "script error" in line.lower()]
    verdict = ("runtime errors found - FIX THESE:" if errors else "ran with no errors")
    return "play_scene %s (%ds): %s%s%s" % (filename, seconds, verdict, chr(10), _shorten(out))


def run_command(command: str, timeout: int = 120) -> str:
    try:
        proc = subprocess.run(command, shell=True, cwd=WORKSPACE,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"error: command timed out after {timeout}s"
    except Exception as e:
        return f"error: {e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return f"exit {proc.returncode}\n{_shorten(out)}" if out else f"exit {proc.returncode}"


def run_godot(args: str = "", project_path: str = "", timeout: int = 180) -> str:
    cmd = [GODOT_EXE]
    proj = project_path or GAME_PROJECT
    if proj:
        cmd += ["--path", proj]
    if args:
        cmd += shlex.split(args, posix=False)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"error: Godot timed out after {timeout}s"
    except Exception as e:
        return f"error: {e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return f"exit {proc.returncode}\n{_shorten(out)}" if out else f"exit {proc.returncode}"


def open_godot(project_path: str = "") -> str:
    # Launch the editor detached so it keeps running after this tool returns.
    args = [GODOT_EXE]
    if project_path:
        args += ["--path", project_path]
    args.append("-e")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **kwargs)
    except Exception as e:
        return f"error: could not launch Godot: {e}"
    where = f" for {project_path}" if project_path else ""
    return f"launched the Godot editor{where}"


ECC_DIR = ROOT / "vendor" / "ECC"
ECC_AGENTS_DIR = ECC_DIR / "agents"
ECC_SKILLS_DIR = ECC_DIR / "skills"


def list_ecc_agents() -> str:
    """List the specialised agents available from the vendored ECC repo."""
    if not ECC_AGENTS_DIR.is_dir():
        return "ECC agents not installed (vendor/ECC/agents missing)."
    names = sorted(p.stem for p in ECC_AGENTS_DIR.glob("*.md"))
    return "ECC agents (%d): %s" % (len(names), ", ".join(names))


def load_ecc_agent(name: str) -> str:
    """Return a specialised agent's instructions so you can follow them for the task."""
    target = ECC_AGENTS_DIR / (os.path.basename(str(name).strip()) + ".md")
    if not target.is_file():
        return "no such ECC agent: %s" % name
    return target.read_text(encoding="utf-8")[:12000]


def list_ecc_skills() -> str:
    """List the specialised skill packs available from the vendored ECC repo."""
    if not ECC_SKILLS_DIR.is_dir():
        return "ECC skills not installed (vendor/ECC/skills missing)."
    names = sorted(p.parent.name for p in ECC_SKILLS_DIR.glob("*/SKILL.md"))
    return "ECC skills (%d): %s" % (len(names), ", ".join(names))


def load_ecc_skill(name: str) -> str:
    """Return a skill's guidance so you can follow it for the task."""
    target = ECC_SKILLS_DIR / os.path.basename(str(name).strip()) / "SKILL.md"
    if not target.is_file():
        return "no such ECC skill: %s" % name
    return target.read_text(encoding="utf-8")[:12000]


def sync_ecc(force: bool = False) -> str:
    """Refresh the ECC agent/skill library from GitHub."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import ecc_sync
        report = ecc_sync.sync(force=bool(force))
        state = ecc_sync.installed()
    except Exception as e:
        return "error: could not sync ECC: %s" % e
    return "synced %s; %d agents, %d skills" % (report, state["agents"], state["skills"])


_CAPTURE_BOOTSTRAP = """extends SceneTree

var _frames := 20
var _target := ""

func _initialize() -> void:
    var args := OS.get_cmdline_user_args()
    if args.size() > 0:
        _target = args[0]
    if args.size() > 1:
        _frames = int(args[1])
    if _target.is_empty():
        print("LOKI_CAPTURE_ERROR: no scene given")
        quit(1)
        return
    var packed: PackedScene = load(_target)
    if packed == null:
        print("LOKI_CAPTURE_ERROR: cannot load " + _target)
        quit(1)
        return
    root.add_child(packed.instantiate())

func _process(_delta: float) -> bool:
    if _frames > 0:
        _frames -= 1
        return false
    var image: Image = root.get_texture().get_image()
    image.save_png("user://loki_capture.png")
    print("LOKI_CAPTURE_OK: " + ProjectSettings.globalize_path("user://loki_capture.png"))
    quit(0)
    return true
"""


def capture_scene(filename: str, frames: int = 20, timeout: int = 120) -> str:
    """Run a scene in a REAL window and save a PNG of the running frame.

    The agent is otherwise blind - it can build a scene but never see it. Pair
    this with view_image so it can look at its own work and fix what it sees.
    """
    project = GAME_PROJECT or str(WORKSPACE)
    bootstrap = Path(project) / "loki_capture_tmp.gd"
    scene = filename if filename.startswith("res://") else "res://" + filename.lstrip("/")
    try:
        bootstrap.write_text(_CAPTURE_BOOTSTRAP, encoding="utf-8")
    except OSError as exc:
        return "error: cannot stage the capture script in %s: %s" % (project, exc)
    try:
        proc = subprocess.run(
            [GODOT_EXE, "--path", project, "--resolution", "1152x648",
             "--script", "res://loki_capture_tmp.gd", "--", scene, str(int(frames))],
            capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return "error: capture timed out after %ds - the scene probably never finishes loading" % timeout
    except Exception as exc:
        return "error: %s" % exc
    finally:
        try:
            bootstrap.unlink()
        except OSError:
            pass
    for line in out.splitlines():
        if line.startswith("LOKI_CAPTURE_OK: "):
            path = line.split(": ", 1)[1].strip()
            extra = ""
            try:
                extra = " (%d bytes)" % os.path.getsize(path)
            except OSError:
                pass
            return "captured %s -> %s%s. Inspect it with view_image." % (scene, path, extra)
    problems = [l.strip() for l in out.splitlines() if "ERROR" in l][:8]
    return "capture failed for " + scene + chr(10) + (chr(10).join(problems) or out[-400:])


async def view_image(filename: str, question: str = "") -> str:
    """Send a PNG to the current model and get a description or critique back."""
    import base64
    path = Path(filename)
    if not path.is_absolute():
        path = (Path(GAME_PROJECT or str(WORKSPACE)) / filename.replace("res://", "")).resolve()
    if not path.is_file():
        return "error: no image at %s" % path
    size = path.stat().st_size
    if size > 6_000_000:
        return "error: image is %d bytes; too large to send" % size
    prompt = question or ("Describe exactly what is visible in this Godot game screenshot. "
                          "Then list anything that looks wrong: black or empty viewport, missing "
                          "meshes, the camera looking at nothing, objects floating or clipping.")
    payload = base64.b64encode(path.read_bytes()).decode()
    client = make_client()
    try:
        response = await client.chat.completions.create(
            model=MODELS[active_model_name()].model,
            max_tokens=int(os.getenv("LOKI_MAX_TOKENS", "8192")),
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + payload}}]}])
    except Exception as exc:
        detail = str(exc)[:160]
        low = detail.lower()
        if "429" in detail or "quota" in low or "resource_exhausted" in low or "rate limit" in low:
            return ("error: the vision provider is rate-limited or out of quota. Wait, or let Smart "
                    "pick another provider. Details: " + detail)
        return ("error: vision request failed - the current provider may not accept images; use a "
                "vision-capable one such as gemini. Details: " + detail)
    text = str(response.choices[0].message.content or "").strip()
    return text or "(the model returned no description)"


LOCAL_TOOLS = {
    "list_files": list_files,
    "list_tree": list_tree,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "edit_file": edit_file,
    "search_files": search_files,
    "make_dir": make_dir,
    "move_file": move_file,
    "delete_file": delete_file,
    "run_command": run_command,
    "run_godot": run_godot,
    "open_godot": open_godot,
    "build_3d_scene": build_3d_scene,
    "build_scene": build_scene,
    "validate_scene": validate_scene,
    "play_scene": play_scene,
    "check_script": check_script,
    "capture_scene": capture_scene,
    "view_image": view_image,
    "godot_api": godot_tools.godot_api,
    "godot_search": godot_tools.godot_search,
    "read_scene": godot_tools.read_scene,
    "add_input_action": godot_tools.add_input_action,
    "set_project_setting": godot_tools.set_project_setting,
    "add_autoload": godot_tools.add_autoload,
    "list_ecc_agents": list_ecc_agents,
    "load_ecc_agent": load_ecc_agent,
    "list_ecc_skills": list_ecc_skills,
    "load_ecc_skill": load_ecc_skill,
    "sync_ecc": sync_ecc,
    "open_in_editor": open_in_editor,
    "todo_add": todo_add,
    "todo_list": todo_list,
    "todo_done": todo_done,
    "save_memory": save_memory,
}

# Tools that change files on disk (used to verify a task really did work).
MODIFYING = {"write_file", "append_file", "edit_file", "build_3d_scene", "move_file", "delete_file", "make_dir"}

# Tools that touch the system ask for a yes/no first, unless AUTO_APPROVE is on.
DANGEROUS = {"run_command", "open_godot", "move_file", "delete_file"}


def schema(name, description, properties=None, required=None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        },
    }


TOOL_SCHEMAS = [
    schema("list_files", "List the files at the top of the game project."),
    schema("list_tree", "Show the project as a tree.",
           {"subdir": {"type": "string"}, "max_depth": {"type": "integer"}}),
    schema("read_file", "Read one file.", {"filename": {"type": "string"}}, ["filename"]),
    schema("write_file", "Write (overwrite) a file.",
           {"filename": {"type": "string"}, "content": {"type": "string"}}, ["filename", "content"]),
    schema("append_file", "Append text to the end of a file.",
           {"filename": {"type": "string"}, "content": {"type": "string"}}, ["filename", "content"]),
    schema("edit_file", "Replace an exact snippet of text in a file. Prefer this over rewriting a whole file.",
           {"filename": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
           ["filename", "old", "new"]),
    schema("search_files", "Search file contents with a regular expression, with line numbers.",
           {"pattern": {"type": "string"}, "subdir": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    schema("make_dir", "Create a directory (and parents).", {"path": {"type": "string"}}, ["path"]),
    schema("move_file", "Move or rename a file or directory.",
           {"src": {"type": "string"}, "dst": {"type": "string"}}, ["src", "dst"]),
    schema("delete_file", "Delete a file or directory.", {"path": {"type": "string"}}, ["path"]),
    schema("run_command", "Run a shell command and return its output (tests, git, etc.).",
           {"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"]),
    schema("run_godot", "Run the Godot engine with arguments and return its output. Use for headless import ('--headless --quit') and running scenes, then READ the output to catch errors.",
           {"args": {"type": "string"}, "project_path": {"type": "string"}, "timeout": {"type": "integer"}}),
    schema("open_godot", "Open the Godot editor (optionally for a project folder).",
           {"project_path": {"type": "string"}}),
    schema("build_3d_scene", 'Create AND verify a Godot 4 3D scene (.tscn) from primitive meshes. ALWAYS use this instead of hand-writing .tscn text. objects is a JSON array like [{"type": "box", "name": "Box", "pos": [0, 1, 0], "size": [1, 1, 1], "color": [0.8, 0.2, 0.2]}]. Types: box, sphere, cylinder, capsule, plane, torus.',
           {"filename": {"type": "string"}, "objects": {"type": "string"}, "camera": {"type": "boolean"}, "light": {"type": "boolean"}}, ["filename", "objects"]),
    schema("play_scene", "Run a game scene headless for a few seconds to test runtime behaviour (controller, shooting, physics) and report errors and printed output. Use this to verify work actually functions.",
           {"filename": {"type": "string"}, "seconds": {"type": "integer"}}, ["filename"]),
    schema("capture_scene", "Run a scene in a real window and save a screenshot of the running frame. Use this to SEE what your scene actually looks like, then view_image to inspect the picture.",
           {"filename": {"type": "string"}, "frames": {"type": "integer"}}, ["filename"]),
    schema("view_image", "Send a screenshot (or any PNG) to the model and get back a description and a list of visual problems. Use it after capture_scene to check your own work.",
           {"filename": {"type": "string"}, "question": {"type": "string"}}, ["filename"]),
    schema("list_ecc_agents", "List the specialised coding agents available (planning, review, security, build repair, etc.)."),
    schema("load_ecc_agent", "Load a specialised agent's instructions and follow them for the task.",
           {"name": {"type": "string"}}, ["name"]),
    schema("list_ecc_skills", "List the specialised skill packs available (TDD, security, frontend, data, ML, operations, ...)."),
    schema("load_ecc_skill", "Load a skill's guidance and follow it for the task.",
           {"name": {"type": "string"}}, ["name"]),
    schema("sync_ecc", "Refresh the ECC agent/skill library from GitHub. Use when the library is missing or stale.",
           {"force": {"type": "boolean"}}),
    schema("godot_api", "Look up the REAL Godot 4 API before calling a Godot method you are unsure about - never guess a method name. name is a class like InputMap or CharacterBody3D, or Class.member for one exact signature.", {"name": {"type": "string"}, "member": {"type": "string"}}, ["name"]),
    schema("godot_search", "Search the Godot API by keyword to find the right class or method name (e.g. input action, raycast).", {"query": {"type": "string"}}, ["query"]),
    schema("read_scene", "Show the node tree of a .tscn - names, types, attached scripts, instanced scenes - before editing it.", {"filename": {"type": "string"}}, ["filename"]),
    schema("add_input_action", "Register an input action in project.godot so scripts can use Input.is_action_pressed(name). keys is a comma-separated list such as W,Up or Space or mouse_left.", {"name": {"type": "string"}, "keys": {"type": "string"}, "deadzone": {"type": "number"}}, ["name", "keys"]),
    schema("set_project_setting", "Set a project.godot setting using section/key form, e.g. display/window/size/viewport_width = 1280.", {"name": {"type": "string"}, "value": {"type": "string"}}, ["name", "value"]),
    schema("add_autoload", "Register an autoload singleton, e.g. add_autoload with GameState and res://scripts/game_state.gd.", {"name": {"type": "string"}, "path": {"type": "string"}}, ["name", "path"]),
    schema("build_scene", "Create AND verify a Godot scene from a node tree (any node type: players, cameras, collision shapes, scripts, instancing). Prefer this over build_3d_scene for anything richer than primitives, and over hand-writing .tscn.", {"filename": {"type": "string"}, "nodes": {"type": "string"}, "light": {"type": "boolean"}, "camera": {"type": "boolean"}}, ["filename", "nodes"]),
    schema("check_script", "Compile-check a GDScript file with Godot and report parse errors. Use after writing or editing a .gd file.",
           {"filename": {"type": "string"}}, ["filename"]),
    schema("validate_scene", "Load a scene headless and report whether Godot loads it cleanly.",
           {"filename": {"type": "string"}}, ["filename"]),
    schema("open_in_editor", "Open a scene in the running Godot editor (and optionally run it) so the user sees it. Call this after creating or changing a scene.",
           {"path": {"type": "string"}, "run": {"type": "boolean"}}, ["path"]),
    schema("todo_add", "Add a step to the persistent plan.", {"item": {"type": "string"}}, ["item"]),
    schema("todo_list", "Show the persistent plan."),
    schema("todo_done", "Mark plan item N (1-based) as done.", {"index": {"type": "integer"}}, ["index"]),
    schema("save_memory", "Save one short lasting fact about the user.", {"fact": {"type": "string"}}, ["fact"]),
]


# The tools actually offered to the model. run_command/open_godot are deliberately
# excluded: they are dangerous (approval prompts) and a small model misuses them
# (e.g. unix "ls -R" on Windows), which stalls the whole task.
MODEL_TOOL_NAMES = {
    "list_ecc_agents", "load_ecc_agent", "list_ecc_skills", "load_ecc_skill", "sync_ecc",
    "godot_api", "godot_search", "read_scene", "add_input_action",
    "set_project_setting", "add_autoload",
    "list_files", "list_tree", "read_file", "write_file", "append_file",
    "edit_file", "search_files", "make_dir", "move_file", "delete_file",
    "build_3d_scene", "build_scene", "validate_scene", "play_scene", "open_in_editor",
    "check_script", "capture_scene", "view_image",
}
MODEL_TOOL_SCHEMAS = [t for t in TOOL_SCHEMAS if t["function"]["name"] in MODEL_TOOL_NAMES]



# --- tool categories (toggleable from the editor Settings dialog) ------------
TOOL_CATEGORIES = {
    "files": ["list_files", "list_tree", "read_file", "write_file", "append_file",
              "edit_file", "search_files", "make_dir", "move_file", "delete_file"],
    "scenes": ["build_3d_scene", "build_scene", "validate_scene", "read_scene", "open_in_editor"],
    "godot": ["godot_api", "godot_search"],
    "project": ["add_input_action", "set_project_setting", "add_autoload"],
    "runtime": ["play_scene", "check_script", "capture_scene", "view_image"],
    "planning": ["todo_add", "todo_list", "todo_done"],
    "memory": ["save_memory"],
    "skills": ["list_ecc_agents", "load_ecc_agent", "list_ecc_skills", "load_ecc_skill", "sync_ecc"],
    "system": ["run_command", "run_godot", "open_godot"],
}
CATEGORY_LABELS = {
    "files": "Files (read/write/edit/search)",
    "scenes": "Scenes (build/validate/open in editor)",
    "runtime": "Runtime checks (run scene, compile script)",
    "planning": "Planning (todo list)",
    "memory": "Memory (save facts)",
    "skills": "Skills (ECC agents and skills)",
    "godot": "Godot API reference (look up classes and methods)",
    "project": "Project setup (input actions, settings, autoloads)",
    "system": "System (shell commands, launch Godot) - dangerous",
    "runtime": "Runtime checks (run scene, compile script, screenshot + look)",
}
SETTINGS_FILE = ROOT / "loki_settings.json"


def _load_settings() -> dict:
    defaults = {name: (name != "system") for name in TOOL_CATEGORIES}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for name, value in (data.get("categories") or {}).items():
            if name in defaults:
                defaults[name] = bool(value)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


CATEGORIES = _load_settings()


def save_settings() -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps({"categories": CATEGORIES}, indent=2), encoding="utf-8")
    except OSError:
        pass


def set_category(name: str, enabled: bool) -> bool:
    if name not in TOOL_CATEGORIES:
        return False
    CATEGORIES[name] = bool(enabled)
    save_settings()
    return True


def _tool_enabled(tool_name: str) -> bool:
    for category, members in TOOL_CATEGORIES.items():
        if tool_name in members:
            return CATEGORIES.get(category, True)
    return True


def model_tool_schemas() -> list:
    """The tool schemas to offer the model, filtered by enabled categories."""
    return [t for t in TOOL_SCHEMAS if t["function"]["name"] in MODEL_TOOL_NAMES
            and _tool_enabled(t["function"]["name"])]


def categories_state() -> dict:
    return {"categories": CATEGORIES, "labels": CATEGORY_LABELS}


SYSTEM_PROMPT = '''You are a SENIOR GAME DEVELOPER working autonomously in a Godot 4 project. You are practical, rigorous and concise.

The workspace folder is the game project. You can list, read, search, edit, create, move and delete files; run shell commands (run_command); run the Godot engine (run_godot); and open the Godot editor (open_godot).

To create or extend a 3D scene, ALWAYS use build_3d_scene - never hand-write .tscn text, you get it wrong. build_3d_scene writes the file and re-loads it in Godot for you, so only claim a scene works when its output says valid. Do NOT launch the editor (open_godot) unless the user asks.

Work like a professional, in this order - do not skip steps:
1. UNDERSTAND: use list_tree, search_files and read_file to learn the project structure, scenes (.tscn), scripts (.gd) and resources before you change anything.
2. PLAN: at most two todo_add items, only if genuinely useful. Do NOT pad the task with planning.
3. IMPLEMENT: every turn must produce a real artifact - a .tscn (use build_3d_scene), a .gd or .tres (use write_file). Creating folders or todo items is NOT progress. You are on Windows: never use 'mkdir -p', use make_dir. Write correct Godot 4 code: typed GDScript (class_name, type hints on vars, params and return types), signals, and valid .tscn/.tres text format.
4. VERIFY: after changes, check the scene with validate_scene or run the engine headless with run_godot and READ the output. Fix what breaks. A feature is not done until the engine runs it cleanly. If you cannot verify it, say so plainly.
5. ITERATE until the task is finished, then stop and summarise what you did.

Rules:
- You are EXECUTING, not chatting. Never ask the user a question, never ask for permission or confirmation, and never end a turn with only a plan or a summary of what you are about to do. Call the tool and do the work. If a detail is ambiguous, pick the most reasonable option and continue.
- Keep calling tools until the task is finished; a turn with no tool call is only acceptable when the task is genuinely done.
- Prefer the smallest change that works; never rewrite a whole file when edit_file will do.
- Do not create empty folders. Do not repeat a tool call that already succeeded.
- Never claim something works without running it and seeing the output.
- If you are blocked, reply 'BLOCKED: <what you need>'.

What you remember about the user from previous sessions:
{memory}

When you learn a new lasting fact about the user, save it with save_memory.'''


def _read_vendor(*parts: str) -> str:
    try:
        return (ROOT / "vendor").joinpath(*parts).read_text(encoding="utf-8")
    except OSError:
        return ""


# Ponytail: the "lazy senior dev" coding standard (github.com/DietrichGebert/ponytail).
# Braces escaped so SYSTEM_PROMPT.format() still works.
# LOKI_LEAN=1 trims the coding-standard block: free tiers (e.g. Groq at 7k
# input tokens/minute) reject the full agent request otherwise.
if os.getenv("LOKI_LEAN"):
    _PONYTAIL = ""
else:
    _PONYTAIL = _read_vendor("ponytail", "AGENTS.md").replace("{", "{{").replace("}", "}}")
if _PONYTAIL:
    SYSTEM_PROMPT += chr(10) * 2 + "# Coding standard - Ponytail (write the least code that works)" + chr(10) + _PONYTAIL

HISTORY_FILE = WORKSPACE / ".godot" / "loki_history.json"
CONVERSATIONS_FILE = WORKSPACE / ".godot" / "loki_conversations.json"


def _as_dict(message) -> dict:
    # JSON-safe chat message (OpenAI objects or plain dicts)
    if isinstance(message, dict):
        return message
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(message, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:
                continue
    return {"role": getattr(message, "role", "assistant"), "content": getattr(message, "content", "")}


def _sanitize_history(items: list) -> list:
    # keep only plain conversational turns
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant") or item.get("tool_calls"):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        head = content.strip().upper()
        if head.startswith("GOAL:") or head.startswith("DONE:") or head.startswith("BLOCKED:"):
            continue
        clean.append({"role": role, "content": content})
    return clean[-40:]


PROFILE: dict = {"name": "", "notes": ""}


def composed_memory() -> str:
    text = load_memory()
    lines = []
    if PROFILE.get("name"):
        lines.append("Preferred name: " + PROFILE["name"])
    if PROFILE.get("notes"):
        lines.append("User-provided profile/preferences: " + PROFILE["notes"])
    if lines:
        text += chr(10) * 2 + "Editable user profile:" + chr(10) + chr(10).join(lines)
    return text


def refresh_system_prompt() -> None:
    if messages:
        messages[0] = {"role": "system", "content": SYSTEM_PROMPT.format(memory=composed_memory())}


def set_profile(name: str, notes: str) -> None:
    PROFILE["name"] = (name or "").strip()[:100]
    PROFILE["notes"] = (notes or "").strip()[:4000]
    refresh_system_prompt()
    save_conversations()


def get_memory() -> str:
    return MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.is_file() else ""


def set_memory(text: str) -> str:
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text((text or "").strip() + chr(10), encoding="utf-8")
        refresh_system_prompt()
    except OSError as exc:
        return "could not save memory: %s" % exc
    return "memory saved"


CONVERSATIONS: dict = {}
active_conversation: str = ""


def _new_conversation(title: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:12],
            "title": (title or "New chat").strip()[:60] or "New chat",
            "created": time.time(), "updated": time.time(), "messages": []}


_TITLE_SKIP = ("You ended your turn", "is premature", "NO file was created", "(no output)",
               "the model stopped responding", "returned empty replies",
               "You have not used any tools", "You have now made this exact call")


def _is_internal_turn(text: str) -> bool:
    """True for Loki's own steering messages, which must never title a chat."""
    plain = (text or "").strip()
    return any(marker in plain for marker in _TITLE_SKIP)


def _first_real_user(turns: list) -> str:
    for turn in turns:
        if turn.get("role") == "user" and not _is_internal_turn(turn.get("content", "")):
            return turn.get("content", "")
    return ""


def _title_from_text(text: str) -> str:
    rows = (text or "").strip().splitlines()
    head = rows[0].strip() if rows else ""
    if len(head) > 48:
        head = head[:48] + chr(8230)
    return head or "New chat"


def list_conversations() -> list:
    ordered = sorted(CONVERSATIONS.values(), key=lambda c: c.get("updated", 0), reverse=True)
    return [{"id": c["id"], "title": c["title"], "updated": c["updated"], "count": len(c["messages"])}
            for c in ordered]


def active_conversation_id() -> str:
    return active_conversation


def conversation_messages(cid: str) -> list:
    convo = CONVERSATIONS.get(cid)
    if convo is None:
        return []
    return [{"role": m["role"], "content": m["content"]} for m in convo["messages"]
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]


def save_conversations() -> None:
    try:
        CONVERSATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active": active_conversation, "profile": PROFILE,
                   "conversations": list(CONVERSATIONS.values())}
        CONVERSATIONS_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def save_history() -> None:
    convo = CONVERSATIONS.get(active_conversation)
    if convo is None:
        return
    turns = _sanitize_history(messages)
    convo["messages"] = turns
    convo["updated"] = time.time()
    if convo["title"] in ("", "New chat") or _is_internal_turn(convo["title"]):
        first_user = _first_real_user(turns)
        if first_user:
            convo["title"] = _title_from_text(first_user)
    save_conversations()


def _activate(cid: str) -> None:
    global active_conversation
    active_conversation = cid
    messages[:] = [{"role": "system", "content": SYSTEM_PROMPT.format(memory=composed_memory())}]
    for item in CONVERSATIONS.get(cid, {}).get("messages", []):
        if item.get("role") in ("user", "assistant") and isinstance(item.get("content"), str):
            messages.append({"role": item["role"], "content": item["content"]})


def new_conversation(title: str = "") -> str:
    save_history()
    convo = _new_conversation(title)
    CONVERSATIONS[convo["id"]] = convo
    _activate(convo["id"])
    save_conversations()
    return convo["id"]


def switch_conversation(cid: str) -> bool:
    if cid not in CONVERSATIONS:
        return False
    if cid != active_conversation:
        save_history()
        _activate(cid)
        save_conversations()
    return True


def rename_conversation(cid: str, title: str) -> bool:
    convo = CONVERSATIONS.get(cid)
    if convo is None:
        return False
    convo["title"] = (title or "").strip()[:60] or convo["title"]
    convo["updated"] = time.time()
    save_conversations()
    return True


def delete_conversation(cid: str) -> bool:
    global active_conversation
    if cid not in CONVERSATIONS:
        return False
    was_active = cid == active_conversation
    del CONVERSATIONS[cid]
    if not CONVERSATIONS:
        convo = _new_conversation()
        CONVERSATIONS[convo["id"]] = convo
        _activate(convo["id"])
    elif was_active:
        newest = max(CONVERSATIONS.values(), key=lambda c: c.get("updated", 0))
        _activate(newest["id"])
    save_conversations()
    return True


def load_conversations() -> None:
    global active_conversation
    data = {}
    try:
        if CONVERSATIONS_FILE.is_file():
            data = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    saved_profile = data.get("profile")
    if isinstance(saved_profile, dict):
        PROFILE["name"] = str(saved_profile.get("name", ""))[:100]
        PROFILE["notes"] = str(saved_profile.get("notes", ""))[:4000]
    for convo in (data.get("conversations") or []):
        if isinstance(convo, dict) and convo.get("id"):
            convo.setdefault("title", "New chat")
            convo.setdefault("created", time.time())
            convo.setdefault("updated", convo.get("created", time.time()))
            convo["messages"] = [m for m in (convo.get("messages") or []) if isinstance(m, dict)][-40:]
            CONVERSATIONS[convo["id"]] = convo
    if not CONVERSATIONS:
        convo = _new_conversation()
        try:
            if HISTORY_FILE.is_file():
                old = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
                turns = _sanitize_history(old) if isinstance(old, list) else []
                convo["messages"] = turns
                if turns:
                    convo["title"] = _title_from_text(
                        next((t["content"] for t in turns if t["role"] == "user"), ""))
        except (OSError, json.JSONDecodeError):
            pass
        CONVERSATIONS[convo["id"]] = convo
    wanted = data.get("active", "")
    if wanted in CONVERSATIONS:
        active_conversation = wanted
    else:
        active_conversation = max(CONVERSATIONS.values(), key=lambda c: c.get("updated", 0))["id"]
    _activate(active_conversation)


def clear_active_conversation() -> None:
    convo = CONVERSATIONS.get(active_conversation)
    if convo is not None:
        convo["messages"] = []
        convo["updated"] = time.time()
    refresh_system_prompt()
    save_conversations()


messages = [{"role": "system", "content": SYSTEM_PROMPT.format(memory=composed_memory())}]
load_conversations()


# ---------------------------------------------------------------------------
# Pillar: MCP. Launch servers from mcp_servers.json and merge in their tools.
# ---------------------------------------------------------------------------

mcp_sessions = {}


async def connect_mcp(stack: AsyncExitStack) -> None:
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    for name, spec in config["mcpServers"].items():
        params = StdioServerParameters(command=spec["command"], args=spec["args"])
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as e:
            print(f"  [mcp] '{name}' failed to start: {e}")
            continue
        tools = (await session.list_tools()).tools
        for tool in tools:
            mcp_sessions[tool.name] = session
            TOOL_SCHEMAS.append(schema(tool.name, tool.description,
                                       tool.input_schema.get("properties", {}),
                                       tool.input_schema.get("required", [])))
        print(f"  [mcp] connected '{name}': {[t.name for t in tools]}")


async def approve(kind: str, detail: str) -> bool:
    if AUTO_APPROVE:
        print(f"  [auto-approved] {kind}: {detail}")
        return True
    answer = await asyncio.to_thread(input, f"  [approve] {kind}: {detail}\n  allow? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


# Models rarely use the exact parameter name from the schema (they say "path" for
# "filename", "text" for "content", ...). Accept the common synonyms so a reasonable
# call is not rejected outright.
_ARG_ALIASES = {
    "filename": ("path", "file", "filepath", "file_path", "name"),
    "path": ("filename", "file", "filepath", "file_path"),
    "content": ("text", "data", "body", "code", "contents"),
    "name": ("agent", "agent_name", "tool_name"),
    "command": ("cmd", "shell", "script"),
    "item": ("step", "task", "todo"),
    "objects": ("object", "primitives", "meshes"),
    "fact": ("memory", "note", "text"),
    "seconds": ("duration", "time", "timeout"),
    "args": ("arguments", "params", "command"),
}

_TOOL_REQUIRED = {
    entry["function"]["name"]: list(entry["function"].get("parameters", {}).get("required", []))
    for entry in TOOL_SCHEMAS
}


def _normalize_args(name: str, args: dict) -> dict:
    """Map a model's synonym argument names onto the tool's real parameters."""
    if not isinstance(args, dict):
        return args if isinstance(args, dict) else {}
    required = _TOOL_REQUIRED.get(name)
    if not required:
        return args
    out = dict(args)
    for canonical in required:
        if canonical in out:
            continue
        for alias in _ARG_ALIASES.get(canonical, ()):
            if alias in out:
                out[canonical] = out.pop(alias)
                break
    return out


async def call_tool(name: str, args: dict) -> str:
    args = _normalize_args(name, args)
    if name in LOCAL_TOOLS:
        if name in DANGEROUS and not await approve(name, json.dumps(args)[:400]):
            return ("DENIED: the user did not approve this tool. Do NOT request it again. "
                    "Make progress with file tools (build_3d_scene, write_file, edit_file, "
                    "play_scene, validate_scene) instead, or reply 'BLOCKED: <reason>'.")
        try:
            result = LOCAL_TOOLS[name](**args)
            if asyncio.iscoroutine(result):
                result = await result
            global _task_modified
            if name in MODIFYING:
                _task_modified = True
            return result
        except Exception as e:
            return f"error: {e}"
    if name in mcp_sessions:
        try:
            result = await mcp_sessions[name].call_tool(name, args)
            return "\n".join(c.text for c in result.content if hasattr(c, "text"))
        except Exception as e:
            return f"error: {e}"
    return f"error: unknown tool {name}"


# ---------------------------------------------------------------------------
# The agent loop: one turn = keep calling tools until the model stops asking.
# ---------------------------------------------------------------------------

class ModelUnavailable(Exception):
    """Raised when the model endpoint cannot be reached."""

    def __init__(self, hint: str) -> None:
        super().__init__(hint)
        self.hint = hint


def model_endpoint(cfg) -> str:
    from urllib.parse import urlparse
    return urlparse(cfg.base_url).netloc or cfg.base_url


def endpoint_reachable(base_url: str, timeout: float = 1.5) -> bool:
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def model_down_hint(cfg) -> str:
    where = model_endpoint(cfg)
    if "11434" in cfg.base_url or "ollama" in cfg.base_url.lower():
        return (
            f"[model unavailable] I cannot reach the model at {where}.\n"
            "  Ollama does not look like it is running. Start it, then retry:\n"
            "    1) launch the Ollama app, or run:  ollama serve\n"
            f"    2) make sure the model is pulled:  ollama pull {cfg.model}\n"
            "  Your prompt was not lost - press Up to resend, or type /status to check."
        )
    return (
        f"[model unavailable] I cannot reach the model at {where} ({cfg.model}).\n"
        "  Check that the endpoint is up and the API key is set, then retry. /status to check."
    )


def make_client() -> AsyncOpenAI:
    cfg = MODELS[active_model_name()]
    return AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key)


class BudgetExhausted(Exception):
    """A request stopped early because it hit a turn/time budget or was cancelled."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_cancel_event = threading.Event()
_empty_nudges = 0
_last_turn_had_tools = False
_repeat_sig = ""
_repeat_count = 0
_task_modified = False


def request_cancel() -> None:
    """Ask the in-flight request to stop at the next safe point."""
    _cancel_event.set()


def clear_cancel() -> None:
    _cancel_event.clear()


def _progress(event: str, text: str) -> None:
    """Report activity to whatever host set loki_progress_callback (the Godot dock)."""
    callback = globals().get("loki_progress_callback")
    if callback is not None:
        try:
            callback(event, text)
        except Exception:
            pass


def _trim_context() -> None:
    """Keep the system prompt plus a bounded window so context cannot overflow."""
    if MAX_CONTEXT_MESSAGES <= 0 or len(messages) <= MAX_CONTEXT_MESSAGES:
        return
    tail = messages[-MAX_CONTEXT_MESSAGES:]
    for index, item in enumerate(tail):
        if item.get("role") == "user":
            messages[:] = [messages[0]] + tail[index:]
            return
    messages[:] = [messages[0]] + tail


_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _retry_delay(attempt: int) -> float:
    """Exponential backoff, capped."""
    return min(RETRY_MAX_S, RETRY_BASE_S * (2 ** (attempt - 1)))


def _status_of(exc) -> int:
    status = getattr(exc, "status_code", None)
    return int(status) if isinstance(status, int) else 0


async def _model_request(client, kwargs: dict, cfg):
    """Ask the model, retrying transient failures so one 429 does not end the task."""
    attempt = 0
    while True:
        try:
            return await client.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            status = _status_of(exc)
            if "tool_choice" in kwargs and 400 <= status < 500:
                # Backend does not support tool_choice; retry unforced.
                kwargs.pop("tool_choice", None)
                continue
            if status in _TRANSIENT_STATUS and attempt < MODEL_RETRIES:
                attempt += 1
                delay = _retry_delay(attempt)
                _progress("thinking", "Model returned HTTP %s; retrying in %.1fs (attempt %d of %d)..." % (status, delay, attempt, MODEL_RETRIES))
                await asyncio.sleep(delay)
                continue
            _mark_smart_failure()
            raise ModelUnavailable(
                "[model error] %s answered HTTP %s: %s" % (cfg.model, status, exc.message)
            ) from exc
        except openai.APIConnectionError as exc:
            if attempt < MODEL_RETRIES:
                attempt += 1
                delay = _retry_delay(attempt)
                _progress("thinking", "Model connection failed; retrying in %.1fs (attempt %d of %d)..." % (delay, attempt, MODEL_RETRIES))
                await asyncio.sleep(delay)
                continue
            _mark_smart_failure()
            raise ModelUnavailable(model_down_hint(cfg)) from exc
        except openai.OpenAIError as exc:
            _mark_smart_failure()
            raise ModelUnavailable("[model error] %s: %s" % (type(exc).__name__, exc)) from exc


def _json_object_spans(text: str) -> list:
    """Every balanced {...} object in a string (handles nesting)."""
    spans, depth, start = [], 0, -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append(text[start:index + 1])
                    start = -1
    return spans


def _recover_text_tool_calls(content: str) -> list:
    """Recover tool calls a model wrote as TEXT instead of real tool_calls.

    Some models (e.g. qwen2.5-coder via Ollama) print
    {"name": "list_files", "arguments": {"path": "."}} into the message body and
    never emit a structured call, which used to stall the agent. Only names that
    match a real tool are accepted, so ordinary JSON in a reply is ignored.
    """
    if not content or "{" not in content or "name" not in content:
        return []
    known = set(LOCAL_TOOLS) | set(mcp_sessions)
    calls = []
    for blob in _json_object_spans(content):
        try:
            data = json.loads(blob)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("function"), dict):
            data = data["function"]
        name = data.get("name") or data.get("tool")
        if not isinstance(name, str) or name not in known:
            continue
        args = data.get("arguments", data.get("parameters", data.get("args", {})))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                args = {}
        calls.append((name, args if isinstance(args, dict) else {}))
    return calls


async def agent_turn(force_tool: bool = False) -> str:
    cfg = MODELS[active_model_name()]
    client = make_client()
    started = time.monotonic()
    turns = 0
    while True:
        if _cancel_event.is_set():
            raise BudgetExhausted("cancelled by the user")
        if REQUEST_DEADLINE_S > 0 and time.monotonic() - started > REQUEST_DEADLINE_S:
            raise BudgetExhausted("hit the %ds time budget" % int(REQUEST_DEADLINE_S))
        if MAX_TURNS_PER_REQUEST > 0 and turns >= MAX_TURNS_PER_REQUEST:
            raise BudgetExhausted("hit the %d-turn budget" % MAX_TURNS_PER_REQUEST)
        turns += 1
        _trim_context()
        _progress("thinking", "Turn %d: asking the model..." % turns)
        # Thinking models (Gemini 3.x) spend tokens reasoning before answering, so
        # give them headroom or the tool call gets truncated away.
        kwargs = {"model": cfg.model, "messages": messages, "tools": model_tool_schemas(),
                  "max_tokens": int(os.getenv("LOKI_MAX_TOKENS", "8192"))}
        if "11434" in cfg.base_url or "ollama" in cfg.api_key:
            # Qwen3 family: disable extended thinking so the model acts instead of
            # writing long reasoning prose that never calls a tool.
            kwargs["extra_body"] = {"think": False}
        if force_tool:
            kwargs["tool_choice"] = "required"
        response = await _model_request(client, kwargs, cfg)
        message = response.choices[0].message
        global _last_turn_had_tools
        _last_turn_had_tools = bool(message.tool_calls)
        if not message.tool_calls:
            content = message.content or ""
            if not content.strip():
                # Some local models finish a turn with only hidden reasoning; recover it.
                content = getattr(message, "reasoning", None) or ""
            recovered = _recover_text_tool_calls(content)
            if recovered:
                _progress("thinking", "Model wrote %d tool call(s) as text; running them." % len(recovered))
                messages.append({"role": "assistant", "content": content})
                notes = []
                for tool_name, tool_args in recovered[:4]:
                    print("  [tool:text] %s(%s)" % (tool_name, json.dumps(tool_args)[:200]))
                    tool_result = await call_tool(tool_name, tool_args)
                    notes.append("Result of %s(%s):\n%s" % (tool_name, json.dumps(tool_args)[:200], tool_result))
                messages.append({"role": "user", "content": "\n\n".join(notes)})
                _last_turn_had_tools = True
                continue
            if not content.strip():
                global _empty_nudges
                if _empty_nudges < 2:
                    _empty_nudges += 1
                    _progress("thinking", "Model returned an empty reply; asking it to continue...")
                    messages.append({"role": "assistant", "content": "(no output)"})
                    messages.append({"role": "user", "content": (
                        "You ended your turn without any message or tool call. Continue the task. "
                        "If it is finished, reply on its own line as 'DONE: <summary>'."
                    )})
                    continue
                content = "(the model stopped responding and gave no message; it may have stalled.)"
            messages.append({"role": "assistant", "content": content})
            return content
        messages.append(message)
        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                print("  [tool] %s(invalid JSON args)" % call.function.name)
                messages.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": "error: invalid JSON in tool arguments: %r" % (call.function.arguments,),
                })
                continue
            print("  [tool] %s(%s)" % (call.function.name, json.dumps(args)[:200]))
            result = await call_tool(call.function.name, args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            # Break a loop where the model repeats an identical failing call forever.
            global _repeat_sig, _repeat_count
            signature = "%s|%s" % (call.function.name, json.dumps(args, sort_keys=True)[:400])
            if "error" in str(result)[:80].lower():
                if signature == _repeat_sig:
                    _repeat_count += 1
                else:
                    _repeat_sig, _repeat_count = signature, 1
                if _repeat_count >= 3:
                    _repeat_count = 0
                    messages.append({"role": "user", "content": (
                        "You have now made this exact call %d times with identical arguments and it "
                        "keeps failing. Do NOT repeat it. Read the error text, then change approach: "
                        "use a different tool or different arguments, or do something simpler. If the "
                        "tool cannot do what you want, use write_file to author the file instead."
                    ) % 3})
            else:
                _repeat_sig, _repeat_count = "", 0


async def run_agent(user_message: str) -> str:
    global _empty_nudges, _repeat_sig, _repeat_count
    _empty_nudges = 0
    _repeat_sig, _repeat_count = "", 0
    messages.append({"role": "user", "content": user_message})
    try:
        answer = await agent_turn()
        save_history()
        return answer
    except ModelUnavailable:
        messages.pop()  # drop the stalled prompt so a retry starts clean
        raise
    except BudgetExhausted:
        save_history()
        raise


def _goal_needs_files(goal: str) -> bool:
    words = ("create", "add", "make", "build", "implement", "write", "system",
             "script", "scene", "setup", "set up", "configure", "fix", "update",
             "generate", "template", "controller", "player")
    text = goal.lower()
    return any(word in text for word in words)


async def pursue_goal(goal: str) -> str:
    global _empty_nudges, _task_modified, _repeat_sig, _repeat_count
    _empty_nudges = 0
    _repeat_sig, _repeat_count = "", 0
    _task_modified = False
    todo_clear()  # stale items from earlier tasks derail the model
    print("  [goal] working on: %s" % goal)
    _progress("task", "Goal: %s" % goal[:200])
    messages.append({
        "role": "user",
        "content": (
            "GOAL: " + goal + chr(10) * 2 +
            "This is a new, independent task. Work only on the goal above; do not "
            "resume or recreate anything from earlier tasks." + chr(10) * 2 +
            "Work toward this goal on your own until it is done. Use your tools "
            "and your plan. When it is finished, reply on its own line as "
            "'DONE: <short summary>'. If you cannot continue, reply "
            "'BLOCKED: <what you need>'."
        ),
    })
    step = 0
    idle = 0
    stalls = 0
    force_next = False
    while True:
        step += 1
        if GOAL_STEPS > 0 and step > GOAL_STEPS:
            _progress("done", "Reached the %d-step limit without finishing." % GOAL_STEPS)
            save_history()
            print("  [goal] hit the step limit without finishing")
            return "Reached the %d-step limit without finishing." % GOAL_STEPS
        label = ("Step %d of %d..." % (step, GOAL_STEPS)) if GOAL_STEPS > 0 else ("Step %d..." % step)
        _progress("thinking", label)
        reply = await agent_turn(force_tool=force_next)
        force_next = False
        print(chr(10) + "[step %d] %s" % (step, reply) + chr(10))
        if reply.strip():
            _progress("assistant", reply.strip()[:300])
        if reply.strip().startswith("(the model stopped responding"):
            stalls += 1
            if stalls >= 2:
                message = "The model returned empty replies repeatedly; task halted. Try again or use a stronger model."
                _progress("done", message)
                save_history()
                return message
        else:
            stalls = 0
        head = reply.strip().upper()
        if head.startswith("DONE") and _goal_needs_files(goal) and not _task_modified:
            _progress("thinking", "Checked: nothing was written yet - not accepting DONE.")
            messages.append({"role": "user", "content": (
                "Your 'DONE' is premature: NO file was created or changed during this "
                "task, so the goal is not actually done. Implement it now with real tool "
                "calls (build_3d_scene for a scene, write_file for a script, edit_file for "
                "a change). After writing, verify with validate_scene or play_scene, and "
                "only then reply 'DONE'."
            )})
            force_next = True
            continue
        if head.startswith("DONE") or head.startswith("BLOCKED"):
            save_history()
            return reply.strip()
        if _last_turn_had_tools:
            idle = 0
        else:
            idle += 1
            if idle >= 12:
                message = "The model stopped calling tools after several nudges. Say 'continue' to resume."
                _progress("done", message)
                save_history()
                return message
            # Stalled in prose. Do NOT inject a "user" nudge - the model just echoes
            # it and loops. Silently force a tool call on the next turn instead.
            force_next = True


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

def ollama_status() -> str:
    """Report installed and loaded models via Ollama's local API."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            installed = json.loads(response.read().decode("utf-8")).get("models", [])
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as response:
            running = json.loads(response.read().decode("utf-8")).get("models", [])
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return f"Ollama unavailable at localhost:11434: {exc}"
    names = [str(model.get("name", "?")) for model in installed]
    loaded = [str(model.get("name", "?")) for model in running]
    return "Installed: " + (", ".join(names) or "none") + "\\nLoaded now: " + (", ".join(loaded) or "none")
def handle_command(line: str) -> bool:
    global model_name
    if not line.startswith("/"):
        return False
    cmd, _, arg = line.partition(" ")
    if cmd == "/models":
        print(ollama_status())
        for name, cfg in MODELS.items():
            marker = "*" if name == model_name else " "
            print(f" {marker} {name:<12} {cfg.model}  ({cfg.base_url})")
    elif cmd == "/model":
        if arg in MODELS:
            model_name = arg
            print(f"  switched to {arg} ({MODELS[arg].model})")
        else:
            print(f"  unknown model '{arg}' - try /models")
    elif cmd == "/tools":
        for s in TOOL_SCHEMAS:
            fn = s["function"]
            origin = "local" if fn["name"] in LOCAL_TOOLS else "mcp"
            print(f"  [{origin}] {fn['name']}: {fn['description'][:60]}")
    elif cmd == "/memory":
        print(load_memory())
    elif cmd == "/plan":
        print(todo_list())
    elif cmd == "/clear":
        messages.clear()
        messages.append({"role": "system", "content": SYSTEM_PROMPT.format(memory=load_memory())})
        print("  conversation cleared")
    elif cmd == "/status":
        print(ollama_status())
    elif cmd == "/quit":
        raise SystemExit
    else:
        print("  commands: /models /model <name> /tools /memory /plan /clear /goal <text> /status /quit")
    return True


async def main() -> None:
    async with AsyncExitStack() as stack:
        print("starting loki...")
        await connect_mcp(stack)
        cfg = MODELS[active_model_name()]
        print(f"\nloki ready - model: {model_name} ({cfg.model}), {len(TOOL_SCHEMAS)} tools")
        print(f"workspace: {WORKSPACE}")
        print(f"Godot:     {GODOT_EXE}")
        if not endpoint_reachable(cfg.base_url):
            print(f"! WARNING: the model endpoint at {model_endpoint(cfg)} is not reachable.")
            print("  For a local model, start Ollama (ollama serve) before you send a prompt.\n")
        print("type /models, /model <name>, /tools, /memory, /plan, /goal <task>, or just talk\n")
        while True:
            try:
                line = (await asyncio.to_thread(input, "you: ")).strip()
                if not line:
                    continue
                if line.startswith("/goal "):
                    await pursue_goal(line[len("/goal "):].strip())
                    continue
                if handle_command(line):
                    continue
                print("\nassistant:", await run_agent(line), "\n")
            except ModelUnavailable as exc:
                print(f"\n{exc.hint}\n")
            except (EOFError, KeyboardInterrupt, SystemExit):
                print("\nbye!")
                return
            except Exception as exc:
                print(f"\n[loki] unexpected error: {type(exc).__name__}: {exc}")
                print("[loki] staying alive - your next prompt starts a fresh turn.\n")


if __name__ == "__main__":
    asyncio.run(main())
