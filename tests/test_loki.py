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


check("the godot server imposes no startup allow-list (all tools offered)",

      "tools" not in _godot, _godot.get("tools"))

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


check("bootstrap is single-instance (atomic lock)",


      "O_EXCL" in (REPO / "addons" / "loki" / "bootstrap.py").read_text(encoding="utf-8"))


check("dock guards against a duplicate bridge launch",


      "_last_bridge_spawn_msec" in (REPO / "addons" / "loki" / "loki_dock.gd").read_text(encoding="utf-8"))


_dock_source = (REPO / "addons" / "loki" / "loki_dock.gd").read_text(encoding="utf-8")


check("chat dock has real multi-file attachment picker", "FileDialog.FILE_MODE_OPEN_FILES" in _dock_source and "files_selected.connect(_on_attachment_files_selected)" in _dock_source)


check("attachments accept code and Godot scene/resource text", all(ext in _dock_source for ext in ("gdshader", "tscn", "tres", "gd", "cs")))


check("text attachment sizes are bounded", "MAX_ATTACHMENT_FILE_BYTES" in _dock_source and "MAX_ATTACHMENT_TOTAL_BYTES" in _dock_source)


check("images are identified distinctly and not mislabeled as text", "Image attachment:" in _dock_source and "is_image" in _dock_source)


check("pending attachments can be cleared", "Clear pending attachments" in _dock_source and "_clear_attachments()" in _dock_source)


_settings_source = (REPO / "addons" / "loki" / "loki_settings.gd").read_text(encoding="utf-8")


_bridge_source = (REPO / "addons" / "loki" / "loki_bridge.py").read_text(encoding="utf-8")


check("settings provide a Connections tab", 'page.name = "Connections"' in _settings_source and "set_connections(payload: Dictionary)" in _settings_source)


check("connection inventory is available from the authenticated local bridge", 'route == "/connections"' in _bridge_source and "connection_inventory" in _bridge_source)


check("connection inventory never includes environment credentials", '"status": status' in _bridge_source and '"api_key"' not in _bridge_source[_bridge_source.index("def connection_inventory"): _bridge_source.index("class BridgeHandler")])


check("Chrome, PowerShell and CMake prerequisites are inventoried", all(term in _bridge_source for term in ("Chrome DevTools MCP prerequisite", "PowerShell 7", "Windows PowerShell", "CMake CLI")))


check("connections refresh is wired to settings", "connections_refresh_requested.connect(_refresh_connections)" in _dock_source and '"/connections"' in _dock_source)





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


# Loki must never surface a raw OSError for a bad workspace - it wraps everything in


# CliAgentError. Do NOT assert on the CLI's own stderr text: codex may legitimately


# mention its own WinError 267, which Loki does not control, and that made this check


# flaky. The contract under test is the exception TYPE, which is deterministic.


try:


    cli_agents.run("codex", "sys", "hi", str(REPO / "harness_data" / ".no_such_dir_zzz"))


    check("a bad workspace is handled without a raw OSError", True)


except cli_agents.CliAgentError:


    check("a bad workspace is reported as a clean CliAgentError", True)


except Exception as exc:


    check("a bad workspace is reported as a clean CliAgentError", False, type(exc).__name__)


_shutil.rmtree(_temp, ignore_errors=True)








section("jev (typed decisions for the loop)")


import jev  # noqa: E402


_env_keys = ("TYPESAFE_API_KEY", "JEV_API_KEY", "JEV_KEY", "LOKI_JEV")


_saved = {k: os.environ.get(k) for k in _env_keys}


for _k in _env_keys:


    os.environ.pop(_k, None)


check("jev is inert with no key", jev.available() is False)


check("jev decide is inert with no key", jev.decide({"q": {"type": "noul", "instructions": "x"}}, "s") == {})


check("jev risk gate returns None with no key", jev.risk_gate("delete_file", "{}") is None)


