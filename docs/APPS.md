# LOKI Apps - LOKI turns into whatever you need

Four parts, one idea: LOKI is not one fixed app. It builds the small tools you need, changes into
the helper you need, and anyone can extend it.

| Part | What it is | Where |
| --- | --- | --- |
| **Mini-apps** | small apps LOKI builds or you install (budget, habits, study cards...) running inside LOKI | the grid icon in the sidebar -> **My apps** |
| **Gallery** | 12 ready-made apps, one click to install, LOKI can change them for you | Apps -> **Gallery** |
| **Modes** | Tutor, Writer, Coder, Researcher, Life admin, Small business, Student, Creator - and your own | the picker in the message box; Apps -> **Modes** |
| **Extensions** | plugins anyone can write: tools, an app, a panel, a mode | Apps -> **Extensions** |

## For users

**Get an app.** Open Apps (the grid icon under "New chat"). In **Gallery** press *Try* to look
(nothing is kept) or *Install* to make it yours. Or ask in chat: "make me a tracker for watering my
plants" - LOKI reads its app guide, builds the app and it shows up in **My apps**.

**Change an app.** Open it and type in the box at the top ("add a savings goal with a progress bar"),
or say it in chat ("add a savings goal to my budget app"). LOKI reads the app's files, changes them
and the app shows the change the next time you open it.

**Your data.** What an app saves is kept by LOKI (not in the browser), in `harness_data/app_data/`,
and is synced to your other machines over the peer link - the apps themselves too. An app on the Mac
is on the PC a few seconds after either machine changes it. Removing an app removes it on both
machines; it goes to LOKI's trash (`harness_data/app_data/.removed/`), its data is kept.

**Files.** When an app saves a file LOKI asks you first, in its own window (an app cannot draw over
that). Saved files go to `App files/<app>/` in your workspace and never overwrite an older file.
When an app wants to open a file, you pick it; the app sees only that one file.

**Ask LOKI.** Apps have "Ask LOKI" buttons ("where can I save money?"): LOKI answers with the app's
data in front of it, using your normal model route (local first; paid only within your budget).

**Modes.** The button left of Ask/Plan/Build picks a mode. A mode adds instructions to how LOKI works,
puts its tools first, points LOKI at skill packs and changes the starter prompts on the home screen.
Make your own in Apps -> Modes (*New mode*, or *Copy* a built-in one). *Export* writes
`<workspace>/LOKI modes/<id>.lokimode`; send that file to anyone, they *Import* it. A mode never
changes the safety rules: risky actions still ask; an imported mode that tries to switch off
approvals is refused.

**Extensions.** Apps -> Extensions: paste a folder path or an `https://` git URL and press *Scan*.
LOKI copies it aside and shows what it brings (tools, app, panel, mode), what it found (blocked
problems in red, things to look at in yellow). *Install* only if you agree. Its tools ask you before
each use until you press *Trust*. *Turn off* / *Remove* any time.

## For app authors (and for LOKI itself)

An app is one folder `<workspace>/apps/<name>/`:

```
manifest.json   {"name": "plants", "title": "Plants", "icon": "🪴", "description": "Watering tracker",
                 "entry": "index.html", "customize": ["Add a fertiliser reminder"]}
index.html      loads /ui/appkit/appkit.css + /ui/appkit/appkit.js, then app.js
app.js          your code
app.css         optional
```

The agent tools: `app_builder_guide()` (the rules, the API and a full example - always read first)
and `make_app(action=create|update|install|read|list|data, ...)`. `make_app` refuses what would not
work in the sandbox and says how to fix it (inline scripts, `onclick=`, CDN links, `fetch`,
`localStorage`, `alert`, JavaScript syntax errors).

**The sandbox.** The app runs in an iframe with `sandbox="allow-scripts"` only (an opaque origin:
no LOKI token, no cookies, no browser storage) and its page is served with
`default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; ...;
sandbox allow-scripts`. So: scripts from files only, no network at all, inline styles allowed.

**The bridge** (`window.loki`, all promises):

| Call | Does |
| --- | --- |
| `loki.ready(fn)` | runs `fn` once LOKI has said hello (at once when the page is opened on its own) |
| `loki.store.get(key, fallback)` / `set(key, value)` / `remove(key)` / `keys()` / `all()` | the app's own JSON store (256 KB per value, 2 MB per app) |
| `loki.ask(question, {data})` | a model answer, with the app's saved data + `data` as context |
| `loki.files.save(name, text)` | asks the owner; `{name, path}` or `null` if declined |
| `loki.files.open({accept})` | the owner picks a file; `{name, text}` or `null` |

