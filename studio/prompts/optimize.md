---
description: make the running game faster (find_lag, fix the top cause, measure again)
---
The game is slow. {{args}}
run_game, reproduce it, find_lag for a few seconds, then fix the biggest cause
(the busiest scripts in _process / _physics_process, too many nodes or draw calls, orphan nodes, big
textures). find_lag again and report the numbers before and after.
