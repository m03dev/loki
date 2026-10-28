---
name: image
title: Picture
triggers: picture, image, draw, paint, painting, illustration, concept art, concept, artwork, poster, cover art, book cover, thumbnail, icon, wallpaper, key art, splash art, sprite, pixel art, texture, portrait of, landscape of, scene of, character art, creature design, logo idea, mood board, moodboard, sketch, render me a picture, upscale, make it bigger, variations
specialists: Concept Artist, Reviewer, worker
---
# Picture

## Purpose
A finished still picture made by LOKI's own image tools and saved in the workspace: concept art, a painting, a cover,
a sprite, a texture or a variation set. Done means: the prompt was OK'd by the owner in Home > For you, the picture
exists as a PNG on disk at the asked shape and size, it was looked at and holds up against the brief and the checklist,
and its prompt, seed and model are recorded beside it.

## Stages
```json
[
 {
  "id": "brief",
  "specialist": "Concept Artist",
  "objective": "Turn the request into a visual brief: subject, use (concept for 3D, cover, sprite, texture, mood), shape, style, and what must not appear.",
  "output": "BRIEF: subject / use / aspect / style / palette / must-have / never, plus the library items reused (paths)",
  "tools": ["library", "memory", "read_file"],
  "check": "use and aspect are stated; earlier owner notes for this kind of picture were recalled and applied; the library was searched for something to build on",
  "gate": "",
  "writes": false,
  "depends_on": []
 },
 {
  "id": "prompt",
  "specialist": "Concept Artist",
  "objective": "Write the art-director prompt in the order subject and action, setting, composition and camera, light, palette, mood, medium - and the negative list.",
  "output": "images/<slug>.prompt.txt with PROMPT, NEGATIVE, STYLE, SIZE, COUNT, SEED",
  "tools": ["write_file"],
  "check": "40-120 words; one subject (unless the brief is a scene); camera and light named concretely (e.g. 85 mm, eye level, soft key from front-left); 3-5 named colours; no words or logos asked for unless the brief is typography",
  "gate": "",
  "writes": true,
  "depends_on": ["brief"]
 },
 {
  "id": "draw",
  "specialist": "Concept Artist",
  "objective": "Submit the prompt for the owner's OK and, once approved, draw 2-4 variations on the PC.",
  "output": "images/<slug>-<n>.png (2-4 files) with the backend, model and seed of each",
  "tools": ["make_image", "make_sprite", "run_on_machine", "machine_job"],
  "check": "files exist, shorter side >= 1024 px (>= 512 for sprites before pixelizing); the run used the approved prompt unchanged",
  "gate": "owner",
  "writes": true,
  "depends_on": ["prompt"]
 },
 {
  "id": "select",
  "specialist": "Reviewer",
  "objective": "Look at every variation and pick the best against the brief, or send back one concrete change.",
  "output": "PICK: <file> with the reason, and per variation a one-line verdict (anatomy, composition, palette, artefacts)",
  "tools": ["read_file", "library"],
  "check": "each picture was opened and judged on hands/faces/eyes, extra limbs, text artefacts, silhouette readability at thumbnail size (128 px), and match to the palette and framing in the brief",
  "gate": "",
  "writes": false,
  "depends_on": ["draw"]
 },
 {
  "id": "finish",
  "specialist": "worker",
  "objective": "Finish the pick for its use: upscale for print or covers, pixelize for sprites, crop to the exact aspect.",
  "output": "images/<slug>-final.png (and <slug>-4x.png or sprites/<slug>-pixel<size>.png when asked)",
  "tools": ["upscale_image", "pixelize", "make_sprite"],
  "check": "final size matches the use (cover >= 2048 px tall, wallpaper 3840x2160, sprite at the asked pixel size on transparency); upscaled art has no waxy smearing (anime=true for drawn art)",
  "gate": "",
  "writes": true,
  "depends_on": ["select"]
 },
 {
  "id": "deliver",
  "specialist": "worker",
  "objective": "Hand over the final picture with its prompt sidecar and offer the next step (turnaround, 3D, video).",
  "output": "the hand-off block with the final path, the prompt file, and the next-step offer",
  "tools": ["library"],
  "check": "the final file appears in the library with its prompt; the report links the final and the prompt file",
  "gate": "owner",
  "writes": false,
  "depends_on": ["finish"]
 }
]
```

## Questions
```json
[
 {
  "header": "Style",
  "question": "Which look should it have?",
  "multi": false,
  "options": [
    {"label": "Painterly concept", "description": "Painted game concept art, readable shapes"},
    {"label": "Stylized 3D", "description": "Clean shapes and materials, like an asset render"},
    {"label": "Pixel art", "description": "Crisp pixels, a limited palette"},
    {"label": "Photoreal", "description": "Looks like a photograph"}
  ],
  "skip_if": "(?i)\\b(painterly|painted|concept art|pixel|photo ?real\\w*|realistic|stylized|cel|anime|manga|watercolou?r|oil|3d render)\\b"
 },
 {
  "header": "Use",
  "question": "What is the picture for?",
  "multi": false,
  "options": [
    {"label": "Concept for 3D", "description": "Full body, plain grey background, ready for a turnaround"},
    {"label": "Finished art", "description": "A scene or cover with its world and mood"},
    {"label": "Game sprite", "description": "Cut out, pixelized, transparent"},
    {"label": "Texture", "description": "Flat, tileable surface"}
  ],
  "skip_if": "(?i)\\b(for 3d|turnaround|cover|poster|wallpaper|sprite|texture|tileable|icon)\\b"
 },
 {
  "header": "Shape",
  "question": "Which picture shape?",
  "multi": false,
  "options": [
    {"label": "16:9", "description": "Wide - concept art, wallpapers, thumbnails"},
    {"label": "1:1", "description": "Square - icons, sprites, posts"},
    {"label": "2:3", "description": "Tall - covers and posters"},
    {"label": "9:16", "description": "Phone - Reels, TikTok"}
  ],
  "skip_if": "(?i)\\b(\\d{1,2}:\\d{1,2}|square|vertical|widescreen|portrait orientation|\\d{3,4}x\\d{3,4})\\b"
 }
]
```

