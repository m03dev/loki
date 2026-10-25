"""LOKI Studio as an MCP server: Claude Code, Codex and Cursor get Studio's Godot hands.

The tools are Studio's: the LIVE Godot editor through the
LOKI Studio plugin (scene tree, nodes, properties, signals, scripts, run / stop, playtest turn by
turn, find lag, screenshots, the editor's and the game's errors), the offline Godot class reference,
the project index - and Studio's own sessions (start one, send to it, read what it did).

It talks to the running Studio through its loopback API, with the token from the connect file
(~/.loki/studio_connect.json, or --connect). The docs and the project index work without Studio.

    python studio/studio_mcp.py [--project <godot project>]          stdio (what clients start)
    python studio/studio_mcp.py --list

Claude Code:  claude mcp add loki-studio -- python /path/to/loki/studio/studio_mcp.py --project /path/to/game
Codex (~/.codex/config.toml):
    [mcp_servers.loki_studio]
    command = "python"
    args = ["/path/to/loki/studio/studio_mcp.py", "--project", "/path/to/game"]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import studio_paths  # noqa: E402,F401
import studio_godot  # noqa: E402
import studio_index  # noqa: E402
import godot_docs  # noqa: E402

VERSION = "1"


class StudioLink:
    def __init__(self, connect: str = "", project: str = "", opener=urllib.request.urlopen):
        self.connect = Path(connect) if connect else studio_godot.connect_path()
        self.project = str(Path(project).resolve()) if project else ""
        self.opener = opener

    def _conn(self) -> dict:
        try:
            return json.loads(self.connect.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("LOKI Studio is not running (no %s). Start LOKI Studio first." % self.connect) from None

    def api(self, method: str, path: str, body: dict | None = None, timeout: float = 90.0) -> dict:
        conn = self._conn()
        req = urllib.request.Request(conn["url"].rstrip("/") + path, method=method,
                                     data=json.dumps(body or {}).encode("utf-8") if method == "POST" else None,
                                     headers={"Authorization": "Bearer " + conn["token"], "Content-Type": "application/json"})
        try:
            with self.opener(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8"))
            except ValueError:
                return {"ok": False, "error": "HTTP %s" % exc.code}
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError("LOKI Studio does not answer at %s (%s)" % (conn.get("url"), exc)) from None

    def proj(self, project: str = "") -> str:
        return str(Path(project).resolve()) if project else self.project


class Tools:
    """Each method is one MCP tool (docstring = description)."""

    def __init__(self, link: StudioLink):
        self.link = link

    def _out(self, data: dict) -> str:
        if not data.get("ok", True):
            return "error: " + str(data.get("error") or data)
        body = data.get("output", data.get("result", data))
        return body if isinstance(body, str) else json.dumps(body, indent=1, default=str)[:60000]

    def _safe(self, fn) -> str:
        try:
            return fn()
        except RuntimeError as exc:
            return "error: %s" % exc

    def studio_status(self) -> str:
        """Is LOKI Studio running, which Godot editors are connected (project, Godot version), the model driving."""
        return self._safe(lambda: self._out({"ok": True, "result": {
            "editors": self.link.api("GET", "/api/godot/editors").get("editors"),
            "driver": self.link.api("GET", "/api/state").get("driver")}}))

    def godot(self, action: str, args: str = "{}", project: str = "") -> str:
        """Run one action in the live Godot editor (through the LOKI Studio plugin). action: editor_state, scene_tree,
        node_info, selected_code, set_property, add_node, remove_node, connect_signal, attach_script, new_scene,
        open_scene, save_scene, open_script, select_nodes, rescan, run_game, stop_game, game_tree. args: a JSON object."""
        try:
            parsed = json.loads(args or "{}") if isinstance(args, str) else dict(args or {})
        except ValueError:
            return "error: args must be a JSON object"
        return self._safe(lambda: self._out(self.link.api("POST", "/api/godot/call", {
            "action": action, "args": parsed, "project": self.link.proj(project)})))

    def _tool(self, name: str, args: dict, project: str) -> str:
        return self._safe(lambda: self._out(self.link.api("POST", "/api/godot/tool", {
            "tool": name, "args": args, "project": self.link.proj(project)})))

    def godot_errors(self, since: int = 0, project: str = "") -> str:
        """Errors and warnings from the Godot editor and the running game (since = index from a previous call)."""
        return self._tool("editor_errors", {"since": since}, project)

    def godot_screenshot(self, target: str = "game", project: str = "") -> str:
        """A PNG of the running game (game) or the editor (editor, 2d, 3d); returns where it was saved."""
        return self._tool("screenshot", {"target": target}, project)

    def godot_playtest_step(self, events: str, wait_ms: int = 300, project: str = "") -> str:
        """One playtest turn on the RUNNING game: events (JSON list: {action, hold_ms} | {key} | {mouse, x, y} | {text} |
        {wait_ms}) -> wait -> screenshot -> new errors. Run the game first: godot(action="run_game")."""
        try:
            evs = json.loads(events) if isinstance(events, str) else list(events)
        except ValueError:
            return "error: events must be a JSON list"
        return self._tool("playtest_step", {"events": evs, "wait_ms": wait_ms}, project)

    def godot_find_lag(self, seconds: float = 4.0, project: str = "") -> str:
        """Sample the running game's performance monitors and say what makes it slow."""
        return self._tool("find_lag", {"seconds": seconds}, project)

    def godot_docs(self, query: str) -> str:
        """The Godot class reference, offline: a class, Class.member, or words."""
        return godot_docs.answer(query)

    def project_index(self, query: str = "", project: str = "") -> str:
        """The Godot project's scenes, scripts, signals, autoloads and input actions (empty query = overview)."""
        root = self.link.proj(project)
        if not root or not studio_index.is_godot(Path(root)):
            return "error: give project= the folder with project.godot"
        return studio_index.godot_query(studio_index.godot_index(Path(root)), query)

    def studio_sessions(self) -> str:
        """LOKI Studio's sessions (id, title, kind, status, mode)."""
        return self._safe(lambda: self._out({"ok": True, "result": [
            {k: s.get(k) for k in ("id", "title", "kind", "status", "mode", "project")} for s in self.link.api("GET", "/api/state").get("sessions", [])]}))

    def studio_new_session(self, text: str, project: str = "", mode: str = "default") -> str:
        """Start a Studio session (its own agent) on a Godot project (project=) or on LOKI's code (no project)."""
        return self._safe(lambda: self._out(self.link.api("POST", "/api/session/new", {"text": text, "project": self.link.proj(project),
                                                                                        "mode": mode})))

    def studio_send(self, id: str, text: str) -> str:  # noqa: A002
        """Send a message (or a /command) to a Studio session."""
        return self._safe(lambda: self._out(self.link.api("POST", "/api/session/send", {"id": id, "text": text})))

    def studio_events(self, id: str, after: int = 0) -> str:  # noqa: A002
        """What a Studio session did after event `after`: its steps, tool calls, results, answers."""
        def go():
            data = self.link.api("GET", "/api/session?id=%s&after=%d" % (urllib.parse.quote(id), int(after or 0)))
            if not data.get("ok"):
                return "error: " + str(data.get("error"))
            return "\n".join("[%d %s] %s" % (e["id"], e["type"], str(e.get("text", ""))[:600]) for e in data.get("events", [])) or "(nothing new)"
        return self._safe(go)


