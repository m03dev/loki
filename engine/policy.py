"""The Policy Engine - hardcoded rules that decide whether an action may run.

Separation of duties (blueprint, decision layer):

    decision providers (Jev / Laya)  RECOMMEND   "this looks safe", "you are looping"
    the policy engine                DECIDES     allow / ask / deny, from fixed rules
    the human                        APPROVES    anything the policy says to ask about

No model is consulted here. A recommendation can only turn an ASK that the policy marks
`decidable` into an ALLOW; it can never turn a DENY into anything, and never skips a
non-decidable ASK. That is enforced in one function, `final()`, which the tests pin.

Rules (in order):
  1. run_command: refused if the command policy or the no-shell parser rejects it.
  2. File tools: every path argument must stay inside the workspace.
  3. Capability-backed actions: the capability must be enabled, the permission granted
     at enable time, and its required env/commands present.
  4. Network: loopback is always fine; other hosts need a granted network permission,
     or LOKI_NET_ALLOW (comma-separated hosts) set by the user.
  5. Dangerous tools ASK (decidable); everything else is ALLOWED.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

ALLOW, ASK, DENY = "allow", "ask", "deny"

# Which arguments of which local tools are workspace paths.
PATH_ARGS = {
    "read_file": ("filename",), "write_file": ("filename",), "append_file": ("filename",),
    "edit_file": ("filename",), "make_dir": ("path",), "move_file": ("src", "dst"),
    "delete_file": ("path",), "build_3d_scene": ("filename",), "list_tree": ("subdir",),
    "search_files": ("subdir",), "review_repository": ("path",),
}
# Asks the human, but a confident decision provider may skip the prompt.
DECIDABLE = {"run_command", "move_file", "open_godot"}
# Always asks the human, whatever any provider says.
ALWAYS_ASK = {"delete_file", "delegate"}
# Tools that need an enabled capability (tool -> capability name).
CAPABILITY_TOOLS: dict[str, str] = {}
# conductor(role=...) - checked per role by conductor.Conductor.pick, which asks capability()
# Job backends that need an enabled capability.
BACKEND_CAPABILITY = {"herdr": "herdr", "cua": "cua"}
AGENT_CAPABILITY = {"hermes": "hermes-agent"}
BACKEND_PERMISSION = {"herdr": "process:agent", "cua": "computer:virtual", "local": "process:agent"}


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str = ""
    decidable: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW


def final(verdict: Verdict, recommendation: str | None) -> Verdict:
    """Combine the policy verdict with a decision provider's recommendation.

    The ONLY upgrade is ASK(decidable) + "allow" -> ALLOW. Everything else is unchanged.
    """
    if verdict.decision == ASK and verdict.decidable and recommendation == "allow":
        return Verdict(ALLOW, "allowed: the decision layer judged it safe (" + verdict.reason + ")", False)
    return verdict


class PolicyEngine:
    def __init__(self, path_check: Callable[[str], Any], command_check: Callable[[str], tuple],
                 parse_command: Callable[[str], Any], dangerous: set[str],
                 registry: Any = None, env: dict | None = None) -> None:
        self.path_check = path_check          # raises on a path that escapes the workspace
        self.command_check = command_check    # (allowed, reason)
        self.parse_command = parse_command    # raises on shell syntax
        self.dangerous = set(dangerous)
        self.registry = registry
        self.env = env if env is not None else os.environ

    # ------------------------------------------------------------- tools
    def tool_call(self, name: str, args: dict) -> Verdict:
        args = args if isinstance(args, dict) else {}
        if name == "run_command":
            command = str(args.get("command", ""))
            ok, reason = self.command_check(command)
            if not ok:
                return Verdict(DENY, reason)
            try:
                self.parse_command(command)
            except ValueError as exc:
                return Verdict(DENY, "refused: %s" % exc)
        for key in PATH_ARGS.get(name, ()):
            value = args.get(key)
            if value is None or str(value).strip() == "":
                continue
            try:
                self.path_check(str(value))
            except Exception as exc:  # noqa: BLE001 - any escape is a denial
                return Verdict(DENY, "refused: %s is outside the workspace (%s)" % (key, exc))
        capability = CAPABILITY_TOOLS.get(name)
        if capability:
            verdict = self.capability(capability)
            if not verdict.allowed:
                return verdict
        if name == "conductor" and str(args.get("role", "")).strip().lower() == "browse":
            # A browser acting on live websites always asks; no recommendation skips it.
            return Verdict(ASK, "a browser will act on websites", decidable=False)
        if name in ALWAYS_ASK:
            return Verdict(ASK, "%s always asks" % name, decidable=False)
        if name in self.dangerous:
            return Verdict(ASK, "%s changes the system" % name, decidable=name in DECIDABLE)
        return Verdict(ALLOW, "ok")

    # ------------------------------------------------------------- capabilities
    def capability(self, name: str, permission: str = "") -> Verdict:
        if self.registry is None:
            return Verdict(DENY, "no capability registry")
        entry = self.registry.get(name)
        if entry is None:
            return Verdict(DENY, "unknown capability %r" % name)
        status = entry.get("status")
        if status == "disabled":
            return Verdict(DENY, "%s is not enabled - turn it on in Settings > Capabilities" % name)
        if status == "changed":
            return Verdict(DENY, "%s changed since you enabled it - review and enable it again" % name)
        if status == "invalid":
            return Verdict(DENY, "%s has an invalid manifest" % name)
        if status == "missing":
            return Verdict(DENY, "%s is missing %s" % (name, ", ".join(entry.get("missing", []))))
        if permission and permission not in self.registry.granted(name):
            return Verdict(DENY, "%s was not granted %s" % (name, permission))
        return Verdict(ALLOW, "ok")

    def job(self, backend: str, agent: str = "") -> Verdict:
        capability = BACKEND_CAPABILITY.get(backend)
        if capability:
            verdict = self.capability(capability, BACKEND_PERMISSION.get(backend, ""))
            if not verdict.allowed:
                return verdict
        agent_capability = AGENT_CAPABILITY.get(agent)
        if agent_capability:
            return self.capability(agent_capability, "process:agent")
        return Verdict(ALLOW, "ok")

    # ------------------------------------------------------------- network
    def network(self, url: str, capability: str = "") -> Verdict:
        parsed = urlparse(str(url))
        if parsed.scheme not in ("http", "https"):
            return Verdict(DENY, "only http(s) is allowed")
        host = (parsed.hostname or "").lower()
        if not host:
            return Verdict(DENY, "no host")
        if host in ("localhost", "::1") or host.startswith("127."):
            return Verdict(ALLOW, "loopback")
        allow = {h.strip().lower() for h in str(self.env.get("LOKI_NET_ALLOW", "")).split(",") if h.strip()}
        if host in allow:
            return Verdict(ALLOW, "in LOKI_NET_ALLOW")
        if capability and self.registry is not None:
            granted = self.registry.granted(capability)
            if "network" in granted or "network:" + host in granted:
                return Verdict(ALLOW, "granted to " + capability)
        return Verdict(DENY, "network access to %s is not allowed (add it to LOKI_NET_ALLOW)" % host)
