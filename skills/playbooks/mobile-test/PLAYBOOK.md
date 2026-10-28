---
name: mobile-test
title: Mobile app test
triggers: mobile test, test the app, test on phone, test on android, test on ios, android, ios, iphone, ipad, emulator, simulator, apk, ipa, app crashes, mobile app, phone app, tap through, smoke test, ui test, end to end, e2e, regression test, accessibility test, onboarding flow, login flow, deep link, mobile-mcp, device test, play store build, testflight
specialists: Mobile Tester, Tester, Reviewer, Builder
---
# Mobile app test

## Purpose
A real test pass of a mobile app (Android emulator, iOS simulator or a connected test device) driven through the
mobile MCP tools: the main flows tapped through, every step checked against the expected screen, crashes and defects
written up with exact steps, evidence from the device, and a pass/fail matrix. Done means: the test plan ran on at
least one named device, each case has PASS/FAIL with evidence, and every FAIL is a reproducible defect report.

## Stages
```json
[
 {
  "id": "plan",
  "specialist": "Mobile Tester",
  "objective": "Write the test plan: build under test, devices, the flows to cover, and test cases with steps and expected results.",
  "output": "tests/mobile/<app>-<date>/plan.md: build (version, file), devices (name, OS), cases (id, flow, steps, expected, priority)",
  "tools": ["read_file", "search_files", "memory", "write_file"],
  "check": "covers launch, onboarding, the 3-5 core flows, permissions, offline/poor network, rotation, background/foreground, and one accessibility pass; each case has an observable expected result",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "setup",
  "specialist": "Mobile Tester",
  "objective": "Find the device, install the build, and confirm a clean launch.",
  "output": "SETUP: device id and OS, install result, launch result, screen size",
  "tools": ["mobile_list_available_devices", "mobile_install_app", "mobile_launch_app", "mobile_get_screen_size", "mobile_list_apps"],
  "check": "the device is an emulator, simulator or test phone (never the owner's computer screen); the app id matches the build; first screen elements listed after launch",
  "gate": "",
  "writes": false,
  "depends_on": ["plan"]
 },
 {
  "id": "run",
  "specialist": "Mobile Tester",
  "objective": "Execute every case: read the screen's element tree, act on elements by their coordinates, check the expected result after each step.",
  "output": "tests/mobile/<app>-<date>/run.md: per case and step - action, element, result, PASS/FAIL; device screenshots saved for each FAIL",
  "tools": ["mobile_list_elements_on_screen", "mobile_click_on_screen_at_coordinates", "mobile_type_keys", "mobile_swipe_on_screen", "mobile_press_button", "mobile_open_url", "mobile_set_orientation", "mobile_take_screenshot", "mobile_save_screenshot"],
  "check": "the element tree read before every tap (no blind coordinates); the expected element or text present after the step; screenshots only of the device, saved in the run folder",
  "gate": "",
  "writes": true,
  "depends_on": ["setup"]
 },
 {
  "id": "crashes",
  "specialist": "Tester",
  "objective": "Collect crash reports and logs for any crash or freeze, and reproduce each failure once more from a fresh launch.",
  "output": "tests/mobile/<app>-<date>/crashes/<id>.txt and REPRO: yes/no per failure",
  "tools": ["mobile_list_crashes", "mobile_get_crash", "mobile_terminate_app", "mobile_launch_app", "bash"],
  "check": "every FAIL tried again from a clean start; crash logs attached; flaky failures marked flaky with the count (e.g. 2 of 3)",
  "gate": "",
  "writes": true,
  "depends_on": ["run"]
 },
 {
  "id": "report",
  "specialist": "Reviewer",
  "objective": "Write the result: pass/fail matrix, defects ranked by severity with steps, expected vs actual, evidence, and a release recommendation.",
  "output": "tests/mobile/<app>-<date>/report.md",
  "tools": ["write_file", "read_file"],
  "check": "each defect has title, severity (blocker/major/minor/cosmetic), device and OS, build, numbered steps, expected, actual, evidence path; recommendation GO / NO-GO with reasons",
  "gate": "owner",
  "writes": true,
  "depends_on": ["crashes"]
 },
 {
  "id": "fix",
  "specialist": "Builder",
  "objective": "When the app is the owner's code and he asks for it, hand the defects to the code playbook and re-run the failed cases after the fix.",
  "output": "the re-run results for the fixed cases appended to report.md",
  "tools": ["read_file", "run_subagent", "mobile_launch_app", "mobile_list_elements_on_screen"],
  "check": "only failed cases plus a short smoke run repeated; each fixed case now PASS with evidence",
  "gate": "owner",
  "writes": true,
  "depends_on": ["report"]
 }
]
```

## Questions
```json
[
 {
  "header": "Device",
  "question": "Which device should the test run on?",
  "multi": false,
  "options": [
    {"label": "Android emulator", "description": "On the PC"},
    {"label": "iOS simulator", "description": "On the Mac (Xcode)"},
    {"label": "Real phone", "description": "A connected test phone"},
    {"label": "Both platforms", "description": "One Android and one iOS run"}
  ],
  "skip_if": "(?i)\\b(emulator|simulator|real (phone|device)|both platforms|android|ios|iphone|pixel)\\b"
 },
 {
  "header": "Scope",
  "question": "How much should be tested?",
  "multi": false,
  "options": [
    {"label": "Smoke test", "description": "Launch and the core flow, 10 minutes"},
    {"label": "Full pass", "description": "Every main flow and edge cases"},
    {"label": "One flow", "description": "Only the flow I name"}
  ],
  "skip_if": "(?i)\\b(smoke|full (pass|test|regression)|regression|only the|just the|login flow|checkout|onboarding)\\b"
 },
 {
  "header": "Build",
  "question": "Which build should be tested?",
  "multi": false,
  "options": [
    {"label": "Installed app", "description": "The version already on the device"},
    {"label": "New build file", "description": "An .apk / .ipa / .app I name"}
  ],
  "skip_if": "(?i)(\\.apk|\\.ipa|\\.app\\b|\\.aab|installed|already on)"
 }
]
```

