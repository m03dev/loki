---
name: code
title: Code change
triggers: code, bug, fix the, crash, traceback, exception, error in, stack trace, refactor, function, endpoint, api, python, javascript, typescript, rust, c++, test, tests, unit test, failing test, regression, implement, add a feature, python script, module, build fails, compile, lint, performance, slow, memory leak, ship, commit, pull request, fastapi, godot script, gdscript
specialists: Architect, Builder, Tester, Reviewer
---
# Code change

## Purpose
A change to code - LOKI's own or a project in the workspace - that fixes the root cause or adds the feature, comes
with a test that would have caught it, passes the suites within the 1-minute budget on the touched area, and works
on both the Mac and Windows. Done means: a failing test first, the fix, the test green, the diff reviewed, and (when
the owner wants it) shipped to master with tools/ship.py.

## Stages
```json
[
 {
  "id": "reproduce",
  "specialist": "Tester",
  "objective": "Reproduce the problem or pin the missing behaviour with a check that fails today.",
  "output": "the failing check in tests/<suite>.py (or tests/js/<name>.test.js) and its FAIL line, word for word",
  "tools": ["read_file", "search_files", "code_map", "check_loki", "bash"],
  "check": "the new check FAILS before any change and its message names the behaviour in a plain sentence; the suite runs in under 60 s with --only <suite>",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "locate",
  "specialist": "Architect",
  "objective": "Find the root cause: trace from the failing check to the line that makes the wrong decision, and list every caller that depends on it.",
  "output": "ROOT CAUSE: <file:line> - <why>; CALLERS: <file:line list>; PLAN: the smallest change that fixes the cause, both OS considered",
  "tools": ["code_map", "search_files", "read_file", "memory"],
  "check": "the cause is a line of code, not a symptom; the plan says why the same problem cannot come back; Windows paths, encodings and shells were considered",
  "gate": "",
  "writes": false,
  "depends_on": ["reproduce"]
 },
 {
  "id": "implement",
  "specialist": "Builder",
  "objective": "Make the planned change with exact edits, keeping style and existing behaviour.",
  "output": "the edited files (edit_file diffs), each with a one-line reason",
  "tools": ["edit_file", "write_file", "read_file"],
  "check": "only files named in the plan changed; no check was deleted or weakened; no new dependency without a licence note in docs/THIRD_PARTY.md",
  "gate": "",
  "writes": true,
  "depends_on": ["locate"]
 },
 {
  "id": "test",
  "specialist": "Tester",
  "objective": "Run the reproduced check and the suites that own the touched files, then the neighbours that import them.",
  "output": "PASS/FAIL lines for each suite run, with counts (N passed, M failed)",
  "tools": ["check_loki", "bash"],
  "check": "the new check passes; every check that passed before still passes; each run stays under 60 s (python tools/ship.py --check --only <suite>)",
  "gate": "",
  "writes": false,
  "depends_on": ["implement"]
 },
 {
  "id": "review",
  "specialist": "Reviewer",
  "objective": "Review the diff like a senior engineer: correctness, both OS, edge cases, naming, needless complexity, leftover debug code.",
  "output": "REVIEW: APPROVE or CHANGES with numbered findings (file:line - problem - fix)",
  "tools": ["read_file", "bash", "search_files"],
  "check": "git diff was read in full; every finding names a line; no finding is style-only when a correctness issue exists",
  "gate": "",
  "writes": false,
  "depends_on": ["test"]
 },
 {
  "id": "ship",
  "specialist": "Builder",
  "objective": "Publish to master with a message that says what changed and how it was checked, after the owner's OK.",
  "output": "the commit hash on master and the ship.py output tail",
  "tools": ["ship_loki", "bash"],
  "check": "ship.py ran its tests and pushed to master (never a side branch); HANDOFF.md updated in place if the change is significant",
  "gate": "owner",
  "writes": true,
  "depends_on": ["review"]
 }
]
```

## Questions
```json
[
 {
  "header": "Scope",
  "question": "How far should the change go?",
  "multi": false,
  "options": [
    {"label": "Root-cause fix", "description": "Find why it breaks, fix that, add a test"},
    {"label": "Smallest change", "description": "Make this case work, touch nothing else"},
    {"label": "Rework it", "description": "Redesign this part properly"}
  ],
  "skip_if": "(?i)\\b(root cause|refactor|rework|redesign|rewrite|minimal|smallest|quick fix)\\b"
 },
 {
  "header": "When done",
  "question": "When it works, then what?",
  "multi": false,
  "options": [
    {"label": "Ship to master", "description": "Tests, commit, push - both machines update"},
    {"label": "Commit only", "description": "Commit here, do not push"},
    {"label": "Show me", "description": "Show the diff, no commit"}
  ],
  "skip_if": "(?i)\\b(ship|push|commit|don'?t (push|commit)|just show)\\b"
 }
]
```

