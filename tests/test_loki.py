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


import subprocess
import sys


from pathlib import Path





REPO = Path(__file__).resolve().parent.parent


sys.path.insert(0, str(REPO / "engine"))





_env = REPO / "harness_data" / ".env"


if _env.is_file():


    for _line in io.open(_env, encoding="utf-8"):


        _line = _line.strip()


        if _line and not _line.startswith("#") and "=" in _line:


            _k, _v = _line.split("=", 1)


            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))





import loki  # noqa: E402
# Tests drive real turns with fake models: they must never write into the user's real
# experience log or let it reorder providers. The self-improvement tests opt back in,
# in a temp data dir.
loki.EXPERIENCE_ENABLED = False
loki.LEARN_ROUTING = False
# ...and never add test calls to the user's real credits ledger.
import tempfile as _usage_tf  # noqa: E402
loki.USAGE = loki.usage.Ledger(Path(_usage_tf.mkdtemp()) / "usage.jsonl")





PASS, FAIL = [], []








def check(name: str, ok: bool, detail: str = "") -> None:


    (PASS if ok else FAIL).append(name)


    tail = ("  <- " + str(detail)[:120]) if (detail and not ok) else ""


    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, tail))








def section(title: str) -> None:


    print("\n" + title)








SEP = os.sep


layout = Path(*loki.ROOT.parts[-3:])





section("layout: Loki is its own app (engine/), not a Godot addon")


check("ROOT is engine/", loki.ROOT.name == "engine" and loki.ROOT.parent == REPO, loki.ROOT)


check("DATA_DIR is named harness_data", loki.DATA_DIR.name == "harness_data", loki.DATA_DIR)


check("DATA_DIR is not inside engine/", "engine" not in loki.DATA_DIR.relative_to(REPO).parts if REPO in loki.DATA_DIR.parents else True, loki.DATA_DIR)
for _godot_leftover in ("project.godot", "addons"):
    check("no %s in the checkout" % _godot_leftover, not (REPO / _godot_leftover).exists())
_tracked_godot = [f for f in subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
                  if f.endswith((".gd", ".uid", ".tscn", ".tres", ".godot", ".import")) or f.startswith("addons/")]
check("no Godot files are tracked in the repo", not _tracked_godot, _tracked_godot[:5])


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


_checkout = REPO / "engine"


_B = chr(92)  # one backslash, so the assertions below survive any transport mangling


_bat = (REPO / "setup.bat").read_text(encoding="utf-8")


check("setup.bat uses the engine/ path", ('set "ENGINE=%REPO%' + _B + 'engine"') in _bat)


check("setup.bat dropped the pre-fold harness root", ('set "HARNESS=%REPO%' + _B + 'harness"') not in _bat)


check("setup.bat creates the venv under harness_data",


      ('set "DATA=%REPO%' + _B + 'harness_data"') in _bat and (_B + ".venv") in _bat)


check("setup.sh ships for macOS/Linux", (REPO / "setup.sh").is_file())


check("doctor script ships", (REPO / "tools" / "loki_doctor.py").is_file())


