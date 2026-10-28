---
name: general
title: General task
triggers: quick question, how do i, summarize, summarise, organize, organise, sort out, tidy, clean up my, rename, find the file, where is, set up, configure, plan my, to-do, todo list, checklist, convert, look into, figure out, remind me, what happened, status of, check on, which machine, disk space, free up space
specialists: worker, Researcher, Reviewer
---
# General task

## Purpose
Anything that no other playbook claims: a question, a small chore on files, a setup step, a comparison, a plan.
It produces either an answer in chat backed by something that was actually read or run, or a file on disk.
Done means the owner's literal ask is answered or made, the result was checked by opening it, and nothing else
was changed on the way.

## Stages
```json
[
 {
  "id": "frame",
  "specialist": "worker",
  "objective": "Restate the ask in one line, say what DONE looks like, and decide whether a domain playbook fits better.",
  "output": "the first lines of the hand-off: GOAL, DONE-WHEN, KIND (general or the playbook name it moves to)",
  "tools": ["memory", "library"],
  "check": "the GOAL line names one concrete result (an answer, a file path, a changed setting); KIND is another playbook when the ask names a picture, model, video, code, research, design or music",
  "gate": "",
  "writes": false,
  "depends_on": []
 },
 {
  "id": "gather",
  "specialist": "worker",
  "objective": "Collect only the facts the answer needs: the files involved, earlier memories, what already exists in the library, and at most a few web pages.",
  "output": "a short fact list with where each fact came from (file path:line, memory id, URL)",
  "tools": ["read_file", "list_tree", "search_files", "memory", "library", "web_search", "read_web"],
  "check": "every fact has a source; no more than 10 tool calls for a simple ask, 25 for a comparison; nothing searched twice with the same words",
  "gate": "",
  "writes": false,
  "depends_on": ["frame"]
 },
 {
  "id": "act",
  "specialist": "worker",
  "objective": "Do the thing: answer, write the file, run the command, or make the plan - the smallest change that satisfies the ask.",
  "output": "the answer text, or the made file(s) at their real paths (notes/<slug>.md for plans and lists)",
  "tools": ["write_file", "edit_file", "bash", "run_on_machine", "machine_job"],
  "check": "a file that should exist is listed with its size; a command shows its exit code and the last lines of output; anything destructive was asked first",
  "gate": "",
  "writes": true,
  "depends_on": ["gather"]
 },
 {
  "id": "verify",
  "specialist": "Reviewer",
  "objective": "Open what was made or re-run the decisive command and hold it against the ask and the checklist below.",
  "output": "CHECKED lines: each checklist item PASS/FAIL with what was seen",
  "tools": ["read_file", "list_tree", "bash"],
  "check": "at least one check reads the real result back (file content, folder listing, command output) rather than trusting the act stage",
  "gate": "",
  "writes": false,
  "depends_on": ["act"]
 },
 {
  "id": "report",
  "specialist": "worker",
  "objective": "Tell the owner what was done in a few lines: the result, where it is, what was checked, what is left.",
  "output": "the final message with the hand-off block",
  "tools": ["memory"],
  "check": "under 12 lines unless the answer itself is long; paths are complete; any assumption taken is named once",
  "gate": "owner",
  "writes": false,
  "depends_on": ["verify"]
 }
]
```

## Questions
```json
[
 {
  "header": "Depth",
  "question": "How far should this go?",
  "multi": false,
  "options": [
    {"label": "Quick answer", "description": "A short, sourced answer in chat"},
    {"label": "Thorough", "description": "Read everything relevant and write it up"},
    {"label": "Just do it", "description": "Make the change, then tell me what changed"}
  ],
  "skip_if": "(?i)\\b(quick|briefly|short answer|in detail|thorough|deep dive|just do it)\\b"
 },
 {
  "header": "Result",
  "question": "Where should the result go?",
  "multi": false,
  "options": [
    {"label": "In chat", "description": "Answer here, no files"},
    {"label": "A file", "description": "Saved under notes/ in the workspace"},
    {"label": "Both", "description": "A short answer here and the full file"}
  ],
  "skip_if": "(?i)\\b(save (it|this)|as a file|\\.md|\\.txt|in chat|just tell me)\\b"
 }
]
```

