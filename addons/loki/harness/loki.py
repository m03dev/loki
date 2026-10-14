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
import urllib.parse
import urllib.request
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client
from mcp.client.sse import sse_client
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

ROOT = Path(__file__).parent   # the code that ships inside the addon


def _resolve_data_dir() -> Path:
    """Where secrets, memory, plans and downloads live - NOT inside the addon.

    Anything stored next to the code would ship with the addon, so user data goes
    in <project>/harness_data beside project.godot. LOKI_DATA overrides, and the
    bridge sets it explicitly.
    """
    explicit = os.getenv("LOKI_DATA", "").strip()
    if explicit:
        return Path(explicit)
    for candidate in (ROOT, *ROOT.parents):
        if (candidate / "project.godot").is_file():
            return candidate / "harness_data"
    return ROOT / "harness_data"


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
    "omniroute": "OMNIROUTE_API_KEY",
    "vireonix": "VIREONIX_API_KEY",
    "typesafe": "TYPESAFE_API_KEY",
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
    if reason:
        return {"ok": False, "error": reason}
    if not write_provider_key(name, key):
        return {"ok": False, "error": "Could not save the key."}
    return {"ok": True, "provider": name, "env": PROVIDER_ENV_VARS[name],
            "message": "%s connected." % name.replace("-", " ").title()}


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
import policy  # noqa: E402  (the hardcoded policy engine: allow / ask / deny)
import manifests  # noqa: E402  (capability manifests: discovered, never executed)
import federation  # noqa: E402  (Ollama on other machines - LOKI_WORKERS)
import skill_scan  # noqa: E402  (downloaded skills are untrusted text)
import knowledge  # noqa: E402  (viking:// context store over local folders)
import model_setup  # noqa: E402  (offline-first: find, download and warm local models)
import usage  # noqa: E402  (token and cost ledger - the credits meter)
import conductor  # noqa: E402  (Loki the conductor: specialists by role)

# The repo checkout this addon lives in (capabilities/ and skills/ sit at its root).
REPO_ROOT = ROOT.parent.parent.parent
CAPABILITIES = manifests.default_registry(REPO_ROOT, DATA_DIR)
KNOWLEDGE = knowledge.default_store(REPO_ROOT, DATA_DIR, WORKSPACE)
import experience  # noqa: E402  (outcome log, learned routing, training data)

godot_tools.ROOT = ROOT
godot_tools.WORKSPACE = WORKSPACE