_bridge_source = (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8")
_loki_source = (REPO / "engine" / "loki.py").read_text(encoding="utf-8")


check("connection inventory is available from the authenticated local bridge", 'route == "/connections"' in _bridge_source and "connection_inventory" in _bridge_source)


check("connection inventory never includes environment credentials", '"status": status' in _bridge_source and '"api_key"' not in _bridge_source[_bridge_source.index("def connection_inventory"): _bridge_source.index("class BridgeHandler")])


check("Chrome, PowerShell and CMake prerequisites are inventoried", all(term in _bridge_source for term in ("Chrome DevTools MCP prerequisite", "PowerShell 7", "Windows PowerShell", "CMake CLI")))


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


check("approve() is risk-gated by the decision layer",


      "decisions.risk_gate" in (_checkout / "loki.py").read_text(encoding="utf-8"))


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



section("no dependence on any single provider")
check("an HTTP 400 (tool list refused) fails over instead of ending the run",
      loki._is_limit_error(Exception("[model error] m answered HTTP 400: maximum number of items is 128")) is True)
check("an HTTP 429 fails over", loki._is_limit_error(Exception("HTTP 429 quota")) is True)
check("a genuine 500 is not mistaken for a limit",
      loki._is_limit_error(Exception("HTTP 500 server exploded")) is False)
check("smart mode offers a zero-key/local landing spot",
      "vireonix" in loki.SMART_ORDER and "local" in loki.SMART_ORDER)



NL = chr(10)
section("chat text normalisation")
check("a mangled character is dropped",
      loki.clean_text("passed" + chr(0xFFFD)) == "passed")
check("runaway blank lines collapse",
      loki.clean_text("a" + NL * 5 + "b") == "a" + NL + NL + "b")
check("carriage returns normalise", loki.clean_text("a" + chr(13) + "b") == "a" + NL + "b")
check("a repeated reply is stored once",
      len(loki._sanitize_history([{"role": "assistant", "content": "same"},
                                  {"role": "assistant", "content": "same"}])) == 1)
check("distinct replies both survive",
      len(loki._sanitize_history([{"role": "assistant", "content": "a"},
                                  {"role": "assistant", "content": "b"}])) == 2)

section("go-to model: DeepSeek 4.1 via OpenRouter")
check("the deepseek-4.1 alias exists", "deepseek-4.1" in loki.MODELS)
check("it points at deepseek v4.1 flash",
      "v4.1" in loki.MODELS["deepseek-4.1"].model, loki.MODELS["deepseek-4.1"].model)
check("OpenRouter leads smart mode", loki.SMART_ORDER[0] == "openrouter", loki.SMART_ORDER[0])



section("account connection")
check("every connectable provider maps to an env var",
      set(loki.PROVIDER_ENV_VARS) >= {"openrouter", "gemini", "groq", "deepseek"})
check("an unknown provider is refused",
      loki.connect_provider("nope", "x")["ok"] is False)
check("an empty key is refused",
      loki.connect_provider("openrouter", "")["ok"] is False)
check("a rejected key is reported, not saved",
      loki.verify_provider_key("openrouter", "sk-or-definitely-not-real") != "")
check("the env file path is absolute-ish", str(loki.env_file_path()).endswith(".env"), str(loki.env_file_path()))



section("modes: ask -> plan -> build")
check("the default mode is build", loki.set_mode("build") == "build")
loki.set_mode("ask")
check("ask offers no tools at all", loki.model_tool_schemas() == [])
loki.set_mode("plan")
_plan = {s["function"]["name"] for s in loki.model_tool_schemas()}
check("plan can still read", "read_file" in _plan, str(sorted(_plan)[:4]))
check("plan offers no writing tool", not (_plan & loki.MODIFYING), str(sorted(_plan & loki.MODIFYING)))
check("plan offers no running tool", not (_plan & loki.DANGEROUS), str(sorted(_plan & loki.DANGEROUS)))
loki.set_mode("build")
check("build offers more than plan", len(loki.model_tool_schemas()) > len(_plan))
check("an unknown mode changes nothing", loki.set_mode("nonsense") == "build")
loki.set_mode("ask")
_ask_prompt = loki.system_prompt()
loki.set_mode("plan")
_plan_prompt = loki.system_prompt()
loki.set_mode("build")
check("each mode carries its own instructions",
      "ASK mode" in _ask_prompt and "PLAN mode" in _plan_prompt
      and ("SENIOR GAME DEVELOPER" in loki.system_prompt()
           or "desktop command center" in loki.system_prompt()))
check("mode_state lists all three", len(loki.mode_state()["modes"]) == 3)



section("a provider message object can never crash the run")


class _FakeFunction:
    name = "read_file"
    arguments = '{"filename": "a.gd"}'


class _FakeCall:
    id = "call_1"
    function = _FakeFunction()


class _FakeMessage:
    """Stands in for openai's ChatCompletionMessage: attributes, no .get()."""

    role = "assistant"
    content = None
    tool_calls = [_FakeCall()]

    def model_dump(self) -> dict:
        raise RuntimeError("this dump path is broken on purpose")


_converted = loki._as_dict(_FakeMessage())
check("a provider message object converts to a plain dict",
      isinstance(_converted, dict) and _converted.get("role") == "assistant")
check("tool calls survive the conversion",
      bool(_converted.get("tool_calls"))
      and _converted["tool_calls"][0]["function"]["name"] == "read_file")
check("the converted message is JSON-serializable", json.dumps(_converted) != "")
check("sanitizing history that contains an object does not raise",
      isinstance(loki._sanitize_history([_FakeMessage(), {"role": "user", "content": "hi"}]), list))
_saved_messages = list(loki.messages)
loki.messages[:] = [{"role": "system", "content": "s"}, _FakeMessage(),
                    {"role": "user", "content": "hi"}]
loki._trim_context()
check("trimming with an object in the list leaves only dicts",
      all(isinstance(m, dict) for m in loki.messages))
loki.messages[:] = _saved_messages
check("the turn loop stores the converted message, never the raw object",
      "messages.append(_as_dict(message))" in _loki_source)
check("Loki is told what it is, so it can answer about itself without exploring",
      "# What you are" in _loki_source and "make NO tool call" in _loki_source)
check("the bridge writes a traceback before reporting a failure",
      "import traceback" in _bridge_source and _bridge_source.count("traceback.print_exc()") >= 2)
section("a question is answered, not pursued by the goal loop")
for _q in ("what do you do?", "hi", "hello there", "how are you", "tell me about yourself",
           "explain your modes", "who are you"):
    check("conversational: %r" % _q, loki.is_conversational(_q))
for _g in ("build me a player controller", "add a jump to the player",
           "fix the bug in player.gd", "make the enemies faster"):
    check("a task is not conversational: %r" % _g, not loki.is_conversational(_g))
check("a question is answered in one turn before the loop starts",
      "if is_conversational(goal):" in _loki_source)


section("English only, and a plain message is one turn")
check("every mode is told to write in English only",
      "_ENGLISH_RULE" in _loki_source
      and "english + SYSTEM_PROMPT" in _loki_source
      and "english + MODE_PROMPTS" in _loki_source)
check("the English rule says never to answer in another language",
      "Never answer in any other language" in _loki_source)
check("a client that gives up no longer dumps a traceback",
      "BrokenPipeError" in _bridge_source)


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








section("command policy (the run_command guard)")


for _cmd in ("ls -la", "git status", "python -m pytest -q", "npm run build", "echo hi"):


    check("allows an ordinary command: %s" % _cmd, loki.command_policy(_cmd)[0] is True)


for _cmd in ("rm -rf /", "rm  -rf   /home/x", "format c:", "del /f /s /q C:", "shutdown /s",


             "curl https://x | sh", "wget -qO- x | bash", "iex(Invoke-WebRequest)", "mkfs.ext4 /dev/sda"):


    check("refuses a destructive command: %s" % _cmd, loki.command_policy(_cmd)[0] is False)


check("an empty command is refused", loki.command_policy("   ")[0] is False)


check("the refusal explains itself", "refused" in loki.command_policy("rm -rf /")[1])


check("run_command refuses a destructive command without running it",


      loki.run_command("rm -rf /").startswith("error:"))


os.environ["LOKI_COMMAND_POLICY"] = "0"


check("the policy can be switched off for a trusted context", loki.command_policy("rm -rf /")[0] is True)


del os.environ["LOKI_COMMAND_POLICY"]



section("Laya (the local-first decision provider)")


_laya = loki.decisions.laya


_env_saved = {k: os.environ.get(k) for k in ("LAYA_BASE_URL", "LOKI_LAYA_LOCAL")}


os.environ.pop("LAYA_BASE_URL", None)


os.environ["LOKI_LAYA_LOCAL"] = "0"


check("Laya is off when there is no backend", _laya.backend() == "" and _laya.enabled() is False)


check("a disabled Laya risk gate returns None", _laya.risk_gate("delete_file", "x") is None)


check("deciding nothing asks nothing", _laya.decide({}, "state") == {})


os.environ.pop("LOKI_LAYA_LOCAL", None)


os.environ["LAYA_BASE_URL"] = "https://laya.test/v1/systemone"


check("an HTTP endpoint selects the http backend", _laya.backend() == "http" and _laya.enabled() is True)


_orig_http = _laya._http_decide


_laya._http_decide = lambda payload: {"answers": {"q": {"type": "noul", "noul": 0.25}}}


_laya._cache.clear()


check("a decision parses the answers map", _laya.decide({"q": {"type": "noul", "instructions": "?"}}, "s").get("q", {}).get("noul") == 0.25)


check("noul() returns the calibrated probability", _laya.noul("?", "s") == 0.25)


def _laya_boom(payload):


    raise RuntimeError("backend down")


_laya._http_decide = _laya_boom


_laya._cache.clear()


check("a failing Laya backend is non-fatal", _laya.decide({"q": {"type": "noul", "instructions": "?"}}, "s2") == {})


_laya._http_decide = _orig_http


_laya._cache.clear()


os.environ.pop("LAYA_BASE_URL", None)


for _k, _v in _env_saved.items():


    if _v is None:


        os.environ.pop(_k, None)


    else:


        os.environ[_k] = _v


check("the local driver ships as a Node module", (loki.ROOT / "laya_driver.mjs").is_file())


check("the driver delegates to the real @receptron/laya package", "@receptron/laya" in (loki.ROOT / "laya_driver.mjs").read_text(encoding="utf-8"))


_loki_src = (loki.ROOT / "loki.py").read_text(encoding="utf-8")


check("approvals route through the decision layer", "decisions.risk_gate(kind, detail)" in _loki_src)


check("loop detection routes through the decision layer", "decisions.loop_nudge" in _loki_src)


section("decision routing (Laya first, Jev fallback)")


_dec = loki.decisions


class _FakeProvider:


    def __init__(self, enabled=True, gate=None, noul=None):


        self._enabled = enabled


        self._gate = gate


        self._noul = noul


    def enabled(self):


        return self._enabled


    def risk_gate(self, kind, detail):


        return self._gate


    def noul(self, question, state, criteria=None):


        return self._noul


    def status(self):


        return {}


_orig_providers = dict(_dec.PROVIDERS)


_orig_order = os.environ.get("LOKI_DECISION_ORDER")


os.environ["LOKI_DECISION_ORDER"] = "laya,jev"


_dec.PROVIDERS = {"laya": _FakeProvider(gate="allow"), "jev": _FakeProvider(gate="allow")}


check("providers agreeing to allow -> allow", _dec.risk_gate("write_file", "x") == "allow")


_dec.PROVIDERS = {"laya": _FakeProvider(gate="allow"), "jev": _FakeProvider(gate="confirm")}


_disagreements_before = _dec.STATS["disagreements"]


check("providers disagreeing -> ask (None)", _dec.risk_gate("write_file", "x") is None)


check("a disagreement is recorded", _dec.STATS["disagreements"] == _disagreements_before + 1)


_dec.PROVIDERS = {"laya": _FakeProvider(gate=None), "jev": _FakeProvider(gate="allow")}


check("one provider deciding is enough", _dec.risk_gate("write_file", "x") == "allow")


_dec.PROVIDERS = {"laya": _FakeProvider(gate=None), "jev": _FakeProvider(gate=None)}


check("no provider deciding -> ask (None)", _dec.risk_gate("write_file", "x") is None)


_dec.PROVIDERS = {"laya": _FakeProvider(enabled=False, noul=0.99), "jev": _FakeProvider(noul=0.95)}


check("a disabled provider is skipped in the loop nudge", _dec.loop_nudge("state") == "0.95")


_dec.PROVIDERS = {"laya": _FakeProvider(noul=0.4), "jev": _FakeProvider(noul=0.9)}


check("a confident spinning report wins", _dec.loop_nudge("state") == "0.90")


_dec.PROVIDERS = {"laya": _FakeProvider(noul=0.1), "jev": _FakeProvider(noul=0.2)}


check("low confidence does not nudge", _dec.loop_nudge("state") == "")


_dec.PROVIDERS = dict(_orig_providers)


if _orig_order is None:


    os.environ.pop("LOKI_DECISION_ORDER", None)


else:


    os.environ["LOKI_DECISION_ORDER"] = _orig_order


check("the decision status names the order and both providers", set(_dec.status()["order"]) == {"laya", "jev"})


check("loki exposes a decision status for the bridge", isinstance(loki.decision_status(), dict))



section("injected-input probe (run a scene and feed it inputs)")


import godot_assets as _godot_assets  # noqa: E402
check("the probe script ships as engine data, not a .gd file", "extends SceneTree" in _godot_assets.PROBE_GD)


_probe_src = _godot_assets.PROBE_GD


check("the harness holds each press for at least two physics frames",


      "MIN_HOLD_PHYSICS := 2" in _probe_src and "Engine.get_physics_frames()" in _probe_src)


check("the harness is driven by a sidecar, not text substitution",


      "SIDECAR" in _probe_src and "res://.godot/loki_probe.json" in _probe_src)


check("the harness reports the clamp it applied", "clamp_applied" in _probe_src)


check("probe_scene has a tool schema", any(t["function"]["name"] == "probe_scene" for t in loki.TOOL_SCHEMAS))


check("probe_scene is offered to the model", "probe_scene" in loki.MODEL_TOOL_NAMES)


check("probe_scene is in the runtime category", "probe_scene" in loki.TOOL_CATEGORIES["runtime"])


check("probe_scene rejects non-JSON inputs", loki.probe_scene("res://x.tscn", "nope").startswith("error:"))


check("probe_scene rejects a non-array inputs value", loki.probe_scene("res://x.tscn", "{\"a\": 1}").startswith("error:"))



section("free providers from awesome-free-llm-apis")


_free_apis = ("aion", "cohere", "zai", "huggingface", "kilocode", "llm7",


              "modelscope", "nvidia", "ollama-cloud", "ovh", "siliconflow")


for _name in _free_apis:


    check("%s is registered" % _name, _name in loki.MODELS)


    check("%s has a base_url and a model" % _name,


          bool(loki.MODELS[_name].base_url) and bool(loki.MODELS[_name].model))


check("the new providers are NOT in the smart failover order",


      not (set(_free_apis) & set(loki.SMART_ORDER)))



section("capability registry (the API Vault seed)")


_caps = loki.capability_registry()


check("the registry is non-empty", len(_caps) > 0)


check("every entry has an id, a kind and a status",


      all(e.get("id") and e.get("kind") and e.get("status") for e in _caps))


check("every kind is a documented kind",


      all(e.get("kind") in loki.capabilities.KINDS for e in _caps))


check("every provider carries an endpoint",


      all(e.get("source") for e in _caps if e.get("kind") in ("provider", "cli-agent")))


check("the mode pseudo-providers are not entries",


      not any(e.get("id") in ("smart", "online") for e in _caps))


check("a provider can be found by name",


      any(e["id"] == "zai" for e in loki.capabilities.search(_caps, "zai")))


check("an empty query returns everything",


      len(loki.capabilities.search(_caps, "")) == len(_caps))


_sum = loki.capability_summary()


check("the summary total matches the registry", _sum["total"] == len(_caps))


check("statuses are the documented set",


      set(_sum["by_status"]) <= {"ready", "needs_key", "disabled", "unavailable"})


check("the registry is offered to the model", "list_capabilities" in loki.MODEL_TOOL_NAMES)


check("it has its own tool category",


      loki.TOOL_CATEGORIES.get("capabilities") == ["list_capabilities"])



section("resumable project state (blueprint 7.3)")


import tempfile


import project_state as _ps


_tmp = Path(tempfile.mkdtemp()) / "state.json"


_blank = _ps.load(_tmp)


check("a missing state reads as blank", _blank["objective"] == "" and _blank["next_actions"] == [])


_ps.set_field(_blank, "objective", "ship it")


_ps.add(_blank, "next_actions", "write docs")


_ps.add(_blank, "next_actions", "write docs")


_ps.save(_tmp, _blank)


_reloaded = _ps.load(_tmp)


check("state round-trips through disk", _reloaded["objective"] == "ship it")


check("duplicate list items collapse", _reloaded["next_actions"] == ["write docs"])


check("save stamps an updated time", bool(_reloaded["updated"]))


check("an unknown field is refused", "unknown" in _ps.add(_reloaded, "nonsense", "x"))


check("render shows the objective", "ship it" in _ps.render(_reloaded))


check("every blueprint field is present", all(f in _reloaded for f in _ps.FIELDS))


check("project_state is offered to the model", "project_state" in loki.MODEL_TOOL_NAMES)


check("project_state is in the planning category", "project_state" in loki.TOOL_CATEGORIES["planning"])


check("the bridge exposes /state", 'route == "/state"' in (_checkout / "loki_bridge.py").read_text(encoding="utf-8"))


check("the prompt tells the agent to keep the state", "RESUMABLE PROJECT STATE" in loki.SYSTEM_PROMPT)



section("repository browser (blueprint 5.1)")


import repo_review as _rr


import tempfile as _tf


_tmpdir = Path(_tf.mkdtemp())


(_tmpdir / "LICENSE").write_text("MIT", encoding="utf-8")


(_tmpdir / "README.md").write_text("hi", encoding="utf-8")


(_tmpdir / "a.py").write_text("x = 1", encoding="utf-8")


(_tmpdir / "project.godot").write_text("config_version=5", encoding="utf-8")


(_tmpdir / "node_modules").mkdir()


(_tmpdir / "node_modules" / "junk.js").write_text("junk", encoding="utf-8")


_report = _rr.review(_tmpdir)


check("the review finds the licence", _report["licence"] == "LICENSE")


check("the review finds the readme and the manifest",


      _report["readme"] == "README.md" and "project.godot" in _report["manifests"])


check("the review counts the files, skipping node_modules", _report["files"] == 4)


check("the review lists languages", _report["languages"].get("py") == 1)


check("the review is read-only and says so", "nothing was executed" in _rr.render(_report))


check("a missing folder is reported, not raised", "not a folder" in _rr.review(_tmpdir / "nope").get("error", ""))


check("review_repository is offered to the model", "review_repository" in loki.MODEL_TOOL_NAMES)


check("review_repository has a schema", any(t["function"]["name"] == "review_repository" for t in loki.TOOL_SCHEMAS))



section("agent sessions - the herdr registry (blueprint 9 / 7.1)")


import sessions as _se


_reg = _se.empty()


_s = _se.add(_reg, "alpha", "projA", "claude-code", "working", "wire the dock")


check("add records who, where and what", _s["status"] == "working" and _s["agent"] == "claude-code")


_se.add(_reg, "beta", "projB", "codex", "blocked", "needs a key")


_se.add(_reg, "gamma", "projA", "loki", "idle")


_sums = _se.summary(_reg)


check("the summary counts each state", _sums["working"] == 1 and _sums["blocked"] == 1 and _sums["idle"] == 1 and _sums["total"] == 3)


check("the summary names who is stuck", _sums["needs_attention"] == ["beta"])


check("update flips a state", _se.update(_reg, "beta", status="working") and _se.summary(_reg)["blocked"] == 0)


check("close marks a session done", _se.close(_reg, "alpha") and _se.summary(_reg)["done"] == 1)


check("a session can be addressed by id as well as name", _se.update(_reg, _s["id"], status="idle"))


check("an unknown session is refused, not invented", _se.update(_reg, "nope", status="working") is False)


check("a bogus status is ignored rather than stored", _se.update(_reg, "gamma", status="banana") and _se.summary(_reg)["total"] == 3)


check("the render shows every session", "alpha" in _se.render(_reg) and "gamma" in _se.render(_reg))


check("an empty registry renders, not crashes", _se.render(_se.empty()) == "no agent sessions")


check("agent_sessions is offered to the model", "agent_sessions" in loki.MODEL_TOOL_NAMES)


check("agent_sessions has a schema", any(tt["function"]["name"] == "agent_sessions" for tt in loki.TOOL_SCHEMAS))



section("the API Vault (blueprint 3.3)")


import api_vault as _av


_payload = {"example.com": {"preferred": "1.0", "versions": {"1.0": {


    "info": {"title": "Example API", "contact": {"url": "https://example.com"}},


    "x-origin": [{"url": "https://api.example.com"}],


    "x-providerName": "example",


    "x-apisguru-categories": ["developer_tools"],


    "swagger": {"securityDefinitions": {"apiKey": {"type": "apiKey"}}},


}}}}


_v = _av.import_apis_guru(_payload)


_ve = _v["entries"][0]


check("a catalog entry keeps its name and reachable url", _ve["name"] == "Example API" and _ve["url"] == "https://api.example.com")


check("the provider and categories survive", _ve["provider"] == "example" and _ve["categories"] == ["developer_tools"])


check("a keyed API is marked as needing a key", _ve["auth"] == "key")


check("the source is recorded", _ve["source"] == "apis.guru")


check("search finds it by a word", len(_av.search(_v, "example")) == 1)


check("search filters by category", len(_av.search(_v, category="developer_tools")) == 1 and len(_av.search(_v, category="music")) == 0)


check("search filters by auth", len(_av.search(_v, auth="key")) == 1 and len(_av.search(_v, auth="none")) == 0)


_av.add(_v, "Other API", "https://other.example", "other", ["music"], "none")


check("add records a second entry", _av.stats(_v)["total"] == 2)


_av.add(_v, "Other API", "https://other.example/v2", "other", ["music"], "none")


check("add updates rather than duplicates by id", _av.stats(_v)["total"] == 2 and _av.search(_v, "other")[0]["url"].endswith("/v2"))


check("stats counts by auth", _av.stats(_v)["by_auth"].get("key") == 1)


check("the render explains the auth marks", "needs a key" in _av.render(_av.search(_v)))


check("an empty vault renders, not crashes", "no matching APIs" in _av.render(_av.empty()))


_seed = _av.load(loki.VAULT_SEED)


check("the shipped vault is present and large", _av.stats(_seed)["total"] >= 1000)


check("the shipped vault is searchable offline", len(_av.search(_seed, "weather")) >= 1)


check("Loki's own providers are in the vault", len(_av.search(_seed, query="openai-compatible")) >= 5)


check("the vault never stores a key", not any("api_key" in e for e in _seed["entries"]))


check("api_vault is offered to the model", "api_vault" in loki.MODEL_TOOL_NAMES)


check("api_vault has a schema", any(s["function"]["name"] == "api_vault" for s in loki.TOOL_SCHEMAS))


section("provider failover inside a real turn (routing regression)")
# These drive agent_turn itself with a fake model client, because the old tests only
# called failover_target() alone and missed the bug: _model_request marked the failing
# provider, then agent_turn re-resolved "the spent provider" - which by then named the
# NEXT one - and marked that too. One quota error skipped a ready provider (with two
# keys set it fell through to "local" and reported "Ollama is not running").
import types as _types  # noqa: E402

_fo_saved = (loki.provider_configured, loki.make_client, loki.refresh_mcp_tools,
             loki.model_name, set(loki._SMART_FAILED), list(loki.messages), loki.MODEL_RETRIES)


def _fo_run(mode, ready, fail_on, status=429, text="You exceeded your current quota"):
    """Run one agent_turn; return (providers tried, used-up set, answer or error, mode after)."""
    tried = []

    class _Completions:
        def __init__(self, provider):
            self.provider = provider

        async def create(self, **kwargs):
            tried.append(self.provider)
            if self.provider in fail_on:
                response = _types.SimpleNamespace(status_code=status, headers={}, request=None)
                raise loki.openai.APIStatusError(text, response=response, body=None)
            message = _types.SimpleNamespace(content="answer from " + self.provider, tool_calls=None)
            return _types.SimpleNamespace(choices=[_types.SimpleNamespace(message=message)])

    def _client():
        name = loki.active_model_name()
        return _types.SimpleNamespace(chat=_types.SimpleNamespace(completions=_Completions(name)))

    async def _no_refresh(*args, **kwargs):
        return []

    loki.provider_configured = lambda name: name in ready
    loki.make_client = _client
    loki.refresh_mcp_tools = _no_refresh
    loki.MODEL_RETRIES = 0
    loki.model_name = mode
    loki._SMART_FAILED.clear()
    loki.ROUTE_TRACE.clear()
    loki.messages[:] = [{"role": "system", "content": "test"}, {"role": "user", "content": "hi"}]
    try:
        outcome = asyncio.run(loki.agent_turn())
    except loki.ModelUnavailable as exc:
        outcome = "ERROR: " + str(exc)
    return tried, set(loki._SMART_FAILED), outcome, loki.model_name


try:
    _t, _used, _out, _ = _fo_run("smart", {"openrouter", "gemini", "groq"}, {"openrouter"})
    check("a spent quota moves to the NEXT ready provider, not the one after",
          _t == ["openrouter", "gemini"], _t)
    check("only the provider that failed is marked used-up", _used == {"openrouter"}, _used)
    check("the turn is answered by the next provider", _out == "answer from gemini", _out)
    check("the switch is recorded with its reason",
          [(r["provider"], r["reason"], r["next"]) for r in loki.ROUTE_TRACE]
          == [("openrouter", "quota spent", "gemini")], loki.ROUTE_TRACE)

    _t, _used, _out, _ = _fo_run("smart", {"openrouter", "gemini"}, {"openrouter"})
    check("with two keys, a spent quota uses the second key (never an unset local model)",
          _t == ["openrouter", "gemini"] and _out == "answer from gemini", (_t, _out))

    _t, _used, _out, _mode = _fo_run("online", {"openrouter", "gemini", "local"}, {"openrouter"})
    check("online mode stays online after a failover", _mode == "online", _mode)
    check("online failover never reaches a local model", "local" not in _t, _t)

    _t, _used, _out, _ = _fo_run("smart", {"openrouter", "gemini"}, {"openrouter"},
                                 status=401, text="Incorrect API key provided")
    check("smart mode skips a provider whose key is rejected", _out == "answer from gemini", (_t, _out))
    check("a rejected key is recorded as such",
          bool(loki.ROUTE_TRACE) and loki.ROUTE_TRACE[0]["reason"] == "key rejected", loki.ROUTE_TRACE)

    _t, _used, _out, _mode = _fo_run("gemini", {"gemini", "groq"}, {"gemini"},
                                     status=401, text="Incorrect API key provided")
    check("a PINNED provider with a bad key surfaces the error (no silent switch)",
          _out.startswith("ERROR:") and _t == ["gemini"] and _mode == "gemini", (_t, _out, _mode))

    _t, _used, _out, _ = _fo_run("smart", {"openrouter"}, {"openrouter"})
    check("with nothing else configured, the ORIGINAL error is shown",
          _out.startswith("ERROR:") and "quota" in _out.lower() and _t == ["openrouter"], (_t, _out))

    _t, _used, _out, _ = _fo_run("smart", {"openrouter", "gemini"}, {"openrouter"},
                                 status=400, text="KeyError: objects")
    check("an HTTP 400 still fails over (existing behaviour kept)", _out == "answer from gemini", (_t, _out))
finally:
    (loki.provider_configured, loki.make_client, loki.refresh_mcp_tools,
     loki.model_name, _fo_failed, _fo_messages, loki.MODEL_RETRIES) = _fo_saved
    loki._SMART_FAILED.clear()
    loki._SMART_FAILED.update(_fo_failed)
    loki.messages[:] = _fo_messages
    loki.ROUTE_TRACE.clear()

check("should_fail_over: a quota error always fails over", loki.should_fail_over(Exception("quota"), False))
check("should_fail_over: a rejected key fails over only when auto-routing",
      loki.should_fail_over(Exception("HTTP 401: invalid api key"), True)
      and not loki.should_fail_over(Exception("HTTP 401: invalid api key"), False))
check("should_fail_over: an ordinary bug never fails over",
      not loki.should_fail_over(Exception("KeyError: objects"), True))
check("the route trace masks key-shaped strings",
      "sk-or-v1-abcdef0123456789" not in loki.redact_secrets("Incorrect API key provided: sk-or-v1-abcdef0123456789")
      and "[redacted]" in loki.redact_secrets("Bearer abcdefghijklmnop1234"))
check("redaction leaves ordinary error text alone",
      loki.redact_secrets("HTTP 429: quota exceeded") == "HTTP 429: quota exceeded")
check("the bridge reports the route on /health",
      '"route": route_trace' in (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8"))


section("verification: DONE is checked, not believed")
import tempfile as _vtf  # noqa: E402

# A missing engine used to read as "INVALID - fix these errors", so the model "fixed"
# files that were fine. It must now say NOT VERIFIED and say it is not the file's fault.
_v_saved_exe = loki.GODOT_EXE
loki.GODOT_EXE = str(Path(_vtf.gettempdir()) / "no-such-godot" / "godot.exe")
try:
    _vs = loki.validate_scene("main.tscn", timeout=5)
    check("validate_scene without Godot says NOT VERIFIED, not INVALID",
          loki.NOT_VERIFIED in _vs and "INVALID" not in _vs, _vs[:120])
    _vc = loki.check_script("player.gd")
    check("check_script without Godot says NOT VERIFIED", loki.NOT_VERIFIED in _vc, _vc[:120])
    _vp = loki.play_scene("main.tscn", 1)
    check("play_scene without Godot says NOT VERIFIED", loki.NOT_VERIFIED in _vp, _vp[:120])
    check("a missing engine is classified unverified, never failed", loki._verdict(_vs) == "unverified")
finally:
    loki.GODOT_EXE = _v_saved_exe

_v_saved_env = os.environ.get("GODOT_EXE")
os.environ["GODOT_EXE"] = "/explicit/godot"
check("GODOT_EXE from the environment wins", loki.resolve_godot_exe() == "/explicit/godot")
if _v_saved_env is None:
    del os.environ["GODOT_EXE"]
else:
    os.environ["GODOT_EXE"] = _v_saved_env
check("the Godot default is no longer one developer's G: drive",
      'os.getenv("GODOT_EXE", "G:/' not in (REPO / "engine" / "loki.py").read_text(encoding="utf-8"))

check("build_scene counts as modifying (DONE after it is not 'premature')", "build_scene" in loki.MODIFYING)
check("project.godot editors count as modifying",
      {"add_input_action", "set_project_setting", "add_autoload"} <= loki.MODIFYING)
_v_saved_mode = loki.AGENT_MODE
loki.set_mode("plan")
_v_plan = {t["function"]["name"] for t in loki.model_tool_schemas()}
loki.set_mode(_v_saved_mode)
check("plan mode offers no writing tool", not (_v_plan & loki.MODIFYING), sorted(_v_plan & loki.MODIFYING))
check("plan mode offers no tool that runs the game", not (_v_plan & loki.RUNS_PROJECT),
      sorted(_v_plan & loki.RUNS_PROJECT))
check("plan mode still reads and compile-checks", {"read_file", "search_files", "check_script"} <= _v_plan)

check("touched path: write_file", loki._touched_path("write_file", {"filename": "a.gd"}) == "a.gd")
check("touched path: move_file records the destination",
      loki._touched_path("move_file", {"src": "a.gd", "dst": "b.gd"}) == "b.gd")
check("touched path: settings tools record project.godot",
      loki._touched_path("add_autoload", {"name": "G", "path": "g.gd"}) == "project.godot")
check("touched path: delete_file records nothing", loki._touched_path("delete_file", {"path": "a.gd"}) == "")

# Fake checkers: Godot cannot run in every test environment. Everything else is real:
# the workspace (a temp dir), the files, verify_files, the goal loop and agent_turn.
_v_saved = (loki.WORKSPACE, loki.check_script, loki.validate_scene, loki.save_history, loki.todo_clear,
            loki.provider_configured, loki.make_client, loki.refresh_mcp_tools, loki.model_name,
            set(loki._SMART_FAILED), list(loki.messages), loki.MODEL_RETRIES, loki.AGENT_MODE)
_v_ws = Path(_vtf.mkdtemp())


def _v_check_script(filename):
    text = loki.resolve_in_workspace(filename).read_text(encoding="utf-8")
    if "BROKEN" in text:
        return "check_script res://%s: ERRORS - fix these:\nParse Error: unexpected token" % filename
    return "check_script res://%s: compiles OK\n" % filename


def _v_validate(filename, timeout=90):
    return "validate_scene res://%s: valid - Godot loaded it cleanly.\n" % filename


def _v_turns(script):
    """A fake model that plays `script`: a list of ("tool", name, args) or ("say", text)."""
    steps = list(script)
    seen = []

    class _C:
        async def create(self, **kwargs):
            seen.append(len(kwargs["messages"]))
            step = steps.pop(0) if steps else ("say", "DONE: nothing left")
            if step[0] == "tool":
                call = _types.SimpleNamespace(id="c%d" % len(seen), type="function",
                                              function=_types.SimpleNamespace(
                                                  name=step[1], arguments=json.dumps(step[2])))
                msg = _types.SimpleNamespace(role="assistant", content="", tool_calls=[call])
            else:
                msg = _types.SimpleNamespace(role="assistant", content=step[1], tool_calls=None)
            return _types.SimpleNamespace(choices=[_types.SimpleNamespace(message=msg)])

    loki.make_client = lambda: _types.SimpleNamespace(chat=_types.SimpleNamespace(completions=_C()))
    return seen, steps


async def _v_noop(*args, **kwargs):
    return []


try:
    loki.WORKSPACE = _v_ws
    loki.check_script = _v_check_script
    loki.validate_scene = _v_validate
    loki.save_history = lambda: None
    loki.todo_clear = lambda: "cleared"   # never touch the user's real plan.md
    loki.refresh_mcp_tools = _v_noop
    loki.provider_configured = lambda name: name == "openrouter"
    loki.model_name = "smart"
    loki._SMART_FAILED.clear()
    loki.MODEL_RETRIES = 0
    loki.AGENT_MODE = "build"

    (_v_ws / "ok.gd").write_text("extends Node\n", encoding="utf-8")
    (_v_ws / "bad.gd").write_text("BROKEN\n", encoding="utf-8")
    (_v_ws / "data.json").write_text("{not json", encoding="utf-8")
    (_v_ws / "notes.md").write_text("hi", encoding="utf-8")
    _vr = loki.verify_files(["ok.gd", "bad.gd", "data.json", "notes.md", "gone.gd"])
    check("verify_files: a compiling script is ok", _vr["ok"] == ["ok.gd"], _vr)
    check("verify_files: a broken script and bad JSON fail",
          [p for p, _ in _vr["failed"]] == ["bad.gd", "data.json"], _vr["failed"])
    check("verify_files: a deleted file is reported, not passed",
          ("gone.gd", "no longer exists") in _vr["unverified"], _vr["unverified"])
    check("verify_files: an uncheckable type is listed as such", _vr["skipped"] == ["notes.md"], _vr)
    _vsum = loki.verification_summary(_vr)
    check("the summary names what failed and what was not checked",
          "FAILED (bad.gd, data.json)" in _vsum and "not verified" in _vsum and "no automatic check" in _vsum, _vsum)

    # The goal loop: the model writes a broken script and claims DONE. The DONE must be
    # refused with the real error, the model fixes it, and only then is DONE accepted.
    loki.messages[:] = [{"role": "system", "content": "test"}]
    _seen, _left = _v_turns([
        ("tool", "write_file", {"filename": "player.gd", "content": "BROKEN\n"}),
        ("say", "DONE: added the player"),
        ("tool", "write_file", {"filename": "player.gd", "content": "extends CharacterBody3D\n"}),
        ("say", "DONE: added the player (fixed)"),
    ])
    _vout = asyncio.run(loki.pursue_goal("create a player controller script"))
    check("a DONE over a broken script is refused",
          any("Automatic verification" in str(m.get("content", "")) and "Parse Error" in str(m.get("content", ""))
              for m in loki.messages if m.get("role") == "user"))
    check("after the fix, DONE is accepted with a verification line",
          _vout.startswith("DONE: added the player (fixed)") and "1 checked OK (player.gd)" in _vout, _vout)
    check("the fix round used the scripted turns, no more", not _left, _left)

    # Bounded: a model that never fixes it is not looped forever; the user is told.
    loki.messages[:] = [{"role": "system", "content": "test"}]
    _rounds = loki.VERIFY_FIX_ROUNDS
    _v_turns([("tool", "write_file", {"filename": "enemy.gd", "content": "BROKEN\n"})]
             + [("say", "DONE: enemy")] * (_rounds + 1))
    _vout = asyncio.run(loki.pursue_goal("create an enemy script"))
    check("an unfixed error ends after the bounded rounds, reported as FAILED",
          _vout.startswith("DONE: enemy") and "FAILED (enemy.gd)" in _vout, _vout)

    # The chat path gets one repair round.
    loki.messages[:] = [{"role": "system", "content": "test"}]
    _v_turns([
        ("tool", "write_file", {"filename": "hud.gd", "content": "BROKEN\n"}),
        ("say", "I added the HUD."),
        ("tool", "edit_file", {"filename": "hud.gd", "old": "BROKEN", "new": "extends Control"}),
        ("say", "Fixed the HUD script."),
    ])
    _vout = asyncio.run(loki.run_agent("add a hud script"))
    check("a chat turn that broke a script gets one repair round and an honest line",
          _vout.startswith("Fixed the HUD script.") and "1 checked OK (hud.gd)" in _vout, _vout)

    # A question that wrote nothing gets no verification noise.
    loki.messages[:] = [{"role": "system", "content": "test"}]
    _v_turns([("say", "Godot uses GDScript.")])
    _vout = asyncio.run(loki.run_agent("what language does Godot use"))
    check("an answer that changed nothing has no verification line", _vout == "Godot uses GDScript.", _vout)

    # Godot missing: DONE is accepted but the user is told it was NOT verified.
    loki.check_script = _v_saved[1]   # the real one: Godot is missing, so NOT VERIFIED
    _v_exe = loki.GODOT_EXE
    loki.GODOT_EXE = ""
    loki.messages[:] = [{"role": "system", "content": "test"}]
    _v_turns([("tool", "write_file", {"filename": "door.gd", "content": "extends Node\n"}),
              ("say", "DONE: door")])
    _vout = asyncio.run(loki.pursue_goal("create a door script"))
    loki.GODOT_EXE = _v_exe
    check("without Godot, DONE says the work was NOT verified (never 'OK')",
          "not verified (door.gd: Godot not found)" in _vout and "checked OK" not in _vout, _vout)
finally:
    (loki.WORKSPACE, loki.check_script, loki.validate_scene, loki.save_history, loki.todo_clear,
     loki.provider_configured, loki.make_client, loki.refresh_mcp_tools, loki.model_name,
     _v_failed, _v_messages, loki.MODEL_RETRIES, loki.AGENT_MODE) = _v_saved
    loki._SMART_FAILED.clear()
    loki._SMART_FAILED.update(_v_failed)
    loki.messages[:] = _v_messages
    loki._task_files.clear()
    import shutil as _vsh  # noqa: E402
    _vsh.rmtree(_v_ws, ignore_errors=True)




section("MCP edits are verified too; paid providers have a budget")
check("an MCP script write records the script",
      loki.mcp_touched_paths("write_script", {"script_path": "res://player.gd", "content": "x"}) == ["player.gd"])
check("a prefixed MCP tool name is recognised",
      loki.mcp_touched_paths("godot_create_scene", {"scene_path": "res://levels/a.tscn"}) == ["levels/a.tscn"])
check("an MCP settings tool records project.godot",
      loki.mcp_touched_paths("set_setting", {"name": "x", "value": 1}) == ["project.godot"])
check("a node path is not mistaken for a file",
      loki.mcp_touched_paths("create_node", {"parent_path": "Player", "node_path": "Player/Cam"}) == [])
check("a read-only MCP tool records nothing",
      loki.mcp_touched_paths("read_script", {"script_path": "res://player.gd"}) == [])

_mb_saved = (dict(loki.mcp_sessions), list(loki._task_files), loki._task_modified)


class _FakeMcp:
    async def call_tool(self, name, args):
        return _types.SimpleNamespace(content=[_types.SimpleNamespace(text='{"script_path": "res://p.gd", "created": true}')])


try:
    loki.mcp_sessions["write_script"] = _FakeMcp()
    loki._task_files.clear()
    loki._task_modified = False
    asyncio.run(loki.call_tool("write_script", {"script_path": "res://p.gd", "content": "extends Node"}))
    check("an MCP write lands in the verification set", loki._task_files == ["p.gd"], loki._task_files)
    check("an MCP write counts as a modification (DONE is not 'premature')", loki._task_modified is True)
finally:
    loki.mcp_sessions.clear()
    loki.mcp_sessions.update(_mb_saved[0])
    loki._task_files[:] = _mb_saved[1]
    loki._task_modified = _mb_saved[2]

check("gpt and claude are metered", loki.is_metered("gpt") and loki.is_metered("claude"))
check("a :free OpenRouter model is not metered", not loki.is_metered("openrouter"))
check("a non-free OpenRouter model is metered", loki.is_metered("deepseek-4.1"))
check("subscription CLIs and local models are not metered",
      not loki.is_metered("claude-code") and not loki.is_metered("local"))
os.environ["LOKI_FREE_PROVIDERS"] = "gpt"
check("LOKI_FREE_PROVIDERS overrides the default", not loki.is_metered("gpt"))
del os.environ["LOKI_FREE_PROVIDERS"]

# Budget: a metered provider stops after PAID_MAX_CALLS model calls in one request.
_pb_saved = (loki.provider_configured, loki.make_client, loki.refresh_mcp_tools, loki.model_name,
             list(loki.messages), loki.PAID_MAX_CALLS, loki.MODEL_RETRIES)


class _LoopForever:
    async def create(self, **kwargs):
        call = _types.SimpleNamespace(id="x", type="function",
                                      function=_types.SimpleNamespace(name="list_files", arguments="{}"))
        msg = _types.SimpleNamespace(role="assistant", content="", tool_calls=[call])
        usage = _types.SimpleNamespace(prompt_tokens=1000, completion_tokens=50)
        return _types.SimpleNamespace(choices=[_types.SimpleNamespace(message=msg)], usage=usage)


async def _pb_noop(*a, **k):
    return []

try:
    loki.provider_configured = lambda n: n == "gpt"
    loki.make_client = lambda: _types.SimpleNamespace(chat=_types.SimpleNamespace(completions=_LoopForever()))
    loki.refresh_mcp_tools = _pb_noop
    loki.model_name = "gpt"
    loki.PAID_MAX_CALLS = 3
    loki.REQUEST_USAGE.clear()
    loki.messages[:] = [{"role": "system", "content": "t"}, {"role": "user", "content": "go"}]
    try:
        asyncio.run(loki.agent_turn())
        _pb = "no stop"
    except loki.BudgetExhausted as exc:
        _pb = str(exc)
    check("a metered provider stops at the paid budget", "paid-provider budget" in _pb, _pb)
    check("it stopped after exactly the budget", loki.REQUEST_USAGE["gpt"]["calls"] == 3, loki.REQUEST_USAGE)
    check("usage counts tokens", loki.REQUEST_USAGE["gpt"]["prompt_tokens"] == 3000, loki.REQUEST_USAGE)
    check("the usage line says it was paid", "(paid)" in loki.usage_summary(), loki.usage_summary())
finally:
    (loki.provider_configured, loki.make_client, loki.refresh_mcp_tools, loki.model_name,
     _pb_msgs, loki.PAID_MAX_CALLS, loki.MODEL_RETRIES) = _pb_saved
    loki.messages[:] = _pb_msgs
    loki.REQUEST_USAGE.clear()



section("self-improvement: experience, learned routing, training data, promotion gate")
import tempfile as _stf  # noqa: E402
import experience as _ex  # noqa: E402

_s_root = Path(_stf.mkdtemp())
_s_env = os.environ.get("LOKI_DATA")
os.environ["LOKI_DATA"] = str(_s_root)

check("outcome: DONE with every file OK is verified",
      _ex.outcome_of("done", {"ok": ["a.gd"], "failed": [], "unverified": []}) == "verified")
check("outcome: an unverifiable file is NOT verified",
      _ex.outcome_of("done", {"ok": ["a.gd"], "failed": [], "unverified": [("b.gd", "Godot not found")]}) == "unverified")
check("outcome: a failed check is failed", _ex.outcome_of("done", {"ok": [], "failed": [("a", "x")]}) == "failed")
check("outcome: a budget stop is blocked", _ex.outcome_of("budget", {}) == "blocked")

# learned order: reorders inside a tier only, and only with enough samples
_tiers = {"a": "free", "b": "free", "c": "free", "p": "paid", "l": "local"}
_stats = {"a": {"samples": 20, "success_rate": 0.2}, "b": {"samples": 20, "success_rate": 0.9},
          "c": {"samples": 3, "success_rate": 1.0}, "p": {"samples": 50, "success_rate": 1.0}}
_lo = _ex.learned_order(["a", "b", "c", "p", "l"], _tiers.get, _stats, min_samples=10)
check("learned routing puts the better free provider first", _lo[:2] == ["b", "a"], _lo)
check("a provider with too few samples keeps its place", _lo[2] == "c", _lo)
check("a perfect PAID provider never jumps ahead of free ones", _lo.index("p") == 3, _lo)
check("no stats, no change", _ex.learned_order(["a", "b"], _tiers.get, {}) == ["a", "b"])
check("loki tiers: local, subscription, paid, free",
      (loki.provider_tier("local"), loki.provider_tier("claude-code"), loki.provider_tier("gpt"),
       loki.provider_tier("gemini")) == ("local", "subscription", "paid", "free"))
check("the tuned model exists but is not routed until promoted",
      "loki-tuned" in loki.MODELS and ("loki-tuned" in loki.SMART_ORDER) == loki.TUNED_PROMOTED)

# End to end through the real request wrappers.
_s_saved = (loki.EXPERIENCE_ENABLED, loki.WORKSPACE, loki.check_script, loki.save_history, loki.todo_clear,
            loki.provider_configured, loki.make_client, loki.refresh_mcp_tools, loki.model_name,
            list(loki.messages), loki.MODEL_RETRIES, loki.AGENT_MODE)
_s_ws = Path(_stf.mkdtemp())


async def _s_noop(*a, **k):
    return []


def _s_script(steps):
    steps = list(steps)

    class _C:
        async def create(self, **kwargs):
            step = steps.pop(0) if steps else ("say", "DONE: end")
            if step[0] == "tool":
                fn = _types.SimpleNamespace(name=step[1], arguments=json.dumps(step[2]))
                msg = _types.SimpleNamespace(role="assistant", content="",
                                             tool_calls=[_types.SimpleNamespace(id="c1", type="function", function=fn)])
            else:
                msg = _types.SimpleNamespace(role="assistant", content=step[1], tool_calls=None)
            return _types.SimpleNamespace(choices=[_types.SimpleNamespace(message=msg)],
                                          usage=_types.SimpleNamespace(prompt_tokens=10, completion_tokens=5))
    loki.make_client = lambda: _types.SimpleNamespace(chat=_types.SimpleNamespace(completions=_C()))


try:
    loki.EXPERIENCE_ENABLED = True
    loki.WORKSPACE = _s_ws
    loki.check_script = lambda f: ("check_script res://%s: ERRORS - fix these:\nParse Error" % f
                                   if "BROKEN" in loki.resolve_in_workspace(f).read_text(encoding="utf-8")
                                   else "check_script res://%s: compiles OK" % f)
    loki.save_history = lambda: None
    loki.todo_clear = lambda: "cleared"
    loki.refresh_mcp_tools = _s_noop
    loki.provider_configured = lambda n: n == "openrouter"
    loki.model_name = "smart"
    loki.MODEL_RETRIES = 0
    loki.AGENT_MODE = "build"

    loki.messages[:] = [{"role": "system", "content": "SECRET USER MEMORY: my dog is Rex"}]
    _s_script([("tool", "write_file", {"filename": "jump.gd",
                                        "content": "extends Node # key sk-or-v1-abcdef0123456789xyz\n"}),
               ("say", "DONE: added jump.gd")])
    asyncio.run(loki.pursue_goal("create a jump script"))
    _log = _ex.entries()
    check("a verified task is logged as verified",
          _log and _log[-1]["outcome"] == "verified" and _log[-1]["provider"] == "openrouter", _log[-1:])
    check("its trajectory is kept", _log[-1]["trajectory"] and len(_ex.trajectories()) == 1)
    _traj = json.dumps(_ex.trajectories()[0])
    check("the trajectory carries the generic system prompt, not the user's memory",
          "Rex" not in _traj and _ex.TRAIN_SYSTEM[:40] in _traj)
    check("secrets are masked in training data", "sk-or-v1-abcdef0123456789xyz" not in _traj and "[redacted]" in _traj)
    check("the trajectory keeps the real tool call", '"name": "write_file"' in _traj)

    loki.messages[:] = [{"role": "system", "content": "t"}]
    _s_script([("say", "GDScript is Godot's language.")])
    asyncio.run(loki.run_agent("what is gdscript"))
    check("a plain answer is logged but never becomes training data",
          _ex.entries()[-1]["outcome"] == "unverified" and len(_ex.trajectories()) == 1)

    loki.messages[:] = [{"role": "system", "content": "t"}]
    _s_script([("tool", "write_file", {"filename": "bad.gd", "content": "BROKEN\n"})]
              + [("say", "DONE: bad")] * (loki.VERIFY_FIX_ROUNDS + 1))
    asyncio.run(loki.pursue_goal("create a bad script"))
    check("a task whose files fail verification is logged failed, not trained on",
          _ex.entries()[-1]["outcome"] == "failed" and len(_ex.trajectories()) == 1, _ex.entries()[-1])

    _ps = _ex.provider_stats()
    check("provider stats count verified and failed work",
          _ps["openrouter"]["verified"] == 1 and _ps["openrouter"]["failed"] == 1, _ps)
finally:
    (loki.EXPERIENCE_ENABLED, loki.WORKSPACE, loki.check_script, loki.save_history, loki.todo_clear,
     loki.provider_configured, loki.make_client, loki.refresh_mcp_tools, loki.model_name,
     _s_msgs, loki.MODEL_RETRIES, loki.AGENT_MODE) = _s_saved
    loki.messages[:] = _s_msgs
    loki._task_files.clear()

# dataset
for _n in range(12):
    _ex.save_trajectory("t%02d" % _n, "goal %d" % (_n % 11), [
        {"role": "user", "content": "do %d" % _n},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "read_file", "arguments": '{"filename": "a.gd"}'}}]},
        {"role": "tool", "tool_call_id": "1", "content": "extends Node"},
        {"role": "assistant", "content": "DONE: ok"}], ["read_file"])