Outside LOKI (the page opened directly) the store lives in memory and `ask` says LOKI is not
connected - handy for trying a page.

**The kit** (`window.kit` + CSS classes): `kit.h(tag, props, ...children)`, `mount`, `header`, `card`,
`stat`, `field`, `input`, `select`, `button`, `tabs`, `progress`, `bars`, `empty`, `toast`, `confirm`,
`ask`, `form`, `askLoki`, and helpers `uid today date money number sum groupBy sortBy debounce csv`.
Classes: `lk-app lk-head lk-card lk-grid lk-row lk-col lk-list lk-item lk-btn (.primary .ghost .danger .sm)
lk-input lk-select lk-textarea lk-field lk-tag lk-stat lk-progress lk-table lk-tabs lk-empty ...`.
The full reference is the comment at the top of `app/ui/appkit/appkit.js`. Midnight navy with
cyan-to-emerald accents; light mode follows the system unless LOKI sets `data-theme`.

The 12 templates in `app/ui/appkit/templates/` are complete examples (`habits` is the short one).

## Writing an extension

A folder or git repository with `extension.json`:

```json
{
  "format": "loki-extension/1",
  "id": "word_tools", "name": "Word tools", "version": "1.0.0",
  "description": "Counts and shouts words.", "author": "you", "homepage": "https://...",
  "tools": [{
    "name": "word_count", "description": "Count the words in a text.",
    "file": "tools/word_count.py",
    "parameters": {"text": {"type": "string"}}, "required": ["text"],
    "network": false, "timeout": 30,
    "tests": [{"args": {"text": "a b"}, "expect": "2"}]
  }],
  "app": "app",
  "panel": "panel",
  "mode": "mode.json"
}
```

- **Tools**: `def run(args: dict) -> str | dict | list | number`, standard library. They run like the
  tools LOKI writes for itself (`engine/user_tools.py`): a separate `python -I` process, no keys, no
  LOKI settings, a time limit and an output cap. Not allowed: `subprocess`, `ctypes`, `eval`/`exec`,
  deleting files, the network unless `"network": true`. A tool may not take the name of one of
  LOKI's own tools. Its `tests` run at install; a failing test leaves the extension off.
- **app** / **panel**: a mini-app folder (same rules as above); the app is listed in My apps, the
  panel opens from the extension's card. Storage keys `x:<id>` / `p:<id>`.
- **mode**: a mode file (the `.lokimode` format) installed with the extension.
- The scan blocks: no/invalid manifest, symbolic links, more than 400 files or 20 MB, tool code that
  breaks the rules, any text that tries to override LOKI's rules (the patterns downloaded skills are
  held to, `engine/skill_scan.py` + `engine/skill_rules.py`). It notes (yellow): programs that are not
  declared tools (never run), tools that use the internet, pages that reach the internet.
- Git: `https://` only, shallow clone, no prompts, `.git` removed after cloning.

## Engine map

| File | Does |
| --- | --- |
| `engine/apps.py` | apps on disk, serving rules + CSP, templates, per-app store (last writer wins per key, tombstones), saved files, peer sync, the guide |
| `engine/personas.py` | built-in and own modes, active mode, export/import, the system-prompt section |
| `engine/extensions.py` | format, scan, stage/install/remove, sandboxed tool runs, the tool registry |
| `engine/apps_api.py` | the window's routes: `/apps/*`, `/personas*`, `/extensions*` |
| `engine/loki_bridge.py` | `GET /apps/<w|t|x|p>/<name>/<file>` (no token, Host-checked) + the API routes (6 MB bodies) |
| `engine/peers.py`, `engine/peer_link.py` | `POST /peer/apps` (summaries, then only what is missing) |
| `engine/loki.py` | the session-29 block: `app_builder_guide`, `make_app`, `app_ask`, extension tools, wrappers around `system_prompt` and `_tool_enabled` |
| `app/ui/apps.js`, `apps.css`, `modes.js` | the Apps area, the window side of the bridge, LOKI's approval dialogs, the mode picker |
| `app/ui/appkit/` | `appkit.css`, `appkit.js`, `templates/` |