## Checklist
- The goal is restated in one line before the first tool call.
- DONE is defined as something observable (a path, a value, an exit code).
- A more specific playbook was considered; if one fits, the work moved there and said so.
- Memory was recalled for this subject before starting (earlier answers, the owner's preferences).
- The library was checked before anything new was made.
- Every factual claim names its source (file:line, URL, command output).
- No file outside the ask was changed.
- Anything hard to undo (delete, move, overwrite, install, push) was announced and confirmed first.
- Heavy work (GPU, big downloads, model runs) went to the PC, not the Mac.
- Big files went to the external drive, never the Mac's internal disk.
- The result was opened and read back after it was made.
- A command that failed twice the same way was not run a third time.
- The report says what is not done, if anything, in plain words.
- Paths in the report are complete and real.
- If something was learned that will matter again, it was saved with memory action=learn.

## Quality bar
- Great: answers the question that was asked in the first sentence, then gives the evidence; acceptable: buries the answer under background.
- Great: 1 tool call for a fact already in memory, 3-10 for a simple lookup; a simple ask that took 30 calls is over-invested.
- Great: the owner never has to ask "where is it?" - every made thing has its path.
- Great: an assumption is stated once ("I took X to mean Y"); acceptable work hides it.
- Great: a plan or list is short enough to act on today (5-12 items), each item a verb plus an object.
- Great reports are under 12 lines; a long result goes to a file and the report points to it.

## Failure modes
- The agent answers a different, easier question -> reread the ask, quote its key noun in the GOAL line, check the answer against it.
- Endless searching with no answer -> stop after the budget, say what is known, what is not, and which source would settle it.
- A domain task handled generically (a picture described instead of drawn) -> move to the image/3d/code playbook at the frame stage.
- A file was "created" only in the chat text -> write it with write_file and list it before reporting.
- Mac ran out of memory during a local model run -> send heavy work to the PC with run_on_machine; keep one heavy job at a time on the Mac.
- A command works on the Mac and fails on Windows -> use pathlib-style paths and the venv python path for each OS; never assume bash on Windows outside Git Bash.
- The same failing call repeated -> read the error text, change one argument or the approach, or report BLOCKED with the error word for word.
- A cleanup deleted something the owner wanted -> list what would go, ask, then move to a _to_delete/ folder instead of deleting.
- The report claims success the checks did not show -> report only what verify saw; anything else is OPEN.
- Old facts reused as current (machine status, versions) -> re-check with list_machines or the real file before reporting.

## Hand-off
Beyond the constitution's block: the GOAL and DONE-WHEN lines from the frame stage; which playbook was considered
and why general was kept; the sources consulted (paths, URLs); any assumption taken; and, for a chore that changed
files, a before/after listing of the folder touched.

## Tools
- memory: action=recall query=<subject> first; action=learn text=<one lasting fact> at the end when something new was found.
- library: kind= and search= before making anything; reuse what exists.
- read_file / list_tree / search_files: the ground truth for anything in the workspace; search before reading whole files.
- web_search then read_web url= query=<what you need>: for current facts; prefer official docs and primary sources.
- write_file / edit_file: notes/<slug>.md for plans and lists; edit_file for small changes to existing files.
- bash: for commands; show the exit code; never destructive without asking.
- list_machines / run_on_machine / machine_job: when the work needs the PC (GPU, ComfyUI) or the other machine's files; write the task fully, it does not see this chat.

## References
- Anthropic, Building effective agents (workflows vs agents, ground truth from the environment) - https://www.anthropic.com/engineering/building-effective-agents
- OpenAI, GPT-5 prompting guide (eagerness, stop conditions, tool preambles) - https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
- Anthropic, How we built our multi-agent research system (scaling effort to the ask) - https://www.anthropic.com/engineering/multi-agent-research-system
