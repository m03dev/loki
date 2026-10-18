# How fast LOKI starts (session 30)

The owner: "don't stress the user, it should be quick - if we need to move to Rust to be fast we do,
anything and everything is on the table". This page has the numbers, what was changed, and an
honest look at Rust.

Measure it yourself (a throwaway data folder each run; nothing of yours is touched):

    python tools/measure_start.py              # median of 3: interpreter, imports, engine to /health
    python tools/measure_start.py --cold       # no cached bytecode: a first start
    python tools/measure_start.py --imports    # the engine's slowest imports

On a real machine the app also writes its own timings into `<data>/app/loki_app.log`:
`window shown after X s`, `engine ready after Y s (Z s since the app started) (W s since the
double-click)` - the last part when the native launcher (`Loki.exe` / `Loki.app`) started it.

## Numbers (Linux cloud box, Python 3.13, this repo; median of 5 runs unless said)

| Step | Before | After | What changed |
| --- | --- | --- | --- |
| bare interpreter | 0.018 s | 0.018 s | - (the floor) |
| `import loki_bridge` | 0.11 s | 0.11 s | - |
| `import loki` (the agent) | **1.25 s** | **0.59 s** | the MCP client (`mcp`, 0.73 s of it) is imported inside `connect_mcp`, which already runs in the background after the window is up |
| engine start -> `/health` 200 (warm .pyc) | **1.21 s** | **0.88 s** | the same |
| engine start, cold (no .pyc: a first start) | **3.32 s** (3 runs) | **2.38 s** | the same; the installers now also ship **pre-compiled .pyc** (unchecked-hash) for the runtime and the seed, so an installed LOKI's first start is the warm number (~0.9 s), not the cold one |
| launcher (`loki_launch.py --check`, set up) | - | 0.042 s | new: venv check + version pick |
| native launcher overhead (`Loki` -> Python) | - | 0.002 s | Rust, std only |
| first start of an installed LOKI: seed copy + venv from the bundled Python | 3-10 **minutes** (download uv + Python + ~40 packages) | **0.3 s**, offline | the installer carries Python and every package (`tools/bundle_runtime.py`) |

The window: until now `app/loki_app.py` opened the window only **after** the start-up update and the
engine answered - a person looked at nothing for 1-3 s (cold) and, on the owner's git checkouts, for as
long as `git fetch` took (its timeout is 25 s). Now the window opens **first**, with a start screen, and
the update + engine start run behind it; the window switches to LOKI the moment the engine answers.
pywebview's own start (WebView2 / WKWebView) could not be timed here (no display, no pywebview on the
cloud box) - the `window shown after` log line gives that number on the real machines (ZIVA W44/M33).

An installed LOKI used to check the release feed, download and pre-flight a new version **before**
its window opened (up to 20 s for the feed, minutes for a download + self-test). Now the engine's
background check downloads and pre-flights it while LOKI runs (`release_update.prepare`), and the next
start only switches folders (`apply_ready`, no network). `LOKI_UPDATE_AT_START=1` restores the old order.

## What is still on the table (measured, not done)

- `loki.py` itself: 0.28 s of module code (8,500 lines run at import). Splitting the tool registry
  into lazily loaded modules would save maybe 0.1-0.2 s - not worth the churn while other agents
  edit `loki.py` daily.
- `serve()` before the API answers: ~0.3 s (workers, peers, autopilot, laya.warm). Starting the HTTP
  server first would need every route to cope with half-initialised state - risky for ~0.2 s.
- The 3D world / UI first paint: measured by the UI's own `/ui/timing` (session 22); unchanged here.

## The Rust question

Measured, the Python parts of the start are small: the launcher costs **42 ms**, the interpreter
**18 ms**, the engine **0.9 s** (mostly importing LOKI's own 8,500-line agent and its libraries,
which a Rust launcher would not change), and the window is drawn by the OS's own WebView either way.
Rewriting the launcher in Rust saves ~40 ms of a ~1-2 s start: invisible. Rewriting the engine in
Rust is a rewrite of LOKI (~63,000 lines of Python in engine/ alone, on Python-only libraries such
as `mcp`, `openai`, `pydantic`, `yt-dlp`) for well under a second - not justified by these numbers.

What Rust **is** good for here, and what was built:

- **`packaging/launcher` - a 340 KB native `Loki.exe` / `Loki.app/Contents/MacOS/Loki`**, Rust standard
  library only (no crates to audit). It gives Windows a real program to double-click (no console
  window - `windows_subsystem = "windows"` + `CREATE_NO_WINDOW` - no `.vbs`, no PowerShell flash), the
  portable zip a starter, macOS a Mach-O main executable (becomes the Python process with `exec`, so
  the Dock icon belongs to Loki.app), and stamps `LOKI_LAUNCH_T0` so the app can log "since the
  double-click". It falls back to the bootstrap when a slim build has no bundled Python.

What would be next if the real machines show the window itself is slow (`window shown after` > ~1 s):

- **A native start screen drawn by the launcher before Python starts** (Rust: a borderless window
  via the OS API - Win32 / Cocoa - or `tao`+`wry`), closed when the app's window reports ready. That
  is the only place Rust can win visible time. LOKI's own evolve step **E12 (a Maya-like loading
  screen)** owns the design; the hook is ready either way:
  - today the app shows `app/ui/splash.html` (E12 adds it; self-contained HTML, inline assets) in its
    window while the engine starts, and calls `window.lokiSplashStatus(text)` with progress lines;
  - a native splash would read the same file, or a PNG next to it, and the same ready signal
    (`/ui/ready`, which the window already posts).
- **Tauri as the window** (replacing pywebview): Tauri uses the same WebView2/WKWebView, so it would
  not draw faster; it would only matter if pywebview itself turns out slow to start. Not justified yet.

Decision: keep Python for the app and the engine; ship the tiny Rust launcher for the double-click
UX; open the window first; prepare updates in the background; ship pre-compiled bytecode; revisit a
native splash only with numbers from the real machines.