## Checklist
- A check that fails before the change exists and passes after it.
- The root cause is named as file:line with the reason, not just the symptom.
- The fix prevents the same class of problem (a guard, a shared helper, a test on the boundary), not only this instance.
- Mac and Windows both considered: paths via pathlib, no hard-coded "/", text files opened with encoding="utf-8", the venv python path for each OS, no bash-only syntax in Windows code paths.
- No check deleted, skipped or loosened to make a suite pass.
- Each suite run under 60 seconds; long suites run with --only <suite>.
- Tests are offline: network, models, ComfyUI and Blender are faked at their boundary.
- The diff touches only the files in the plan; no drive-by reformatting.
- No secrets, tokens or personal paths in code or logs.
- Errors teach: a raised or returned error says what was wrong and what to do.
- New third-party code keeps its licence and is listed in docs/THIRD_PARTY.md (AGPL-3.0 compatible).
- UI changes: icons have hover tooltips (name + what it does), sizes in %, nothing overlaps, no repeated icon, no hotkey used twice in Forge.
- Debug prints, scratch files and commented-out code removed.
- git diff read in full before shipping.
- Shipped only to master with tools/ship.py; never a side branch.
- HANDOFF.md edited in place when the change is significant.

## Quality bar
- Great: the test is named as a sentence that a non-programmer understands ("a bake with no UVs says so instead of crashing").
- Great: diff under ~150 changed lines for a fix; a larger one is split or justified.
- Great: the root cause section would let another agent fix a sibling bug without re-investigating.
- Great: no new dependency when the standard library or an existing module does it.
- Acceptable code works; great code also fails loudly and clearly when misused.
- Great: suite time unchanged or lower; a new check costs under 1 s.

## Failure modes
- The fix makes the symptom vanish but the cause stays (a try/except swallowing the error) -> trace to the decision line; catch only what is expected and report it.
- A test passes on the Mac and fails on Windows -> path separators, CRLF, file locking, case-insensitive names: normalise with pathlib and newline="" and close files before moving them.
- Suite exceeds the 1-minute budget -> run --only the owning suite; mock the slow boundary (subprocess, HTTP, model) instead of running it.
- A test was weakened to go green -> restore it; fix the code or explain to the owner why the check is wrong and ask.
- The same edit fails twice with "old text not found" -> re-read the file region; the content changed or whitespace differs.
- A refactor broke callers not covered by tests -> search_files for every use of the symbol before changing its signature.
- Encoding crash on Windows (cp1252) -> pass encoding="utf-8" everywhere text is read or written.
- A push went to a side branch -> never; tools/ship.py pushes master only; delete nothing on the remote without the owner.
- Flaky test (passes sometimes) -> remove timing and ordering dependence: fixed seeds, fake clocks, no sleeps.
- Shipping while another machine pushed -> ship.py catches up with GitHub first; on conflict, merge and rerun the suites, never force-push.
- Fixed in one copy of duplicated code only -> search for the duplicate logic and share one helper.
- New feature works but the UI breaks layout -> run the matching tests/js or *_ui suite; check padding and overlap.

## Hand-off
Beyond the constitution's block: ROOT CAUSE (file:line and why), the failing-then-passing check name, the suites run
with counts and durations, the OS considerations, the full list of changed files, and for the ship stage the commit
hash and the first line of the commit message.

## Tools
- code_map path=<folder or file>: the outline before reading; then read_file with start_line/end_line.
- search_files pattern=<regex>: every caller of a symbol before changing it.
- edit_file old=<exact unique snippet> new=<replacement>: prefer over rewriting files.
- check_loki suite=<test_name>: run one suite in the LOKI worktree; empty runs all (avoid; budget).
- bash: python tools/ship.py --check --only <suite> (1-minute budget); git diff; node tests for tests/js.
- ship_loki message="<what changed, how it was checked>": tests, commit, push to master; only after the owner's OK.
- memory: recall earlier fixes in this area; learn the root cause when it was non-obvious.
- run_subagent agent=code-reviewer or bug-investigator: a second pair of eyes on a large diff or an unclear crash.

## References
- Google engineering practices, what to look for in a code review - https://google.github.io/eng-practices/review/reviewer/looking-for.html
- OpenAI, GPT-5 prompting guide (context gathering, verification before ending) - https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
- Anthropic, Building effective agents (evaluator-optimizer, tools as interfaces) - https://www.anthropic.com/engineering/building-effective-agents
- Google SRE book, postmortem culture (root cause, preventing recurrence) - https://sre.google/sre-book/postmortem-culture/
