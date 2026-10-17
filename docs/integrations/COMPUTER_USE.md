# Computer use and browser automation in LOKI (session 28)

The owner: "the core systems aren't fleshed out yet - TOOLS, CONNECTORS, COMPUTER USE". This page is the
research behind LOKI's `computer` tool and the Chromium path of `browse_page`, and how to use them.

## What the current open-source agents do (October 2026)

| Approach | Projects | How it finds a button | Fits LOKI's 7-9B local models? |
| --- | --- | --- | --- |
| Accessibility tree | [Windows-MCP](https://github.com/CursorTouch/Windows-MCP) (MIT, UI Automation via comtypes), [Cua Driver](https://cua.ai/docs/cua-driver) (macOS AX, Windows UIA, Linux AT-SPI), macOS-use, agent-desktop | the OS tells it every control's role, name and rectangle | **yes** - text only, exact, cheap |
| Screen parsing + vision | [OmniParser](https://github.com/microsoft/OmniParser) (icon detector + captioner), [UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) (Apache-2.0; UI-TARS-1.5-7B) | a vision model looks at a screenshot | needs a vision model; UI-TARS 7B fits the PC's 8 GB quantized |
| Virtual computers | [cua](https://github.com/trycua/cua) (already a LOKI add-on: Docker Linux / Lume VMs) | either of the above, inside a VM | the safe place for long unattended jobs |
| Browser accessibility snapshot | [playwright-mcp](https://github.com/microsoft/playwright-mcp) (Apache-2.0) | numbered refs from the page's accessibility tree | **yes** |

The consensus in 2026 (Windows-MCP, Cua Driver, playwright-mcp): **accessibility first, pixels only when that
fails** - a small text model can act on `[3] button "Save"` reliably; it cannot do pixel geometry.

## What LOKI does

`engine/computer_use.py` (safety, numbering, finding, vision fallback, log) over `engine/computer_backends.py`
(one backend per OS, ctypes only - nothing new to install except `comtypes` on Windows for UI Automation):

| | Windows (the PC) | macOS (the Mac mini) |
| --- | --- | --- |
| tree | UI Automation (comtypes): the focused window's controls, Windows-MCP's interactive types | AXUIElement: focused window + menu bar |
| screenshot | GDI BitBlt -> PNG (standard library) | `/usr/sbin/screencapture` |
| mouse / keyboard | SendInput (Unicode typing), SetCursorPos | Quartz CGEvent (Unicode typing, flags) |
| kill hotkey | Ctrl+Alt+Esc (GetAsyncKeyState) | Ctrl+Option+Esc (CGEventSourceKeyState) |
| permissions | none (an interactive desktop session) | Accessibility + Screen Recording for the app running LOKI |

The model sees:

    App: notepad - Untitled - Notepad
    3 elements:
    [1] button "Close" @(780,15)
    [2] menuitem "File" @(20,40)
    [3] field "Text editor" @(400,310)

and calls `computer(action="type", index=3, text="hello")`. Actions: elements, find (text, role), click /
double_click / right_click (index, text, or x/y), type, key ("ctrl+s"), scroll, open_app, apps, screenshot,
look (vision describes the screen), wait. When the tree is empty (games, canvas apps, remote desktops),
`click text="Save"` asks a vision model for the coordinates (`LOKI_VISION_MODEL`: an Ollama tag such as
`qwen2.5vl:7b`, or a provider name; else the active model), scaled from screenshot pixels to input points.

### Safety (in this order, every call)

1. The `computer-use` add-on (permission `computer:host`, high risk: the owner confirms when turning it on).
   Off = engine/policy.py refuses the tool and it is not offered to the model.
2. Never in a background job unless the owner allows it (`LOKI_COMPUTER_IN_JOBS=1`).
3. Kill switch: Ctrl+Alt+Esc, the mouse pushed into the top-left corner, or Stop in Settings > Tools.
   Everything is refused until the owner re-arms it there. Typing checks it between chunks.
4. A never-list (password managers, keychains; `LOKI_COMPUTER_NEVER`). Ctrl+Alt+Delete is never pressed.
5. Approval per app: the first action in an app asks the owner (never decidable by Laya); yes holds until
   LOKI restarts. `LOKI_COMPUTER_APPS` = apps the owner pre-approved.
6. Every action logged to `harness_data/computer_log.jsonl` (typed text only as its length and first characters).

BUILD_BRIEF section 7 says "browsers and computer-use only inside VMs". The owner has now asked for computer
use on the PC and the Mac themselves; the guardrails above keep it opt-in, supervised and stoppable. For
unattended work, cua VMs stay the right place.

## The browser

`browse_page` stays the text browser (session 27). With the `chromium` add-on on (Settings > Add-ons; Install
runs `pip install playwright` and `python -m playwright install chromium`), a page that "shows almost nothing
without JavaScript" is opened in a real headless Chromium automatically, with the SAME numbered-element view;
the numbers are written into the live page (`data-loki-idx`), so `click index=12` clicks exactly that element.
A fresh private profile per session (none of the owner's logins), downloads off, local-network requests blocked
in the browser itself, and typing a password or submitting a POST form asks the owner (refused in jobs).
`engine='chromium'` forces it; `LOKI_BROWSER=text|chromium|auto`; `LOKI_BROWSER_HEADED=1` shows the window.

## Next

- UI-TARS-1.5-7B (Q4) on the PC as the vision model for apps without a tree; OmniParser if it is not enough.
- Run the computer tool inside cua VMs for unattended jobs (the same backend code runs in a Windows VM).
- Cache what worked per app/site (Stagehand's idea) so a small model does not re-plan each click.