os.environ["TYPESAFE_API_KEY"] = "jv_live_demo"


check("a hosted key enables jev", jev.enabled() is True)


check("a jv_live_ key routes to the hosted gateway",


      jev.base_url() == "https://thejevai.com/v1/systemone", jev.base_url())


os.environ["TYPESAFE_API_KEY"] = "ts_official_demo"


check("an official key routes to api.typesafe.ai",


      jev.base_url() == "https://api.typesafe.ai/v1/systemone", jev.base_url())


os.environ["LOKI_JEV"] = "0"


check("LOKI_JEV=0 disables jev even with a key", jev.enabled() is False)


os.environ.pop("LOKI_JEV", None)


# A mocked transport proves the parsing without spending a network call.


_orig_post = jev._post


jev._post = lambda payload: {"answers": {"q": {"type": "choice", "choice": "confirm", "confidence": 0.9}}}


check("choice() parses the winning option",


      jev.choice("gate?", {"allow": "a", "confirm": "b"}, "s") == ("confirm", 0.9))


jev._post = lambda payload: {"answers": {"destructive": {"noul": 0.02}, "action": {"choice": "allow"}}}


check("risk gate allows a confidently safe action", jev.risk_gate("run_command", "ls") == "allow")


jev._post = lambda payload: {"answers": {"destructive": {"noul": 0.8}, "action": {"choice": "confirm"}}}


check("risk gate defers a risky action to the human", jev.risk_gate("delete_file", "rm -rf /") == "confirm")


def _boom(payload):


    raise RuntimeError("network down")


jev._post = _boom


check("a transport error is non-fatal (falls back)", jev.risk_gate("delete_file", "x") is None)


jev._post = _orig_post


check("loki exposes jev_status()", isinstance(loki.jev_status(), dict))


check("the jev MCP server is registered but gated by an env key",


      _cfg["mcpServers"].get("jev", {}).get("requires_env") == "TYPESAFE_API_KEY")


check("approve() is risk-gated by jev",


      "jev.risk_gate" in (_checkout / "loki.py").read_text(encoding="utf-8"))


for _k, _v in _saved.items():


    if _v is None:


        os.environ.pop(_k, None)


    else:


        os.environ[_k] = _v











section("vendored libraries (Godot skill packs)")


import ecc_sync  # noqa: E402


check("GodotPrompter is a sync source", "GodotPrompter" in ecc_sync.SOURCES)


check("the dead godot-ai-builder repo was dropped", "godot-ai-builder" not in ecc_sync.SOURCES)


check("every sync source declares a repo", all(s.get("repo") for s in ecc_sync.SOURCES.values()))


_state = ecc_sync.installed()


check("the library reports per-source counts", isinstance(_state.get("sources"), dict))


check("GodotPrompter skills were fetched",


      _state["sources"].get("GodotPrompter", {}).get("skills", 0) > 20,


      _state["sources"].get("GodotPrompter"))


check("loki aggregates the libraries", {"ECC", "GodotPrompter"} <= set(loki.LIBRARIES))


_libs = loki.vendor_library()


check("vendor_library reports ECC and GodotPrompter", {"ECC", "GodotPrompter"} <= set(_libs))


_check_skills = loki.list_ecc_skills()


check("list_ecc_skills names every library",


      "ECC" in _check_skills and "GodotPrompter" in _check_skills)


_gp_skill = _libs["GodotPrompter"]["skills"][0]


check("a GodotPrompter skill loads", "name:" in loki.load_ecc_skill(_gp_skill))


check("an unknown skill is reported, not crashed", loki.load_ecc_skill("__nope__").startswith("no such skill"))


check("an unknown agent is reported, not crashed", loki.load_ecc_agent("__nope__").startswith("no such agent"))





_libs_now = loki.vendor_library()


check("the loader finds every library recursively",


      {"ECC", "GodotPrompter", "Superpowers", "awesome-gamedev", "gamedev-plugin"} <= set(_libs_now),


      sorted(_libs_now))