TOOL_ORDER = ("studio_status", "godot", "godot_errors", "godot_screenshot", "godot_playtest_step", "godot_find_lag",
              "godot_docs", "project_index", "studio_sessions", "studio_new_session", "studio_send", "studio_events")


def build_server(tools: Tools):
    from mcp.server.mcpserver import MCPServer  # pylint: disable=import-outside-toplevel
    server = MCPServer("loki-studio", version=VERSION, instructions=(
        "LOKI Studio's hands in the live Godot editor (through the LOKI Studio plugin), the offline Godot docs, the project "
        "index and Studio's sessions. Default project: %s." % (tools.link.project or "(give project=)")))
    for name in TOOL_ORDER:
        server.tool(name=name, description=" ".join((getattr(tools, name).__doc__ or name).split()),
                    structured_output=False)(getattr(tools, name))
    return server


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="LOKI Studio as an MCP server")
    ap.add_argument("--connect", default="", help="the connect file (default ~/.loki/studio_connect.json)")
    ap.add_argument("--project", default="", help="the default Godot project")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    tools = Tools(StudioLink(args.connect, args.project))
    if args.list:
        for name in TOOL_ORDER:
            print("%-22s %s" % (name, " ".join((getattr(tools, name).__doc__ or "").split())[:100]))
        return 0
    build_server(tools).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
