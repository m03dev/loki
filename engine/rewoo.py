"""ReWOO: plan all the tool calls in ONE model call, run them, then solve - for small models.

Ported from ReWOO (billxbf/ReWOO: algos/PWS.py Planner-Worker-Solver, _parse_plans,
_parse_planner_evidences, _get_worker_evidences with #E variable substitution, and the planner /
solver prompts in prompts/planner.py and prompts/solver.py), MIT - see engine/licenses/ReWOO-MIT.txt.
Paper: "ReWOO: Decoupling Reasoning from Observations for Efficient Augmented Language Models"
(Xu et al., 2023).

Why it suits a 7-9B model: in a ReAct loop the model re-reads the whole growing transcript and
must choose a correct tool call on every turn - every turn is a chance to derail. ReWOO asks for
the whole plan once:

    Plan: find where the tool list is trimmed for local models
    #E1 = search_files[LOCAL_MAX_TOOLS]
    Plan: read that part of the file
    #E2 = read_file[{"filename": "engine/loki.py", "start_line": 3460, "end_line": 3520}]
    Plan: explain it
    #E3 = LLM[How are tools picked for a local model? Given context: #E1, #E2]

then the WORKER runs each step (no model involved, #En replaced by earlier results) and the
SOLVER writes the answer from the evidence. Three short calls instead of many long ones; the
paper reports ~5x fewer tokens at equal or better accuracy.

LOKI additions: a tool input may be a JSON object (named arguments) or a plain string (the tool's
first required argument); only the tools passed in `workers` can run (LOKI gives it read-only
ones); a step whose tool is unknown or fails says so as its evidence instead of stopping the
plan; at most MAX_STEPS steps. Pure parsing + one async run over injected callables.
"""
from __future__ import annotations

import json
import re

MAX_STEPS = 8
MAX_EVIDENCE_CHARS = 4000

PLANNER_PREFIX = (
    "For the following task, make plans that can solve the problem step by step. For each plan, "
    "indicate which external tool together with tool input to retrieve evidence. You can store the "
    "evidence into a variable #E that can be called by later tools. (Plan, #E1, Plan, #E2, Plan, ...)\n\n")
PLANNER_SUFFIX = ("Begin! Describe your plans with rich details. Each Plan should be followed by only one #E. "
                  "Make as few plans as possible if it can solve the problem.\n\n")
SOLVER_PREFIX = ("Solve the following task or problem. To assist you, we provide some plans and corresponding "
                 "evidences that might be helpful. Notice that some of these information contain noise so you "
                 "should trust them with caution.\n\n")
SOLVER_SUFFIX = "\nNow begin to solve the task or problem. Respond with the answer directly with no extra words.\n\n"

FEWSHOT = """Task: Which file defines the function that reads web pages, and what does it remove?
Plan: Search the code for the definition of the web reading function.
#E1 = search_files[def read_web]
Plan: Read the module that does the reading.
#E2 = read_file[{"filename": "engine/web_reader.py", "start_line": 1, "end_line": 40}]
Plan: Answer from what was found.
#E3 = LLM[Which file defines read_web and what does it remove from pages? Given context: #E1, #E2]
"""

_EVIDENCE = re.compile(r"^\s*#E(\d+)\s*[:=]\s*(.+?)\s*$")
_PLAN = re.compile(r"^[*#\s]*plan\s*\**\s*:\s*\**\s*(.*)$", re.I)
_CALL = re.compile(r"^([A-Za-z_][\w.-]*)\s*[\[(](.*)[\])]\s*$", re.S)


def worker_lines(workers: dict) -> str:
    """Tools: name[input] + one line each, the way ReWOO's planner lists its workers."""
    lines = ["Tools can be one of the following:"]
    for i, (name, info) in enumerate(sorted(workers.items()), 1):
        lines.append("(%d) %s[input]: %s" % (i, name, info.get("description", "")))
    lines.append("(%d) LLM[input]: A pretrained language model. Useful for reasoning, summarizing and "
                 "answering from evidence. Input can be any instruction; put #E variables in it." % (len(workers) + 1))
    return "\n".join(lines)


def planner_prompt(task: str, workers: dict, fewshot: str = FEWSHOT) -> str:
    return (PLANNER_PREFIX + worker_lines(workers) + "\n\nFor example,\n" + fewshot + "\n"
            + PLANNER_SUFFIX + "Task: " + task.strip() + "\n")


def parse_plan(text: str) -> list:
    """[{"plan": str, "var": "#E1", "tool": str, "input": str}] from the planner's text."""
    steps, plan = [], ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        pm = _PLAN.match(line)
        if pm:
            plan = pm.group(1).strip().strip("*").strip()
            continue
        line = line.strip("*").strip()
        m = _EVIDENCE.match(line)
        if not m:
            continue
        var, call = "#E" + m.group(1), m.group(2).strip().strip("`")
        cm = _CALL.match(call)
        if cm:
            tool, tool_input = cm.group(1), cm.group(2).strip()
        else:
            tool, tool_input = "", call
        steps.append({"plan": plan, "var": var, "tool": tool, "input": tool_input})
        plan = ""
        if len(steps) >= MAX_STEPS:
            break
    return steps


def substitute(text: str, evidence: dict) -> str:
    """Replace #En with the evidence gathered so far (longest variable names first: #E10 before #E1)."""
    for var in sorted(evidence, key=len, reverse=True):
        text = text.replace(var, "[" + str(evidence[var])[:MAX_EVIDENCE_CHARS] + "]")
    return text


def arguments(tool_input: str, info: dict) -> dict:
    """A JSON object is used as named arguments; anything else goes to the first required argument."""
    text = str(tool_input or "").strip()
    if text.startswith("{"):
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    first = info.get("arg") or "input"
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return {first: text}


async def run(task: str, ask, workers: dict, call_tool, fewshot: str = FEWSHOT, progress=None) -> dict:
    """Plan -> work -> solve.

    ask(prompt) -> str (async model call); workers {name: {"description", "arg"}};
    call_tool(name, args) -> str (async). Returns {"answer", "plan", "steps": [...]}."""
    plan_text = await ask(planner_prompt(task, workers, fewshot))
    steps = parse_plan(plan_text)
    evidence: dict = {}
    for step in steps:
        tool, tool_input = step["tool"], substitute(step["input"], evidence)
        if progress:
            progress("%s %s[%s]" % (step["var"], tool or "?", tool_input[:80]))
        if tool.upper() == "LLM":
            result = await ask(tool_input)
        elif tool in workers:
            try:
                result = await call_tool(tool, arguments(tool_input, workers[tool]))
            except Exception as exc:  # noqa: BLE001 - one failed step is evidence, not the end
                result = "error: %s" % exc
        elif not tool:
            result = tool_input        # a literal value the planner wrote
        else:
            result = "No evidence found (%s is not an available tool)" % tool
        evidence[step["var"]] = str(result)[:MAX_EVIDENCE_CHARS]
        step["result"] = evidence[step["var"]]
    if not steps:
        # The planner wrote no usable plan: answer directly rather than fail.
        answer = await ask(task)
        return {"answer": answer, "plan": plan_text, "steps": []}
    log = "".join("Plan: %s\nEvidence:\n%s\n" % (s["plan"] or "%s[%s]" % (s["tool"], s["input"]), s["result"])
                  for s in steps)
    answer = await ask(SOLVER_PREFIX + task + "\n" + log + SOLVER_SUFFIX + task + "\n")
    return {"answer": answer, "plan": plan_text, "steps": steps}