## Checklist
- The prompt names the subject first, then action, setting, composition/camera, light, palette, mood, medium.
- The prompt was OK'd by the owner before any picture was drawn.
- Concept art for 3D: one subject, full body in frame with margin, feet visible, neutral relaxed pose, three-quarter front, plain flat light grey background, no ground plane, no cast shadow on the background.
- Camera stated: lens look (35 mm wide, 50 mm normal, 85 mm portrait), height (eye level, low, high), distance (wide, medium, close).
- Light stated: key direction and quality, fill, rim; time of day for scenes.
- 3-5 named colours and where they go.
- Negative list covers: extra fingers or limbs, text, watermark, logo, frame, blur, cropped subject.
- Size matches the use: 1024 px minimum on the short side; 2:3 for covers; 16:9 for concept and wallpapers.
- 2-4 variations drawn when the brief is open; 1 when it is a precise edit.
- Every variation was opened and judged; the pick has a stated reason.
- Hands, eyes and faces are anatomically right at full size; no melted details.
- Silhouette reads at 128 px (squint test).
- No unintended text or letters in the picture.
- Pixel sprites: transparent background, one outline colour, pixel size as asked, palette consistent.
- Upscale used anime=true for drawn/comic art, false for photoreal.
- Prompt, seed, backend and model recorded beside the file (the sidecar).
- Heavy runs went to the PC; the Mac only showed results.
- Owner notes from earlier send-backs for pictures were applied.

## Quality bar
- Great: the subject is readable in 1 second; the focal point sits on a thirds line or dead centre by intent, not by accident.
- Great: value structure works in greyscale (3-4 clear value groups); acceptable pictures turn to mud without colour.
- Great: palette limited to the 3-5 named colours plus neutrals; no rainbow noise.
- Great concept for 3D: a modeller could block it out from the picture alone - every part's shape and material is unambiguous.
- Great: no artefact visible at 100% zoom (fused fingers, broken straps, mirrored text).
- Great: the first variation set already contains a keeper in at least 1 of 4; if 0 of 4, the prompt changes, not just the seed.

## Failure modes
- Two subjects or a crowd when one was wanted -> say "a single <subject>, alone", drop plural words, remove scene nouns.
- Subject cut off at the feet or head -> ask for "full body in frame with margin, feet visible" and use a taller aspect (2:3 or 3:4).
- Mood painting instead of a usable concept -> plain flat light grey background, soft even light, neutral pose; move drama to a separate finished-art picture.
- Random text or signatures appear -> add text, letters, watermark, signature to the negative; never put quoted words in the prompt unless typography is wanted.
- Bad hands -> pose the hands simply (relaxed at sides, holding one object), draw larger, pick the best of 4; fix with an edit pass, not a full redraw.
- Style drift between pictures of one character -> reuse the same seed, the same style= and the concept's own prompt words; pass the earlier picture as reference.
- Dark muddy result -> name the key light and its direction; ask for clear value separation between subject and background.
- Upscale looks waxy or plastic -> use anime=true for drawn art; upscale 2x instead of 4x; upscale from the original, not a JPEG.
- Pixel sprite looks noisy -> draw the source as a sprite-source (subject alone on white), then pixelize with sprite=true, a fixed palette and outline=1-2.
- Generation fails on the Mac or runs out of memory -> send it to the PC (run_on_machine) and keep the Mac to viewing.
- The owner rejected a picture for a reason (e.g. flat light) -> that note goes into every later prompt of this kind; never repeat the rejected choice.
- Prompt too long and contradictory -> cut to 120 words; one style, one light setup, one camera.

## Hand-off
Beyond the constitution's block: the approved prompt file path, the picked file and the rejected variations with a
one-line reason each, the seed, backend and model of the pick, the final size in pixels, and the suggested next
playbook (turnaround for a 3D concept, video for an animated shot).

## Tools
- library kind=images search=<words>: reuse a concept or extend an earlier picture before drawing new.
- make_image prompt= style= count=2-4 width= height= negative= seed= reference=<picture here>: draws on the best backend; style game-concept / model-reference for 3D concepts; upscale=2|4 on the final.
- make_sprite prompt= or image=: one step from a description to a pixel sprite on transparency.
- pixelize image= size= palette= sprite=true outline=1-2: turn a picture into real pixel art.
- upscale_image image= scale=2|4 anime=true|false: Real-ESRGAN for print and cover sizes.
- run_on_machine machine=pc task=<full instructions> / machine_job job= wait=: when the Mac would have to run the model itself.
- write_file: the prompt sidecar images/<slug>.prompt.txt before submitting for the owner's OK.

## References
- Black Forest Labs, FLUX prompting summary (subject, setting, style, light, composition) - https://docs.bfl.ai/guides/prompting_summary
- Black Forest Labs skills, FLUX best practices - https://github.com/black-forest-labs/skills
- Real-ESRGAN anime model notes - https://github.com/xinntao/Real-ESRGAN/blob/master/docs/anime_model.md
- LOKI concept-artist specialist - skills/art-pipeline/concept-artist/SKILL.md
