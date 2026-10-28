# Art pipeline specialists

One skill per role in LOKI's art pipeline (owner 2026-10-27: "they need specialized agents ... the prompts should be
very technical"). engine/art_specialists.py loads the right one for each stage, for the Prompt Expert and for team
agents, together with the best-matching skills from the downloaded libraries (harness_data/vendor).

concept -> technical-artist (turnaround) -> 3d-artist (mesh) -> 3d-finisher (Blender) -> lighting-render; video-director
for text-to-video.
