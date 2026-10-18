# Ziva's quality-of-life features, and LOKI's own versions

The owner (2026-10-17): "go through all ziva updates and patchnotes i want those quality of life features like when
you disconnect it gives you options and stuff".

Ziva (ziva.sh) is a commercial, proprietary AI agent for Godot. **Nothing of Ziva's was copied, decompiled or
ported.** This page lists what Ziva's PUBLIC patch notes and docs say each feature does; LOKI's versions were written
clean-room from those descriptions (engine/qol.py, app/ui/qol.js, app/ui/qol.css, two small edits in studio/ui).

Sources read (2026-10-17): the changelog https://ziva.sh/changelog (Ziva 3.3.0 back to the January 2026 patch
notes), the docs https://ziva.sh/docs (index), https://ziva.sh/docs/queue-and-steer,
https://ziva.sh/docs/keyboard-shortcuts, https://ziva.sh/docs/approvals, https://ziva.sh/docs/chat-history,
https://ziva.sh/docs/troubleshooting-connection, https://ziva.sh/docs/troubleshooting-ai-errors,
https://ziva.sh/docs/settings, https://ziva.sh/docs/usage-limit-best-practices, and the blog index
https://ziva.sh/blogs (release posts: ziva-3-release, ziva-2-4-release, ziva-release-free-gpt-mini-undo-button).
The GitHub repo ziva-sh/ziva-agent-plugin-godot could not be read from this session (no access), so its release
notes/issues are not in this list. Godot-only, billing and model-catalogue notes are left out; everything about
using the chat is in.

Status: **built** = new in this session; **had** = LOKI already had it (where); **partly**; **not built** (why).

## 1. When something goes wrong: options, not dead ends