_total_skills = sum(len(v["skills"]) for v in _libs_now.values())


check("the library holds hundreds of skills", _total_skills > 400, _total_skills)


check("every sync source is loaded (ponytail has no skills)",


      (set(ecc_sync.SOURCES) - {"ponytail"}) <= set(loki.LIBRARIES))


check("every loaded library is a sync source", set(loki.LIBRARIES) <= set(ecc_sync.SOURCES))


check("skill listing filters by query", "awesome-gamedev" in loki.list_ecc_skills("platformer"))


check("the unfiltered listing is capped, not dumped",


      "+" in loki.list_ecc_skills(), loki.list_ecc_skills()[:80])


check("agent listing accepts a query filter", isinstance(loki.list_ecc_agents("architect"), str))





section("optional Godot MCP servers")


_srv = json.loads(loki.MCP_CONFIG.read_text(encoding="utf-8"))["mcpServers"]


check("the game-run server is gated by npx", _srv.get("godot_run", {}).get("requires_cmd") == "npx")


check("the game-run server offers a tight tool set", len(_srv.get("godot_run", {}).get("tools", [])) <= 8)


check("the big Godot-MCP gateway is registered but off by default",


      _srv.get("godot_omni", {}).get("enabled") is False)


check("connect_mcp honours requires_cmd",


      "requires_cmd" in (_checkout / "loki.py").read_text(encoding="utf-8"))


check("the jev MCP server is gated by an env key",


      _srv.get("jev", {}).get("requires_env") == "TYPESAFE_API_KEY")


check("the git server is registered but opt-in",


      _srv.get("git", {}).get("enabled") is False and _srv.get("git", {}).get("requires_cmd") == "uvx")


check("the sequential-thinking server is opt-in",


      _srv.get("sequential", {}).get("enabled") is False)


check("GODOT_EXE is shared with MCP children as GODOT_PATH",


      'os.environ["GODOT_PATH"] = GODOT_EXE' in (_checkout / "loki.py").read_text(encoding="utf-8"))





# The gate must be a pure function so this bug class is unit-testable: an earlier


# patch dropped a `continue` and a disabled server still started.


import shutil as _sh  # noqa: E402


check("the gate skips a disabled server", bool(loki._server_skip_reason({"enabled": False})))


check("the gate skips a server needing an unset env",


      bool(loki._server_skip_reason({"requires_env": "__LOKI_TEST_UNSET__"})))


check("the gate skips a server needing a missing command",


      bool(loki._server_skip_reason({"requires_cmd": "__loki_no_such_cmd__"})))


check("the gate starts a plain server", loki._server_skip_reason({}) == "")


os.environ["__LOKI_TEST_SET__"] = "1"


check("the gate passes a server whose env is set",


      loki._server_skip_reason({"requires_env": "__LOKI_TEST_SET__"}) == "")


del os.environ["__LOKI_TEST_SET__"]


_present = "python" if _sh.which("python") else ("cmd" if _sh.which("cmd") else "sh")


check("the gate passes a server whose command exists",


      loki._server_skip_reason({"requires_cmd": _present}) == "")


_prev_enable = os.environ.get("LOKI_MCP_ENABLE")
os.environ["LOKI_MCP_ENABLE"] = "git"


check("LOKI_MCP_ENABLE turns an opt-in server on",


      loki._server_skip_reason({"enabled": False}, "git") == "")


if _prev_enable is None:
    os.environ.pop("LOKI_MCP_ENABLE", None)
else:
    os.environ["LOKI_MCP_ENABLE"] = _prev_enable


_prev_disable = os.environ.get("LOKI_MCP_DISABLE")
os.environ["LOKI_MCP_DISABLE"] = "time"


check("LOKI_MCP_DISABLE forces a server off",


      bool(loki._server_skip_reason({}, "time")))


