"""Loki test battery.

    harness_data/.venv/Scripts/python.exe tests/test_loki.py           # structural (offline)
    harness_data/.venv/Scripts/python.exe tests/test_loki.py --live    # + MCP and a real turn

Structural tests are offline and deterministic. --live needs a model and the MCP
servers (uvx) on PATH.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "loki" / "harness"))

_env = REPO / "harness_data" / ".env"
if _env.is_file():
    for _line in io.open(_env, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import loki  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    tail = ("  <- " + str(detail)[:120]) if (detail and not ok) else ""
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, tail))


def section(title: str) -> None:
    print("\n" + title)


SEP = os.sep
layout = Path(*loki.ROOT.parts[-3:])

section("layout: the addon is self-contained")
check("ROOT is inside the addon", layout == Path("addons") / "loki" / "harness", loki.ROOT)
check("DATA_DIR is named harness_data", loki.DATA_DIR.name == "harness_data", loki.DATA_DIR)
check("DATA_DIR is not inside addons", "addons" not in loki.DATA_DIR.parts, loki.DATA_DIR)
check("MCP_CONFIG ships with the code", loki.MCP_CONFIG.parent == loki.ROOT, loki.MCP_CONFIG)
check("MEMORY_FILE is user data", loki.MEMORY_FILE.parent == loki.DATA_DIR)
check("PLAN_FILE is user data", loki.PLAN_FILE.parent == loki.DATA_DIR)
check("SETTINGS_FILE is user data", loki.SETTINGS_FILE.parent == loki.DATA_DIR)
check("WORKSPACE lives in DATA_DIR", loki.DATA_DIR in loki.WORKSPACE.parents or loki.WORKSPACE.parent == loki.DATA_DIR, loki.WORKSPACE)
check("no harness/ at the repo root", not (REPO / "harness").exists())

section("providers")
check("github removed (GitHub Models retired)", "github" not in loki.MODELS)
check("online mode exists", "online" in loki.MODELS)
check("online order excludes local providers", not (set(loki.ONLINE_ORDER) & set(loki.LOCAL_PROVIDERS)))
check("online order is a subset of smart order", set(loki.ONLINE_ORDER) <= set(loki.SMART_ORDER))
check("every order entry exists in MODELS", all(n in loki.MODELS for n in loki.SMART_ORDER))
check("deepseek points at V4.1-Flash", loki.MODELS["deepseek"].model == "deepseek-flash", loki.MODELS["deepseek"].model)
check("claude-code is a CLI agent", loki.MODELS["claude-code"].base_url.startswith("cli-agent://"))
check("codex is a CLI agent", loki.MODELS["codex"].base_url.startswith("cli-agent://"))
check("local-tools is the tool-reliability model", "groq-tool-use" in loki.MODELS["local-tools"].model)

_saved_mode = loki.model_name
loki.model_name = "online"
check("online resolves to an online provider", loki.active_model_name() in loki.ONLINE_ORDER, loki.active_model_name())
loki.model_name = _saved_mode

section("failure paths")
check("429 counts as a limit", loki._is_limit_error(Exception("HTTP 429 rate limit")))
check("quota counts as a limit", loki._is_limit_error(Exception("quota exceeded")))
check("resource_exhausted counts as a limit", loki._is_limit_error(Exception("RESOURCE_EXHAUSTED")))
check("413 too large counts as a limit", loki._is_limit_error(Exception("Request too large")))
check("a real bug is not a limit", not loki._is_limit_error(Exception("KeyError: objects")))

# A provider that cannot run (an unsigned coding CLI) must be skipped, not fatal -
# otherwise one unusable provider at the end of the order kills a turn a ready
# provider further down would have finished.
check("an unsigned CLI agent is a skippable provider",
      loki._is_agent_unavailable(Exception("[model error] CliAgentError: Claude Code is not signed in.")))
check("an ordinary bug is not a skippable provider",
      not loki._is_agent_unavailable(Exception("KeyError: objects")))
check("a spent quota must not be retried",
      loki._is_quota_error(Exception("You exceeded your current quota, please check your plan and billing details")))
check("a daily free-model limit must not be retried",
      loki._is_quota_error(Exception("Rate limit exceeded: free-models-per-day. Add 10 credits to unlock")))
check("a transient rate limit IS still retried",
      not loki._is_quota_error(Exception("temporarily rate-limited upstream, please try again")))

_failed_before = set(loki._SMART_FAILED)
loki.model_name = "gemini"
_next = loki.failover_target()
check("failover marks the spent provider", "gemini" in loki._SMART_FAILED)
check("failover moves to a different provider", _next != "gemini", _next)
loki._SMART_FAILED.clear()
loki._SMART_FAILED.update(_failed_before)
loki.model_name = _saved_mode

section("filesystem sandbox")
_ws = loki.WORKSPACE.resolve()
_traversals = [".." + SEP + ".." + SEP + "etc" + SEP + "passwd",
               ".." + SEP + ".." + chr(92) + "windows" + chr(92) + "system32",
               "etc" + SEP + "shadow"]
for attempt in _traversals:
    got = None
    try:
        got = loki.resolve_in_workspace(attempt).resolve()
        inside = got == _ws or _ws in got.parents
    except Exception:
        inside = True
    check("traversal contained: %s" % attempt[:26], inside, got)

section("tool schemas")
_names = [t["function"]["name"] for t in loki.TOOL_SCHEMAS]
check("no duplicate tool names", len(_names) == len(set(_names)))
_bad = [t["function"]["name"] for t in loki.TOOL_SCHEMAS
        if not t.get("function", {}).get("name") or not isinstance(t["function"].get("parameters"), dict)]
check("every tool has a name and parameters", not _bad, _bad)
check("MODEL_TOOL_SCHEMAS is a subset of TOOL_SCHEMAS",
      {t["function"]["name"] for t in loki.MODEL_TOOL_SCHEMAS} <= set(_names))
check("MCP config defines the godot server", "godot" in loki.MCP_CONFIG.read_text(encoding="utf-8"))
check("system prompt renders", len(loki.SYSTEM_PROMPT.format(memory="")) > 100)

section("CLI agents")
section("godot domains (the vendored capability surface)")
_cfg = json.loads(loki.MCP_CONFIG.read_text(encoding="utf-8"))
_godot = _cfg["mcpServers"]["godot"]
check("godot server declares a toolsets knob", "toolsets" in _godot)
check("startup surface stays small (token discipline)", len(_godot.get("tools", [])) <= 12, len(_godot.get("tools", [])))
for _t in ("godot_list_toolsets", "godot_enable_toolset"):
    check("%s is offered at startup" % _t, _t in _godot.get("tools", []))
check("prompt advertises the unlockable domains",
      "godot_enable_toolset" in loki.SYSTEM_PROMPT and "capability domains" in loki.SYSTEM_PROMPT)
check("toolset summary compacts an enable payload",
      loki._toolset_summary('{"name":"animation","enabled":true,"tools":[{"name":"godot_animation_x"}]}')
      == "Enabled domain 'animation': 1 tool(s) now available. godot_animation_x.")
check("toolset summary reports a disable",
      loki._toolset_summary('{"name":"shader","enabled":false}') == "Disabled domain 'shader'.")
check("toolset summary ignores non-JSON", loki._toolset_summary("plain text") == "")

section("setup / onboarding")
_checkout = REPO / "addons" / "loki" / "harness"
_B = chr(92)  # one backslash, so the assertions below survive any transport mangling
_bat = (REPO / "setup.bat").read_text(encoding="utf-8")
check("setup.bat uses the post-fold harness path", ("addons" + _B + "loki" + _B + "harness") in _bat)
check("setup.bat dropped the pre-fold harness root", ('set "HARNESS=%REPO%' + _B + 'harness"') not in _bat)
check("setup.bat creates the venv under harness_data",
      ('set "DATA=%REPO%' + _B + 'harness_data"') in _bat and (_B + ".venv") in _bat)
check("setup.sh ships for macOS/Linux", (REPO / "setup.sh").is_file())
check("doctor script ships", (REPO / "tools" / "loki_doctor.py").is_file())

_envx = (_checkout / ".env.example").read_text(encoding="utf-8")
check(".env.example does not disable the zero-key provider",
      not any(line.strip() == "VIREONIX_API_KEY=" for line in _envx.splitlines()))
check(".env.example defaults to smart", "LOKI_MODEL=smart" in _envx)
check(".env.example carries no stale model names",
      "gemini-2.0-flash" not in _envx and "llama-3.3-70b-versatile" not in _envx)
check("LOKI_MODEL is smart by default (zero-config)",
      'os.getenv("LOKI_MODEL", "smart")' in (_checkout / "loki.py").read_text(encoding="utf-8"))
check("vireonix needs no key", loki.provider_configured("vireonix"))
check("vireonix is tried before local", loki.SMART_ORDER.index("vireonix") < loki.SMART_ORDER.index("local"))

import cli_agents  # noqa: E402
for _name in ("claude-code", "codex"):
    _spec = cli_agents.CLI_AGENTS[_name]
    check("%s gives install+signin guidance" % _name, bool(_spec.get("install")) and bool(_spec.get("signin")))
check("codex is allowed to write (workspace-write)", "workspace-write" in cli_agents.CLI_AGENTS["codex"]["args"])
check("cli_agents.make_client exists", callable(getattr(cli_agents, "make_client", None)))
check("cli agent workspace fallback exists", callable(getattr(cli_agents, "ensure_workspace", None)))



section("CLI agents: failure paths")
_temp = REPO / "harness_data" / ".test_ws"
import shutil as _shutil
_shutil.rmtree(_temp, ignore_errors=True)
_made = cli_agents.ensure_workspace(str(_temp))
check("ensure_workspace creates a missing dir", _made == str(_temp) and _temp.is_dir(), _made)
check("ensure_workspace tolerates an empty path", cli_agents.ensure_workspace("") == "")
try:
    cli_agents.run("does-not-exist-agent", "sys", "hi", str(_temp))
    check("unknown CLI agent raises instead of crashing", False, "no exception")
except cli_agents.CliAgentError as exc:
    check("unknown CLI agent raises CliAgentError", True)
except Exception as exc:
    check("unknown CLI agent raises CliAgentError", False, type(exc).__name__)
try:
    cli_agents.run("codex", "sys", "hi", str(REPO / "harness_data" / ".no_such_dir_zzz"))
    check("a missing workspace does not raise WinError 267", True)
except cli_agents.CliAgentError as exc:
    # reported cleanly, which is the point - not a raw OSError
    check("a bad workspace is reported cleanly", "267" not in str(exc), str(exc)[:80])
_shutil.rmtree(_temp, ignore_errors=True)


async def live() -> None:
    from contextlib import AsyncExitStack
    section("live: MCP")
    async with AsyncExitStack() as stack:
        try:
            await asyncio.wait_for(loki.connect_mcp(stack), timeout=180)
            check("MCP servers connected", bool(loki.MCP_SESSIONS_BY_SERVER), list(loki.MCP_SESSIONS_BY_SERVER))
        except Exception as exc:
            check("MCP servers connected", False, "%s: %s" % (type(exc).__name__, exc))
            return
        start = len(loki.MODEL_TOOL_SCHEMAS)
        await loki.refresh_mcp_tools()
        check("refresh reveals runtime tools", len(loki.MODEL_TOOL_SCHEMAS) >= start,
              "%d -> %d" % (start, len(loki.MODEL_TOOL_SCHEMAS)))
        check("refresh is idempotent", len(await loki.refresh_mcp_tools()) == 0)
        loki.MCP_SESSIONS_BY_SERVER["__dead__"] = object()
        try:
            await loki.refresh_mcp_tools()
            check("a dead MCP server cannot break a refresh", True)
        except Exception as exc:
            check("a dead MCP server cannot break a refresh", False, exc)
        del loki.MCP_SESSIONS_BY_SERVER["__dead__"]

        section("live: godot capability domains")
        _ts = loki.mcp_sessions.get("godot_list_toolsets")
        if not _ts:
            check("godot_list_toolsets is reachable", False, "not offered at startup")
        else:
            _res = await _ts.call_tool("godot_list_toolsets", {})
            _sets = json.loads("\n".join(c.text for c in _res.content if hasattr(c, "text")))
            check("the server exposes many domains", len(_sets) >= 10, len(_sets))
            check("every domain carries a description", all(s.get("description") for s in _sets))
            # 'scripts' needs no Godot bridge, so it proves the unlock path headlessly.
            _out = await loki.call_tool("godot_enable_toolset", {"category": "scripts"})
            check("an enable is summarised, not dumped",
                  "Enabled domain 'scripts'" in _out and '"tools"' not in _out, _out[:160])
            _surfaced = [t["function"]["name"] for t in loki.MODEL_TOOL_SCHEMAS
                         if t["function"]["name"].startswith("godot_scripts")]
            check("enabling a domain surfaces its tools to the model", bool(_surfaced), _surfaced[:4])
            check("a surfaced tool is callable (in mcp_sessions)",
                  all(n in loki.mcp_sessions for n in _surfaced))

        section("live: agent turn")
        loki.messages[:] = [{"role": "system", "content": loki.SYSTEM_PROMPT.format(memory="")}]
        loki.loki_progress_callback = lambda event, text: None
        loki.messages.append({"role": "user", "content": "List the files in the project root. One tool call is enough."})
        try:
            text = await asyncio.wait_for(loki.agent_turn(), timeout=240)
            check("agent turn completes", bool(text), (text or "")[:120])
        except Exception as exc:
            check("agent turn completes", False, "%s: %s" % (type(exc).__name__, exc))


if "--live" in sys.argv:
    asyncio.run(live())

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