| Ziva (source) | LOKI | What LOKI does |
| --- | --- | --- |
| Connection dropped: banner / "Unable to Reconnect" overlay, reconnects by itself; "Connection lost. Retrying… attempt 1/6" ([troubleshooting-connection](https://ziva.sh/docs/troubleshooting-connection)); "Plugin recovers from dropped connections", "Chats recover after connection drops" (3.0.9, 3.0.3, [changelog](https://ziva.sh/changelog)) | **built** | When LOKI's engine stops answering, a banner at the top: "LOKI's engine is not answering. Trying again in N s (attempt n). Your chats and your draft are kept." Buttons: **Reconnect now**, **Copy my message**, **What happened?**, hide. Backoff 2-3-5-8-13-20-30 s. When the engine answers again: "Connected to LOKI's engine again." |
| "Cut-off responses fail visibly" (3.1.1) | **built** | A message whose answer was cut off gets a card "The answer was cut off" (Reconnect now / Try again / What happened?), and the text goes back in the box. After reconnecting LOKI checks: if the engine finished the answer meanwhile, it is shown ("LOKI finished that answer while the connection was down"); if it is still working, it waits for it; otherwise it offers Send again. |
| "Failed turns offer retry, model switch, compaction, or account reconnect" (3.2.5) | **built** | Every failed answer gets a **recovery card**: what went wrong in plain words + the choices that fit. engine/qol.py `classify()` knows 14 kinds from LOKI's real error texts: rate limit, quota/credit, bad or missing key, context too long, model not downloaded, local model not running, timeout, network, no model ready, empty reply, busy, stopped, time/step budget, unknown. Choices: Try again, **Wait then try again (countdown)**, Use another model (lists the models ready right now), Use a model on this computer, Let LOKI pick (Smart), Summarize and try again, Fix the key (opens Connections), Local models, Start a new chat, Put it back in the box, What happened? |
| "Slow responses can extend the wait to 4 or 10 minutes, switch models, or retry" (3.2.5) | **built** | No news from the model for 90 s (setting) -> a card: **Keep waiting** (3 more minutes), **Stop and try again**, **Stop and use another model** (then a model picker card). LOKI's 8-second "Still working" heartbeat does not count as news. |
| Rate limits: "Rate limit resets shown" (2.5.0); "Free fallback when you hit your limit" (Feb); "Connected accounts fall back to Ziva usage when exhausted" (3.2.9) | **built** + had | The wait the provider asked for is read (Retry-After, "try again in 7.5s", Gemini's retryDelay) and counted down on the button; dropped connections and rate limits retry **by themselves** (up to 5 times, can be cancelled, setting). Quota -> "Let LOKI pick" first. Had: smart routing fails over between providers (engine/loki.py, provider_health). |
| "Expired BYO logins open Settings to reconnect" (3.2.2) | **built** | A refused/missing key -> "Fix the key" opens Settings > Connections. |
| Context exceeded -> new chat / smaller attachments / bigger model ([troubleshooting-ai-errors](https://ziva.sh/docs/troubleshooting-ai-errors)); "Ollama context overflow gets a clear message" (3.1.8) | **built** | Kind `context`: Summarize and try again, Use another model, Start a new chat. |
| "Broken local models fail immediately with a reason" (3.2.0); local models not appearing -> start the provider ([troubleshooting-ai-errors](https://ziva.sh/docs/troubleshooting-ai-errors)) | had + **built** | Had: `model_down_hint` (Ollama not running / model not pulled). Built: kinds `local_down` / `model_missing` -> Local models, or an online model. |
| "Connection errors explain why the sidecar is unreachable" (3.2.2); "Startup failures name the failed step with a one-click report button" (3.1.5); /export-logs (3.0.2) | **built** + had | **What happened?** (card button, banner button, Ctrl/Cmd+Shift+H, /why): the model and what it really used, the last steps and errors, how LOKI picked the model, provider health, the window's connection log, and **Copy this report**. When the engine is down it says what to do (it may be restarting after an update; quit and reopen; LOKI Studio's Logs). Had: boot.js rescue screen, LOKI Studio's logs from disk. |
| Offline | **built** | The computer goes offline -> "online models cannot answer" banner with **Use <local model>** when one is ready. |
| "Interrupted turns recover after restarts or crashes" (3.0.5); "Crash-interrupted turns are marked" (3.0.9); "Retrying after restart keeps history" (3.2.7) | **built** | The turn being answered is written to `<data>/qol/inflight.json` and removed when it ends. If LOKI quit, crashed or updated mid-answer, the next start shows "LOKI was closed while it was answering you (time): '...'" with **Send it again** (in that chat), **Put it in the box**, **Dismiss**. |
| "Drafts restore after failed sends" (Feb-Mar); "Drafts survive login" (Feb); "you can draft messages while your account loads" (3.3.0) | **built** | The message box is saved as you type and comes back after a reload, a crash or an update; a failed send puts the message back in the box. LOKI Studio too. |
| "Messages kept when errors occur mid-tool call" (2.5.0); "Empty replies no longer break conversations" (Feb-Mar) | had | engine/loki.py (empty-reply retry, condenser, session 28 loop fixes). |
| "Fewer stacked notices" (3.2.5); "Dismissible toasts" (3.1.5) | **built** | The recovery card replaces the duplicate red notice; banners have ×. |
| "Client disconnects cancel in-flight model requests" (3.2.5) | not built (on purpose) | LOKI keeps working when the window drops, and the window picks the answer up when it reconnects - the opposite choice, so no work is lost. |

## 2. Working while LOKI works

| Ziva (source) | LOKI | What LOKI does |
| --- | --- | --- |
| "Message queuing while Ziva works" (Feb-Mar); "Steer a running chat or queue your next task" (3.2.9); [queue-and-steer](https://ziva.sh/docs/queue-and-steer): Enter queues, Cmd/Ctrl+Enter steers; Queued/Steering labels; Steered shown where it was read; Steer, Send now, Edit, ✕ | **built** | Before, typing while LOKI worked **lost the message** (the box was cleared, send() returned). Now **Enter queues** it (a "Queued" row above the box; sent by itself when LOKI is free) and **Ctrl/Cmd+Enter steers**: the engine (engine/qol.py, wrapping the agent loop's `_trim_context`; loki.py untouched) adds it to the conversation at the agent's NEXT step - never between a tool call and its results - and the window shows it as **Steered** where it was read. Each waiting message: **Steer**, **Send now** (stops the current step, sends this first; what LOKI changed is kept), **Edit** (back to the box), **Remove**. A steer the agent never reached comes back as a queued message. |
| "Pressing Stop, or an error ending the task, returns all waiting messages to the composer" (queue-and-steer) | **built** | Stop puts waiting messages back in the box; after an error the queue pauses ("Send them" / "Put them in the box"). |
| "You can queue messages while a retry runs" (3.1.1); "Video uploads show a 'Message queued' state" (3.2.0); "'Agent is already processing' error fixed" (3.0.4) | **built** | Any send while busy queues (status "Queued - LOKI sends it when it is free"); no more "already handling a request". |
| "Long pastes become attachments, and oversized prompts show a clear error" (3.2.9) | **built** + had | A paste over 8,000 characters (setting) is saved as `uploads/paste-<time>.txt` and attached with `@uploads/...` (LOKI's existing @file attach). Had: the engine's "Prompt exceeds N characters". |
| "/compact command shortens long conversations" (3.0.3); "Rewritten context usage widget" (2.6.0); "Context usage widget in the chat box" (Jan-Feb) | **built** | After each answer, if the chat is past 75 % of what LOKI sends before its condenser summarizes, a bar: "This chat is getting long (82 %...)" with **Summarize now** (the agent's own condenser, `_model_view(requested=True)`; the full history is kept) and **New chat**. `/compact` does the same. |
| "Compaction now runs inside the turn, with status messages" (3.1.9); "Long chats recover at context limits" (3.1.5) | had | engine/condenser.py (session 26/27). |
| "Completion sound" (2.3.1); "Notification sounds with volume and preview" (2.5.0); "Completion sound plays on errors too" (2.6.1); "Desktop alerts for frozen editors" (3.1.2) | **built** (partly) | When an answer took longer than 20 s (setting) and you are in another window: a **desktop notification** ("LOKI finished" / "LOKI needs you" - the engine's macOS osascript / Windows toast / notify-send, text never inside a script) and an optional **sound**; also when LOKI waits for your OK. No volume slider; no frozen-window detector. |
| "Questions no longer time out after five minutes" (3.3.0) | partly | LOKI's approvals still expire after 90 s (engine safety, unchanged) - but now you get a notification when one is waiting and you are elsewhere. |
| "Skip unanswered questions; the work timer pauses while waiting" (3.2.9) | not built | LOKI's clarifying questions are plain chat replies; nothing to skip. |

## 3. Approvals

| Ziva (source) | LOKI | What LOKI does |
| --- | --- | --- |
| Allow once / **Always allow** (that exact tool permission, per project) / Reject ([approvals](https://ziva.sh/docs/approvals)); "'Allow always' rules survive restarts" (3.0.9) | **built**, safer | A third button on the approval card: **Allow for this session** - the SAME action (tool + exact details) is not asked again until LOKI's engine restarts. Never offered or accepted for policy.ALWAYS_ASK (delete_file, delegate), connector writes (ACTION_ALWAYS_ASK: email, calendar, GitHub, notes, home...) or extensions; not persisted (AGENTS.md: "approvals for risky actions" stay). "Ask me every time again" in the comfort dialog forgets them. |
| "Auto-approve all actions" setting | not in the window (on purpose) | `LOKI_AUTO_APPROVE` exists for the command line only; the window always asks for what the policy engine marks ASK. |

## 4. Chats

| Ziva (source) | LOKI | What LOKI does |
| --- | --- | --- |
| Sidebar chat search (3.0.0); "Search chats ... arrow keys and Enter" ([chat-history](https://ziva.sh/docs/chat-history)) | **built** (more) | **Search chats** icon under New chat and Ctrl/Cmd+K: searches every chat's **name and messages** (Ziva: titles only), snippets, arrows + Enter; opening a message hit finds the words in that chat. |
| Find in chat (Ctrl/Cmd+F) (chat-history) | **built** | A find bar over the chat: n / m, ↑ ↓, Enter / Shift+Enter, Esc. |
| Favorites ("Favorite chat") (chat-history) | **built** | **Pin** icon on each chat (hover; always shown when pinned): pinned chats stay at the top (`<data>/qol/prefs.json`). |
| Rename chats (3.0.0, chat-history); "Renamed chats keep their titles" (3.0.4); generated titles | **built** + had | Double-click a chat (or F2) to rename it (the engine's rename route existed, the window had no way to use it). Had: titles from the first message. |
| Chat outline, Previous / Next message (3.0.9, chat-history) | partly | Alt+↑ / Alt+↓ jump between messages; no outline rail. |
| "Copy a chat as Markdown" (3.2.9); "Download shared chats as Markdown" (3.1.1) | **built** + had | Ctrl/Cmd+Shift+C or `/copy` copies the chat as Markdown. Had: export as Markdown / page / JSON (research round 3). |
| "Fork a chat from a finished response" (3.2.9) | had | Branch from here (chat_plus.js). |
| Archive / delete archived chats (chat-history) | not built | LOKI deletes directly (×); pin covers "keep this one handy". |
| "Last open chat restored on startup" (3.1.1) | had | The engine keeps the active chat. |
| "Long chats load the newest 50 messages first" (3.2.1) | not built | LOKI's chats render at once; not a problem at current sizes. |
| "Hover timestamps" (2.5.0, 3.2.5) | not built | LOKI's stored messages have no per-message time. |
| "Thumbs up/down ratings" (Feb-Mar) | not built | (LOKI's compare-models vote covers model choice.) |

## 5. Keyboard and comfort

| Ziva (source) | LOKI | What LOKI does |
| --- | --- | --- |
| "Customizable shortcuts for settings, model picker, new chat, and sidebar" (3.2.9); [keyboard-shortcuts](https://ziva.sh/docs/keyboard-shortcuts): must include Ctrl/Cmd/Alt, Esc cancels, Tab leaves, one action per combination, Clear, Reset all; shortcuts pause while dialogs are open | **built** | **Shortcuts and chat comfort** (keyboard icon in the top bar, Ctrl/Cmd+/): New chat Ctrl/Cmd+N, Search all chats Ctrl/Cmd+K, Find in this chat Ctrl/Cmd+F, Model picker Ctrl/Cmd+Shift+M, Settings Ctrl/Cmd+, , Show/hide the chat list Ctrl/Cmd+B, Stop Ctrl/Cmd+., Copy chat Ctrl/Cmd+Shift+C, Previous/Next message Alt+↑/↓, What happened? Ctrl/Cmd+Shift+H, this dialog Ctrl/Cmd+/. Click one, press new keys (Ctrl/Cmd/Alt required; Esc/Tab cancel; a clash names the other action), Clear, Reset all. Saved per computer. In the box: Up brings back your last message (or the last queued one). |
| Voice input Ctrl/Cmd+Shift+Space "from anywhere" (3.3.0) | partly | Had: the mic button (voice.js). No global hotkey (an OS-wide hotkey is still not built - HANDOFF research round 3). |
| "Chats note model changes" (3.2.0); "Ziva says when it falls back to another model" (3.0.4) | **built** + had | Switching model adds "Switched to X. The next message uses it." Had: failover progress lines, /models doctor. |
| Thinking display (3.0.0 thinking bubbles; "Kimi K3 reasoning stays in the thinking section" 3.1.4) | **built** | "Show the model's thinking in the chat" (off by default): DeepSeek/NIM "thought:" lines appear as collapsible events. |
| Settings: completion sounds and volume; "Search settings" ([settings](https://ziva.sh/docs/settings)) | **built** / had | Comfort dialog: notify, after N s, sound (plays a preview when ticked), auto-retry, slow-answer seconds, thinking, paste limit, the session's allowed actions. Had: Settings search. |
| "Full-width chat option" (3.1.1); "Feature tips appear while Ziva works" (3.1.6); "Live file edits show files filling in" (3.2.7) | not built | Not asked for; candidates for later. |

## 6. Already in LOKI before this session (for completeness)

Plan / Ask modes, Undo + checkpoints (Review / Rewind), per-message cost and token labels, the usage dashboard,
slash commands and @-mentions, skills, MCP servers and LOKI's own MCP server, sub-agents (background jobs, teams),
voice input, background updates with a restart prompt (health-gated), "Clear data" (Settings > Your data), loop/stuck
detection that names the repeating call (stuck.py), todo checks before DONE (session 28), the boot rescue screen with
logs, a responsive window while the engine starts.

## LOKI Studio

Small, on purpose (another agent works in studio/): a failed send puts the message back in the box and says so; the
box is kept as a draft over a reload; when Studio's own server stops answering, the status line turns red and says it
retries every 4 s and that nothing typed is lost. Studio already queued follow-ups while a turn runs (docs/STUDIO.md).

## Where it lives

- `engine/qol.py` - classify/recovery/alternatives, Inflight, steering, session approvals, context + compact, search,
  pins, notify, diagnose, `install()` (wraps BridgeState.request_chat / request_approval and the agent's
  `_trim_context`), routes `GET /qol/state|context|search|diagnose|alternatives`, `POST /qol/classify|steer|
  steer/cancel|approval|approvals/clear|compact|pin|notify|interrupted/dismiss`.
- `engine/loki_bridge.py` - one GET block, one POST block, one start-up line (`qol.install`). loki.py untouched.
- `app/ui/qol.js` + `qol.css` - wraps app.js's globals (api, send, renderConversations, chooseModel); app.js untouched.
  Strings are English for now (like app.js's dynamic strings); the tooltips and dialog titles are in the 8 tables.
- `tests/test_qol.py` (in SUITES, ~20 s): the classifier on LOKI's real error texts, recovery, interrupted turns,
  steering into the real agent loop, allow-for-session and its refusals, context + Summarize now, search, pins,
  notify, the real BridgeHTTPServer with the real loki module (a steer sent during a real /chat reaches the
  conversation), and the window in headless Chromium against a scripted engine. Screens:
  `docs/operations/screens/qol-{start,recovery,queue,disconnected,shortcuts}.png`.