# Providers whose "base_url" is one of these are CLI coding agents, not HTTP APIs.
CLI_AGENT_PREFIX = "cli-agent://"


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
    "nvidia": ModelConfig(base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                          api_key=os.getenv("NVIDIA_API_KEY", ""),
                          model=os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")),
    "ollama-cloud": ModelConfig(base_url=os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api"),
                                api_key=os.getenv("OLLAMA_API_KEY", ""),
                                model=os.getenv("OLLAMA_CLOUD_MODEL", "deepseek-v4-pro")),
    "ovh": ModelConfig(base_url=os.getenv("OVH_BASE_URL", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"),
                       api_key=os.getenv("OVH_API_KEY", ""),
                       model=os.getenv("OVH_MODEL", "Qwen3.5-397B-A17B")),
    "siliconflow": ModelConfig(base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
                               api_key=os.getenv("SILICONFLOW_API_KEY", ""),
                               model=os.getenv("SILICONFLOW_MODEL", "Qwen/Qwen3-8B")),
}

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
SMART_ORDER = ("openrouter", "deepseek-4.1", "gemini", "groq", "mistral", "sambanova",
               "cloudflare", "together", "nous", "unorouter", "deepseek", "cerebras",
               "vireonix", "claude-code", "codex", "local", "local-hermes")

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

ONLINE_ORDER = tuple(p for p in SMART_ORDER if p not in LOCAL_PROVIDERS)
_SMART_FAILED = set()

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


def routing_order(order) -> list:
    """`order` as routing should try it: learned within tiers when enabled, else as-is."""
    if not LEARN_ROUTING:
        return list(order)
    now = time.time()
    if now - _ROUTING_CACHE["t"] > 60:
        try:
            _ROUTING_CACHE["stats"] = experience.provider_stats()
        except Exception:
            _ROUTING_CACHE["stats"] = {}
        _ROUTING_CACHE["t"] = now
    return experience.learned_order(order, provider_tier, _ROUTING_CACHE["stats"],
                                    LEARN_MIN_SAMPLES)


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


def provider_configured(name: str) -> bool:
    cfg = MODELS.get(name)
    if cfg is None:
        return False
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
LOCAL_STATE: dict = {"at": 0.0, "name": "", "base_url": "", "source": "", "warm": "", "note": ""}
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


def _resolve_local() -> dict:
    LOCAL_STATE["at"] = time.time()
    if os.getenv("LOKI_LOCAL_MODEL"):
        # The user pinned a model: use it as-is.
        LOCAL_STATE.update(name=os.environ["LOKI_LOCAL_MODEL"], base_url="http://localhost:11434/v1",
                           source="pinned", note="LOKI_LOCAL_MODEL")
    else:
        models = model_setup.ollama_models()
        best = None
        if models:
            _match_installed_tags([m["name"] for m in models])
            info = HARDWARE if HARDWARE else {"budget_gb": 0}
            best = model_setup.best_installed(models, float(info.get("budget_gb") or 0))
        if best and best.get("tools"):
            name = best["name"]
            if not name.startswith(model_setup.DERIVED_PREFIX) and os.getenv("LOKI_LOCAL_CONTEXT", "1") != "0":
                name = model_setup.ensure_context(name, model_setup.context_for(HARDWARE or {}), models)
            LOCAL_STATE.update(name=name, base_url="http://localhost:11434/v1", source="ollama",
                               note="best installed: %s" % best["name"])
        else:
            servers = model_setup.other_servers()
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
        if "11434" in LOCAL_STATE["base_url"] and LOCAL_STATE["warm"] != LOCAL_STATE["name"]:
            LOCAL_STATE["warm"] = LOCAL_STATE["name"]
            threading.Thread(target=model_setup.keep_warm, args=(LOCAL_STATE["name"],),
                             daemon=True, name="loki-warm").start()
    return LOCAL_STATE


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


def active_model_name() -> str:
    """The provider actually in use - SMART resolves to the best available."""
    if model_name == "online":
        for candidate in routing_order(ONLINE_ORDER):
            if candidate not in _SMART_FAILED and provider_configured(candidate):
                return candidate
        # Nothing is configured yet. Name one anyway so the error tells the user exactly
        # what to set, instead of silently reaching for a local model they may not have.
        return ONLINE_ORDER[0]
    if model_name != "smart":
        return model_name
    local_first = PREFER == "local" and "local" not in _SMART_FAILED and local_ready()
    if local_first or (not online() and local_ready()):
        return "local"
    if not online():
        return "local"
    for candidate in routing_order(SMART_ORDER):
        if candidate not in _SMART_FAILED and provider_configured(candidate):
            return candidate
    return "local"


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
        _SMART_FAILED.add(provider or active_model_name())


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
    if _is_limit_error(exc):
        return "rate/size limit"
    return "error"


def should_fail_over(exc, auto_routing: bool) -> bool:
    """True when the error means 'try another provider', not 'this is a bug'."""
    if _is_limit_error(exc) or _is_agent_unavailable(exc):
        return True
    return auto_routing and (_is_auth_error(exc) or _is_unreachable(exc))


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
_METERED_DEFAULT = {"gpt", "claude", "deepseek", "deepseek-4.1", "cerebras", "aion",
                    "ollama-cloud"}
PAID_MAX_CALLS = int(os.getenv("LOKI_PAID_MAX_CALLS", "40"))
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
                                                "completion_tokens": 0})
    entry["calls"] += 1
    usage = getattr(response, "usage", None)
    for key in ("prompt_tokens", "completion_tokens"):
        value = getattr(usage, key, None) if usage is not None else None
        if isinstance(value, int):
            entry[key] += value


