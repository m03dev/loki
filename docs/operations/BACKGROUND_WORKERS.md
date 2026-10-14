# Background jobs - herdr and virtual computers

Loki can hand work to agents that keep going while you do something else. Open
**Background** in the sidebar, describe the job, pick where it runs, and Start. The badge
counts live jobs and turns amber when one is waiting for you.

| Run on | What runs | Where it works | Survives quitting Loki |
|---|---|---|---|
| **herdr** | Claude Code or Codex, interactive, in its own herdr workspace | its own git branch (worktree) | yes - herdr owns the terminal |
| **This computer** | Claude Code (`-p`) or Codex (`exec`) as a detached process | its own git branch (worktree) | the process keeps running; Loki re-attaches by pid |
| **Virtual computer** | shell commands, or a computer-use agent, inside a cua VM | inside the VM only | no (the VM session ends) |

Code: `engine/workers.py` (store, supervisor, three backends). Engine API:
`GET /jobs`, `POST /jobs`, `POST /jobs/cancel`, `POST /jobs/clear`, `GET /jobs/screenshot?id=`.
Tests: `python tests/test_workers.py` (offline; herdr and cua are faked at their boundary).

## Safety rules

- Only you start jobs (the app or the API). The model cannot spawn background work.
- Host jobs (herdr, this computer) only ever run a known coding agent - never a raw shell
  string. Raw commands are accepted only for the virtual computer.
- Claude Code runs with `--permission-mode acceptEdits`: it may edit files but still asks
  before shell commands (in herdr you answer by attaching; a headless job just skips them).
  Override with `LOKI_JOB_CLAUDE_MODE` in `harness_data/.env` - think hard before using
  `bypassPermissions`, and only in a virtual computer. Codex runs `--sandbox workspace-write`.
- **Separate git branch** (on by default): the job works in
  `harness_data/worktrees/<id>` on branch `loki/job-<id>`. Your working tree and any
  uncommitted changes are never touched. Review with `git diff master...loki/job-<id>`,
  merge what you want, then `git worktree remove harness_data/worktrees/<id>`.
- Every job has a time limit (15 min / 1 h / 4 h) and Cancel always works.
- Limits per backend: local 2, herdr 4, cua 1 (`LOKI_JOBS_LOCAL_LIMIT`, `..._HERDR_LIMIT`,
  `..._CUA_LIMIT`).

## Set up on the Mac mini

Run these in Terminal, then restart Loki. Each part is optional; the Background panel
shows which backends are ready and what is missing.

### 1. A coding agent (needed for herdr and "This computer")

```bash
claude --version      # Claude Code; sign in once with `claude` then /login
codex --version       # optional
```

### 2. herdr

```bash
brew install herdr            # or: curl -fsSL https://herdr.dev/install.sh | sh
herdr                          # open it once so its server is running; leave it open
herdr integration install claude   # richer working/blocked/idle status for Claude Code
```

Start a herdr job from Loki, then in herdr you will see a workspace named `loki-<id>`.
Attach any time to watch it or answer a permission prompt. Jobs keep running if you quit
Loki or close the herdr client; reopen `herdr` to get back to them.

### 3. Virtual computers (cua)

Into Loki's own environment:

```bash
cd ~/path/to/loki
harness_data/.venv/bin/pip install cua-computer cua-agent
```

Then pick a provider in `harness_data/.env`:

- **macOS VM (native on Apple Silicon):** install Lume from the cua docs
  (cua.ai/docs - self-hosted sandboxes), pull the image once, then
  `LOKI_CUA_PROVIDER=lume` and optionally `LOKI_CUA_IMAGE=macos-sequoia-cua:latest`.
- **Linux desktop in Docker:** install Docker Desktop, then
  `docker pull --platform=linux/amd64 trycua/cua-xfce:latest` and
  `LOKI_CUA_PROVIDER=docker` (the default). On Apple Silicon this image runs emulated,
  so it is slower than Lume.

For computer-use **agent** jobs (a prompt with no commands) also set
`LOKI_CUA_MODEL` to a computer-use model cua-agent supports, plus that provider's key.
Command jobs need no model.

First test - a job on "Virtual computer" with these commands:

```
uname -a
echo hello from the VM > /tmp/hello.txt
cat /tmp/hello.txt
```

It should finish **done**, show the output, and a screenshot of the VM.

## Verified vs not yet verified

- Verified offline (tests/test_workers.py, 68 checks): validation, queue limits, timeouts,
  cancel, persistence, worktree isolation, the local backend with a real child process,
  the herdr command sequence against a faked CLI, the cua flow against a faked Computer,
  and the engine endpoints.
- **Not yet run against the real tools.** The herdr commands follow herdr's CLI reference
  (`workspace create`, `pane run`, `agent get`, `agent prompt`, `pane read`); its JSON shape
  is parsed tolerantly. The cua calls follow cua's Computer SDK docs (`Computer(...)`,
  `run()`, `interface.run_command`, `interface.screenshot`). The first real run on the Mac
  is the acceptance test; anything that disagrees is a one-line fix in `workers.py`.