if _prev_disable is None:
    os.environ.pop("LOKI_MCP_DISABLE", None)
else:
    os.environ["LOKI_MCP_DISABLE"] = _prev_disable


os.environ["__LOKI_T"] = "abc"


check("mcp args are env-templated", loki._expand_env("${__LOKI_T}/x") == "abc/x")


del os.environ["__LOKI_T"]


check("mcp_status reports every configured server", set(loki.mcp_status()) == set(_srv), sorted(loki.mcp_status()))


_src = (_checkout / "loki.py").read_text(encoding="utf-8")


check("git repo_path is auto-filled from the workspace",


      'name.startswith("git_")' in _src and "repo_path" in _src)











section("signing (tools/loki_sign.py)")
sys.path.insert(0, str(REPO / "tools"))
import loki_sign  # noqa: E402
check("the trusted public key ships", loki_sign.PUBLIC_KEY.is_file())
check("the key fingerprint is reported", loki_sign.fingerprint().startswith("SHA256:"), loki_sign.fingerprint())
_ok, _ = loki_sign.verify(str(REPO / "README.md"))
check("an unsigned file does not verify", _ok is False)
check("signing without a private key is refused", loki_sign.sign(str(REPO / "README.md"))[0] is False)



section("mcp: servers addressed by URL (no spawn)")
check("a URL server is not gated by a missing command",
      loki._server_skip_reason({"url": "http://127.0.0.1:8000/mcp", "requires_cmd": "uvx"}, "godot_omni") == "")
_specs = json.loads(loki.MCP_CONFIG.read_text(encoding="utf-8"))["mcpServers"]
_omni = _specs.get("godot_omni", {})
check("godot_omni connects to the editor over HTTP, not by spawning",
      "url" in _omni and "command" not in _omni, str(_omni.get("url")))
check("loki imports the HTTP MCP transports",
      hasattr(loki, "streamable_http_client") and hasattr(loki, "sse_client"))



check("a URL server with an unreadable capability token is skipped, not crashed",
      loki._server_skip_reason({"url": "http://x", "auth_bearer_json":
                               {"path": "/nonexistent/http-8000.json", "key": "http"}}) != "")
check("the capability dir defaults to godot-ai/capabilities",
      loki._godot_capability_dir().replace("\\", "/").endswith("godot-ai/capabilities"),
      loki._godot_capability_dir())
check("a missing JSON field reads as empty", loki._json_field("/nonexistent.json", "http") == "")
check("MCP_CONFIG defines the capability-dir variable",
      "GODOT_AI_CAPABILITY_DIR" in os.environ)



check("an unreachable URL endpoint is detected",
      loki._endpoint_reachable("http://127.0.0.1:59999/mcp") is False)
import socket as _socket
_srv = _socket.socket()
_srv.bind(("127.0.0.1", 0))
_srv.listen(1)
_live_port = _srv.getsockname()[1]
check("a reachable URL endpoint is detected",
      loki._endpoint_reachable("http://127.0.0.1:%d/mcp" % _live_port) is True)
_srv.close()



section("tool budget (the model rejects an over-long tool list)")
check("the default budget is provider-safe", 20 <= loki.MAX_TOOLS <= 128, str(loki.MAX_TOOLS))
check("the offered tools respect the budget",
      loki.MAX_TOOLS <= 0 or len(loki.model_tool_schemas()) <= loki.MAX_TOOLS)
_saved_budget = loki.MAX_TOOLS
loki.MAX_TOOLS = 5
_capped = loki.model_tool_schemas()
check("a small budget trims the offered tools", len(_capped) == 5, str(len(_capped)))
check("trimming is reported, not silent", "held back" in loki.TRIMMED_TOOLS_NOTE,
      loki.TRIMMED_TOOLS_NOTE)
check("local tools survive the trim",
      all(t["function"]["name"] in loki.LOCAL_TOOLS for t in _capped))
loki.MAX_TOOLS = _saved_budget



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