def usage_summary() -> str:
    """'openrouter 3 calls, 4.1k tokens' - one line per request, for the user and the log."""
    parts = []
    for name, u in REQUEST_USAGE.items():
        tokens = u["prompt_tokens"] + u["completion_tokens"]
        text = "%s %d call%s" % (name, u["calls"], "" if u["calls"] == 1 else "s")
        if tokens:
            text += ", %s tokens" % (("%.1fk" % (tokens / 1000)) if tokens >= 1000 else tokens)
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


VAULT_SEED = Path(__file__).resolve().parents[1] / "data" / "api_vault.json"
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


def _shorten(text: str) -> str:
    if len(text) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        return text[:half] + "\n...[output truncated]...\n" + text[-half:]
    return text


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
    for token in _REMOTE_EXEC_TOKENS:
        if token in text:
            return False, "refused: remote content piped into an interpreter (%s)" % token
    return True, "ok"


def run_command(command: str, timeout: int = 120) -> str:
    """Run a command WITHOUT a shell (safe_exec): argv only, `a && b` chains allowed,
    pipes / redirects / substitution refused with a reason."""
    allowed, reason = command_policy(command)
    if not allowed:
        print("  [policy] " + reason)
        return "error: " + reason
    try:
        code, out = safe_exec.run(command, cwd=str(WORKSPACE), timeout=int(timeout))
    except safe_exec.CommandRejected as e:
        print("  [policy] " + str(e))
        return f"error: {e}"
    except Exception as e:
        return f"error: {e}"
    return f"exit {code}\n{_shorten(out)}" if out else f"exit {code}"


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
    harness = ROOT / "loki_probe.gd"
    staged = Path(project) / "loki_probe_tmp.gd"
    sidecar = Path(project) / ".godot" / "loki_probe.json"
    if not harness.is_file():
        return "error: the input probe asset is missing (%s)" % harness
    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(harness.read_text(encoding="utf-8"), encoding="utf-8")
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
    "knowledge": knowledge_tool,
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
    "project_state": project_state_update,
    "review_repository": review_repository,
    "agent_sessions": agent_sessions,
    "api_vault": api_vault_lookup,
    "todo_list": todo_list,
    "todo_done": todo_done,
    "save_memory": save_memory,
}

# Tools that change files on disk (used to verify a task really did work).
MODIFYING = {"write_file", "append_file", "edit_file", "build_3d_scene", "build_scene",
             "move_file", "delete_file", "make_dir",
             # these three rewrite project.godot
             "add_input_action", "set_project_setting", "add_autoload"}
# Tools that START the game or the editor (scene scripts run, and can do anything a
# script can). Plan mode is read-only, so it offers none of them. check_script stays:
# --check-only parses the script without running it.
RUNS_PROJECT = {"play_scene", "probe_scene", "capture_scene", "validate_scene", "open_in_editor"}
# Writes outside the project (downloads into harness_data) - not "read-only" either.
NETWORK_WRITES = {"sync_ecc"}
# Starting or steering another agent: a delegated coder writes, so Plan mode cannot.
DELEGATING = {"delegate"}

# Tools that touch the system ask for a yes/no first, unless AUTO_APPROVE is on.
DANGEROUS = {"run_command", "open_godot", "move_file", "delete_file", "delegate"}
POLICY = policy.PolicyEngine(path_check=lambda name: resolve_in_workspace(name),
                             command_check=lambda command: command_policy(command),
                             parse_command=safe_exec.parse, dangerous=DANGEROUS,
                             registry=CAPABILITIES)
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
        spec = agent_profiles.job_spec(profile, task, str(WORKSPACE))
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
    return ("started background job %s: %s is working on it. The user can follow it in Background; "
            "you do not need to wait for it." % (job["id"], profile["name"]))


