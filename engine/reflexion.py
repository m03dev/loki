"""Reflexion: after a failed attempt, write down WHY it failed and a plan to avoid it - and use it.

Ported from Reflexion (noahshinn/reflexion: hotpotqa_runs/prompts.py REFLECT_INSTRUCTION,
REFLECTION_HEADER, LAST_TRIAL_HEADER; hotpotqa_runs/agents.py format_reflections /
format_last_attempt and the trial loop; programming_runs PY_SELF_REFLECTION_CHAT_INSTRUCTION),
MIT - see engine/licenses/Reflexion-MIT.txt. Paper: "Reflexion: Language Agents with Verbal
Reinforcement Learning" (Shinn et al., 2023).

The point for LOKI's local models: a small model retried on the same task tends to repeat the
same mistake. Reflexion turns the failure signal (a failing test, a refused tool, the user's
"no, that's wrong") into a few sentences of diagnosis + a new high-level plan, and puts those
sentences in front of the next attempt. Fine-tuning-free, and it measurably helps small models.

LOKI keeps each reflection as an episodic memory tagged `reflexion` (memory_core), so it also
reaches LATER requests on similar tasks through the memory pack - not only the next retry.
`trial_loop` is the full Reflexion loop for callers with an evaluator (a test command, a checker).
Pure prompt building + async loops over injected callables; no network here.
"""
from __future__ import annotations

REFLECT_INSTRUCTION = (
    "You are an advanced reasoning agent that can improve based on self reflection. You will be given a "
    "previous attempt at a task and the feedback it got. The attempt was unsuccessful. In a few sentences, "
    "diagnose a possible reason for the failure and devise a new, concise, high level plan that aims to "
    "mitigate the same failure. Use complete sentences. Only write the diagnosis and the plan, not a new "
    "attempt.")
REFLECTION_HEADER = ("You have attempted this task before and failed. The following reflection(s) give a plan to "
                     "avoid failing in the same way you did previously. Use them to improve your strategy.\n")
LAST_TRIAL_HEADER = "You have attempted the following task before and failed. Below is the last trial.\n"
MAX_ATTEMPT_CHARS = 6000
MAX_REFLECTIONS = 3
TAG = "reflexion"


def truncate_attempt(attempt: str, limit: int = MAX_ATTEMPT_CHARS) -> str:
    """Reflexion truncates the scratchpad by dropping the longest observations first; LOKI keeps the
    head and the tail of the attempt, where the plan and the failure usually are."""
    text = str(attempt or "").strip()
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n[... %d characters of the attempt left out ...]\n" % (len(text) - limit) + text[-half:]


def reflection_prompt(task: str, attempt: str, feedback: str) -> str:
    return (REFLECT_INSTRUCTION + "\n\n" + LAST_TRIAL_HEADER + "Task: " + str(task).strip() + "\n"
            + truncate_attempt(attempt) + "\n(END PREVIOUS TRIAL)\n\nFeedback: " + str(feedback or "it failed").strip()
            + "\n\nReflection:")


def format_reflections(reflections: list, header: str = REFLECTION_HEADER) -> str:
    items = [str(r).strip() for r in reflections or [] if str(r).strip()][-MAX_REFLECTIONS:]
    if not items:
        return ""
    return header + "Reflections:\n- " + "\n- ".join(items)


def clean(text: str) -> str:
    text = str(text or "").strip()
    for prefix in ("Reflection:", "reflection:", "Diagnosis:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return " ".join(text.split())[:1200]


async def reflect(task: str, attempt: str, feedback: str, ask, learn=None) -> dict:
    """One reflection. ask(prompt) -> str (async); learn(text, tags) stores it (optional)."""
    text = clean(await ask(reflection_prompt(task, attempt, feedback)))
    if not text:
        return {"ok": False, "error": "the model wrote no reflection"}
    stored = ""
    if learn is not None:
        memo = "Lesson for tasks like '%s': %s" % (" ".join(str(task).split())[:160], text)
        try:
            out = learn(memo, [TAG])
            stored = (out or {}).get("id", "") if isinstance(out, dict) else str(out or "")
        except Exception:  # noqa: BLE001 - a reflection that could not be stored is still useful now
            stored = ""
    return {"ok": True, "reflection": text, "stored": stored}


async def trial_loop(task: str, attempt_fn, evaluate_fn, ask, max_trials: int = 3, learn=None) -> dict:
    """Reflexion's loop: attempt -> evaluate -> (fail) reflect -> attempt with the reflections.

    attempt_fn(task, reflections_text) -> str; evaluate_fn(result) -> (ok: bool, feedback: str);
    all async. Returns {"ok", "result", "trials", "reflections"}."""
    reflections: list = []
    result = ""
    for trial in range(1, max(1, int(max_trials)) + 1):
        result = await attempt_fn(task, format_reflections(reflections))
        ok, feedback = await evaluate_fn(result)
        if ok:
            return {"ok": True, "result": result, "trials": trial, "reflections": reflections}
        if trial < max_trials:
            out = await reflect(task, result, feedback, ask, learn)
            if out.get("ok"):
                reflections.append(out["reflection"])
    return {"ok": False, "result": result, "trials": int(max_trials), "reflections": reflections}
