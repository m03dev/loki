# LOKI Spaces (archived 2026-10-21)

The owner took Spaces out of LOKI on 2026-10-21: "get rid of spaces, we dont need it in the directions we're going".
Following the "don't remove anything, only improve" rule, the whole feature is kept here instead of deleted:

- `spaces.js`, `spaces.css` - the full-window tab (was app/ui/)
- `spaces.py`, `spaces_api.py` - the host, signed requests, sealed messages, WebRTC signalling (was engine/)
- `test_spaces.py`, `test_spaces_ui.py` - its suites (were tests/, in tools/ship.py's list)
- `SPACES.md` - its design doc (was docs/)

To bring it back: move the files to their old folders, re-add the tab to app/ui/modebar.js MODES, the two
tags to app/ui/index.html, the `/spaces` GET/POST routes and `spaces_api.start()` to engine/loki_bridge.py
(see commit history), and the two suites to tools/ship.py.
