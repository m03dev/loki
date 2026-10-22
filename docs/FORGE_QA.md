# LOKI tests Forge

Owner, 2026-10-22: "clean up the menu buttons, some are not functional and look weird, can't even click them ... there
are some real bugs in the forge. I want you to start using LOKI to test the forge and everything, use it to send out
different agents ... plan this out right, reimagine."

The idea: LOKI is its own QA department. Four kinds of tester, from cheapest to most human, each feeding the next.

```
  sweeper (every 6 h, idle)        explorers ([loki] teams)        Ziva (real Mac / PC)        owner
  tools/forge_qa.py           ->   scenarios a person would do ->  GPU, real screens, input -> decides
        |                                 |                               |
        +------ problems ------> triage (engine/forge_qa_duty.py) <-------+
                                          |
                          "LOKI's idea (Forge QA)" in Settings > Lab
                                          |
                     evolve's improve agent: own worktree, a failing test first,
                     the fix, every test, tools/ship.py  ->  the next sweep checks it
```

## 1. The sweeper - `tools/forge_qa.py`

A real (headless) browser on the real UI. No model, no guessing: it checks what a person would click.

| Part | What it checks |
|---|---|
| `menus` | every menu of the window's menu bar in every menu set, and every submenu to any depth: each row on screen, the topmost thing under its middle (so a click lands on it), labelled, not a dead "not in Forge yet" row, rows not overlapping |
| `buttons` | every visible button in every workspace (Modeling, Sculpting, UV, Retopo, Bake, Materials, Animation): clickable, labelled or iconed, not a dead button, not on top of another button |
| `hotbox` | the Space hotbox (every menu name, every list, every flyout) and the Space wheel (every wedge, every submenu, with Back) |
| `commands` | runs EVERY command the menus offer, one by one, on a fresh cube: page errors, "could not run" messages, hangs, slow ones; a big result (a remesh) is cleared before the next command so one cannot break the rest |

```
python tools/forge_qa.py                      # everything, ~3 minutes on a slow box
python tools/forge_qa.py --only menus         # one part
python tools/forge_qa.py --size 900x1600      # a vertical monitor; 1280x720 for a laptop
```

The report is `harness_data/qa/forge_qa.json` (never committed) plus a summary on stdout.

## 2. Triage and the fix loop - `engine/forge_qa_duty.py` (the autopilot's `qa` duty)

* Every `LOKI_FORGE_QA_S` (6 h) when LOKI is idle, the sweep runs in the background; nothing else starts meanwhile.
* The report is compared with the last runs (`harness_data/qa/known.json`): new, fixed, repeating. Timing problems
  (slow / hangs) count only when they repeat - a busy machine is not a bug.
* Up to 3 new problems become **LOKI's idea (Forge QA)** in Settings > Lab, each with how to reproduce it.
  `LOKI_FORGE_QA_IDEAS=auto` (default) approves them at once (measured, narrow - like the speed watch), so evolve builds
  them: own worktree, a test that fails first, the fix, all tests, `tools/ship.py`. `=ask` makes them wait for "Build it".
* The autopilot log gets one line ("Forge QA: N problems over ... ; M fixed since the last run; proposed I12, I13").
* `LOKI_FORGE_QA=auto` (default) runs where Playwright is installed (Settings > Add-ons > Chromium); `off` stops it.

## 3. The explorers - `[loki]` teams

The sweeper cannot tell that a bevel looks wrong or that a workflow is confusing. The explorers are LOKI's own agent
teams doing what a person does, start to finish, and writing down what got in the way. They are queued in
ZIVA_TASKS.md under "For LOKI's own agents" and the autopilot starts them one at a time:

1. **Sweep + reproduce** - run the sweeper at three window sizes, reproduce each problem by hand, screenshot it.
2. **Modelling scenario** - a chair from a cube: Multi-Cut (with the modifiers), Extrude, Bevel, Soften/Harden, Mirror,
   Smooth Preview; undo / redo through all of it.
3. **Sculpting scenario** - a head in the Sculpting workspace: brushes from the strip and the wheel, masking, hide,
   levels, remesh, reduce, then back to Modeling.
4. **UV + bake + render scenario** - unwrap the chair, check the checker, bake, Path Traced Preview, send to Render Studio.

Each writes `qa/<name>.md` in the workspace (steps, what broke, how bad, a screenshot), which Home shows as Content.

## 4. Ziva and the owner

Ziva runs the sweeper on the real Mac and PC (GPU, real screen sizes, a pen) and turns what only a real machine shows
into `[claude]` requests. The owner sees the Lab ideas and the Content reports, and can stop any of it
(`LOKI_FORGE_QA=off`, "No" on an idea).

## What the first sweep found and fixed (2026-10-22)

* The Space hotbox's lists ran off the screen and under the next row's menu names (32 rows could not be clicked); the
  Space wheel's menus went off the viewport (24). Every floating list now fits the window and scrolls; the open menu's
  row is on top.
* Dead rows (Select > UV / Vertex Face / UV Shell / Multi, the toolbox's Lasso and Paint) - left out of every menu now;
  UV and UV Shell were made real (the UV Editor had them; an old placeholder hid them).
* The Outliner's buttons slid out of sight under the viewport (Freeze) - they wrap now.
* The viewport's panel menus were cut off in a narrow viewport (UV workspace) - they fold into one "Menus" button whose
  menus open as submenus.
* Planar / camera UVs on a 54k-face remesh froze Forge for over a minute (one canvas fill per face plus a forced layout
  per UV point) - now about 2 s.
* Help's tips were rows that did nothing when clicked - they are plain text now.
* The Outliner's fold title ran under the panel's float / close buttons; the Space wheel's menu could cover the next wedge.
