# Storage


## Keeping LOKI small (engine/storage.py, 2026-10-27)

Owner: "i dont have that much space we cant keep this stuff its just for testing and later people will need some
sort of solutions if this is going to be a real app". Measured on the PC: 38 finished-job worktrees (~3 GB), an npm
project with node_modules an agent built in the Home workspace, every 3D model saved 4-6 times (identical "LODs" -
the decimate did nothing; textures in three folders), job logs and folders that only grew.

How it works (modelled on Hugging Face's cache scan / delete strategy, `docker system df` / `prune`, Photos'
"Recently Deleted"):

| Step | What |
| --- | --- |
| scan | usage per area + free space on the drive(s) - changes nothing |
| plan | what may go, item by item, with why and how much it frees; the plan has an id |
| clean | runs exactly that plan (or the ticked ids from it); regenerable things are deleted, your outputs go to `<data>/storage_trash/<batch>/` with a manifest |
| restore | puts a trash batch back |
| auto | the autopilot, every 6 h (busy or not): safe rules always, budget rules when over LOKI_STORAGE_BUDGET_GB (20) or the drive has less than LOKI_MIN_FREE_GB (25) free; trash older than LOKI_TRASH_DAYS (7) is emptied; finished jobs beyond the newest 500 leave the job list |

Rules: worktrees of finished jobs (never one with uncommitted changes, never `_baseline_loki`), job logs older than 7
days, build leftovers agents made in the workspace (node_modules, dist, caches, *.log) older than 3 days, download
caches in `big/` (budget only), Home deletes (`trash/`) older than 7 days, standing-goal drafts older than
LOKI_DRAFT_DAYS (7, budget only) and byte-identical copies (only when you tick them). Never: anything you liked (thumbs
up, a `.meta` "liked"), anything kept (`storage_keep.json`, POST /storage/keep), anything a running job uses, anything
outside LOKI's data folder and workspace. LOKI_STORAGE_AUTO=off|safe|budget.

At the source: the Blender LOD step no longer writes a "LOD" the decimate did not reduce; unattended jobs are told not
to set up build projects or logs in the workspace.

Where: Lab > Storage (app/ui/storage_view.js), GET /storage, POST /storage/clean {plan, ids}, /storage/restore {batch},
/storage/keep {path, on}, /storage/empty-trash; `python engine/storage.py` (usage) / `python engine/storage.py plan`.