_ds = _ex.build_dataset(_s_root / "ds", {"read_file": {"type": "function", "function": {"name": "read_file"}}})
check("the dataset dedupes by goal and holds some back for evaluation",
      _ds["train"] + _ds["eval"] == 12 and _ds["eval"] >= 1, _ds)
_row = json.loads((_s_root / "ds" / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
check("each example carries the schemas of the tools it used", _row["tools"][0]["function"]["name"] == "read_file")
check("tool arguments are objects, as chat templates expect",
      any(isinstance(c["function"]["arguments"], dict) for m in _row["messages"] for c in m.get("tool_calls", [])))
check("new examples are counted since the last training run",
      _ex.new_examples() == len(_ex.trajectories()))

# the gate and the evaluator
sys.path.insert(0, str(REPO / "tools"))
import self_improve as _si  # noqa: E402

check("first move: a tool call", _si.first_move(_row["messages"])[1] == ("tool", "read_file"))
check("score: same tool 1, other tool 0.5, text 0",
      (_si.score_move(("tool", "read_file"), {"tool_calls": [{"function": {"name": "read_file"}}]}),
       _si.score_move(("tool", "read_file"), {"tool_calls": [{"function": {"name": "list_files"}}]}),
       _si.score_move(("tool", "read_file"), {"content": "hi"})) == (1.0, 0.5, 0.0))
_good = {"model": "cand", "n": 40, "score": 0.80, "errors": 0}
check("promote only when the candidate beats every baseline",
      _si.decide(_good, [{"model": "qwen3:8b", "score": 0.70}])[0]
      and not _si.decide(_good, [{"model": "qwen3:8b", "score": 0.79}])[0])
check("too few held-out tasks is not evidence", not _si.decide({**_good, "n": 3}, [])[0])
check("a candidate that errors a lot is never promoted", not _si.decide({**_good, "errors": 20}, [])[0])
check("a busy GPU blocks training", bool(_si.gpu_busy({"used_mb": 6000, "total_mb": 8192, "util": 90})))
check("an idle GPU allows training", _si.gpu_busy({"used_mb": 300, "total_mb": 8192, "util": 0}) == "")
check("no GPU blocks training with a reason", "no NVIDIA GPU" in _si.gpu_busy({}))

# a fake Ollama that always calls read_file: the evaluator must score it 1.0 on this set
from http.server import BaseHTTPRequestHandler as _BH, ThreadingHTTPServer as _TS  # noqa: E402
import threading as _sth  # noqa: E402


class _FakeOllama(_BH):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        reply = {"message": {"role": "assistant", "content": "",
                             "tool_calls": [{"function": {"name": "read_file", "arguments": {}}}]}}
        if body.get("model") == "texty":
            reply = {"message": {"role": "assistant", "content": "I would read a.gd"}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_fo = _TS(("127.0.0.1", 0), _FakeOllama)
_sth.Thread(target=_fo.serve_forever, daemon=True).start()
_fo_url = "http://127.0.0.1:%d" % _fo.server_address[1]
# an eval set whose first moves are all read_file (the synthetic rows above)
_rf = [l for l in ((_s_root / "ds" / "train.jsonl").read_text(encoding="utf-8").splitlines()
                   + (_s_root / "ds" / "eval.jsonl").read_text(encoding="utf-8").splitlines())
       if l.strip() and _si.first_move(json.loads(l)["messages"])[1] == ("tool", "read_file")]
(_s_root / "rf.jsonl").write_text("\n".join(_rf) + "\n", encoding="utf-8")
try:
    _ev = _si.evaluate("cand", _s_root / "rf.jsonl", url=_fo_url)
    _ev2 = _si.evaluate("texty", _s_root / "rf.jsonl", url=_fo_url)
    check("the evaluator scores a model that makes the right first move 1.0", _ev["score"] == 1.0, _ev)
    check("and one that only talks 0.0", _ev2["score"] == 0.0, _ev2)
finally:
    _fo.shutdown()

check("train refuses below the example threshold",
      _si.main(["train"]) == 0 and not (_s_root / "experience" / "runs").exists())
check("promote refuses without a passing evaluation", _si.main(["promote"]) == 1)
(_s_root / ".env").write_text("OPENROUTER_API_KEY=x\n# keep me\n", encoding="utf-8")
_si.set_env_value("LOKI_TUNED_PROMOTED", "1")
_envtxt = (_s_root / ".env").read_text(encoding="utf-8")
check("set_env_value keeps every other line", "OPENROUTER_API_KEY=x" in _envtxt and "# keep me" in _envtxt
      and "LOKI_TUNED_PROMOTED=1" in _envtxt)

# the trainer fails clearly (not with a traceback) where there is no Unsloth / GPU
import subprocess as _ssp  # noqa: E402
_tr = _ssp.run([sys.executable, str(REPO / "tools" / "train_lora.py"), "--data", str(_s_root / "ds"),
                "--out", str(_s_root / "run")], capture_output=True, text=True, timeout=120)
check("train_lora.py without Unsloth exits with a clear message",
      _tr.returncode in (3, 4) and "Traceback" not in _tr.stderr, (_tr.returncode, _tr.stdout[-200:], _tr.stderr[-300:]))
_tr0 = _ssp.run([sys.executable, str(REPO / "tools" / "train_lora.py"), "--data", str(_s_root / "nothing"),
                 "--out", str(_s_root / "run")], capture_output=True, text=True, timeout=60)
check("train_lora.py with no data says so", _tr0.returncode == 2 and "no training data" in _tr0.stdout)

if _s_env is None:
    os.environ.pop("LOKI_DATA", None)
else:
    os.environ["LOKI_DATA"] = _s_env
import shutil as _ssh  # noqa: E402
for _dir in (_s_root, _s_ws):
    _ssh.rmtree(_dir, ignore_errors=True)

check("the bridge serves what Loki has learned on /experience",
      'route == "/experience"' in (REPO / "engine" / "loki_bridge.py").read_text(encoding="utf-8"))


section("macOS: Loki.app")
check("setup.sh picks a Python 3.11+ instead of whatever python3 is",
      "sys.version_info >= (3, 11)" in (REPO / "setup.sh").read_text(encoding="utf-8"))

import shutil as _sh, subprocess as _sp, tempfile as _tf, plistlib as _pl  # noqa: E401,E402
_builder = REPO / "tools" / "macos" / "make_loki_app.sh"
if os.name == "nt" or not _sh.which("bash"):
    print("  SKIP Loki.app build checks (needs a POSIX bash)")
else:
    check("make_loki_app.sh parses", _sp.run(["bash", "-n", str(_builder)]).returncode == 0)
    check("launcher.sh parses",
          _sp.run(["bash", "-n", str(REPO / "tools" / "macos" / "launcher.sh")]).returncode == 0)
    with _tf.TemporaryDirectory() as _td:
        _td = Path(_td)
        _home = _td / "home"
        _home.mkdir()
        _built = _sp.run(["bash", str(_builder), str(_td)], capture_output=True, text=True)
        _app = _td / "Loki.app"
        _exe = _app / "Contents" / "MacOS" / "Loki"
        check("Loki.app builds", _built.returncode == 0 and _exe.is_file(), _built.stdout + _built.stderr)
        _plist = _pl.loads((_app / "Contents" / "Info.plist").read_bytes()) if _built.returncode == 0 else {}
        check("Info.plist is valid and names the launcher",
              _plist.get("CFBundleExecutable") == "Loki" and _plist.get("CFBundlePackageType") == "APPL")
        check("launcher is executable", _exe.is_file() and os.access(_exe, os.X_OK))
        _rebuilt = _sp.run(["bash", str(_builder), str(_td)], capture_output=True, text=True)
        check("rebuilding replaces its own bundle", _rebuilt.returncode == 0 and _exe.is_file())
        _foreign = _td / "foreign"
        (_foreign / "Loki.app" / "Contents").mkdir(parents=True)
        _deny = _sp.run(["bash", str(_builder), str(_foreign)], capture_output=True, text=True)
        check("refuses to overwrite a Loki.app it did not make",
              _deny.returncode != 0 and (_foreign / "Loki.app" / "Contents").is_dir()
              and not (_foreign / "Loki.app" / "Contents" / "MacOS").exists(), _deny.stdout)

        def _launch(**extra: str):
            env = {"PATH": "/usr/bin:/bin", "HOME": str(_home), "LOKI_SKIP_SETUP": "1",
                   "LOKI_DATA": str(_td / "data")}
            env.update(extra)
            return _sp.run([str(_exe)], env=env, capture_output=True, text=True, timeout=30)

        _fake_py = _td / "fake_python"
        _fake_py.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "' + str(_td) + '/py.args"\n', encoding="utf-8")
        _fake_py.chmod(0o755)
        _r = _launch(LOKI_PYTHON=str(_fake_py))
        _py_args = (_td / "py.args").read_text(encoding="utf-8").split() if (_td / "py.args").is_file() else []
        check("Loki.app runs the standalone app with Loki's Python (allowed)",
              _r.returncode == 0 and _py_args == [str(REPO / "app" / "loki_app.py")], _r.stderr or _py_args)
        _r = _launch(LOKI_PYTHON=str(_td / "no-such-python"))
        check("Loki.app rejects an invalid interpreter path",
              _r.returncode == 4 and "LOKI_PYTHON" in _r.stderr, _r.stderr)
        _r = _launch()
        check("Loki.app without setup says how to set up, and installs nothing (denied)",
              _r.returncode == 4 and "setup.sh" in _r.stderr and not (_td / "data" / ".venv").exists(), _r.stderr)
        _venv_bin = _td / "data" / ".venv" / "bin"
        _venv_bin.mkdir(parents=True)
        (_venv_bin / "python3").symlink_to(_fake_py)
        (_td / "py.args").unlink()
        _r = _launch()
        check("Loki.app finds the private environment by itself", _r.returncode == 0 and (_td / "py.args").is_file(), _r.stderr)
    check("Loki.app no longer needs Godot",
          "godot" not in (REPO / "tools" / "macos" / "launcher.sh").read_text(encoding="utf-8").lower())
    check("setup.sh builds Loki.app on macOS and installs the window",
          "make_loki_app.sh" in (REPO / "setup.sh").read_text(encoding="utf-8")
          and "app/requirements.txt" in (REPO / "setup.sh").read_text(encoding="utf-8"))


section("standalone app: engine without Godot")

sys.path.insert(0, str(REPO / "engine"))
import loki_bridge as _lb  # noqa: E402
_a = _lb.parse_args(["--loki-root", "x", "--secret-file", "t"])
check("engine starts without --godot-exe or --project-dir", _a.godot_exe == "" and _a.project_dir == "")
check("workspace defaults to ~/LOKI Projects/Home (never ~/Loki)", _lb.resolve_workspace("") == (Path.home() / "LOKI Projects" / "Home").resolve()
      if not os.environ.get("LOKI_WORKSPACE") else True)
check("an explicit workspace wins", _lb.resolve_workspace("/tmp/ws-x") == Path("/tmp/ws-x").resolve())
_ui = REPO / "app" / "ui"
check("UI root serves index.html", _lb.ui_file(_ui, "/") == (_ui / "index.html").resolve())
check("UI assets are served", _lb.ui_file(_ui, "/ui/app.js") == (_ui / "app.js").resolve())
check("UI refuses path traversal", _lb.ui_file(_ui, "/ui/../../engine/loki.py") is None)
check("UI refuses encoded-backslash and absolute tricks",
      _lb.ui_file(_ui, "/ui/..\\loki_app.py") is None and _lb.ui_file(_ui, "/ui//etc/passwd") is None)
check("UI refuses non-asset types", _lb.ui_file(REPO / "app", "/ui/loki_app.py") is None)
check("the app's own origin may call the engine", "http://127.0.0.1:8766" in _lb.ALLOWED_ORIGINS)
check("foreign hosts cannot load the UI (DNS rebinding)", "evil.example:8766" not in _lb.ALLOWED_HOSTS)
check("the UI page has a strict content security policy",
      "script-src 'self'" in _lb.UI_CSP and "frame-ancestors 'none'" in _lb.UI_CSP)
_html = (_ui / "index.html").read_text(encoding="utf-8")
check("the UI has no inline script or style (CSP-clean)",
      "<script>" not in _html and " style=" not in _html and "onclick" not in _html)
_js = (_ui / "app.js").read_text(encoding="utf-8")
check("the UI escapes model output before rendering", "escapeHtml(part)" in _js and "escapeHtml(body" in _js)
check("the token travels in the URL fragment, not the query", "location.hash" in _js and "?token" not in _js)

_saved_gp = loki.GAME_PROJECT
try:
    loki.GAME_PROJECT = ""
    _general = loki.system_prompt() if loki.AGENT_MODE == "build" else (loki.set_mode("build"), loki.system_prompt())[1]
    check("outside a Godot project, Build mode is not told it is in Godot",
          "Godot 4 project" not in _general and "standalone desktop app" in _general)
    import tempfile as _gp_tf
    with _gp_tf.TemporaryDirectory() as _game:
        (Path(_game) / "project.godot").write_text("config_version=5\n", encoding="utf-8")
        loki.GAME_PROJECT = _game
        check("inside a Godot project, the game prompt is kept", "Godot 4 project" in loki.system_prompt())
finally:
    loki.GAME_PROJECT = _saved_gp


_mcp_cfg = json.loads((REPO / "engine" / "mcp_servers.json").read_text(encoding="utf-8"))["mcpServers"]
check("Godot MCP servers start only for a Godot workspace",
      _mcp_cfg["godot"].get("requires_env") == "GAME_PROJECT"
      and _mcp_cfg["godot_run"].get("requires_env") == "GAME_PROJECT")
_had = os.environ.pop("GAME_PROJECT", None)
try:
    check("no Godot project -> the Godot MCP server is skipped",
          "GAME_PROJECT" in loki._server_skip_reason(_mcp_cfg["godot"], "godot"))
finally:
    if _had is not None:
        os.environ["GAME_PROJECT"] = _had


section("standalone app: desktop shell")

import importlib.util as _ilu  # noqa: E402
_spec2 = _ilu.spec_from_file_location("_loki_app", REPO / "app" / "loki_app.py")
_app = _ilu.module_from_spec(_spec2)
_spec2.loader.exec_module(_app)
check("app workspace: --workspace wins", _app.choose_workspace("/tmp/a", {"workspace": "/tmp/b"}, {}) == Path("/tmp/a").resolve())
check("app workspace: remembered next", _app.choose_workspace("", {"workspace": "/tmp/b"}, {"LOKI_WORKSPACE": "/tmp/c"}) == Path("/tmp/b").resolve())
check("app workspace: default ~/LOKI Projects/Home", _app.choose_workspace("", {}, {}) == (Path.home() / "LOKI Projects" / "Home").resolve())
import tempfile as _ac_tf  # noqa: E402
with _ac_tf.TemporaryDirectory() as _ac:
    _ac = Path(_ac)
    (_ac / "Loki" / ".godot").mkdir(parents=True)
    (_ac / "Loki" / ".godot" / "loki_conversations.json").write_text('{"chats": []}', encoding="utf-8")
    _ws_new = _ac / "LOKI Projects" / "Home"
    check("old chats in ~/Loki/.godot are copied to the new workspace",
          _app.adopt_old_chats(_ws_new, home=_ac) == ["loki_conversations.json"]
          and (_ws_new / ".loki" / "loki_conversations.json").is_file()
          and (_ac / "Loki" / ".godot" / "loki_conversations.json").is_file())
    check("chats are adopted only once (an existing file is never overwritten)",
          _app.adopt_old_chats(_ws_new, home=_ac) == [])
_cmd = _app.engine_command(Path("/py"), Path("/ws"), "")
check("app starts the engine with its UI and its own state folder",
      "--ui-dir" in _cmd and "--state-dir" in _cmd and "--godot-exe" not in _cmd)
check("app passes Godot only when it found one",
      _app.engine_command(Path("/py"), Path("/ws"), "/G")[-2:] == ["--godot-exe", "/G"])
check("app ignores a Godot path that does not exist", _app.find_godot({"LOKI_GODOT": "/no/such/godot"}) == "")
check("app reports an engine that never answers", _app.probe("x", timeout=0.3) in (0, 401, 403))
_page = _app.problem_page("<b>x</b>", "a & b")
check("the app's engine has its own port, apart from the Godot dock's", _app.PORT == 8767 and _lb.PORT == 8766)
check("the app tells its engine which port to use", "LOKI_PORT=str(PORT)" in (REPO / "app" / "loki_app.py").read_text(encoding="utf-8"))
check("on Windows the engine gets no console window",
      _app.popen_options("win32").get("creationflags", 0) & 0x08000000 == 0x08000000)
check("on macOS/Linux the engine gets its own session", _app.popen_options("darwin") == {"start_new_session": True})
_bat = (REPO / "setup.bat").read_text(encoding="utf-8")
check("setup.bat picks a Python 3.11+ (py launcher first)", "py -%%V" in _bat and "(3, 11)" in _bat)
check("setup.bat installs the Loki window and makes shortcuts",
      "app\\requirements.txt" in _bat and "make_shortcuts.ps1" in _bat)
_ps1 = (REPO / "tools" / "windows" / "make_shortcuts.ps1").read_text(encoding="utf-8")
check("Windows shortcuts start Loki without a console (pythonw)", "pythonw.exe" in _ps1 and "loki_app.py" in _ps1)
check("Loki.cmd starts the app with pythonw", "pythonw.exe" in (REPO / "Loki.cmd").read_text(encoding="utf-8"))
check("Windows scripts are checked out with CRLF",
      "*.bat text eol=crlf" in (REPO / ".gitattributes").read_text(encoding="utf-8"))
check("app error page escapes its text", "&lt;b&gt;" in _page and "a &amp; b" in _page)


if "--live" in sys.argv:


    asyncio.run(live())





print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))


if FAIL:


    print("FAILED: " + ", ".join(FAIL))


sys.exit(1 if FAIL else 0)