def conductor_tool(role: str, task: str = "", url: str = "") -> str:
    """Hand one step to a specialist: research, read_web, browse, remember, recall."""
    return CONDUCTOR.run(str(role).strip().lower(), str(task or ""), str(url or ""))


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
    schema("todo_list", "Show the persistent plan."),
    schema("todo_done", "Mark plan item N (1-based) as done.", {"index": {"type": "integer"}}, ["index"]),
    schema("save_memory", "Save one short lasting fact about the user.", {"fact": {"type": "string"}}, ["fact"]),
    schema("delegate", "Hand a longer task to one of your agents (Researcher, Builder, Reviewer, Tester, or one the user made) as a background job, so you can keep talking. The user approves each one. agent=name, task=what to do.",
           {"agent": {"type": "string"}, "task": {"type": "string"}}, ["agent", "task"]),
    schema("conductor", "You are the conductor: hand one step to a specialist. role='research' (a cited answer from the live web; task=question), 'read_web' (one page as markdown; url=...), 'browse' (a real browser does task on websites - asks the user), 'remember' (task=fact to keep long-term), 'recall' (task=question for long-term memory). Only roles listed under 'Specialists you can call' in your instructions are ready.",
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
    "list_files", "list_tree", "read_file", "write_file", "append_file",
    "edit_file", "search_files", "make_dir", "move_file", "delete_file",
    "build_3d_scene", "build_scene", "validate_scene", "play_scene", "probe_scene", "open_in_editor",
    "check_script", "capture_scene", "view_image", "project_state", "review_repository",
    "list_capabilities", "agent_sessions", "api_vault", "knowledge", "conductor", "delegate",
}
MODEL_TOOL_SCHEMAS = [t for t in TOOL_SCHEMAS if t["function"]["name"] in MODEL_TOOL_NAMES]



# --- tool categories (toggleable from the editor Settings dialog) ------------
TOOL_CATEGORIES = {
    "files": ["list_files", "list_tree", "read_file", "write_file", "append_file",
              "edit_file", "search_files", "make_dir", "move_file", "delete_file"],
    "scenes": ["build_3d_scene", "build_scene", "validate_scene", "read_scene", "open_in_editor"],
    "godot": ["godot_api", "godot_search"],
    "project": ["add_input_action", "set_project_setting", "add_autoload", "review_repository"],
    "runtime": ["play_scene", "check_script", "capture_scene", "probe_scene", "view_image"],
    "planning": ["todo_add", "todo_list", "todo_done", "project_state", "list_capabilities",
                 "agent_sessions", "api_vault"],
    "memory": ["save_memory", "knowledge"],
    "specialists": ["conductor", "delegate"],
    "capabilities": ["list_capabilities"],
    "skills": ["list_ecc_agents", "load_ecc_agent", "list_ecc_skills", "load_ecc_skill", "sync_ecc"],
    "system": ["run_command", "run_godot", "open_godot"],
}
CATEGORY_LABELS = {
    "files": "Files (read/write/edit/search)",
    "scenes": "Scenes (build/validate/open in editor)",
    "runtime": "Runtime checks (run scene, compile script)",
    "planning": "Planning (todo list)",
    "memory": "Memory (save facts)",
    "capabilities": "Capabilities (what Loki can use right now)",
    "skills": "Skills (ECC agents and skills)",
    "godot": "Godot API reference (look up classes and methods)",
    "project": "Project setup (input actions, settings, autoloads)",
    "system": "System (shell commands, launch Godot) - dangerous",
    "runtime": "Runtime checks (run scene, compile script, screenshot + look)",
}
SETTINGS_FILE = DATA_DIR / "loki_settings.json"


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


# Hard ceiling on how many tool schemas one request may carry. Providers reject a
# request that exceeds it (Groq: "'tools' : maximum number of items is 128"), and the
# whole turn fails - not just the excess tools. Loki's own tools are kept first, then
# MCP tools in connection order, so a big surface degrades instead of breaking.
MAX_TOOLS = int(os.getenv("LOKI_MAX_TOOLS", "128"))
TRIMMED_TOOLS_NOTE = ""


