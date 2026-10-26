import sys
try:   # no console windows on Windows for anything LOKI starts (engine/no_console.py)
    import no_console  # noqa: F401
except Exception:  # noqa: BLE001
    pass

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
import types
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

# The MCP client (`mcp`) is imported where it is used (connect_mcp, which runs in the background
# after the window opens): it is ~0.7 s of the engine's ~1.2 s start (docs/SPEED.md).
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

ROOT = Path(__file__).parent   # engine/: Loki's own code


def _resolve_data_dir() -> Path:
    """Where secrets, memory, plans and downloads live - never inside engine/.

    User data goes in <repo>/harness_data (gitignored). LOKI_DATA overrides, and the
    app sets it explicitly (a packaged build keeps it in a per-user folder).
    """
    explicit = os.getenv("LOKI_DATA", "").strip()
    if explicit:
        return Path(explicit)
    return ROOT.parent / "harness_data"


DATA_DIR = _resolve_data_dir()

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
    or str(DATA_DIR / "workspace")
)
# Where Godot usually lives when GODOT_EXE is not set. The editor always passes its own
# executable to the bridge; this only matters for the CLI, the tests and standalone use.
# (The first entry is the original developer's install, kept so nothing regresses there.)
_GODOT_GUESSES = (
    "G:/Godot_v4.8-dev7_win64.exe/Godot_v4.8-dev7_win64.exe",
    "/Applications/Godot.app/Contents/MacOS/Godot",
    "/Applications/Godot_mono.app/Contents/MacOS/Godot",
)


def resolve_godot_exe() -> str:
    """GODOT_EXE if set, else a Godot on PATH, else a known install path, else ""."""
    explicit = os.getenv("GODOT_EXE", "").strip()
    if explicit:
        return explicit
    for name in ("godot", "godot4", "Godot"):
        found = shutil.which(name)
        if found:
            return found
    for guess in _GODOT_GUESSES:
        if Path(guess).is_file():
            return guess
    try:   # LOKI's own Godot 4.7.2 (engine/godot_editor.py), when the computer has none of its own
        import godot_editor  # pylint: disable=import-outside-toplevel
        own = godot_editor.editor_binary()
        if own:
            return str(own)
    except Exception:  # noqa: BLE001
        pass
    return ""


GODOT_EXE = resolve_godot_exe()
# MCP servers that drive the engine (Coding-Solo's godot-mcp, Godot Forge) look
# for GODOT_PATH; Loki already knows the engine as GODOT_EXE, so share it.
if str(GODOT_EXE or "").strip() and Path(GODOT_EXE).is_file() and not os.getenv("GODOT_PATH"):
    os.environ["GODOT_PATH"] = GODOT_EXE

MEMORY_FILE = DATA_DIR / "memory.md"
PLAN_FILE = DATA_DIR / "plan.md"
MCP_CONFIG = ROOT / "mcp_servers.json"

# LOKI_AUTO_APPROVE=1 runs dangerous tools without asking (for unattended runs).
AUTO_APPROVE = (os.getenv("LOKI_AUTO_APPROVE") or os.getenv("HARNESS_AUTO_APPROVE", "")) == "1"

MAX_OUTPUT = 8000   # characters of command output handed back to the model
GOAL_STEPS = 0      # 0 = run a goal until it says DONE/BLOCKED (no step limit)
PREMATURE_DONE_LIMIT = 3   # "DONE" with nothing written: rejected this many times, then BLOCKED
MAX_TURNS_PER_REQUEST = int(os.getenv("LOKI_MAX_TURNS", "0"))       # model<->tool cycles per request (0 = UNLIMITED)
REQUEST_DEADLINE_S = float(os.getenv("LOKI_REQUEST_DEADLINE", "0"))    # wall-clock seconds per request (0 = no deadline)
# Safety nets that hold even when the budgets above are "unlimited": a runaway loop
# (a model that never stops calling tools) ends here instead of running forever.
HARD_MAX_TURNS = int(os.getenv("LOKI_HARD_MAX_TURNS", "400"))
HARD_DEADLINE_S = float(os.getenv("LOKI_HARD_DEADLINE", str(6 * 3600)))
# Every model HTTP call gets a timeout (the client default is 10 minutes).
MODEL_TIMEOUT_S = float(os.getenv("LOKI_MODEL_TIMEOUT", "180"))

# Transient model failures (429 rate limits, 5xx, dropped connections) are retried
# with exponential backoff instead of killing the whole task.
MODEL_RETRIES = int(os.getenv("LOKI_MODEL_RETRIES", "4"))
RETRY_BASE_S = float(os.getenv("LOKI_RETRY_BASE_S", "1.5"))
RETRY_MAX_S = float(os.getenv("LOKI_RETRY_MAX_S", "20"))
MAX_CONTEXT_MESSAGES = int(os.getenv("LOKI_MAX_CONTEXT", "0"))      # context window (0 = keep everything)


# ---------------------------------------------------------------------------
# Pillar: the model registry. Every entry is an OpenAI-compatible endpoint.
# ---------------------------------------------------------------------------

PROVIDER_ENV_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "nemotron-free": "OPENROUTER_API_KEY",
    "gpt6-luna": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "nous": "NOUS_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "unorouter": "UNOROUTER_API_KEY",
    "9router": "NINEROUTER_API_KEY",
    "omniroute": "OMNIROUTE_API_KEY",
    "vireonix": "VIREONIX_API_KEY",
    "typesafe": "TYPESAFE_API_KEY",
    # added with the Connections portal (engine/providers_catalog.py); the portal's cards use
    # the MODELS names, so "gpt" and "claude" are accepted alongside openai / anthropic.
    "gpt": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
    "cohere": "COHERE_API_KEY",
    "huggingface": "HF_TOKEN",
    "kilocode": "KILOCODE_API_KEY",
    "llm7": "LLM7_API_KEY",
    "modelscope": "MODELSCOPE_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "ollama-cloud": "OLLAMA_API_KEY",
    "ovh": "OVH_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "zai": "ZAI_API_KEY",
    "aion": "AION_API_KEY",
    "codestral": "CODESTRAL_API_KEY",
    "opencode-zen": "OPENCODE_API_KEY",
    "vercel": "AI_GATEWAY_API_KEY",
    "pollinations": "POLLINATIONS_API_KEY",
    "nebius": "NEBIUS_API_KEY",
    "scaleway": "SCALEWAY_API_KEY",
    "hyperbolic": "HYPERBOLIC_API_KEY",
    "novita": "NOVITA_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY",
    "chutes": "CHUTES_API_KEY",
    "baseten": "BASETEN_API_KEY",
    "inference-net": "INFERENCE_API_KEY",
    "ai21": "AI21_API_KEY",
    "upstage": "UPSTAGE_API_KEY",
}


def env_file_path() -> Path:
    """The .env Loki reads keys from: the data dir, then a legacy location."""
    path = DATA_DIR / ".env"
    if path.is_file():
        return path
    for fallback in (ROOT / ".env", Path.cwd() / ".env"):
        if fallback.is_file():
            return fallback
    return DATA_DIR / ".env"


def write_provider_key(provider: str, key: str) -> bool:
    """Persist a provider key into the .env and make it live for this session."""
    name = PROVIDER_ENV_VARS.get((provider or "").strip().lower())
    value = (key or "").strip()
    if not name or not value:
        return False
    path = env_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        replaced = False
        for index, line in enumerate(lines):
            if line.strip().startswith(name + "="):
                lines[index] = name + "=" + value
                replaced = True
                break
        if not replaced:
            lines.append(name + "=" + value)
        path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    except OSError:
        return False
    os.environ[name] = value
    try:
        import user_keys  # pylint: disable=import-outside-toplevel
        user_keys.update({name: value})   # every copy of LOKI on this account has it from now on
    except Exception:  # noqa: BLE001
        pass
    cfg = MODELS.get((provider or "").strip().lower())
    if cfg is not None:
        cfg.api_key = value
    _SMART_FAILED.discard((provider or "").strip().lower())
    return True


# Endpoints that actually REQUIRE the key: /models is public on several providers,
# so a bad key would still return 200 and the check would be worthless.
_VERIFY_PATHS = {"openrouter": "/key"}


def verify_provider_key(provider: str, key: str, timeout: float = 12.0) -> str:
    """Empty when the key checks out, else a short human reason."""
    name = (provider or "").strip().lower()
    value = (key or "").strip()
    if not value:
        return "Enter a key first."
    cfg = MODELS.get(name)
    if cfg is None or cfg.base_url.startswith(CLI_AGENT_PREFIX):
        return ""
    url = cfg.base_url.rstrip("/") + _VERIFY_PATHS.get(name, "/models")
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + value, "User-Agent": "Loki/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return "" if 200 <= response.status < 300 else "Provider answered HTTP %d." % response.status
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return "That key was rejected (HTTP %d)." % exc.code
        return ""
    except Exception:
        return "Could not reach the provider to check that key."


def connect_provider(provider: str, key: str) -> dict:
    """Verify a key and save it, so an account can be connected from the GUI."""
    name = (provider or "").strip().lower()
    if name not in PROVIDER_ENV_VARS:
        return {"ok": False, "error": "Unknown provider '%s'." % name}
    reason = verify_provider_key(name, key)
    unchecked = reason.startswith("Could not reach")
    if reason and not unchecked:
        return {"ok": False, "error": reason}
    if not write_provider_key(name, key):
        return {"ok": False, "error": "Could not save the key."}
    title = name.replace("-", " ").title()
    # A key LOKI could not check (no internet, the provider slow) is still saved: throwing it away
    # made it look like keys "don't save" (owner, 2026-10-18). A bad one shows up on its first use.
    message = ("%s key saved. LOKI could not reach %s to check it just now; it is used from the next request."
               % (title, title)) if unchecked else "%s connected." % title
    return {"ok": True, "provider": name, "env": PROVIDER_ENV_VARS[name], "message": message, "checked": not unchecked}


def _load_env_file() -> None:
    """Load KEY=VALUE pairs from harness/.env so users can store API keys."""
    path = DATA_DIR / ".env"
    if not path.is_file():
        # Backwards compatible: an older install kept .env beside the code.
        for fallback in (ROOT / ".env", Path.cwd() / ".env"):
            if fallback.is_file():
                path = fallback
                break
        else:
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
try:
    import user_keys as _user_keys  # noqa: E402  (keys saved per user account: ~/.loki/keys.env)
    _user_keys.adopt(env_file_path() if "env_file_path" in globals() else DATA_DIR / ".env")
    _user_keys.load_into()
except Exception:  # noqa: BLE001 - keys are a convenience; never stop the engine over them
    _user_keys = None


class ModelConfig(BaseModel):
    base_url: str
    api_key: str = "none"
    model: str


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import godot_tools  # noqa: E402  (Godot API + project editing tools)
import cli_agents  # noqa: E402  (Claude Code / Codex as subscription providers)
import jev  # noqa: E402  (Jev typed decisions: risk gate + loop detection)
# Laya's optional local backend resolves @receptron/laya from the data dir, never the addon.
os.environ.setdefault("LOKI_LAYA_PACKAGE_DIR", str(DATA_DIR / "laya"))
import decisions  # noqa: E402  (Laya-first decision routing with Jev fallback)
import project_state  # noqa: E402  (resumable project state - blueprint 7.3)
import repo_review  # noqa: E402  (read-only repository review - blueprint 5.1)
import sessions  # noqa: E402  (agent-session registry - blueprint 9 / herdr.dev)
import api_vault  # noqa: E402  (the API Vault - blueprint 3.3)
import capabilities  # noqa: E402  (the capability registry / API Vault seed)
import safe_exec  # noqa: E402  (structured command execution - no shell)
import shell_tools  # noqa: E402  (bash / Git Bash and itch.io's butler)
import policy  # noqa: E402  (the hardcoded policy engine: allow / ask / deny)
import manifests  # noqa: E402  (capability manifests: discovered, never executed)
import federation  # noqa: E402  (Ollama on other machines - LOKI_WORKERS)
import skill_scan  # noqa: E402  (downloaded skills are untrusted text)
import knowledge  # noqa: E402  (viking:// context store over local folders)
import model_setup  # noqa: E402  (offline-first: find, download and warm local models)
import usage  # noqa: E402  (token and cost ledger - the credits meter)
import conductor  # noqa: E402  (Loki the conductor: specialists by role)
import first_layer  # noqa: E402  (every request is triaged first: Laya, else built-in rules)
import events  # noqa: E402  (the event stream: what really happened, for the world and agents)
import tool_harness  # noqa: E402  (any model can use any tool: prompted tool calling)
import tool_guard  # noqa: E402  (repairs and checks tool calls; constrained decoding for local models)

# The repo checkout this addon lives in (capabilities/ and skills/ sit at its root).
REPO_ROOT = ROOT.parent
CAPABILITIES = manifests.default_registry(REPO_ROOT, DATA_DIR)
KNOWLEDGE = knowledge.default_store(REPO_ROOT, DATA_DIR, WORKSPACE)
import experience  # noqa: E402  (outcome log, learned routing, training data)
import reasoning_bank  # noqa: E402  (Ruflo-style lessons from past tasks)
import memory  # noqa: E402  (one interface over the four memory tiers)
# Session 26 core upgrade - ported from OpenHuman (GPL-3), OpenHands (MIT) and Scrapling (BSD-3);
# see docs/THIRD_PARTY.md and engine/licenses/.
import memory_core  # noqa: E402  (learn / recall / forget + the per-request memory pack)
import skill_learning  # noqa: E402  (verified multi-step work becomes a learned SKILL.md)
import condenser  # noqa: E402  (summarize old turns so long tasks never overflow)
import context_budget  # noqa: E402  (observation masking + cache-friendly batches: what each call sends)
import stuck  # noqa: E402  (loop / stuck detection)
import subagent  # noqa: E402  (run_subagent: a short-lived helper with its own context)
import file_editor  # noqa: E402  (view ranges, unique str_replace, insert, undo)
import web_reader  # noqa: E402  (read a web page natively, no add-on)
import command_risk  # noqa: E402  (LOW / MEDIUM / HIGH for shell commands)
import task_tracker  # noqa: E402  (a plan with statuses that survives condensing)
import provider_health  # noqa: E402  (each provider's live state, remembered across processes)
import ratelimit  # noqa: E402  (pacing for per-minute caps: NVIDIA NIM's ~40 requests/min)
import routing  # noqa: E402  (task-aware model choice, learned per task kind, /models doctor)

godot_tools.ROOT = ROOT
godot_tools.WORKSPACE = WORKSPACE


# Providers whose "base_url" is one of these are CLI coding agents, not HTTP APIs.
CLI_AGENT_PREFIX = "cli-agent://"


def _mlx_model() -> str:
    value = os.getenv("MLX_MODEL", "").strip()
    return "default_model" if value in ("", "auto") else value


MODELS = {
    # Offline default. qwen3:8b is the ONLY local model verified to emit real
    # structured tool_calls through Ollama; qwen2.5-coder only *writes* the call
    # as JSON text, so it cannot drive the agent. Ollama: `ollama pull qwen3:8b`.
    # SMART: automatically use the best available free provider (see SMART_ORDER).
    "smart": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:8b"),
    # A mode, not an endpoint: resolves to the best online provider. No Ollama, no GPU.
    "online": ModelConfig(base_url="https://api.deepseek.com", model="deepseek-flash"),
    "local": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:8b"),
    "local-small": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:8b"),
    "local-coder": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen2.5-coder:7b"),
    # Second verified offline tool-caller that fits 8 GB. Hermes is tool-focused with no
    # long hidden-reasoning phase, so it can be steadier on long agent loops.
    "local-hermes": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="hermes3:8b"),
    "local-reasoning": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3.5:9b"),
    # Best small model for TOOL RELIABILITY specifically (highest published BFCL score of
    # any small self-hosted finetune, ~4.8 GB - fits an 8 GB card). `ollama pull llama3-groq-tool-use:8b`.
    "local-tools": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="llama3-groq-tool-use:8b"),
    # Faster, smaller agent option for 8 GB: ~2.8 GB, optional thinking, ~80 tok/s.
    # `ollama pull qwen3:4b`
    "local-fast": ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama", model="qwen3:4b"),
    "gpt": ModelConfig(base_url="https://api.openai.com/v1", api_key=os.getenv("OPENAI_API_KEY", ""), model="gpt-5.2"),
    "claude": ModelConfig(base_url="https://api.anthropic.com/v1/", api_key=os.getenv("ANTHROPIC_API_KEY", ""), model="claude-sonnet-5"),
    # Subscription coding agents (see harness/cli_agents.py). These are NOT API
    # clients: once signed in they run on the flat-rate allowance you already pay,
    # so extra requests add nothing to the bill. Install once, then
    # LOKI_MODEL=claude-code (or codex).
    "claude-code": ModelConfig(base_url="cli-agent://claude-code", model="claude-code"),
    "codex": ModelConfig(base_url="cli-agent://codex", model="codex"),
    # OmniRoute: local AI gateway (one OpenAI-compatible endpoint -> many providers,
    # free tiers and auto-fallback). Run it, set a provider key, then use LOKI_MODEL=omniroute.
    # Free tiers (put the key in harness/.env). OpenAI-compatible endpoints.
    # NOTE: the Gemini free tier may use your content to improve Google products.
    "gemini": ModelConfig(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                          api_key=os.getenv("GEMINI_API_KEY", ""), model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash")),
    "groq": ModelConfig(base_url="https://api.groq.com/openai/v1",
                        api_key=os.getenv("GROQ_API_KEY", ""), model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")),
    # NOTE: free variants allow 50 requests/day (1,000 after a one-time $10 credit
    # purchase). A NEGATIVE credit balance can make even the :free models error.
    "openrouter": ModelConfig(base_url="https://openrouter.ai/api/v1",
                              api_key=os.getenv("OPENROUTER_API_KEY", ""), model=os.getenv("OPENROUTER_MODEL", "poolside/laguna-s-2.1:free")),
    # DeepSeek V4.1-Flash on OpenRouter - the go-to model. One account, 1M context,
    # very cheap, and it tolerates a 200-tool request where Gemini/Groq refuse one
    # well below that. Equivalent to LOKI_MODEL=openrouter with OPENROUTER_MODEL set;
    # this alias exists so "deepseek-4.1" can be named directly.
    "deepseek-4.1": ModelConfig(
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        model=os.getenv("DEEPSEEK_41_MODEL", "deepseek/deepseek-v4.1-flash")),
    # Nemotron 3.5 Lightning Free (OpenRouter :free, 1M context, costs nothing) in Smart's order, and GPT-6 Luna (OpenAI,
    # $0.10 / $0.50 per million tokens) through your OpenAI key (or OpenRouter) when you pick it.
    "nemotron-free": ModelConfig(base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                                 api_key=os.getenv("OPENROUTER_API_KEY", ""),
                                 model=os.getenv("NEMOTRON_FREE_MODEL", "nvidia/nemotron-3.5-lightning:free")),
    "gpt6-luna": ModelConfig(
        base_url="https://api.openai.com/v1" if os.getenv("OPENAI_API_KEY") else "https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY", ""),
        model=os.getenv("GPT6_LUNA_MODEL", "gpt-6-luna" if os.getenv("OPENAI_API_KEY") else "openai/gpt-6-luna")),
    # NOTE: not really free - Cerebras requires a verified payment method to activate.
    "cerebras": ModelConfig(base_url="https://api.cerebras.ai/v1",
                            api_key=os.getenv("CEREBRAS_API_KEY", ""), model=os.getenv("CEREBRAS_MODEL", "llama-3.3-70b")),
    "mistral": ModelConfig(base_url="https://api.mistral.ai/v1",
                           api_key=os.getenv("MISTRAL_API_KEY", ""), model=os.getenv("MISTRAL_MODEL", "mistral-large-latest")),
    "together": ModelConfig(base_url="https://api.together.xyz/v1",
                            api_key=os.getenv("TOGETHER_API_KEY", ""), model=os.getenv("TOGETHER_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free")),
    # DeepSeek V4.1-Flash. The live model name is "deepseek-flash" (the retired
    # deepseek-v4-flash and deepseek-chat names route to it). NOT free - it is
    # pay-as-you-go, and off-peak is half price: $0.15/1M in, $0.60/1M out.
    # Thinking mode is ON by default there, which burns tokens in an agent loop.
    "deepseek": ModelConfig(base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                            model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash")),
    # Vireonix: OpenAI-compatible, needs NO key, NO account and NO card, and mixes
    # MiniMax/Nemotron/GLM/Qwen/GPT-OSS behind "auto". 20M input tokens/hour, 1M
    # context. This is the "nothing to set up at all" option - note that prompts
    # and file contents are sent to a third-party service.
    "vireonix": ModelConfig(base_url=os.getenv("VIREONIX_BASE_URL", "https://vireonix.ai/v1"),
                            api_key=os.getenv("VIREONIX_API_KEY", "vireonix"),
                            model=os.getenv("VIREONIX_MODEL", "auto")),
    # --- Additional STANDING free tiers (verified 2026-10). These are providers that
    # keep a free tier indefinitely, as opposed to a one-off trial. Model names move
    # around, so every one is overridable with <PROVIDER>_MODEL.
    # SambaNova Cloud: 20 requests/min, 20/day, 200k tokens/day, no card.
    "sambanova": ModelConfig(base_url=os.getenv("SAMBANOVA_BASE_URL", "https://api.sambanova.ai/v1"),
                             api_key=os.getenv("SAMBANOVA_API_KEY", ""),
                             model=os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.3-70B-Instruct")),
    # Cloudflare Workers AI: 10,000 Neurons/day free. Needs an ACCOUNT_ID in the URL.
    "cloudflare": ModelConfig(
        base_url=os.getenv("CLOUDFLARE_BASE_URL",
                           "https://api.cloudflare.com/client/v4/accounts/%s/ai/v1"
                           % os.getenv("CLOUDFLARE_ACCOUNT_ID", "ACCOUNT_ID")),
        api_key=os.getenv("CLOUDFLARE_API_TOKEN", ""),
        model=os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")),
    # 9Router (engine/ninerouter.py, MIT, a separate Node program LOKI starts on 127.0.0.1): your subscriptions, free
    # tiers and keys behind one OpenAI endpoint with its own fallback chains. Model "loki" = a combo you name so in
    # its dashboard; without one LOKI takes the first model it lists (provider_health.SWAP_PREFERENCE).
    "9router": ModelConfig(base_url=os.getenv("NINEROUTER_BASE_URL", "http://127.0.0.1:%s/v1" % (os.getenv("NINEROUTER_PORT") or "20128")),
                           api_key=os.getenv("NINEROUTER_API_KEY", ""),
                           model=os.getenv("NINEROUTER_MODEL", "loki")),
    # UnoRouter: a large catalogue of :free routes, no card required.
    "unorouter": ModelConfig(base_url=os.getenv("UNOROUTER_BASE_URL", "https://api.unorouter.com/v1"),
                             api_key=os.getenv("UNOROUTER_API_KEY", ""),
                             model=os.getenv("UNOROUTER_MODEL", "ling-3.1-flash:free")),
    # Nous Portal: the $0 plan includes :free models.
    "nous": ModelConfig(base_url=os.getenv("NOUS_BASE_URL", "https://inference-api.nousresearch.com/v1"),
                        api_key=os.getenv("NOUS_API_KEY", ""),
                        model=os.getenv("NOUS_MODEL", "hermes-4-405b:free")),
    "omniroute": ModelConfig(
        base_url=os.getenv("OMNIROUTE_BASE_URL", "http://localhost:20128/v1"),
        api_key=os.getenv("OMNIROUTE_API_KEY", "omniroute"),
        model=os.getenv("OMNIROUTE_MODEL", "auto"),
    ),
    # --- More standing free tiers, taken from awesome-free-llm-apis
    # (github.com/mnfst/awesome-free-llm-apis, data.json - a machine-readable catalogue of
    # LLM APIs with permanent free tiers; verified 2026-10). All are OpenAI-compatible
    # endpoints, every model name is overridable with <PROVIDER>_MODEL, and every base URL
    # with <PROVIDER>_BASE_URL. Put the key in harness_data/.env; run tools/loki_doctor.py
    # to see what is configured. See docs/providers.md.
    "aion": ModelConfig(base_url=os.getenv("AION_BASE_URL", "https://api.aionlabs.ai/v1"),
                        api_key=os.getenv("AION_API_KEY", ""),
                        model=os.getenv("AION_MODEL", "aion-labs/aion-3.0")),
    # Cohere's own v2 API is not OpenAI-shaped, so this points at their OpenAI
    # compatibility endpoint instead.
    "cohere": ModelConfig(base_url=os.getenv("COHERE_BASE_URL", "https://api.cohere.com/compatibility/v1"),
                          api_key=os.getenv("COHERE_API_KEY", ""),
                          model=os.getenv("COHERE_MODEL", "command-a-plus-05-2026")),
    "zai": ModelConfig(base_url=os.getenv("ZAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                       api_key=os.getenv("ZAI_API_KEY", ""),
                       model=os.getenv("ZAI_MODEL", "glm-4.7-flash")),
    "huggingface": ModelConfig(base_url=os.getenv("HUGGINGFACE_BASE_URL", "https://router.huggingface.co/v1"),
                               api_key=os.getenv("HF_TOKEN", os.getenv("HUGGINGFACE_API_KEY", "")),
                               model=os.getenv("HUGGINGFACE_MODEL", "meta-llama/Llama-3.1-8B-Instruct")),
    "kilocode": ModelConfig(base_url=os.getenv("KILOCODE_BASE_URL", "https://api.kilo.ai/api/gateway"),
                            api_key=os.getenv("KILOCODE_API_KEY", ""),
                            model=os.getenv("KILOCODE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")),
    # LLM7.io answers without a token; a token raises the limits.
    "llm7": ModelConfig(base_url=os.getenv("LLM7_BASE_URL", "https://api.llm7.io/v1"),
                        api_key=os.getenv("LLM7_API_KEY", "unused"),
                        model=os.getenv("LLM7_MODEL", "gpt-oss:20b")),
    "modelscope": ModelConfig(base_url=os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"),
                              api_key=os.getenv("MODELSCOPE_API_KEY", ""),
                              model=os.getenv("MODELSCOPE_MODEL", "Qwen/Qwen3.5-35B-A3B")),
    # NVIDIA NIM, free with an account key (nvapi-..., build.nvidia.com/settings/api-keys), about
    # 40 requests/min. Since session 29 it serves LOKI's MAIN DRIVER: DeepSeek V4.1 Flash (1M
    # context, native tool calling). Paced client-side (engine/ratelimit.py, LOKI_NVIDIA_RPM);
    # its thinking mode is off for agent work (LOKI_NVIDIA_THINKING=off|high|max).
    "nvidia": ModelConfig(base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                          api_key=os.getenv("NVIDIA_API_KEY", ""),
                          model=os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4.1-flash")),
    "ollama-cloud": ModelConfig(base_url=os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api"),
                                api_key=os.getenv("OLLAMA_API_KEY", ""),
                                model=os.getenv("OLLAMA_CLOUD_MODEL", "deepseek-v4-pro")),
    "ovh": ModelConfig(base_url=os.getenv("OVH_BASE_URL", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"),
                       api_key=os.getenv("OVH_API_KEY", ""),
                       model=os.getenv("OVH_MODEL", "Qwen3.5-397B-A17B")),
    "siliconflow": ModelConfig(base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
                               api_key=os.getenv("SILICONFLOW_API_KEY", ""),
                               model=os.getenv("SILICONFLOW_MODEL", "Qwen/Qwen3-8B")),
    # --- Added 2026-10 with the Connections portal (engine/providers_catalog.py describes
    # each one: free limits, where to get a key, how to sign in). Every base URL and model
    # is overridable with <PROVIDER>_BASE_URL / <PROVIDER>_MODEL, and the portal's model
    # picker reads each provider's live /models list.
    "codestral": ModelConfig(base_url=os.getenv("CODESTRAL_BASE_URL", "https://codestral.mistral.ai/v1"),
                             api_key=os.getenv("CODESTRAL_API_KEY", ""),
                             model=os.getenv("CODESTRAL_MODEL", "codestral-latest")),
    "opencode-zen": ModelConfig(base_url=os.getenv("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1"),
                                api_key=os.getenv("OPENCODE_API_KEY", ""),
                                model=os.getenv("OPENCODE_ZEN_MODEL", "deepseek-v4-flash-free")),
    "vercel": ModelConfig(base_url=os.getenv("VERCEL_BASE_URL", "https://ai-gateway.vercel.sh/v1"),
                          api_key=os.getenv("AI_GATEWAY_API_KEY", ""),
                          model=os.getenv("VERCEL_MODEL", "openai/gpt-oss-120b")),
    # Keyless: a placeholder key so it counts as configured; a real key raises the limits.
    "pollinations": ModelConfig(base_url=os.getenv("POLLINATIONS_BASE_URL", "https://text.pollinations.ai/openai"),
                                api_key=os.getenv("POLLINATIONS_API_KEY", "pollinations"),
                                model=os.getenv("POLLINATIONS_MODEL", "openai")),
    "nebius": ModelConfig(base_url=os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
                          api_key=os.getenv("NEBIUS_API_KEY", ""),
                          model=os.getenv("NEBIUS_MODEL", "deepseek-ai/DeepSeek-R1-0528")),
    "scaleway": ModelConfig(base_url=os.getenv("SCALEWAY_BASE_URL", "https://api.scaleway.ai/v1"),
                            api_key=os.getenv("SCALEWAY_API_KEY", ""),
                            model=os.getenv("SCALEWAY_MODEL", "gpt-oss-120b")),
    "hyperbolic": ModelConfig(base_url=os.getenv("HYPERBOLIC_BASE_URL", "https://api.hyperbolic.xyz/v1"),
                              api_key=os.getenv("HYPERBOLIC_API_KEY", ""),
                              model=os.getenv("HYPERBOLIC_MODEL", "Qwen/Qwen3-Coder-480B-A35B-Instruct")),
    "novita": ModelConfig(base_url=os.getenv("NOVITA_BASE_URL", "https://api.novita.ai/openai"),
                          api_key=os.getenv("NOVITA_API_KEY", ""),
                          model=os.getenv("NOVITA_MODEL", "deepseek/deepseek-v3-0324")),
    "fireworks": ModelConfig(base_url=os.getenv("FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"),
                             api_key=os.getenv("FIREWORKS_API_KEY", ""),
                             model=os.getenv("FIREWORKS_MODEL", "accounts/fireworks/models/gpt-oss-120b")),
    "dashscope": ModelConfig(base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
                             api_key=os.getenv("DASHSCOPE_API_KEY", ""),
                             model=os.getenv("DASHSCOPE_MODEL", "qwen-plus")),
    # More hosts with starter credits (2026-10-14).
    "deepinfra": ModelConfig(base_url=os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai"),
                             api_key=os.getenv("DEEPINFRA_API_KEY", ""),
                             model=os.getenv("DEEPINFRA_MODEL", "meta-llama/Llama-3.3-70B-Instruct-Turbo")),
    "chutes": ModelConfig(base_url=os.getenv("CHUTES_BASE_URL", "https://llm.chutes.ai/v1"),
                          api_key=os.getenv("CHUTES_API_KEY", ""),
                          model=os.getenv("CHUTES_MODEL", "deepseek-ai/DeepSeek-V3")),
    "baseten": ModelConfig(base_url=os.getenv("BASETEN_BASE_URL", "https://inference.baseten.co/v1"),
                           api_key=os.getenv("BASETEN_API_KEY", ""),
                           model=os.getenv("BASETEN_MODEL", "openai/gpt-oss-120b")),
    "inference-net": ModelConfig(base_url=os.getenv("INFERENCE_NET_BASE_URL", "https://api.inference.net/v1"),
                                 api_key=os.getenv("INFERENCE_API_KEY", ""),
                                 model=os.getenv("INFERENCE_NET_MODEL", "glm-5.2")),
    "ai21": ModelConfig(base_url=os.getenv("AI21_BASE_URL", "https://api.ai21.com/studio/v1"),
                        api_key=os.getenv("AI21_API_KEY", ""),
                        model=os.getenv("AI21_MODEL", "jamba-mini")),
    "upstage": ModelConfig(base_url=os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1"),
                           api_key=os.getenv("UPSTAGE_API_KEY", ""),
                           model=os.getenv("UPSTAGE_MODEL", "solar-mini")),
    # --- Local OpenAI-compatible servers. "auto" = the first model the server lists.
    "lmstudio": ModelConfig(base_url=os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1"),
                            api_key="local", model=os.getenv("LMSTUDIO_MODEL", "auto")),
    "llamacpp": ModelConfig(base_url=os.getenv("LLAMACPP_BASE_URL", "http://127.0.0.1:8080/v1"),
                            api_key="local", model=os.getenv("LLAMACPP_MODEL", "auto")),
    # mlx_lm.server defaults to 8080 too; LOKI uses 8082 so it can run beside llama.cpp.
    # Its /v1/models lists the whole Hugging Face cache, not the model it serves, and a
    # request for model "auto" makes it look up huggingface.co/api/models/auto (404). Its own
    # name for "the model I was started with" is "default_model", so that is the default.
    "mlx": ModelConfig(base_url=os.getenv("MLX_BASE_URL", "http://127.0.0.1:8082/v1"),
                       api_key="local", model=_mlx_model()),
    # colibri (github.com/JustVugg/colibri, Apache-2.0): big MoE models with the experts offloaded to the SSD / the GPU -
    # Qwen3.6-35B at 25-30 tok/s on the PC's 8 GB RTX 3070 Ti with CUDA, DeepSeek V4.1 Flash from a 2 TB SSD (slow, for
    # background jobs). `coli serve` = OpenAI-compatible on :8000/v1; the model is whatever it serves.
    "colibri": ModelConfig(base_url=os.getenv("COLIBRI_BASE_URL", "http://127.0.0.1:8000/v1"),
                           api_key=os.getenv("COLI_API_KEY", "local"), model=os.getenv("COLIBRI_MODEL", "auto")),
    "vllm": ModelConfig(base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
                        api_key=os.getenv("VLLM_API_KEY", "local"), model=os.getenv("VLLM_MODEL", "auto")),
    "jan": ModelConfig(base_url=os.getenv("JAN_BASE_URL", "http://127.0.0.1:1337/v1"),
                       api_key=os.getenv("JAN_API_KEY", "local"), model=os.getenv("JAN_MODEL", "auto")),
    # Kyojin (github.com/Yamz-Labs/kyojin): ExLlamaV3 server for 100 GB-class packs on an
    # AMD Strix Halo box. Point KYOJIN_BASE_URL at that machine (its container uses 8731).
    "kyojin": ModelConfig(base_url=os.getenv("KYOJIN_BASE_URL", "http://127.0.0.1:8731/v1"),
                          api_key=os.getenv("KYOJIN_API_KEY", "local"), model=os.getenv("KYOJIN_MODEL", "auto")),
    # OpenCode (github.com/anomalyco/opencode) as a subscription-style coding agent.
    "opencode": ModelConfig(base_url="cli-agent://opencode", model="opencode"),
}

# Local OpenAI-compatible servers that are not Ollama: "configured" means the server is up.
LOCAL_SERVERS = ("colibri", "lmstudio", "llamacpp", "mlx", "vllm", "jan", "kyojin")
_LOCAL_UP: dict = {}   # name -> (checked_at, up)


def local_server_up(name: str, max_age: float = 30.0) -> bool:
    """Is this local server answering? Also resolves model "auto" to the first model it lists."""
    cfg = MODELS.get(name)
    if cfg is None:
        return False
    hit = _LOCAL_UP.get(name)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    up = False
    try:
        req = urllib.request.Request(cfg.base_url.rstrip("/") + "/models", headers={"User-Agent": "Loki/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        ids = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
        up = True
        if cfg.model in ("", "auto") and ids:
            cfg.model = ids[0]
    except Exception:  # noqa: BLE001 - not running
        up = False
    _LOCAL_UP[name] = (time.time(), up)
    return up

model_name = os.getenv("LOKI_MODEL", "smart")

# --- Smart mode -------------------------------------------------------------
# "smart" picks the best available FREE provider on its own: the first in this
# order that has a key configured (or a reachable Ollama), and it falls back to
# the next one whenever a provider fails, so the user never chooses.
# Ordered most-suitable-first for a big agent prompt. Gemini leads because its free
# tier allows 1M input tokens/min; Groq's free tier caps at 7k/min and returns 413
# on Loki's ~8k-token request, so it sits lower.
# Free cloud tiers first, then the subscription agents - when every free quota is
# spent it is better to hand the job to a real coding agent than a weak local model.
SMART_ORDER = ("nemotron-free", "openrouter", "9router", "deepseek-4.1", "gemini", "groq", "mistral", "sambanova",
               "cloudflare", "together", "nous", "unorouter", "opencode-zen", "codestral",
               "vercel", "deepseek", "cerebras",
               "vireonix", "claude-code", "codex", "colibri", "local", "local-hermes")

# Providers that need a GPU and a local download. The "online" mode exists so Loki is
# usable with NEITHER - it never touches these.
LOCAL_PROVIDERS = ("local", "local-small", "local-coder", "local-hermes",
                   "local-reasoning", "local-tools", "local-fast")

# ONLINE MODE (LOKI_MODEL=online): everything reached over the network. Free tiers first,
# then the subscription agents (which need no key and no GPU), and never a local model.
# The model Loki fine-tuned on its own verified work (tools/self_improve.py). It joins the
# smart order - just ahead of the stock local model - only once it has been PROMOTED, i.e.
# it beat the base model on held-out tasks. Until then it does not exist as far as routing
# is concerned.
TUNED_MODEL = os.getenv("LOKI_TUNED_MODEL", "loki-tuned").strip() or "loki-tuned"
TUNED_PROMOTED = str(os.getenv("LOKI_TUNED_PROMOTED", "0")).strip() == "1"
MODELS["loki-tuned"] = ModelConfig(base_url="http://localhost:11434/v1", api_key="ollama",
                                   model=TUNED_MODEL)
LOCAL_PROVIDERS = LOCAL_PROVIDERS + ("loki-tuned",)
if TUNED_PROMOTED and "local" in SMART_ORDER:
    _at = SMART_ORDER.index("local")
    SMART_ORDER = SMART_ORDER[:_at] + ("loki-tuned",) + SMART_ORDER[_at:]

# THE MAIN DRIVER (session 29, the owner: "i want it as the main driver"): DeepSeek V4.1 Flash on
# NVIDIA NIM. Whenever its key is set and it is healthy it comes first in smart and online routing -
# chat, background jobs, teams and LOKI improving itself - ahead of local-first and the learned
# order; every other provider stays behind it as the fallback. LOKI_MAIN_DRIVER=off (Settings >
# General) goes back to the plain smart order; another provider name makes that one the driver.
MAIN_DRIVER = str(os.getenv("LOKI_MAIN_DRIVER", "nvidia")).strip().lower()
if MAIN_DRIVER in ("off", "none", "0", "false", "no"):
    MAIN_DRIVER = ""
MAIN_DRIVER_KEY_URL = "https://build.nvidia.com/settings/api-keys"
if MAIN_DRIVER and MAIN_DRIVER in MODELS:
    SMART_ORDER = (MAIN_DRIVER,) + tuple(p for p in SMART_ORDER if p != MAIN_DRIVER)

ONLINE_ORDER = tuple(p for p in SMART_ORDER if p not in LOCAL_PROVIDERS)


class _FailedSet(set):
    """Providers used up in THIS process. Reviving one here (clear/discard) also forgets the
    provider-health mark this process made for it, so the in-process truth wins; marks from
    other processes and from probes expire on their own (provider_health.py)."""

    def clear(self) -> None:
        super().clear()
        try:
            provider_health.registry().forget_session()
        except Exception:  # noqa: BLE001 - health must never break routing
            pass

    def discard(self, name) -> None:
        super().discard(name)
        try:
            provider_health.registry().forget(name, session_only=True)
        except Exception:  # noqa: BLE001
            pass


_SMART_FAILED = _FailedSet()
# Providers skipped for a TEMPORARY rate limit (HTTP 429), not a spent quota. When every
# provider is out, these come back after a short cooldown instead of the run ending;
# LOKI_RATE_LIMIT_WAIT caps the total wait per turn (seconds, 0 turns it off).
_RATE_LIMITED: dict = {}
RATE_LIMIT_WAIT_S = float(os.getenv("LOKI_RATE_LIMIT_WAIT", "90") or 0)
RATE_LIMIT_COOLDOWN_S = 20.0


def _is_rate_limit(exc) -> bool:
    text = str(exc).lower()
    return (("429" in text or "rate limit" in text or "rate_limit" in text or "too many requests" in text)
            and not _is_quota_error(exc))


# When each provider was marked used-up. A LOCAL model is never "out of quota": it failed
# because Ollama was cold-loading the model, restarting, or briefly busy. Before this, one
# such failure kept local out of routing for the whole session, and every later request
# silently went to cloud or Claude Code - local looked useless. Now a local provider comes
# back at the start of the next request once its server answers (LOKI_LOCAL_REVIVE_S,
# default 20s after the failure).
_FAILED_AT: dict = {}
LOCAL_REVIVE_S = float(os.getenv("LOKI_LOCAL_REVIVE_S", "20") or 0)


def revive_local(now: float | None = None) -> list:
    """Put failed local providers back in the running when their server is up again."""
    now = time.time() if now is None else now
    back = []
    for name in sorted(_SMART_FAILED):
        if name not in LOCAL_PROVIDERS and name not in LOCAL_SERVERS:
            continue
        if now - _FAILED_AT.get(name, 0.0) < LOCAL_REVIVE_S:
            continue
        try:
            if name in LOCAL_SERVERS:
                _LOCAL_UP.pop(name, None)
            if provider_configured(name):
                _SMART_FAILED.discard(name)
                back.append(name)
        except Exception:  # noqa: BLE001 - a health probe must never break a request
            continue
    return back


def revive_rate_limited() -> list:
    """Put the rate-limited providers back in the running; returns which ones."""
    back = [name for name in _RATE_LIMITED if provider_configured(name)]
    for name in back:
        _SMART_FAILED.discard(name)
    _RATE_LIMITED.clear()
    return back

# Learned routing: measured success reorders providers WITHIN a cost tier (see
# experience.learned_order). Free stays ahead of paid whatever the numbers say.
LEARN_ROUTING = str(os.getenv("LOKI_LEARN_ROUTING", "1")).strip().lower() not in ("0", "false", "off", "no")
LEARN_MIN_SAMPLES = int(os.getenv("LOKI_LEARN_MIN_SAMPLES", "10"))
_ROUTING_CACHE = {"t": 0.0, "stats": {}}


def provider_tier(name: str) -> str:
    cfg = MODELS.get(name)
    if name in LOCAL_PROVIDERS or (cfg is not None and "11434" in cfg.base_url):
        return "local"
    if cfg is not None and cfg.base_url.startswith(CLI_AGENT_PREFIX):
        return "subscription"
    if is_metered(name):
        return "paid"
    return "free"


def _model_of(provider: str) -> str:
    """The actual model name behind a provider (needed to score local models one by one)."""
    cfg = MODELS.get(provider or "")
    return str(getattr(cfg, "model", "") or "")


_LOCAL_TAGS: dict = {"t": 0.0, "tags": []}


def _installed_local_tags() -> list:
    now = time.time()
    if now - _LOCAL_TAGS["t"] > 30:
        try:
            import model_setup  # pylint: disable=import-outside-toplevel
            _LOCAL_TAGS["tags"] = [str(m.get("name") or "") for m in (model_setup.ollama_models() or [])]
        except Exception:  # noqa: BLE001 - Ollama down: keep what we had
            _LOCAL_TAGS["tags"] = _LOCAL_TAGS["tags"] or []
        _LOCAL_TAGS["t"] = now
    return _LOCAL_TAGS["tags"]


def resolve_local_model(provider: str) -> str:
    """The tag to actually ask THIS machine's Ollama for. A local preset names a catalogue tag
    ("qwen3.5:9b"), but a machine installs a particular build of it ("qwen3.5:9b-q4_K_M") or LOKI's
    longer-context "loki-<tag>" variant, so the hardcoded name would 404. Fall back to the same family
    that IS installed, then to whatever the engine scores best (model_setup.best_installed)."""
    cfg = MODELS.get(provider or "")
    if cfg is None or "11434" not in str(cfg.base_url or ""):
        return str(getattr(cfg, "model", "") or "")
    want = str(cfg.model or "")
    tags = _installed_local_tags()
    if not tags or want in tags or (want + ":latest") in tags:
        return want
    base = want.split(":")[0]
    same = [t for t in tags if t.split(":")[0] == base or t.split(":")[0].startswith("loki-" + base)]
    if same:
        # the same SIZE first ("qwen3.5:9b" -> "qwen3.5:9b-q4_K_M" or "loki-qwen3.5:9b"), not just the family -
        # a 0.8b or a 27b build is a different model (review 2026-10-19); LOKI's longer-context variant first
        size = want.split(":")[1] if ":" in want else ""
        sized = [t for t in same if size and t.split(":", 1)[-1].startswith(size)] if size else []
        pool = sized or same
        prefer = [t for t in pool if t.startswith("loki-")] or pool
        return prefer[0]
    try:
        import model_setup  # pylint: disable=import-outside-toplevel
        best = model_setup.best_installed(model_setup.ollama_models() or [], 8.0)
        if best and best.get("name"):
            return str(best["name"])
    except Exception:  # noqa: BLE001
        pass
    return want


_FORECAST_CACHE: dict = {"t": 0.0, "outlook": {}}


def latency_outlook() -> dict:
    """Each provider's forecast latency for the next calls (forecast.py, TimesFM-3 when
    installed), from the usage ledger; cached for a minute."""
    now = time.time()
    if now - _FORECAST_CACHE["t"] > 60:
        try:
            import forecast  # pylint: disable=import-outside-toplevel
            _FORECAST_CACHE["outlook"] = forecast.provider_outlook(USAGE.entries(now - 3 * 86400))
        except Exception:  # noqa: BLE001
            _FORECAST_CACHE["outlook"] = {}
        _FORECAST_CACHE["t"] = now
    return _FORECAST_CACHE["outlook"]


def _forecast_order(order: list) -> list:
    try:
        import forecast  # pylint: disable=import-outside-toplevel
        return forecast.reorder(order, latency_outlook())
    except Exception:  # noqa: BLE001
        return list(order)


def routing_order(order) -> list:
    """`order` as routing should try it: learned within tiers when enabled, then providers
    forecast to be getting slow moved back (forecast.py), else as-is."""
    if not LEARN_ROUTING:
        return _forecast_order(list(order))
    now = time.time()
    if now - _ROUTING_CACHE["t"] > 60:
        try:
            _ROUTING_CACHE["stats"] = experience.provider_stats()
        except Exception:
            _ROUTING_CACHE["stats"] = {}
        _ROUTING_CACHE["t"] = now
    return _forecast_order(experience.learned_order(order, provider_tier, _ROUTING_CACHE["stats"],
                                                    LEARN_MIN_SAMPLES))


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


_OLLAMA_MODELS_CACHE: dict = {"at": 0.0, "models": None}


def _ollama_models() -> list | None:
    """Names of the models this machine's Ollama has pulled (cached 20s); None if down."""
    now = time.time()
    if now - _OLLAMA_MODELS_CACHE["at"] < 20:
        return _OLLAMA_MODELS_CACHE["models"]
    models = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
        models = [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]
    except Exception:
        models = None
    _OLLAMA_MODELS_CACHE.update(at=now, models=models)
    return models


def missing_key_env(name: str) -> str:
    """The env var a provider's key goes in, for the 'add your key' message."""
    cfg = MODELS.get(name)
    host = (urllib.parse.urlparse(cfg.base_url).hostname or "") if cfg else ""
    for provider, env in PROVIDER_ENV_VARS.items():
        if provider == name or (provider in host):
            return env
    return name.upper().replace("-", "_").replace(".", "_") + "_API_KEY"


def provider_disabled(name: str) -> bool:
    """Switched off in Settings > Connections (LOKI_DISABLED_PROVIDERS): never routed to."""
    return name in {p.strip().lower() for p in os.getenv("LOKI_DISABLED_PROVIDERS", "").split(",") if p.strip()}


def provider_configured(name: str) -> bool:
    cfg = MODELS.get(name)
    if cfg is None or provider_disabled(name):
        return False
    if name in LOCAL_SERVERS:
        return local_server_up(name)
    if cfg.base_url.startswith(CLI_AGENT_PREFIX):
        # Counts as configured only once the CLI is actually installed.
        return cli_agents.is_available(cfg.base_url[len(CLI_AGENT_PREFIX):])
    if name == "local":
        return local_ready()
    if "11434" in cfg.base_url:
        # Reachable is not enough: a model that was never pulled answers 404 on every
        # request. Smart mode skips it; LOKI_FLEET routing may still find it elsewhere.
        models = _ollama_models()
        if models is None:
            return False
        return federation.has_model(models, cfg.model) or CAPABILITIES.is_enabled("ollama-fleet")
    return bool(str(cfg.api_key or "").strip())


# ---- offline-first: the best model on THIS computer -------------------------------
# "local" is not a fixed tag any more: it resolves to the best tool-calling model that is
# actually installed (Ollama, or LM Studio / llama.cpp / Jan if one is running), in a
# variant with an agent-sized context window. LOKI_PREFER=local (default) puts it first in
# smart mode; with no internet, smart uses ONLY local models.
PREFER = os.getenv("LOKI_PREFER", "local").strip().lower()
HARD_DIFFICULTY = int(os.getenv("LOKI_HARD_DIFFICULTY", "2"))


def triage_difficulty() -> int:
    """The first layer's 0..3 read on this request (1 when it did not say).

    RouteLLM's idea, on LOKI's own default: local-first is right for easy work, but it must
    not keep HARD work on the weak offline model.
    """
    try:
        return int((LAST_TRIAGE or {}).get("difficulty"))
    except (TypeError, ValueError):
        return 1
LOCAL_STATE: dict = {"at": 0.0, "name": "", "base_url": "", "source": "", "warm": "", "note": "",
                     "version": "", "context": 0, "wanted_context": 0, "skipped": ""}
_ONLINE: dict = {"at": 0.0, "ok": True}


def online(max_age: float = 60.0) -> bool:
    """Is the internet reachable? (one quick TCP connect, cached)"""
    import socket
    if time.time() - _ONLINE["at"] < max_age:
        return _ONLINE["ok"]
    ok = False
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((host, 443), timeout=1.2):
                ok = True
                break
        except OSError:
            continue
    _ONLINE.update(at=time.time(), ok=ok)
    return ok


_LOCAL_LOCK = threading.Lock()


def resolve_local(force: bool = False) -> dict:
    """Point MODELS['local'] at the best model on this computer. Cached for 30s; never
    makes a caller wait while another thread is already resolving."""
    if not force and time.time() - LOCAL_STATE["at"] < 30:
        return LOCAL_STATE
    if not _LOCAL_LOCK.acquire(blocking=force):
        return LOCAL_STATE
    try:
        return _resolve_local()
    finally:
        _LOCAL_LOCK.release()


LOCAL_TOOL_MIN_SAMPLES = int(os.getenv("LOKI_TOOL_MIN_SAMPLES", "3"))


def _best_local_by_tools(models: list, budget_gb: float) -> dict:
    """The installed, tool-capable model with the BEST measured tool-calling record.

    Local choice used to be hardware-only (model_setup.best_installed), so a model that
    narrates instead of acting got picked again and again. Measured tool use now decides -
    but only with evidence: no data, or too few requests, changes nothing.
    """
    try:
        stats = experience.tool_stats()
    except Exception:  # noqa: BLE001 - learning must never break model choice
        return {}
    scored = []
    for m in models or []:
        name = str(m.get("name") or "")
        if not name or "embed" in name.lower():
            continue
        fit = model_setup.best_installed([m], budget_gb)
        if not fit or not fit.get("tools"):
            continue
        score = experience.tool_score("local/" + name, stats, LOCAL_TOOL_MIN_SAMPLES)
        if score is not None:
            scored.append((score, name))
    if not scored:
        return {}
    scored.sort(key=lambda row: (-row[0], row[1]))
    return {"name": scored[0][1], "score": scored[0][0]}


# Characters of LOKI's own prompt a local model must hold besides the conversation: the system
# prompt (~2.7k chars), the "This request" note with memories (~2k) and the trimmed tool list
# (~9k for LOCAL_MAX_TOOLS=22). Measured 2026-10; the window is sized from it (required_context).
LOCAL_PROMPT_CHARS = int(os.getenv("LOKI_LOCAL_PROMPT_CHARS", "14000") or 14000)
_CTX_DONE: dict = {}   # (model, wanted) -> the name with that window (made once per process)


def _with_context(name: str, models: list) -> str:
    """`name` with a context window that holds LOKI's prompt + tools + room to work (a loki-*
    variant made with /api/create num_ctx - Ollama's OpenAI endpoint ignores num_ctx per
    request, so the Modelfile parameter is the only reliable way). LOKI_LOCAL_CONTEXT=0: off."""
    if os.getenv("LOKI_LOCAL_CONTEXT", "1") == "0":
        return name
    wanted = model_setup.required_context(LOCAL_PROMPT_CHARS // 4, HARDWARE or None)
    LOCAL_STATE["wanted_context"] = wanted
    key = (name, wanted)
    if key not in _CTX_DONE:
        _CTX_DONE[key] = model_setup.ensure_context(name, wanted, models)
    return _CTX_DONE[key]


def _note_context(name: str) -> None:
    """Read the window the chosen model really has and size the local condenser to it."""
    try:
        ctx = model_setup.model_context(name)
    except Exception:  # noqa: BLE001
        ctx = {}
    real = int(ctx.get("loaded") or ctx.get("num_ctx") or 0)
    LOCAL_STATE["context"] = real
    LOCAL_STATE["context_source"] = ("loaded" if ctx.get("loaded") else "num_ctx" if ctx.get("num_ctx")
                                     else "default")
    if not real and name.startswith(model_setup.DERIVED_PREFIX):
        real = int(LOCAL_STATE.get("wanted_context") or 0)   # our own variant: made with that window
    window = real or 4096   # a base model with no num_ctx: Ollama's default, small on most versions
    condenser.LOCAL_WINDOW_TOKENS = max(2048, window - LOCAL_PROMPT_CHARS // 4)


def _resolve_local() -> dict:
    LOCAL_STATE["at"] = time.time()
    try:
        LOCAL_STATE["version"] = model_setup.ollama_version()
    except Exception:  # noqa: BLE001
        LOCAL_STATE["version"] = ""
    version = LOCAL_STATE["version"]
    LOCAL_STATE["skipped"] = ""
    if os.getenv("LOKI_LOCAL_MODEL") and model_setup.is_broken(os.environ["LOKI_LOCAL_MODEL"], version):
        LOCAL_STATE["skipped"] = ("Ollama %s cannot load the chosen model %s; LOKI uses the best other one"
                                  % (version or "", os.environ["LOKI_LOCAL_MODEL"]))
    if os.getenv("LOKI_LOCAL_MODEL") and not model_setup.is_broken(os.environ["LOKI_LOCAL_MODEL"], version):
        # The user pinned a model: use it, with a window big enough for LOKI's prompt.
        pinned = os.environ["LOKI_LOCAL_MODEL"]
        models = model_setup.ollama_models() or []
        if models and any(m["name"] == pinned or m["name"].startswith(pinned + ":") for m in models):
            pinned = _with_context(pinned, models)
        LOCAL_STATE.update(name=pinned, base_url="http://localhost:11434/v1",
                           source="pinned", note="LOKI_LOCAL_MODEL")
    else:
        models = model_setup.ollama_models()
        best = None
        why = ""
        if models:
            _match_installed_tags([m["name"] for m in models])
            info = HARDWARE if HARDWARE else {"budget_gb": 0}
            usable = models
            if model_setup.version_at_least(version, model_setup.BONSAI_MIN_OLLAMA) is False:
                usable = [m for m in models if not model_setup.is_bonsai(m["name"])]
                if len(usable) != len(models):
                    LOCAL_STATE["skipped"] = model_setup.bonsai_support(version)["message"]
            best = model_setup.best_installed(usable, float(info.get("budget_gb") or 0), version=version)
            proven = _best_local_by_tools(usable, float(info.get("budget_gb") or 0))
            if proven and (not best or proven["name"] != best.get("name")):
                best = dict(best or {}, name=proven["name"], tools=True)
                why = "best measured tool caller (score %.2f)" % proven["score"]
        if best and best.get("tools"):
            name = best["name"]
            if not name.startswith(model_setup.DERIVED_PREFIX):
                name = _with_context(name, models)
            LOCAL_STATE.update(name=name, base_url="http://localhost:11434/v1", source="ollama",
                               note=why or ("best installed: %s" % best["name"]))
            # The other local entries smart mode may use get the same window.
            for other in ("local-hermes", "loki-tuned"):
                cfg = MODELS.get(other)
                if cfg is not None and "11434" in cfg.base_url and not cfg.model.startswith(model_setup.DERIVED_PREFIX) \
                        and any(m["name"] == cfg.model for m in models):
                    MODELS[other] = ModelConfig(base_url=cfg.base_url, api_key=cfg.api_key,
                                                model=_with_context(cfg.model, models))
        else:
            servers = model_setup.other_servers(include_mlx=True)
            if servers:
                server = servers[0]
                LOCAL_STATE.update(name=server["models"][0], base_url=server["base_url"],
                                   source=server["key"], note=server["label"])
            else:
                LOCAL_STATE.update(name="", base_url="", source="",
                                   note=("Ollama has no models yet" if models == [] else
                                         "no installed model can call tools" if models else
                                         "Ollama is not running"))
    if LOCAL_STATE["name"]:
        api_key = "ollama" if "11434" in LOCAL_STATE["base_url"] else "local"
        MODELS["local"] = ModelConfig(base_url=LOCAL_STATE["base_url"], api_key=api_key,
                                      model=LOCAL_STATE["name"])
        if "11434" in LOCAL_STATE["base_url"]:
            _note_context(LOCAL_STATE["name"])
        if "11434" in LOCAL_STATE["base_url"] and LOCAL_STATE["warm"] != LOCAL_STATE["name"]:
            LOCAL_STATE["warm"] = LOCAL_STATE["name"]
            threading.Thread(target=model_setup.keep_warm, args=(LOCAL_STATE["name"],),
                             daemon=True, name="loki-warm").start()
    return LOCAL_STATE


def local_report() -> dict:
    """The local side for /models doctor: Ollama's version, Bonsai, the model and its real
    context window, MLX - with what to do about each problem."""
    state = resolve_local()
    lines, needs_you = [], []
    version = state.get("version") or ""
    if state.get("name"):
        ctx = int(state.get("context") or 0)
        wanted = int(state.get("wanted_context") or 0)
        src = state.get("context_source") or ""
        lines.append("Local model: %s (%s)%s." % (state["name"], state.get("note") or state.get("source"),
                                                    ", context %d tokens (%s)" % (ctx, src) if ctx else ""))
        if "11434" in str(state.get("base_url")) and ctx and wanted and ctx < wanted:
            lines.append("Its context window (%d) is smaller than LOKI's prompt needs (%d): the start of the prompt "
                         "would be cut off. LOKI condenses earlier to fit." % (ctx, wanted))
        elif "11434" in str(state.get("base_url")) and not ctx:
            lines.append("Its context window is Ollama's default (no num_ctx set) - LOKI could not make its "
                         "loki-* variant; the conversation is condensed to fit ~4k tokens.")
    else:
        lines.append("No local model: %s." % (state.get("note") or "none"))
    if version:
        bon = model_setup.bonsai_support(version)
        lines.append("Ollama %s. %s" % (version, "Runs Bonsai 2." if bon["ok"] else ""))
        if bon["ok"] is False:
            needs_you.append("Update Ollama for Bonsai 2 (%s has %s, needs %s+): %s" % (
                "this computer", version, bon["needs"], bon["upgrade"]["command"]))
    elif state.get("source") in ("", "ollama"):
        lines.append("Ollama is not answering on 127.0.0.1:11434.")
    if state.get("skipped"):
        lines.append(state["skipped"])
    if sys.platform == "darwin":
        try:
            mlx = model_setup.mlx_status()
            lines.append("MLX: %s%s." % ("running on 8082" if mlx.get("running") else "not running",
                                         "" if mlx.get("running") else " (start Bonsai 2 for Apple Silicon: %s)" % mlx.get("bonsai_command")))
        except Exception:  # noqa: BLE001
            pass
    return {"name": state.get("name", ""), "version": version, "context": state.get("context", 0),
            "wanted_context": state.get("wanted_context", 0), "lines": lines, "needs_you": needs_you}


def _match_installed_tags(installed: list) -> None:
    """local-* entries name a tag ("qwen3.5:9b"); Ollama may hold it under a longer one
    ("qwen3.5:9b-q4_K_M"). Point the entry at what is really installed."""
    for name in LOCAL_PROVIDERS:
        cfg = MODELS.get(name)
        if cfg is None or name == "local" or cfg.model in installed:
            continue
        match = next((t for t in installed if t.startswith(cfg.model + "-")), "")
        if match:
            MODELS[name] = ModelConfig(base_url=cfg.base_url, api_key=cfg.api_key, model=match)


def local_ready() -> bool:
    return bool(resolve_local()["name"])


try:
    HARDWARE = model_setup.hardware()
except Exception:
    HARDWARE = {}


_TOOL_CHARS: dict = {"n": 0}
_NEEDS_OVERRIDE: list = []   # route_for() pins the needs while it asks active_model_name


def _tool_chars() -> int:
    """Size of the tool list a request carries (static, measured once)."""
    if not _TOOL_CHARS["n"]:
        try:
            _TOOL_CHARS["n"] = len(json.dumps(MODEL_TOOL_SCHEMAS))
        except Exception:  # noqa: BLE001 - before the schemas exist
            return 8000
    return _TOOL_CHARS["n"]


def current_needs() -> dict:
    """What the request in flight needs from a model (routing.needs_for)."""
    if _NEEDS_OVERRIDE:
        return _NEEDS_OVERRIDE[-1]
    try:
        msgs = messages
    except NameError:
        msgs = []
    return routing.needs_for(LAST_TRIAGE if "LAST_TRIAGE" in globals() else {},
                             background=bool(os.getenv("LOKI_JOB_ID")), messages=msgs,
                             local_only=routing.local_only_setting(),
                             est_tokens=routing.estimate_tokens(msgs, _tool_chars()) if msgs else 0)


ROUTE_NOTES: dict = {}   # provider -> why routing skipped it for the last pick (for /models doctor)


def main_driver_ready(needs: dict | None = None) -> tuple:
    """(True, "") when the main driver (MAIN_DRIVER, DeepSeek V4.1 Flash on NVIDIA) should take
    this task: set up, not switched off or used up, healthy, not local-only, and able to do it
    (it cannot see pictures). Else (False, why) - routing then goes on as before."""
    needs = dict(needs or {})
    if not MAIN_DRIVER or MAIN_DRIVER not in MODELS:
        return False, "no main driver (LOKI_MAIN_DRIVER=off)"
    if needs.get("local_only"):
        return False, "local only is on"
    if not provider_configured(MAIN_DRIVER):
        return False, "no key yet - get a free one at " + MAIN_DRIVER_KEY_URL
    if MAIN_DRIVER in _SMART_FAILED:
        return False, "used up or failing in this session (falls back until it recovers)"
    if provider_tier(MAIN_DRIVER) == "paid" and not paid_allowed_automatically():
        return False, "paid and paid providers are not allowed automatically"
    try:
        ok, why = provider_health.registry().usable(MAIN_DRIVER, str(MODELS[MAIN_DRIVER].api_key or ""),
                                                    int(needs.get("est_tokens") or 0))
        if not ok:
            return False, why
        fit, short = routing.fits(routing.abilities(sys.modules[__name__], MAIN_DRIVER), needs)
        if not fit:
            return False, short
    except Exception:  # noqa: BLE001 - health must never break routing
        pass
    return True, ""


def _main_first(ordered: list, needs: dict) -> list:
    """`ordered` with the main driver moved to the front when it is ready for this task."""
    if MAIN_DRIVER in ordered and main_driver_ready(needs)[0]:
        return [MAIN_DRIVER] + [p for p in ordered if p != MAIN_DRIVER]
    return ordered


def _route_pick(order, needs: dict, allow_local: bool = True) -> str:
    """The first provider in `order` that is configured, not used up, healthy, affordable and
    (when any is) able to do this task. "" when none is."""
    ordered, notes = routing.order_for(sys.modules[__name__], routing_order(order), needs)
    ordered = _main_first(list(ordered), needs)
    ROUTE_NOTES.clear()
    ROUTE_NOTES.update(notes)
    for candidate in ordered:
        if not allow_local and candidate in LOCAL_PROVIDERS:
            continue
        if provider_tier(candidate) == "paid" and not paid_allowed_automatically():
            continue   # never switch to a paid provider on its own
        if candidate not in _SMART_FAILED and provider_configured(candidate):
            return candidate
    # Never a dead end: everything healthy is used up, so try the configured provider whose
    # limit ends soonest (it may be back) rather than one that is certainly not set up.
    reg = provider_health.registry()
    waiting = []
    for candidate in order:
        if candidate not in notes or (not allow_local and candidate in LOCAL_PROVIDERS):
            continue
        entry = reg.get(candidate)
        if entry.get("state") in ("key_rejected", "no_credit") or needs.get("local_only"):
            continue
        if provider_tier(candidate) == "paid" and not paid_allowed_automatically():
            continue
        if candidate not in _SMART_FAILED and provider_configured(candidate):
            waiting.append((float(entry.get("until") or 0), candidate))
    return min(waiting)[1] if waiting else ""


def _free_capable_online(needs: dict) -> str:
    """The best FREE online provider that can do this task, or "". Subscription agents (Claude
    Code, Codex) are not counted here: an unattended job should not use up the owner's plan when
    the local model may do; they stay in the smart order after the free tiers."""
    order = [p for p in SMART_ORDER if p not in LOCAL_PROVIDERS and provider_tier(p) == "free"]
    ordered, _notes = routing.order_for(sys.modules[__name__], routing_order(order), dict(needs, local_only=False))
    for candidate in ordered:
        if candidate in _SMART_FAILED or not provider_configured(candidate):
            continue
        ab = routing.abilities(sys.modules[__name__], candidate)
        if ab.get("keyless") and ab.get("tool_score") is None:
            continue   # an anonymous third-party route has not earned an unattended job yet
        if routing.fits(ab, needs)[0]:
            return candidate
    return ""


def _local_fits(needs: dict) -> tuple:
    if not needs.get("vision") and not needs.get("long"):
        return True, ""
    ab = routing.abilities(sys.modules[__name__], "local")
    return routing.fits(ab, dict(needs, tool_heavy=False))


def _smart_pick(needs: dict) -> tuple:
    """(provider, why) in smart mode."""
    if needs.get("local_only"):
        if local_ready():
            return "local", "local only is on (LOKI_LOCAL_ONLY): this computer's model"
        for name in LOCAL_SERVERS:
            if name not in _SMART_FAILED and provider_configured(name):
                return name, "local only is on: the local server that is running"
        return "local", "local only is on, but no local model is running"
    driver_ok, _driver_why = main_driver_ready(needs)
    if driver_ok and online():
        # The main driver takes everything it can do - ahead of local-first (session 29).
        return MAIN_DRIVER, "main driver: %s on %s (%s)" % (
            MODELS[MAIN_DRIVER].model, MAIN_DRIVER, routing.why_line(sys.modules[__name__], MAIN_DRIVER, needs))
    local_first = PREFER == "local" and "local" not in _SMART_FAILED and local_ready()
    why_not_local = ""
    job_pick = ""
    if local_first and int(needs.get("difficulty") or 1) >= HARD_DIFFICULTY:
        # This one is medium/hard: do not spend it on the offline model. Falls through to the
        # best provider that is configured and affordable.
        local_first, why_not_local = False, "hard work goes past the offline model"
    if local_first and needs.get("background") and online():
        # A background job is tool-heavy and unattended: the best FREE capable model, not just
        # 'local' (session 27: jobs on qwen3:8b came back empty or BLOCKED).
        job_pick = _free_capable_online(needs)
        if job_pick:
            local_first, why_not_local = False, "background jobs get the best free model that calls tools reliably"
    if local_first:
        ok, why = _local_fits(needs)
        if not ok and online() and _free_capable_online(needs):
            local_first, why_not_local = False, "the local model " + why
    if local_first or (not online() and local_ready()):
        return "local", ("local first (LOKI_PREFER=local) for easy work" if local_first else "offline: the local model")
    if not online():
        return "local", "offline, and no local model is ready"
    pick = job_pick or _route_pick(SMART_ORDER, needs)
    if pick:
        why = routing.why_line(sys.modules[__name__], pick, needs)
        return pick, (why_not_local + "; " if why_not_local else "") + why
    return "local", "no other provider is ready"


def route_for(needs: dict) -> tuple:
    """(provider, why) routing would choose for a task with these needs - the same decision
    active_model_name() makes, used by /models doctor to explain it."""
    if model_name not in AUTO_ROUTING_MODES:
        return model_name, "you picked it (pinned); routing steps in only when it fails"
    _NEEDS_OVERRIDE.append(needs)
    try:
        if model_name == "online":
            pick = _route_pick(ONLINE_ORDER, needs, allow_local=False)
            return (pick, routing.why_line(sys.modules[__name__], pick, needs)) if pick else \
                (ONLINE_ORDER[0], "nothing online is set up yet - add a key for it")
        pick, why = _smart_pick(needs)
        if pick in MODELS:
            fit, short = routing.fits(routing.abilities(sys.modules[__name__], pick), needs)
            if not fit:
                why += "; but it %s - no ready model does better (set one up in Settings > Connections)" % short
        return pick, why
    finally:
        _NEEDS_OVERRIDE.pop()


def active_model_name() -> str:
    """The provider actually in use - SMART resolves to the best available for THIS task."""
    if model_name == "online":
        pick = _route_pick(ONLINE_ORDER, current_needs(), allow_local=False)
        # Nothing is configured yet. Name one anyway so the error tells the user exactly
        # what to set, instead of silently reaching for a local model they may not have.
        return pick or ONLINE_ORDER[0]
    if model_name != "smart":
        return model_name
    return _smart_pick(current_needs())[0]


def smart_report() -> str:
    marks = []
    for candidate in SMART_ORDER:
        state = "used-up" if candidate in _SMART_FAILED else ("ready" if provider_configured(candidate) else "-")
        marks.append("%s=%s" % (candidate, state))
    # Only claim "smart" when Loki is actually in smart mode; otherwise report the
    # pinned model, which is what the user chose.
    headline = ("smart uses %s" % active_model_name()) if model_name == "smart"         else ("model: %s" % model_name)
    return "%s | %s" % (headline, ", ".join(marks))


AUTO_ROUTING_MODES = ("smart", "online")


def _mark_smart_failure(provider: str = "") -> None:
    """Mark the provider that FAILED as used-up (auto-routing modes only).

    Pass the provider the request was actually sent to. Re-resolving it here with
    active_model_name() is wrong once anything has already been marked: it names the
    NEXT provider, which then gets marked too and is skipped without ever being tried.
    """
    if model_name in AUTO_ROUTING_MODES:
        failed = provider or active_model_name()
        _SMART_FAILED.add(failed)
        _FAILED_AT[failed] = time.time()


# A provider being out of quota or rate-limited must NOT end the run - we move to
# the next available provider and carry on. These markers tell an "out of
# allowance" refusal apart from a genuine bug.
_LIMIT_MARKERS = ("429", "402", "413", "quota", "rate limit", "rate_limit",
                  "rate-limit", "resource_exhausted", "too large", "exceeded",
                  "insufficient", "credit", "billing",
                  # A provider that refuses the request itself (an over-long tool
                  # list, an unsupported field) is just as unusable as an exhausted
                  # quota: the run must move on rather than end. Matching the
                  # rendered "HTTP 400" keeps this off unrelated numbers.
                  "http 400", "http 422",
                  # Ollama is running but the model was never pulled.
                  "[model missing]")


def _is_limit_error(exc) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _LIMIT_MARKERS)


# A provider that cannot run at all - most often a coding CLI that is installed but
# NOT signed in - must be skipped like an exhausted quota, never treated as a fatal
# bug. Otherwise one unusable provider late in the order (claude-code) kills a turn
# that a ready provider further down (local Ollama) would have finished.
_AGENT_UNAVAILABLE_MARKERS = ("cliagenterror", "not signed in", "not logged in",
                              "no cli agent", "could not find the cli")


def _is_agent_unavailable(exc) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _AGENT_UNAVAILABLE_MARKERS)


# A rate limit clears on its own and is worth retrying; a spent QUOTA or a billing
# refusal will not, so retrying one only delays the failover by the whole backoff
# (1.5 + 3 + 6 + 12s). Deliberately no bare "429"/"exceeded" here, so a genuine
# transient rate limit still gets its retries.
_QUOTA_MARKERS = ("quota", "billing", "insufficient", "credit", "resource_exhausted",
                  "free-models-per-day")


def _is_quota_error(exc) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _QUOTA_MARKERS)


# A provider whose key is wrong/revoked, or whose endpoint cannot be reached, cannot
# serve this turn either. In an auto-routing mode that is a reason to move on, not to
# end the turn while other providers are ready. (A PINNED provider still surfaces the
# error: the user chose it, and should be told its key is wrong.)
_AUTH_MARKERS = ("http 401", "http 403", "invalid api key", "incorrect api key",
                 "invalid_api_key", "unauthorized", "authentication", "permission denied")


def _is_auth_error(exc) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _is_unreachable(exc) -> bool:
    return str(exc).startswith("[model unavailable]")


def _is_flaky(exc) -> bool:
    """An answer with nothing in it, or no answer in time: another provider may do better."""
    text = str(exc).lower()
    return "empty reply" in text or "no choices" in text or "timed out" in text


def failover_reason(exc) -> str:
    """A short, honest label for why a provider was skipped."""
    if _is_agent_unavailable(exc):
        return "agent not available"
    if _is_quota_error(exc):
        return "quota spent"
    if _is_auth_error(exc):
        return "key rejected"
    if _is_unreachable(exc):
        return "unreachable"
    if condenser.is_context_error(str(exc)):
        return "context too long"
    if _is_flaky(exc):
        return "empty reply" if "empty" in str(exc).lower() else "no answer in time"
    if _is_limit_error(exc):
        return "rate/size limit"
    return "error"


# Some providers (NVIDIA NIM's free tier, 2026-10-18) answer an over-long request with a bare
# "HTTP 400: The request could not be completed" - no word about context. On a big request that
# is almost always the size, so treat it like a context error: condense, then fail over.
SIZE_400_TOKENS = int(os.getenv("LOKI_SIZE_400_TOKENS", "24000") or 24000)


def _maybe_size_error(exc, messages=None, tools=None) -> bool:
    text = str(exc)
    if not re.search(r"HTTP (400|413|422)\b", text):
        return False
    try:
        tokens = routing.estimate_tokens(list(messages or []), len(json.dumps(tools or [])))
    except Exception:  # noqa: BLE001
        return False
    return tokens >= SIZE_400_TOKENS


def should_fail_over(exc, auto_routing: bool) -> bool:
    """True when the error means 'try another provider', not 'this is a bug'."""
    if _is_limit_error(exc) or _is_agent_unavailable(exc):
        return True
    return auto_routing and (_is_auth_error(exc) or _is_unreachable(exc) or _is_flaky(exc)
                             or condenser.is_context_error(str(exc)))


# The route each request actually took: which provider failed, why, and where the turn
# went next. Reset per request, so "why did Loki use X?" has a recorded answer.
ROUTE_TRACE: list = []

# Provider error bodies sometimes echo part of the key; the trace leaves the process
# (the bridge serves it on /health), so key-shaped strings are masked first.
_SECRET_SHAPES = re.compile(r"(sk|gsk|xai|pk|rk|AIza)[-_A-Za-z0-9]{12,}|Bearer\s+[-._A-Za-z0-9]{12,}")


def redact_secrets(text: str) -> str:
    return _SECRET_SHAPES.sub("[redacted]", str(text))


# ---------------------------------------------------------------------------
# Cost: usage per request, and a cap that applies ONLY to metered providers.
# ---------------------------------------------------------------------------
# Free tiers, local models and the flat-rate subscription CLIs keep running unbounded
# (LOKI_MAX_TURNS still applies to everything). A provider billed per token cannot run
# away: after LOKI_PAID_MAX_CALLS model calls in one request, the request stops and says
# why. Override the lists with LOKI_PAID_PROVIDERS / LOKI_FREE_PROVIDERS (comma lists).
_METERED_DEFAULT = {"gpt", "gpt6-luna", "claude", "deepseek", "deepseek-4.1", "cerebras", "aion",
                    "ollama-cloud", "nebius", "scaleway", "hyperbolic", "novita", "fireworks",
                    "dashscope", "deepinfra", "chutes", "baseten", "inference-net", "ai21", "upstage"}
PAID_MAX_CALLS = int(os.getenv("LOKI_PAID_MAX_CALLS", "40"))
# Spending policy (docs/VISION.md 6): automatic routing never picks a paid provider unless
# LOKI_ALLOW_PAID=1, and paid use stops for the day at LOKI_DAILY_USD_LIMIT (from the usage
# ledger), even for a paid model you picked yourself.
ALLOW_PAID = str(os.getenv("LOKI_ALLOW_PAID", "0")).strip().lower() in ("1", "true", "yes", "on")
try:
    DAILY_USD_LIMIT = float(os.getenv("LOKI_DAILY_USD_LIMIT", "1.0") or 1.0)
except ValueError:
    DAILY_USD_LIMIT = 1.0


def paid_spent_today() -> float:
    try:
        return round(sum(e.get("cost", 0.0) for e in USAGE.entries(time.time() - 86400)), 4)
    except Exception:  # noqa: BLE001 - no ledger yet means nothing spent
        return 0.0


def paid_allowed_automatically() -> bool:
    return ALLOW_PAID and paid_spent_today() < DAILY_USD_LIMIT
REQUEST_USAGE: dict = {}   # provider -> {"calls", "prompt_tokens", "completion_tokens"}


def is_metered(name: str) -> bool:
    """True when every call to this provider costs money."""
    if name in _csv_env("LOKI_FREE_PROVIDERS"):
        return False
    if name in _csv_env("LOKI_PAID_PROVIDERS") or name in _METERED_DEFAULT:
        return True
    cfg = MODELS.get(name)
    if cfg is not None and "openrouter.ai" in cfg.base_url:
        return not str(cfg.model).endswith(":free")
    return False


def _paid_calls() -> int:
    return sum(u["calls"] for name, u in REQUEST_USAGE.items() if is_metered(name))


def _record_request_usage(provider: str, response) -> None:
    entry = REQUEST_USAGE.setdefault(provider, {"calls": 0, "prompt_tokens": 0,
                                                "completion_tokens": 0, "cached_tokens": 0})
    entry["calls"] += 1
    usage = getattr(response, "usage", None)
    for key in ("prompt_tokens", "completion_tokens"):
        value = getattr(usage, key, None) if usage is not None else None
        if isinstance(value, int):
            entry[key] += value
    cached = context_budget.cached_tokens(usage)
    if cached:
        entry["cached_tokens"] = entry.get("cached_tokens", 0) + cached


def usage_summary() -> str:
    """'openrouter 3 calls, 4.1k tokens' - one line per request, for the user and the log."""
    parts = []
    for name, u in REQUEST_USAGE.items():
        tokens = u["prompt_tokens"] + u["completion_tokens"]
        text = "%s %d call%s" % (name, u["calls"], "" if u["calls"] == 1 else "s")
        if tokens:
            text += ", %s tokens" % (("%.1fk" % (tokens / 1000)) if tokens >= 1000 else tokens)
            if u.get("cached_tokens") and u["prompt_tokens"]:
                text += " (%d%% of the prompt from the cache)" % round(100 * u["cached_tokens"] / u["prompt_tokens"])
        if is_metered(name):
            text += " (paid)"
        parts.append(text)
    return "; ".join(parts)


def failover_target(spent: str = "") -> str:
    """Mark `spent` (the provider that just failed) used-up; return the next usable one.

    Returns "" when no other CONFIGURED provider is left, so the caller surfaces the
    original error (e.g. "quota spent") instead of a misleading one from a provider the
    user never set up (e.g. "Ollama is not running").

    Online mode stays online: it must never fall through to a local model.
    """
    global model_name
    current = spent or active_model_name()
    _SMART_FAILED.add(current)
    _FAILED_AT[current] = time.time()
    if model_name not in AUTO_ROUTING_MODES:
        # The chosen provider is spent; pick automatically from here so the task
        # keeps going instead of dying on one exhausted key.
        model_name = "smart"
    nxt = active_model_name()
    if nxt == current or nxt in _SMART_FAILED or not provider_configured(nxt):
        return ""
    return nxt


# ---------------------------------------------------------------------------
# Memory and the plan: two markdown files in the prompt + tools to edit them.
# ---------------------------------------------------------------------------

def load_memory() -> str:
    """Who the owner is, for every prompt - bounded (memory.profile_block); the rest of memory
    comes per request through memory.pack."""
    try:
        text = memory.profile_block(DATA_DIR, MEMORY_FILE)["text"]
    except Exception:  # noqa: BLE001
        text = MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.is_file() else ""
    return text or "(nothing saved yet)"


def save_memory(fact: str) -> str:
    """One lasting fact about the user - the semantic tier of memory.py."""
    result = memory.remember("semantic", fact, root=DATA_DIR)
    if not result.get("ok"):
        return "could not save: %s" % result.get("error", "unknown error")
    refresh_system_prompt()  # take effect this session, not next restart
    return "saved: %s" % result["saved"]


def todo_list() -> str:
    if not PLAN_FILE.is_file():
        return "(no plan yet - use todo_add to start one)"
    text = PLAN_FILE.read_text(encoding="utf-8").strip()
    return text or "(empty plan)"


def todo_clear() -> str:
    if PLAN_FILE.is_file():
        PLAN_FILE.unlink()
    tracker = DATA_DIR / "task_tracker.json"
    if tracker.is_file():
        tracker.unlink()
    return "plan cleared"


STATE_FILE = DATA_DIR / "project_state.json"


def project_state_text() -> str:
    """The resumable project state (blueprint 7.3) rendered as text."""
    return project_state.render(project_state.load(STATE_FILE))


def project_state_update(action: str = "view", field: str = "", value: str = "") -> str:
    """Read or update the RESUMABLE PROJECT STATE so work survives a restart.

    action: view | add | set | reset
    field:  objective | phase | completed | files_changed | tests | known_issues |
            decisions | blockers | next_actions
    """
    data = project_state.load(STATE_FILE)
    action = (action or "view").strip().lower()
    if action == "view":
        return project_state.render(data)
    if action == "reset":
        project_state.save(STATE_FILE, project_state.empty())
        return "project state reset"
    if action == "add":
        note = project_state.add(data, field, value)
        project_state.save(STATE_FILE, data)
        return note + chr(10) + project_state.render(data)
    if action == "set":
        note = project_state.set_field(data, field, value)
        project_state.save(STATE_FILE, data)
        return note + chr(10) + project_state.render(data)
    return "unknown action: %s (use view, add, set or reset)" % action


SESSIONS_FILE = DATA_DIR / "agent_sessions.json"


def _sessions_save(data: dict) -> None:
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def agent_sessions(action: str = "list", name: str = "", session_id: str = "",
                   status: str = "", task: str = "", workspace: str = "",
                   agent: str = "loki") -> str:
    """Track concurrent agent sessions: who is working, blocked or idle.

    The Herdr idea (herdr.dev) and the blueprint's multi-agent/worker registry: a shared
    list of sessions, each with a workspace, the agent driving it and a status, so a run (or
    a human) can see who is doing what and who is stuck. action: list | add | update | close.
    """
    data = sessions.empty()
    if SESSIONS_FILE.is_file():
        try:
            loaded = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (ValueError, OSError):
            data = sessions.empty()
    action = (action or "list").strip().lower()
    if action == "add":
        session = sessions.add(data, name, workspace, agent, status or "working", task)
        _sessions_save(data)
        return "started %s (%s)" % (session["name"], session["id"]) + chr(10) + sessions.render(data)
    if action in ("update", "close"):
        key = session_id or name
        ok = sessions.close(data, key) if action == "close" else sessions.update(data, key, status, task)
        if not ok:
            return "no session named or id: " + key
        _sessions_save(data)
        return ("closed " if action == "close" else "updated ") + key + chr(10) + sessions.render(data)
    return sessions.render(data)


VAULT_SEED = ROOT / "data" / "api_vault.json"
VAULT_USER = DATA_DIR / "api_vault_extra.json"


def _vault_merged() -> dict:
    merged = api_vault.load(VAULT_SEED)
    extra = api_vault.load(VAULT_USER)
    seen = {entry.get("id") for entry in merged.get("entries", [])}
    for entry in extra.get("entries", []):
        if entry.get("id") not in seen:
            merged["entries"].append(entry)
    return merged


def api_vault_lookup(action: str = "search", query: str = "", category: str = "",
                     auth: str = "", name: str = "", url: str = "", provider: str = "",
                     docs: str = "", limit: int = 25) -> str:
    """Search the API Vault, or add to it.

    The blueprint's API Vault (3.3): a searchable index of APIs - what they do, where to
    reach them and whether they need a key - so Loki can propose one before connecting it.
    The shipped catalog is read-only; 'add' appends to the caller's own extra file.
    action: search | stats | add
    """
    action = (action or "search").strip().lower()
    if action == "add":
        if not name.strip():
            return "add needs a name"
        extra = api_vault.load(VAULT_USER)
        entry = api_vault.add(extra, name, url, provider, [category] if category else ["custom"],
                              auth or "unknown", docs, "manual")
        api_vault.save(VAULT_USER, extra)
        return "added %s (%s) to the vault" % (entry["name"], entry["id"])
    merged = _vault_merged()
    if action == "stats":
        counts = api_vault.stats(merged)
        return chr(10).join(["API Vault: %d entries" % counts["total"],
                        "by auth: %s" % counts["by_auth"],
                        "by source: %s" % counts["by_source"]])
    hits = api_vault.search(merged, query, category, auth, limit)
    title = "API Vault - %d match(es)%s" % (len(hits), (" for '%s'" % query) if query else "")
    return api_vault.render(hits, title=title)


def review_repository(path: str = ".") -> str:
    """Review a LOCAL repository folder read-only: size, licence, languages, entry points.

    The blueprint's repository browser (5.1). Nothing is executed or installed - the
    review only reads files, so a listed repository never becomes runnable (5.2).
    """
    try:
        target = resolve_in_workspace(path or ".")
    except ValueError:
        target = Path(path or ".").expanduser()
    return repo_review.render(repo_review.review(target))


def forecast_series(values: list, horizon: int = 12) -> str:
    """Forecast the next values of a numeric series (TimesFM-3 when installed)."""
    import forecast  # pylint: disable=import-outside-toplevel
    try:
        numbers = [float(v) for v in values]
    except (TypeError, ValueError):
        return "error: values must be a list of numbers (oldest first)"
    if len(numbers) < 3:
        return "error: give at least 3 values"
    f = forecast.forecast(numbers, int(horizon or 12))
    fmt = lambda xs: ", ".join("%.4g" % x for x in xs)  # noqa: E731
    return ("forecast (%s) for the next %d steps:\nmedian: %s\n10%%: %s\n90%%: %s"
            % (f["backend"], len(f["median"]), fmt(f["median"]), fmt(f["q10"]), fmt(f["q90"])))


def generate_media(prompt: str, kind: str = "image", model: str = "", aspect_ratio: str = "16:9") -> str:
    """Make an image (or a video) with Higgsfield, saved in the workspace. Spends the user's credits."""
    import higgsfield  # pylint: disable=import-outside-toplevel
    r = higgsfield.generate(prompt, kind=kind, application=model, workspace=WORKSPACE, aspect_ratio=aspect_ratio)
    if not r.get("ok"):
        return "error: " + str(r.get("error"))
    where = ", ".join(r["files"]) if r["files"] else ", ".join(r["urls"])
    return "made with Higgsfield (%s): %s" % (r["application"], where or "no files came back")


# --- built-in CRM (engine/crm.py; the database is DATA_DIR/crm.sqlite3) ---------------
_CRM_STORE = None


def crm_store():
    """The CRM, opened on first use (tests replace loki._CRM_STORE with a temporary one)."""
    global _CRM_STORE
    if _CRM_STORE is None:
        import crm  # pylint: disable=import-outside-toplevel
        _CRM_STORE = crm.CRM(DATA_DIR / "crm.sqlite3")
    return _CRM_STORE


def _crm_fields(fields) -> dict:
    if isinstance(fields, str):
        try:
            fields = json.loads(fields or "{}")
        except ValueError:
            raise ValueError("fields must be a JSON object like {\"name\": \"Ada\"}") from None
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object like {\"name\": \"Ada\"}")
    return fields


def _crm_call(fn) -> str:
    import crm  # pylint: disable=import-outside-toplevel
    try:
        return fn(crm)
    except (crm.CRMError, ValueError, TypeError) as exc:
        return "error: %s" % exc


def crm_add(type: str, fields=None) -> str:  # noqa: A002 - the model's word for it
    """Add a contact, company, deal, interaction or task to LOKI's CRM."""
    return _crm_call(lambda crm: "added " + crm.render_rows(
        [dict(crm_store().add(type, _crm_fields(fields)), type=crm.table_name(type))]))


def crm_update(type: str, id: int, fields=None) -> str:  # noqa: A002
    """Change fields of one CRM record (e.g. a deal's stage, a task's done)."""
    return _crm_call(lambda crm: "updated " + crm.render_rows(
        [dict(crm_store().update(type, int(id), _crm_fields(fields)), type=crm.table_name(type))]))


def crm_find(query: str = "", type: str = "", limit: int = 25) -> str:  # noqa: A002
    """Search the CRM; with no query, list the records of one type."""
    def go(crm):
        if not str(query or "").strip():
            if not type:
                return "error: give a query, or a type to list"
            table = crm.table_name(type)
            return crm.render_rows([dict(r, type=table) for r in crm_store().list(table, limit)])
        return crm.render_rows(crm_store().find(query, type, int(limit or 25)))
    return _crm_call(go)


def crm_log(summary: str, kind: str = "note", contact_id: int = 0, company_id: int = 0, deal_id: int = 0,
            at: str = "") -> str:
    """Record a note, call, email or meeting against a contact, company or deal."""
    return _crm_call(lambda crm: "logged " + crm.render_rows([dict(crm_store().log(
        {"summary": summary, "kind": kind, "contact_id": contact_id, "company_id": company_id,
         "deal_id": deal_id, "at": at}), type="interactions")]))


def crm_pipeline() -> str:
    """Deals per stage, open and won value, win rate and overdue tasks."""
    return _crm_call(lambda crm: crm.render_pipeline(crm_store().pipeline()))


# --- scraping (conductor.scrape: Scrapling, else read_web) and Remotion videos ------------
def scrape(url: str, crawl: bool = False, max_pages: int = 20, dynamic: bool = False) -> str:
    """One page as markdown, or crawl a site into scraped/<domain>/ in the workspace."""
    out = CONDUCTOR.scrape(str(url or ""), "", crawl=bool(crawl), max_pages=int(max_pages or 20),
                           workspace=WORKSPACE, dynamic=bool(dynamic))
    if str(out).startswith("error: no scraper is ready") and not _private_host(str(url or "")):
        # No add-on: LOKI reads the page itself (web_reader.py, Scrapling's core ported).
        text = web_reader.read(str(url or ""))
        if not text.startswith("error:"):
            return text + ("\n(Crawling a whole site needs the Scrapling add-on; only this page was read.)"
                           if crawl else "")
    return out


def video_project(name: str) -> str:
    """Scaffold a blank Remotion project in videos/<name> (npx create-video)."""
    try:
        target = resolve_in_workspace(str(Path("videos") / Path(str(name or "video")).name))
    except ValueError as exc:
        return "error: %s" % exc
    result = CONDUCTOR._runner("video", {"op": "scaffold", "dir": str(target)}, timeout=1800)  # pylint: disable=protected-access
    if not result.get("ok"):
        return "error: " + str(result.get("error"))
    return "Remotion project ready in %s (entry %s)%s. Licence: free for individuals and companies up to 3 " \
           "employees (remotion.dev/license)." % (result.get("dir"), result.get("entry", "src/index.ts"),
                                                  ("; " + result["note"]) if result.get("note") else "")


def render_video(project_dir: str, composition: str, out: str = "", props=None, entry: str = "") -> str:
    """Render a Remotion composition to an MP4 in the workspace."""
    try:
        project = resolve_in_workspace(project_dir)
        target = resolve_in_workspace(out or str(Path("videos") / (str(composition or "video") + ".mp4")))
        if isinstance(props, str) and props.strip():
            props = json.loads(props)
    except ValueError as exc:
        return "error: %s" % exc
    if not str(composition or "").strip():
        return "error: render_video needs the composition id (see src/Root.tsx)"
    job = {"op": "render", "project_dir": str(project), "composition": str(composition).strip(),
           "out": str(target), "props": props if isinstance(props, dict) else {}, "entry": str(entry or "")}
    result = CONDUCTOR._runner("video", job, timeout=int(os.getenv("LOKI_VIDEO_TIMEOUT", "1800") or 1800))  # pylint: disable=protected-access
    if not result.get("ok"):
        return "error: " + str(result.get("error"))
    return "rendered %s (%d bytes)" % (result.get("file"), int(result.get("bytes") or 0))


def game_engine_guide() -> str:
    """How to make a game with LOKI's own Pixel Engine: the API, the workflow and a full example."""
    ui = REPO_ROOT.parent / "app" / "ui" if (REPO_ROOT.parent / "app" / "ui").is_dir() else REPO_ROOT / "app" / "ui"
    try:
        src = (ui / "engine" / "pixel_engine.js").read_text(encoding="utf-8")
        api = src.split('"use strict";', 1)[0]
        example = (ui / "games" / "fox_berries" / "game.js").read_text(encoding="utf-8")
    except OSError as exc:
        return "error: the game engine files are missing (%s)" % exc
    return ("LOKI PIXEL ENGINE - make games that run inside LOKI (Settings > Play), in a pixel "
            "cel-shaded look.\n\nWORKFLOW: write ONE file games/<name>/game.js in the workspace (name: lowercase "
            "letters, digits, _ or -). Its FIRST line must be a comment '// <Title> - <one line about it>'. Wrap "
            "everything in an IIFE, get the canvas with document.getElementById(\"game\"), only use window.PixelEngine "
            "(no imports, no network, no other files). Keep it small and fun; controls on the HUD. Then tell the user "
            "to open Settings > Play.\n\nAPI:\n" + api + "\nFULL EXAMPLE (games/fox_berries/game.js):\n" + example)


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


import agent_folders  # noqa: E402  (folders agents may READ besides the workspace - owner 2026-10-22)


def agent_roots() -> list:
    """[(label, folder)] the read tools may use besides WORKSPACE: LOKI's folder, its data folder,
    ~/LOKI Projects and the owner's extra folders (LOKI_AGENT_FOLDERS / settings "agent_folders")."""
    return agent_folders.roots(REPO_ROOT, DATA_DIR, settings_file=DATA_DIR / "loki_settings.json")


def resolve_readable(name: str) -> Path:
    """A path to READ: the workspace as before, or an agent folder (never a secret, never a system folder)."""
    return agent_folders.resolve_readable(name, WORKSPACE, agent_roots(), data_dir=DATA_DIR)


def folders_tool() -> str:
    """The folders an agent may read (and the one it may write)."""
    return agent_folders.describe(WORKSPACE, agent_roots(), sys.executable)


# ---------------------------------------------------------------------------
# Local tools: read the code, edit it precisely, search it, run it, verify it.
# ---------------------------------------------------------------------------

def list_files() -> str:
    return "\n".join(p.name for p in WORKSPACE.iterdir()) or "(empty)"


def list_tree(subdir: str = ".", max_depth: int = 3) -> str:
    base = resolve_readable(subdir)   # the workspace, or a folder agents may read (agent_folders)
    if not base.is_dir():
        return "error: no folder %s" % subdir
    away = agent_folders.outside(base, WORKSPACE)
    lines = []

    def walk(d: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            return
        for e in entries:
            if e.name in (".git", "__pycache__", ".venv", ".godot", "node_modules"):
                continue
            if away and agent_folders.secret_name(Path(e.name)):
                continue   # outside the workspace secrets are not even listed
            lines.append(prefix + e.name + ("/" if e.is_dir() else ""))
            if e.is_dir():
                walk(e, prefix + "   ", depth + 1)

    walk(base, "", 1)
    return "\n".join(lines) if lines else "(empty)"


def read_file(filename: str, start_line: int = 0, end_line: int = 0) -> str:
    """The file's text; with start_line/end_line (end -1 = to the end) numbered lines of that
    range (OpenHands' view). A big file read whole shows its first lines numbered, with the
    line count, so the model can ask for exactly the range it needs. Outside the workspace it reads
    LOKI's folder, its data folder, ~/LOKI Projects and the owner's extra folders (absolute paths)."""
    path = resolve_readable(filename)
    if not path.is_file():
        return f"error: no {filename}"
    try:
        if int(start_line or 0) or int(end_line or 0):
            return file_editor.view(path, int(start_line or 1), int(end_line or -1), label=filename)
    except (file_editor.EditError, ValueError) as exc:
        return "error: %s" % exc
    text = path.read_text(encoding="utf-8")
    if len(text) <= MAX_OUTPUT:
        return text
    lines = text.splitlines()
    shown, size = [], 0
    for i, line in enumerate(lines, 1):
        size += len(line) + 8
        if size > MAX_OUTPUT - 400:
            break
        shown.append("%6d\t%s" % (i, line))
    return ("%s has %d lines (%d characters) - too long to show whole. Lines 1-%d below; read the "
            "rest with start_line/end_line, or search_files for what you need:\n%s"
            % (filename, len(lines), len(text), len(shown), "\n".join(shown)))


MEDIA_TOOL_ALIASES = {"generate_image": "image", "make_image": "image", "create_image": "image", "image_gen": "image",
                      "draw": "image", "text_to_image": "image", "web_search": "research", "search_web": "research"}
MEDIA_SUFFIXES = {".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
                  ".gif": (b"GIF8",), ".webp": (b"RIFF",), ".mp4": (), ".mov": (), ".webm": (b"\x1a\x45\xdf\xa3",),
                  ".mp3": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), ".wav": (b"RIFF",), ".pdf": (b"%PDF",),
                  ".zip": (b"PK",)}


def media_check(filename: str) -> str:
    """'media x: OK' when a picture/video/sound file really is one, 'media x: INVALID - ...' when
    it is text with a picture's name (a small model 'saving an image' with write_file)."""
    path = resolve_in_workspace(filename)
    suffix = path.suffix.lower()
    try:
        head = path.read_bytes()[:16]
    except OSError as exc:
        return "media %s: INVALID - cannot read it (%s)" % (filename, exc)
    if len(head) < 4:
        return "media %s: INVALID - the file is empty" % filename
    magics = MEDIA_SUFFIXES.get(suffix, ())
    if suffix in (".mp4", ".mov"):
        ok = head[4:8] == b"ftyp"
    else:
        ok = not magics or any(head.startswith(m) for m in magics)
    if ok:
        return "media %s: OK (a real %s file)" % (filename, suffix.lstrip("."))
    return ("media %s: INVALID - this is not a real %s file (it holds text). Pictures are made with "
            "conductor(role='image', task='<what to draw>'), not write_file." % (filename, suffix.lstrip(".").upper()))


def write_file(filename: str, content: str) -> str:
    if Path(str(filename)).suffix.lower() in MEDIA_SUFFIXES:
        return ("error: write_file writes text, so %s would not be a real %s. To make a picture call "
                "conductor(role='image', task='<what to draw>') - it saves the real file in images/ and "
                "says where. Videos, sounds and PDFs come from their own tools too."
                % (filename, Path(str(filename)).suffix.lstrip(".").upper()))
    path = resolve_in_workspace(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    note = _check_written(filename)
    return f"wrote {filename}" + (chr(10) + note if note else "")


def append_file(filename: str, content: str) -> str:
    path = resolve_in_workspace(filename)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)
    note = _check_written(filename)
    return f"appended to {filename}" + (chr(10) + note if note else "")


def edit_file(filename: str, old: str, new: str, replace_all: bool = False) -> str:
    """Replace text that appears EXACTLY ONCE (OpenHands str_replace); replace_all=true for every one."""
    path = resolve_in_workspace(filename)
    if not path.is_file():
        return f"error: no {filename}"
    try:
        snippet, count = file_editor.str_replace(path, old, new, replace_all=str(replace_all).lower()
                                                 in ("1", "true", "yes"), label=filename)
    except file_editor.EditError as exc:
        return "error: %s" % exc
    note = _check_written(filename)
    return (f"edited {filename} ({count} replacement(s))" + (chr(10) + note if note else "")
            + chr(10) + snippet + "Review the change; edit again if it is not right (undo_edit reverts it).")


def insert_lines(filename: str, insert_line: int, text: str) -> str:
    """Insert text after line N (0 = at the top) - OpenHands insert."""
    path = resolve_in_workspace(filename)
    if not path.is_file():
        return f"error: no {filename}"
    try:
        snippet = file_editor.insert(path, int(insert_line), text, label=filename)
    except (file_editor.EditError, ValueError) as exc:
        return "error: %s" % exc
    note = _check_written(filename)
    return (f"inserted into {filename} after line {int(insert_line)}" + (chr(10) + note if note else "")
            + chr(10) + snippet + "Check the indentation and that no line is doubled.")


def undo_edit(filename: str) -> str:
    """Put a file back as it was before the last edit_file / insert_lines made in this session."""
    try:
        return file_editor.undo(resolve_in_workspace(filename), label=filename)
    except file_editor.EditError as exc:
        return "error: %s" % exc


def search_files(pattern: str, subdir: str = ".", glob: str = "*") -> str:
    base = resolve_readable(subdir)   # the workspace, or a folder agents may read (absolute path)
    rx = re.compile(pattern)
    hits = []
    away = agent_folders.outside(base, WORKSPACE)
    if away:   # another folder: skip venvs/.git/node_modules, big files and every secret
        paths = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in agent_folders.SKIP_DIRS
                                 and not agent_folders.secret_name(Path(d)))
            paths += [Path(dirpath, f) for f in sorted(filenames) if Path(f).match(glob)
                      and not agent_folders.secret_name(Path(f))]
    else:
        paths = sorted(base.rglob(glob))
    for path in paths:
        if not path.is_file():
            continue
        try:
            if away and (path.stat().st_size > agent_folders.SEARCH_MAX_BYTES
                         or agent_folders.is_secret(path, base, DATA_DIR)):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                rel = agent_folders.show(path, WORKSPACE)
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


def godot_available() -> bool:
    """True when GODOT_EXE names an executable that actually exists."""
    exe = str(GODOT_EXE or "").strip()
    return bool(exe) and (Path(exe).is_file() or bool(shutil.which(exe)))


# Said instead of a verdict when Godot cannot be started. Without this a missing engine
# read as "INVALID - fix these errors", and the model "fixed" files that were fine.
NOT_VERIFIED = "NOT VERIFIED"


def _godot_missing(tool: str, filename: str) -> str:
    return ("%s %s: %s - the Godot executable was not found (%s). This says nothing about "
            "the file itself; do not change it because of this. Set GODOT_EXE in "
            "harness_data/.env to enable checks." % (tool, filename, NOT_VERIFIED,
                                                    GODOT_EXE or "GODOT_EXE is unset"))


def validate_scene(filename: str, timeout: int = 90) -> str:
    """Run a scene headless and report whether Godot loaded it without errors."""
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")
    if not godot_available():
        return _godot_missing("validate_scene", filename)
    # run_godot uses shlex.split(posix=False), which keeps literal quotes,
    # so the res:// path must be passed unquoted here.
    res = run_godot("--headless --quit-after 1 " + filename, timeout=timeout)
    low = res.lower()
    bad = "error:" in low or "failed loading" in low or "parse error" in low
    verdict = "INVALID - fix these errors:" if bad else "valid - Godot loaded it cleanly."
    return chr(10).join(["validate_scene %s: %s" % (filename, verdict), res])


def _elide(text: str, limit: int = MAX_OUTPUT) -> str:
    """Bound a tool result, keeping its head AND tail, and SAY what was dropped.

    SWE-agent's point: the boundary between agent and computer is a design surface. A model
    handed 40k characters of file loses the thread; a model told exactly what was elided can
    ask for the rest. The tail is kept because errors and totals live there.
    """
    body = str(text)
    if len(body) <= limit:
        return body
    try:   # session 27: Headroom's crushers keep errors/summaries/telling rows (engine/compress.py)
        import compress as _compress  # pylint: disable=import-outside-toplevel
        crushed = _compress.compress(body, limit)
        if crushed:
            return crushed
    except Exception:  # noqa: BLE001 - never let compression break a tool result
        pass
    half = max(1, limit // 2)
    head, tail = body[:half], body[-half:]
    dropped = body[len(head):len(body) - len(tail)]
    marker = (chr(10) + "...[%d characters, about %d lines, elided - read a smaller range"
              " or use search_files to see them]..." + chr(10)) % (len(dropped), dropped.count(chr(10)) + 1)
    return head + marker + tail


def _shorten(text: str) -> str:
    return _elide(text)


def _check_written(filename: str) -> str:
    """An immediate syntax verdict for the file just written, so the model sees its own
    mistake NOW instead of at DONE (SWE-agent's check-on-edit). In-process and instant for
    the types LOKI can read back; .gd still goes to Godot."""
    if str(filename).endswith(".gd"):
        return check_script(filename)
    try:
        text = resolve_in_workspace(filename).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "could not re-read %s: %s" % (filename, exc)
    low = str(filename).lower()
    try:
        if low.endswith(".json"):
            json.loads(text)
            return "json ok"
        if low.endswith(".py"):
            ast.parse(text)
            return "python ok"
    except Exception as exc:  # noqa: BLE001 - a broken file is exactly what we want to catch
        return "SYNTAX ERROR in %s: %s" % (filename, str(exc)[:200])
    return ""


def check_script(filename: str) -> str:
    """Compile-check a GDScript file with Godot and report any parse errors."""
    if not filename.startswith("res://"):
        filename = "res://" + filename.lstrip("/")
    if not godot_available():
        return _godot_missing("check_script", filename)
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
    if not godot_available():
        return _godot_missing("play_scene", filename)
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


# ---------------------------------------------------------------------------
# Command policy: a structured guard in front of the run_command shell.
# ---------------------------------------------------------------------------
# run_command hands a raw string to the OS shell. Before it does, the command is
# normalised and checked against a policy of known-destructive shapes: disk and
# boot tampering, wholesale deletion of a drive or root, account and registry
# edits, and downloading remote code straight into an interpreter. The policy is a
# pure function so it is unit tested. It is a GUARD, not a full sandbox - a
# determined command can still be built - so run_command also stays behind the
# approval gate. Set LOKI_COMMAND_POLICY=0 to disable it in a trusted context.

_DESTRUCTIVE_SNIPPETS = (
    "rm -rf /", "rm -fr /", "rm -rf ~",
    "del /f /s /q", "del /s /q", "rd /s /q", "rmdir /s /q",
    "format ", "mkfs", "diskpart", "fdisk", "wipefs",
    "dd if=", "dd of=/dev/", "> /dev/sda", "> /dev/nvme",
    ":(){", ":() {",
    "shutdown", "reboot", "poweroff",
    "cipher /w", "vssadmin", "bcdedit", "bootrec",
    "takeown", "icacls", "reg delete", "reg add",
    "net user", "net localgroup", "netsh advfirewall",
    "chmod -r 777 /", "chown -r", "chmod 777 /",
)

_REMOTE_EXEC_TOKENS = (
    "| sh", "| bash", "| zsh", "| python", "| perl", "| iex",
    "invoke-expression", "iex(", "eval(",
)


def command_policy(command: str) -> tuple:
    """Return (allowed, reason) for a shell command string. Pure, no side effects.

    A blank command is refused. A command whose whitespace-normalised text contains
    a known-destructive shape, or that pipes remote content into an interpreter, is
    refused with a reason. Everything else is allowed.
    """
    if str(os.getenv("LOKI_COMMAND_POLICY", "1")).strip().lower() in ("0", "false", "off", "no"):
        return True, "policy disabled"
    text = " ".join(str(command or "").split()).lower()
    if not text:
        return False, "empty command"
    for snippet in _DESTRUCTIVE_SNIPPETS:
        if snippet in text:
            return False, "refused: destructive command pattern (%s)" % snippet
    # `a || python b` is "or", not a pipe (it refused a plain fallback, 2026-10-25); `|python` is still a pipe
    piped = " ".join(text.replace("||", " \u2016 ").replace("|", "| ").split())
    for token in _REMOTE_EXEC_TOKENS:
        if token in piped:
            return False, "refused: remote content piped into an interpreter (%s)" % token
    return True, "ok"


def run_command(command: str, timeout: int = 120, cwd: str = "") -> str:
    """Run a command WITHOUT a shell (safe_exec): argv only, `a && b` chains allowed,
    pipes / redirects / substitution refused with a reason. cwd: the workspace (default) or a folder
    agents may read (e.g. LOKI's own folder to run tools/forge_qa.py)."""
    allowed, reason = command_policy(command)
    if not allowed:
        print("  [policy] " + reason)
        return "error: " + reason
    try:
        where = resolve_readable(cwd) if str(cwd or "").strip() else WORKSPACE
    except ValueError as exc:
        return "error: %s" % exc
    if not where.is_dir():
        return "error: no folder %s" % cwd
    try:
        code, out = safe_exec.run(command, cwd=str(where), timeout=int(timeout))
    except safe_exec.CommandRejected as e:
        print("  [policy] " + str(e))
        return f"error: {e}"
    except Exception as e:
        return f"error: {e}"
    return f"exit {code}\n{_shorten(out)}" if out else f"exit {code}"


def bash(command: str, timeout: int = 120, cwd: str = "") -> str:
    """A real shell (engine/shell_tools.py): Git Bash on Windows, bash on the Mac - pipes, redirects, globs.
    The same command policy as run_command; the risk analyzer and approval run in the tool gate."""
    allowed, reason = command_policy(command)
    if not allowed:
        print("  [policy] " + reason)
        return "error: " + reason
    try:
        where = resolve_readable(cwd) if str(cwd or "").strip() else WORKSPACE
    except ValueError as exc:
        return "error: %s" % exc
    if not where.is_dir():
        return "error: no folder %s" % cwd
    try:
        code, out = shell_tools.run_bash(command, str(where), timeout=int(timeout or 120))
    except FileNotFoundError as exc:
        return "error: %s" % exc
    except subprocess.TimeoutExpired:
        return "error: the command timed out after %ss" % timeout
    except Exception as exc:  # noqa: BLE001
        return "error: %s" % exc
    return f"exit {code}\n{_shorten(out)}" if out else f"exit {code}"


def itch(action: str, target: str = "", path: str = "", userversion: str = "") -> str:
    """itch.io through butler (engine/shell_tools.py): version, login, status, push, install."""
    def inside(p: str) -> Path:   # a build in the workspace, or in a folder agents may read
        return resolve_readable(p) if Path(p).is_absolute() else (WORKSPACE / p)
    return shell_tools.itch(action, target, path, userversion, data_dir=str(DATA_DIR), resolve_path=inside, shorten=_shorten)


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


# ---- vendored agent/skill libraries ---------------------------------------
# Downloaded by ecc_sync.py into harness_data/vendor/<name>/. Every library uses
# the same layout - agents/<name>.md and skills/<name>/SKILL.md - so one loader
# covers ECC (general agents/skills) and GodotPrompter (Godot-specific skills)
# alike. Nothing ships inside the addon; these are user data.
# ---- vendored agent/skill libraries ---------------------------------------
# Downloaded by ecc_sync.py into harness_data/vendor/<name>/. Layouts vary - some
# keep skills/ at the root, others plugins/<x>/skills or .agents/skills - so the
# loader searches RECURSIVELY for SKILL.md and agents/*.md. One loader therefore
# covers ECC, GodotPrompter, Superpowers and the game-dev skill packs alike.
# Nothing ships inside the addon; these are user data.
LIBRARIES = ("ECC", "GodotPrompter", "Superpowers", "awesome-gamedev", "gamedev-plugin",
             "agentic-gamedev")
ECC_DIR = DATA_DIR / "vendor" / "ECC"          # kept for backward compatibility
ECC_AGENTS_DIR = ECC_DIR / "agents"
ECC_SKILLS_DIR = ECC_DIR / "skills"
SKILL_LIST_CAP = int(os.getenv("LOKI_SKILL_LIST_CAP", "120"))


def _lib_roots():
    """(library, folder) for Loki's own skills and every vendored library on disk."""
    own = REPO_ROOT / "skills"
    if own.is_dir():
        yield "Loki", own
    for library in LIBRARIES:
        folder = DATA_DIR / "vendor" / library
        if folder.is_dir():
            yield library, folder


def _agent_entries() -> list:
    """[(library, name, path)] for every vendored agent, whatever the layout."""
    entries = []
    for library, folder in _lib_roots():
        for path in sorted(folder.glob("**/agents/*.md")):
            entries.append((library, path.stem, path))
    return entries


def _skill_entries() -> list:
    """[(library, name, path)] for every vendored skill, whatever the layout."""
    entries = []
    for library, folder in _lib_roots():
        for path in sorted(folder.glob("**/SKILL.md")):
            entries.append((library, path.parent.name, path))
    return entries


def _describe(entries, query: str = "") -> str:
    by_lib: dict = {}
    for library, name, _path in entries:
        if query and query.lower() not in name.lower():
            continue
        by_lib.setdefault(library, []).append(name)
    if not by_lib:
        return ("nothing matches %r" % query) if query else "nothing found"
    parts = []
    for library, names in by_lib.items():
        shown = names[:SKILL_LIST_CAP]
        more = "" if len(names) <= SKILL_LIST_CAP else " ... (+%d more)" % (len(names) - SKILL_LIST_CAP)
        parts.append("%s (%d): %s%s" % (library, len(names), ", ".join(shown), more))
    return " | ".join(parts)


def list_ecc_agents(query: str = "") -> str:
    """List the specialised agents available from every vendored library."""
    entries = _agent_entries()
    if not entries:
        return "no agent libraries installed (call sync_ecc to fetch them)."
    return "agents - " + _describe(entries, query)


def load_ecc_agent(name: str) -> str:
    """Return a specialised agent's instructions so you can follow them for the task."""
    wanted = os.path.basename(str(name).strip())
    for _library, stem, path in _agent_entries():
        if stem == wanted:
            return skill_scan.safe_doc(path)
    return "no such agent: %s (call list_ecc_agents)" % name


def list_ecc_skills(query: str = "") -> str:
    """List the specialised skill packs from every vendored library.

    Pass query to filter by name substring - the library holds several hundred.
    """
    entries = _skill_entries()
    if not entries:
        return "no skill libraries installed (call sync_ecc to fetch them)."
    return "skills - " + _describe(entries, query)


def load_ecc_skill(name: str) -> str:
    """Return a skill's guidance so you can follow it for the task."""
    wanted = os.path.basename(str(name).strip())
    for _library, skill, path in _skill_entries():
        if skill == wanted:
            # Downloaded skills are untrusted: refused if they try to override Loki's
            # rules, annotated if they ship scripts (which Loki never runs). SkillSpector
            # adds a deeper static scan when it is enabled.
            skill_scan.EXTERNAL_SCANNERS[:] = (
                [conductor.skillspector_findings] if CAPABILITIES.is_enabled("skillspector") else [])
            return skill_scan.safe_text(path)
    return "no such skill: %s (call list_ecc_skills)" % name


def mcp_status() -> dict:
    """Per-server state for the bridge and the doctor: connected, or why not."""
    try:
        servers = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))["mcpServers"]
    except Exception:
        return {}
    out: dict = {}
    for name, spec in servers.items():
        if name in MCP_SESSIONS_BY_SERVER:
            offered = sorted(n for n in MODEL_TOOL_NAMES if mcp_sessions.get(n) is MCP_SESSIONS_BY_SERVER[name])
            out[name] = {"state": "connected", "tools": len(offered)}
        else:
            out[name] = {"state": "off", "reason": _server_skip_reason(spec, name) or "not started"}
    return out


def vendor_library() -> dict:
    """{library: {agents: [...], skills: [...]}} for the bridge and the dock."""
    result: dict = {}
    for library, name, _path in _agent_entries():
        result.setdefault(library, {"agents": [], "skills": []})["agents"].append(name)
    for library, name, _path in _skill_entries():
        result.setdefault(library, {"agents": [], "skills": []})["skills"].append(name)
    return result


def sync_ecc(force: bool = False) -> str:
    """Refresh every vendored agent/skill library (ECC, GodotPrompter, ponytail)."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import ecc_sync
        report = ecc_sync.sync(force=bool(force))
        state = ecc_sync.installed()
    except Exception as e:
        return "error: could not sync the libraries: %s" % e
    totals = state.get("totals", {})
    return "synced %s; %d agents, %d skills total" % (report, totals.get("agents", 0), totals.get("skills", 0))


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


def probe_scene(filename: str, inputs: str = "[]", settle_frames: int = 5,
                duration_ms: int = 3000, timeout: int = 120) -> str:
    """Run a scene in a real window, feed it a timed input sequence, and report what landed.

    inputs is a JSON array of steps, for example:
      [{"at_ms": 400, "hold_ms": 150, "type": "action", "action": "move_right"},
       {"at_ms": 900, "hold_ms": 60,  "type": "key", "key": "Space"},
       {"at_ms": 1200, "type": "motion", "dx": 120, "dy": 0}]
    Every press is held at least two PHYSICS frames so a per-frame poller sees it, and the
    result reports what the game actually received. This is how to prove a controller moves,
    a button fires, or a shot lands - instead of assuming it.
    """
    if not GODOT_EXE:
        return "error: the Godot executable was not found; set GODOT_EXE in harness_data/.env"
    project = GAME_PROJECT or str(WORKSPACE)
    scene = filename if filename.startswith("res://") else "res://" + filename.lstrip("/")
    try:
        steps = json.loads(inputs) if isinstance(inputs, str) else list(inputs)
    except (ValueError, TypeError):
        return "error: inputs must be a JSON array of steps"
    if not isinstance(steps, list):
        return "error: inputs must be a JSON array of steps"
    from godot_assets import PROBE_GD
    staged = Path(project) / "loki_probe_tmp.gd"
    sidecar = Path(project) / ".godot" / "loki_probe.json"
    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(PROBE_GD, encoding="utf-8")
        sidecar.write_text(json.dumps({
            "scene": scene, "inputs": steps,
            "settle_frames": int(settle_frames), "duration_ms": int(duration_ms)}),
            encoding="utf-8")
    except OSError as exc:
        return "error: cannot stage the probe in %s: %s" % (project, exc)
    try:
        proc = subprocess.run(
            [GODOT_EXE, "--path", project, "--resolution", "1152x648",
             "--script", "res://loki_probe_tmp.gd"],
            capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return "error: probe timed out after %ds" % timeout
    except Exception as exc:
        return "error: %s" % exc
    finally:
        for leftover in (staged, sidecar):
            try:
                leftover.unlink()
            except OSError:
                pass
    results = ""
    shot = ""
    for line in out.splitlines():
        if line.startswith("LOKI_PROBE_RESULTS: "):
            results = line.split(": ", 1)[1].strip()
        elif line.startswith("LOKI_PROBE_SHOT: "):
            shot = line.split(": ", 1)[1].strip()
    if not results:
        problems = [l.strip() for l in out.splitlines() if "ERROR" in l][:8]
        return "probe failed for " + scene + chr(10) + (chr(10).join(problems) or out[-400:])
    try:
        data = json.loads(Path(results).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "probe ran but its results could not be read: %s" % exc
    delivered = data.get("delivered", [])
    ok = sum(1 for e in delivered if e.get("delivered"))
    lines = ["probe_scene %s: %d/%d inputs delivered at %s Hz"
             % (scene, ok, int(data.get("requested", len(delivered))),
                data.get("physics_ticks_per_second", "?"))]
    for event in delivered:
        if not event.get("delivered"):
            lines.append("  #%s %s: NOT delivered (%s)"
                         % (event.get("index"), event.get("type"), event.get("reason", "?")))
            continue
        note = " - held to the physics floor" if event.get("clamp_applied") else ""
        lines.append("  #%s %s: %s physics frame(s)%s"
                     % (event.get("index"), event.get("type"),
                        event.get("physics_frames", "?"), note))
    if shot:
        lines.append("screenshot: %s. Inspect it with view_image." % shot)
    return chr(10).join(lines)


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
    if question:
        prompt = question
    elif "sketch" in path.name.lower():
        prompt = ("The user drew this for you. Describe exactly what it shows: shapes, layout, arrows, "
                  "labels and handwriting (transcribe it), and what it most likely means or asks for.")
    else:
        prompt = ("Describe exactly what is visible in this image or screenshot. Then list anything "
                  "that looks wrong: an empty or black view, missing parts, things floating, clipping "
                  "or overlapping, unreadable text.")
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


def capability_registry() -> list:
    """Every way Loki can reach the outside world, as one list of entries."""
    return capabilities.registry(
        models=MODELS, configured=provider_configured,
        schemas=TOOL_SCHEMAS, offered=MODEL_TOOL_NAMES, categories=TOOL_CATEGORIES,
        mcp_path=MCP_CONFIG, skip_reason=_server_skip_reason,
        vendor_dir=DATA_DIR / "vendor")


def list_capabilities(query: str = "") -> str:
    """List or search what Loki can use: providers, tools, MCP servers, skill libraries."""
    entries = capability_registry()
    return capabilities.render(capabilities.search(entries, query), len(entries))


def capability_summary() -> dict:
    """Counts by kind and status, for the bridge and the report."""
    return capabilities.summary(capability_registry())


def knowledge_tool(action: str = "list", uri: str = "viking://memory", text: str = "") -> str:
    """Read, list or write Loki's viking:// context store (memory/ and state/ are writable)."""
    try:
        if action == "read":
            return KNOWLEDGE.read(uri)
        if action == "write":
            KNOWLEDGE.write(uri, text)
            return "saved " + uri
        return "\n".join(KNOWLEDGE.list(uri)) or "(empty)"
    except knowledge.KnowledgeError as exc:
        return "error: %s" % exc


LOCAL_TOOLS = {
    "conductor": lambda role, task="", url="": conductor_tool(role, task, url),
    "delegate": lambda agent, task: delegate(agent, task),
    "improve_loki": lambda task: improve_loki(task),
    "start_team": lambda goal: start_team(goal),
    "team_post": lambda text, to="all": team_post(text, to),
    "team_read": lambda: team_read(),
    "ship_loki": lambda message, path="": ship_loki(message, path),
    "check_loki": lambda suite="", path="": check_loki(suite, path),
    "knowledge": knowledge_tool,
    "list_files": list_files,
    "list_tree": list_tree,
    "read_file": read_file,
    "folders": folders_tool,
    "write_file": write_file,
    "append_file": append_file,
    "edit_file": edit_file,
    "search_files": search_files,
    "make_dir": make_dir,
    "move_file": move_file,
    "delete_file": delete_file,
    "run_command": run_command,
    "bash": bash,
    "itch": itch,
    "run_godot": run_godot,
    "open_godot": open_godot,
    "build_3d_scene": build_3d_scene,
    "build_scene": build_scene,
    "validate_scene": validate_scene,
    "play_scene": play_scene,
    "check_script": check_script,
    "capture_scene": capture_scene,
    "probe_scene": probe_scene,
    "view_image": view_image,
    "list_capabilities": list_capabilities,
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
    "forecast_series": forecast_series,
    "generate_media": generate_media,
    "game_engine_guide": game_engine_guide,
    "crm_add": crm_add,
    "crm_update": crm_update,
    "crm_find": crm_find,
    "crm_log": crm_log,
    "crm_pipeline": crm_pipeline,
    "scrape": scrape,
    "video_project": video_project,
    "render_video": render_video,
    "project_state": project_state_update,
    "review_repository": review_repository,
    "agent_sessions": agent_sessions,
    "api_vault": api_vault_lookup,
    "todo_list": todo_list,
    "todo_done": todo_done,
    "save_memory": save_memory,
    "insert_lines": insert_lines,
    "undo_edit": undo_edit,
}

# Tools that change files on disk (used to verify a task really did work).
MODIFYING = {"bash", "write_file", "append_file", "edit_file", "insert_lines", "undo_edit", "build_3d_scene", "build_scene",
             "move_file", "delete_file", "make_dir",
             # these three rewrite project.godot
             "add_input_action", "set_project_setting", "add_autoload",
             "video_project", "render_video"}
# Tools that START the game or the editor (scene scripts run, and can do anything a
# script can). Plan mode is read-only, so it offers none of them. check_script stays:
# --check-only parses the script without running it.
RUNS_PROJECT = {"play_scene", "probe_scene", "capture_scene", "validate_scene", "open_in_editor"}
# Writes outside the project (downloads into harness_data, the CRM database) or saves what it
# fetched (scrape) - not "read-only" either.
NETWORK_WRITES = {"sync_ecc", "crm_add", "crm_update", "crm_log", "scrape"}
# Starting or steering another agent: a delegated coder writes, so Plan mode cannot.
DELEGATING = {"delegate", "improve_loki", "ship_loki", "start_team"}
# Starts a helper that may write if it is given write tools: never offered in Plan mode either.
DELEGATING |= {"run_subagent"}

# LOKI improving its own code (improve_loki / ship_loki): "auto" lets agents change, test
# and push LOKI without asking (ship.py refuses to push unless every test passes), "ask"
# asks you first, "off" disables both tools.
SELF_SHIP = str(os.getenv("LOKI_SELF_SHIP", "auto")).strip().lower()

# Tools that touch the system ask for a yes/no first, unless AUTO_APPROVE is on.
DANGEROUS = {"run_command", "bash", "open_godot", "move_file", "delete_file", "delegate", "start_team"}
# video_project/render_video run npx and the video project's own code (Remotion).
DANGEROUS |= {"video_project", "render_video"}
if SELF_SHIP == "ask":
    DANGEROUS |= {"improve_loki", "ship_loki"}
POLICY = policy.PolicyEngine(path_check=lambda name: resolve_in_workspace(name),
                             command_check=lambda command: command_policy(command),
                             parse_command=safe_exec.parse, dangerous=DANGEROUS,
                             registry=CAPABILITIES,
                             read_check=lambda name: resolve_readable(name))
CONDUCTOR = conductor.Conductor(POLICY, CAPABILITIES)


import agents as agent_profiles  # noqa: E402  (your named agents - harness_data/agents.json)
AGENTS = agent_profiles.Store(DATA_DIR / "agents.json")
JOBS = None  # workers.Supervisor, set by the engine (loki_bridge) when background jobs run


def delegate(agent: str, task: str) -> str:
    """Hand a longer task to one of your agents as a background job (always asks first)."""
    if JOBS is None:
        return "error: background jobs are not running in this Loki"
    wanted = str(agent or "").strip().lower()
    profile = next((a for a in AGENTS.all() if a["id"] == wanted or a["name"].lower() == wanted), None)
    if profile is None:
        names = ", ".join(a["name"] for a in AGENTS.all())
        return "error: no agent called %r. Your agents: %s" % (agent, names)
    try:
        spec = agent_profiles.job_spec(profile, task, str(WORKSPACE),
                                       catalog=agent_profiles.skills_catalog(
                                           agent_profiles.skill_roots(REPO_ROOT, DATA_DIR)))
    except ValueError as exc:
        return "error: %s" % exc
    verdict = POLICY.job(spec["backend"], spec["agent"])
    if not verdict.allowed:
        return "error: %s" % verdict.reason
    try:
        job = JOBS.create(spec)
    except ValueError as exc:
        return "error: %s" % exc
    threading.Thread(target=JOBS.tick, daemon=True).start()
    return ("started background job %s: %s is working on it. The user sees it above the message box; "
            "you do not need to wait for it." % (job["id"], profile["name"]))


import team as teams  # noqa: E402  (agent teams: one sentence in, a team that builds it)
TEAMS = None  # team.TeamRunner, set by the engine (loki_bridge) next to JOBS
JOB_ROLE = ""  # the team role a background job runs as (set by run_job; "" for chat)
ROLE_MIN_SAMPLES = int(os.getenv("LOKI_ROLE_MIN_SAMPLES", "5"))


def model_for_role(role: str) -> str:
    """The agent factory's model pick for a team role: the ready provider that has done
    this role best (experience.best_for_role), within the spending policy; "" = smart."""
    try:
        candidates = []
        for name in dict.fromkeys(list(SMART_ORDER) + list(LOCAL_PROVIDERS)):
            if name in _SMART_FAILED or not provider_configured(name):
                continue
            if provider_tier(name) == "paid" and not paid_allowed_automatically():
                continue
            candidates.append(name)
        return experience.best_for_role(role, candidates, provider_tier, min_samples=ROLE_MIN_SAMPLES)
    except Exception:  # noqa: BLE001
        return ""


def start_team(goal: str) -> str:
    """Build a team for this goal and start it (roles, specs and stages are chosen for you)."""
    if TEAMS is None:
        return "error: agent teams are not running in this Loki"
    try:
        team = TEAMS.start(goal, str(WORKSPACE), triage=dict(LAST_TRIAGE or {}), model="")
    except ValueError as exc:
        return "error: %s" % exc
    return ("started team %s (%s) on %s. They plan, build, test and review in turn and talk on a "
            "shared board; the user sees them above the message box. You do not need to wait."
            % (team["id"], ", ".join(teams.ROLES[r]["name"] for r in team["roles"]), WORKSPACE))


def _my_team() -> str:
    return os.getenv("LOKI_TEAM_ID", "").strip()


def team_post(text: str, to: str = "all") -> str:
    """Post a note to your team's board (only inside a team)."""
    team_id = _my_team()
    if not team_id:
        return "error: you are not on a team"
    who = os.getenv("LOKI_TEAM_ROLE", "") or "agent " + os.getenv("LOKI_JOB_ID", "")
    teams.post(team_id, who, text, to)
    return "posted to team %s" % team_id


def team_read() -> str:
    """Read your team's board."""
    team_id = _my_team()
    if not team_id:
        return "error: you are not on a team"
    return teams.board_text(team_id) or "(the board is empty)"


SELF_IMPROVE_PROMPT = """You are improving LOKI itself - the app you are part of.
This workspace is a git worktree of LOKI's own repository, on its own branch.
Read AGENTS.md first and follow it. Then make this change:

{task}

Rules: LOKI runs on macOS and Windows from the same code, so never write code for one
without the other; add or update tests in tests/; keep docs/ true. You cannot run shell
commands, and the conductor's roles are not a way to run them: to test, call check_loki
(suite="test_portal" for a quick check, or no suite for all). You ARE the agent that changes
LOKI - never call improve_loki yourself. Read only the parts of big files you need
(search_files first, then read_file with start_line/end_line). Edit with edit_file (the old text
must be unique - copy a few surrounding lines) or insert_lines; undo_edit reverts a bad edit.
Plan the steps with task_tracker and keep it up to date. Hand a side question ("where is X
defined?", "what does this module do?") to run_subagent so your own context stays small. Use
memory recall for what earlier attempts learned, and memory learn for a lesson worth keeping.
When the change is done and check_loki passes, call ship_loki with a one-line message saying
what changed and how you checked it. ship_loki runs every suite again and pushes only if they
all pass; if it reports failures, fix them and call it again. You are not done until ship_loki
says "shipped". Report DONE with what you shipped, or BLOCKED with why."""


IMPROVE_MODEL = os.getenv("LOKI_IMPROVE_MODEL", "online").strip() or "online"


def improve_model(preferred: str = "") -> str:
    """The model an improve job runs on. "online" (the best FREE online model) when one is set up -
    changing LOKI is long tool work a small local model tends to drop - else "smart" (the local
    model, which still works), never a model that is not configured (the job would only report
    BLOCKED at once - the reason evolve never finished a step on a machine without an online key)."""
    wanted = (preferred or IMPROVE_MODEL or "online").strip()
    if wanted not in MODELS:
        return ""
    if wanted == "online":
        for candidate in ONLINE_ORDER:
            if provider_tier(candidate) == "paid" and not paid_allowed_automatically():
                continue
            if provider_configured(candidate):
                return "online"
        return "smart"
    if wanted not in AUTO_ROUTING_MODES and not provider_configured(wanted):
        return "smart"
    return wanted


# Variables a LOKI test run must NOT inherit from the engine or a background job: they point the
# suites at the live data folder (keys, memory, settings) or the job's worktree, so a check run
# inside an improve job behaved differently from CI - and could write into the owner's real data.
_CHECK_ENV_DROP = ("GAME_PROJECT",)


def check_env(base: dict | None = None) -> dict:
    """The environment for tools/ship.py runs: like CI - no LOKI_* settings, no job variables, no keys."""
    env = dict(base if base is not None else os.environ)
    keys = set(PROVIDER_ENV_VARS.values())
    for name in list(env):
        if name.startswith(("LOKI_", "HARNESS_")) or name in keys or name in _CHECK_ENV_DROP:
            env.pop(name, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _ship_script(repo: Path) -> Path:
    """The checkout's OWN tools/ship.py, so a suite the change adds is run too."""
    own = Path(repo) / "tools" / "ship.py"
    return own if own.is_file() else REPO_ROOT / "tools" / "ship.py"


def ship_marker(job_id: str) -> Path:
    return DATA_DIR / "jobs" / ("%s.shipped.json" % re.sub(r"[^A-Za-z0-9_-]", "", str(job_id or "")))


def _is_loki_checkout(path: Path) -> bool:
    return (path / "engine" / "loki.py").is_file() and (path / ".git").exists()


def _in_loki_worktree() -> bool:
    """True inside a LOKI job's own worktree (harness_data/worktrees/<job>)."""
    try:
        return WORKSPACE.resolve() != REPO_ROOT.resolve() and _is_loki_checkout(WORKSPACE) \
            and "worktrees" in WORKSPACE.resolve().parts
    except OSError:
        return False


def check_loki(suite: str = "", path: str = "") -> str:
    """Run LOKI's test suites (tools/ship.py --check) in a LOKI checkout or worktree."""
    repo = Path(path).expanduser() if path else (WORKSPACE if _is_loki_checkout(WORKSPACE) else REPO_ROOT)
    if not _is_loki_checkout(repo):
        return "error: %s is not a LOKI checkout" % repo
    argv = [sys.executable, str(_ship_script(repo)), "--check", "--repo", str(repo)]
    suite = re.sub(r"[^a-z_,]", "", str(suite or "").lower())
    if suite:
        argv += ["--only", suite]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=3600, cwd=str(repo), env=check_env())
    except subprocess.TimeoutExpired:
        return "error: the tests took over an hour and were stopped"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return ("ALL PASSED\n" if proc.returncode == 0 else "SOME FAILED\n") + out[-3000:]


def improve_loki(task: str) -> str:
    """Start a background agent that changes LOKI's own code in an isolated worktree."""
    if _in_loki_worktree():
        return ("error: you are already the agent changing LOKI (this is its worktree). Make the "
                "change here, test it with check_loki and ship it with ship_loki.")
    if SELF_SHIP == "off":
        return "error: LOKI may not change its own code here (LOKI_SELF_SHIP=off)"
    if JOBS is None:
        return "error: background jobs are not running in this Loki"
    task = str(task or "").strip()
    if not task:
        return "error: say what to change"
    if not _is_loki_checkout(REPO_ROOT):
        return "error: %s is not a git checkout of LOKI yet (restart LOKI once)" % REPO_ROOT
    spec = {"backend": "local", "agent": "loki", "workspace": str(REPO_ROOT), "isolate": True,
            "timeout_s": 7200, "allow_commands": True, "title": "Improve LOKI: " + task.splitlines()[0][:60],
            "prompt": SELF_IMPROVE_PROMPT.format(task=task),
            # Changing LOKI's own code is long, careful tool work: by default it goes to the best
            # FREE online model (the "online" mode, never paid unless allowed), not a small local
            # model that tends to stop after a few turns - but only when one is set up; else the
            # local model (improve_model). LOKI_IMPROVE_MODEL overrides it.
            "model": improve_model()}
    verdict = POLICY.job(spec["backend"], spec["agent"])
    if not verdict.allowed:
        return "error: %s" % verdict.reason
    try:
        job = JOBS.create(spec)
    except ValueError as exc:
        return "error: %s" % exc
    threading.Thread(target=JOBS.tick, daemon=True).start()
    return ("started job %s: a LOKI agent is making the change in its own worktree and will "
            "ship it when every test passes. The user sees it above the message box." % job["id"])


def ship_loki(message: str, path: str = "") -> str:
    """Test, commit and push a change to LOKI (tools/ship.py), then tell the other machines."""
    if SELF_SHIP == "off":
        return "error: LOKI may not push its own code here (LOKI_SELF_SHIP=off)"
    message = str(message or "").strip()
    if not message:
        return "error: give a one-line message saying what changed"
    repo = Path(path).expanduser() if path else (WORKSPACE if _is_loki_checkout(WORKSPACE) else REPO_ROOT)
    if not _is_loki_checkout(repo):
        return "error: %s is not a git checkout of LOKI" % repo
    env = check_env()
    # ship.py tells the linked machines with LOKI's own peer settings (harness_data/.env)
    env["LOKI_DATA"] = str(DATA_DIR)
    try:
        proc = subprocess.run([sys.executable, str(_ship_script(repo)), "-m", message,
                               "--repo", str(repo)], capture_output=True, text=True, timeout=3600,
                              cwd=str(repo), env=env)
    except subprocess.TimeoutExpired:
        return "error: shipping took over an hour and was stopped"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    job_id = os.getenv("LOKI_JOB_ID", "")
    if proc.returncode == 0 and job_id and ("pushed" in out or "Shipped" in out):
        # Proof for evolve/autopilot that this job really shipped (a job that merely ended is not).
        try:
            marker = ship_marker(job_id)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"t": time.time(), "message": message[:300],
                                          "out": out[-600:]}), encoding="utf-8")
        except OSError:
            pass
    return ("shipped:\n" if proc.returncode == 0 else "NOT shipped:\n") + out[-3000:]


def conductor_tool(role: str, task: str = "", url: str = "") -> str:
    """Hand one step to a specialist: research, read_web, browse, remember, recall, media, image, reach, track."""
    role = str(role).strip().lower()
    out = CONDUCTOR.run(role, str(task or ""), str(url or ""))
    if role == "read_web" and str(out).startswith("error: no specialist") and not _private_host(str(url or task or "")):
        return web_reader.read(str(url or task or "").strip())   # no add-on: read it natively
    return out


# ---------------------------------------------------------------------------
# Session 26 core upgrade: memory, sub-agents, native web reading, the task tracker.
# ---------------------------------------------------------------------------

MEMORY_BUDGET = memory_core.Budget()
LAST_RECALL: list = []      # memories this request used: the pack's citations + the memory tool's recalls
LAST_SKILLS: list = []      # learned skills offered to this request
LAST_LEARNED: dict = {}     # the skill learned from the last request, if any
LAST_NOTED: list = []       # what the last request taught LOKI about the owner (memory.after_request)


def _cite(citations: list) -> None:
    for c in citations or []:
        if c.get("id") and all(c["id"] != x.get("id") for x in LAST_RECALL):
            LAST_RECALL.append({"id": c["id"], "tier": c.get("tier", ""), "text": str(c.get("text", ""))[:160]})


def memory_tool(action: str = "recall", text: str = "", query: str = "", id: str = "",  # noqa: A002
                tier: str = "semantic", tags: str = "", cursor: int = 0, all: bool = False) -> str:  # noqa: A002
    """LOKI's memory (OpenHuman's single memory tool): learn | recall | fetch | forget."""
    refusal = MEMORY_BUDGET.take()
    if refusal:
        return "error: " + refusal
    action = str(action or "recall").strip().lower()
    if action in ("learn", "save", "remember", "store"):
        out = memory_core.learn(text or query, tier=tier or "semantic", tags=tags, root=DATA_DIR,
                                meta={"workspace": str(WORKSPACE)})
        return ("learned (%s): %s" % (out["id"], out["status"])) if out.get("ok") else "error: " + out["error"]
    if action in ("recall", "search"):
        out = memory_core.recall(query or text, root=DATA_DIR, repo=REPO_ROOT)
        _cite(out.get("citations"))
        return out["evidence"] or out.get("note", "Nothing relevant is stored in memory.")
    if action == "fetch":
        out = memory_core.fetch(query or text, cursor=int(cursor or 0), root=DATA_DIR, repo=REPO_ROOT)
        _cite(out["items"])
        lines = ["[%s %s] %s" % (i["tier"], i["id"], i["text"]) for i in out["items"]]
        more = ("\n(next_cursor=%d of %d)" % (out["next_cursor"], out["total"])) if out["next_cursor"] is not None else ""
        return ("\n".join(lines) or "Nothing relevant is stored in memory.") + more
    if action in ("forget", "delete", "remove"):
        out = memory_core.forget(id, query or text, root=DATA_DIR, all_matches=str(all).lower() in ("1", "true", "yes"))
        if out.get("ok"):
            return "forgot %d memor%s" % (out["forgotten"], "y" if out["forgotten"] == 1 else "ies")
        extra = "".join("\n- %s: %s" % (m["id"], m["text"]) for m in out.get("matches") or [])
        return "error: %s%s" % (out.get("error"), extra)
    return "error: action is learn, recall, fetch or forget"


def _private_host(url: str) -> bool:
    import ipaddress  # pylint: disable=import-outside-toplevel
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    allow = {h.strip().lower() for h in os.getenv("LOKI_NET_ALLOW", "").split(",") if h.strip()}
    if host in allow:
        return False
    if host in ("localhost", "") or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:   # session 27 (Agent Reach url.py): internal names, and IPv4 in legacy spellings (127.1, 2130706433)
        import reach_native as _rn  # pylint: disable=import-outside-toplevel
        if host.rstrip(".") in _rn.BLOCKED_HOSTS or host.rstrip(".").endswith(_rn.BLOCKED_SUFFIXES):
            return True
        legacy = _rn.literal_ip(host)
        if legacy is not None and not legacy.is_global:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def read_web(url: str, max_chars: int = 20000, query: str = "") -> str:
    """One web page as markdown. An installed reader add-on (crawl4ai, Scrapling, Firecrawl) is used
    when it is on; otherwise LOKI reads it natively (web_reader.py, ported from Scrapling's core).
    With `query`, only the parts of the page about it are returned (crawl4ai's BM25 filter)."""
    if str(query or "").strip():
        whole = read_web(url, 60000)
        if whole.startswith("error"):
            return whole
        import content_filter as _cf  # pylint: disable=import-outside-toplevel
        part = _cf.focus(whole, query, max_chars=max(1000, min(int(max_chars or 6000), 20000)))
        if part:
            return "[the parts of %s about %r - read_web without query for the whole page]\n\n%s" % (url, query, part)
        return whole[:max(1000, min(int(max_chars or 20000), 60000))]
    url = str(url or "").strip()
    if _private_host(url):
        return ("error: %s is on this computer or the local network; read_web only reads public pages "
                "(add the host to LOKI_NET_ALLOW to allow it)" % url)
    via, _why = ("", "")
    try:
        via, _why = CONDUCTOR.pick("read_web")
    except Exception:  # noqa: BLE001
        via = ""
    if via:
        text = CONDUCTOR.read_web(via, url)
        if not str(text).startswith("error:"):
            return text
    return web_reader.read(url, max_chars=max(1000, min(int(max_chars or 20000), 60000)))


SKETCH_SHAPES = ("line", "arrow", "rect", "circle", "text", "path")
SKETCH_MAX_SHAPES = 200


def sketch_reply(shapes, note: str = "") -> str:
    """Draw back on the user's drawing pad (the canvas <-> agent loop PenEcho is built on: the
    answer appears ON the canvas, beside what the user drew). shapes: a list of
    {type: line|arrow|rect|circle|text|path, x1,y1,x2,y2 | x,y,w,h | cx,cy,r | x,y,text | points:[[x,y],...],
    color}; coordinates 0..1000 across and down the pad. Saved to sketches/loki-<time>.json in the
    workspace; the pad (✎ Draw) shows the newest one under the user's own strokes."""
    if isinstance(shapes, str):
        try:
            shapes = json.loads(shapes)
        except ValueError:
            return "error: shapes must be a JSON list"
    if not isinstance(shapes, list) or not shapes:
        return "error: give a list of shapes to draw"

    def num(v) -> float:
        try:
            return max(-100.0, min(1100.0, float(v)))
        except (TypeError, ValueError):
            return 0.0
    clean = []
    for shape in shapes[:SKETCH_MAX_SHAPES]:
        if not isinstance(shape, dict) or shape.get("type") not in SKETCH_SHAPES:
            continue
        out = {"type": shape["type"]}
        color = str(shape.get("color", "#8ccfc4"))
        out["color"] = color if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color) else "#8ccfc4"
        for key in ("x1", "y1", "x2", "y2", "x", "y", "w", "h", "cx", "cy", "r"):
            if key in shape:
                out[key] = num(shape[key])
        if shape["type"] == "text":
            out["text"] = str(shape.get("text", ""))[:200]
        if shape["type"] == "path":
            pts = [[num(p[0]), num(p[1])] for p in (shape.get("points") or [])[:400]
                   if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(pts) < 2:
                continue
            out["points"] = pts
        clean.append(out)
    if not clean:
        return "error: none of those shapes could be drawn (types: %s)" % ", ".join(SKETCH_SHAPES)
    folder = WORKSPACE / "sketches"
    folder.mkdir(parents=True, exist_ok=True)
    name = "loki-%s.json" % time.strftime("%Y%m%d-%H%M%S")
    (folder / name).write_text(json.dumps({"t": time.time(), "note": str(note or "")[:500], "shapes": clean}),
                               encoding="utf-8")
    return ("drew %d shape(s) on the drawing pad (sketches/%s); the user sees them when they open ✎ Draw, "
            "under their own strokes." % (len(clean), name))


def task_tracker_tool(command: str = "view", task_list=None) -> str:
    """OpenHands' task tracker: view, or plan with the FULL list [{title, notes, status}]."""
    return task_tracker.run(command, task_list, path=DATA_DIR / "task_tracker.json", plan_file=PLAN_FILE)


SUBAGENT_DEPTH = 0


async def run_subagent(task: str = "", tools: str = "", tasks=None, max_turns: int = 0) -> str:
    """A short-lived helper with a narrow tool set and its own small context; returns one result.
    `tasks` (a list) runs several side by side. Same model routing as this request."""
    global SUBAGENT_DEPTH
    if SUBAGENT_DEPTH > 0:
        return "error: a sub-agent cannot start another sub-agent"
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except ValueError:
            tasks = [t for t in tasks.split("\n") if t.strip()]
    todo = [str(t).strip() for t in (tasks or []) if str(t).strip()][:subagent.MAX_PARALLEL] or \
        ([str(task).strip()] if str(task or "").strip() else [])
    if not todo:
        return "error: give the sub-agent a task"
    offered = model_tool_schemas()
    names = subagent.narrow(tools, [s["function"]["name"] for s in offered])
    if not names:
        return "error: none of those tools can be given to a sub-agent here (try: %s)" % ", ".join(subagent.DEFAULT_TOOLS)
    provider = active_model_name()
    cfg = MODELS[provider]
    client = make_client()

    async def request(msgs: list, schemas: list):
        kwargs = {"model": cfg.model, "messages": msgs, "max_tokens": int(os.getenv("LOKI_SUBAGENT_TOKENS", "4096"))}
        if schemas:
            kwargs["tools"] = schemas
        if "11434" in cfg.base_url or "ollama" in cfg.api_key:
            kwargs["extra_body"] = {"think": False}
        started = time.monotonic()
        response = await _model_request(client, kwargs, cfg, provider)
        _record_usage(response, kwargs, cfg, started)
        _record_request_usage(provider, response)
        msg = response.choices[0].message
        if not getattr(msg, "tool_calls", None):
            recovered = _recover_text_tool_calls(getattr(msg, "content", "") or "")
            if recovered:
                return {"content": "", "tool_calls": [
                    {"id": "sub%d" % i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                    for i, (n, a) in enumerate(recovered[:4])]}
        return msg

    async def run_tool(name: str, args: dict) -> str:
        fix = _guard_call(name, json.dumps(args))
        if not fix.ok:
            return "error: %s" % fix.error
        return await call_tool(fix.name, fix.args)

    _progress("thinking", "Starting %d sub-agent(s) with %s." % (len(todo), ", ".join(names)))
    SUBAGENT_DEPTH += 1
    try:
        cap = subagent.iter_cap(autonomous=bool(os.getenv("LOKI_JOB_ID")), requested=int(max_turns or 0))
        results = await subagent.run_many(todo, names, offered, request, run_tool, max_turns=cap)
    finally:
        SUBAGENT_DEPTH -= 1
    try:
        events.emit("agent.message", "LOKI sub-agent", {"subagents": [t[:200] for t in todo],
                                                         "ok": [bool(r.get("ok")) for r in results]})
    except Exception:  # noqa: BLE001
        pass
    return subagent.format_results(todo, results)


LOCAL_TOOLS.update({"memory": memory_tool, "read_web": read_web, "run_subagent": run_subagent,
                    "task_tracker": task_tracker_tool, "sketch_reply": sketch_reply})


# --- session 27 harvest: code from the documented repos, built in (docs/integrations/HARVEST.md) ----
import web_search as _web_search  # noqa: E402  (Vane: search + cited research; DuckDuckGo/arXiv/Wikipedia/SearxNG)
import site_map as _site_map  # noqa: E402  (Firecrawl map)
import text_browser as _text_browser  # noqa: E402  (browser-use + page-agent: numbered elements)
import reach_native as _reach_native  # noqa: E402  (Agent Reach: GitHub, feeds, YouTube, Jina)
import code_map as _code_map  # noqa: E402  (SWE-agent filemap / search_dir)
import content_filter as _content_filter  # noqa: E402  (crawl4ai BM25 + citations)
import schedules as _schedules  # noqa: E402  (Hermes Agent cron)


def _public_ok(url: str) -> bool:
    return not _private_host(url)


def web_search(query: str, mode: str = "web", max_results: int = 8) -> str:
    """Search the web with no add-on and no key (Vane's SearxNG client when LOKI_SEARXNG_URL is set,
    else DuckDuckGo, arXiv for mode=academic, Wikipedia as the last fallback)."""
    found = _web_search.search(query, mode=str(mode or "web"), max_results=max(1, min(int(max_results or 8), 15)))
    return _web_search.format_results(query, found)


def research_web(question: str, mode: str = "web", pages: int = 3, queries=None) -> str:
    """Vane's pipeline in one call: search, read the best pages natively, keep the relevant parts,
    return numbered sources and the citation rules to answer from."""
    if isinstance(queries, str):
        queries = [q.strip() for q in queries.split("\n") if q.strip()]
    return _web_search.research(question, mode=str(mode or "web"), pages=int(pages or 3), queries=queries,
                                read=lambda url: read_web(url, 40000))


def browse_page(action: str = "view", url: str = "", index: int = 0, text: str = "", direction: str = "down") -> str:
    """A text browser: open a page and see its links and form fields numbered; click, type, select,
    submit (search-style forms), scroll, back, find. No JavaScript (the Browser Use add-on does that)."""
    return _text_browser.act(action, url=url, index=index, text=text, direction=direction,
                             name=os.getenv("LOKI_JOB_ID", "") or "chat", allow=_public_ok)


def map_site(url: str, search: str = "", limit: int = 200) -> str:
    """Every page URL a website has (sitemaps + links), optionally ranked for `search`."""
    if _private_host(url if "://" in str(url) else "https://" + str(url)):
        return "error: %s is on this computer or the local network; map_site maps public sites" % url
    result = _site_map.map_site(url, search=search, limit=int(limit or 200))
    return _site_map.format_map(url, result, search)


def reach(url: str) -> str:
    """Read a URL with the channel that suits it: GitHub API (repo + README, issue, file), RSS/Atom feed,
    YouTube details, Reddit/JavaScript pages through Jina Reader; LOKI's own reader for the rest."""
    if _private_host(url if "://" in str(url) else "https://" + str(url)):
        return "error: %s is on this computer or the local network" % url
    return _reach_native.reach(url, native_read=lambda u: read_web(u, 40000))


def code_map(path: str = ".", depth_files: int = 60) -> str:
    """A file's outline (Python function bodies elided, other languages' declarations) or a folder's
    map (every source file with its top-level symbols and line numbers)."""
    target = resolve_in_workspace(path or ".")
    if target.is_dir():
        return _code_map.repo_map(target, max_files=max(5, min(int(depth_files or 60), 200)))
    return _code_map.outline(target, label=str(path))


def search_docs(query: str, subdir: str = ".", top: int = 6) -> str:
    """The passages in the workspace's documents and code that best answer `query` (BM25)."""
    return _content_filter.search_files_bm25(resolve_in_workspace(subdir or "."), query, top=int(top or 6))


SCHEDULES = _schedules.Schedules(DATA_DIR / "schedules.json")


def schedule_task(action: str = "list", prompt: str = "", schedule: str = "", id: str = "", repeat: str = "") -> str:  # noqa: A002
    """Scheduled tasks LOKI does by itself as background jobs: add | list | remove | pause | resume."""
    action = str(action or "list").strip().lower()
    try:
        if action == "add":
            if os.getenv("LOKI_JOB_ID"):
                return "error: a background job cannot schedule more jobs - ask the user to schedule it"
            item = SCHEDULES.add(prompt, schedule, repeat=repeat or None)
            return "scheduled: " + _schedules.describe(item) + "\n(it runs as a background job; see the job list)"
        if action == "remove":
            return ("removed %s" % id) if SCHEDULES.remove(id) else "error: no scheduled task %s" % id
        if action in ("pause", "resume"):
            return ("%sd %s" % (action, id)) if SCHEDULES.pause(id, action == "pause") else "error: no scheduled task %s" % id
        items = SCHEDULES.list()
        return ("\n".join(_schedules.describe(i) for i in items)) if items else "no scheduled tasks"
    except ValueError as exc:
        return "error: %s" % exc


LOCAL_TOOLS.update({"web_search": web_search, "research_web": research_web, "browse_page": browse_page,
                    "map_site": map_site, "reach": reach, "code_map": code_map, "search_docs": search_docs,
                    "schedule_task": schedule_task})
NETWORK_WRITES |= {"schedule_task"}


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
    schema("list_tree", "Show the project as a tree (or, with an absolute subdir, a folder you may read - see folders).",
           {"subdir": {"type": "string"}, "max_depth": {"type": "integer"}}),
    schema("folders", "List the folders you may read besides your workspace: LOKI's own folder (code, tools/), its "
           "data folder (logs, jobs, qa results), ~/LOKI Projects and the owner's extra folders - with absolute paths."),
    schema("read_file", "Read one file (a workspace path, or an absolute path in a folder listed by folders). For a big file pass start_line and end_line (1-based, end_line -1 = to the end) to get those lines numbered - read only the part you need.",
           {"filename": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["filename"]),
    schema("write_file", "Write (overwrite) a file.",
           {"filename": {"type": "string"}, "content": {"type": "string"}}, ["filename", "content"]),
    schema("append_file", "Append text to the end of a file.",
           {"filename": {"type": "string"}, "content": {"type": "string"}}, ["filename", "content"]),
    schema("edit_file", "Replace an exact snippet of text in a file. Prefer this over rewriting a whole file. `old` must appear EXACTLY ONCE (copy enough surrounding lines to make it unique) unless replace_all=true; the result shows the edited lines numbered.",
           {"filename": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"},
            "replace_all": {"type": "boolean"}},
           ["filename", "old", "new"]),
    schema("insert_lines", "Insert text into a file after line insert_line (0 = at the top). Use read_file with a line range first to find the line.",
           {"filename": {"type": "string"}, "insert_line": {"type": "integer"}, "text": {"type": "string"}},
           ["filename", "insert_line", "text"]),
    schema("undo_edit", "Put a file back as it was before your last edit_file or insert_lines on it.",
           {"filename": {"type": "string"}}, ["filename"]),
    schema("memory", "LOKI's long-term memory. action='recall' (query: what you need to know - returns the most relevant memories), 'learn' (text: one short lasting learning worth keeping, e.g. a fix that worked or a fact about this machine; tier 'semantic' for facts, 'episodic' for what happened), 'fetch' (query + cursor: page through all matches), 'forget' (id, or query with all=true). Relevant memories are already recalled into your instructions at the start of each request.",
           {"action": {"type": "string"}, "query": {"type": "string"}, "text": {"type": "string"}, "id": {"type": "string"},
            "tier": {"type": "string"}, "tags": {"type": "string"}, "cursor": {"type": "integer"}, "all": {"type": "boolean"}}, ["action"]),
    schema("read_web", "Read one public web page as markdown (main content only; hidden text removed). Works without any add-on. Pass query='what you need' to get only the parts of the page about it (much shorter).",
           {"url": {"type": "string"}, "max_chars": {"type": "integer"}, "query": {"type": "string"}}, ["url"]),
    # session 27 harvest (docs/integrations/HARVEST.md)
    schema("web_search", "Search the web (no add-on, no key). mode='web' (default), 'academic' (papers: arXiv), 'discussion' (Reddit threads), 'news'. Returns numbered results with url and snippet; then read_web(url, query=...) the useful ones. Targeted queries; do not search just to check something exists.",
           {"query": {"type": "string"}, "mode": {"type": "string"}, "max_results": {"type": "integer"}}, ["query"]),
    schema("research_web", "Answer a question from the live web in ONE call: searches, reads the best pages, keeps only the relevant parts and returns numbered sources [1], [2]... with the rules for a cited answer. Use for any question about current facts, products, people, news or docs. queries = up to 2 extra search phrasings.",
           {"question": {"type": "string"}, "mode": {"type": "string"}, "pages": {"type": "integer"},
            "queries": {"type": "array", "items": {"type": "string"}}}, ["question"]),
    schema("browse_page", "A text web browser. action='open' url=...; the page shows its links and form fields numbered like [3]<input name=q />. Then action='click' index=N (follow a link / press a button), 'type' index=N text=..., 'select' index=N text=option, 'submit' index=N (search-style forms), 'scroll' (direction up/down), 'back', 'find' text=..., 'view'. No JavaScript.",
           {"action": {"type": "string"}, "url": {"type": "string"}, "index": {"type": "integer"},
            "text": {"type": "string"}, "direction": {"type": "string"}}, ["action"]),
    schema("map_site", "List the pages of a website (from its sitemaps and links) without crawling it. search='words' ranks the URLs for those words - use it to find the right page on a big site, then read_web it.",
           {"url": {"type": "string"}, "search": {"type": "string"}, "limit": {"type": "integer"}}, ["url"]),
    schema("reach", "Read a URL the best way for its site: a GitHub repo (facts + README), issue/PR or file; an RSS/Atom feed (newest items); a YouTube video's details; Reddit or JavaScript-heavy pages (through Jina Reader). Other pages: LOKI's own reader.",
           {"url": {"type": "string"}}, ["url"]),
    schema("code_map", "See code structure without reading every line. path=a file: its outline with line numbers (Python function bodies elided). path=a folder (default '.'): every source file with its classes/functions and line numbers. Then read_file with start_line/end_line for the part you need.",
           {"path": {"type": "string"}, "depth_files": {"type": "integer"}}, []),
    schema("search_docs", "Find the passages in the workspace's documents and code (md, txt, html, code, json, csv; pdf if pypdf is installed) that best answer a question - ranked by relevance (BM25), with file and line.",
           {"query": {"type": "string"}, "subdir": {"type": "string"}, "top": {"type": "integer"}}, ["query"]),
    schema("schedule_task", "Tasks LOKI does by itself later, as background jobs. action='add' with prompt=what to do and schedule='every weekday at 9am' | 'in 30m' (once) | 'every 2h' | 'every monday 18:00' | a cron line '0 9 * * 1-5' | '2026-11-03T14:00'; 'list'; 'remove'/'pause'/'resume' with id.",
           {"action": {"type": "string"}, "prompt": {"type": "string"}, "schedule": {"type": "string"},
            "id": {"type": "string"}, "repeat": {"type": "string"}}, ["action"]),
    schema("run_subagent", "Hand ONE focused sub-task to a short-lived helper agent with its own small context and a narrow tool set; it returns one result, so your own context stays small. Good for: searching the code for something, reading a few files and summarizing them, reading web pages. tools = comma list (default read_file, search_files, list_tree, list_files, read_web, memory). tasks = a list of several tasks to run side by side (at most 4).",
           {"task": {"type": "string"}, "tools": {"type": "string"}, "tasks": {"type": "array", "items": {"type": "string"}},
            "max_turns": {"type": "integer"}}, []),
    schema("sketch_reply", "Draw back on the user's drawing pad, so your answer appears on the canvas beside their sketch (a corrected layout, an arrow to the spot, labels, a diagram). shapes = list of {type: line|arrow|rect|circle|text|path, x1,y1,x2,y2 (line/arrow) | x,y,w,h (rect) | cx,cy,r (circle) | x,y,text (text) | points [[x,y],...] (path), color '#rrggbb'}; coordinates 0..1000 across and down. The user sees it when they open the pad.",
           {"shapes": {"type": "array", "items": {"type": "object"}}, "note": {"type": "string"}}, ["shapes"]),
    schema("task_tracker", "Your plan for a multi-step task, with statuses. command='view' shows it; command='plan' with task_list = the FULL list [{title, notes, status: todo|in_progress|done}] replaces it. Mark a task in_progress before you start it and done when it is verified.",
           {"command": {"type": "string"}, "task_list": {"type": "array", "items": {"type": "object"}}}, ["command"]),
    schema("search_files", "Search file contents with a regular expression, with line numbers.",
           {"pattern": {"type": "string"}, "subdir": {"type": "string"}, "glob": {"type": "string"}}, ["pattern"]),
    schema("make_dir", "Create a directory (and parents).", {"path": {"type": "string"}}, ["path"]),
    schema("move_file", "Move or rename a file or directory.",
           {"src": {"type": "string"}, "dst": {"type": "string"}}, ["src", "dst"]),
    schema("delete_file", "Delete a file or directory.", {"path": {"type": "string"}}, ["path"]),
    schema("run_command", "Run a shell command and return its output (tests, git, etc.). cwd: the folder to run in "
           "(default the workspace; or an absolute folder from folders, e.g. LOKI's own folder for its tools/).",
           {"command": {"type": "string"}, "timeout": {"type": "integer"}, "cwd": {"type": "string"}}, ["command"]),
    schema("bash", "Run a command in a real shell - bash on the Mac, Git Bash on Windows - with pipes, redirects, globs, "
           "&& and $(...): git (status, log, diff, commit, push), grep, find, sed, npm, python, butler ... Use it when "
           "run_command refuses a pipe or a redirect. cwd: the folder (default the workspace).",
           {"command": {"type": "string"}, "timeout": {"type": "integer"}, "cwd": {"type": "string"}}, ["command"]),
    schema("itch", "itch.io (butler): action=version | login (is there a key) | status target=user/game | "
           "push path=<build folder or .zip> target=user/game:channel [userversion] | install (gets butler).",
           {"action": {"type": "string", "enum": ["version", "login", "status", "push", "install"]},
            "target": {"type": "string"}, "path": {"type": "string"}, "userversion": {"type": "string"}}, ["action"]),
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
    schema("probe_scene", "Run a scene in a real window and FEED IT INPUTS, then report what the game actually received (and a screenshot). Use this to prove a controller moves, a button fires or a shot lands instead of assuming it. inputs is a JSON array like [{\"at_ms\": 400, \"hold_ms\": 150, \"type\": \"action\", \"action\": \"move_right\"}] (types: action, key, mouse, motion).",
           {"filename": {"type": "string"}, "inputs": {"type": "string"}, "settle_frames": {"type": "integer"}, "duration_ms": {"type": "integer"}}, ["filename"]),
    schema("view_image", "Send a screenshot (or any PNG) to the model and get back a description and a list of visual problems. Use it after capture_scene to check your own work.",
           {"filename": {"type": "string"}, "question": {"type": "string"}}, ["filename"]),
    schema("api_vault", "Search the API Vault before building an integration: what an API does, where to reach it and whether it needs a key. action='search' (default; query/category/auth filters), 'stats' for the catalog size, 'add' to record one Loki should know about.",
           {"action": {"type": "string"}, "query": {"type": "string"}, "category": {"type": "string"}, "auth": {"type": "string"}, "name": {"type": "string"}, "url": {"type": "string"}, "provider": {"type": "string"}, "docs": {"type": "string"}, "limit": {"type": "integer"}}),
    schema("agent_sessions", "Track concurrent agent sessions - who is working, blocked or idle - so you never hunt for the stuck one. action='list' shows them, 'add' starts one (name, workspace, agent, status, task), 'update' changes a status/task, 'close' marks one done.",
           {"action": {"type": "string"}, "name": {"type": "string"}, "session_id": {"type": "string"}, "status": {"type": "string"}, "task": {"type": "string"}, "workspace": {"type": "string"}, "agent": {"type": "string"}}),
    schema("review_repository", "Review a repository FOLDER before adopting it: size, licence, languages, entry points and manifests. Read-only - it never executes or installs anything. Use it before adding third-party code.",
           {"path": {"type": "string"}}),
    schema("list_capabilities", "List or search what Loki can use right now - model providers, tools, MCP servers and skill libraries - with each one's status and where to get a key. Pass query to filter.",
           {"query": {"type": "string"}}),
    schema("list_ecc_agents", "List the specialised coding agents available (planning, review, security, build repair, etc.). Pass query to filter by name when the list is long.",
           {"query": {"type": "string"}}),
    schema("load_ecc_agent", "Load a specialised agent's instructions and follow them for the task.",
           {"name": {"type": "string"}}, ["name"]),
    schema("list_ecc_skills", "List the specialised skill packs available (TDD, security, Godot game dev, frontend, data, ML, operations, ...). Pass query to filter by name - the library holds hundreds.",
           {"query": {"type": "string"}}),
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
    schema("project_state", "Read or update the RESUMABLE PROJECT STATE so the work survives a restart or a different model. action='view' reads it; 'add' appends a value to a field; 'set' replaces one; 'reset' clears it. Fields: objective, phase, completed, files_changed, tests, known_issues, decisions, blockers, next_actions.",
           {"action": {"type": "string"}, "field": {"type": "string"}, "value": {"type": "string"}}),
    schema("todo_add", "Add a step to the persistent plan.", {"item": {"type": "string"}}, ["item"]),
    schema("forecast_series", "Forecast the next values of a numeric time series (oldest first) with "
           "TimesFM-3 when installed: returns the median and a 10-90% band.",
           {"values": {"type": "array", "items": {"type": "number"}}, "horizon": {"type": "integer"}}, ["values"]),
    schema("generate_media", "Make an image (kind='image') or a video (kind='video', needs model=<Higgsfield "
           "application id>) with Higgsfield; saved in images/ or videos/. Spends the user's Higgsfield credits - "
           "only when the user asks for it.",
           {"prompt": {"type": "string"}, "kind": {"type": "string"}, "model": {"type": "string"},
            "aspect_ratio": {"type": "string"}}, ["prompt"]),
    schema("crm_add", "Add a record to LOKI's built-in CRM. type='contact' (name, email, phone, title, "
           "company_id, notes, tags), 'company' (name, website, industry, notes), 'deal' (title, company_id, "
           "contact_id, stage=lead|qualified|proposal|negotiation|won|lost, value, currency, close_date), 'task' "
           "(title, due=YYYY-MM-DD, contact_id/company_id/deal_id) or 'interaction'. fields is a JSON object of those fields.",
           {"type": {"type": "string"}, "fields": {"type": "string", "description": "a JSON object, e.g. {\"name\": \"Ada\", \"email\": \"ada@example.com\"}"}}, ["type", "fields"]),
    schema("crm_update", "Change fields of one CRM record by type and id, e.g. move a deal to stage 'won' or "
           "mark a task done (fields={\"done\": true}).",
           {"type": {"type": "string"}, "id": {"type": "integer"}, "fields": {"type": "string", "description": "a JSON object, e.g. {\"name\": \"Ada\", \"email\": \"ada@example.com\"}"}},
           ["type", "id", "fields"]),
    schema("crm_find", "Search the CRM (names, emails, titles, notes). With no query, list the records of "
           "one type (contacts, companies, deals, tasks, interactions).",
           {"query": {"type": "string"}, "type": {"type": "string"}, "limit": {"type": "integer"}}),
    schema("crm_log", "Log a note, call, email, meeting or message against a contact, company or deal "
           "(give at least one of contact_id, company_id, deal_id). at=YYYY-MM-DD HH:MM, default now.",
           {"summary": {"type": "string"}, "kind": {"type": "string"}, "contact_id": {"type": "integer"},
            "company_id": {"type": "integer"}, "deal_id": {"type": "integer"}, "at": {"type": "string"}},
           ["summary"]),
    schema("crm_pipeline", "Summarise the sales pipeline: deals per stage, open and won value, win rate, "
           "open and overdue tasks."),
    schema("scrape", "Read a web page as clean markdown, or crawl=true to save a whole site (same domain, "
           "max_pages) as markdown files under scraped/<domain>/ in the workspace. dynamic=true renders "
           "JavaScript first. Uses Scrapling when installed, otherwise reads the one page another way.",
           {"url": {"type": "string"}, "crawl": {"type": "boolean"}, "max_pages": {"type": "integer"},
            "dynamic": {"type": "boolean"}}, ["url"]),
    schema("video_project", "Create a blank Remotion video project (videos made with React code) in "
           "videos/<name>. Asks the user first.", {"name": {"type": "string"}}, ["name"]),
    schema("render_video", "Render a Remotion composition to MP4: project_dir (e.g. videos/intro), "
           "composition id, out (default videos/<composition>.mp4), props (object passed to the "
           "composition). Asks the user first.",
           {"project_dir": {"type": "string"}, "composition": {"type": "string"}, "out": {"type": "string"},
            "props": {"type": "string", "description": "JSON object of input props"}, "entry": {"type": "string"}}, ["project_dir", "composition"]),
    schema("game_engine_guide", "Before making a game: how to build one with LOKI's own Pixel Engine so it runs "
           "inside LOKI (Settings > Play) - the API, the workflow (one file games/<name>/game.js) and a full example.", {}, []),
    schema("todo_list", "Show the persistent plan."),
    schema("todo_done", "Mark plan item N (1-based) as done.", {"index": {"type": "integer"}}, ["index"]),
    schema("save_memory", "Save one short lasting fact about the user.", {"fact": {"type": "string"}}, ["fact"]),
    schema("delegate", "Hand a longer task to one of your agents (Researcher, Builder, Reviewer, Tester, or one the user made) as a background job, so you can keep talking. The user approves each one. agent=name, task=what to do.",
           {"agent": {"type": "string"}, "task": {"type": "string"}}, ["agent", "task"]),
    schema("start_team", "Start a team of agents for a large job (the first layer marks it 'team'): LOKI picks the roles (researcher, architect, builder, tester, reviewer, browser tester), runs them in stages in this workspace, lets them talk on a shared board, and verifies the result. goal=the whole job in one or two sentences.",
           {"goal": {"type": "string"}}, ["goal"]),
    schema("team_post", "Post a note to your team's board (only when you are an agent on a team). to='all' or a role name.",
           {"text": {"type": "string"}, "to": {"type": "string"}}, ["text"]),
    schema("team_read", "Read your team's board: what teammates found, built and reported (only on a team).", {}, []),
    schema("improve_loki", "Change LOKI's own code (a feature, a fix, a new tool for yourself). A background LOKI agent makes the change in its own git worktree, tests it on the shared Mac/Windows test suites and ships it with ship_loki. task=what to change and why.",
           {"task": {"type": "string"}}, ["task"]),
    schema("check_loki", "Run LOKI's own test suites in this LOKI worktree (you cannot run shell commands; this is how you test a change to LOKI). suite=one suite name like test_portal for a quick check, empty for all of them. Returns each suite's PASS/FAIL lines.",
           {"suite": {"type": "string"}, "path": {"type": "string"}}, []),
    schema("ship_loki", "Publish a finished change to LOKI's own code: runs every test suite, commits, catches up with GitHub, pushes to master and tells the other machines to update. Pushes nothing if a test fails. message=one line: what changed and how it was checked; path=the worktree (default: this workspace).",
           {"message": {"type": "string"}, "path": {"type": "string"}}, ["message"]),
    schema("conductor", "You are the conductor: hand one step to a specialist. role='research' (a cited answer from the live web; task=question), 'read_web' (one page as markdown; url=...), 'browse' (a real browser does task on websites - asks the user), 'remember' (task=fact to keep long-term), 'recall' (task=question for long-term memory), 'media' (url=video; task='transcript'|'info'|'audio'|'video'|'search: words'), 'image' (task=what to draw), 'reach' (url=page to read, or task='github: ...' / 'doctor'), 'track' (url=video file in the workspace; task=what to track, e.g. 'car'; writes an annotated video and a per-track JSON/CSV to tracks/). Only roles listed under 'Specialists you can call' in your instructions are ready.",
           {"role": {"type": "string"}, "task": {"type": "string"}, "url": {"type": "string"}}, ["role"]),
    schema("knowledge", "Loki's context store, addressed as viking:// URIs: viking://memory/ and viking://state/ (read/write), viking://skills/ and viking://project/ (read-only docs). action='list' (default), 'read' or 'write' (with text).",
           {"action": {"type": "string"}, "uri": {"type": "string"}, "text": {"type": "string"}}, ["uri"]),
]


# The tools actually offered to the model. run_command/open_godot are deliberately
# excluded: they are dangerous (approval prompts) and a small model misuses them
# (e.g. unix "ls -R" on Windows), which stalls the whole task.
MODEL_TOOL_NAMES = {
    "list_ecc_agents", "load_ecc_agent", "list_ecc_skills", "load_ecc_skill", "sync_ecc",
    "godot_api", "godot_search", "read_scene", "add_input_action",
    "set_project_setting", "add_autoload",
    "list_files", "list_tree", "read_file", "folders", "write_file", "append_file",
    "edit_file", "search_files", "make_dir", "move_file", "delete_file",
    "build_3d_scene", "build_scene", "validate_scene", "play_scene", "probe_scene", "open_in_editor",
    "check_script", "capture_scene", "view_image", "project_state", "review_repository",
    "list_capabilities", "agent_sessions", "api_vault", "knowledge", "conductor", "delegate",
    "improve_loki", "ship_loki", "check_loki", "start_team", "team_post", "team_read",
    "forecast_series", "generate_media", "game_engine_guide",
    "crm_add", "crm_update", "crm_find", "crm_log", "crm_pipeline", "scrape", "video_project", "render_video",
    "insert_lines", "undo_edit", "memory", "read_web", "run_subagent", "task_tracker", "sketch_reply",
    # session 27 harvest
    "web_search", "research_web", "browse_page", "map_site", "reach", "code_map", "search_docs", "schedule_task",
    # 2026-10-25 (owner: "is it calling out tools? ... use gitbash and itch.io"): the shell was NEVER offered in the
    # window - run_command only reached background jobs. Offered now; every call still asks first (DANGEROUS).
    "run_command", "bash", "itch",
}
MODEL_TOOL_SCHEMAS = [t for t in TOOL_SCHEMAS if t["function"]["name"] in MODEL_TOOL_NAMES]



# --- tool categories (toggleable from the editor Settings dialog) ------------
TOOL_CATEGORIES = {
    "files": ["list_files", "list_tree", "read_file", "folders", "write_file", "append_file",
              "edit_file", "insert_lines", "undo_edit", "search_files", "make_dir", "move_file", "delete_file",
              "code_map", "search_docs"],
    "scenes": ["build_3d_scene", "build_scene", "validate_scene", "read_scene", "open_in_editor"],
    "godot": ["godot_api", "godot_search"],
    "project": ["add_input_action", "set_project_setting", "add_autoload", "review_repository"],
    "runtime": ["play_scene", "check_script", "capture_scene", "probe_scene", "view_image"],
    "planning": ["todo_add", "todo_list", "todo_done", "forecast_series", "project_state", "list_capabilities",
                 "agent_sessions", "api_vault", "task_tracker", "schedule_task"],
    "memory": ["save_memory", "knowledge", "memory"],
    "specialists": ["conductor", "delegate", "start_team", "team_post", "team_read", "improve_loki", "ship_loki",
                    "check_loki", "run_subagent"],
    "capabilities": ["list_capabilities"],
    "creative": ["generate_media", "video_project", "render_video", "game_engine_guide", "sketch_reply"],
    "business": ["crm_add", "crm_update", "crm_find", "crm_log", "crm_pipeline"],
    "web": ["scrape", "read_web", "web_search", "research_web", "browse_page", "map_site", "reach"],
    "skills": ["list_ecc_agents", "load_ecc_agent", "list_ecc_skills", "load_ecc_skill", "sync_ecc"],
    "system": ["run_command", "bash", "itch", "run_godot", "open_godot"],
}
# Tools that only make sense inside a Godot project (the optional game adapter).
GODOT_ONLY_TOOLS = {"build_3d_scene", "build_scene", "validate_scene", "read_scene", "open_in_editor",
                    "godot_api", "godot_search", "add_input_action", "set_project_setting",
                    "add_autoload", "play_scene", "check_script", "capture_scene", "probe_scene",
                    "run_godot", "open_godot"}
CATEGORY_LABELS = {
    "files": "Files (read/write/edit/search)",
    "scenes": "Scenes (build/validate/open in editor)",
    "runtime": "Runtime checks (run scene, compile script)",
    "planning": "Planning (todo list)",
    "memory": "Memory (save facts)",
    "capabilities": "Capabilities (what Loki can use right now)",
    "creative": "Creative (Higgsfield images and video - uses your credits; Remotion videos)",
    "business": "Business (LOKI's CRM: contacts, companies, deals, tasks)",
    "web": "Web (search, research with sources, read and browse pages, map sites, scrape and crawl)",
    "skills": "Skills (ECC agents and skills)",
    "godot": "Godot API reference (look up classes and methods)",
    "project": "Project setup (input actions, settings, autoloads)",
    "system": "System (shell commands, launch Godot) - dangerous",
    "runtime": "Runtime checks (run scene, compile script, screenshot + look)",
}
SETTINGS_FILE = DATA_DIR / "loki_settings.json"


SETTINGS_VERSION = 2   # 2: the "system" tools (run_command, bash, itch) are on by default - they always ask first


def _load_settings() -> dict:
    defaults = {name: True for name in TOOL_CATEGORIES}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        old = int(data.get("v", 1) or 1) < SETTINGS_VERSION
        for name, value in (data.get("categories") or {}).items():
            if name in defaults and not (old and name == "system"):   # an old file saved "system: off" as the default
                defaults[name] = bool(value)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


CATEGORIES = _load_settings()


def save_settings() -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps({"v": SETTINGS_VERSION, "categories": CATEGORIES}, indent=2), encoding="utf-8")
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


# Hard ceiling on how many tool schemas one request may carry. Providers reject a
# request that exceeds it (Groq: "'tools' : maximum number of items is 128"), and the
# whole turn fails - not just the excess tools. Loki's own tools are kept first, then
# MCP tools in connection order, so a big surface degrades instead of breaking.
MAX_TOOLS = int(os.getenv("LOKI_MAX_TOOLS", "128"))
TRIMMED_TOOLS_NOTE = ""


LOCAL_MAX_TOOLS = int(os.getenv("LOKI_LOCAL_MAX_TOOLS", "22"))
LOCAL_TOOL_PRIORITY = ["list_tree", "read_file", "edit_file", "write_file", "search_files",
                       "research_web", "web_search", "read_web", "code_map",   # session 27 harvest
                       "conductor", "delegate", "run_command", "bash", "make_dir", "move_file", "delete_file",
                       "knowledge", "save_memory", "todo_add", "todo_list", "todo_done",
                       "project_state", "append_file", "validate_scene", "play_scene",
                       "check_script", "build_scene", "read_scene", "godot_search"]
# Inside a LOKI worktree (an improve_loki / evolve job) the job is changing LOKI itself: testing
# and shipping are the tools it cannot do without, so they lead the local model's short list.
SELF_IMPROVE_PRIORITY = ["check_loki", "ship_loki", "read_file", "edit_file", "insert_lines", "search_files",
                         "write_file", "list_tree", "run_subagent", "memory", "task_tracker", "undo_edit"]


# --- Session 27 research ports (docs/integrations/research-2026-10-17.md) --------------------
# aider (repo map, SEARCH/REPLACE edits), langgraph-bigtool (find_tools), instructor (structured
# output), ReWOO (plan_and_solve), Reflexion (reflect), STORM (deep_research + web_search),
# Fooocus (image prompt styles), ACE-Step (make_music), Kokoro (speak). Licences: engine/licenses/.
import deep_research  # noqa: E402
import edit_blocks  # noqa: E402
import image_prompt  # noqa: E402
import music  # noqa: E402
import reflexion  # noqa: E402
import repo_map  # noqa: E402
import rewoo  # noqa: E402
import structured  # noqa: E402
import tool_select  # noqa: E402
import voice  # noqa: E402

FOUND_TOOLS: list = []          # tools find_tools added to a local model's list (newest last)
REWOO_TOOLS = {                 # what plan_and_solve may run: read-only tools only
    "search_files": {"description": "Search the project's files with a regular expression. Input: the pattern.",
                     "arg": "pattern"},
    "read_file": {"description": "Read a file. Input: the path, or {\"filename\": ..., \"start_line\": n, "
                                 "\"end_line\": m}.", "arg": "filename"},
    "list_tree": {"description": "Show the project's folders. Input: a sub-folder or '.'.", "arg": "subdir"},
    "repo_map": {"description": "The most important functions and classes of the code, ranked for a topic. "
                                "Input: the topic.", "arg": "focus"},
    "web_search": {"description": "Search the web. Input: the query.", "arg": "query"},
    "read_web": {"description": "Read a web page as text. Input: the URL.", "arg": "url"},
    "memory": {"description": "Recall what LOKI remembers. Input: what to recall.", "arg": "query"},
}


async def _port_ask(prompt: str, system: str = "", schema: dict | None = None, max_tokens: int = 0) -> str:
    """One plain model call for the research-port tools, on the model this request uses. With a schema
    a local server gets it as response_format (constrained JSON); a server that refuses it is asked again
    without. <think> blocks are removed from the answer."""
    provider = active_model_name()
    cfg = MODELS[provider]
    client = make_client()
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    kwargs = {"model": cfg.model, "messages": msgs,
              "max_tokens": int(max_tokens or os.getenv("LOKI_PORT_TOKENS", "2048"))}
    if "11434" in cfg.base_url or "ollama" in cfg.api_key:
        kwargs["extra_body"] = {"think": False}
    if schema and _cfg_is_local(cfg) and (provider or cfg.base_url) not in CONSTRAINED_REFUSED:
        kwargs["response_format"] = structured.response_format(schema)
    started = time.monotonic()
    try:
        response = await _model_request(client, kwargs, cfg, provider)
    except Exception:  # noqa: BLE001 - e.g. a server without json_schema: plain request once
        if "response_format" not in kwargs:
            raise
        kwargs.pop("response_format", None)
        CONSTRAINED_REFUSED.add(provider or cfg.base_url)
        response = await _model_request(client, kwargs, cfg, provider)
    _record_usage(response, kwargs, cfg, started)
    _record_request_usage(provider, response)
    return structured.strip_thinking(response.choices[0].message.content or "")


def repo_map_tool(focus: str = "", subdir: str = ".", max_chars: int = 6000, files: str = "") -> str:
    """aider's repo map of the workspace, ranked for `focus` (a question, symbol names or file names)."""
    base = resolve_in_workspace(subdir or ".")
    chat = [f.strip() for f in str(files or "").split(",") if f.strip()]
    return repo_map.build(WORKSPACE, focus=str(focus or ""), chat_files=chat,
                          max_chars=max(500, min(int(max_chars or 6000), 20000)),
                          subdir=str(base.relative_to(WORKSPACE.resolve())) if base != WORKSPACE.resolve() else ".")


def apply_edits(blocks: str) -> str:
    """aider's SEARCH/REPLACE blocks, several files in one call; undo_edit reverts a file."""
    out = edit_blocks.apply(str(blocks or ""), resolve_in_workspace)
    for name in out["applied"]:
        try:
            note = _check_written(name)
        except Exception:  # noqa: BLE001
            note = ""
        if note:
            out["report"] += "\n" + note
    return out["report"]


def _findable_schemas() -> list:
    schemas = [t for t in TOOL_SCHEMAS if t["function"]["name"] in MODEL_TOOL_NAMES
               and _tool_enabled(t["function"]["name"])]
    schemas = [t for t in schemas if not policy.CAPABILITY_TOOLS.get(t["function"]["name"])
               or CAPABILITIES.is_enabled(policy.CAPABILITY_TOOLS[t["function"]["name"]])]
    if not is_godot_workspace():
        schemas = [t for t in schemas if t["function"]["name"] not in GODOT_ONLY_TOOLS]
    return [t for t in schemas if t["function"]["name"] != "find_tools"]


def find_tools(query: str, limit: int = 3) -> str:
    """langgraph-bigtool's retrieve_tools: the best tools for a need; they join a local model's list."""
    schemas = _findable_schemas()
    found = [name for name, _score in tool_select.rank(query, schemas, limit=max(1, min(int(limit or 3), 6)))]
    if not found:
        return "No tool matches '%s'. Try other words (what you want to do, not how)." % query
    tool_select.promote(LOCAL_TOOL_PRIORITY, found, anchor="find_tools", unlocked=FOUND_TOOLS)
    return ("These tools can do it and are available from your next step on - call them directly:\n"
            + tool_select.describe(schemas, found))


async def plan_and_solve(task: str) -> str:
    """ReWOO: one plan with all tool calls, the tools run, then one answer from the evidence."""
    if not str(task or "").strip():
        return "error: say what to find out"

    async def ask(prompt):
        return await _port_ask(prompt)

    async def run_tool(name, args):
        if name == "memory":
            args = {"action": "recall", **args}
        fix = _guard_call(name, json.dumps(args))
        if not fix.ok:
            return "error: %s" % fix.error
        return await call_tool(fix.name, fix.args)

    workers = {k: v for k, v in REWOO_TOOLS.items() if k in LOCAL_TOOLS}
    out = await rewoo.run(str(task), ask, workers, run_tool, progress=lambda t: _progress("thinking", t))
    steps = "\n".join("%s = %s[%s] -> %s" % (s["var"], s["tool"] or "-", s["input"][:120],
                                            " ".join(str(s.get("result", "")).split())[:160]) for s in out["steps"])
    return "%s\n\n(plan and evidence)\n%s" % (str(out["answer"]).strip(), steps or "(no tool steps)")


async def reflect_tool(task: str, attempt: str = "", feedback: str = "") -> str:
    """Reflexion: diagnose a failed attempt + a new plan, kept as an episodic memory."""
    if not str(task or "").strip():
        return "error: say which task failed"

    def learn(text, tags):
        return memory_core.learn(text, tier="episodic", tags=tags, root=DATA_DIR, source="reflexion",
                                 meta={"workspace": str(WORKSPACE)})

    out = await reflexion.reflect(task, attempt, feedback, _port_ask, learn)
    if not out.get("ok"):
        return "error: %s" % out.get("error")
    return ("Reflection (kept in memory%s; use it now):\n%s"
            % ((" as " + out["stored"]) if out.get("stored") else "", out["reflection"]))


async def extract_structured(text: str = "", schema=None, instruction: str = "") -> str:
    """instructor-style: JSON that matches `schema`, validated and re-asked; constrained on local models."""
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except ValueError:
            return "error: schema must be a JSON Schema object"
    if not isinstance(schema, dict) or not schema:
        return "error: give a JSON Schema, e.g. {\"type\": \"object\", \"properties\": {...}, \"required\": [...]}"
    what = str(instruction or "Extract the information as JSON.")
    if str(text or "").strip():
        what += "\n\nText:\n" + str(text)[:12000]
    out = await structured.ask_structured(lambda prompt, schema=None: _port_ask(prompt, schema=schema), what, schema)
    if out["ok"]:
        return json.dumps(out["value"], ensure_ascii=False, indent=1)
    return "error: no valid JSON after %d tries: %s" % (out["attempts"], "; ".join(out["errors"][:5]))


async def deep_research_tool(question: str, depth: int = 1) -> str:
    """STORM: perspectives -> questions -> searches -> read pages -> cited report in research/."""
    if not str(question or "").strip():
        return "error: say what to research"

    async def search_fn(query):
        return await asyncio.to_thread(deep_research.search, query, 6)

    async def read_fn(url):
        return await asyncio.to_thread(read_web, url, deep_research.READ_CHARS)

    out = await deep_research.run(str(question), _port_ask, search_fn, read_fn,
                                  depth=max(1, min(int(depth or 1), 3)),
                                  progress=lambda t: _progress("thinking", "research: " + t))
    if not out.get("report"):
        return "error: %s" % out.get("error", "no report")
    folder = WORKSPACE / "research"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("%s-%s.md" % (time.strftime("%Y%m%d-%H%M"), deep_research.slug(question)))
    path.write_text(out["report"], encoding="utf-8")
    rel = path.relative_to(WORKSPACE).as_posix()
    return ("wrote %s (%d sources, %d questions researched). The report:\n\n%s"
            % (rel, len(out["sources"]), len(out["questions"]), out["report"][:6000]))


async def enhance_image_prompt(prompt: str, style: str = "", seed: int = 0) -> str:
    """Fooocus: a short idea -> a rich image prompt in a named style (+ negative prompt)."""
    if str(style or "").strip().lower() in ("list", "styles", "?"):
        return "Styles: " + ", ".join(sorted(image_prompt.styles()))
    out = await image_prompt.enhance(prompt, style, ask=_port_ask, seed=int(seed or 0))
    if not out.get("ok"):
        return "error: %s" % out.get("error")
    return ("prompt: %s\nnegative: %s\nstyle: %s\n(pass the prompt to generate_media or the image specialist)"
            % (out["prompt"], out["negative"] or "-", out["style"] or "none"))


async def make_music(prompt: str = "", lyrics: str = "", duration: float = 0, bpm: int = 0, key: str = "") -> str:
    """ACE-Step 1.5 on this computer (or LOKI_ACESTEP_URL): a song into music/."""
    out = await asyncio.to_thread(music.make, prompt, WORKSPACE / "music", lyrics, duration, bpm, key)
    if not out.get("ok"):                   # no ACE-Step server: the same model on the owner's ComfyUI (the PC)
        import comfy_jobs  # pylint: disable=import-outside-toplevel
        alt = await asyncio.to_thread(comfy_jobs.make_music, {"tags": prompt, "lyrics": lyrics,
                                                              "seconds": duration or 60, "bpm": bpm or None,
                                                              "key": key}, WORKSPACE / "music")
        if not alt.get("ok"):
            return "error: %s (ComfyUI: %s)" % (out["error"], alt.get("error"))
        out = alt
    return "made %s" % ", ".join(Path(p).relative_to(WORKSPACE).as_posix() for p in out["files"])


async def speak(text: str, voice_name: str = "") -> str:
    """Kokoro (or the OS voice): text read aloud into voice/<file>."""
    out = await asyncio.to_thread(voice.speak, text, WORKSPACE / "voice", voice_name)
    if not out.get("ok"):
        return "error: %s" % out["error"]
    return "spoke it with %s: %s" % (out["engine"], Path(out["file"]).relative_to(WORKSPACE).as_posix())


LOCAL_TOOLS.update({"repo_map": repo_map_tool, "apply_edits": apply_edits, "find_tools": find_tools,
                    "plan_and_solve": plan_and_solve, "reflect": reflect_tool,
                    "extract_structured": extract_structured,   # web_search: the harvest's (SearxNG/DDG/arXiv)
                    "deep_research": deep_research_tool, "enhance_image_prompt": enhance_image_prompt,
                    "make_music": make_music, "speak": speak})
_PORT_SCHEMAS = [
    schema("repo_map", "A map of the code: the most important files, classes and functions, with the line that "
           "defines each, ranked by how much the code depends on them and by `focus` (the question, symbol names "
           "or file names you care about). Read it before searching a project you do not know.",
           {"focus": {"type": "string"}, "subdir": {"type": "string"}, "max_chars": {"type": "integer"},
            "files": {"type": "string"}}),
    schema("apply_edits", "Edit one or more files with SEARCH/REPLACE blocks (no JSON escaping of code). blocks = "
           "text with, for each edit: the file path alone on a line, then '<<<<<<< SEARCH', the exact current "
           "lines, '=======', the new lines, '>>>>>>> REPLACE'. An empty SEARCH creates the file. Failed blocks "
           "come back with the closest real lines; resend only those.",
           {"blocks": {"type": "string"}}, ["blocks"]),
    schema("find_tools", "Find a tool you do not see in your list: describe what you need (e.g. 'make a song', "
           "'search the web', 'map the code'); the best matches are shown and become callable from your next step.",
           {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    schema("plan_and_solve", "Answer a question that needs several lookups in ONE go: you get a plan of tool calls "
           "(search_files, read_file, list_tree, repo_map, web_search, read_web, memory), they run, and one answer "
           "comes back with the evidence. Cheaper and steadier than many separate calls.",
           {"task": {"type": "string"}}, ["task"]),
    schema("reflect", "After something failed (a test, a refused call, the user said it is wrong): write a short "
           "diagnosis and a new plan, kept in memory so this and later similar tasks avoid the same mistake. "
           "attempt = what you did, feedback = the error or what was wrong.",
           {"task": {"type": "string"}, "attempt": {"type": "string"}, "feedback": {"type": "string"}}, ["task"]),
    schema("extract_structured", "Get data out of text as JSON that matches a JSON Schema - validated, and fixed "
           "automatically when it does not match.",
           {"text": {"type": "string"}, "schema": {"type": "object"}, "instruction": {"type": "string"}}, ["schema"]),
    schema("deep_research", "Research a topic on the web and write a report with numbered citations and a "
           "reference list (saved in research/). depth 1 (quick) to 3 (thorough). Takes a few minutes.",
           {"question": {"type": "string"}, "depth": {"type": "integer"}}, ["question"]),
    schema("enhance_image_prompt", "Turn a short picture idea into a rich image prompt (+ negative prompt) in a "
           "style: pixel art, cinematic, anime, photographic, fantasy art, digital art, comic book, lowpoly, "
           "isometric, analog film, neonpunk, craft clay, origami, line art, 3d-model... (style='list' lists them). "
           "Then make the picture with the enhanced prompt.",
           {"prompt": {"type": "string"}, "style": {"type": "string"}, "seed": {"type": "integer"}}, ["prompt"]),
    schema("make_music", "Make a song or a piece of music (ACE-Step 1.5, free: its server on this computer, else the "
           "owner's ComfyUI on the PC). prompt = genre, mood, "
           "instruments, voice; lyrics optional ([verse]/[chorus] lines); duration in seconds.",
           {"prompt": {"type": "string"}, "lyrics": {"type": "string"}, "duration": {"type": "number"},
            "bpm": {"type": "integer"}, "key": {"type": "string"}}, []),
    schema("speak", "Read text aloud into an audio file (Kokoro voice when installed, else the computer's own "
           "voice). voice_name e.g. af_heart, am_michael, bf_emma.",
           {"text": {"type": "string"}, "voice_name": {"type": "string"}}, ["text"]),
]
TOOL_SCHEMAS.extend(_PORT_SCHEMAS)
MODEL_TOOL_SCHEMAS.extend(_PORT_SCHEMAS)
MODEL_TOOL_NAMES.update(LOCAL_TOOLS.keys() & {s["function"]["name"] for s in _PORT_SCHEMAS})
TOOL_CATEGORIES["files"] += ["repo_map", "apply_edits"]
TOOL_CATEGORIES["planning"] += ["find_tools", "plan_and_solve", "extract_structured"]
TOOL_CATEGORIES["memory"] += ["reflect"]
TOOL_CATEGORIES["research"] = ["web_search", "deep_research"]
CATEGORY_LABELS["research"] = "Research (web search without a key, cited deep-research reports)"
CATEGORIES.setdefault("research", True)
TOOL_CATEGORIES["creative"] += ["enhance_image_prompt", "make_music", "speak"]
MODIFYING |= {"apply_edits", "deep_research", "make_music", "speak"}
# find_tools is how a local model reaches every other tool; repo_map is how it finds its way in code.
LOCAL_TOOL_PRIORITY[5:5] = ["find_tools", "repo_map"]

# --- Session 28: tools LOKI writes for itself (EVOLVE E9, engine/user_tools.py) + speed watch (E6) ---
import speed_watch  # noqa: E402
import user_tools  # noqa: E402


def _user_tool_runner(tool_name: str):
    """LOCAL_TOOLS entry for a tool LOKI wrote: ask first (like run_command, never auto-decided), then
    run it in its own sandboxed python process in the workspace."""
    async def run(**args) -> str:
        path = user_tools.folder(tool_name, DATA_DIR)
        meta = user_tools.read_meta(path)
        if not meta.get("enabled"):
            return "error: the tool %s is switched off (Settings > Tools)" % tool_name
        detail = "%s(%s)" % (tool_name, json.dumps(args, ensure_ascii=False, default=str)[:300])
        if not await approve("user_tool", detail, decidable=False):
            return ("DENIED: running your own tool %s was not approved (a background job may run it only when it "
                    "was started with commands allowed). Do it with other tools, or reply 'BLOCKED: <reason>'." % tool_name)
        _ok, out = await asyncio.to_thread(user_tools.execute, path, args, WORKSPACE, int(meta.get("timeout") or 30))
        return out
    return run


USER_TOOLS = user_tools.Registry(sys.modules[__name__], lambda: DATA_DIR, _user_tool_runner)


def make_tool(name: str, description: str, code: str, parameters=None, required=None, tests=None,
              timeout: int = 30, network: bool = False) -> str:
    """Write a new tool for yourself (harness_data/tools/<name>/), check it, and load it at once."""
    out = user_tools.make(name, description, code, parameters=parameters, required=required, tests=tests,
                          timeout=timeout, network=network, by="loki", root=DATA_DIR, reserved=USER_TOOLS.builtin())
    USER_TOOLS.sync()
    if out.get("ok"):
        tool_select.promote(LOCAL_TOOL_PRIORITY, [out["name"]], anchor="find_tools", unlocked=FOUND_TOOLS)
        return ("made tool %s: its check passed (%s) and it is callable from your next step. Every call asks the "
                "owner first." % (out["name"], out["check"].get("detail") or "tests ok"))
    return "error: %s" % out.get("error")


LOCAL_TOOLS["make_tool"] = make_tool
_E9_SCHEMA = schema(
    "make_tool", "Write a small tool for yourself when you need the same kind of work again and no tool does it: "
    "Python with `def run(args: dict) -> str` (standard library; no subprocess/eval/deleting files; network only "
    "with network=true), its parameters as JSON Schema properties, and tests [{\"args\": {...}, \"expect\": "
    "\"text the output must contain\"}]. It is checked (compiled, scanned, tests run in a sandbox) and, when it "
    "passes, loaded at once; every call asks the owner first.",
    {"name": {"type": "string"}, "description": {"type": "string"}, "code": {"type": "string"},
     "parameters": {"type": "object"}, "required": {"type": "array", "items": {"type": "string"}},
     "tests": {"type": "array", "items": {"type": "object"}}, "timeout": {"type": "integer"},
     "network": {"type": "boolean"}}, ["name", "description", "code", "tests"])
TOOL_SCHEMAS.append(_E9_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_E9_SCHEMA)
MODEL_TOOL_NAMES.add("make_tool")
TOOL_CATEGORIES["planning"] += ["make_tool"]
TOOL_CATEGORIES["my_tools"] = []
CATEGORY_LABELS["my_tools"] = "Tools LOKI wrote for itself (each call asks first)"
CATEGORIES.setdefault("my_tools", True)
DANGEROUS.add("make_tool")          # writing code that is then run asks first, like run_command
POLICY.dangerous.add("make_tool")
try:
    USER_TOOLS.sync()
except Exception as _exc:  # noqa: BLE001 - a broken tool folder must never stop LOKI starting
    print("[loki] tools LOKI wrote could not be loaded: %s" % _exc)


# ---------------------------------------------------------------------------
# Session 28 creative pipelines (engine/creative.py): a short video made on this machine
# (Wan2GP on the PC; Higgsfield when its key is set), from words or from a picture.
# ---------------------------------------------------------------------------
async def make_local_video(prompt: str, image: str = "", seconds: float = 3) -> str:
    """Wan2GP (LTX-Video distilled, 8 GB profile) or Higgsfield: a short video into videos/."""
    import creative  # pylint: disable=import-outside-toplevel
    if image and not (WORKSPACE / image).resolve().is_relative_to(WORKSPACE.resolve()):
        return "error: the picture must be in the workspace"
    out = await asyncio.to_thread(creative.make_video, prompt, WORKSPACE, image, float(seconds or 3))
    return ("made %s with %s%s" % (out["file"], out["backend"], (" (%s)" % out["note"]) if out.get("note") else "")
            if out.get("ok") else "error: %s" % out.get("error"))


LOCAL_TOOLS["make_local_video"] = make_local_video
_VIDEO_SCHEMA = schema("make_local_video", "Make a short video (1-10 s) on this computer for free: Wan2GP on the PC "
                       "(text-to-video, or image-to-video when image = a picture in the workspace, e.g. "
                       "images/fox.png - 'animate this'); falls back to Higgsfield when its key is set. Saved in videos/.",
                       {"prompt": {"type": "string"}, "image": {"type": "string"}, "seconds": {"type": "number"}},
                       ["prompt"])
TOOL_SCHEMAS.append(_VIDEO_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_VIDEO_SCHEMA)
MODEL_TOOL_NAMES.add("make_local_video")
TOOL_CATEGORIES["creative"] += ["make_local_video"]
MODIFYING |= {"make_local_video"}


# ---------------------------------------------------------------------------
# Session 29 automations (engine/automations.py): the owner says "every morning at 8 send me ..."
# and LOKI drafts it - switched OFF until the owner reads the card and turns it on.
# ---------------------------------------------------------------------------
def automation(action: str = "list", text: str = "", id: str = "") -> str:  # noqa: A002
    """list | draft (from the owner's sentence; saved OFF) | show | run (an existing one)."""
    import automations as _automations  # pylint: disable=import-outside-toplevel
    return _automations.tool(action, text, id)


LOCAL_TOOLS["automation"] = automation
_AUTOMATION_SCHEMA = schema(
    "automation", "The owner's automations - things LOKI does by itself on a trigger (a schedule, a file in a folder, "
    "a new email, a calendar event, a webhook, a Telegram keyword, a job finishing, a machine coming online). "
    "action='draft' with text = the owner's own sentence (e.g. 'every morning at 8 send me the weather and my calendar "
    "on Telegram') drafts one, switched OFF: show the owner the card and tell them to turn it on in Settings > "
    "Automations. 'list' shows them, 'show' one (id), 'run' starts one now (id).",
    {"action": {"type": "string", "enum": ["list", "draft", "show", "run"]}, "text": {"type": "string"},
     "id": {"type": "string"}}, ["action"])
TOOL_SCHEMAS.append(_AUTOMATION_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_AUTOMATION_SCHEMA)
MODEL_TOOL_NAMES.add("automation")
TOOL_CATEGORIES["planning"] += ["automation"]
NETWORK_WRITES |= {"automation"}          # not in Plan mode (a draft is saved)


def _godot_live_wanted() -> bool:
    """A job for the live Godot editor (LOKI_GODOT_LIVE, set by workers for the Godot tab's jobs) or an editor linked
    to this engine right now: then godot_editor must reach a local model's short list (it fell off it - W50)."""
    if os.getenv("LOKI_GODOT_LIVE", "") == "1":
        return True
    try:
        return any(e.alive() for e in list(godot_live.hub().editors.values()))
    except Exception:  # noqa: BLE001
        return False


# A local model gets a short tool list; a tool the request NAMES must be on it (owner 2026-10-25: "use gitbash
# and itch.io"). _REQUEST_HINT is the newest user message, set before each model call.
_REQUEST_HINT = ""
HINT_TOOLS = {"itch": ("itch.io", "itch ", "butler"), "bash": ("git bash", "gitbash", "bash", "pipe", "pipeline", "grep ")}


def _hinted(name: str) -> bool:
    keys = HINT_TOOLS.get(name)
    return bool(keys and _REQUEST_HINT and any(k in _REQUEST_HINT for k in keys))


def _local_rank(name: str) -> int:
    if name == "godot_editor" and _godot_live_wanted():
        return -90
    if _hinted(name):
        return -70
    if name in ("team_read", "team_post") and os.getenv("LOKI_TEAM_ID"):
        return -100   # an agent on a team must reach its board (they fell off the local model's short list)
    if name in SELF_IMPROVE_PRIORITY and _in_loki_worktree():
        return SELF_IMPROVE_PRIORITY.index(name) - len(SELF_IMPROVE_PRIORITY) - 1
    try:
        return LOCAL_TOOL_PRIORITY.index(name)
    except ValueError:
        return len(LOCAL_TOOL_PRIORITY) + (0 if name in LOCAL_TOOLS else 50)


def _is_local_model() -> bool:
    try:
        cfg = MODELS[active_model_name()]
    except Exception:
        return False
    host = cfg.base_url
    return any(h in host for h in ("11434", "127.0.0.1", "localhost")) and not host.startswith(CLI_AGENT_PREFIX)


def model_tool_schemas() -> list:
    """The tool schemas to offer the model: enabled categories, within the budget."""
    global TRIMMED_TOOLS_NOTE
    if AGENT_MODE == "ask":
        # Ask mode is a conversation, not an agent turn: no tools at all.
        TRIMMED_TOOLS_NOTE = "ask mode: no tools offered"
        return []
    schemas = [t for t in TOOL_SCHEMAS if t["function"]["name"] in MODEL_TOOL_NAMES
               and _tool_enabled(t["function"]["name"])]
    # A tool that needs an add-on (policy.CAPABILITY_TOOLS, e.g. render_video -> remotion) is
    # only offered while that add-on is on: offering a tool that is always refused wastes a turn.
    schemas = [t for t in schemas if not policy.CAPABILITY_TOOLS.get(t["function"]["name"])
               or CAPABILITIES.is_enabled(policy.CAPABILITY_TOOLS[t["function"]["name"]])]
    if not is_godot_workspace():
        # Outside a Godot project the game tools only mislead a model into writing .tscn
        # files for a website (seen on the PC, 2026-10-14). LOKI is not a Godot project.
        schemas = [t for t in schemas if t["function"]["name"] not in GODOT_ONLY_TOOLS]
    local_note = ""
    if _is_local_model():
        # A local model reads every tool schema on every turn: fewer, better-chosen tools
        # mean a much faster first token and steadier tool calls. MAX_TOOLS stays a hard
        # ceiling on top of that (providers reject an over-long list outright).
        schemas = sorted(schemas, key=lambda t: _local_rank(t["function"]["name"]))[:LOCAL_MAX_TOOLS]
        local_note = "local model: %d core tools offered" % len(schemas)
    if AGENT_MODE == "plan":
        # Plan mode is read-only: no writing, moving, deleting or running.
        schemas = [t for t in schemas
                   if t["function"]["name"] in LOCAL_TOOLS
                   and t["function"]["name"] not in MODIFYING
                   and t["function"]["name"] not in DANGEROUS
                   and t["function"]["name"] not in RUNS_PROJECT
                   and t["function"]["name"] not in NETWORK_WRITES
                   and t["function"]["name"] not in DELEGATING]
    if MAX_TOOLS <= 0 or len(schemas) <= MAX_TOOLS:
        TRIMMED_TOOLS_NOTE = local_note
        return schemas
    local = [t for t in schemas if t["function"]["name"] in LOCAL_TOOLS]
    remote = [t for t in schemas if t["function"]["name"] not in LOCAL_TOOLS]
    kept = local[:MAX_TOOLS]
    kept += remote[:max(0, MAX_TOOLS - len(kept))]
    dropped = len(schemas) - len(kept)
    TRIMMED_TOOLS_NOTE = ("%d tools offered, %d held back to stay under LOKI_MAX_TOOLS=%d "
                          "(raise it for a provider with a larger limit)"
                          % (len(kept), dropped, MAX_TOOLS))
    return kept


def categories_state() -> dict:
    return {"categories": CATEGORIES, "labels": CATEGORY_LABELS}


_ENGLISH_RULE = (
    "# Language - ENGLISH ONLY, always" + chr(10)
    + "Every word you produce must be in English: replies, questions, plans, todo items,"
    + " code comments and commit messages. Never answer in any other language, not even"
    + " one sentence, even when the user writes in another language or the project"
    + " contains another language. Leave the non-English *data* of a file you were asked"
    + " to edit alone, but keep all of your own writing in English."
)

# Session 29 (LOKI for anyone): LOKI answers in the user's language by default.
# LOKI_REPLY_LANGUAGE: match (default) = the language the user writes in, ui = always the window's
# language (LOKI_LANGUAGE), en = English only (_ENGLISH_RULE, the old behaviour).
_LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "ar": "Arabic",
                   "hi": "Hindi", "zh": "Chinese (Simplified)", "ja": "Japanese"}


def _ui_language() -> str:
    code = (os.environ.get("LOKI_LANGUAGE", "auto") or "auto").strip().lower()
    if code == "auto":
        code = (os.environ.get("LOKI_BROWSER_LANGUAGE", "") or "en").strip().lower()
    return code if code in _LANGUAGE_NAMES else "en"


def _language_rule() -> str:
    reply = (os.environ.get("LOKI_REPLY_LANGUAGE", "match") or "match").strip().lower()
    if reply == "en":
        return _ENGLISH_RULE
    name = _LANGUAGE_NAMES[_ui_language()]
    keep = (" Code, code comments, commit messages, file names and tool arguments stay in English"
            " unless the user asks otherwise; leave the data of files you edit in their own language.")
    if reply == "ui":
        return ("# Language - always " + name + chr(10) + "Write every reply, question and plan in " + name
                + ", whatever language the user or the project uses." + keep)
    return ("# Language - answer in the user's language" + chr(10)
            + "Reply in the language the user's latest message is written in. When it gives no clear"
            + " language (a command, a link, a file name), use " + name + ". Never switch to a language"
            + " the user did not use - not even one sentence." + keep)


SYSTEM_PROMPT = '''You are LOKI. You are a SENIOR GAME DEVELOPER working autonomously in a Godot 4 project. You are practical, rigorous and concise.

# What you are - answer questions about yourself from HERE, without using a single tool
When the user asks about YOU (what you are, what you can do, how to use you, which model
you are on, what you remember), that is a CONVERSATION, not a task. Answer from this
section, in a few sentences, and make NO tool call at all. Do not list the project, read
files, or "check" yourself by exploring: nothing in the project describes you, and going
to look for it wastes the user's time and looks broken.

- You are Loki, an agent that lives in this project's left-hand dock in the Godot 4
  editor. You read the project, edit its scenes and scripts, run Godot to check your own
  work, and iterate until the job is done.
- You work in three modes, picked in the dock: ASK answers a question and touches
  nothing; PLAN reads the project, asks up to three clarifying questions, then writes a
  numbered plan; BUILD is the full autonomous agent.
- Your tools: read/write/move files in the workspace, search, run shell commands, run the
  engine headless, build scenes with build_3d_scene, and unlock extra Godot capability
  domains on demand with godot_enable_toolset.
- You run on the model the user picks: a free route with no key, a local Ollama model, or
  their own provider key. "smart" picks the best one available and falls over to the next
  when a quota runs out.
- You keep a Memory of lasting facts about the user and the project (Settings -> Memory),
  and every conversation is saved as its own tab.
- You keep a RESUMABLE PROJECT STATE (the project_state tool): objective, phase, what is
  done, files changed, tests, known issues, decisions, blockers and next actions. Update
  it at each milestone so the work survives a restart or a different model.

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

Beyond these tools, the Godot editor exposes capability domains you can unlock on
demand - animation, scene_3d, tilemap, shader, theme and UI, resources (.tres), physics,
particles, navigation, audio, input, input map, profiling, batch, analysis, export, the
debugger, and more. godot_list_toolsets lists them all with a description. Before doing
a Godot task by hand, call godot_enable_toolset with category set to the domain name (for
example "animation"); that domain's tools become callable on your next step, and
godot_disable_toolset turns it off again. A domain whose min_godot is 4.4 needs the
editor's Godot bridge connected.

What you remember about the user from previous sessions:
{memory}

When you learn a new lasting fact about the user, save it with save_memory.'''


def _read_vendor(*parts: str) -> str:
    try:
        return (DATA_DIR / "vendor").joinpath(*parts).read_text(encoding="utf-8")
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

# Chats live in <workspace>/.loki/. Older builds kept them in <workspace>/.godot/; the
# first run copies them across (never deletes the old copy).
HISTORY_FILE = WORKSPACE / ".loki" / "loki_history.json"
CONVERSATIONS_FILE = WORKSPACE / ".loki" / "loki_conversations.json"


def _adopt_legacy_chats() -> None:
    for new in (HISTORY_FILE, CONVERSATIONS_FILE):
        old = WORKSPACE / ".godot" / new.name
        if not new.exists() and old.is_file():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, new)
            except OSError:
                pass


_adopt_legacy_chats()


_MESSAGE_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")


def _as_dict(message) -> dict:
    """A plain, JSON-safe chat message from either a dict or a provider object.

    Providers hand back two different shapes: raw dictionaries (our own HTTP routes,
    some OpenAI-compatible servers) and SDK objects (openai's ChatCompletionMessage,
    which is what Ollama goes through). Everything that walks or saves the
    conversation assumes a dict, so this MUST be applied at the point a message
    enters the list. An object left in there crashes the history pass with
    "'ChatCompletionMessage' object has no attribute 'get'".
    """
    if isinstance(message, dict):
        raw: dict = message
    else:
        raw = {}
        for attr in ("model_dump", "to_dict", "dict"):
            method = getattr(message, attr, None)
            if not callable(method):
                continue
            try:
                candidate = method()
            except Exception:  # noqa: BLE001 - a broken dumper must not end the turn
                continue
            if isinstance(candidate, dict):
                raw = candidate
                break
        else:
            raw = {}
        if not raw:
            # Manual fallback. tool_calls is kept deliberately: without it the
            # following role:"tool" messages point at ids the provider cannot resolve.
            calls = []
            for call in (getattr(message, "tool_calls", None) or []):
                fn = getattr(call, "function", None)
                calls.append({
                    "id": getattr(call, "id", "") or "",
                    "type": "function",
                    "function": {"name": getattr(fn, "name", "") or "",
                                 "arguments": getattr(fn, "arguments", "") or "{}"},
                })
            raw = {"role": getattr(message, "role", "assistant") or "assistant",
                   "content": getattr(message, "content", None) or ""}
            if calls:
                raw["tool_calls"] = calls
    # Keep only what a chat message may carry; strict providers reject stray fields.
    return {key: raw[key] for key in _MESSAGE_KEYS if key in raw}


_REPLACEMENT_CHAR = chr(0xFFFD)
_NL = chr(10)
_CR = chr(13)
_TAB = chr(9)
_TRAILING_BLANKS = re.compile("[" + " " + _TAB + "]+" + _NL)
_BLANK_RUN = re.compile(_NL + "{3,}")


def clean_text(text: str) -> str:
    """Normalise text so the chat never shows mangled or stray characters.

    A byte that did not decode becomes U+FFFD, which renders as a black diamond;
    stray control bytes, trailing spaces and runaway blank lines are just as ugly.
    """
    text = str(text).replace(_CR + _NL, _NL).replace(_CR, _NL)
    text = text.replace(_REPLACEMENT_CHAR, "")
    text = "".join(ch for ch in text if ch in (_NL, _TAB) or ord(ch) >= 32)
    text = _TRAILING_BLANKS.sub(_NL, text)
    text = _BLANK_RUN.sub(_NL + _NL, text)
    return text.strip()


def _sanitize_history(items: list) -> list:
    # Anything that is not a dict is normalised first (see _as_dict).
    items = [_as_dict(item) for item in items]
    # keep only plain conversational turns, cleaned and de-duplicated
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant") or item.get("tool_calls"):
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        content = clean_text(content)
        if not content:
            continue
        head = content.upper()
        if head.startswith("GOAL:") or head.startswith("DONE:") or head.startswith("BLOCKED:"):
            continue
        if clean and clean[-1]["role"] == role and clean[-1]["content"] == content:
            continue
        clean.append({"role": role, "content": content})
    return clean[-40:]


PROFILE: dict = {"name": "", "notes": ""}


# --- Modes: ask -> plan -> build --------------------------------------------
# The panel works in one of three modes, and the point is to stop the agent charging
# into a change it does not understand yet:
#   ask    answer the question. No tools, nothing touched.
#   plan   investigate READ-ONLY, ask the questions that clear the fog, then write
#          a numbered plan. Nothing is implemented.
#   build  the full autonomous agent (the original behaviour).
AGENT_MODE = str(os.getenv("LOKI_MODE", "build")).strip().lower() or "build"
MODE_LABELS = {"ask": "Ask", "plan": "Plan", "build": "Build"}
MODE_PROMPTS = {
    "ask": (
        "You are Loki in ASK mode. Answer the user's question directly and briefly." + chr(10)
        + "Rules:" + chr(10)
        + "- Call NO tools. Change nothing, start no task." + chr(10)
        + "- Answer from what you already know about the project. If you genuinely need to"
        + " look something up, say exactly which file you would read." + chr(10)
        + "- Be concise. No preamble, no restating the question."
    ),
    "plan": (
        "You are Loki in PLAN mode. Investigate, then plan - and write nothing." + chr(10)
        + "Rules:" + chr(10)
        + "- You may only READ (read_file, list_tree, search_files, read_scene, godot_api,"
        + " godot_search). Every writing, running and deleting tool is unavailable to you."
        + chr(10)
        + "- FIRST clear the fog: if anything about the request is open, ask up to three"
        + " short questions, each with the options you would choose, then stop." + chr(10)
        + "- When there is no fog left, answer with a numbered plan of 3 to 7 steps naming"
        + " the files you would touch. Do not implement it."
    ),
}


def set_mode(mode: str) -> str:
    """Switch mode. Returns the mode actually in effect."""
    global AGENT_MODE
    name = str(mode or "").strip().lower()
    if name in MODE_LABELS:
        AGENT_MODE = name
    return AGENT_MODE


def mode_state() -> dict:
    return {"mode": AGENT_MODE, "label": MODE_LABELS.get(AGENT_MODE, AGENT_MODE),
            "modes": [{"id": key, "label": MODE_LABELS[key]} for key in ("ask", "plan", "build")]}


# BUILD mode outside a Godot project: the standalone app's default. Same working
# discipline as SYSTEM_PROMPT, without the game-engine framing.
SYSTEM_PROMPT_GENERAL = '''You are LOKI, a desktop command center for software and creative work: an autonomous senior engineer who is practical, rigorous and concise.

# What you are - answer questions about yourself from HERE, without using a single tool
When the user asks about YOU (what you are, what you can do, which model you are on, what
you remember), that is a CONVERSATION, not a task. Answer from this section in a few
sentences and make NO tool call.

- You are Loki, running as a standalone desktop app. You work in one workspace folder:
  you read it, edit its files, run checks, and iterate until the job is done.
- Three modes, picked in the app: ASK answers and touches nothing; PLAN reads, asks up
  to three clarifying questions, then writes a numbered plan; BUILD is the full agent.
- Your tools: read/write/move files in the workspace, search, project state, memory,
  the capability registry, the API vault and the skill libraries. Shell commands and
  other risky tools need the user's approval in the app.
- You run on the model the user picks; "smart" picks the best available and fails over.
- You keep a Memory of lasting facts and a RESUMABLE PROJECT STATE (project_state).

The workspace folder is {workspace} on {platform}.

Work in this order:
1. UNDERSTAND the relevant files (list_tree, search_files, read_file) before changing anything.
2. PLAN briefly, only if useful.
3. IMPLEMENT the smallest change that works; prefer edit_file to rewriting a file.
4. VERIFY by running the project's own checks when you can, and read the output. If you cannot verify, say so plainly.
5. Stop and summarise what changed and what was verified.

Rules:
- Never claim something works without running it and seeing the output.
- Do not repeat a tool call that already succeeded. Do not create empty folders.
- If you are blocked, reply 'BLOCKED: <what you need>'.

What you remember about the user from previous sessions:
{memory}'''


def is_godot_workspace() -> bool:
    """True when Loki is pointed at a Godot project (the optional game adapter)."""
    return bool(GAME_PROJECT) and (Path(GAME_PROJECT) / "project.godot").is_file()


def identity_section() -> str:
    """Who is answering, on which machine, with which model - so LOKI can say it plainly
    instead of guessing (it used to answer "I don't know which model I am")."""
    try:
        provider = active_model_name()
        model = MODELS[provider].model if provider in MODELS else provider
    except Exception:  # noqa: BLE001
        provider, model = model_name, ""
    try:
        import updater  # pylint: disable=import-outside-toplevel
        commit = updater.version().get("commit", "")[:7]
    except Exception:  # noqa: BLE001
        commit = ""
    try:
        import peers  # pylint: disable=import-outside-toplevel
        machine, linked = peers.my_name(), [p["name"] for p in peers.peers()]
    except Exception:  # noqa: BLE001
        machine, linked = "", []
    try:
        cost = " (paid)" if is_metered(provider) else " (free)"
    except Exception:  # noqa: BLE001 - also built once at import, before the metering helpers exist
        cost = ""
    lines = ["# Who you are right now",
             "You are LOKI, a standalone desktop app (macOS and Windows) that runs AI agents on the "
             "owner's own machines. You are not a Godot project.",
             "- Your job (Home): the owner's work OUTSIDE this app - their projects (~/LOKI Projects), their "
             "games, files, repos, art, marketing, the web. You can do anything they ask, including changing LOKI "
             "itself, but that is LOKI Studio's main job (it works on LOKI's own code in its own worktree) - so for "
             "LOKI's own code, say it suits LOKI Studio better, then do it if they still want it here.",
             "- Answering this message: model %s through provider %s%s." % (
                 model or "?", provider, cost),
             "- This machine: %s (%s)%s." % (machine or "this computer", sys.platform,
                                             (", LOKI version " + commit) if commit else ""),
             "- Linked machines: %s. When the owner means another computer (the Mac, the PC, 'the other one'), "
             "use the machines tool: list, run a task there, check its result." % (", ".join(linked) if linked else "none yet")]
    return chr(10).join(lines)


def system_prompt() -> str:
    """The system prompt for the current mode, always English-only, plus the ready specialists."""
    try:
        specialists = CONDUCTOR.prompt_section()
    except Exception:
        specialists = ""
    base = _base_system_prompt()
    text = base + chr(10) * 2 + identity_section() + (chr(10) * 2 + specialists if specialists else "")
    if TRIAGE_NOTE:
        text += chr(10) * 2 + "# This request" + chr(10) + TRIAGE_NOTE
    return text


# The first layer's verdict on the request being handled (first_layer.triage), and the
# note it adds to the system prompt for the length of that request only.
LAST_TRIAGE: dict = {}
TRIAGE_NOTE = ""


def _triage(text: str) -> dict:
    """Run the first layer for one request: show it, steer the agent, keep it for the log."""
    global LAST_TRIAGE, TRIAGE_NOTE
    _speed_t0 = time.monotonic()   # speed watch (E6): the triage phase
    try:
        # never block the request on Laya loading (it is ~8 s cold and unloads after idle):
        # the rules answer at once and Laya keeps warming for the next request
        verdict = first_layer.triage(text, AGENT_MODE, wait=False)
    except Exception as exc:  # noqa: BLE001 - the first layer must never break a request
        verdict = dict(first_layer.rules(text), source="rules", note="triage failed: %s" % exc)
    LAST_TRIAGE = verdict
    TRIAGE_NOTE = first_layer.guidance(verdict)
    try:   # the ONE memory path (memory.pack): lessons + memories + project passages, token-budgeted
        mem = memory.pack(text, root=DATA_DIR, repo=REPO_ROOT, workspace=WORKSPACE,
                          lessons=EXPERIENCE_ENABLED, notes_file=MEMORY_FILE)
    except Exception:  # noqa: BLE001
        mem = {"text": "", "used": [], "skills": []}
    if mem.get("lessons"):
        _progress("thinking", "Recalled %d lesson(s) from similar past tasks." % mem["lessons"])
    if mem.get("text"):
        TRIAGE_NOTE = (TRIAGE_NOTE + chr(10) * 2 + mem["text"]).strip()
        _cite(mem.get("used"))
        LAST_SKILLS[:] = list(mem.get("skills") or [])
        _progress("thinking", "Recalled %d memor%s%s." % (
            len(mem["used"]), "y" if len(mem["used"]) == 1 else "ies",
            (" and learned skill " + ", ".join(LAST_SKILLS)) if LAST_SKILLS else ""))
    events.emit("decision.made", "Laya" if verdict.get("source") == "laya" else "LOKI rules",
                dict(verdict, request=text[:300]))
    events.emit("agent.status", "LOKI", {"state": "working", "kind": verdict.get("kind", "")})
    refresh_system_prompt()
    _progress("triage", first_layer.describe(verdict))
    speed_watch.since(_speed_t0, "triage", str(verdict.get("source", "")))
    return verdict


def _end_triage() -> None:
    global TRIAGE_NOTE
    events.emit("agent.status", "LOKI", {"state": "idle"})
    if TRIAGE_NOTE:
        TRIAGE_NOTE = ""
        refresh_system_prompt()


def _base_system_prompt() -> str:
    english = _language_rule() + chr(10) * 2   # the user's language (session 29); _ENGLISH_RULE when en
    if AGENT_MODE in MODE_PROMPTS:
        return english + MODE_PROMPTS[AGENT_MODE] + chr(10) * 2 + "# Project context" + chr(10) + composed_memory()
    if not is_godot_workspace():
        platform_name = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, sys.platform)
        return english + SYSTEM_PROMPT_GENERAL.format(memory=composed_memory(), workspace=WORKSPACE,
                                                      platform=platform_name)
    return english + SYSTEM_PROMPT.format(memory=composed_memory())


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
        messages[0] = {"role": "system", "content": system_prompt()}


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
    messages[:] = [{"role": "system", "content": system_prompt()}]
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


messages = [{"role": "system", "content": system_prompt()}]
load_conversations()


# ---------------------------------------------------------------------------
# Pillar: MCP. Launch servers from mcp_servers.json and merge in their tools.
# ---------------------------------------------------------------------------

mcp_sessions = {}


_ENV_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value) -> str:
    """Replace ${VAR} in an mcp_servers.json arg/env with the environment value.

    This is what lets a server be pointed at the active workspace, e.g.
    "args": ["mcp-server-git", "--repository", "${LOKI_WORKSPACE}"].
    """
    return _ENV_TOKEN.sub(lambda m: os.environ.get(m.group(1), ""), str(value))

def _godot_capability_dir() -> str:
    """Where the Godot MCP server publishes its per-launch capability record."""
    explicit = str(os.getenv("GODOT_AI_CAPABILITY_DIR") or "").strip()
    if explicit:
        return explicit
    local = str(os.getenv("LOCALAPPDATA") or "").strip()  # Windows
    if local:
        return os.path.join(local, "godot-ai", "capabilities")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "godot-ai", "capabilities")


# The Godot addon and its python server both honour this; defaulting it here means
# mcp_servers.json can say ${GODOT_AI_CAPABILITY_DIR}/http-8000.json with no setup.
os.environ.setdefault("GODOT_AI_CAPABILITY_DIR", _godot_capability_dir())

# CADCraft (capabilities/cadcraft): where its cadcraft-cli is, so mcp_servers.json can run
# ${LOKI_CADCRAFT_CLI} mcp. Set only when it is installed (the server is skipped otherwise).
try:
    import cad as _cad  # pylint: disable=import-outside-toplevel
    if not os.getenv("LOKI_CADCRAFT_CLI") and _cad.cli_path():
        os.environ["LOKI_CADCRAFT_CLI"] = _cad.cli_path()
except Exception:  # noqa: BLE001
    pass


def _json_field(path: str, key: str) -> str:
    """The string field `key` of a JSON file, or "" if it is missing/unreadable."""
    if not path or not key:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    value = data.get(key, "") if isinstance(data, dict) else ""
    return str(value).strip()


def _endpoint_reachable(url: str, timeout: float = 0.7) -> bool:
    """Whether a URL MCP server's host:port accepts a connection right now.

    A stale capability record outlives the editor that published it, so a URL
    server can look configured while nothing is listening. Probing first turns a
    multi-minute hang into a one-line skip.
    """
    import socket
    import urllib.parse as _urlparse

    parsed = _urlparse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _csv_env(name: str) -> set:
    return {item.strip() for item in str(os.getenv(name) or "").split(",") if item.strip()}


def _server_skip_reason(spec: dict, name: str = "") -> str:
    """Why an MCP server entry must be skipped, or "" to start it.

    Kept as a pure function so the gating stays testable without spawning processes:
      "enabled": false        -> never start (an opt-in server)
      "requires_env": NAME    -> start only when that env var is set (e.g. an API key)
      "requires_cmd": CMD     -> start only when CMD is on PATH (e.g. npx / uvx)
    LOKI_MCP_ENABLE=godot_omni,git turns opt-in servers on locally WITHOUT editing the
    shipped mcp_servers.json, and LOKI_MCP_DISABLE forces servers off. Every gate keeps
    a server's tool schemas off every request until it can actually work.
    """
    if name and name in _csv_env("LOKI_MCP_DISABLE"):
        return "disabled by LOKI_MCP_DISABLE"
    forced_on = bool(name) and name in _csv_env("LOKI_MCP_ENABLE")
    # "capability": NAME - an opt-in server that the owner turns on as an add-on (Settings >
    # Add-ons, engine/manifests.py) starts while that add-on is enabled.
    if not forced_on and spec.get("capability"):
        try:
            forced_on = CAPABILITIES.is_enabled(str(spec["capability"]))
        except Exception:  # noqa: BLE001 - a broken registry never starts a server
            forced_on = False
    if spec.get("enabled", True) is False and not forced_on:
        return "disabled in mcp_servers.json (enable with LOKI_MCP_ENABLE=%s)" % name
    required = spec.get("requires_env")
    if required and not str(os.environ.get(required) or "").strip():
        return "needs %s to be set" % required
    command_needed = spec.get("requires_cmd")
    if command_needed and not spec.get("url") and not shutil.which(command_needed):
        return "needs '%s' on PATH" % command_needed
    bearer = spec.get("auth_bearer_json")
    if isinstance(bearer, dict):
        token_path = _expand_env(bearer.get("path", ""))
        if not _json_field(token_path, str(bearer.get("key", ""))):
            return "no capability token at %s (start the Godot editor)" % token_path
    return ""


async def connect_mcp(stack: AsyncExitStack) -> None:
    """Start every MCP server and offer its tools to the model.

    A server entry may set:
      "enabled": false      - skip it entirely
      "url": "http://..."   - connect to a running server over HTTP (no spawn)
      "transport": "sse"    - use the SSE handshake instead of streamable-http
      "tools": ["a", "b"]   - offer only these (an allow-list)
      "max_tools": 20       - cap how many are offered

    Gating matters: a Godot MCP server can expose 150+ tools, and every tool
    schema is paid for on every request - free tiers choke on a few extra k.
    """
    from mcp import ClientSession, StdioServerParameters  # pylint: disable=import-outside-toplevel
    from mcp.client.stdio import stdio_client  # pylint: disable=import-outside-toplevel
    from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client  # pylint: disable=import-outside-toplevel
    from mcp.client.sse import sse_client  # pylint: disable=import-outside-toplevel
    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    for name, spec in config["mcpServers"].items():
        reason = _server_skip_reason(spec, name)
        if reason:
            print(f"  [mcp] '{name}' skipped: {reason}")
            continue
        if spec.get("url") and not _endpoint_reachable(_expand_env(spec["url"])):
            print(f"  [mcp] '{name}' skipped: nothing is listening at "
                  f"{_expand_env(spec['url'])}")
            continue
        try:
            if spec.get("url"):
                # A server that is already running, addressed by URL rather than
                # spawned. The Godot editor plugin starts and owns its own python
                # server (http://127.0.0.1:8000/mcp); spawning a second copy here
                # makes the two fight over ports 8000/9500 and kills the editor,
                # so connect to the one that exists. streamable_http is the
                # default; "transport": "sse" selects the older SSE handshake.
                url = _expand_env(spec["url"])
                if str(spec.get("transport", "")).lower() == "sse":
                    entered = await stack.enter_async_context(sse_client(url))
                else:
                    kwargs = {}
                    bearer = spec.get("auth_bearer_json")
                    if isinstance(bearer, dict):
                        # A per-launch capability token: read it fresh at connect
                        # time, since the editor mints a new one every startup.
                        token = _json_field(_expand_env(bearer.get("path", "")),
                                            str(bearer.get("key", "")))
                        client = create_mcp_http_client(
                            headers={"Authorization": "Bearer " + token})
                        kwargs["http_client"] = await stack.enter_async_context(client)
                    entered = await stack.enter_async_context(
                        streamable_http_client(url, **kwargs))
                read, write = entered[0], entered[1]
            else:
                params = StdioServerParameters(command=_expand_env(spec["command"]),
                                               args=[_expand_env(a) for a in spec["args"]])
                if spec.get("cwd"):
                    # Some servers drop files into their working directory. Point
                    # that at Loki's data dir so they never litter the game project.
                    params.cwd = _expand_env(spec["cwd"])
                if spec.get("env"):
                    params.env = {**os.environ,
                                  **{k: _expand_env(v) for k, v in spec["env"].items()}}
                read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(session.initialize(),
                                   timeout=float(os.getenv("LOKI_MCP_TIMEOUT", "30")))
        except Exception as e:
            print(f"  [mcp] '{name}' failed to start: {e}")
            continue
        MCP_SESSIONS_BY_SERVER[name] = session
        try:
            tools = (await session.list_tools()).tools
        except Exception as e:
            print(f"  [mcp] '{name}' connected but listing tools failed: {e}")
            continue
        # Opt-in always-on capability domains (mcp_servers.json "toolsets"): the
        # vendored Godot server ships ~25 domains but starts with only core and
        # inspection, so enabling one here is what makes its tools offerable. A
        # domain that needs the Godot bridge answers BRIDGE_DISCONNECTED and adds
        # nothing, so this is best-effort and never fatal.
        want_toolsets = spec.get("toolsets") or []
        for domain in want_toolsets:
            try:
                await session.call_tool("godot_enable_toolset", {"category": domain})
                print(f"  [mcp] '{name}' enabled domain '{domain}'")
            except Exception as e:
                print(f"  [mcp] '{name}' could not enable domain '{domain}': {e}")
        if want_toolsets:
            try:
                tools = (await session.list_tools()).tools
            except Exception:
                pass
        # Domains enabled on purpose mean offer the whole domain surface (bounded by
        # max_tools) rather than the small startup allow-list.
        allow = None if want_toolsets else spec.get("tools")
        limit = spec.get("max_tools")
        added = []
        for tool in tools:
            if allow is not None and tool.name not in allow:
                continue
            if limit is not None and len(added) >= int(limit):
                break
            mcp_sessions[tool.name] = session
            TOOL_SCHEMAS.append(schema(tool.name, (tool.description or "")[:500],
                                       tool.input_schema.get("properties", {}),
                                       tool.input_schema.get("required", [])))
            MODEL_TOOL_NAMES.add(tool.name)
            added.append(tool.name)
        MODEL_TOOL_SCHEMAS[:] = [t for t in TOOL_SCHEMAS
                                 if t["function"]["name"] in MODEL_TOOL_NAMES]
        hidden = len(tools) - len(added)
        print(f"  [mcp] connected '{name}': {len(added)} tools offered to the model"
              + (f", {hidden} hidden" if hidden else ""))


async def approve(kind: str, detail: str, decidable: bool = True) -> bool:
    if AUTO_APPROVE:
        print(f"  [auto-approved] {kind}: {detail}")
        return True
    # Risk gate: auto-allow only when a decision provider is confident the action is safe
    # AND the policy engine marked the action decidable (policy.final enforces this).
    # Anything risky, uncertain, contested or always-ask still asks the human.
    if decidable:
        recommended = decisions.risk_gate(kind, detail)
        if policy.final(policy.Verdict(policy.ASK, kind, True), recommended).allowed:
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


# How often the tool guard (tool_guard.py) repaired or rejected a call this session;
# shown by the System check and the eval so "is local reliable now?" has a number.
GUARD_STATS = {"repaired": 0, "rejected": 0}


def _tool_params() -> dict:
    """name -> parameters schema for every tool the model can call (LOKI's and MCP's)."""
    out = {}
    for entry in TOOL_SCHEMAS:
        fn = entry.get("function") or {}
        if fn.get("name"):
            out[fn["name"]] = fn.get("parameters") or {}
    for name in mcp_sessions:
        out.setdefault(name, {})
    return out


def _guard_call(name: str, raw_args):
    """Repair and check one tool call before it runs (see tool_guard.check_call)."""
    params = _tool_params()
    real = tool_guard.resolve_name(name, params.keys()) or name
    role = MEDIA_TOOL_ALIASES.get(real, real)
    if real not in params and role in conductor.ROLES and "conductor" in params:
        # A small model called a specialist by its role name ("image", "generate_image",
        # "research"): that is conductor(role=...). The guard used to reject it before call_tool
        # could route it, so the job never made its picture (seen on the PC).
        given = tool_guard.repair_json(raw_args) or {}
        task = str(given.get("task") or given.get("prompt") or given.get("query") or given.get("description") or "")
        name, real = "conductor", "conductor"
        raw_args = {"role": role, "task": task}
        if given.get("url"):
            raw_args["url"] = str(given["url"])
    args = tool_guard.repair_json(raw_args)
    if args is not None:
        # LOKI's own synonyms (filename -> path, text -> content) first, so validation
        # does not drop an argument the model named slightly differently.
        args = _normalize_args(real, args)
        raw_args = args
    if real in params and not params[real].get("properties"):
        # An MCP tool with no schema we can read: only the name and JSON are checked.
        fix = tool_guard.check_call(name, raw_args, {real: {}})
        return fix
    return tool_guard.check_call(name, raw_args, params)


# Tools a server starts exposing at runtime, after the model enables a toolset.
# The allow-list in mcp_servers.json decides what is offered at STARTUP; a toolset the
# model explicitly unlocks may add to that, because otherwise enabling it would have no
# effect at all - the model could never call what it just unlocked.
MCP_SESSIONS_BY_SERVER: dict = {}
MCP_SERVER_OF: dict = {}
# Cap the offered list so one greedy unlock cannot blow the context budget that every
# free tier is measured against.
DYNAMIC_TOOLS_MAX = int(os.getenv("LOKI_DYNAMIC_TOOLS_MAX", "400"))


async def refresh_mcp_tools(server: str = "") -> list:
    """Re-read tool lists and offer anything new. Returns the names added."""
    if server and server in MCP_SESSIONS_BY_SERVER:
        targets = {server: MCP_SESSIONS_BY_SERVER[server]}
    else:
        targets = dict(MCP_SESSIONS_BY_SERVER)
    added: list = []
    for server_name, session in targets.items():
        try:
            tools = (await session.list_tools()).tools
        except Exception:
            continue
        for tool in tools:
            if tool.name in MODEL_TOOL_NAMES:
                continue
            if len(MODEL_TOOL_SCHEMAS) + len(added) >= DYNAMIC_TOOLS_MAX:
                break
            mcp_sessions[tool.name] = session
            MCP_SERVER_OF[tool.name] = server_name
            TOOL_SCHEMAS.append(schema(tool.name, (tool.description or "")[:500],
                                       tool.input_schema.get("properties", {}),
                                       tool.input_schema.get("required", [])))
            MODEL_TOOL_NAMES.add(tool.name)
            added.append(tool.name)
    if added:
        MODEL_TOOL_SCHEMAS[:] = [t for t in TOOL_SCHEMAS
                                 if t["function"]["name"] in MODEL_TOOL_NAMES]
    return added


def _toolset_summary(text: str) -> str:
    """Compact a godot toolset enable/disable JSON payload to one or two lines."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return ""
    if not isinstance(data, dict) or "name" not in data:
        return ""
    domain = data.get("name")
    if data.get("enabled"):
        names = sorted(t["name"] for t in (data.get("tools") or [])
                       if isinstance(t, dict) and t.get("name"))
        head = "Enabled domain '%s': %d tool(s) now available." % (domain, len(names))
        if names:
            head += " " + ", ".join(names[:40]) + "."
        return head
    return "Disabled domain '%s'." % domain


async def call_tool(name: str, args: dict) -> str:
    global _task_modified, _task_wrote_file
    args = _normalize_args(name, args)
    # The git MCP server requires repo_path on every call. Loki already knows the
    # project, so fill it in - the model never has to guess the workspace path.
    if name.startswith("git_") and "repo_path" not in args:
        args = {**args, "repo_path": str(WORKSPACE)}
    if name in LOCAL_TOOLS:
        # The policy engine decides first (fixed rules, no model). DENY never reaches the
        # user; ASK goes through approve(), where a decision provider may only skip the
        # prompt for actions the policy marks decidable.
        verdict = POLICY.tool_call(name, args)
        if verdict.decision == policy.DENY:
            print("  [policy] %s: %s" % (name, verdict.reason))
            return ("DENIED by Loki's policy: %s. Do NOT retry the same call; change the approach "
                    "or reply 'BLOCKED: <reason>'." % verdict.reason)
        decidable = verdict.decidable
        if name in ("run_command", "bash"):
            # OpenHands' security analyzer (command_risk.py): a HIGH-risk command is refused in an
            # unattended job and always asks a human in the window - no provider may wave it through.
            risk = command_risk.assess(str(args.get("command", "")))
            if risk["risk"] == command_risk.HIGH:
                if os.getenv("LOKI_JOB_ID"):
                    return ("DENIED: HIGH-risk command (%s) - a background job may not run it. Do it another "
                            "way, or reply 'BLOCKED: <reason>'." % "; ".join(risk["reasons"]))
                decidable = False
        if verdict.decision == policy.ASK and not await approve(
                name, json.dumps(args)[:400], decidable=decidable):
            return ("DENIED: the user did not approve this tool. Do NOT request it again. "
                    "Make progress with file tools (build_3d_scene, write_file, edit_file, "
                    "play_scene, validate_scene) instead, or reply 'BLOCKED: <reason>'.")
        try:
            _speed_t0 = time.monotonic()   # speed watch (E6): one tool call
            result = LOCAL_TOOLS[name](**args)
            if asyncio.iscoroutine(result):
                result = await result
            speed_watch.since(_speed_t0, "tools", name)
            if name in MODIFYING and not str(result).lstrip().lower().startswith(("error", "denied")):
                # a failed call changed nothing, and an empty folder is not a written file
                _task_modified = True
                if name != "make_dir":
                    _task_wrote_file = True
                _record_touched(name, args, result)
            made = _specialist_made(name, result)
            if made:
                # A specialist (the image maker...) wrote a real file: that is the work done, so
                # DONE is accepted and the file is verified (a picture must be a real picture).
                _task_modified = _task_wrote_file = True
                if made in _task_files:
                    _task_files.remove(made)
                _task_files.append(made)
            return _elide(result) if isinstance(result, str) else result
        except Exception as e:
            return f"error: {e}"
    if name in mcp_sessions:
        try:
            result = await mcp_sessions[name].call_tool(name, args)
            text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
        except Exception as e:
            return f"error: {e}"
        if _record_mcp_touched(name, args, text):
            _task_modified = True
            _task_wrote_file = True
        if "toolset" in name:
            # Enabling a toolset changes the server's tool list; without this the
            # model would have to guess at tools it can never see.
            try:
                newly = await refresh_mcp_tools(MCP_SERVER_OF.get(name, ""))
            except Exception:
                newly = []
            # The server answers a domain enable with its full JSON (every tool and
            # its schema). Those schemas are already offered, so echo a summary, not
            # the blob - the blob is pure context cost on every remaining request.
            _summary = _toolset_summary(text)
            if _summary:
                text = _summary
            if newly:
                text += ("\n\n%d new tool(s) are now available and can be called directly: %s"
                         % (len(newly), ", ".join(sorted(newly)[:40])))
        return _elide(text)
    real = tool_guard.resolve_name(name, set(LOCAL_TOOLS) | set(mcp_sessions))
    if real and real != name:
        return await call_tool(real, args)
    role = MEDIA_TOOL_ALIASES.get(name, name)
    if role in conductor.ROLES and "conductor" in LOCAL_TOOLS:
        # A small model called a specialist by its role name (image, research, ...): that is
        # what conductor(role=...) is for, so do it rather than failing the step.
        args = dict(args or {})
        if "task" not in args:
            args["task"] = str(args.pop("prompt", "") or args.pop("query", "") or args.pop("description", "") or "")
        args["role"] = role
        return await call_tool("conductor", args)
    return f"error: unknown tool {name}"


# --- Session 28: tools, connectors, computer use (worktree) -----------------------------------------
# The tool health map (tool_health.py), connectors to the owner's apps (connectors.py + conn_*.py), the
# `computer` tool (computer_use.py + computer_backends.py), a real Chromium behind browse_page
# (browser_real.py) and tool errors that teach small models (tool_teach.py). Registration only: the three
# wrappers at the end sit AROUND _tool_enabled, _guard_call and call_tool; none of them is changed.
# Writes ask the owner through engine/policy.py (ACTION_ALWAYS_ASK, CAPABILITY_TOOLS["computer"]).
import browser_real  # noqa: E402
import computer_use  # noqa: E402
import connectors as _connectors  # noqa: E402
import tool_health  # noqa: E402
import tool_teach  # noqa: E402

_connectors._load_all()   # noqa: SLF001 - registers conn_google/email/calendar/github/notes/peer_files
import conn_calendar  # noqa: E402
import conn_email  # noqa: E402
import conn_github  # noqa: E402
import conn_notes  # noqa: E402
import conn_peer_files  # noqa: E402

TOOL_HEALTH = tool_health.default(DATA_DIR, redact=lambda s: _connectors.redact(redact_secrets(str(s))))


async def _vision_ask(png: bytes, prompt: str) -> str:
    """One image question for the computer tool: LOKI_VISION_MODEL (a provider name, or an Ollama tag like
    qwen2.5vl:7b), else the active model."""
    import base64  # pylint: disable=import-outside-toplevel
    want = str(os.getenv("LOKI_VISION_MODEL", "") or "").strip()
    if want and want in MODELS:
        cfg = MODELS[want]
        base, key, model = cfg.base_url, cfg.api_key, cfg.model
    elif want:
        base, key, model = "http://localhost:11434/v1", "ollama", want
    else:
        cfg = MODELS[active_model_name()]
        base, key, model = cfg.base_url, cfg.api_key, cfg.model
    if str(base).startswith(CLI_AGENT_PREFIX):
        raise RuntimeError("the active model is a CLI agent; set LOKI_VISION_MODEL to a vision model")
    client = AsyncOpenAI(base_url=base, api_key=key or "none", timeout=MODEL_TIMEOUT_S)
    response = await client.chat.completions.create(model=model, max_tokens=900, messages=[{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}])
    return str(response.choices[0].message.content or "")


COMPUTER = computer_use.default(DATA_DIR, approve=lambda kind, detail, decidable=True: approve(kind, detail, decidable),
                                vision=_vision_ask, workspace=WORKSPACE)
CHROMIUM = browser_real.default(allow=_public_ok, workspace=WORKSPACE)


def _threaded(fn):
    async def run(**kwargs):
        return _connectors.redact(await asyncio.to_thread(fn, **kwargs))
    return run


async def computer_tool(**kwargs) -> str:
    return await COMPUTER.act(**kwargs)


_browse_text = LOCAL_TOOLS["browse_page"]


async def browse_page_any(action: str = "view", url: str = "", index: int = 0, text: str = "", direction: str = "down",
                          engine: str = "") -> str:
    """browse_page: the text browser, or Chromium (the `chromium` add-on) when a page needs JavaScript or
    engine='chromium'. Steps that would send something ask the owner (browser_real.risky)."""
    name = os.getenv("LOKI_JOB_ID", "") or "chat"
    use = browser_real.choose(name, str(action or "view").strip().lower(), engine)
    chromium_on = CAPABILITIES.is_enabled("chromium")
    if use == "chromium" and not chromium_on:
        if str(engine or "").lower() == "chromium":
            return "error: the Chromium browser is off - the owner turns it on in Settings > Add-ons (chromium)"
        use = "text"
    if use == "text":
        result = await asyncio.to_thread(_browse_text, action, url, index, text, direction)
        if str(action).lower() in ("open", "goto", "navigate", "visit") and browser_real.needs_js(result) and chromium_on \
                and (await asyncio.to_thread(CHROMIUM.available))[0]:
            browser_real.switch(name, "chromium")
            more = await asyncio.to_thread(CHROMIUM.act, "open", url, None, "", "down", name)
            return "(This page needs JavaScript - switched to the Chromium browser.)\n" + more
        return result
    risk = CHROMIUM.risky(name, str(action or "").lower(), index)
    if risk:
        if os.getenv("LOKI_JOB_ID"):
            return "DENIED: the browser would %s - a background job may not. Ask the owner, or reply 'BLOCKED: <reason>'." % risk
        if not await approve("browse_page", "The browser wants to " + risk, False):
            return "DENIED: the owner did not approve that. Do NOT retry it; reply 'BLOCKED: <reason>' or do it another way."
    return await asyncio.to_thread(CHROMIUM.act, action, url, index, text, direction, name)


LOCAL_TOOLS.update({"email": _threaded(conn_email.tool), "calendar": _threaded(conn_calendar.tool),
                    "github": _threaded(conn_github.tool), "notes": _threaded(conn_notes.tool),
                    "peer_files": _threaded(conn_peer_files.tool), "computer": computer_tool,
                    "machines": _threaded(__import__("machines").tool),
                    "browse_page": browse_page_any})
_S28_SCHEMAS = [
    schema("email", tool_teach.DESCRIPTIONS["email"],
           {"action": {"type": "string", "enum": list(conn_email.ACTIONS)}, "query": {"type": "string"},
            "id": {"type": "string"}, "folder": {"type": "string"}, "to": {"type": "string"},
            "subject": {"type": "string"}, "body": {"type": "string"}, "draft": {"type": "string"},
            "limit": {"type": "integer"}}, ["action"]),
    schema("calendar", tool_teach.DESCRIPTIONS["calendar"],
           {"action": {"type": "string", "enum": list(conn_calendar.ACTIONS)}, "days": {"type": "integer"},
            "start": {"type": "string"}, "end": {"type": "string"}, "title": {"type": "string"},
            "duration_min": {"type": "integer"}, "location": {"type": "string"}, "notes": {"type": "string"}}, ["action"]),
    schema("github", tool_teach.DESCRIPTIONS["github"],
           {"action": {"type": "string", "enum": list(conn_github.ACTIONS)}, "repo": {"type": "string"},
            "number": {"type": "integer"}, "query": {"type": "string"}, "title": {"type": "string"},
            "body": {"type": "string"}, "head": {"type": "string"}, "base": {"type": "string"},
            "state": {"type": "string", "enum": ["open", "closed", "all"]}, "limit": {"type": "integer"}}, ["action"]),
    schema("notes", tool_teach.DESCRIPTIONS["notes"],
           {"action": {"type": "string", "enum": list(conn_notes.ACTIONS)}, "query": {"type": "string"},
            "path": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"},
            "page": {"type": "string"}}, ["action"]),
    schema("peer_files", tool_teach.DESCRIPTIONS["peer_files"],
           {"action": {"type": "string", "enum": ["machines", "list", "read", "write"]}, "machine": {"type": "string"},
            "path": {"type": "string"}, "text": {"type": "string"}}, ["action"]),
    schema("machines", "The owner's OTHER LOKI machines (Mac <-> Windows PC): action list (which are linked, online, "
           "busy) | run (machine, task - their own LOKI agent does it there as a job; write the task fully) | status "
           "(machine, job, wait - the result when done) | stop (machine, job). Use it when the owner asks you to help, "
           "check or use the other machine.",
           {"action": {"type": "string", "enum": ["list", "run", "status", "stop"]}, "machine": {"type": "string"},
            "task": {"type": "string"}, "job": {"type": "string"}, "wait": {"type": "number"}}, ["action"]),
    schema("computer", tool_teach.DESCRIPTIONS["computer"],
           {"action": {"type": "string", "enum": ["elements", "find", "click", "double_click", "right_click", "type", "key",
                                                  "scroll", "open_app", "apps", "screenshot", "look", "wait"]},
            "index": {"type": "integer"}, "text": {"type": "string"}, "role": {"type": "string"},
            "x": {"type": "integer"}, "y": {"type": "integer"}, "keys": {"type": "string"},
            "direction": {"type": "string", "enum": ["up", "down"]}, "amount": {"type": "integer"},
            "app": {"type": "string"}, "seconds": {"type": "number"}, "question": {"type": "string"}}, ["action"]),
]
TOOL_SCHEMAS.extend(_S28_SCHEMAS)
MODEL_TOOL_SCHEMAS.extend(_S28_SCHEMAS)
MODEL_TOOL_NAMES.update(s["function"]["name"] for s in _S28_SCHEMAS)
for _entry in TOOL_SCHEMAS:     # browse_page gains engine= (auto | text | chromium), key and screenshot
    if _entry["function"]["name"] == "browse_page":
        _entry["function"]["description"] += (" With the chromium add-on on, a page that needs JavaScript opens in a real "
                                              "Chromium automatically (engine='chromium' forces it; there also 'key' "
                                              "text='Escape' and 'screenshot'); sending a form or a password asks the owner.")
        _entry["function"]["parameters"]["properties"]["engine"] = {"type": "string", "enum": ["auto", "text", "chromium"]}
TOOL_CATEGORIES["connectors"] = ["email", "calendar", "github", "notes", "peer_files", "machines"]
TOOL_CATEGORIES["computer"] = ["computer"]
CATEGORY_LABELS["connectors"] = "Connectors (your email, calendar, GitHub, notes, files on your other machine - writes ask)"
CATEGORY_LABELS["computer"] = "Computer use (drive this desktop; needs the computer-use add-on; asks per app)"
CATEGORIES.setdefault("connectors", True)
CATEGORIES.setdefault("computer", True)
NETWORK_WRITES |= {"computer"}            # never in Plan mode (it clicks and types)
LOCAL_TOOL_PRIORITY[LOCAL_TOOL_PRIORITY.index("code_map") + 1:LOCAL_TOOL_PRIORITY.index("code_map") + 1] = [
    "email", "calendar", "github", "notes", "computer", "peer_files"]   # hidden until set up, so no slot is wasted

for _cid, _spec in _connectors.SPECS.items():   # an unset connector is not offered to the model
    if _spec.get("tool"):
        tool_health.require(_spec["tool"], (lambda c: lambda: "" if _connectors.configured(c)
                                            else "not set up: " + _connectors.modules()[c].status().get("detail", ""))(_cid))
tool_health.require("computer", lambda: "" if COMPUTER.backend.available()[0] and COMPUTER.armed
                    else ("kill switch on" if not COMPUTER.armed else COMPUTER.backend.available()[1]))
tool_health.require("generate_media", lambda: "" if __import__("higgsfield").configured() else
                    "needs a Higgsfield key (Settings > General)")
# make_music is not pre-checked: its own error says how to start ACE-Step, and after 3 such failures
# ("is not running") the health map hides it for the cool-down anyway.

_tool_enabled_by_category = _tool_enabled


def _tool_enabled(tool_name: str) -> bool:   # noqa: F811 - wraps the category switch with the health map
    return _tool_enabled_by_category(tool_name) and tool_health.offerable(tool_name)


_guard_call_plain = _guard_call


def _guard_call(name: str, raw_args):   # noqa: F811 - teaching errors around the tool guard
    params = _tool_params()
    real = tool_guard.resolve_name(name, params.keys()) or name
    raw_args = tool_teach.repair(real, raw_args)
    fix = _guard_call_plain(name, raw_args)
    if not fix.ok:
        fix.error = tool_teach.teach(fix.name or real, fix.error, params.get(fix.name or real), raw_args)
    return fix


_call_tool_unrecorded = call_tool


async def call_tool(name: str, args: dict) -> str:   # noqa: F811 - records every result in the health map
    args = args if isinstance(args, dict) else {}
    if name == "email" and str(args.get("action", "")).lower() == "send" and args.get("draft") and not args.get("to"):
        try:   # the owner's approval prompt shows what a draft would send
            draft_msg = conn_email.load_draft(args["draft"])
            args = {**args, "to": draft_msg["To"], "subject": draft_msg["Subject"],
                    "body": str(draft_msg.get_body(("plain",)).get_content())[:2000]}
        except Exception:  # noqa: BLE001 - send reports the bad draft itself
            pass
    result = await _call_tool_unrecorded(name, args)
    if name in LOCAL_TOOLS or name in mcp_sessions:
        try:
            TOOL_HEALTH.record(name, result)
        except Exception:  # noqa: BLE001 - bookkeeping never breaks a tool call
            pass
    return result


# --- Research round 3 (docs/integrations/research-2026-10-17b.md): what the best personal-AI apps have ------
# Home Assistant (conn_home.py, writes always ask via policy.ACTION_ALWAYS_ASK["home"]), everyday answers
# with no key (everyday.py: Open-Meteo weather, RSS news, world clock, translate), picture edits on this
# computer (image_tools.py: Pillow + the rembg add-on + Real-ESRGAN when installed), and one plain model call
# per provider for "compare models" (compare.py, routes in assist_api.py). Registration only.
import conn_home  # noqa: E402
import everyday  # noqa: E402
import image_tools  # noqa: E402


async def _r3_model_ask(name: str, prompt: str) -> str:
    """One answer from the provider `name` (no tools, no history) - for side-by-side comparisons."""
    cfg = MODELS[name]
    if cfg.base_url.startswith(CLI_AGENT_PREFIX):
        client = cli_agents.make_client(cfg.base_url[len(CLI_AGENT_PREFIX):], str(WORKSPACE))
    else:
        if not str(cfg.api_key or "").strip() and "11434" not in cfg.base_url:
            raise ModelUnavailable("%s needs an API key (Settings > Connections)" % name)
        client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or "none", timeout=MODEL_TIMEOUT_S, max_retries=0)
    kwargs = {"model": cfg.model, "messages": [{"role": "user", "content": str(prompt)}],
              "max_tokens": int(os.getenv("LOKI_COMPARE_TOKENS", "1500"))}
    if "11434" in cfg.base_url:
        kwargs["extra_body"] = {"think": False}
    started = time.monotonic()
    response = await _model_request(client, kwargs, cfg, name)
    _record_usage(response, kwargs, cfg, started)
    return structured.strip_thinking(response.choices[0].message.content or "")


async def weather_tool(place: str = "", days: int = 3, units: str = "") -> str:
    return await asyncio.to_thread(everyday.weather, place, days, units)


async def news_tool(topic: str = "", limit: int = 8) -> str:
    return await asyncio.to_thread(everyday.news, topic, limit)


async def world_clock_tool(place: str = "") -> str:
    return await asyncio.to_thread(everyday.clock, place)


async def translate_tool(text: str, to: str, source_lang: str = "") -> str:
    return await everyday.translate(text, to, _port_ask, source_lang)


async def edit_image_tool(path: str, action: str = "info", width: int = 0, height: int = 0, box: str = "",
                          degrees: float = 90, direction: str = "horizontal", to: str = "", quality: int = 82,
                          scale: int = 2, palette: str = "", colors: int = 0, dither: str = "none") -> str:
    """Edit a picture in the workspace; the result is a new file next to it."""
    try:
        src = resolve_in_workspace(path)
        out = await asyncio.to_thread(image_tools.edit, src, action, width, height, box, degrees, direction, to,
                                      quality, scale, "", palette, colors, dither)
    except image_tools.ImageError as exc:
        return "error: %s" % exc
    except ValueError as exc:
        return "error: %s" % exc
    rel = Path(out["path"]).resolve().relative_to(WORKSPACE.resolve()).as_posix() if out.get("path") else ""
    return "%s%s" % (out["detail"], (" -> %s" % rel) if rel and action != "info" else "")


LOCAL_TOOLS.update({"home": _threaded(conn_home.tool), "weather": weather_tool, "news": news_tool,
                    "world_clock": world_clock_tool, "translate": translate_tool, "edit_image": edit_image_tool})
_R3_SCHEMAS = [
    schema("home", "Your smart home through Home Assistant. Read: action='status' (what is on, unlocked), 'list' "
           "(domain='light' or a word), 'find' (entity='kitchen'), 'state' (entity='thermostat'), 'history' (entity=, "
           "hours=). Change (asks the owner first): 'turn_on' / 'turn_off' / 'toggle' with entity= a name or id, and "
           "optional brightness=0-100, color='warm white', temperature=21; 'call' domain= service= data='{...}' for any "
           "other service; 'assist' text='...' hands a sentence to Home Assistant's Assist. Example: "
           "home(action='turn_off', entity='living room lights').",
           {"action": {"type": "string", "enum": list(conn_home.ACTIONS)}, "entity": {"type": "string"},
            "domain": {"type": "string"}, "service": {"type": "string"}, "text": {"type": "string"},
            "brightness": {"type": "integer"}, "color": {"type": "string"}, "temperature": {"type": "number"},
            "data": {"type": "string"}, "hours": {"type": "integer"}, "limit": {"type": "integer"}}, ["action"]),
    schema("weather", "The weather now and the next days for a place (free, no key; Open-Meteo). place='Paris' or "
           "'Springfield, Illinois'; blank = LOKI_HOME_CITY. Copy the ```loki-card block it returns into your reply "
           "unchanged so the window draws the forecast card.",
           {"place": {"type": "string"}, "days": {"type": "integer"}, "units": {"type": "string", "enum": ["", "c", "f"]}}),
    schema("news", "Current headlines with links: topic='electric cars' searches the news; blank = top world stories. "
           "Cite the links you use.", {"topic": {"type": "string"}, "limit": {"type": "integer"}}),
    schema("world_clock", "The time and date now in a city (its time zone).", {"place": {"type": "string"}}, ["place"]),
    schema("translate", "Translate text into a language (to='Spanish', 'Japanese', 'de'...); keeps tone and formatting.",
           {"text": {"type": "string"}, "to": {"type": "string"}, "source_lang": {"type": "string"}}, ["text", "to"]),
    schema("edit_image", "Edit a picture in the workspace on this computer; the result is a NEW file next to it. "
           "action: info | resize (width/height) | crop (box='left,top,right,bottom') | rotate (degrees) | flip "
           "(direction) | convert (to=png|jpg|webp) | compress (quality, width) | grayscale | thumbnail (width) | "
           "upscale (scale=2-4) | remove_background (transparent PNG; needs the rembg add-on) | pixelize (real game pixel "
           "art: width= the sprite's size in pixels, default 64; palette= pico-8 | sweetie-16 | endesga-32 | gameboy | "
           "'#hex ...' or colors=; dither= none | floyd | bayer).",
           {"path": {"type": "string"}, "action": {"type": "string", "enum": list(image_tools.ACTIONS)},
            "width": {"type": "integer"}, "height": {"type": "integer"}, "box": {"type": "string"},
            "degrees": {"type": "number"}, "direction": {"type": "string", "enum": ["horizontal", "vertical"]},
            "to": {"type": "string"}, "quality": {"type": "integer"}, "scale": {"type": "integer"},
            "palette": {"type": "string"}, "colors": {"type": "integer"},
            "dither": {"type": "string", "enum": ["none", "floyd", "bayer"]}}, ["path", "action"]),
]
TOOL_SCHEMAS.extend(_R3_SCHEMAS)
MODEL_TOOL_SCHEMAS.extend(_R3_SCHEMAS)
MODEL_TOOL_NAMES.update(s["function"]["name"] for s in _R3_SCHEMAS)
TOOL_CATEGORIES["home"] = ["home"]
CATEGORY_LABELS["home"] = "Smart home (Home Assistant - reading is free, every change asks)"
CATEGORIES.setdefault("home", True)
TOOL_CATEGORIES["everyday"] = ["weather", "news", "world_clock", "translate"]
TOOL_CATEGORIES["creative"] += ["edit_image"]
CATEGORY_LABELS["everyday"] = "Everyday (weather, news, time around the world, translation - free, no key)"
CATEGORIES.setdefault("everyday", True)
MODIFYING |= {"edit_image"}


# --- Forge (engine/forge3d.py): a picture, drawing or sentence -> a 3D model in models/ ------------------
def forge_image_maker(prompt: str) -> str:
    """Text -> picture through the image specialist (its policy check and backends), for Forge."""
    import forge3d  # pylint: disable=import-outside-toplevel
    out = CONDUCTOR.make_image(prompt + ", a single object, centered, plain white background, full view", {})
    if not out.get("ok"):
        raise forge3d.ForgeError("could not make the picture: %s" % out.get("error"))
    return str(out.get("file"))


async def make_3d_tool(path: str = "", prompt: str = "", backend: str = "auto") -> str:
    """Make a 3D model (.glb + .obj in models/) from a workspace picture or a description."""
    import forge3d  # pylint: disable=import-outside-toplevel
    try:
        src = str(resolve_in_workspace(path)) if path else ""
    except ValueError as exc:
        return "error: %s" % exc
    out = await asyncio.to_thread(forge3d.make_3d, src, WORKSPACE / "models", prompt, backend or "auto",
                                  image_maker=forge_image_maker)
    if not out.get("ok"):
        return "error: " + str(out.get("error"))
    meta = out["meta"]
    return ("made models/%s with %s (%d vertices, %d triangles)%s%s. Open it in Forge (the cube in the sidebar) "
            "to look at it, sculpt it and export it." % (out["name"], out["backend"], meta.get("vertices", 0),
                                                         meta.get("triangles", 0),
                                                         "; also models/%s" % Path(out["obj"]).name if out["obj"] else "",
                                                         "; %s" % meta["note"] if meta.get("note") else ""))


LOCAL_TOOLS["make_3d"] = make_3d_tool
_FORGE_SCHEMA = schema(
    "make_3d", "Make a 3D model (.glb and .obj, saved in models/) from a picture in the workspace (path=) or from "
    "a description (prompt=; LOKI first draws a picture, then lifts it to 3D). backend: auto (best available: "
    "Pixal3D on the owner's ComfyUI - a fully textured model that matches the picture - then TripoSR on this "
    "computer, a free online Space, and an offline inflate that always works) | pixal3d | trellis2 | triposr | "
    "online | lift. Tell the user it opens in Forge for viewing and sculpting.",
    {"path": {"type": "string"}, "prompt": {"type": "string"},
     "backend": {"type": "string", "enum": ["auto", "pixal3d", "trellis2", "triposr", "online", "lift"]}})
TOOL_SCHEMAS.append(_FORGE_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_FORGE_SCHEMA)
MODEL_TOOL_NAMES.add("make_3d")


# --- Voices (engine/voice_studio.py): VoiceStudio's local backend - speak, clone, design, transcribe to .srt ----------
async def voice_tool(action: str = "speak", text: str = "", voice: str = "", instruct: str = "", language: str = "",
                     speed: float = 1.0, out: str = "", name: str = "", audio: str = "", ref_text: str = "",
                     description: str = "", srt: bool = True) -> str:
    import voice_studio  # pylint: disable=import-outside-toplevel
    args = {k: v for k, v in dict(action=action, text=text, voice=voice, instruct=instruct, language=language,
                                  speed=speed, out=out, name=name, audio=audio, ref_text=ref_text,
                                  description=description, srt=srt).items() if v not in ("", None)}
    if action == "install":
        if os.getenv("LOKI_JOB_ID"):
            return "DENIED: installing an app needs the owner - ask them."
        if not await approve("voice_install", "Install VoiceStudio (AGPL-3.0, github.com/debpalash/VoiceStudio) with "
                             "its official installer:\n$ " + " ".join(voice_studio.install_command()), False):
            return "DENIED: the owner did not approve installing VoiceStudio."
        args["_approved"] = True
    res = await asyncio.to_thread(voice_studio.tool, args, WORKSPACE, (lambda *_a: True) if args.get("_approved") else None)
    return json.dumps(res)


LOCAL_TOOLS["voice"] = voice_tool


# --- The Tool Shelf (engine/toolshelf.py): open-source game-dev tools, installed when the owner allows ------------
async def toolshelf_tool(action: str = "list", area: str = "", id: str = "", run: str = "",  # noqa: A002
                         args: dict | None = None) -> str:
    import toolshelf  # pylint: disable=import-outside-toplevel
    req = {"action": action, "area": area, "id": id, "run": run, "args": args or {}}
    if action in ("install", "remove"):
        if os.getenv("LOKI_JOB_ID"):
            return "DENIED: installing or removing a tool needs the owner - ask them."
        try:
            r = toolshelf.recipe(id)
        except toolshelf.ShelfError as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        what = ("Install %s (%s, licence %s) - it downloads and runs its code in LOKI's tools folder."
                % (r.get("name"), r.get("repo"), r.get("license")) if action == "install"
                else "Remove %s and everything it downloaded." % r.get("name"))
        if not await approve("toolshelf_" + action, what, False):
            return "DENIED: the owner did not approve that."
    ask = None
    if action == "run":
        try:
            act = (toolshelf.recipe(id).get("actions") or {}).get(run) or {}
        except toolshelf.ShelfError:
            act = {}
        if act.get("ask"):
            if os.getenv("LOKI_JOB_ID"):
                return "DENIED: %s needs the owner's OK - a background job may not; ask them." % run
            ok = await approve("toolshelf_" + run, "%s: %s\n\n%s" % (id, act.get("what", run),
                               json.dumps(args or {}, indent=1)[:3000]), False)
            if not ok:
                return "DENIED: the owner did not approve that."
            ask = lambda *_a: True  # noqa: E731 - approved just now
    res = await asyncio.to_thread(toolshelf.tool, req, WORKSPACE, ask)
    return json.dumps(res)


LOCAL_TOOLS["toolshelf"] = toolshelf_tool

_SHELF_SCHEMA = schema("toolshelf", __import__("toolshelf").TOOL["description"],
                       __import__("toolshelf").TOOL["inputSchema"]["properties"], ["action"])
TOOL_SCHEMAS.append(_SHELF_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_SHELF_SCHEMA)
MODEL_TOOL_NAMES.add("toolshelf")
_VOICE_SCHEMA = schema("voice", __import__("voice_studio").TOOL["description"],
                       __import__("voice_studio").TOOL["inputSchema"]["properties"], ["action"])
TOOL_SCHEMAS.append(_VOICE_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_VOICE_SCHEMA)
MODEL_TOOL_NAMES.add("voice")
TOOL_CATEGORIES["creative"] += ["make_3d"]
MODIFYING |= {"make_3d"}


# --- anyCreature (contrib/anycreature/, MIT; engine/anycreature.py): an ACS spec -> a creature .glb --------
async def make_creature_tool(preset: str = "", spec: str = "", size: float = 0, smooth: int = 0,
                             body_color: str = "", accent_color: str = "", name: str = "creature",
                             shape=None, coat: str = "") -> str:
    """Make a creature (.glb in models/ + its four views) - from a starter + tweaks, or from an ACS spec."""
    import anycreature  # pylint: disable=import-outside-toplevel
    try:
        if spec:
            res = await asyncio.to_thread(anycreature.make, spec, WORKSPACE / "models", name or "creature")
        else:
            controls = {"preset": preset or "hound", "colors": {"body": body_color, "ear": accent_color}}
            if size:
                controls["size"] = size
            if smooth:
                controls["smooth"] = smooth
            if coat:
                controls["coat"] = coat
            if isinstance(shape, str) and shape.strip():
                try:
                    shape = json.loads(shape)
                except ValueError:
                    shape = None
            if isinstance(shape, dict):
                controls["shape"] = shape
            res = await asyncio.to_thread(anycreature.make_from_controls, controls,
                                          WORKSPACE / "models", name or "creature")
    except anycreature.AnyCreatureError as exc:
        return "error: %s" % exc
    sized = ""
    if res.get("size"):
        sized = " It stands %.2fx%s." % (res["size"], " (the nearest size that passed every check)"
                                         if res.get("size_moved") else "")
    return ("made models/%s (%d bytes) and its front/side/top/hero views in models/%s.views/.%s Open it in Forge "
            "(the cube in the sidebar): the Quad view shows the four views a modeller reads a shape from."
            % (res["name"], res.get("bytes", 0), res["stem"], sized))


LOCAL_TOOLS["make_creature"] = make_creature_tool
_CREATURE_SCHEMA = schema(
    "make_creature", "Make a creature (a skinned, animated .glb in models/) plus its front/side/top/hero views. "
    "The easy way: pick a starter (preset: hound | tall | low | fox | deer | bear), then tweak size, smooth, a coat "
    "(wolf | fox | arctic | panther | deer | bear | dusk | sand | moss | ember), the colours, and shape= its body plan "
    "as multipliers around 1.0 (legs, legthick, body, girth, neck, head, snout, ears, tail; e.g. {\"legs\": 1.3}). The "
    "engine checks every build, applies its own fixes, and lands on the nearest build that stands. Or pass spec= a whole anyCreature ACS "
    "spec (JSON) to author one from scratch (a copied example is BLOCKED and must be made its own). Use this "
    "whenever someone asks for a creature, animal or monster. Tell the user it opens in Forge's four-view panel.",
    {"preset": {"type": "string", "enum": ["hound", "tall", "low", "fox", "deer", "bear"]}, "spec": {"type": "string"},
     "shape": {"type": "object", "description": "body-plan multipliers around 1.0: legs, legthick, body, girth, neck, head, snout, ears, tail"},
     "coat": {"type": "string"},
     "size": {"type": "number"}, "smooth": {"type": "integer"},
     "body_color": {"type": "string"}, "accent_color": {"type": "string"}, "name": {"type": "string"}})
TOOL_SCHEMAS.append(_CREATURE_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_CREATURE_SCHEMA)
MODEL_TOOL_NAMES.add("make_creature")
TOOL_CATEGORIES["creative"] += ["make_creature"]
MODIFYING |= {"make_creature"}
LOCAL_TOOL_PRIORITY[LOCAL_TOOL_PRIORITY.index("peer_files") + 1:LOCAL_TOOL_PRIORITY.index("peer_files") + 1] = [
    "home", "weather", "news"]


# --- Godogen (htdt/godogen, MIT; engine/godogen.py, contrib/godogen) ----------------------------------------
# "Make me a game where ..." -> godogen's instructions are written into ~/LOKI Projects/<name> and a coding
# agent (Claude Code, Codex, OpenCode, Nanocoder, or LOKI's own) builds the game there as a background job.
# Needs the godogen add-on (policy.CAPABILITY_TOOLS) and always asks first (policy.ALWAYS_ASK).
def make_godot_game(description: str, name: str = "", engine: str = "godot-gdscript", agent: str = "auto") -> str:
    import godogen  # pylint: disable=import-outside-toplevel
    if JOBS is None:
        return "error: background jobs are not running in this Loki"
    try:
        made = godogen.make_godot_game(description, name, engine or godogen.DEFAULT_ENGINE, agent or "auto")
    except (godogen.GodogenError, OSError) as exc:
        return "error: %s" % exc
    spec = made["job"]
    verdict = POLICY.job(spec["backend"], spec["agent"])
    if not verdict.allowed:
        return "error: the game folder is ready (%s) but the agent cannot start: %s" % (made["workspace"], verdict.reason)
    try:
        job = JOBS.create(spec)
    except ValueError as exc:
        return "error: %s" % exc
    threading.Thread(target=JOBS.tick, daemon=True).start()
    return ("made %s with godogen's %s instructions (%s) and started background job %s: %s is building the game "
            "there. The user sees it above the message box; open the folder in Godot when it is done."
            % (made["workspace"], made["engine"], made["manifest"], job["id"], made["agent"]))


LOCAL_TOOLS["make_godot_game"] = make_godot_game
_GODOGEN_SCHEMA = schema(
    "make_godot_game", "Make a whole game from a description with godogen: a folder ~/LOKI Projects/<name> gets "
    "godogen's game-building instructions and a coding agent builds, runs and checks the game there as a background "
    "job (the user approves it first). engine: godot-gdscript (default; any Godot 4) | godot (C#, .NET Godot) | "
    "bevy | babylon | threejs. agent: auto | claude-code | codex | opencode | nanocoder | loki.",
    {"description": {"type": "string"}, "name": {"type": "string"},
     "engine": {"type": "string", "enum": ["godot-gdscript", "godot", "bevy", "babylon", "threejs"]},
     "agent": {"type": "string", "enum": ["auto", "claude-code", "codex", "opencode", "nanocoder", "loki"]}},
    ["description"])
TOOL_SCHEMAS.append(_GODOGEN_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_GODOGEN_SCHEMA)
MODEL_TOOL_NAMES.add("make_godot_game")
TOOL_CATEGORIES["godot"] += ["make_godot_game"]
DELEGATING |= {"make_godot_game"}
# (an unset Home Assistant is hidden from the model by the connectors' requirement loop above)

# The live Godot editor (engine/godot_live.py, owner 2026-10-18: "agents ... in a live project state, change everything"):
# every agent works in the owner's real Godot editor through the LOKI Studio plugin - whichever project is open.
# Read actions only in Plan mode (the tool enforces it); not hidden outside a Godot workspace.
import godot_live  # noqa: E402
LOCAL_TOOLS["godot_editor"] = godot_live.godot_editor
_GODOT_EDITOR_SCHEMA = schema(
    "godot_editor", godot_live.tool_doc(),
    {"action": {"type": "string", "enum": sorted(set(godot_live.studio_godot.ACTIONS) - {"quit"} | set(godot_live.EXTRA_ACTIONS))},
     "args": {"type": "object", "description": "the action's arguments, e.g. {\"node\": \"Player\", \"property\": \"speed\", \"value\": \"6\"}"},
     "project": {"type": "string", "description": "the project folder when more than one editor is open (default: the open one)"}},
    ["action"])
TOOL_SCHEMAS.append(_GODOT_EDITOR_SCHEMA)
MODEL_TOOL_SCHEMAS.append(_GODOT_EDITOR_SCHEMA)
MODEL_TOOL_NAMES.add("godot_editor")
TOOL_CATEGORIES["godot"] += ["godot_editor"]


# --- Session 29: documents, files and data (worktree) -----------------------------------------------
# Read anything (doc_read.py), write Word/Excel/PowerPoint/PDF (doc_write.py), analyze data in a sandbox and
# SQL over spreadsheets (data_sandbox.py), chat with document collections (knowledge.py collections, the same
# index memory.pack() already uses). Registration only; read_file hands documents to read_document.
import data_sandbox  # noqa: E402
import doc_read  # noqa: E402
import doc_write  # noqa: E402
import files_api  # noqa: E402

DOC_CACHE = DATA_DIR / "documents" / "cache"
DOC_READ_CHARS = int(os.getenv("LOKI_DOC_READ_CHARS", "12000") or 12000)


def _doc_path(name: str) -> Path:
    """A workspace path, or a file inside one of the owner's document collections ("<collection>/<file>" or
    an absolute path inside its folder)."""
    import knowledge  # pylint: disable=import-outside-toplevel
    raw = str(name or "").strip().strip('"').strip("'")
    try:
        path = resolve_in_workspace(raw)
        if path.exists() or not raw:
            return path
    except ValueError:
        path = None
    for coll in knowledge.list_collections(DATA_DIR):
        folder = Path(coll["folder"]).resolve()
        cand = Path(raw).expanduser()
        if not cand.is_absolute() and raw.lower().startswith(coll["name"].lower() + "/"):
            cand = folder / raw[len(coll["name"]) + 1:]
        cand = cand.resolve() if cand.is_absolute() else cand
        if cand.is_absolute() and (cand == folder or folder in cand.parents) and cand.exists():
            return cand
    if path is None:
        return resolve_readable(raw)   # LOKI's folder, its data folder, LOKI Projects, extra folders (or raises)
    return path


def _ws_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()
    except ValueError:
        return str(path)


def _vision_sync(png: bytes, prompt: str) -> str:
    return asyncio.run(_vision_ask(png, prompt))   # read_document runs in a worker thread: its own loop


async def read_document(path: str, pages: str = "", section: str = "", ocr: str = "auto", describe: bool = False,
                        password: str = "") -> str:
    """Any document as Markdown with page/section anchors; long ones in parts."""
    try:
        p = _doc_path(path)
    except ValueError as exc:
        return "error: %s" % exc
    if not p.is_file():
        return "error: no %s (list_tree shows what is there; dropped files land in uploads/)" % path
    opts = {"ocr": ocr or "auto", "password": password or ""}
    if describe:
        doc = await asyncio.to_thread(doc_read.convert, p, describe=True, vision=_vision_sync, **opts)
    else:
        doc = await asyncio.to_thread(doc_read.convert_cached, p, DOC_CACHE, **opts)
    if not doc.get("ok"):
        return "error: %s" % doc.get("error")
    files_api.touch(DATA_DIR, _ws_rel(p), "", "read by LOKI")
    every = doc.get("sections") or []
    chosen = doc_read.select(doc, pages, section) if (pages or section) else every
    if (pages or section) and not chosen:
        return "error: no such page/section. It has: %s" % ", ".join(s["anchor"] for s in every[:60])
    shown, size = [], 0
    for s in chosen:
        piece = len(s.get("text") or "") + len(s.get("title") or "") + 20
        if shown and size + piece > DOC_READ_CHARS:
            break
        shown.append(s)
        size += piece
    body = doc_read.build_markdown("", shown)
    if len(body) > DOC_READ_CHARS:
        body = body[:DOC_READ_CHARS] + "\n...(cut)"
    head = "%s - %s, %d %s, read with %s. Cite it as %s#<anchor> (anchors: %s%s)." % (
        _ws_rel(p), doc.get("format"), doc.get("pages") or len(every),
        "pages" if doc.get("format") == "pdf" else "sections", doc.get("backend"), p.name,
        ", ".join(s["anchor"] for s in every[:12]), " ..." if len(every) > 12 else "")
    if doc.get("warnings"):
        head += "\nNote: " + "; ".join(doc["warnings"])
    if len(shown) < len(chosen):
        nxt = chosen[len(shown)]
        head += ("\nShowing %d of %d parts - read on with pages='%s-' or section='%s'." % (
            len(shown), len(chosen), nxt.get("page") or (every.index(nxt) + 1), nxt["anchor"]))
    return head + "\n\n" + body


_read_file_text = LOCAL_TOOLS["read_file"]


async def read_file_any(filename: str, start_line: int = 0, end_line: int = 0) -> str:
    """read_file, but a PDF/Word/Excel/PowerPoint/picture/e-mail goes through read_document (a text read of a
    binary file used to fail with a decode error)."""
    if Path(str(filename)).suffix.lower() in (doc_read.DOCUMENT_SUFFIXES - doc_read.HTML):
        return await read_document(filename)
    return _read_file_text(filename, start_line, end_line)


def _out_path(path: str, overwrite: bool) -> Path:
    p = resolve_in_workspace(path)
    if p.exists() and not overwrite:
        raise ValueError("%s already exists - edit_document changes it, or pass overwrite=true" % path)
    return p


def _made(p: Path, what: str) -> str:
    rel = _ws_rel(p)
    files_api.touch(DATA_DIR, rel, "", "made by LOKI")
    return "made %s (%s). The owner opens it from the chat or the Files view; name it as `%s` in your answer." % (rel, what, rel)


def _slides_from_markdown(markdown: str) -> list:
    slides, cur = [], None
    for b in doc_write.blocks(markdown):
        if b["type"] == "heading" and b["level"] <= 2:
            cur = {"title": b["text"], "bullets": []}
            slides.append(cur)
            continue
        if cur is None:
            cur = {"title": "", "bullets": []}
            slides.append(cur)
        if b["type"] in ("bullet", "number"):
            cur["bullets"].append("  " * b["level"] + "- " + b["text"] if b["level"] else b["text"])
        elif b["type"] in ("para", "quote", "heading"):
            cur["bullets"].append(b["text"])
        elif b["type"] == "table":
            cur["table"] = b["rows"]
        elif b["type"] == "image":
            cur["image"] = b["path"]
    return slides


async def write_document(path: str, content: str = "", title: str = "", sheets=None, charts=None, slides=None,
                         overwrite: bool = False, paper: str = "a4") -> str:
    """Make a .docx / .xlsx / .pptx / .pdf / .md / .html in the workspace."""
    try:
        p = _out_path(path, bool(overwrite))
        suffix = p.suffix.lower()
        if suffix == ".docx":
            out = await asyncio.to_thread(doc_write.write_docx, p, content, title, WORKSPACE)
            return _made(p, "%d blocks" % out["blocks"])
        if suffix == ".xlsx":
            if not sheets and content:   # a Markdown table becomes the sheet
                tables = [b["rows"] for b in doc_write.blocks(content) if b["type"] == "table"]
                sheets = [{"name": title[:31] or "Sheet%d" % (i + 1), "rows": t} for i, t in enumerate(tables)]
            out = await asyncio.to_thread(doc_write.write_xlsx, p, sheets or [], charts or [])
            return _made(p, "sheets %s, %d formulas, %d charts" % (", ".join(out["sheets"]), out["formulas"], len(out["charts"])))
        if suffix == ".pptx":
            out = await asyncio.to_thread(doc_write.write_pptx, p, slides or _slides_from_markdown(content), title, WORKSPACE)
            return _made(p, "%d slides" % out["slides"])
        if suffix == ".pdf":
            out = await asyncio.to_thread(doc_write.markdown_to_pdf, content, p, title, WORKSPACE, "", paper)
            return _made(p, "PDF via %s" % out["engine"])
        if suffix in (".md", ".markdown", ".txt"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(("# %s\n\n" % title if title and not content.lstrip().startswith("#") else "") + content, encoding="utf-8")
            return _made(p, "%d characters" % len(content))
        if suffix in (".html", ".htm"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(doc_write.markdown_to_html(content, title, WORKSPACE, paper), encoding="utf-8")
            return _made(p, "HTML page")
        return "error: write_document makes .docx, .xlsx, .pptx, .pdf, .md or .html (got %s)" % (suffix or "no extension")
    except (ValueError, doc_write.WriteError, OSError, KeyError) as exc:
        return "error: %s" % exc


async def edit_document(path: str, replace=None, append: str = "", cells=None, append_rows=None, charts=None,
                        slides=None, save_as: str = "") -> str:
    """Change an existing .docx (replace text, append Markdown), .xlsx (cells, rows, charts), .pptx
    (replace text, add slides) or text file."""
    try:
        p = resolve_in_workspace(path)
        if not p.is_file():
            return "error: no %s" % path
        out = resolve_in_workspace(save_as) if save_as else None
        suffix = p.suffix.lower()
        replace = replace if isinstance(replace, dict) else {}
        if suffix == ".docx":
            got = await asyncio.to_thread(doc_write.edit_docx, p, replace, append, out, WORKSPACE)
        elif suffix in (".xlsx", ".xlsm"):
            got = await asyncio.to_thread(doc_write.edit_xlsx, p, cells or {}, append_rows or {}, charts or [], out)
        elif suffix == ".pptx":
            got = await asyncio.to_thread(doc_write.edit_pptx, p, replace, slides or [], out, WORKSPACE)
        elif suffix in doc_read.TEXT:
            text = p.read_text(encoding="utf-8")
            counts = {k: text.count(k) for k in replace}
            for k, v in replace.items():
                text = text.replace(k, str(v))
            text += ("\n\n" + append) if append else ""
            (out or p).write_text(text, encoding="utf-8")
            got = {"ok": True, "path": str(out or p), "replaced": counts, "not_found": [k for k, v in counts.items() if not v]}
        else:
            return "error: edit_document changes .docx, .xlsx, .pptx and text files (a PDF: pdf_tools)"
    except (ValueError, doc_write.WriteError, OSError, KeyError) as exc:
        return "error: %s" % exc
    done = _made(Path(got["path"]), "edited")
    if got.get("not_found"):
        done += " Not found (unchanged): %s" % ", ".join(repr(k) for k in got["not_found"])
    return done


async def pdf_tools(action: str, path: str = "", paths=None, out: str = "", ranges: str = "", values=None,
                    signers=None, flatten: bool = False, markdown: str = "", title: str = "") -> str:
    """info | fields | fill | merge | split | sign_ready | from_markdown"""
    action = str(action or "").lower().strip()
    try:
        src = resolve_in_workspace(path) if path else None
        if action not in ("merge", "from_markdown") and (src is None or not src.is_file()):
            return "error: give path= an existing PDF in the workspace"
        stem = _ws_rel(src.with_suffix("")) if src else "document"   # outputs land next to the source
        if action == "info":
            return json.dumps(await asyncio.to_thread(doc_write.pdf_info, src))
        if action == "fields":
            got = await asyncio.to_thread(doc_write.pdf_fields, src)
            return json.dumps(got["fields"])[:MAX_OUTPUT] if got["fields"] else "this PDF has no form fields"
        if action == "fill":
            target = _out_path(out or "%s_filled.pdf" % stem, True)
            got = await asyncio.to_thread(doc_write.pdf_fill, src, target, values or {}, bool(flatten))
            return _made(target, "filled %s%s" % (", ".join(got["filled"]) or "nothing",
                                                  "; unknown fields: %s" % ", ".join(got["unknown"]) if got["unknown"] else ""))
        if action == "merge":
            items = paths if isinstance(paths, list) else [x.strip() for x in str(paths or "").split(",") if x.strip()]
            inputs = [resolve_in_workspace(x) for x in items]
            missing = [x for x, q in zip(items, inputs) if not q.is_file()]
            if missing:
                return "error: no such file: %s" % ", ".join(missing)
            target = _out_path(out or "merged.pdf", True)
            got = await asyncio.to_thread(doc_write.pdf_merge, inputs, target)
            return _made(target, "%d PDFs, %d pages" % (got["inputs"], got["pages"]))
        if action == "split":
            folder = resolve_in_workspace(out or "%s_split" % stem)
            got = await asyncio.to_thread(doc_write.pdf_split, src, folder, ranges)
            return "made %d PDFs: %s" % (len(got["files"]), ", ".join(_ws_rel(Path(f)) for f in got["files"][:30]))
        if action == "sign_ready":
            target = _out_path(out or "%s_to_sign.pdf" % stem, True)
            names = signers if isinstance(signers, list) else [x.strip() for x in str(signers or "").split(",") if x.strip()]
            got = await asyncio.to_thread(doc_write.pdf_sign_ready, src, target, names)
            return _made(target, "a signature page with signature fields for %s" % ", ".join(got["signature_fields"]))
        if action == "from_markdown":
            target = _out_path(out or "document.pdf", True)
            got = await asyncio.to_thread(doc_write.markdown_to_pdf, markdown, target, title, WORKSPACE)
            return _made(target, "PDF via %s" % got["engine"])
    except (ValueError, doc_write.WriteError, OSError) as exc:
        return "error: %s" % exc
    return "error: action must be info, fields, fill, merge, split, sign_ready or from_markdown"


def _data_files(path) -> list:
    items = path if isinstance(path, list) else [x.strip() for x in str(path or "").split(",") if x.strip()]
    return [_doc_path(x) for x in items]


async def analyze_data(path, question: str = "", code: str = "", sheet: str = "") -> str:
    """Profile / analyze CSV, Excel or JSON in the data sandbox; charts land in analysis/<time>/."""
    try:
        files = _data_files(path)
    except ValueError as exc:
        return "error: %s" % exc
    if not files:
        return "error: give path= the data file(s)"
    got = await asyncio.to_thread(data_sandbox.analyze, files, question, code, WORKSPACE, sheet)
    if not got.get("ok"):
        return "error: %s%s" % (got.get("error"), ("\n" + got["trace"]) if got.get("trace") else "")
    for c in got.get("charts") or []:
        files_api.touch(DATA_DIR, c, "", "made by LOKI")
    parts = []
    if got.get("finding"):
        parts.append("Finding:\n" + got["finding"])
    if got.get("stdout") and not got.get("tables"):
        parts.append("Printed:\n" + got["stdout"][:3000])
    for t in (got.get("tables") or [])[:3]:
        parts.append(t[:2500])
    if got.get("charts"):
        parts.append("Charts saved (show them in your answer as ![chart](path) so the owner sees them):\n" +
                     "\n".join("![%s](%s)" % (Path(c).stem.replace("_", " "), c) for c in got["charts"]))
    if got.get("note"):
        parts.append("Note: " + got["note"])
    return "\n\n".join(parts)[:MAX_OUTPUT] or "the analysis ran and printed nothing - print() or show() the result"


async def data_sql(query: str, files) -> str:
    """One read-only SQL query over CSV/XLSX/JSON files (each file = a table named after it)."""
    try:
        paths = _data_files(files)
    except ValueError as exc:
        return "error: %s" % exc
    got = await asyncio.to_thread(data_sandbox.sql, query, paths)
    if got.get("ok"):
        return "%s\n\n(%d rows, %s)" % (got["markdown"][:MAX_OUTPUT - 200], got["total"], got["engine"])
    schema_lines = []
    used: set = set()
    for p in paths:
        try:
            cols, _rows = data_sandbox.load_rows(p)
            schema_lines.append("%s(%s)" % (data_sandbox.table_name(p, used), ", ".join(cols)))
        except Exception:  # noqa: BLE001
            continue
    return "error: %s%s" % (got.get("error"), ("\nTables: " + "; ".join(schema_lines)) if schema_lines else "")


async def documents(action: str = "search", query: str = "", folder: str = "", name: str = "", ocr: bool = False,
                    top: int = 6) -> str:
    """search | collections | add | remove | index - the owner's document collections."""
    import knowledge  # pylint: disable=import-outside-toplevel
    action = str(action or "search").lower()
    if action == "collections":
        items = knowledge.list_collections(DATA_DIR)
        if not items:
            return "no document collections yet - add one with action='add', folder='<folder>'"
        return "\n".join("- %s: %s (%d files indexed)" % (c["name"], c["folder"], knowledge.collection_index(DATA_DIR, c).status()["files"])
                         for c in items)
    if action == "add":
        target = Path(folder).expanduser()
        try:
            target = target if target.is_absolute() else resolve_in_workspace(folder)
        except ValueError as exc:
            return "error: %s" % exc
        got = knowledge.add_collection(DATA_DIR, target, name, bool(ocr))
        if not got.get("ok"):
            return "error: %s" % got.get("error")
        idx = await asyncio.to_thread(knowledge.collection_index(DATA_DIR, got["collection"]).refresh, 20.0)
        return "added the collection %s (%d files, %d passages%s)" % (
            got["collection"]["name"], idx.get("files", 0), idx.get("chunks", 0), "" if idx.get("complete") else "; still indexing")
    if action == "remove":
        got = knowledge.remove_collection(DATA_DIR, name)
        return "removed %s" % name if got.get("ok") else "error: %s" % got.get("error")
    if action == "index":
        out = []
        for c in knowledge.list_collections(DATA_DIR):
            if name and c["name"].lower() != name.lower():
                continue
            st = await asyncio.to_thread(knowledge.collection_index(DATA_DIR, c).refresh, 60.0)
            out.append("%s: %d files, %d passages%s" % (c["name"], st.get("files", 0), st.get("chunks", 0),
                                                         "" if st.get("complete") else " (more next time)"))
        return "\n".join(out) or "no such collection"
    hits = await asyncio.to_thread(knowledge.search_documents, DATA_DIR, query, int(top or 6), name, True, True)
    if not knowledge.list_collections(DATA_DIR):   # no collections yet: the workspace's own documents
        index = knowledge.project_index(WORKSPACE, DATA_DIR)
        await asyncio.to_thread(index.refresh, 8.0)
        hits = await asyncio.to_thread(index.search, query, int(top or 6))
    if not hits:
        return "nothing in the documents matches %r - try other words, or read_document a file directly" % query
    return ("Passages (answer from them and cite each fact as [cite]):\n\n" +
            "\n\n".join("[%s]\n%s" % (h["cite"], " ".join(h["text"].split())[:900]) for h in hits))[:MAX_OUTPUT]


LOCAL_TOOLS.update({"read_document": read_document, "read_file": read_file_any, "write_document": write_document,
                    "edit_document": edit_document, "pdf_tools": pdf_tools, "analyze_data": analyze_data,
                    "data_sql": data_sql, "documents": documents})
_S29_SCHEMAS = [
    schema("read_document", "Read any document as Markdown with page/section anchors: PDF (scans via OCR), Word, Excel, "
           "PowerPoint, CSV, e-mail (.eml), EPUB, HTML, pictures (text by OCR; describe=true asks a vision model what it "
           "shows). Long files come in parts: pages='3-5' or section='<anchor>'. Cite as file#anchor, e.g. report.pdf#p3. "
           "Example: {\"path\": \"uploads/contract.pdf\", \"pages\": \"1-2\"}",
           {"path": {"type": "string"}, "pages": {"type": "string"}, "section": {"type": "string"},
            "ocr": {"type": "string", "enum": ["auto", "off"]}, "describe": {"type": "boolean"},
            "password": {"type": "string"}}, ["path"]),
    schema("write_document", "Make a document from Markdown: .docx (Word), .pdf (a clean PDF), .pptx (each ## heading = a "
           "slide, or slides=[{title, bullets, image, notes, table}]), .xlsx (sheets=[{name, rows: [[...]]}] - a cell "
           "'=SUM(B2:B9)' is a real formula; charts=[{sheet, type: bar|line|pie|scatter, title, data: 'B1:C9', "
           "categories: 'A2:A9'}]), .md or .html. Example: {\"path\": \"reports/q3.docx\", \"title\": \"Q3\", "
           "\"content\": \"# Q3\\n\\n| Region | Sales |\\n|---|---|\\n| North | 10 |\"}",
           {"path": {"type": "string"}, "content": {"type": "string"}, "title": {"type": "string"},
            "sheets": {"type": "array", "items": {"type": "object"}}, "charts": {"type": "array", "items": {"type": "object"}},
            "slides": {"type": "array", "items": {"type": "object"}}, "overwrite": {"type": "boolean"},
            "paper": {"type": "string", "enum": ["a4", "letter"]}}, ["path"]),
    schema("edit_document", "Change an existing .docx (replace={old: new}, append=Markdown), .xlsx (cells={'Sheet1!B2': 5, "
           "'C3': '=B2*2'}, append_rows={'Sheet1': [[...]]}, charts=[...]) or .pptx (replace, slides to add). save_as "
           "keeps the original. Example: {\"path\": \"letter.docx\", \"replace\": {\"[NAME]\": \"Mia\"}}",
           {"path": {"type": "string"}, "replace": {"type": "object"}, "append": {"type": "string"},
            "cells": {"type": "object"}, "append_rows": {"type": "object"}, "charts": {"type": "array", "items": {"type": "object"}},
            "slides": {"type": "array", "items": {"type": "object"}}, "save_as": {"type": "string"}}, ["path"]),
    schema("pdf_tools", "PDF work: info, fields (list the form's fields), fill (values={field: value}, flatten), merge "
           "(paths=[a.pdf, b.pdf], out), split (ranges='1-3,5', or one PDF per page), sign_ready (adds a signature page "
           "with signature fields for signers=['Ann Lee', 'Bo Chan']), from_markdown (markdown -> out.pdf). "
           "Example: {\"action\": \"fill\", \"path\": \"form.pdf\", \"values\": {\"Name\": \"Mia\"}}",
           {"action": {"type": "string", "enum": ["info", "fields", "fill", "merge", "split", "sign_ready", "from_markdown"]},
            "path": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "out": {"type": "string"},
            "ranges": {"type": "string"}, "values": {"type": "object"}, "signers": {"type": "array", "items": {"type": "string"}},
            "flatten": {"type": "boolean"}, "markdown": {"type": "string"}, "title": {"type": "string"}}, ["action"]),
    schema("analyze_data", "Analyze a spreadsheet/CSV/JSON with pandas in a sandbox (no network, time and memory limits). "
           "Without code: a profile (sizes, missing values, totals, top groups, trend, strongest correlation) and charts. "
           "With code: `df` (first file) and `dfs` are loaded; show(frame) prints a table, chart('name') saves the current "
           "matplotlib figure, set finding='...' for the summary. Charts are saved in analysis/<time>/. "
           "Example: {\"path\": \"sales.xlsx\", \"code\": \"show(df.groupby('Region').Sales.sum())\"}",
           {"path": {"type": "string"}, "question": {"type": "string"}, "code": {"type": "string"},
            "sheet": {"type": "string"}}, ["path"]),
    schema("data_sql", "Answer a question over CSV/Excel/JSON files with ONE read-only SQL query; each file is a table named "
           "after it (sales.csv -> sales). DuckDB when installed, else SQLite. Example: {\"files\": [\"sales.csv\"], "
           "\"query\": \"SELECT region, SUM(units) AS u FROM sales GROUP BY region ORDER BY u DESC\"}",
           {"query": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}}}, ["query", "files"]),
    schema("documents", "The owner's document collections (folders indexed for questions): search (query -> passages "
           "with citations like Contracts/lease.pdf#p3 - answer from them and cite), collections (list), add "
           "(folder, name, ocr), remove (name), index (re-read changed files). Example: {\"action\": \"search\", "
           "\"query\": \"notice period for ending the lease\"}",
           {"action": {"type": "string", "enum": ["search", "collections", "add", "remove", "index"]},
            "query": {"type": "string"}, "folder": {"type": "string"}, "name": {"type": "string"},
            "ocr": {"type": "boolean"}, "top": {"type": "integer"}}, ["action"]),
]
TOOL_SCHEMAS.extend(_S29_SCHEMAS)
MODEL_TOOL_SCHEMAS.extend(_S29_SCHEMAS)
MODEL_TOOL_NAMES.update(s["function"]["name"] for s in _S29_SCHEMAS)
TOOL_CATEGORIES["documents"] = ["read_document", "write_document", "edit_document", "pdf_tools", "analyze_data",
                                "data_sql", "documents"]
CATEGORY_LABELS["documents"] = "Documents & data (read any file, write Word/Excel/PowerPoint/PDF, analyze spreadsheets)"
CATEGORIES.setdefault("documents", True)
MODIFYING |= {"write_document", "edit_document", "pdf_tools", "analyze_data"}
if "read_web" in LOCAL_TOOL_PRIORITY:   # after the web tools, which stay in the first ten
    _at = LOCAL_TOOL_PRIORITY.index("read_web") + 1
    LOCAL_TOOL_PRIORITY[_at:_at] = ["read_document", "write_document", "analyze_data"]


# --- Session 29: LOKI Apps - mini-apps, modes (personas) and extensions (docs/APPS.md) -------------------
# engine/apps.py (mini-apps LOKI builds and runs in a sandboxed frame), engine/personas.py (Tutor, Writer,
# Coder... packs), engine/extensions.py (plugins anyone can write). Registration only: two tools, the
# extensions' tools (each call asks unless the owner trusted that extension), and two wrappers AROUND
# system_prompt (the active mode's instructions) and _tool_enabled (a mode with only_tools) - neither changed.
import apps as _apps  # noqa: E402
import extensions as _extensions  # noqa: E402
import personas as _personas  # noqa: E402


def app_builder_guide() -> str:
    """How to build a LOKI mini-app: the bridge (loki.store / ask / files), the kit, the rules, a full example."""
    return _apps.guide()


def make_app(action: str = "create", name: str = "", title: str = "", description: str = "", icon: str = "",
             html: str = "", js: str = "", css: str = "", template: str = "") -> str:
    """Create / update / install / read / list LOKI mini-apps in <workspace>/apps/, or read an app's saved data."""
    action = str(action or "create").strip().lower()
    if action in ("create", "update", "write", "edit", "save"):
        if not name:
            return "error: make_app needs a name (lowercase, e.g. budget)"
        out = _apps.make_app(WORKSPACE, name, title=title, description=description, icon=icon, html=html, js=js, css=css)
        if not out.get("ok"):
            return "error: %s" % out.get("error")
        _progress("tool", "App %s %s - open it in Apps." % (out["name"], "updated" if out["updated"] else "made"))
        return ("%s app %s (%s). It is in the Apps area now (the grid icon in the sidebar); tell the user to open it."
                "%s" % ("updated" if out["updated"] else "made", out["name"], out["path"],
                        (" Warnings: " + "; ".join(out["warnings"])) if out.get("warnings") else ""))
    if action == "install":
        out = _apps.install_template(WORKSPACE, template or name, name if template else "")
        return ("installed the %s template as app %s; read it with make_app(action='read', name='%s') to change it"
                % (template or name, out["name"], out["name"])) if out.get("ok") else "error: %s" % out.get("error")
    if action == "read":
        out = _apps.read_app(WORKSPACE, _apps.clean_name(name))
        if not out.get("ok"):
            return "error: %s" % out.get("error")
        parts = ["APP %s - %s" % (out["name"], json.dumps(out["manifest"], ensure_ascii=False)[:600])]
        for rel, text in out["files"].items():
            if rel != "manifest.json":
                parts.append("---- %s ----\n%s" % (rel, text))
        return "\n".join(parts)
    if action == "list":
        mine = _apps.list_apps(WORKSPACE)
        return ("installed apps: " + (", ".join("%s (%s)" % (a["name"], a["title"]) for a in mine) or "none")
                + "\ntemplates: " + ", ".join(t["name"] for t in _apps.list_templates()))
    if action == "data":
        try:
            return "data saved by app %s:\n%s" % (name, _apps.data_summary(_apps.clean_name(name), DATA_DIR))
        except ValueError as exc:
            return "error: %s" % exc
    return "error: unknown action %r (create, update, install, read, list, data)" % action


async def app_ask(app_key: str, prompt: str, data=None) -> str:
    """'Ask LOKI' from inside a mini-app: one model call with the app's own data as context."""
    try:
        stored = _apps.data_summary(app_key, DATA_DIR, limit=8000)
    except ValueError:
        stored = "{}"
    extra = json.dumps(data, ensure_ascii=False, default=str)[:8000] if data is not None else ""
    title = app_key.split(":")[-1]
    system = ("You are LOKI, answering a question asked from inside the owner's mini-app '%s'. Answer in plain, "
              "short text (no Markdown tables unless asked), using the app's data below. If the data does not say, "
              "say so.\n\nThe app's saved data (JSON):\n%s%s"
              % (title, stored, ("\n\nWhat the app sent with the question:\n" + extra) if extra else ""))
    mode = _personas.active(DATA_DIR)
    if mode and mode.get("instructions"):
        system += "\n\n" + _personas.prompt_section(mode)
    return (await _port_ask(prompt, system=system, max_tokens=1200)).strip()


def _extension_runner(item: dict):
    async def run(**args) -> str:
        detail = "%s from extension %s(%s)" % (item["name"], item["ext_name"],
                                               json.dumps(args, ensure_ascii=False, default=str)[:300])
        if not item.get("trusted") and not await approve("extension_tool", detail, decidable=False):
            return ("DENIED: running %s (extension %s) was not approved. Do it with other tools, or reply "
                    "'BLOCKED: <reason>'." % (item["name"], item["ext_name"]))
        _ok, out = await asyncio.to_thread(_extensions.execute, item["path"], args, WORKSPACE, item["timeout"])
        return out
    return run


EXTENSIONS = _extensions.Registry(sys.modules[__name__], lambda: DATA_DIR, _extension_runner)
LOCAL_TOOLS.update({"app_builder_guide": app_builder_guide, "make_app": make_app})
_S29_SCHEMAS = [
    schema("app_builder_guide", "Before making or changing a LOKI app (a small tool the user keeps: budget, habit "
           "tracker, planner, flashcards, invoice...): how apps work inside LOKI - the loki.store/ask/files bridge, "
           "the design kit, the sandbox rules and a full example.", {}, []),
    schema("make_app", "Build a small app that runs inside LOKI's Apps area (read app_builder_guide first). "
           "action=create (name, title, icon emoji, description, html = BODY markup, js = app.js, css optional) - "
           "also updates an existing app (only the parts given are replaced); action=install template=<budget|habits|"
           "journal|flashcards|meals|workout|reading|contacts|invoice|kanban|pomodoro|notes>; action=read name (its "
           "files, before changing it); action=list; action=data name (what the app saved).",
           {"action": {"type": "string", "enum": ["create", "update", "install", "read", "list", "data"]},
            "name": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"},
            "icon": {"type": "string"}, "html": {"type": "string"}, "js": {"type": "string"},
            "css": {"type": "string"}, "template": {"type": "string"}}, ["action"]),
]
TOOL_SCHEMAS.extend(_S29_SCHEMAS)
MODEL_TOOL_SCHEMAS.extend(_S29_SCHEMAS)
MODEL_TOOL_NAMES.update(("app_builder_guide", "make_app"))
TOOL_CATEGORIES["creative"] += ["app_builder_guide", "make_app"]
TOOL_CATEGORIES["extensions"] = []
CATEGORY_LABELS["extensions"] = "Extensions you installed (each call asks first unless you trusted it)"
CATEGORIES.setdefault("extensions", True)
MODIFYING.add("make_app")       # it writes files: never in Plan mode, and counts as real work
try:
    EXTENSIONS.sync()
except Exception as _exc:  # noqa: BLE001 - a broken extension must never stop LOKI starting
    print("[loki] extensions could not be loaded: %s" % _exc)

_PERSONA_PROMOTED: list = []


def apply_persona() -> dict | None:
    """Put the active mode's tools first for small models (and take the last mode's back out)."""
    mode = _personas.active(DATA_DIR)
    for name in _PERSONA_PROMOTED:
        if name in LOCAL_TOOL_PRIORITY:
            LOCAL_TOOL_PRIORITY.remove(name)
    _PERSONA_PROMOTED.clear()
    wanted = [t for t in (mode or {}).get("tools") or [] if t in LOCAL_TOOLS and t not in LOCAL_TOOL_PRIORITY]
    at = LOCAL_TOOL_PRIORITY.index("find_tools") + 1 if "find_tools" in LOCAL_TOOL_PRIORITY else 0
    LOCAL_TOOL_PRIORITY[at:at] = wanted
    _PERSONA_PROMOTED.extend(wanted)
    try:
        refresh_system_prompt()
    except Exception:  # noqa: BLE001
        pass
    return mode


_system_prompt_plain = system_prompt


def system_prompt() -> str:   # noqa: F811 - the active mode's instructions on top of LOKI's own
    text = _system_prompt_plain()
    try:
        mode = _personas.active(DATA_DIR)
    except Exception:  # noqa: BLE001 - a broken mode file never breaks a request
        mode = None
    text += (chr(10) * 2 + _personas.prompt_section(mode) if mode else "")
    try:   # where LOKI's code, logs and the other projects are (owner 2026-10-22: agents could not find them)
        text += chr(10) * 2 + folders_tool()
    except Exception:  # noqa: BLE001
        pass
    try:   # the owner's other machines, every request (owner 2026-10-25: "it should know to go look for whats linked")
        import machines  # pylint: disable=import-outside-toplevel
        text += chr(10) * 2 + "# Your other machines" + chr(10) + machines.describe().replace(
            "list_machines", "machines(action=list)").replace("run_on_machine", "machines(action=run)").replace(
            "machine_job", "machines(action=status)")
    except Exception:  # noqa: BLE001
        pass
    return text


_tool_enabled_before_modes = _tool_enabled
# Always offered, even in a mode with only_tools: answering, planning and finding more tools.
_MODE_ALWAYS = {"machines", "find_tools", "todo_add", "todo_list", "todo_done", "save_memory", "read_file", "list_files", "folders",
                "app_builder_guide", "make_app", "load_ecc_skill", "list_ecc_skills"}


def _tool_enabled(tool_name: str) -> bool:   # noqa: F811 - a mode with only_tools narrows the offer
    if not _tool_enabled_before_modes(tool_name):
        return False
    try:
        mode = _personas.active(DATA_DIR)
    except Exception:  # noqa: BLE001
        return True
    if mode and mode.get("only_tools") and mode.get("tools"):
        return tool_name in mode["tools"] or tool_name in _MODE_ALWAYS
    return True


try:
    apply_persona()
except Exception as _exc:  # noqa: BLE001
    print("[loki] the chosen mode could not be applied: %s" % _exc)


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


def make_client():
    """An AsyncOpenAI for HTTP providers, or the CLI-agent shim for subscription ones."""
    cfg = MODELS[active_model_name()]
    if "11434" in str(cfg.base_url or ""):
        cfg.model = resolve_local_model(active_model_name())   # a preset tag is per-machine: use what is installed
    if cfg.base_url.startswith(CLI_AGENT_PREFIX):
        return cli_agents.make_client(cfg.base_url[len(CLI_AGENT_PREFIX):], str(WORKSPACE))
    base_url = cfg.base_url
    if not str(cfg.api_key or "").strip() and "11434" not in base_url:
        # A provider with no key: say which key, instead of the client library's
        # "Missing credentials ... OPENAI_API_KEY" traceback (which names the wrong key).
        name = active_model_name()
        raise ModelUnavailable(
            "[model unavailable] %s needs an API key and none is set. Add %s in Settings > "
            "Connections (or harness_data/.env), or pick 'smart' so Loki uses a provider "
            "that is ready." % (name, missing_key_env(name)))
    # Ollama federation: when this machine's Ollama is down or lacks the model, use a
    # listed worker that has it - only with the ollama-fleet capability enabled.
    if federation.is_ollama(base_url) and CAPABILITIES.is_enabled("ollama-fleet"):
        try:
            base_url, note = federation.route(base_url, cfg.model)
            if note:
                print("  [fleet] " + note)
        except Exception:
            base_url = cfg.base_url
    # max_retries=0: LOKI retries itself (_model_request) and fails over to another provider;
    # the SDK's own hidden retries (up to 60 s on a 429's Retry-After, twice) only delayed that.
    return AsyncOpenAI(base_url=base_url, api_key=cfg.api_key, timeout=MODEL_TIMEOUT_S, max_retries=0)


def short_error(text, limit: int = 240) -> str:
    """Collapse a message into one readable paragraph, trimming a huge API body."""
    collapsed = " ".join(clean_text(str(text)).split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 3].rstrip() + "..."
    return collapsed


def friendly_error(exc) -> str:
    """A short, human message for the chat - never a raw exception name.

    The dock shows this directly, so it reads plainly: what happened
    and what to do, not "KeyError: 'x'".
    """
    if isinstance(exc, ModelUnavailable):
        return exc.hint
    if isinstance(exc, BudgetExhausted):
        return str(exc)
    text = short_error(exc)
    low = text.lower()
    if isinstance(exc, FileNotFoundError) or "no such file" in low:
        return "That file does not exist: " + text
    if isinstance(exc, PermissionError) or "permission denied" in low:
        return "Loki cannot write there (permission denied)."
    if isinstance(exc, TimeoutError) or "timed out" in low or "timeout" in low:
        return "That took too long and timed out. Try again."
    if "connection" in low or "unreachable" in low or "refused" in low:
        return "Loki could not reach the model. Check your connection and retry."
    if isinstance(exc, KeyError):
        return "Loki was missing something it needed (%s)." % text
    return text or type(exc).__name__


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
_stuck_hits = 0         # stuck patterns seen in this request (stuck.py)
STUCK_DETECTION = str(os.getenv("LOKI_STUCK_DETECTION", "on")).strip().lower() not in ("0", "off", "false", "no")
STUCK_STOP_AFTER = int(os.getenv("LOKI_STUCK_STOP_AFTER", "2") or 2)
CONDENSE_STATS = {"runs": 0, "forgot": 0, "fallback": 0}
_task_modified = False
_task_wrote_file = False   # a file (not just a folder) was written or changed in this task

# ---------------------------------------------------------------------------
# Verification: a model saying it is done is not proof that it is.
# ---------------------------------------------------------------------------
# Every project file a request writes is recorded. When the agent finishes, those
# files - and only those - are checked deterministically (scripts compiled, scenes
# loaded headless, JSON parsed). Real errors go back to the model a bounded number of
# times; the final answer always says what was verified, what failed, and what could
# NOT be verified, so a missing engine is never reported as success.
_task_files: list = []
_LAST_VERIFY: dict = {}        # the last verification report of this request
_REQUEST_TOOL_CALLS = 0        # tool calls made in this request
_GUARD_AT_START = {"repaired": 0, "rejected": 0}   # tool-guard counters when the request began
EXPERIENCE_ENABLED = str(os.getenv("LOKI_EXPERIENCE", "1")).strip().lower() not in ("0", "false", "off", "no")
VERIFY_ENABLED = str(os.getenv("LOKI_VERIFY", "1")).strip().lower() not in ("0", "false", "off", "no")
VERIFY_MAX_FILES = int(os.getenv("LOKI_VERIFY_MAX_FILES", "6"))
VERIFY_FIX_ROUNDS = int(os.getenv("LOKI_VERIFY_FIX_ROUNDS", "2"))
_PROJECT_SETTINGS_TOOLS = ("add_input_action", "set_project_setting", "add_autoload")


def _touched_path(name: str, args: dict) -> str:
    """The project file a modifying tool call wrote, or "" when there is none to check."""
    if name in _PROJECT_SETTINGS_TOOLS:
        return "project.godot"
    if name in ("delete_file", "make_dir"):
        return ""
    if name == "move_file":
        return str(args.get("dst") or "")
    return str(args.get("filename") or args.get("path") or "")


def _specialist_made(name: str, result) -> str:
    """The workspace path a conductor specialist reported making ("made <file> with <backend>"),
    or ""."""
    if name != "conductor" or not isinstance(result, str):
        return ""
    m = re.match(r"\s*made (.+?) with ", result)
    if not m:
        return ""
    raw = m.group(1).strip().strip("'\"")
    try:
        rel = Path(raw).resolve().relative_to(Path(WORKSPACE).resolve())
        return rel.as_posix()
    except (ValueError, OSError):
        return raw if not os.path.isabs(raw) else ""


def _record_touched(name: str, args: dict, result) -> None:
    path = _touched_path(name, args)
    if not path or str(result).lstrip().lower().startswith("error"):
        return
    path = path.replace("res://", "", 1).lstrip("/")
    if path in _task_files:
        _task_files.remove(path)
    _task_files.append(path)   # most recent last


# MCP tools (godot-editor-mcp and friends) write project files too. Their names vary by
# server, so recognise them by verb, and take the file from a *_path argument whose
# value looks like a file. Node paths ("Player/Camera") are tree paths, not files.
_MCP_WRITE_VERB = re.compile(r"(^|_)(write|patch|create|save|move|scaffold|import|attach)_")
_MCP_SETTINGS_TOOL = re.compile(r"(^|_)(set_setting|add_input_action|remove_input_action|"
                                r"add_input_event|clear_input_action_events|register_autoload|"
                                r"unregister_autoload)$")
_MCP_FILE_KEYS = ("script_path", "scene_path", "shader_path", "save_path", "resource_path",
                  "tileset_path", "library_path", "new_path", "path", "file_path", "target_file")
_FILE_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,6}$")


def mcp_touched_paths(name: str, args: dict) -> list:
    """Project files an MCP tool call writes (best effort, by name and arguments)."""
    if not isinstance(args, dict):
        return []
    if _MCP_SETTINGS_TOOL.search(name):
        return ["project.godot"]
    if not _MCP_WRITE_VERB.search(name):
        return []
    found = []
    for key in _MCP_FILE_KEYS:
        value = args.get(key)
        if isinstance(value, str) and _FILE_SUFFIX.search(value.strip()):
            path = value.strip().replace("res://", "", 1).lstrip("/")
            if path not in found:
                found.append(path)
    return found


def _record_mcp_touched(name: str, args: dict, result_text: str) -> bool:
    head = str(result_text or "")[:200].lower()
    if head.startswith("error") or '"ok": false' in head or '"error"' in head[:40]:
        return False
    paths = mcp_touched_paths(name, args)
    for path in paths:
        _record_touched("write_file", {"filename": path}, "ok")
    return bool(paths)


def _verdict(text: str) -> str:
    """Classify a checker's output: 'ok', 'failed' or 'unverified'."""
    if NOT_VERIFIED in text:
        return "unverified"
    head = text.split(chr(10), 1)[0]
    if "ERRORS" in head or "INVALID" in head:
        return "failed"
    if ": error " in head or "timed out" in head:
        return "unverified"
    return "ok"


_SYNTAX_CHECKED = (".py", ".pyw", ".toml", ".xml", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css")


def verify_files(paths) -> dict:
    """Check each path that has a deterministic checker. Pure apart from running Godot.

    Returns {"ok": [...], "failed": [(path, detail)], "unverified": [(path, why)],
             "skipped": [...]} - skipped means no checker exists for that file type.
    """
    report = {"ok": [], "failed": [], "unverified": [], "skipped": []}
    seen = []
    for path in paths:
        if path and path not in seen:
            seen.append(path)
    checked = seen[-VERIFY_MAX_FILES:] if VERIFY_MAX_FILES > 0 else seen
    for path in checked:
        lower = path.lower()
        try:
            exists = resolve_in_workspace(path).is_file()
        except Exception:
            exists = False
        if not exists:
            report["unverified"].append((path, "no longer exists"))
            continue
        if lower.endswith(".gd"):
            text = check_script(path)
        elif lower.endswith((".tscn", ".scn")):
            text = validate_scene(path)
        elif lower.endswith(".json"):
            try:
                json.loads(resolve_in_workspace(path).read_text(encoding="utf-8"))
                text = "json %s: parses OK" % path
            except Exception as exc:
                text = "json %s: INVALID - %s" % (path, exc)
        elif lower.endswith(tuple(MEDIA_SUFFIXES)):
            text = media_check(path)
        elif lower.endswith(_SYNTAX_CHECKED):
            # Python, TOML, XML and the C-like languages (JS, TS, CSS...): a syntax check, so
            # "DONE" on a script that does not even compile is sent back (it used to pass as
            # "no automatic check").
            import lint_guard  # pylint: disable=import-outside-toplevel
            try:
                errors = lint_guard.check(path, resolve_in_workspace(path).read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                errors = ["cannot read it: %s" % exc]
            text = ("syntax %s: ERRORS\n%s" % (path, "\n".join(errors[:6]))) if errors else "syntax %s: OK" % path
        else:
            report["skipped"].append(path)
            continue
        kind = _verdict(text)
        if kind == "ok":
            report["ok"].append(path)
        elif kind == "failed":
            report["failed"].append((path, _shorten(text)[:1500]))
        else:
            first = text.split(chr(10), 1)[0]
            why = "Godot not found" if NOT_VERIFIED in text else first[:160]
            report["unverified"].append((path, why))
    report["skipped"].extend(p for p in seen if p not in checked)
    return report


def verification_summary(report: dict) -> str:
    """One honest line for the user: what passed, what failed, what was not checked."""
    parts = []
    if report["ok"]:
        parts.append("%d checked OK (%s)" % (len(report["ok"]), ", ".join(report["ok"])))
    if report["failed"]:
        parts.append("%d FAILED (%s)" % (len(report["failed"]),
                                         ", ".join(p for p, _ in report["failed"])))
    if report["unverified"]:
        parts.append("%d not verified (%s)" % (len(report["unverified"]), "; ".join(
            "%s: %s" % (p, why) for p, why in report["unverified"])))
    if report["skipped"]:
        parts.append("%d with no automatic check (%s)" % (len(report["skipped"]),
                                                          ", ".join(report["skipped"])))
    return "Verification: " + ("; ".join(parts) if parts else "nothing to check") + "."


def verification_feedback(report: dict) -> str:
    """The message that sends real errors back to the model."""
    lines = ["Automatic verification of the files you changed found errors. The task is NOT "
             "done. Fix them, then reply 'DONE: <summary>' again:"]
    for path, detail in report["failed"]:
        lines.append("")
        lines.append("--- " + path)
        lines.append(detail)
    return chr(10).join(lines)


async def _verify_touched() -> dict:
    _progress("thinking", "Verifying %d changed file(s)..." % len(_task_files))
    _speed_t0 = time.monotonic()   # speed watch (E6): verification
    report = await asyncio.to_thread(verify_files, list(_task_files))
    speed_watch.since(_speed_t0, "verification", "%d file(s)" % len(_task_files))
    _LAST_VERIFY.clear()
    _LAST_VERIFY.update(report)
    return report

# Loop detection (Jev): a rolling window of recent actions, checked periodically so a
# model that keeps retrying the same *approach* (not an identical call) gets nudged.
_jev_loop_window = []
JEV_LOOP_CHECK_EVERY = int(os.getenv("LOKI_JEV_LOOP_EVERY", "6"))


async def _jev_loop_nudge() -> str:
    """Ask Jev whether the recent actions repeat the same approach without progress.

    Returns the probability as text when Jev is confident, else "". Never fatal.
    """
    if not decisions.enabled_providers() or len(_jev_loop_window) < 4:
        return ""
    state = "Recent agent actions, oldest first:" + chr(10) + chr(10).join(_jev_loop_window[-8:])
    try:
        return await asyncio.to_thread(decisions.loop_nudge, state)
    except Exception:
        return ""


def jev_status() -> dict:
    """Jev availability for the doctor, the bridge and the dock."""
    return jev.status()


def decision_status() -> dict:
    """Laya/Jev routing, provider availability and disagreement stats."""
    return decisions.status()

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
    # Normalise FIRST and unconditionally: one provider object left in the list used to
    # crash every later pass that walks it (see _as_dict).
    messages[:] = [messages[0]] + [_as_dict(m) for m in messages[1:]]
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


def _retry_header(exc):
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        return headers.get("retry-after") if headers is not None else None
    except Exception:  # noqa: BLE001
        return None


def _has_alternative(provider: str) -> bool:
    """Is another provider ready, so a struggling one is not worth a long back-off?"""
    if model_name not in AUTO_ROUTING_MODES:
        return False
    order = ONLINE_ORDER if model_name == "online" else SMART_ORDER
    try:
        return any(p != provider and p not in _SMART_FAILED and provider_configured(p)
                   and (provider_tier(p) != "paid" or paid_allowed_automatically())
                   and provider_health.registry().usable(p)[0] for p in order)
    except Exception:  # noqa: BLE001
        return False


def _health_failure(provider: str, cfg, text: str, status: int = 0, exc=None) -> None:
    """Remember why this provider failed (provider_health), for every process. Never raises."""
    try:
        header = _retry_header(exc)
        provider_health.registry().record_failure(provider or active_model_name(), text, status,
                                                  key=str(getattr(cfg, "api_key", "") or ""), header_retry=header)
    except Exception:  # noqa: BLE001
        pass


def _health_success(provider: str, cfg, started: float, kwargs: dict) -> None:
    try:
        provider_health.registry().record_success(
            provider, (time.monotonic() - started) * 1000, key=str(getattr(cfg, "api_key", "") or ""),
            request_tokens=routing.estimate_tokens(kwargs.get("messages") or [], len(json.dumps(kwargs.get("tools") or []))))
    except Exception:  # noqa: BLE001
        pass


def _no_choices(response) -> bool:
    try:
        return not list(getattr(response, "choices", None) or [])
    except TypeError:
        return False


# In smart/online mode another provider is ready, so a rate limit or a timeout is not worth
# the full back-off on THIS one: one quick retry, then fail over (LOKI_AUTO_RETRIES).
AUTO_RETRIES = int(os.getenv("LOKI_AUTO_RETRIES", "1") or 1)


async def _model_request(client, kwargs: dict, cfg, provider: str = ""):
    """Ask the model, retrying transient failures so one 429 does not end the task.

    `provider` is the MODELS key the request goes to; a failure marks THAT provider, and
    provider_health remembers why (for routing, the next job and Settings > Connections).
    """
    kwargs = dict(kwargs)   # the halved tool list below stays in THIS call; a retry starts full
    attempt = 0
    empty = 0
    full_tools = list(kwargs.get("tools") or [])
    auto = model_name in AUTO_ROUTING_MODES
    retries = min(MODEL_RETRIES, AUTO_RETRIES) if auto else MODEL_RETRIES   # used when another provider is ready
    while True:
        constrained = False
        if provider and ratelimit.rpm(provider):
            # NVIDIA NIM's free tier is ~40 requests/min per account: space the requests (shared
            # with jobs and LOKI Studio through the data folder) instead of collecting 429s.
            await ratelimit.acquire_async(provider, max_wait_s=RATE_PACE_MAX_S,
                                          say=lambda m: _progress("thinking", m))
        started = time.monotonic()
        try:
            if kwargs.get("tools") and _use_constrained(provider, cfg):
                # A local server with grammar support: the reply can ONLY be a real tool
                # call or an answer, so a small model can no longer get the shape wrong.
                constrained = True
                response = await _constrained_request(client, kwargs)
            elif kwargs.get("tools") and tool_harness.configured(provider):
                # This provider cannot take a native tools list: send the tools as text
                # and turn the <tool_call> blocks in its answer back into tool_calls.
                prompted = _provider_kwargs(provider, cfg, tool_harness.prepare(kwargs))
                known = prompted.pop("_prompted_tools", [])
                response = await client.chat.completions.create(**prompted)
                if not _no_choices(response):
                    response = tool_harness.attach(response, known)
            else:
                sent = _provider_kwargs(provider, cfg, _small_model_kwargs(kwargs, cfg))
                if _stream_for(provider, cfg):
                    response = await _streamed_request(client, sent)
                else:
                    response = await client.chat.completions.create(**sent)
                if not _no_choices(response):
                    response = _salvage_reply(response, kwargs)
            if _no_choices(response):
                # An answer with no choices at all (seen from overloaded free routes): retry once,
                # then treat it like any other provider failure - never an IndexError later.
                empty += 1
                if empty <= 1:
                    _progress("thinking", "%s returned an empty reply; asking again..." % (provider or cfg.model))
                    continue
                text = "[model error] %s returned an empty reply (no choices)" % cfg.model
                _mark_smart_failure(provider)
                _health_failure(provider, cfg, text)
                raise ModelUnavailable(text)
            if provider:
                _health_success(provider, cfg, started, kwargs)
            return _take_reasoning(response, provider, cfg)
        except openai.APIStatusError as exc:
            status = _status_of(exc)
            if status == 429 and provider and ratelimit.rpm(provider):
                # Over the cap anyway (another program on the same key): the next requests wait.
                ratelimit.penalize(provider, provider_health.retry_after(str(exc.message), _retry_header(exc)) or 20)
            if constrained and 400 <= status < 500:
                # This server does not take response_format/json_schema: plain prompted
                # (or native) tools from now on, and retry this same request.
                CONSTRAINED_REFUSED.add(provider or cfg.base_url)
                _progress("thinking", "%s has no structured output; using plain tool calling." % (provider or cfg.model))
                continue
            if (status in (400, 404, 422) and kwargs.get("tools") and len(kwargs["tools"]) <= 1
                    and provider and not tool_harness.configured(provider)):
                # Even one tool was refused: this endpoint has no native tool calling.
                # Use the prompted harness for it from now on (any model, any tool).
                tool_harness.learn(provider)
                _progress("thinking", "%s has no native tool calling; using prompted tools." % provider)
                kwargs["tools"] = full_tools or kwargs["tools"]
                continue
            if "tool_choice" in kwargs and 400 <= status < 500:
                # Backend does not support tool_choice; retry unforced.
                kwargs.pop("tool_choice", None)
                continue
            if (status in (400, 422) and kwargs.get("tools") and attempt < 3
                    and not condenser.is_context_error(str(exc.message))):
                # The provider refused the request - most often because the tool
                # list is longer than it allows (Gemini and Groq both reject a long
                # one). Halve it and try again on this provider; if it still fails
                # the run fails over, so no single provider can stop the work.
                kwargs["tools"] = kwargs["tools"][: max(1, len(kwargs["tools"]) // 2)]
                attempt += 1
                _progress("thinking", "Model refused the tool list (HTTP %s); retrying with %d tools..."
                          % (status, len(kwargs["tools"])))
                continue
            wait_hint = provider_health.retry_after(str(exc.message), _retry_header(exc))
            paced_429 = status == 429 and bool(provider) and ratelimit.rpm(provider) > 0 and _has_alternative(provider)
            if (status in _TRANSIENT_STATUS and attempt < (retries if _has_alternative(provider) else MODEL_RETRIES)
                    and not _is_quota_error(exc) and not (auto and wait_hint > RETRY_MAX_S and _has_alternative(provider))
                    and not paced_429):   # a paced provider that still says 429 is saturated: fail over now
                attempt += 1
                delay = _retry_delay(attempt)
                _progress("thinking", "Model returned HTTP %s; retrying in %.1fs (attempt %d of %d)..." % (status, delay, attempt, retries))
                await asyncio.sleep(delay)
                continue
            _mark_smart_failure(provider)
            _health_failure(provider, cfg, "HTTP %s: %s" % (status, exc.message), status, exc)
            if status == 404 and ("11434" in cfg.base_url) and "not found" in str(exc.message).lower():
                # Ollama is up but this model was never pulled. Marked as a limit so a
                # smart run fails over instead of ending.
                raise ModelUnavailable(
                    "[model missing] Ollama does not have %s yet. "
                    "Run `ollama pull %s` in Terminal, or pick another model." % (cfg.model, cfg.model)
                ) from exc
            if _cfg_is_local(cfg) and "11434" in cfg.base_url and model_setup.is_load_error(str(exc.message)):
                # Ollama cannot even read this model's file (Bonsai 2's ternary GGUF on the Mac,
                # 2026-10-17). Remember it for this Ollama version, move to the next local model now,
                # and let this request fail over instead of failing every request from here on.
                broken = cfg.model
                model_setup.mark_broken(broken, str(exc.message), LOCAL_STATE.get("version", ""))
                try:
                    now = _resolve_local()
                    instead = now.get("name") or "a cloud model"
                except Exception:  # noqa: BLE001
                    instead = "another model"
                raise ModelUnavailable(
                    "[model error] Ollama cannot load %s on this computer (its file format is newer than this "
                    "Ollama). LOKI switched to %s. Updating Ollama lets LOKI try it again." % (broken, instead)
                ) from exc
            raise ModelUnavailable(
                "[model error] %s answered HTTP %s: %s" % (cfg.model, status, short_error(exc.message))
            ) from exc
        except openai.APIConnectionError as exc:
            timed_out = isinstance(exc, getattr(openai, "APITimeoutError", ())) or "timed out" in str(exc).lower()
            # A timeout already cost MODEL_TIMEOUT_S; four more would cost minutes. One retry.
            limit = min(retries, 1) if timed_out else (retries if _has_alternative(provider) else MODEL_RETRIES)
            if attempt < limit:
                attempt += 1
                delay = _retry_delay(attempt)
                _progress("thinking", "Model connection failed; retrying in %.1fs (attempt %d of %d)..." % (delay, attempt, limit))
                await asyncio.sleep(delay)
                continue
            _mark_smart_failure(provider)
            _health_failure(provider, cfg, ("timed out: " if timed_out else "[model unavailable] ") + str(exc), 0, exc)
            if timed_out and not _cfg_is_local(cfg):
                raise ModelUnavailable("[model unavailable] %s timed out (no answer in %ds)."
                                       % (provider or cfg.model, int(MODEL_TIMEOUT_S))) from exc
            raise ModelUnavailable(model_down_hint(cfg)) from exc
        except openai.OpenAIError as exc:
            _mark_smart_failure(provider)
            _health_failure(provider, cfg, "%s: %s" % (type(exc).__name__, exc), 0, exc)
            raise ModelUnavailable("[model error] %s: %s" % (type(exc).__name__, exc)) from exc


# Providers whose server refused response_format (learned this session).
CONSTRAINED_REFUSED: set = set()


_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)

# Pacing: how long one request may wait for a free slot under a provider's per-minute cap.
RATE_PACE_MAX_S = float(os.getenv("LOKI_RATE_PACE_MAX_S", "75") or 75)
# DeepSeek on NVIDIA NIM: thinking off for agent work (fast, light on the per-minute cap, and the
# tool loop never has to carry reasoning back); "high"/"max" turns it on for hard tasks.
NVIDIA_THINKING = str(os.getenv("LOKI_NVIDIA_THINKING", "off")).strip().lower()
LAST_REASONING: list = []   # the last few hidden-reasoning texts (shown as "thinking", never in history)


def _is_deepseek_nim(provider: str, cfg) -> bool:
    model = str(getattr(cfg, "model", "") or "").lower()
    url = str(getattr(cfg, "base_url", "") or "")
    return "deepseek" in model and (provider == "nvidia" or "integrate.api.nvidia.com" in url)


# Streaming (owner's Mac, 2026-10-18: NVIDIA "did not answer (The read operation timed out)" on every long turn).
# Unstreamed, the server sends nothing until the whole answer is written - a long answer at the free tier's speed is
# longer than LOKI_MODEL_TIMEOUT, so it timed out and was retried. Streamed, the timeout is the silence between two
# chunks, so a slow-but-working answer is never cut off. LOKI_STREAM_MODELS: auto (DeepSeek on NVIDIA NIM, where it
# was seen) | remote (every cloud provider) | off.
STREAM_MODELS = os.getenv("LOKI_STREAM_MODELS", "auto").strip().lower()


def _stream_for(provider: str, cfg) -> bool:
    if STREAM_MODELS in ("off", "0", "false", "no") or _cfg_is_local(cfg) or str(cfg.base_url).startswith(CLI_AGENT_PREFIX):
        return False
    return STREAM_MODELS in ("remote", "on", "all") or _is_deepseek_nim(provider, cfg)


class _Obj(types.SimpleNamespace):
    """A streamed reply in the shape the rest of LOKI reads from openai's objects (attributes + model_dump)."""

    def model_dump(self, **_kw):
        def plain(v):
            if isinstance(v, _Obj):
                return {k: plain(x) for k, x in vars(v).items() if x is not None}
            if isinstance(v, list):
                return [plain(x) for x in v]
            return v
        return plain(self)


async def _streamed_request(client, sent: dict):
    """client.chat.completions.create(stream=True) put back together as one completion."""
    stream = await client.chat.completions.create(**dict(sent, stream=True))
    content, reasoning, calls, usage, finish = [], [], {}, None, None
    async for chunk in stream:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        for choice in getattr(chunk, "choices", None) or []:
            finish = getattr(choice, "finish_reason", None) or finish
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            if getattr(delta, "content", None):
                content.append(str(delta.content))
            extra = getattr(delta, "model_extra", None) or {}
            for field in ("reasoning_content", "reasoning"):
                value = getattr(delta, field, None) or (extra.get(field) if isinstance(extra, dict) else None)
                if value:
                    reasoning.append(str(value))
            for tc in getattr(delta, "tool_calls", None) or []:
                index = getattr(tc, "index", None)
                slot = calls.setdefault(len(calls) if index is None else int(index),
                                        {"id": "", "name": "", "arguments": ""})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    slot["name"] += getattr(fn, "name", None) or ""
                    slot["arguments"] += getattr(fn, "arguments", None) or ""
    tool_calls = [_Obj(id=calls[i]["id"] or "call_%d" % i, type="function",
                       function=_Obj(name=calls[i]["name"], arguments=calls[i]["arguments"] or "{}"))
                  for i in sorted(calls)] or None
    message = _Obj(role="assistant", content="".join(content) or None, tool_calls=tool_calls,
                   reasoning_content="".join(reasoning) or None)
    if not (content or calls or reasoning):
        return _Obj(choices=[], usage=usage)
    return _Obj(choices=[_Obj(index=0, message=message, finish_reason=finish or ("tool_calls" if tool_calls else "stop"))],
                usage=usage, model=sent.get("model", ""))


def _provider_kwargs(provider: str, cfg, kwargs: dict) -> dict:
    """Per-provider request fields (a copy): DeepSeek on NIM takes its thinking switch in
    chat_template_kwargs (build.nvidia.com's own example)."""
    if not _is_deepseek_nim(provider, cfg):
        return kwargs
    extra = dict(kwargs.get("extra_body") or {})
    extra.pop("think", None)
    thinking = NVIDIA_THINKING not in ("off", "0", "false", "no", "")
    tmpl: dict = {"thinking": thinking}
    if thinking:
        tmpl["reasoning_effort"] = "max" if NVIDIA_THINKING == "max" else "high"
    extra["chat_template_kwargs"] = tmpl
    return dict(kwargs, extra_body=extra)


def split_reasoning(content, reasoning=None) -> tuple:
    """(answer, reasoning): the reasoning a model returned in reasoning_content / reasoning, or
    as <think>...</think> inside the answer, taken out of the answer."""
    text = content if isinstance(content, str) else ("" if content is None else str(content))
    found = [str(reasoning)] if reasoning else []
    if "think>" in text.lower():
        found += [m.group(0)[7:-8].strip() for m in _THINK_RE.finditer(text)]
        text = _THINK_RE.sub("", text)
        low = text.lower()
        if "</think>" in low:   # the opening tag was in the template: everything before it is reasoning
            at = low.rindex("</think>")
            found.append(text[:at].replace("<think>", "").strip())
            text = text[at + len("</think>"):]
        text = text.replace("<think>", "").replace("</think>", "").strip()
    return text, "\n".join(f for f in found if f).strip()


def _take_reasoning(response, provider: str, cfg):
    """A remote model's hidden reasoning (DeepSeek's reasoning_content, <think> blocks) is shown as
    progress and dropped from the message: it never lands in the history (it would be re-sent every
    turn, and DeepSeek refuses some requests that carry it back). Local models keep the old
    behaviour (an empty answer is recovered from their reasoning)."""
    if provider in LOCAL_PROVIDERS or provider in LOCAL_SERVERS or (not provider and _cfg_is_local(cfg)):
        return response
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return response
    extra = getattr(message, "model_extra", None)
    raw = None
    for field in ("reasoning_content", "reasoning"):
        value = extra.get(field) if isinstance(extra, dict) else None
        if value is None:
            value = getattr(message, field, None)
        if value and raw is None:
            raw = value
        if isinstance(extra, dict):
            extra.pop(field, None)
        try:
            if getattr(message, field, None) is not None:
                setattr(message, field, None)
        except Exception:  # noqa: BLE001
            pass
    original = getattr(message, "content", None)
    content, reasoning = split_reasoning(original, raw)
    if reasoning or (isinstance(original, str) and content != original):
        try:
            message.content = content
        except Exception:  # noqa: BLE001
            pass
    if reasoning:
        LAST_REASONING.append(reasoning[:4000])
        del LAST_REASONING[:-5]
        _progress("thinking", "%s thought: %s" % (provider or "the model", " ".join(reasoning.split())[:240]))
    return response


def _small_model_kwargs(kwargs: dict, cfg) -> dict:
    """Qwen3 on a local server: the '/no_think' soft switch on the system message (the
    `think: false` body field is not honoured by every OpenAI-compatible endpoint). Without it
    qwen3:8b often spends the whole reply thinking and returns an empty answer - the
    "model returned an empty reply" failures. A copy; the conversation is not changed."""
    name = str(getattr(cfg, "model", "")).lower()
    # Qwen3 / Qwen3.5 family, and Bonsai 2 (PrismML's ternary Qwen3.5) which thinks the same way
    if not _cfg_is_local(cfg) or not any(k in name for k in ("qwen3", "bonsai")):
        return kwargs
    msgs = list(kwargs.get("messages") or [])
    if msgs and msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
        if "/no_think" not in msgs[0]["content"]:
            msgs[0] = dict(msgs[0], content=msgs[0]["content"] + "\n\n/no_think")
            return dict(kwargs, messages=msgs)
    return kwargs


def _salvage_reply(response, kwargs: dict):
    """Small models often write the tool call as text (a ```json block, a bare object, a
    <tool_call>) instead of calling it, and leave <think> tags in the answer. Turn such text
    into a real call, so the job acts instead of narrating; drop the think tags."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return response
    content = getattr(message, "content", None)
    if isinstance(content, str) and "think>" in content.lower():
        content = _THINK_RE.sub("", content).replace("</think>", "").replace("<think>", "").strip()
        try:
            message.content = content
        except Exception:  # noqa: BLE001
            pass
    if kwargs.get("tools") and not getattr(message, "tool_calls", None) and content and ("{" in content or "DSML" in content.upper()):
        names = [((t.get("function") or t).get("name")) for t in kwargs["tools"] if isinstance(t, dict)]
        names += [r for r in conductor.ROLES if "conductor" in names]   # "image" -> conductor(role=image)
        response = tool_harness.attach(response, names)
    return response


def _cfg_is_local(cfg) -> bool:
    url = str(getattr(cfg, "base_url", "") or "")
    return (not url.startswith(CLI_AGENT_PREFIX)
            and any(h in url for h in ("11434", "127.0.0.1", "localhost", "[::1]")))


def _use_constrained(provider: str, cfg) -> bool:
    """Constrained decoding for this request? LOKI_CONSTRAINED_TOOLS=auto|on|off.

    auto (default): local servers that are in prompted-tools mode (no native tool calling)
    on:             every local server, instead of its native tool calling too
    Never for cloud providers (many reject or bill json_schema differently).
    """
    mode = tool_guard.constrained_mode()
    if mode == "off" or not _cfg_is_local(cfg):
        return False
    if (provider or cfg.base_url) in CONSTRAINED_REFUSED:
        return False
    return mode == "on" or tool_harness.configured(provider)


async def _constrained_request(client, kwargs: dict):
    """One step as constrained JSON, returned as an ordinary response with tool_calls."""
    tools = kwargs.get("tools") or []
    prompted = tool_harness.prepare(kwargs)
    known = prompted.pop("_prompted_tools", [])
    msgs = prompted.get("messages") or []
    if msgs and msgs[0].get("role") == "system":
        msgs[0] = dict(msgs[0], content=str(msgs[0].get("content") or "") + "\n\n" + tool_guard.CONSTRAINED_PROMPT)
    prompted["response_format"] = tool_guard.constrained_format(tools)
    response = await client.chat.completions.create(**prompted)
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError):
        return response
    calls, text = tool_guard.decode_constrained(message.content or "", known)
    if calls:
        message.content = "\n".join("<tool_call>%s</tool_call>" % json.dumps(
            {"name": name, "arguments": args}, ensure_ascii=False) for name, args in calls)
        return tool_harness.attach(response, known)
    message.content = text
    return response


def _json_object_spans(text: str) -> list:
    """Every balanced {...} object in a string (nesting handled; braces inside strings -
    the CSS and JS of a write_file call - do not count). A last object the model left
    unclosed at the very end of its reply is closed (tool_guard.close_truncated)."""
    spans = tool_guard.json_object_spans(text)
    tail = text.rfind('{"name"')
    if tail >= 0 and not any(text[tail:].startswith(sp) for sp in spans):
        end = text.rfind("}")
        closed = tool_guard.close_truncated(text[tail:end + 1]) if end > tail else None
        if closed:
            spans.append(closed)
    return spans


_partial_call = ""     # a reply that stopped in the middle of a text tool call
_partial_rounds = 0


def _unfinished_call(content: str) -> bool:
    """True when the text ends inside a tool call the model was writing ({"name": ...
    with no complete object after it)."""
    tail = (content or "").rfind('{"name"')
    if tail < 0:
        return False
    return not tool_guard.json_object_spans(content[tail:]) and tool_guard.close_truncated(content[tail:].rstrip("` \n")) is None


def _recover_text_tool_calls(content: str) -> list:
    """Recover tool calls a model wrote as TEXT instead of real tool_calls.

    Some models (e.g. qwen2.5-coder via Ollama) print
    {"name": "list_files", "arguments": {"path": "."}} into the message body and
    never emit a structured call, which used to stall the agent. Only names that
    match a real tool are accepted, so ordinary JSON in a reply is ignored.
    """
    known = set(LOCAL_TOOLS) | set(mcp_sessions)
    if content and "{" not in content and "(" in content:
        # Calls written as code: write_file(path="a.txt", content="hi").
        return tool_guard.parse_function_syntax(content, known)
    if not content or "{" not in content or "name" not in content:
        return []
    calls = []
    for blob in _json_object_spans(content):
        data = tool_guard.repair_json(blob)   # tolerates single quotes, trailing commas, fences
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("function"), dict):
            data = data["function"]
        name = data.get("name") or data.get("tool")
        name = tool_guard.resolve_name(name, known) if isinstance(name, str) else ""
        if not name:
            continue
        args = data.get("arguments", data.get("parameters", data.get("args", {})))
        if isinstance(args, str):
            args = tool_guard.repair_json(args) or {}
        calls.append((name, args if isinstance(args, dict) else {}))
    return calls


USAGE = usage.Ledger(DATA_DIR / "usage.jsonl")
LAST_USAGE: list = []   # entries for the current request, read by the bridge


def _record_usage(response, kwargs: dict, cfg, started: float) -> None:
    """Add one model call to the credits ledger; never fatal."""
    try:
        meta = getattr(response, "usage", None)
        tin = getattr(meta, "prompt_tokens", None) if meta is not None else None
        tout = getattr(meta, "completion_tokens", None) if meta is not None else None
        message = response.choices[0].message
        out_chars = len(message.content or "") + sum(len(str(getattr(c.function, "arguments", "")))
                                                     for c in (message.tool_calls or []))
        entry = USAGE.record(active_model_name(), cfg.model, tin, tout,
                             int((time.monotonic() - started) * 1000),
                             prompt_chars=usage.messages_chars(kwargs.get("messages", [])) +
                             len(json.dumps(kwargs.get("tools", []))),
                             output_chars=out_chars)
        hit = context_budget.cached_tokens(meta)
        if hit:
            entry["cached"] = hit
        if MASK_STATS.get("saved_chars"):
            entry["masked_chars"] = MASK_STATS["saved_chars"]
        LAST_USAGE.append(entry)
        _progress("usage", usage.line(entry))
        if "11434" in cfg.base_url:
            # Keep the model loaded between turns (Ollama unloads it after 5 idle minutes).
            threading.Thread(target=model_setup.keep_warm, args=(cfg.model,), daemon=True).start()
    except Exception:
        pass


async def _summarize_for_condenser(summary_messages: list) -> str:
    """One model call that writes the condenser's state summary (no tools)."""
    provider = active_model_name()
    cfg = MODELS[provider]
    kwargs = {"model": cfg.model, "messages": summary_messages,
              "max_tokens": int(os.getenv("LOKI_CONDENSE_TOKENS", "1500"))}
    if "11434" in cfg.base_url or "ollama" in cfg.api_key:
        kwargs["extra_body"] = {"think": False}
    started = time.monotonic()
    response = await _model_request(make_client(), kwargs, cfg, provider)
    _record_usage(response, kwargs, cfg, started)
    return str(response.choices[0].message.content or "")


# The condensed VIEW of the conversation (OpenHands keeps every event and condenses only what the
# model sees). LOKI's `messages` is also the chat history the window shows and saves, so it is
# never cut: the model gets head + one summary + the recent tail, cached until the history grows
# past the limits again (then the old summary is folded into a new one - a rolling summary).
_CONDENSE_CACHE: dict = {}


def _history_sig(items: list) -> str:
    import hashlib  # pylint: disable=import-outside-toplevel
    h = hashlib.sha1()
    for m in items:
        if isinstance(m, dict):
            h.update(str(m.get("role", "")).encode())
            h.update(str(m.get("content", ""))[:200].encode("utf-8", "replace"))
            h.update(str(m.get("tool_call_id", "")).encode())
    return h.hexdigest()


MASK_STATS: dict = {"turns": 0, "masked": 0, "saved_chars": 0}


def _masked(msgs: list) -> list:
    """Old tool results stubbed for the model (engine/context_budget.py - observation masking, in cache-friendly
    batches); the history itself keeps everything."""
    st = context_budget.settings()
    if not st["on"]:
        return msgs
    view, stats = context_budget.mask(msgs, keep=st["keep"], step=st["step"], min_chars=st["min_chars"])
    MASK_STATS["turns"] += 1
    MASK_STATS["masked"] = stats["masked"]
    MASK_STATS["saved_chars"] = stats["saved_chars"]
    return view


async def _model_view(requested: bool = False) -> list:
    """What the model is sent: the conversation with old tool output masked, condensed when still too long."""
    base = _masked(messages)
    if not condenser.enabled() or len(messages) < 6:
        return base
    max_messages, max_chars = condenser.limits(local=_is_local_model())
    if MAX_CONTEXT_MESSAGES > 0:
        max_messages = min(max_messages, MAX_CONTEXT_MESSAGES) if max_messages else MAX_CONTEXT_MESSAGES
    cache = _CONDENSE_CACHE
    view = base
    if cache and cache.get("end", 0) <= len(messages) and cache.get("sig") == _history_sig(messages[:cache["end"]]):
        view = base[:cache["start"]] + [cache["note"]] + base[cache["end"]:]
    elif cache:
        cache.clear()
    if not requested and not condenser.reasons(view, max_messages, max_chars):
        return view
    _progress("thinking", "The conversation is long; summarizing the older part so the model keeps the thread...")
    work = list(view)
    try:
        out = await condenser.condense(work, _summarize_for_condenser, max_messages, max_chars,
                                       keep_first=1, requested=requested)
    except Exception as exc:  # noqa: BLE001 - condensing must never be why a task stops
        print("  [condenser] skipped: %s" % exc)
        return view
    if not out.get("condensed"):
        return view

    def to_history(index: int) -> int:     # a view index -> the same message's index in `messages`
        if cache and index > cache["start"]:
            return index - cache["start"] - 1 + cache["end"]
        return index
    hist_end = to_history(out["end"])
    cache.clear()
    cache.update({"start": out["start"], "end": hist_end, "note": out["note"],
                  "sig": _history_sig(messages[:hist_end])})
    CONDENSE_STATS["runs"] += 1
    CONDENSE_STATS["forgot"] += out["forgot"]
    CONDENSE_STATS["fallback"] += 1 if out.get("how") == "fallback" else 0
    _progress("thinking", "Condensed %d older messages into a summary for the model (%s); the history is kept."
              % (out["forgot"], out.get("how")))
    return work


async def agent_turn(force_tool: bool = False) -> str:
    cfg = MODELS[active_model_name()]
    client = make_client()
    # Refresh ONCE per request, never between turns: a tool list that changes mid
    # conversation invalidates prompt caching and can push the request past a
    # provider's limit. Guarded - this is an optimisation, not a requirement.
    try:
        await refresh_mcp_tools()
    except Exception:
        pass
    started = time.monotonic()
    turns = 0
    prompted_forced = False
    while True:
        if _cancel_event.is_set():
            raise BudgetExhausted("cancelled by the user")
        _check_job_deadline()
        if REQUEST_DEADLINE_S > 0 and time.monotonic() - started > REQUEST_DEADLINE_S:
            raise BudgetExhausted("hit the %ds time budget" % int(REQUEST_DEADLINE_S))
        if MAX_TURNS_PER_REQUEST > 0 and turns >= MAX_TURNS_PER_REQUEST:
            raise BudgetExhausted("hit the %d-turn budget" % MAX_TURNS_PER_REQUEST)
        if HARD_MAX_TURNS > 0 and turns >= HARD_MAX_TURNS:
            raise BudgetExhausted("hit the %d-turn safety ceiling (LOKI_HARD_MAX_TURNS)" % HARD_MAX_TURNS)
        if HARD_DEADLINE_S > 0 and time.monotonic() - started > HARD_DEADLINE_S:
            raise BudgetExhausted("hit the %ds safety ceiling (LOKI_HARD_DEADLINE)" % int(HARD_DEADLINE_S))
        turns += 1
        _trim_context()
        view = await _model_view()
        _progress("thinking", "Turn %d: asking the model..." % turns)
        globals()["_REQUEST_HINT"] = next((str(m.get("content") or "")[:2000].lower() for m in reversed(view)
                                            if isinstance(m, dict) and m.get("role") == "user"
                                            and isinstance(m.get("content"), str)
                                            and not str(m.get("content")).lstrip().startswith("<tool_response>")), "")
        # Thinking models (Gemini 3.x) spend tokens reasoning before answering, so
        # give them headroom or the tool call gets truncated away.
        kwargs = {"model": cfg.model, "messages": view, "tools": model_tool_schemas(),
                  "max_tokens": int(os.getenv("LOKI_MAX_TOKENS", "8192"))}
        if CAPABILITIES.is_enabled("headroom"):
            # Headroom compresses a copy; the conversation itself is never rewritten.
            kwargs["messages"], _saved = conductor.compress_messages(list(view), cfg.model)
            if _saved:
                _progress("thinking", _saved)
        if "11434" in cfg.base_url or "ollama" in cfg.api_key:
            # Qwen3 family: disable extended thinking so the model acts instead of
            # writing long reasoning prose that never calls a tool.
            kwargs["extra_body"] = {"think": False}
        if force_tool:
            kwargs["tool_choice"] = "required"
        # A limit is not a failure: mark the provider used-up and continue this SAME
        # turn on the next provider rather than ending the run.
        switches = 0
        condensed_for_error = False
        waited = 0.0
        _t0 = time.monotonic()
        while True:
            # Resolve the provider BEFORE the request, so a failure is pinned on the
            # provider that actually failed (re-resolving afterwards names the next one).
            provider = active_model_name()
            if is_metered(provider) and paid_spent_today() >= DAILY_USD_LIMIT:
                raise BudgetExhausted(
                    "hit the daily paid budget: $%.2f spent in the last 24 hours (limit $%.2f, "
                    "LOKI_DAILY_USD_LIMIT). Use a free provider, or raise the limit." % (
                        paid_spent_today(), DAILY_USD_LIMIT))
            if PAID_MAX_CALLS > 0 and is_metered(provider) and _paid_calls() >= PAID_MAX_CALLS:
                raise BudgetExhausted(
                    "hit the paid-provider budget: %d calls to metered providers this request "
                    "(%s). Raise LOKI_PAID_MAX_CALLS, or use a free provider." % (
                        _paid_calls(), usage_summary()))
            try:
                response = await _model_request(client, kwargs, cfg, provider)
                _record_usage(response, kwargs, cfg, _t0)
                _record_request_usage(provider, response)
                speed_watch.since(_t0, "model_call", provider)   # speed watch (E6)
                break
            except ModelUnavailable as exc:
                size_like = condenser.is_context_error(str(exc)) or _maybe_size_error(
                    exc, kwargs.get("messages"), kwargs.get("tools"))
                if size_like and not condensed_for_error:
                    _progress("thinking", "The request was too big for %s; condensing the conversation and "
                              "trying again..." % (provider or "the model"))
                    # The provider says the conversation is too long for it: condense now (a hard
                    # request, as in OpenHands) and send the same turn again.
                    smaller = await _model_view(requested=True)
                    if len(smaller) < len(kwargs["messages"]):
                        condensed_for_error = True
                        kwargs["messages"] = smaller
                        continue
                if switches >= len(SMART_ORDER) or not (should_fail_over(
                        exc, model_name in AUTO_ROUTING_MODES) or (size_like and model_name in AUTO_ROUTING_MODES)):
                    raise
                reason = failover_reason(exc)
                if _is_rate_limit(exc):
                    _RATE_LIMITED[provider] = time.monotonic()
                target = failover_target(provider)
                if not target and _RATE_LIMITED and waited < RATE_LIMIT_WAIT_S:
                    pause = min(RATE_LIMIT_COOLDOWN_S, RATE_LIMIT_WAIT_S - waited)
                    _progress("thinking", "Every provider is busy or spent; %s hit a rate limit, so "
                              "waiting %ds for it to recover." % (", ".join(sorted(_RATE_LIMITED)), int(pause)))
                    await asyncio.sleep(pause)
                    waited += pause
                    revive_rate_limited()
                    nxt = active_model_name()
                    target = nxt if provider_configured(nxt) and nxt not in _SMART_FAILED else ""
                ROUTE_TRACE.append({"provider": provider, "reason": reason,
                                    "next": target or "", "error": redact_secrets(short_error(str(exc), 160))})
                if not target:
                    raise
                switches += 1
                client = make_client()
                cfg = MODELS[active_model_name()]
                kwargs["model"] = cfg.model
                kwargs.pop("extra_body", None)
                if "11434" in cfg.base_url or "ollama" in cfg.api_key:
                    kwargs["extra_body"] = {"think": False}
                _progress("thinking", "Cannot use %s (%s) - switched to %s and continuing."
                    % (provider, reason, target))
        message = response.choices[0].message
        global _last_turn_had_tools
        _last_turn_had_tools = bool(message.tool_calls)
        if not message.tool_calls:
            content = message.content or ""
            if not content.strip():
                # Some local models finish a turn with only hidden reasoning; recover it.
                content = getattr(message, "reasoning", None) or ""
            global _partial_call, _partial_rounds
            if _partial_call:
                # the previous reply stopped in the middle of a tool call: this one carries on
                content = _partial_call + content
                _partial_call = ""
            recovered = _recover_text_tool_calls(content)
            if not recovered and _unfinished_call(content) and _partial_rounds < 3:
                # Cut off mid-call (the output limit, a long write_file): keep what came and
                # ask for the rest, instead of losing the whole call and looping.
                _partial_rounds += 1
                _partial_call = content
                _progress("thinking", "The model's tool call was cut off; asking it to finish it.")
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": (
                    "Your last message stopped in the middle of the tool call. Continue it EXACTLY "
                    "from the last character you wrote: no repetition, no explanation, no code fence.")})
                continue
            _partial_rounds = 0
            if recovered:
                GUARD_STATS["repaired"] += len(recovered)  # calls the model wrote as text
                _progress("thinking", "Model wrote %d tool call(s) as text; running them." % len(recovered))
                messages.append({"role": "assistant", "content": content})
                notes = []
                for tool_name, tool_args in recovered[:4]:
                    print("  [tool:text] %s(%s)" % (tool_name, json.dumps(tool_args)[:200]))
                    tool_result = await call_tool(tool_name, tool_args)
                    _note_result(tool_result)
                    notes.append("Result of %s(%s):\n%s" % (tool_name, json.dumps(tool_args)[:200], tool_result))
                messages.append({"role": "user", "content": "\n\n".join(notes)})
                _last_turn_had_tools = True
                continue
            if not content.strip() and force_tool and not prompted_forced                     and not tool_harness.configured(provider):
                # A FORCED native tool call came back completely empty: this provider
                # cannot be trusted with a native tools list (weak local models do this
                # instead of calling a tool). Switch it to the prompted text harness for
                # the rest of this session and retry the turn as a text tool call.
                prompted_forced = True
                tool_harness.learn(provider)
                _progress("thinking", "%s gave nothing when a tool call was required; "
                          "using prompted tools for it." % provider)
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
            # A huge prose reply (a small model reciting a file or its reasoning) is kept short in the
            # history, so it cannot fill a small model's context for the rest of the task. The caller
            # still gets the whole reply (its DONE/BLOCKED line is read from it).
            messages.append({"role": "assistant", "content": _clip_reply(content)})
            return content
        messages.append(_as_dict(message))
        # Nudges wait until every tool result of this batch is in: a user message between an
        # assistant's tool calls and their results is rejected by most providers.
        batch_nudges: list = []
        for call in message.tool_calls:
            # The tool guard repairs the call's shape (bad JSON, near-miss tool name, a
            # number sent as a string) and, when it cannot, answers with one precise
            # sentence and the schema - what a small model needs to fix it next turn.
            fix = _guard_call(call.function.name, call.function.arguments)
            if not fix.ok:
                print("  [tool] %s rejected: %s" % (call.function.name, fix.error[:200]))
                GUARD_STATS["rejected"] += 1
                _note_result("error")
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": "error: %s" % fix.error})
                continue
            if fix.notes:
                GUARD_STATS["repaired"] += 1
                _progress("thinking", "Fixed the model's tool call: %s." % "; ".join(fix.notes))
            args = fix.args
            print("  [tool] %s(%s)" % (fix.name, json.dumps(args)[:200]))
            global _REQUEST_TOOL_CALLS
            _REQUEST_TOOL_CALLS += 1
            result = await call_tool(fix.name, args)
            _note_result(result)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": context_budget.cap_result(result)})
            # Break a loop where the model repeats an identical failing call forever.
            global _repeat_sig, _repeat_count
            signature = "%s|%s" % (fix.name, json.dumps(args, sort_keys=True)[:400])
            if "error" in str(result)[:80].lower():
                if signature == _repeat_sig:
                    _repeat_count += 1
                else:
                    _repeat_sig, _repeat_count = signature, 1
                if _repeat_count >= 3:
                    _repeat_count = 0
                    batch_nudges.append({"role": "user", "content": (
                        "You have now made this exact call %d times with identical arguments and it "
                        "keeps failing. Do NOT repeat it. Read the error text, then change approach: "
                        "use a different tool or different arguments, or do something simpler. If the "
                        "tool cannot do what you want, use write_file to author the file instead."
                    ) % 3})
            else:
                _repeat_sig, _repeat_count = "", 0

            # Jev loop detection: a rolling window of recent actions; every few tool
            # calls, ask Jev whether the agent is spinning without real progress.
            global _jev_loop_window
            _jev_loop_window.append("%s(%s) -> %s" % (
                fix.name, json.dumps(args)[:120], str(result)[:100]))
            if fix.name in MODIFYING and "error" not in str(result)[:80].lower():
                _jev_loop_window = []   # real progress - start a fresh window
            elif len(_jev_loop_window) > 16:
                del _jev_loop_window[:-16]
            if decisions.enabled_providers() and turns % JEV_LOOP_CHECK_EVERY == 0 and len(_jev_loop_window) >= 4:
                _spinning = await _jev_loop_nudge()
                if _spinning:
                    _jev_loop_window = []
                    _progress("thinking", "A decision provider flagged a likely loop (p=%s); nudging." % _spinning)
                    batch_nudges.append({"role": "user", "content": (
                        "You appear to be repeating the same approach without progress. Stop and "
                        "reassess: name what is blocking you, then try a materially different tool "
                        "or arguments, or reply 'BLOCKED: <reason>'. Do not repeat the last action."
                    )})
        # OpenHands stuck detection (stuck.py): the same call and result over and over, the same
        # failing call, or two calls taking turns. First time: a precise nudge. If it loops again
        # after that, the request stops honestly instead of burning turns.
        global _stuck_hits
        pattern = stuck.detect(messages) if STUCK_DETECTION else ""
        if pattern:
            _stuck_hits += 1
            if _stuck_hits >= STUCK_STOP_AFTER:
                content = ("BLOCKED: I was stuck in a loop (%s) and stopped instead of repeating it. %s"
                           % (pattern.replace("_", " "), stuck.MESSAGES.get(pattern, "")))
                _progress("thinking", "Stuck in a loop (%s) twice - stopping." % pattern)
                messages.extend(batch_nudges)
                messages.append({"role": "user", "content": "(LOKI stopped this loop.)"})
                messages.append({"role": "assistant", "content": content})
                return content
            _progress("thinking", "Looks stuck (%s); nudging the model to change approach." % pattern)
            batch_nudges = [{"role": "user", "content": stuck.advice(pattern)}]
        messages.extend(batch_nudges)


async def _finish_with_verification(answer: str, rounds: int) -> str:
    """Verify what this request wrote; send real errors back up to `rounds` times.

    Returns the answer with an honest verification line appended (or unchanged when
    nothing was written or verification is off). Never raises for a checker problem.
    """
    if not (VERIFY_ENABLED and _task_files):
        return answer
    try:
        report = await _verify_touched()
        attempts = 0
        while report["failed"] and attempts < rounds:
            attempts += 1
            _progress("thinking", "Verification found errors; asking the model to fix them (%d of %d)..."
                      % (attempts, rounds))
            messages.append({"role": "user", "content": verification_feedback(report)})
            answer = await agent_turn()
            report = await _verify_touched()
    except (ModelUnavailable, BudgetExhausted):
        raise
    except Exception as exc:
        return (answer or "").rstrip() + chr(10) * 2 + "Verification: could not run (%s)." % exc
    return (answer or "").rstrip() + chr(10) * 2 + verification_summary(report)


async def _run_agent(user_message: str) -> str:
    global _empty_nudges, _repeat_sig, _repeat_count, _jev_loop_window, _stuck_hits
    _empty_nudges = 0
    _stuck_hits = 0
    _repeat_sig, _repeat_count = "", 0
    _jev_loop_window = []
    ROUTE_TRACE.clear()
    REQUEST_USAGE.clear()
    _task_files.clear()
    messages.append({"role": "user", "content": user_message})
    global _task_ok_calls, _task_failed_calls
    _task_ok_calls = _task_failed_calls = 0
    try:
        answer = await agent_turn()
        # "It says it did it but it doesn't actually do it" (owner 2026-10-25): a reply that CLAIMS an action
        # with no tool behind it is never shown as done (_honest_reply).
        answer = await _honest_reply(user_message, answer)
        # A chat turn that changed files gets ONE bounded repair round on real errors -
        # cheap insurance against "I fixed it" when the script does not even compile.
        answer = await _finish_with_verification(answer, rounds=min(1, VERIFY_FIX_ROUNDS))
        save_history()
        return answer
    except ModelUnavailable:
        messages.pop()  # drop the stalled prompt so a retry starts clean
        raise
    except BudgetExhausted:
        save_history()
        raise


# ---------------------------------------------------------------------------
# Session 28: what tools/task_bench.py's scenarios showed the goal loop needed.
# ---------------------------------------------------------------------------
_task_ok_calls = 0        # tool calls in this task that did something (not an error or a refusal)
_task_failed_calls = 0    # tool calls that failed, were refused or rejected
JOB_DEADLINE_AT = 0.0     # time.monotonic() at which a background job must stop (0 = none)
MAX_REPLY_CHARS = int(os.getenv("LOKI_MAX_REPLY_CHARS", "24000") or 0)
_OUTCOME_ANYWHERE = re.compile(r"^\s*[*_`>#\s]*(DONE|BLOCKED)\**\s*[:\-]")
# A file a goal or a DONE line names: documents, code, data, media - not a domain (danas-bakery.com).
_FILE_NAME = re.compile(r"(?<![\w@/:.-])((?:[\w-]+[/\\])*[\w-]+\.(?:md|txt|py|json|html?|css|js|ts|tsx|jsx|csv|tsv|"
                        r"toml|ya?ml|xml|svg|png|jpe?g|gif|webp|mp3|wav|mp4|pdf|docx|xlsx|pptx|sql|sh|bat|ps1|ipynb|"
                        r"gd|tscn|rs|go|java|c|cpp|h|rb|php|ini|cfg|log))\b", re.I)


def reply_outcome(reply: str) -> str:
    """'done', 'blocked' or '': the reply's DONE/BLOCKED line. The first line as before ("Done:"
    in any case), or - a small model often explains first - a later line that starts with an
    upper-case DONE: / BLOCKED: (the last one wins)."""
    text = str(reply or "").strip()
    head = text.upper()
    if head.startswith("DONE"):
        return "done"
    if head.startswith("BLOCKED"):
        return "blocked"
    for line in reversed(text.splitlines()):
        m = _OUTCOME_ANYWHERE.match(line)
        if m:
            return m.group(1).lower()
    return ""


def _outcome_text(reply: str) -> str:
    """The DONE/BLOCKED line itself (for the checks below)."""
    for line in reversed(str(reply or "").strip().splitlines()):
        if _OUTCOME_ANYWHERE.match(line) or line.strip().upper().startswith(("DONE", "BLOCKED")):
            return line.strip()
    return ""


# ---- the honesty check for a chat turn (owner 2026-10-25: "it said it did it but I checked my repo and nothing
# was done. This has been the main issue with LOKI: it says but it doesn't actually do"). The window's chat path ran
# ONE model turn and showed whatever it said: a model that answered "Done! I created the repo ..." without calling a
# single tool was believed. Now: the request asks for an action + the reply claims it + no tool did anything ->
# pushed back once (do it with a tool, or say you cannot); still nothing -> the reply says plainly it was NOT done.
_ASKS_ACTION = re.compile(r"\b(make|create|write|build|commit|push|run|use|init|initiali[sz]e|install|delete|remove|move|"
                          r"rename|add|fix|upload|publish|set up|setup|generate|save|edit|change|update|clone|deploy|"
                          r"mkdir|copy|download|render|export)\b", re.I)
_CLAIMS_DONE = re.compile(r"(\b(i|i've|i have|i just|we|loki)\b[^.\n]{0,40}\b(created|made|wrote|written|committed|"
                          r"initiali[sz]ed|ran|executed|installed|saved|pushed|deleted|removed|moved|renamed|added|"
                          r"updated|built|generated|fixed|set up|uploaded|published|cloned|copied|downloaded|exported)\b"
                          r"|^\W*(done|all done|finished|success)\b|\bsuccessfully\b|\b(has|have) been (created|"
                          r"committed|made|written|saved|added|pushed|installed|initiali[sz]ed|generated)\b)", re.I | re.M)


def _claims_unbacked(request: str, reply: str) -> bool:
    """The request asks for an action, the reply says it was done, and no tool call this turn did anything."""
    text = str(reply or "")
    if not text.strip() or _task_ok_calls > 0 or is_conversational(request):
        return False
    return bool(_ASKS_ACTION.search(request or "") and _CLAIMS_DONE.search(text))


def _not_done_note(reply: str) -> str:
    why = ("every tool call failed or was refused" if _task_failed_calls
           else "the model answered in text without calling a single tool")
    mode = {"ask": "Ask", "plan": "Plan"}.get(AGENT_MODE)
    fix = ("LOKI is in %s mode, which cannot change anything - switch to Build and send it again." % mode if mode
           else "Nothing was changed on your computer. Send it again, or pick a model that calls tools "
                "(Settings > Connections shows which ones do).")
    return ("NOT DONE - LOKI checked: %s, so what the model said below did not happen. %s\n\n(What the model "
            "claimed: %s)" % (why, fix, " ".join(str(reply).split())[:400]))


async def _honest_reply(request: str, answer: str) -> str:
    if not _claims_unbacked(request, answer):
        return answer
    if AGENT_MODE == "build":
        _progress("thinking", "Checked: the reply says it was done, but no tool ran - asking it to really do it.")
        messages.append({"role": "user", "content": (
            "Self-check: your reply says it is done, but NO tool was called (or every call failed), so nothing "
            "actually happened on this computer. Do it now with your tools (bash / run_command for git and shell "
            "commands, write_file / edit_file for files), then report exactly what the tools returned. If you "
            "cannot, say plainly that it was not done and why.")})
        answer = await agent_turn(force_tool=True)
        if not _claims_unbacked(request, answer):
            return answer
    note = _not_done_note(answer)
    # the model must not remember a fake success either: every claim since this request is rewritten
    start = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], dict)
                  and messages[i].get("role") == "user" and messages[i].get("content") == request), 0)
    for i in range(start + 1, len(messages)):
        m = messages[i]
        if isinstance(m, dict) and m.get("role") == "assistant" and not m.get("tool_calls") \
                and _CLAIMS_DONE.search(str(m.get("content") or "")):
            messages[i] = {**m, "content": "(I claimed this was done, but no tool ran - it was NOT done.)"}
    if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "assistant":
        messages[-1] = {**messages[-1], "content": note}
    _progress("thinking", "Checked: still no tool behind the claim - told the owner it was NOT done.")
    return note


def _note_result(result) -> None:
    """Count one tool result as done-something or failed (a refusal, an error, a rejected call)."""
    global _task_ok_calls, _task_failed_calls
    head = str(result or "").lstrip()[:80].lower()
    failed_exit = bool(re.match(r"exit (-?[1-9]\d*)\b", head))     # run_command / bash: a non-zero exit failed
    if head.startswith(("error", "denied", "refused")) or "denied by loki" in head or failed_exit:
        _task_failed_calls += 1
    else:
        _task_ok_calls += 1


def _clip_reply(content: str) -> str:
    text = str(content or "")
    if MAX_REPLY_CHARS <= 0 or len(text) <= MAX_REPLY_CHARS:
        return text
    head, tail = MAX_REPLY_CHARS * 2 // 3, MAX_REPLY_CHARS // 3
    return "%s\n\n[... %d characters of this reply left out ...]\n\n%s" % (text[:head], len(text) - head - tail, text[-tail:])


def _check_job_deadline() -> None:
    if JOB_DEADLINE_AT and time.monotonic() > JOB_DEADLINE_AT:
        raise BudgetExhausted("hit the job's time limit (deadline)")


def _role_writes() -> bool:
    """False for a team agent whose role only reads and reports (tester, reviewer, researcher,
    browser tester): its DONE is a report, so 'nothing was written' is not premature."""
    if not JOB_ROLE:
        return True
    try:
        import team as _team  # pylint: disable=import-outside-toplevel
        spec = _team.ROLES.get(JOB_ROLE)
    except Exception:  # noqa: BLE001
        spec = None
    return True if spec is None else bool(spec.get("writes"))


def _file_exists_somewhere(name: str, limit: int = 4000) -> bool:
    """A file the goal or a DONE line names: at that path, or under that file name anywhere in the
    workspace (a model may put notes.md in docs/). Bounded walk; never raises."""
    clean = str(name).strip().strip("'\"`").replace("\\", "/")
    try:
        if resolve_in_workspace(clean).exists():
            return True
    except Exception:  # noqa: BLE001
        pass
    base = clean.rsplit("/", 1)[-1].lower()
    if any(str(p).replace("\\", "/").rsplit("/", 1)[-1].lower() == base for p in _task_files):
        return True
    seen = 0
    try:
        for root, dirs, files in os.walk(WORKSPACE):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "__pycache__", ".loki")]
            if any(f.lower() == base for f in files):
                return True
            seen += len(files) + 1
            if seen > limit:
                return False
    except OSError:
        return False
    return False


def _named_files(text: str) -> list:
    text = re.sub(r"\b\w+://\S+|\bwww\.\S+|\S+@\S+", " ", str(text or ""))
    out = []
    for name in _FILE_NAME.findall(text):
        name = name.strip("./").replace("\\", "/")
        if name and name not in out:
            out.append(name)
    return out


_OUTPUT_WORDS = {"write", "create", "save", "saved", "into", "as", "to", "named", "called", "produce", "export",
                 "generate", "draft", "build", "make", "add"}


def _goal_outputs(goal: str) -> list:
    """Files the goal asks to PRODUCE that are not there yet: a name right after write / create /
    save as / into / to ... ("summarize report.txt into summary.md" -> summary.md). A file the goal
    only mentions ("read AGENTS.md first") or one that exists already (an input) is not one."""
    text = re.sub(r"\b\w+://\S+|\bwww\.\S+|\S+@\S+", " ", str(goal or ""))
    out = []
    for m in _FILE_NAME.finditer(text):
        before = re.findall(r"[A-Za-z]+", text[max(0, m.start() - 40):m.start()].lower())[-3:]
        name = m.group(1).strip("./").replace("\\", "/")
        if _OUTPUT_WORDS.intersection(before) and name not in out and not _file_exists_somewhere(name):
            out.append(name)
    return out[:8]


_PICTURE_GOAL = re.compile(r"\b(make|draw|create|generate|paint|design|render)\b[^.?!]{0,60}\b(picture|image|logo|"
                           r"drawing|illustration|photo|artwork|poster|icon)s?\b", re.I)
_PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def _goal_wants_picture(goal: str) -> bool:
    """"Make a picture of a fox" - the work is a real picture file, not a text file next to one."""
    return bool(_PICTURE_GOAL.search(str(goal or ""))) and not re.search(r"\.(py|js|ts|html|css|gd)\b", str(goal))


def _made_picture() -> bool:
    return any(str(p).lower().endswith(_PICTURE_SUFFIXES) for p in _task_files)


def _partial_note() -> str:
    """What a stopped task leaves behind, for its result line."""
    files = [p for p in _task_files if p]
    if not files:
        return "Nothing was saved before it stopped."
    return "Partial work is kept in the workspace: %s." % ", ".join(files[-8:])


_NAMED_FILE = re.compile(r"(?<![\w@])[\w./\\-]*\w\.[A-Za-z][A-Za-z0-9]{0,5}\b")


def _goal_names_file(goal: str) -> bool:
    """True when the goal names a file to produce ("create notes/hello.txt"), so making
    only its folder is not done. Web addresses and e-mail addresses are not files."""
    text = re.sub(r"\b\w+://\S+|\bwww\.\S+|\S+@\S+|\b(?:e\.g|i\.e|etc|vs)\.", " ", goal)
    return bool(_NAMED_FILE.search(text))


def _local_chain_next(tried: set) -> dict:
    """The next installed, tool-capable local model to try (offline mix and match), or {} when
    none is left. Same weights under a different name (a loki-* copy) do not count as new."""
    try:
        models = model_setup.ollama_models() or []
    except Exception:  # noqa: BLE001 - choosing a model must never break a job
        return {}
    info = HARDWARE or {}
    return model_setup.next_installed(list(tried), models, float(info.get("budget_gb") or 0),
                                      LOCAL_STATE.get("version", "")) or {}


def _escalate_model(why: str) -> bool:
    """A job on the small local model is failing. FIRST try the next installed local model - stay
    offline and free (the owner: "if one model cant you need to figure out a way to mix and match
    all the offline and free ones"). Only when no other local model is left, carry on with the
    best free online model that is set up (never a paid one on its own). True when it switched."""
    global model_name
    if (not os.getenv("LOKI_JOB_ID") or active_model_name() != "local"
            or os.getenv("LOKI_NO_ESCALATE")):   # background jobs only (each is its own process)
        return False
    # 1) Another LOCAL model: keep working offline for free.
    if not os.getenv("LOKI_NO_LOCAL_CHAIN"):
        tried: set = globals().setdefault("_LOCAL_TRIED", set())
        tried.update({LOCAL_STATE.get("name") or "", os.environ.get("LOKI_LOCAL_MODEL", ""),
                      _model_of(active_model_name())})
        nxt = str(_local_chain_next(tried).get("name") or "")
        if nxt:
            tried.add(nxt)
            os.environ["LOKI_LOCAL_MODEL"] = nxt
            try:
                resolve_local(force=True)
            except Exception:  # noqa: BLE001 - if it will not resolve, fall through to the cloud
                pass
            else:
                _progress("thinking", "The local model is stuck (%s) - trying the next local model, %s "
                          "(staying offline and free)." % (why, LOCAL_STATE.get("name") or nxt))
                messages.append({"role": "user", "content": "A different local model takes over now. "
                                 "Continue the task from here with real tool calls, then reply "
                                 "DONE: <what you did> or BLOCKED: <why>."})
                return True
    # 2) No other local model fits: borrow the best free online one.
    if globals().get("_ESCALATED"):
        return False
    target = ""
    for candidate in routing_order(SMART_ORDER):
        if candidate == "local" or (provider_tier(candidate) == "paid" and not paid_allowed_automatically()):
            continue
        if candidate not in _SMART_FAILED and provider_configured(candidate):
            target = candidate
            break
    if not target:
        return False
    globals()["_ESCALATED"] = True
    model_name = target
    _progress("thinking", "No other local model fits (%s) - switching this task to %s." % (why, target))
    messages.append({"role": "user", "content": "A stronger model takes over now. Continue the task from "
                     "here with real tool calls, then reply DONE: <what you did> or BLOCKED: <why>."})
    return True


def _goal_needs_files(goal: str) -> bool:
    words = ("create", "add", "make", "build", "implement", "write", "system",
             "script", "scene", "setup", "set up", "configure", "fix", "update",
             "generate", "template", "controller", "player")
    text = goal.lower()
    return any(word in text for word in words)


_CONVERSATIONAL = re.compile(
    "^("
    "hi|hello|hey|yo|thanks|thank you|"
    "what|who|how|why|when|where|which|"
    "can you|could you|would you|do you|are you|"
    "is it|does it|tell me|explain|describe|show me|list what"
    ")",
    re.IGNORECASE,
)


def is_conversational(goal: str) -> bool:
    """True when this is a question or greeting, not a change to make.

    A question must be ANSWERED, not pursued. Sending one through the autonomous goal
    loop is what made "what do you do?" explore the project for dozens of turns and
    finally answer in the wrong language: the loop only stops at DONE/BLOCKED, and a
    question never produces either.
    """
    text: str = goal.strip()
    if not text or len(text) > 300:
        return False
    return bool(_CONVERSATIONAL.match(text)) or text.rstrip().endswith("?")


def _answer_only(goal: str) -> bool:
    """A question is answered, not pursued: the old rule, or a confident Laya 'answer'."""
    if is_conversational(goal):
        return True
    t = LAST_TRIAGE or {}
    return (t.get("source") == "laya" and t.get("route") == "answer"
            and (t.get("confidence") or 0) >= 0.7 and len(goal) <= 300)


async def _pursue_goal(goal: str) -> str:
    global _empty_nudges, _task_modified, _task_wrote_file, _repeat_sig, _repeat_count, _jev_loop_window, _stuck_hits
    global _task_ok_calls, _task_failed_calls
    _empty_nudges = 0
    _stuck_hits = 0
    _repeat_sig, _repeat_count = "", 0
    _jev_loop_window = []
    _task_modified = False
    _task_wrote_file = False
    _task_ok_calls = _task_failed_calls = 0
    ROUTE_TRACE.clear()
    REQUEST_USAGE.clear()
    _task_files.clear()
    todo_clear()  # stale items from earlier tasks derail the model
    print("  [goal] working on: %s" % goal)
    _progress("task", "Goal: %s" % goal[:200])
    if _answer_only(goal):
        # One turn, then stop. See is_conversational().
        messages.append({"role": "user", "content": (
            "The user asked you a QUESTION, not for a change to the project." + chr(10) +
            "Answer it directly in your reply. Do not create, edit, move or delete "
            "anything, and only call a tool if the answer genuinely needs one." + chr(10) * 2 +
            goal
        )})
        reply = await agent_turn()
        save_history()
        return reply.strip()
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
    verify_rejections = 0
    premature_done = 0
    # Files the goal asks for that are not there yet. Not for a team agent other than the builder:
    # its prompt quotes the whole team goal ("... as index.html"), which is the builder's to make.
    outputs = _goal_outputs(goal) if JOB_ROLE in ("", "builder") else []
    writes = _role_writes()
    wants_picture = _goal_wants_picture(goal) and JOB_ROLE in ("", "builder")
    in_job = bool(os.getenv("LOKI_JOB_ID"))
    pushed = {"no_action": 0, "done_line": 0, "blocked_untried": 0, "question": 0}
    while True:
        step += 1
        if GOAL_STEPS > 0 and step > GOAL_STEPS:
            _progress("done", "Reached the %d-step limit without finishing." % GOAL_STEPS)
            save_history()
            print("  [goal] hit the step limit without finishing")
            return "BLOCKED: reached the %d-step limit without finishing. %s" % (GOAL_STEPS, _partial_note())
        label = ("Step %d of %d..." % (step, GOAL_STEPS)) if GOAL_STEPS > 0 else ("Step %d..." % step)
        _progress("thinking", label)
        reply = await agent_turn(force_tool=force_next)
        force_next = False
        print(chr(10) + "[step %d] %s" % (step, reply) + chr(10))
        if reply.strip():
            _progress("assistant", reply.strip()[:300])
        if reply.strip().startswith("(the model stopped responding"):
            stalls += 1
            if stalls >= 2 and _escalate_model("it kept returning empty replies"):
                stalls = 0
                continue
            if stalls >= 2:
                # BLOCKED, not a plain sentence: a job that ends like this failed, and must say so
                # (it used to exit 0, so the job - and a team counting on it - looked finished).
                message = ("BLOCKED: the model returned empty replies repeatedly, so the task was halted. "
                           "It needs a stronger model (or try again). %s" % _partial_note())
                _progress("done", message)
                save_history()
                return message
        else:
            stalls = 0
        outcome = reply_outcome(reply)
        head = outcome.upper()
        missing_outputs = [n for n in outputs if not _file_exists_somewhere(n)] if outcome == "done" and writes else []
        if outcome == "done" and writes and wants_picture and not _made_picture():
            missing_outputs.append("the picture (an image file made with conductor(role='image'))")
        if head.startswith("DONE") and writes and ((_goal_needs_files(goal) and (
                not _task_modified or (not _task_wrote_file and _goal_names_file(goal)))) or missing_outputs):
            premature_done += 1
            if premature_done > PREMATURE_DONE_LIMIT and _escalate_model("it kept saying DONE without doing it"):
                premature_done = 0
                continue
            if premature_done > PREMATURE_DONE_LIMIT:
                message = ("BLOCKED: the model kept saying DONE without %s (%d times); stopped instead of "
                           "looping. Try a stronger model." % (
                               ("making " + ", ".join(missing_outputs)) if missing_outputs else "changing any file",
                               premature_done))
                _progress("done", message)
                save_history()
                return message
            _progress("thinking", "Checked: %s - not accepting DONE." % (
                ("%s does not exist yet" % ", ".join(missing_outputs)) if missing_outputs else "nothing was written yet"))
            if missing_outputs and wants_picture and not _made_picture():
                what = ("Your 'DONE' is premature: the task asks for a picture and no picture was made. Make it "
                        "with conductor(role='image', task='<what to draw>') - never write a description into "
                        "a file. If the image maker is not available, reply 'BLOCKED: <what is needed>'.")
            elif missing_outputs:
                what = ("Your 'DONE' is premature: the task asks for %s, which does not exist yet - "
                        "a summary or a draft in your reply is not the file. Write it with write_file now "
                        "(or make it with the right tool), check it, and only then reply 'DONE'."
                        % ", ".join(missing_outputs))
            else:
                what = ("Your 'DONE' is premature: NO file was created or changed during this "
                        "task, so the goal is not actually done. Do it now with a real tool call: "
                        "a picture -> conductor(role='image', task='<what to draw>'); a document or "
                        "code -> write_file / edit_file; research -> conductor(role='research', ...). "
                        "Never write a description into an image file. Check the result, and only "
                        "then reply 'DONE'.")
            messages.append({"role": "user", "content": what})
            force_next = True
            continue
        if head.startswith("DONE") and not _task_modified and _task_ok_calls == 0 and not pushed["no_action"]:
            # No action of this task did anything (none was tried, or every one failed or was
            # refused), and still "DONE": the final self-check says no once (a refused deploy is not
            # a deploy). A second DONE is accepted - some tasks really need no tool.
            pushed["no_action"] += 1
            why = "every tool call failed or was refused" if _task_failed_calls else "no tool was used"
            _progress("thinking", "Checked: %s - not accepting DONE yet." % why)
            messages.append({"role": "user", "content": (
                "Self-check before DONE: nothing was actually done in this task - %s (see above). Do not "
                "claim it is done. Do it with a tool call that works, or reply 'BLOCKED: <exactly what you "
                "need from the owner>' (a key, a permission, a file, an approval). If it truly needed no "
                "action, reply DONE again and say why." % why)})
            continue
        named = [n for n in _named_files(_outcome_text(reply)) if not _file_exists_somewhere(n)] \
            if head.startswith("DONE") else []
        if named and not pushed["done_line"]:
            # The DONE line names a file that is not there: the summary would mislead the owner.
            pushed["done_line"] += 1
            _progress("thinking", "Checked: the DONE line names %s, which does not exist." % ", ".join(named))
            made = ", ".join(_task_files[-6:]) or "no files"
            messages.append({"role": "user", "content": (
                "Self-check before DONE: your DONE line names %s, which does not exist in the workspace "
                "(this task changed: %s). Finish that file if it is still missing, or reply DONE again "
                "naming exactly what you made." % (", ".join(named), made))})
            continue
        if head.startswith("DONE") and VERIFY_ENABLED and _task_files:
            # The model says DONE; check the files it actually wrote before believing it.
            report = await _verify_touched()
            if report["failed"] and verify_rejections < VERIFY_FIX_ROUNDS:
                verify_rejections += 1
                _progress("thinking", "Checked: %d changed file(s) have errors - not accepting DONE."
                          % len(report["failed"]))
                messages.append({"role": "user", "content": verification_feedback(report)})
                continue
            save_history()
            return reply.strip() + chr(10) * 2 + verification_summary(report)
        if head.startswith("BLOCKED") and _task_ok_calls + _task_failed_calls == 0 and not pushed["blocked_untried"]:
            # BLOCKED before trying a single tool is a guess ("I can't read PDFs", "the Builder role is
            # unavailable"). Once: look first, then say BLOCKED with what is really missing.
            pushed["blocked_untried"] += 1
            _progress("thinking", "Checked: BLOCKED without trying anything - asking it to try first.")
            messages.append({"role": "user", "content": (
                "You have not tried anything yet: no tool was called in this task. Try first - look at the "
                "workspace (list_tree, read_file) and use your tools. If a real tool result then shows you "
                "cannot do it, reply 'BLOCKED: <exactly what you need from the owner>'.")})
            continue
        if head.startswith("BLOCKED") and _escalate_model("it gave up: " + _outcome_text(reply)[8:90]):
            continue   # a small model's BLOCKED is often a guess ("Builder's role unavailable")
        if head.startswith("DONE") or head.startswith("BLOCKED"):
            save_history()
            return reply.strip()
        if in_job and not _last_turn_had_tools and reply.strip().endswith("?") and pushed["question"] < 2:
            # A question in a background job: nobody is there to answer it (a small model asks again
            # and again). Tell it to choose and say what it chose.
            pushed["question"] += 1
            _progress("thinking", "The model asked a question; nobody can answer in a background job.")
            messages.append({"role": "user", "content": (
                "Nobody can answer questions during a background job. Make a reasonable assumption, do the "
                "task with it, and state the assumption in your final 'DONE: ...' line.")})
            continue
        if _last_turn_had_tools:
            idle = 0
        else:
            idle += 1
            if idle >= 12 and _escalate_model("it stopped calling tools"):
                idle = 0
                continue
            if idle >= 12:
                message = ("BLOCKED: the model stopped calling tools after several nudges, so the task is not "
                           "finished. Say 'continue' to resume, or use a stronger model. %s" % _partial_note())
                _progress("done", message)
                save_history()
                return message
            # Stalled in prose. Do NOT inject a "user" nudge - the model just echoes
            # it and loops. Silently force a tool call on the next turn instead.
            force_next = True


# ---------------------------------------------------------------------------
# Every request leaves a record (experience.py), so Loki can learn from outcomes.
# ---------------------------------------------------------------------------

def _start_request() -> tuple:
    global _REQUEST_TOOL_CALLS
    _REQUEST_TOOL_CALLS = 0
    MEMORY_BUDGET.reset()
    LAST_RECALL.clear()
    LAST_SKILLS.clear()
    LAST_LEARNED.clear()
    LAST_NOTED.clear()
    _GUARD_AT_START["repaired"] = GUARD_STATS["repaired"]
    _GUARD_AT_START["rejected"] = GUARD_STATS["rejected"]
    _LAST_VERIFY.clear()
    try:
        back = revive_local() if model_name in AUTO_ROUTING_MODES else []
    except Exception:  # noqa: BLE001
        back = []
    if back:
        _progress("thinking", "Local model back in use: %s answers again." % ", ".join(back))
    return time.time(), len(messages)


def _record_experience(kind: str, goal: str, status: str, started: float, start_index: int) -> None:
    """Log the request; keep its trajectory when it is a verified success. Never raises."""
    speed_watch.record("request", (time.time() - started) * 1000, note=kind)   # speed watch (E6)
    # Session 28: the durable things the owner said, remembered (reviewable in Settings > Memory)
    noted = memory.after_request([m for m in messages[start_index:] if isinstance(m, dict)], status, root=DATA_DIR)
    LAST_NOTED[:] = noted
    if noted:
        _progress("thinking", "Remembered: " + "; ".join(n["text"] for n in noted)[:300])
    if not EXPERIENCE_ENABLED:
        return
    try:
        verification = dict(_LAST_VERIFY) if _task_files else {}
        outcome = experience.outcome_of(status, verification)
        providers = list(REQUEST_USAGE)
        request_id = uuid.uuid4().hex[:12]
        kept = False
        if outcome == "verified" and status == "done":
            turns = [m for m in messages[start_index:] if isinstance(m, dict)]
            used = sorted({c.get("function", {}).get("name", "")
                           for m in turns for c in (m.get("tool_calls") or []) if isinstance(c, dict)})
            kept = experience.save_trajectory(
                request_id, goal, turns, [u for u in used if u],
                meta={"kind": kind, "provider": providers[-1] if providers else "",
                      "files": list(_task_files)}) is not None
        for changed in list(_task_files)[:20]:
            events.emit("artifact.created", "LOKI", {"path": changed, "outcome": outcome})
        experience.record({
            "id": request_id, "kind": kind, "goal": goal, "status": status, "outcome": outcome,
            "provider": providers[-1] if providers else "", "providers": providers,
            "tool_calls": _REQUEST_TOOL_CALLS, "files": list(_task_files),
            "model": _model_of(providers[-1] if providers else ""),
            "repaired": GUARD_STATS["repaired"] - _GUARD_AT_START.get("repaired", 0),
            "rejected": GUARD_STATS["rejected"] - _GUARD_AT_START.get("rejected", 0),
            "usage": dict(REQUEST_USAGE), "route": list(ROUTE_TRACE),
            "triage": _triage_record(start_index),
            "seconds": time.time() - started, "trajectory": kept, "role": JOB_ROLE,
        })
        reasoning_bank.remember(goal, status, outcome, [m for m in messages[start_index:] if isinstance(m, dict)],
                                extra={"kind": kind, "provider": providers[-1] if providers else "",
                                       "seconds": round(time.time() - started, 1)})
        # Roadmap E2: a verified success that took more than a few tool calls becomes a learned skill.
        learned = skill_learning.learn_from(goal, [m for m in messages[start_index:] if isinstance(m, dict)],
                                            status, outcome, _REQUEST_TOOL_CALLS, root=DATA_DIR)
        if learned:
            LAST_LEARNED.clear()
            LAST_LEARNED.update(learned)
            _progress("thinking", "Learned a skill from this: %s (%s)." % (
                learned["id"], "refreshed" if learned.get("refreshed") else "new"))
    except Exception as exc:  # noqa: BLE001 - learning must never break a request
        print("  [experience] not recorded: %s" % exc)


def _triage_record(start_index: int = 0) -> dict:
    t = dict(LAST_TRIAGE or {})
    if not t:
        return {}
    delegated = any(isinstance(m, dict) and any(
        (c.get("function") or {}).get("name") == "delegate" for c in (m.get("tool_calls") or [])
        if isinstance(c, dict)) for m in messages[start_index:])
    t["actual_route"] = first_layer.actual_route(_REQUEST_TOOL_CALLS, delegated)
    return {k: t[k] for k in ("source", "kind", "route", "difficulty", "risk", "confidence", "ms",
                              "actual_route", "missing_info", "capabilities") if k in t}


def _skill_note(reply: str) -> str:
    """Roadmap E2: when a learned skill was offered for this request, the reply says so."""
    if LAST_SKILLS and "learned skill" not in str(reply or "").lower():
        return str(reply or "").rstrip() + "\n\n(used learned skill: %s)" % ", ".join(LAST_SKILLS)
    return reply


def _status_of_reply(reply: str) -> str:
    return "done" if reply_outcome(reply) == "done" else "blocked"


def ruflo_command(user_message: str) -> tuple:
    """`/ruflo <command> <task>` -> (None, task with Ruflo's playbook); `/ruflo [list] [word]` ->
    (a list of commands, None). Anything else -> (None, the message unchanged)."""
    text = (user_message or "").strip()
    if not re.match(r"^/ruflo(\s|$)", text, flags=re.IGNORECASE):
        return None, user_message
    try:
        import ruflo_library  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # noqa: BLE001
        return "The Ruflo library is not available here: %s" % exc, None
    parts = text.split(None, 2)
    name = parts[1] if len(parts) > 1 else "list"
    task = parts[2] if len(parts) > 2 else ""
    if name.lower() in ("list", "help", "commands") or not task:
        word = (task or ("" if name.lower() in ("list", "help", "commands") else name)).lower()
        items = [c for c in ruflo_library.commands() if not c["blocked"]
                 and (not word or word in c["id"] or word in c["group"] or word in c["description"].lower())]
        lines = ["- /ruflo %s <task>  (%s) %s" % (c["id"], c["group"], c["description"][:90]) for c in items[:40]]
        more = "" if len(items) <= 40 else "\n...and %d more (add a word to narrow: /ruflo list swarm)" % (len(items) - 40)
        return ("Ruflo commands%s - run one with `/ruflo <command> <task>`:\n%s%s"
                % ((" matching '%s'" % word) if word else "", "\n".join(lines) or "(none match)", more)), None
    try:
        return None, ruflo_library.command_prompt(name, task)
    except (KeyError, PermissionError) as exc:
        return str(exc).strip("'\""), None


async def run_agent(user_message: str) -> str:
    started, start_index = _start_request()
    status = "error"
    try:
        listed, rewritten = ruflo_command(user_message)
        if listed is not None:
            messages.append({"role": "user", "content": user_message})
            messages.append({"role": "assistant", "content": listed})
            status = "done"
            return listed
        user_message = rewritten
        verdict = await asyncio.to_thread(_triage, user_message)
        if verdict.get("self_change") and AGENT_MODE == "build":
            # A change to LOKI's own code never depends on the model choosing the right tool:
            # it always goes to improve_loki (its own worktree, tests, ship only when green).
            result = improve_loki(user_message)
            status = "done" if result.startswith("started") else "blocked"
            reply = ("I handed this to a background LOKI agent that changes LOKI's own code: "
                     + result) if result.startswith("started") else ("I could not start that change: " + result)
            messages.append({"role": "user", "content": user_message})
            messages.append({"role": "assistant", "content": reply})
            return reply
        reply = _skill_note(await _run_agent(user_message))
        status = "done"
        return reply
    except BudgetExhausted:
        status = "budget"
        raise
    finally:
        _end_triage()
        _record_experience("chat", user_message, status, started, start_index)


# ---------------------------------------------------------------------------
# The agent is OpenCode + CodeGraph (engine/opencode_engine.py; owner 2026-10-25: "replace it ... just make my agent
# actually work"). The window's chat and tasks call run_opencode; LOKI's own loop below stays only for background jobs
# and teams until they move too (docs/AGENT_ENGINE.md), and for LOKI_AGENT_ENGINE=loki.
# ---------------------------------------------------------------------------
import opencode_engine  # noqa: E402

OC_SESSIONS = opencode_engine.Sessions(DATA_DIR / "opencode" / "sessions.json")
try:   # the harness picked in Settings > Agent / the Harness menu (harness.txt); the older engine.txt: loki or auto
    _hfile = DATA_DIR / "opencode" / "harness.txt"
    if _hfile.is_file():
        _saved_engine = _hfile.read_text(encoding="utf-8").strip()
    else:
        _saved_engine = (DATA_DIR / "opencode" / "engine.txt").read_text(encoding="utf-8").strip()
        _saved_engine = "loki" if _saved_engine == "loki" else "auto"
    if _saved_engine in opencode_engine.HARNESSES:
        os.environ.setdefault("LOKI_AGENT_ENGINE", _saved_engine)
except OSError:
    pass


def _oc_providers(first: str) -> dict:
    """The providers OpenCode may use: the one LOKI picked first, then every other configured HTTP provider."""
    order, seen = [first] + [p for p in SMART_ORDER if p != first] + [n for n in MODELS if n not in SMART_ORDER], set()
    out = {}
    for name in order:
        if name in seen or name not in MODELS:
            continue
        seen.add(name)
        cfg = MODELS[name]
        base = str(cfg.base_url or "")
        if not base.startswith("http") or not provider_configured(name):
            continue
        model = resolve_local_model(name) if "11434" in base else cfg.model
        out[name] = {"base_url": base, "model": model, "key": str(cfg.api_key or "")}
        if len(out) >= 6:
            break
    return out


def engine_status() -> dict:
    import dsh_engine  # pylint: disable=import-outside-toplevel
    oc, cg = opencode_engine.find_opencode(), opencode_engine.find_codegraph()
    return {"engine": opencode_engine.engine_choice(), "harnesses": [{"id": k, "name": v[0], "what": v[1]}
                                                                     for k, v in opencode_engine.HARNESSES.items()],
            "opencode": oc, "codegraph": cg,
            "codex": __import__("cli_agents").find_cli("codex"), "claude_code": __import__("cli_agents").find_cli("claude-code"),
            "dsh": dsh_engine.find_dsh(), "deepseek_harness": dsh_engine.mode(),
            "install": opencode_engine.INSTALL, "workspace": str(WORKSPACE),
            "indexed": (WORKSPACE / ".codegraph").is_dir()}


async def run_opencode(text: str, task: bool = False, allow_bash: bool = True, preamble: str = "") -> str:
    """One chat message (or a Build task / background job) done by OpenCode in the workspace, with CodeGraph; LOKI
    reports every tool. allow_bash=False: no shell (a job not allowed to run commands); preamble: a job's agent profile."""
    global _task_ok_calls, _task_failed_calls
    # a model on THIS computer (Ollama, LM Studio ...): LOKI's own lean offline agent (engine/local_agent.py) - a 9B
    # model cannot carry OpenCode's 12k-token prompt and 20 tools (owner 2026-10-25: "make me a git repo with my
    # offline local model ... get it done")
    first_name = active_model_name()
    harness = opencode_engine.engine_choice()
    acting = AGENT_MODE not in ("ask", "plan")
    if harness == "shell" or (harness == "auto" and acting and _local_agent_for(first_name)):
        pick = first_name if _local_agent_for(first_name) else next(iter(_oc_providers(first_name)), "")
        if pick:
            return await run_local(text, pick, task=task, preamble=preamble)
    if harness in ("codex", "claude-code"):        # the owner's own ChatGPT / Claude plan through its official CLI
        return await run_cli_harness(text, harness, task=task, preamble=preamble)
    if harness == "dsh":                           # picked by hand: DeepSeek Harness runs whatever model is picked
        import dsh_engine  # pylint: disable=import-outside-toplevel
        prov = _oc_providers(first_name)
        dexe = dsh_engine.find_dsh()
        if prov and dexe:
            name0 = next(iter(prov))
            out = await run_dsh(text, (name0, prov[name0]), dexe, task=task, preamble=preamble)
            if out is not None:
                return out
            messages.pop()
        else:
            _progress("error", "DeepSeek Harness is not installed (%s) - OpenCode runs this one." % dsh_engine.INSTALL)
    # owner 2026-10-25: "when we're using deepseek4.1 use deepseek harness" - DeepSeek's own agent (engine/dsh_engine.py)
    if harness == "auto" and acting and not os.getenv("LOKI_OPENCODE_MODEL", "").strip():
        import dsh_engine  # pylint: disable=import-outside-toplevel
        chosen = dsh_engine.pick(_oc_providers(first_name)) if dsh_engine.mode() != "off" else None
        if chosen and chosen[0] in _DSH_BROKEN:
            chosen = None
        dexe = dsh_engine.find_dsh() if chosen else ""
        if chosen and dexe:
            out = await run_dsh(text, chosen, dexe, task=task, preamble=preamble)
            if out is not None:
                return out
            messages.pop()                         # dsh could not even start (a bad key): OpenCode takes the message
        elif chosen and not dexe:
            _progress("thinking", "DeepSeek Harness is not installed (%s) - OpenCode runs this one." % dsh_engine.INSTALL)
    exe = opencode_engine.find_opencode()
    if not exe and acting and os.getenv("LOKI_LOCAL_AGENT", "on").lower() not in ("off", "0", "no"):
        # no OpenCode on this machine: LOKI's own shell agent does the work with whatever model is there - the one
        # picked (Smart's pick included), else a model on this computer - never "install something first"
        # (owner 2026-10-25: "smart windows made me pictures and opened up my windows folder" instead of a git repo)
        pick = next(iter(_oc_providers(first_name)), "") or next(
            (n for n in LOCAL_PROVIDERS + LOCAL_SERVERS if _local_agent_for(n, any_local=True)), "")
        if pick:
            return await run_local(text, pick, task=task, preamble=preamble)
    messages.append({"role": "user", "content": text})
    if not exe:
        reply = ("NOT DONE - LOKI's agent is OpenCode now and it is not installed on this computer. Install it once: "
                 "Settings > Agent > Install (or run `%s`, and `%s` for the code map), then send this again."
                 % (opencode_engine.INSTALL["opencode"], opencode_engine.INSTALL["codegraph"]))
        messages.append({"role": "assistant", "content": reply})
        save_history()
        return reply
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    __import__("local_agent").protect(WORKSPACE)          # .loki/ (the chats) never ends up in a git commit
    cg = opencode_engine.find_codegraph()
    if cg and not (WORKSPACE / ".codegraph").is_dir():
        _progress("thinking", "CodeGraph: indexing the workspace once (it keeps itself up to date after)...")
        note = await asyncio.to_thread(opencode_engine.ensure_index, str(WORKSPACE), cg)
        if note:
            _progress("thinking", note)
    plan = AGENT_MODE in ("ask", "plan")
    first = active_model_name()
    pinned = os.getenv("LOKI_OPENCODE_MODEL", "").strip()          # provider/model of OpenCode's own (e.g. Zen)
    providers = _oc_providers(first) if not pinned else {}
    try:   # DeepSeek 4.1 on NVIDIA / OpenRouter: its tool calls come back as text there - fixed in a local proxy
        import dsml_proxy  # pylint: disable=import-outside-toplevel
        providers = dsml_proxy.wrap(providers)
    except Exception as exc:  # noqa: BLE001
        print("[loki] DeepSeek tool-call fix not started: %s" % exc, flush=True)
    cfg_dir = DATA_DIR / "opencode"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "opencode.json"
    oc_cfg = opencode_engine.build_config(providers, cg if cg else "", plan, _DESTRUCTIVE_SNIPPETS)
    if not allow_bash:
        oc_cfg["permission"]["bash"] = "deny"
    if os.getenv("LOKI_JOB_ID"):                                   # a background job: its own config file
        cfg_path = cfg_dir / ("opencode-%s.json" % re.sub(r"[^\w-]", "", os.getenv("LOKI_JOB_ID", ""))[:40])
    # every turn knows who and where it is and the owner's other machines - whatever words the owner uses (owner
    # 2026-10-25: "it should know to go look for whats linked devices"): OpenCode's own instructions file
    try:
        import machines  # pylint: disable=import-outside-toplevel
        ctx = cfg_dir / (("context-%s.md" % re.sub(r"[^\w-]", "", os.getenv("LOKI_JOB_ID", ""))[:40])
                         if os.getenv("LOKI_JOB_ID") else "context.md")
        ctx.write_text(identity_section() + "\n\n# Your other machines\n" + machines.describe() + "\n",
                       encoding="utf-8")
        oc_cfg["instructions"] = [str(ctx)]
    except Exception as exc:  # noqa: BLE001
        print("[loki] context for OpenCode not written: %s" % exc, flush=True)
    cfg_path.write_text(json.dumps(oc_cfg, indent=1), encoding="utf-8")
    env = opencode_engine.env_for(providers)
    conv = ("job-" + os.getenv("LOKI_JOB_ID", "")) if os.getenv("LOKI_JOB_ID") else (active_conversation_id() or "default")
    session = OC_SESSIONS.get(conv)
    models = ([pinned] if pinned else ["%s/%s" % (opencode_engine.provider_id(n), p["model"]) for n, p in providers.items()]) or [""]

    def on_event(ev: dict) -> None:
        kind, part = ev.get("type"), ev.get("part") or {}
        if kind == "tool_use":
            name, status, shown, out = opencode_engine.tool_summary(part)
            _progress("tool", "%s %s" % (name, shown))
            _progress("tool_result" if status == "completed" else "error", ("%s: %s" % (name, out or status))[:400])
        elif kind == "text" and part.get("text"):
            _progress("assistant", str(part["text"])[:300])
        elif kind == "step_start":
            _progress("thinking", "OpenCode is working...")
        elif kind == "step_finish":    # the live meter: tokens of each step, added up, and which model did it
            tok = part.get("tokens") or {}
            meter["input"] += int(tok.get("input") or 0) + int(((tok.get("cache") or {}).get("read")) or 0)
            meter["output"] += int(tok.get("output") or 0) + int(tok.get("reasoning") or 0)
            meter["cost"] += float(part.get("cost") or 0)
            meter["step"] += 1
            _progress("usage", json.dumps({"model": meter["model"].split("/", 1)[-1], "where": meter["where"],
                                           "step": meter["step"], "input": meter["input"], "output": meter["output"],
                                           "cost": round(meter["cost"], 4), "seconds": round(time.time() - meter["t0"], 1)}))

    meter = {"model": "", "where": "", "input": 0, "output": 0, "cost": 0.0, "step": 0, "t0": time.time()}
    prompt = text if not task else ("%sGOAL: %s\n\nWork until it is done; check the result (run it, list it, git log) "
                                    "before you say it is done. End with one line: 'DONE: <what you made>' or "
                                    "'BLOCKED: <exactly what you need>'." % ((preamble + "\n\n") if preamble else "", text))
    result: dict = {}
    used = ""
    for model in models[:3]:
        _progress("thinking", "OpenCode%s%s" % (" (plan, read-only)" if plan else "", (" with " + model) if model else ""))
        pname = next((n for n in providers if model.startswith(opencode_engine.provider_id(n) + "/")), "")
        meter.update(model=model, where=pname or "OpenCode")
        _progress("usage", json.dumps({"model": model.split("/", 1)[-1] or "OpenCode's model", "where": meter["where"],
                                       "step": meter["step"], "input": meter["input"], "output": meter["output"],
                                       "seconds": round(time.time() - meter["t0"], 1)}))
        result = await asyncio.to_thread(opencode_engine.run_turn, prompt, str(WORKSPACE), exe=exe,
                                         config_path=str(cfg_path), env=env, session=session, model=model,
                                         agent="plan" if plan else "", on_event=on_event,
                                         cancelled=_cancel_event.is_set)
        used = model
        if result.get("session"):
            session = result["session"]
            OC_SESSIONS.set(conv, session)
        if result.get("text") or result.get("tools") or not result.get("error") or _cancel_event.is_set():
            break
        _progress("error", "%s failed: %s - trying the next provider" % (model or "OpenCode", result.get("error", "")[:200]))
    ok, failed = opencode_engine.tool_counts(result.get("tools") or [])
    _task_ok_calls, _task_failed_calls = ok, failed
    reply = result.get("text") or ""
    if opencode_engine.leaked_tool_markup(reply):
        # should not happen any more (dsml_proxy turns them into real calls) - never show the raw tags, never pretend
        reply = opencode_engine.strip_tool_markup(reply)
        if not result.get("tools") or not reply:
            reply = ("NOT DONE - the model wrote its tool calls as text (DeepSeek's markup) and they did not run, so "
                     "nothing happened.\n\n" + reply).strip()
    if result.get("error") and not reply:
        reply = "NOT DONE - OpenCode stopped: %s" % result["error"]
    elif not plan and _claims_unbacked(text, reply):
        # OpenCode is a real agent, but the MODEL behind it can still just say "done": once, make it really do it
        _progress("thinking", "Checked: it says done, but no tool ran - asking it to really do it.")
        again = await asyncio.to_thread(
            opencode_engine.run_turn, "You said it is done, but no tool ran, so nothing happened on this computer. "
            "Do it now with your tools (bash, write, edit) and check the result. If you cannot, say it was NOT done.",
            str(WORKSPACE), exe=exe, config_path=str(cfg_path), env=env, session=session, model=used, agent="",
            on_event=on_event, cancelled=_cancel_event.is_set)
        ok2, failed2 = opencode_engine.tool_counts(again.get("tools") or [])
        _task_ok_calls, _task_failed_calls = ok + ok2, failed + failed2
        reply = again.get("text") or reply
        if _claims_unbacked(text, reply):
            reply = _not_done_note(reply)
    if not reply:
        reply = "(OpenCode finished without a reply.)"
    tools = result.get("tools") or []
    if tools and not plan:
        reply += "\n\n" + "Tools run: %d ok%s." % (_task_ok_calls, (", %d failed" % _task_failed_calls) if _task_failed_calls else "")
    messages.append({"role": "assistant", "content": reply})
    save_history()
    return reply


async def run_cli_harness(text: str, name: str, task: bool = False, preamble: str = "") -> str:
    """One message done by Codex (the owner's ChatGPT sign-in - GPT-6 on Plus and up) or Claude Code (their Claude
    plan), the official CLIs (engine/cli_agents.py). LOKI checks the folder before/after and runs git log itself -
    the same honesty as the Shell agent."""
    global _task_ok_calls, _task_failed_calls
    import cli_agents  # pylint: disable=import-outside-toplevel
    import dsh_engine  # pylint: disable=import-outside-toplevel
    import local_agent  # pylint: disable=import-outside-toplevel
    label = cli_agents.CLI_AGENTS[name]["label"]
    messages.append({"role": "user", "content": text})
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    local_agent.protect(WORKSPACE)
    if not cli_agents.find_cli(name):
        reply = "NOT DONE - %s is not installed here. Install it once: `%s`, then sign in: `%s`." % (
            label, cli_agents.CLI_AGENTS[name]["install"], cli_agents.CLI_AGENTS[name]["signin"])
        messages.append({"role": "assistant", "content": reply})
        save_history()
        return reply
    history = "\n".join("%s: %s" % (m["role"], str(m["content"])[:1500]) for m in messages[-7:-1]
                        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str))
    system = ((preamble + "\n\n") if preamble else "") + identity_section() + (
        ("\n\n# The chat so far\n" + history) if history else "") + (
        "\n\nDo the task with your tools in this folder and check the result before you say it is done.")
    before = dsh_engine.snapshot(WORKSPACE)
    _progress("thinking", "%s is working in %s..." % (label, WORKSPACE.name))
    t_cli = time.time()
    _progress("usage", json.dumps({"model": label, "where": "your plan", "seconds": 0}))
    try:
        out = await asyncio.to_thread(cli_agents.run, name, system, text, str(WORKSPACE), 1800)
        failed = False
    except Exception as exc:  # noqa: BLE001 - not signed in, timed out ...
        out, failed = "NOT DONE - %s stopped: %s" % (label, exc), True
    chs = dsh_engine.changes(before, dsh_engine.snapshot(WORKSPACE))
    _progress("usage", json.dumps({"model": label, "where": "your plan", "seconds": round(time.time() - t_cli, 1)}))
    _task_ok_calls, _task_failed_calls = len(chs), int(failed)
    reply = out if failed else local_agent.verify(text, WORKSPACE, chs, out, "done", [("cli", 0)] * max(1, len(chs)),
                                                  local_agent.find_shell()[0])
    messages.append({"role": "assistant", "content": reply})
    save_history()
    return reply


def _chats_command(cmd: str):
    """`loki chats list` / `loki chats delete <id>|--all` for the shell agent - LOKI's real chat list, never its files."""
    parts = cmd.split()
    if parts[:3] == ["loki", "chats", "list"] or parts[:2] == ["loki", "chats"] and len(parts) == 2:
        rows = list_conversations()
        return 0, "\n".join("%s  %s%s" % (c.get("id"), c.get("title") or "New chat",
                                           "  (this chat)" if c.get("id") == active_conversation_id() else "")
                             for c in rows) or "(no chats)"
    if parts[:3] == ["loki", "chats", "delete"]:
        current = active_conversation_id()
        ids = [c.get("id") for c in list_conversations() if c.get("id") != current] if "--all" in parts[3:] else parts[3:]
        gone = [i for i in ids if i != current and delete_conversation(i)]
        return 0, "deleted %d chat%s%s" % (len(gone), "" if len(gone) == 1 else "s",
                                           " (the chat you are in is kept)" if current in ids or "--all" in parts else "")
    return 2, "usage: loki chats list | loki chats delete <id> ... | loki chats delete --all"


_DSH_BROKEN: set = set()


def _local_agent_for(name: str, any_local: bool = False) -> bool:
    """Is this provider a model on this computer, ready, and the local agent not switched off?"""
    if os.getenv("LOKI_LOCAL_AGENT", "on").strip().lower() in ("off", "0", "no") or name not in MODELS:
        return False
    cfg = MODELS[name]
    if not (_cfg_is_local(cfg) and str(cfg.base_url or "").startswith("http")):
        return False
    if name in ("loki-tuned",) and not TUNED_PROMOTED:
        return False
    if any_local:
        return provider_configured(name) and bool(resolve_local_model(name) if "11434" in str(cfg.base_url) else cfg.model)
    return True


async def run_local(text: str, name: str, task: bool = False, preamble: str = "") -> str:
    """One message done by the model on this computer with LOKI's offline agent (engine/local_agent.py): shell commands
    one by one, the real output back, then LOKI checks the folder (and git log) itself."""
    global _task_ok_calls, _task_failed_calls
    import local_agent  # pylint: disable=import-outside-toplevel
    cfg = MODELS[name]
    model = resolve_local_model(name) if "11434" in str(cfg.base_url or "") else str(cfg.model or "")
    where = "on this computer" if _cfg_is_local(cfg) else "through %s" % name
    history = [m for m in messages if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)][-6:]
    messages.append({"role": "user", "content": text})
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    __import__("local_agent").protect(WORKSPACE)          # .loki/ (the chats) never ends up in a git commit
    goal = ("%s\n\n%s" % (preamble, text)) if preamble else text
    _progress("thinking", "Working with %s %s - shell commands, one by one..." % (model, where))
    loop = asyncio.get_running_loop()

    def ask_owner(cmd: str, why: str) -> bool:      # the same Allow / Deny card as LOKI's other risky actions
        detail = "%s\n\n$ %s\n\nin %s" % (why or "The agent wants to remove or overwrite something.", cmd[:3000], WORKSPACE)
        try:
            return bool(asyncio.run_coroutine_threadsafe(approve("Remove / overwrite", detail, False), loop).result(900))
        except Exception:  # noqa: BLE001 - no answer = no
            return False

    res = await asyncio.to_thread(local_agent.run, goal, WORKSPACE, str(cfg.base_url), model,
                                  key=str(cfg.api_key or ""), deny=_DESTRUCTIVE_SNIPPETS, progress=_progress,
                                  cancelled=_cancel_event.is_set, history=history,
                                  max_steps=int(os.getenv("LOKI_LOCAL_AGENT_STEPS", "30")),
                                  approve=ask_owner, builtins=_chats_command)
    _task_ok_calls, _task_failed_calls = int(res.get("commands") or 0), (0 if res.get("ok") else 1)
    reply = res.get("reply") or ""
    messages.append({"role": "assistant", "content": reply})
    save_history()
    return reply


async def run_dsh(text: str, chosen: tuple, exe: str, task: bool = False, preamble: str = ""):
    """One message (or Build task / job) done by DeepSeek Harness in the workspace. dsh prints only its last message,
    so LOKI looks at the folder before and after: 'done' with nothing changed is pushed back once, then NOT DONE."""
    global _task_ok_calls, _task_failed_calls
    import dsh_engine  # pylint: disable=import-outside-toplevel
    name, prov = chosen
    messages.append({"role": "user", "content": text})
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    __import__("local_agent").protect(WORKSPACE)          # .loki/ (the chats) never ends up in a git commit
    home = dsh_engine.prepare_home(DATA_DIR / "dsh", prov)
    env = dsh_engine.env_for(home, prov)
    prompt = text if not task else ("%sGOAL: %s\n\nWork until it is done; check the result (run it, list it, git log) "
                                    "before you say it is done. End with one line: 'DONE: <what you made>' or "
                                    "'BLOCKED: <exactly what you need>'." % ((preamble + "\n\n") if preamble else "", text))
    _progress("thinking", "DeepSeek Harness (%s, %s) is working in %s..." % (name, prov.get("model", ""), WORKSPACE.name))
    _progress("usage", json.dumps({"model": prov.get("model", "") or name, "where": name, "seconds": 0}))
    res = await asyncio.to_thread(dsh_engine.run_turn, prompt, str(WORKSPACE), exe=exe, env=env,
                                  cancelled=_cancel_event.is_set,
                                  on_line=lambda ln: _progress("assistant", ln[:300]) if ln.strip() else None)
    chs = res.get("changes") or []
    if res.get("exit") not in (0, None) and not chs and not res.get("text") and re.search(
            r"auth|api key|invalid|401|403|unauthori", str(res.get("error") or ""), re.I):
        # dsh could not start with this provider (owner's Mac 2026-10-25: "Your api key ****0Y0L is invalid"): never
        # again this session - OpenCode answers instead, nothing lost
        _DSH_BROKEN.add(name)
        _progress("error", "DeepSeek Harness can't use %s (%s) - OpenCode takes over." % (name, str(res.get("error"))[:160]))
        return None
    _task_ok_calls, _task_failed_calls = len(chs), (0 if res.get("exit") == 0 else 1)
    if chs:
        _progress("tool_result", "In the folder: " + dsh_engine.describe(chs))
    reply = res.get("text") or ""
    if res.get("error") and not reply:
        reply = "NOT DONE - DeepSeek Harness stopped: %s" % res["error"]
    elif _claims_unbacked(text, reply):
        _progress("thinking", "Checked: it says done, but nothing changed in the folder - asking it to really do it.")
        again = await asyncio.to_thread(
            dsh_engine.run_turn, "Earlier you were asked: %s\n\nYou said it was done, but NOTHING changed in this "
            "folder, so it was not done. Do it now with your tools (bash, write) and check the result. If you cannot, "
            "say it was NOT done." % text[:4000], str(WORKSPACE), exe=exe, env=env, cancelled=_cancel_event.is_set)
        chs = chs + (again.get("changes") or [])
        _task_ok_calls = len(chs)
        reply = again.get("text") or reply
        if _claims_unbacked(text, reply):
            reply = _not_done_note(reply)
    if not reply:
        reply = "(DeepSeek Harness finished without a reply.)"
    if chs:
        reply += "\n\nIn the folder: " + dsh_engine.describe(chs) + "."
    messages.append({"role": "assistant", "content": reply})
    save_history()
    return reply


async def pursue_goal(goal: str) -> str:
    started, start_index = _start_request()
    status = "error"
    try:
        await asyncio.to_thread(_triage, goal)
        reply = await _pursue_goal(goal)
        status = "done" if _answer_only(goal) else _status_of_reply(reply)
        return _skill_note(reply)
    except BudgetExhausted:
        status = "budget"
        raise
    finally:
        _end_triage()
        _record_experience("task", goal, status, started, start_index)


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
    if cmd == "/models" and arg.strip().lower() == "doctor":
        print(routing.doctor(sys.modules[__name__])["text"])
    elif cmd == "/models":
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
        messages.append({"role": "system", "content": system_prompt()})
        print("  conversation cleared")
    elif cmd == "/status":
        print(ollama_status())
    elif cmd == "/quit":
        raise SystemExit
    else:
        print("  commands: /models [doctor] /model <name> /tools /memory /plan /clear /goal <text> /status /quit")
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


# ---------------------------------------------------------------------------
# Headless background job: `python loki.py --job JOB.json`
# ---------------------------------------------------------------------------
# workers.py starts this for the built-in "loki" agent, so background tasks work with
# nothing else installed - on whatever model Loki uses (offline by default). The job
# works in its own folder (a git worktree when possible). Nobody is there to click
# Allow, so: file edits inside that folder are fine (the policy engine keeps them in
# it); commands, moves and deletes run only when the job was started with
# allow_commands, and still pass the command policy and the no-shell rule.
async def run_job(job_path: str) -> int:
    global approve, model_name
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    if job.get("selfcheck"):
        # The System check (system_check.py): prove that a background agent starts here, in
        # its own folder, with LOKI's data, and reports back - without a model or any tool.
        result = "DONE: system check job ran (Python %s, %s, workspace %s)" % (
            sys.version.split()[0], sys.platform, WORKSPACE)
        print("[loki-job] %s | system check" % job.get("id", ""), flush=True)
        print(result, flush=True)
        if job.get("result_path"):
            try:
                Path(job["result_path"]).write_text(result, encoding="utf-8")
            except OSError:
                pass
        return 0
    allow_commands = bool(job.get("allow_commands"))
    picked = job_model_choice(job, model_name)
    if picked != model_name:
        print("[loki-job] %s | %s" % (job.get("id", ""), JOB_MODEL_NOTE.get("why", "")), flush=True)
        model_name = picked
    if job.get("model"):
        model_name = str(job["model"])
        # The agent builder's fallback: use it when the first choice is not set up here.
        fallback = str(job.get("fallback") or "")
        if fallback in MODELS and model_name in MODELS and not provider_configured(model_name):
            model_name = fallback

    async def job_approve(kind: str, detail: str, decidable: bool = True) -> bool:
        if allow_commands and kind in ("run_command", "bash", "move_file", "open_godot", "make_tool", "user_tool"):
            print("  [job] allowed %s: %s" % (kind, detail[:200]), flush=True)
            return True
        print("  [job] not allowed in a background job: %s %s" % (kind, detail[:200]), flush=True)
        return False

    approve = job_approve
    if allow_commands:
        # The job may run commands (tests, builds), so OFFER run_command: the "system" tool category
        # is off by default, so a job allowed to run its tests never saw the tool. This process only;
        # the owner's setting is not saved. The command policy and the risk check still apply.
        CATEGORIES["system"] = True
        MODEL_TOOL_NAMES.update({"run_command", "bash"})   # it was never offered to a model at all
    deadline = float(job.get("deadline_s") or os.getenv("LOKI_JOB_DEADLINE", "0") or 0)
    if deadline > 0:
        # Stop in time to say so and keep the partial work, instead of being killed with nothing saved.
        globals()["JOB_DEADLINE_AT"] = time.monotonic() + deadline
    globals()["JOB_ROLE"] = str((job.get("profile") or {}).get("role") or "")
    globals()["loki_progress_callback"] = lambda event, text: print("  [%s] %s" % (event, text[:300]), flush=True)
    system = system_prompt()
    profile = job.get("profile") or {}
    if profile.get("instructions"):
        system += ("\n\n# You are the agent \"%s\"\n%s" % (profile.get("name", "agent"), profile["instructions"]))
    system += ("\n\n# Background job\nYou are running unattended as a background job in %s. "
               "Nobody can answer questions mid-task, so make reasonable choices and say what you "
               "chose in your final DONE line." % WORKSPACE)
    messages[:] = [{"role": "system", "content": system}]
    print("[loki-job] %s | model %s | workspace %s" % (job.get("id", ""), active_model_name(), WORKSPACE), flush=True)
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        if job.get("mcp"):
            await connect_mcp(stack)
        if opencode_engine.engine_choice() != "loki" and job.get("engine", "") != "loki" and (
                opencode_engine.find_opencode() or _local_agent_for(active_model_name())):
            # background jobs and team agents run on OpenCode too (docs/AGENT_ENGINE.md); LOKI's own loop stays the
            # fallback where OpenCode is not installed (and for LOKI_AGENT_ENGINE=loki)
            pre = ("You are the agent \"%s\". %s\n" % (profile.get("name", "agent"), profile["instructions"])
                   if profile.get("instructions") else "") + (
                "You run unattended as a background job; nobody can answer questions, so make reasonable choices "
                "and say what you chose.")
            # the shell is ON for every job (owner 2026-10-25: "i told you it needs to be able to bash" - Studio and
            # team jobs without allow_commands got no bash at all, and the agent said "No shell/Bash tool is
            # available"). OpenCode still blocks the destructive commands and anything outside the job's folder; a
            # job opts out with no_shell.
            result = _job_outcome(await run_opencode(str(job.get("prompt", "")), task=True,
                                                     allow_bash=not job.get("no_shell"), preamble=pre))
        else:
            result = await pursue_goal(str(job.get("prompt", "")))
    except (ModelUnavailable, BudgetExhausted) as exc:
        # Stopped from outside the loop (no model, a budget, the job's time limit): say BLOCKED with
        # the reason AND what was saved, in the result file too (it used to be left empty).
        why = exc.hint if isinstance(exc, ModelUnavailable) else str(exc)
        result = "BLOCKED: %s. %s" % (str(why).rstrip(". "), _partial_note())
        print(result, flush=True)
        _write_result(job, result)
        return 3 if isinstance(exc, ModelUnavailable) else 4
    finally:
        await stack.aclose()
    print("\n" + (result or "").strip(), flush=True)
    _write_result(job, result)
    return 2 if reply_outcome(result) == "blocked" else 0


JOB_MODEL_NOTE: dict = {}


def job_model_choice(job: dict, current: str) -> str:
    """Which model a background job runs on (2026-10-25: most failed tasks were team jobs on the 9B local model the
    chat happened to be pinned to - 12 tok/s, a 16k context it overflowed, then loops and 'stopped calling tools').
    A job's own model wins; LOKI_JOB_MODEL=same keeps the chat's choice; otherwise ('smart', the default) a chat
    pinned to a LOCAL model hands the job to Smart, which gives background work the best free model that calls
    tools reliably - unless local-only is on or nothing online is ready."""
    if job.get("model"):
        return str(job["model"])
    pref = os.getenv("LOKI_JOB_MODEL", "smart").strip().lower()
    if pref == "same" or current in AUTO_ROUTING_MODES:
        return current
    if pref not in ("smart", "") and pref in MODELS:
        JOB_MODEL_NOTE["why"] = "LOKI_JOB_MODEL picks %s for background jobs" % pref
        return pref
    if current in MODELS and _cfg_is_local(MODELS[current]) and not routing.local_only_setting():
        try:
            ready = online() and bool(_free_capable_online(dict(routing.needs_for({}, background=True), local_only=False)))
        except Exception:  # noqa: BLE001
            ready = False
        if ready or main_driver_ready()[0]:
            JOB_MODEL_NOTE["why"] = ("the chat is on the local model %s; this background job runs on Smart (the best "
                                     "free model that calls tools reliably) - LOKI_JOB_MODEL=same keeps it local" % current)
            return "smart"
    return current


def _job_outcome(reply: str) -> str:
    """A job's result must end DONE / BLOCKED (teams and the job list read it): OpenCode's reply, made so."""
    text = str(reply or "").strip()
    if text.startswith("NOT DONE"):
        return "BLOCKED: " + text
    if reply_outcome(text):
        return text
    if _task_ok_calls > 0:
        return text + "\n\nDONE: " + (text.splitlines()[0][:200] if text else "finished")
    return "BLOCKED: no tool ran, so nothing was done. " + text


def _write_result(job: dict, text: str) -> None:
    if job.get("result_path"):
        try:
            Path(job["result_path"]).write_text(text or "", encoding="utf-8")
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--job":
        raise SystemExit(asyncio.run(run_job(sys.argv[2])))
    asyncio.run(main())
