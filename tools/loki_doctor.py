"""Loki doctor - what is configured, and exactly what to get next.

    python tools/loki_doctor.py

Prints every model provider, whether Loki can use it right now, and the link to
get a key. Nothing secret is printed - only whether a value is present.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "loki" / "harness"))

import loki  # noqa: E402

# Where to get each provider working. Kept here (not in loki.py) because it is
# onboarding copy, not runtime config.
SIGNUP = {
    "gemini": "https://aistudio.google.com/apikey",
    "groq": "https://console.groq.com/keys",
    "openrouter": "https://openrouter.ai/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "sambanova": "https://cloud.sambanova.ai/apis",
    "cloudflare": "https://dash.cloudflare.com (Workers AI; also set CLOUDFLARE_ACCOUNT_ID)",
    "together": "https://api.together.ai/settings/api-keys",
    "nous": "https://portal.nousresearch.com",
    "unorouter": "https://unorouter.com",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "cerebras": "https://cloud.cerebras.ai",
    "gpt": "https://platform.openai.com/api-keys",
    "claude": "https://console.anthropic.com/settings/keys",
    "claude-code": "npm install -g @anthropic-ai/claude-code   then run:  claude  ->  /login",
    "codex": "npm install -g @openai/codex   then run:  codex login",
    "vireonix": "nothing to do - needs no key, no account and no card",
    "omniroute": "local gateway on http://localhost:20128 (see docs/providers.md)",
    "aion": "https://www.aionlabs.ai/app/api-keys/",
    "cohere": "https://dashboard.cohere.com/api-keys",
    "zai": "https://open.bigmodel.cn/usercenter/apikeys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "kilocode": "https://app.kilo.ai/profile",
    "llm7": "https://token.llm7.io  (optional - anonymous use works)",
    "modelscope": "https://modelscope.cn/my/myaccesstoken",
    "nvidia": "https://build.nvidia.com/explore/discover",
    "ollama-cloud": "https://ollama.com/settings/keys",
    "ovh": "https://www.ovhcloud.com/en/public-cloud/ai-endpoints/",
    "siliconflow": "https://cloud.siliconflow.cn/account/ak",
}
LOCAL_HINT = "Ollama:  ollama pull qwen3:8b"

MARK = {True: "ready", False: "  -  "}


def status(name: str) -> bool:
    try:
        return loki.provider_configured(name)
    except Exception:
        return False


def main() -> int:
    print("Loki doctor")
    print("  repo        %s" % REPO)
    print("  data        %s" % loki.DATA_DIR)
    print("  workspace   %s%s" % (loki.WORKSPACE, "" if Path(loki.WORKSPACE).is_dir() else "   (missing)"))
    print("  LOKI_MODEL  %s" % loki.model_name)

    godot = str(loki.GODOT_EXE or "")
    godot_ok = bool(godot) and Path(godot).exists()
    print("  GODOT_EXE   %s%s" % (godot or "(unset)", "" if godot_ok else "   (NOT FOUND - set GODOT_EXE)"))
    print()

    # Smart order first (that is the order Loki actually tries), then the rest.
    seen, order = set(), []
    for name in list(loki.SMART_ORDER) + list(loki.MODELS):
        if name not in seen:
            seen.add(name)
            order.append(name)

    ready = 0
    print("  %-14s %-7s %-30s %s" % ("PROVIDER", "STATE", "MODEL", "HOW TO GET IT"))
    for name in order:
        if name in ("smart", "online"):
            continue
        ok = status(name)
        ready += 1 if ok else 0
        model = loki.MODELS[name].model
        how = SIGNUP.get(name) or (LOCAL_HINT if name.startswith("local") or name in ("local",) else "")
        print("  %-14s %-7s %-30s %s" % (name, MARK[ok], model, how))

    print()
    print("  %d provider(s) ready." % ready)
    print("  (claude-code / codex show ready when INSTALLED; run them once to sign in)")
    if ready == 0:
        print("  Nothing configured - and that is fine: Loki runs with NO keys at all.")
    print("  Zero-setup: 'vireonix' needs no key, no account and no card. Prompts go to a")
    print("  third party, so use a key you own for anything private.")
    print()
    print("  Put a key in %s (copy from .env.example), e.g.:" % (loki.DATA_DIR / ".env"))
    print("      GEMINI_API_KEY=...      then set  LOKI_MODEL=smart")
    print("  Or leave it empty and run  LOKI_MODEL=smart  - it uses whatever is available.")
    print()
    try:
        import jev
        _js = jev.status()
    except Exception:
        _js = {"enabled": False}
    if _js.get("enabled"):
        print("  %-11s %-7s %-30s %s" % ("Jev", MARK[True], _js.get("model"), _js.get("endpoint")))
        print("              typed decisions: risk gate + loop detection are ON.")
    else:
        print("  %-11s %-7s %-30s %s" % ("Jev", MARK[False], "-", "optional: https://thejevai.com"))
        print("              add TYPESAFE_API_KEY to .env for risk-gated approvals. Optional.")
    try:
        import laya
        _ls = laya.status()
    except Exception:
        _ls = {"enabled": False}
    if _ls.get("enabled"):
        print("  %-11s %-7s %-30s %s" % ("Laya", MARK[True], _ls.get("backend"), _ls.get("endpoint")))
        print("              local-first decision provider: risk gate + loop detection are ON.")
    else:
        print("  %-11s %-7s %-30s %s" % ("Laya", MARK[False], "-", "optional: https://github.com/receptron/laya"))
        print("              local backend needs Node 20+ and: npm install @receptron/laya")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