LOCAL_MAX_TOOLS = int(os.getenv("LOKI_LOCAL_MAX_TOOLS", "22"))
LOCAL_TOOL_PRIORITY = ["list_tree", "read_file", "edit_file", "write_file", "search_files",
                       "run_command", "make_dir", "move_file", "delete_file", "conductor", "delegate",
                       "knowledge", "save_memory", "todo_add", "todo_list", "todo_done",
                       "project_state", "append_file", "validate_scene", "play_scene",
                       "check_script", "build_scene", "read_scene", "godot_search"]


def _local_rank(name: str) -> int:
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

HISTORY_FILE = WORKSPACE / ".godot" / "loki_history.json"
CONVERSATIONS_FILE = WORKSPACE / ".godot" / "loki_conversations.json"


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


def system_prompt() -> str:
    """The system prompt for the current mode, always English-only, plus the ready specialists."""
    try:
        specialists = CONDUCTOR.prompt_section()
    except Exception:
        specialists = ""
    base = _base_system_prompt()
    return base + (chr(10) * 2 + specialists if specialists else "")


def _base_system_prompt() -> str:
    english = _ENGLISH_RULE + chr(10) * 2
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
                params = StdioServerParameters(command=spec["command"],
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
    global _task_modified
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
        if verdict.decision == policy.ASK and not await approve(
                name, json.dumps(args)[:400], decidable=verdict.decidable):
            return ("DENIED: the user did not approve this tool. Do NOT request it again. "
                    "Make progress with file tools (build_3d_scene, write_file, edit_file, "
                    "play_scene, validate_scene) instead, or reply 'BLOCKED: <reason>'.")
        try:
            result = LOCAL_TOOLS[name](**args)
            if asyncio.iscoroutine(result):
                result = await result
            if name in MODIFYING:
                _task_modified = True
                _record_touched(name, args, result)
            return result
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
        return text
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


def make_client():
    """An AsyncOpenAI for HTTP providers, or the CLI-agent shim for subscription ones."""
    cfg = MODELS[active_model_name()]
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
    return AsyncOpenAI(base_url=base_url, api_key=cfg.api_key, timeout=MODEL_TIMEOUT_S)


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
_task_modified = False

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
    report = await asyncio.to_thread(verify_files, list(_task_files))
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


async def _model_request(client, kwargs: dict, cfg, provider: str = ""):
    """Ask the model, retrying transient failures so one 429 does not end the task.

    `provider` is the MODELS key the request goes to; a failure marks THAT provider.
    """
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
            if status in (400, 422) and kwargs.get("tools") and attempt < 3:
                # The provider refused the request - most often because the tool
                # list is longer than it allows (Gemini and Groq both reject a long
                # one). Halve it and try again on this provider; if it still fails
                # the run fails over, so no single provider can stop the work.
                kwargs["tools"] = kwargs["tools"][: max(1, len(kwargs["tools"]) // 2)]
                attempt += 1
                _progress("thinking", "Model refused the tool list (HTTP %s); retrying with %d tools..."
                          % (status, len(kwargs["tools"])))
                continue
            if (status in _TRANSIENT_STATUS and attempt < MODEL_RETRIES
                    and not _is_quota_error(exc)):
                attempt += 1
                delay = _retry_delay(attempt)
                _progress("thinking", "Model returned HTTP %s; retrying in %.1fs (attempt %d of %d)..." % (status, delay, attempt, MODEL_RETRIES))
                await asyncio.sleep(delay)
                continue
            _mark_smart_failure(provider)
            if status == 404 and ("11434" in cfg.base_url) and "not found" in str(exc.message).lower():
                # Ollama is up but this model was never pulled. Marked as a limit so a
                # smart run fails over instead of ending.
                raise ModelUnavailable(
                    "[model missing] Ollama does not have %s yet. "
                    "Run `ollama pull %s` in Terminal, or pick another model." % (cfg.model, cfg.model)
                ) from exc
            raise ModelUnavailable(
                "[model error] %s answered HTTP %s: %s" % (cfg.model, status, short_error(exc.message))
            ) from exc
        except openai.APIConnectionError as exc:
            if attempt < MODEL_RETRIES:
                attempt += 1
                delay = _retry_delay(attempt)
                _progress("thinking", "Model connection failed; retrying in %.1fs (attempt %d of %d)..." % (delay, attempt, MODEL_RETRIES))
                await asyncio.sleep(delay)
                continue
            _mark_smart_failure(provider)
            raise ModelUnavailable(model_down_hint(cfg)) from exc
        except openai.OpenAIError as exc:
            _mark_smart_failure(provider)
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
        LAST_USAGE.append(entry)
        _progress("usage", usage.line(entry))
        if "11434" in cfg.base_url:
            # Keep the model loaded between turns (Ollama unloads it after 5 idle minutes).
            threading.Thread(target=model_setup.keep_warm, args=(cfg.model,), daemon=True).start()
    except Exception:
        pass


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
    while True:
        if _cancel_event.is_set():
            raise BudgetExhausted("cancelled by the user")
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
        _progress("thinking", "Turn %d: asking the model..." % turns)
        # Thinking models (Gemini 3.x) spend tokens reasoning before answering, so
        # give them headroom or the tool call gets truncated away.
        kwargs = {"model": cfg.model, "messages": messages, "tools": model_tool_schemas(),
                  "max_tokens": int(os.getenv("LOKI_MAX_TOKENS", "8192"))}
        if CAPABILITIES.is_enabled("headroom"):
            # Headroom compresses a copy; the conversation itself is never rewritten.
            kwargs["messages"], _saved = conductor.compress_messages(list(messages), cfg.model)
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
        _t0 = time.monotonic()
        while True:
            # Resolve the provider BEFORE the request, so a failure is pinned on the
            # provider that actually failed (re-resolving afterwards names the next one).
            provider = active_model_name()
            if PAID_MAX_CALLS > 0 and is_metered(provider) and _paid_calls() >= PAID_MAX_CALLS:
                raise BudgetExhausted(
                    "hit the paid-provider budget: %d calls to metered providers this request "
                    "(%s). Raise LOKI_PAID_MAX_CALLS, or use a free provider." % (
                        _paid_calls(), usage_summary()))
            try:
                response = await _model_request(client, kwargs, cfg, provider)
                _record_usage(response, kwargs, cfg, _t0)
                _record_request_usage(provider, response)
                break
            except ModelUnavailable as exc:
                if switches >= len(SMART_ORDER) or not should_fail_over(
                        exc, model_name in AUTO_ROUTING_MODES):
                    raise
                reason = failover_reason(exc)
                target = failover_target(provider)
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
        messages.append(_as_dict(message))
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
            global _REQUEST_TOOL_CALLS
            _REQUEST_TOOL_CALLS += 1
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

            # Jev loop detection: a rolling window of recent actions; every few tool
            # calls, ask Jev whether the agent is spinning without real progress.
            global _jev_loop_window
            _jev_loop_window.append("%s(%s) -> %s" % (
                call.function.name, json.dumps(args)[:120], str(result)[:100]))
            if call.function.name in MODIFYING and "error" not in str(result)[:80].lower():
                _jev_loop_window = []   # real progress - start a fresh window
            elif len(_jev_loop_window) > 16:
                del _jev_loop_window[:-16]
            if decisions.enabled_providers() and turns % JEV_LOOP_CHECK_EVERY == 0 and len(_jev_loop_window) >= 4:
                _spinning = await _jev_loop_nudge()
                if _spinning:
                    _jev_loop_window = []
                    _progress("thinking", "A decision provider flagged a likely loop (p=%s); nudging." % _spinning)
                    messages.append({"role": "user", "content": (
                        "You appear to be repeating the same approach without progress. Stop and "
                        "reassess: name what is blocking you, then try a materially different tool "
                        "or arguments, or reply 'BLOCKED: <reason>'. Do not repeat the last action."
                    )})


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
    global _empty_nudges, _repeat_sig, _repeat_count, _jev_loop_window
    _empty_nudges = 0
    _repeat_sig, _repeat_count = "", 0
    _jev_loop_window = []
    ROUTE_TRACE.clear()
    REQUEST_USAGE.clear()
    _task_files.clear()
    messages.append({"role": "user", "content": user_message})
    try:
        answer = await agent_turn()
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


async def _pursue_goal(goal: str) -> str:
    global _empty_nudges, _task_modified, _repeat_sig, _repeat_count, _jev_loop_window
    _empty_nudges = 0
    _repeat_sig, _repeat_count = "", 0
    _jev_loop_window = []
    _task_modified = False
    ROUTE_TRACE.clear()
    REQUEST_USAGE.clear()
    _task_files.clear()
    todo_clear()  # stale items from earlier tasks derail the model
    print("  [goal] working on: %s" % goal)
    _progress("task", "Goal: %s" % goal[:200])
    if is_conversational(goal):
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
# Every request leaves a record (experience.py), so Loki can learn from outcomes.
# ---------------------------------------------------------------------------

def _start_request() -> tuple:
    global _REQUEST_TOOL_CALLS
    _REQUEST_TOOL_CALLS = 0
    _LAST_VERIFY.clear()
    return time.time(), len(messages)


def _record_experience(kind: str, goal: str, status: str, started: float, start_index: int) -> None:
    """Log the request; keep its trajectory when it is a verified success. Never raises."""
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
        experience.record({
            "id": request_id, "kind": kind, "goal": goal, "status": status, "outcome": outcome,
            "provider": providers[-1] if providers else "", "providers": providers,
            "tool_calls": _REQUEST_TOOL_CALLS, "files": list(_task_files),
            "usage": dict(REQUEST_USAGE), "route": list(ROUTE_TRACE),
            "seconds": time.time() - started, "trajectory": kept,
        })
    except Exception as exc:  # noqa: BLE001 - learning must never break a request
        print("  [experience] not recorded: %s" % exc)


def _status_of_reply(reply: str) -> str:
    head = (reply or "").strip().upper()
    if head.startswith("DONE"):
        return "done"
    return "blocked"


async def run_agent(user_message: str) -> str:
    started, start_index = _start_request()
    status = "error"
    try:
        reply = await _run_agent(user_message)
        status = "done"
        return reply
    except BudgetExhausted:
        status = "budget"
        raise
    finally:
        _record_experience("chat", user_message, status, started, start_index)


async def pursue_goal(goal: str) -> str:
    started, start_index = _start_request()
    status = "error"
    try:
        reply = await _pursue_goal(goal)
        status = "done" if is_conversational(goal) else _status_of_reply(reply)
        return reply
    except BudgetExhausted:
        status = "budget"
        raise
    finally:
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
        messages.append({"role": "system", "content": system_prompt()})
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
    allow_commands = bool(job.get("allow_commands"))
    if job.get("model"):
        model_name = str(job["model"])

    async def job_approve(kind: str, detail: str, decidable: bool = True) -> bool:
        if allow_commands and kind in ("run_command", "move_file", "open_godot"):
            print("  [job] allowed %s: %s" % (kind, detail[:200]), flush=True)
            return True
        print("  [job] not allowed in a background job: %s %s" % (kind, detail[:200]), flush=True)
        return False

    approve = job_approve
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
        result = await pursue_goal(str(job.get("prompt", "")))
    except ModelUnavailable as exc:
        print("BLOCKED: " + exc.hint, flush=True)
        return 3
    except BudgetExhausted as exc:
        print("BLOCKED: " + str(exc), flush=True)
        return 4
    finally:
        await stack.aclose()
    print("\n" + (result or "").strip(), flush=True)
    if job.get("result_path"):
        try:
            Path(job["result_path"]).write_text(result or "", encoding="utf-8")
        except OSError:
            pass
    return 2 if (result or "").strip().upper().startswith("BLOCKED") else 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--job":
        raise SystemExit(asyncio.run(run_job(sys.argv[2])))
    asyncio.run(main())
