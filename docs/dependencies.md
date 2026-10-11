# Dependencies & packaging

Loki is two halves that talk over a loopback socket:

1. **`addons/loki/`** — a GDScript editor plugin (the dock). Runs inside Godot.
2. **`harness/loki.py`** — the Python agent. Started by the dock, listens on
   `127.0.0.1:8766`.

## Runtime dependencies

- **Godot 4.3+** (the dock uses `EditorDock`).
- **Python 3.11+** with `mcp`, `openai`, `pydantic` (see `harness/requirements.txt`).
- **Ollama** — optional, only if you run a local model.
- **Node 22 + npm** — optional, only for the OmniRoute gateway.
- **`git`** — used once by `setup.bat` to fetch agent skills.
- **Cloud sign-in** — no extra deps. `cloud/auth_server.py` is stdlib-only;
  the bridge starts it for you, or run `cloud/run_cloud.bat`.

`setup.bat` creates `harness/.venv`, installs the Python deps, and clones the
optional skills into `harness/vendor/` (never committed — they are large).

## Why OmniRoute needs Node 22

OmniRoute is a Next.js 16 app and needs Node 20.19+/22 plus a native
`better-sqlite3` binary. It is entirely optional; Loki runs without it.

## Packaging direction

- **Local mode (today)** — the user installs Godot + Python, runs `setup.bat`,
  and supplies a model key (or uses Ollama). Everything stays on their machine.
- **Hosted mode (planned)** — "Sign in with Google" in the dock; the agent runs
  on Loki servers and users need only the addon. See `docs/google-signin.md`.

Both paths keep the same contract: the dock only ever talks to `127.0.0.1:8766`.
Hosted mode simply points that socket at a remote endpoint after sign-in.