## Checklist
- The plan names the build version, the devices with OS versions, and every case with an expected result.
- Testing runs on an emulator, simulator or test phone; the owner's computer screen is never controlled or captured.
- The element tree (mobile_list_elements_on_screen) is read before each tap; taps use the element's centre.
- Screenshots are taken from the device only when the tree is not enough or as evidence for a FAIL.
- After each step the expected element or text is confirmed present.
- Launch from cold start measured (seconds to first interactive screen).
- Core flows: onboarding, sign-in/out, the 3-5 main tasks, settings, and data persistence after relaunch.
- Interruptions: background and return, rotation (portrait/landscape), notification or call simulation where possible.
- Network: offline and slow network behaviour gives a clear message, no crash, no data loss.
- Permissions: deny and allow paths both handled (camera, location, notifications).
- Input: keyboard covers no field; long text and special characters; empty submissions.
- Back button (Android) and swipe-back (iOS) behave as expected.
- Accessibility: every control has a label in the element tree; touch targets 44 pt / 48 dp; text scales with the system font size; contrast ok.
- Deep links open the right screen (mobile_open_url).
- Crash logs collected for every crash; every FAIL reproduced once from a clean launch.
- Defects written with numbered steps, expected vs actual, device, build and evidence.
- Basic security sanity for the owner's app: no secrets in logs, sensitive screens not shown in the app switcher, HTTPS only.
- GO / NO-GO recommendation with the blocking defects named.

## Quality bar
- Great: every defect is reproducible by someone else from the steps alone on the first try.
- Great: 0 blind coordinate taps - each tap traces to a named element.
- Great: core flows covered on both an Android and an iOS device when the app ships on both.
- Great: flaky failures quantified (n of 3 runs), not hidden.
- Great: report fits on one screen at the top (matrix + blockers), details below.
- Acceptable: the happy path passes; great: the edge cases (offline, deny permission, rotation) were tried.

## Failure modes
- Taps land on the wrong element -> re-read the element tree after every screen change; use the element's centre; check orientation and screen size first.
- Custom-drawn UI (games, canvases) has no element tree -> fall back to a device screenshot, find the target visually, tap, then confirm with another screenshot.
- Test hangs on a loading spinner -> wait with a bounded number of re-reads (e.g. 10 x 1 s), then record FAIL with the time waited.
- No devices found -> start the emulator/simulator on the machine that has it (Android on the PC, iOS on the Mac) via run_on_machine; report BLOCKED with the device list output if none.
- App installs but crashes on launch -> mobile_list_crashes and mobile_get_crash; record the top frames; test the previous build to see if it is a regression.
- Keyboard covers the submit button -> record as a defect; dismiss with the back button or swipe to continue the run.
- Results differ between runs -> reset app state (terminate, clear data or reinstall) before each case; mark flaky with counts.
- Typing into the wrong field -> tap the field from the element tree first and confirm it has focus.
- Reporting "it works" without evidence -> each PASS names the element or text that proved it.
- Screenshots of the computer instead of the device -> never; only mobile_take_screenshot / mobile_save_screenshot from the device.
- Heavy emulator on the Mac slows everything -> run Android emulators on the PC; keep the Mac to the iOS simulator, one at a time.

## Hand-off
Beyond the constitution's block: the device list with OS versions, the build tested, the pass/fail matrix (cases x
devices), defects by severity with their file paths, crash log paths, cold-start time, and the GO / NO-GO line.

## Tools
- mobile_list_available_devices: first call; pick the device id for the run.
- mobile_install_app path= / mobile_uninstall_app / mobile_list_apps: put the right build on the device.
- mobile_launch_app package= / mobile_terminate_app: clean starts between cases.
- mobile_get_screen_size / mobile_set_orientation: before coordinate work and for rotation cases.
- mobile_list_elements_on_screen: the source of truth for what is on screen and where; read before every action.
- mobile_click_on_screen_at_coordinates x= y= / mobile_long_press_on_screen_at_coordinates / mobile_double_tap_on_screen: act on an element's centre.
- mobile_type_keys text= submit=: type into the focused field.
- mobile_swipe_on_screen direction=: scroll lists and pages.
- mobile_press_button button=BACK|HOME|ENTER: system navigation.
- mobile_open_url url=: deep links.
- mobile_take_screenshot / mobile_save_screenshot: device evidence for FAILs and canvas UIs.
- mobile_list_crashes / mobile_get_crash id=: crash logs.
- run_on_machine machine=pc|mac: start the emulator or simulator on the machine that has it.
- write_file: plan.md, run.md, report.md under tests/mobile/<app>-<date>/.

## References
- mobile-next mobile-mcp (tools, accessibility-first workflow) - https://github.com/mobile-next/mobile-mcp
- OWASP Mobile Application Security Testing Guide (MASTG) - https://github.com/OWASP/owasp-mastg
- OWASP Mobile Application Security project - https://owasp.org/www-project-mobile-app-security/
- Touch target sizes (Apple 44 pt, Material 48 dp) - https://frontendchecklist.io/rules/accessibility/touch-targets
- LOKI webapp-testing skill (observe, act, verify loop) - skills/anthropic/webapp-testing/SKILL.md
