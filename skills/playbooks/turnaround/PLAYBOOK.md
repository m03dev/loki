---
name: turnaround
title: Turnaround sheet
triggers: turnaround, turn around, turnaround sheet, model sheet, character sheet, orthographic, ortho views, front side back, front view, side view, back view, top view, t-pose, a-pose, tpose, apose, reference sheet, model reference, views for 3d, rotation sheet, character turnaround, creature turnaround, prop turnaround, multi-view
specialists: Technical Artist, Concept Artist, Reviewer
---
# Turnaround sheet

## Purpose
An orthographic model sheet of ONE approved design - front, side (left profile), back, and top when asked - at the
same scale, feet on one line, in a neutral pose (T-pose for characters and creatures, upright for props), on plain
grey, drawn from the concept picture so the design does not drift. Done means: turnarounds/<name>-sheet.png and each
view in turnarounds/<name>/ exist, the views pass the height/centre/colour checks, and the owner OK'd the prompt.

## Stages
```json
[
 {
  "id": "source",
  "specialist": "Technical Artist",
  "objective": "Fix the one design the sheet is drawn from: the approved concept picture and its prompt, or a precise written subject when there is no picture.",
  "output": "SOURCE: images/<concept>.png (+ its prompt sidecar) or a subject description; KIND: character | creature | prop | vehicle",
  "tools": ["library", "read_file"],
  "check": "exactly one source design; the concept shows the whole subject with no parts hidden; if the concept crops the feet or hides the back, the gap is listed for the subject text",
  "gate": "",
  "writes": false,
  "depends_on": []
 },
 {
  "id": "spec",
  "specialist": "Technical Artist",
  "objective": "Write the geometry spec: height in heads, symmetry, a part list as primitives, the profile silhouette, flat albedo per part, the pose.",
  "output": "turnarounds/<name>/spec.md (height and proportions, symmetric vs asymmetric parts with side, parts as primitives, profile protrusions, colours per part, pose)",
  "tools": ["write_file", "read_file"],
  "check": "every design detail of the concept is listed and nothing new is added; asymmetric parts name their side (character's left/right); pose is T-pose (arms at 90 degrees, palms down) for characters and creatures",
  "gate": "",
  "writes": true,
  "depends_on": ["source"]
 },
 {
  "id": "draw",
  "specialist": "Technical Artist",
  "objective": "Submit the spec as the turnaround prompt for the owner's OK, then draw all views FROM the concept on one seed.",
  "output": "turnarounds/<name>-sheet.png, turnarounds/<name>/front.png side.png back.png (top.png), turnarounds/<name>/turnaround.json",
  "tools": ["make_turnaround", "run_on_machine", "machine_job"],
  "check": "turnaround.json shows mode from the reference picture (not text-only); all asked views exist; one seed for every view",
  "gate": "owner",
  "writes": true,
  "depends_on": ["spec"]
 },
 {
  "id": "align",
  "specialist": "Reviewer",
  "objective": "Check the views line up and match: silhouette heights, centring, feet line, colours against the concept, and part-by-part consistency.",
  "output": "ALIGN: per view height % of front, off-centre %, colour match score, and a part checklist (present in every view: yes/no)",
  "tools": ["read_file"],
  "check": "side and back heights within 12% of the front; centre offset under 8%; colour match at or above the pipeline threshold; every part from the spec visible in the views where it should be; no perspective, no cast shadow, no scenery",
  "gate": "",
  "writes": false,
  "depends_on": ["draw"]
 },
 {
  "id": "fix",
  "specialist": "Technical Artist",
  "objective": "Redraw only the failing views with one change at a time (same seed, stronger reference, simpler pose), at most 3 tries.",
  "output": "the replaced view files and an updated turnaround.json, or NO-GO with the reasons after 3 tries",
  "tools": ["make_turnaround", "make_image"],
  "check": "each retry changed exactly one thing and says which; after 3 failed tries the stage reports BLOCKED with the measured numbers",
  "gate": "",
  "writes": true,
  "depends_on": ["align"]
 },
 {
  "id": "handoff",
  "specialist": "Technical Artist",
  "objective": "Hand the sheet to the 3D stage: the front view as the mesh source, side and back as the check.",
  "output": "the hand-off block naming turnarounds/<name>/front.png as make_3d image= and the side/back paths for likeness",
  "tools": ["asset_pipeline"],
  "check": "the front view has a clean plain background and the full body with margin; when the asset pipeline is used, the turnaround stage is submitted with its files",
  "gate": "owner",
  "writes": false,
  "depends_on": ["fix"]
 }
]
```

## Questions
```json
[
 {
  "header": "Views",
  "question": "Which views do you need?",
  "multi": false,
  "options": [
    {"label": "Front, side, back", "description": "The standard model sheet"},
    {"label": "Plus top", "description": "Adds a top view for 3D"},
    {"label": "Plus three-quarter", "description": "Adds a perspective three-quarter view"}
  ],
  "skip_if": "(?i)\\b(top view|three.quarter|front.{0,12}side.{0,12}back)\\b"
 },
 {
  "header": "Pose",
  "question": "Which pose?",
  "multi": false,
  "options": [
    {"label": "T-pose", "description": "Arms straight out - best for rigging"},
    {"label": "A-pose", "description": "Arms down at 45 degrees - better shoulders"},
    {"label": "Upright prop", "description": "No pose - the object standing, front to camera"}
  ],
  "skip_if": "(?i)\\b([ta]-?pose|prop|vehicle|weapon|object)\\b"
 },
 {
  "header": "Source",
  "question": "Which design should the sheet follow?",
  "multi": false,
  "options": [
    {"label": "Newest concept", "description": "The newest concept picture in the library"},
    {"label": "Pick one", "description": "I will name the picture"},
    {"label": "Draw concept first", "description": "The Concept Artist makes one first, you OK it"}
  ],
  "skip_if": "(?i)(images/|\\.png|\\.jpe?g|this (picture|image|concept)|from the concept)"
 }
]
```

## Checklist
- Drawn FROM the approved concept picture (reference mode), not re-imagined from text.
- One design across all views: same parts, same colours, same proportions.
- Orthographic: no perspective convergence, no foreshortening, camera at mid-height.
- Same scale in every view; the top of the head and the soles of the feet sit on shared horizontal lines.
- Side and back silhouette heights within 12% of the front; centring within 8%.
- Characters/creatures in T-pose (arms horizontal, palms down, legs slightly apart) unless A-pose was chosen.
- Props upright, front facing the camera, no hand holding them.
- Plain flat grey background, no ground plane, no cast shadow, no scenery, no text labels inside the views.
- Flat albedo lighting: soft even light, no dramatic shading baked in.
- Asymmetric parts on the correct side in front and back views (they swap screen sides between front and back).
- Profile shows what sticks out (snout, backpack, tail, pauldrons) and how far.
- Back view shows what the concept could not: straps, cloth back, tail root - consistent with the spec.
- Each view at least 768 px tall, full subject with margin.
- turnaround.json written with the concept it came from and the seed.
- The owner OK'd the prompt before drawing.
- The front view is clean enough to be the make_3d source on its own.

## Quality bar
- Great: you could overlay front and side on horizontal guide lines (eyes, chin, shoulders, waist, knees) and every landmark sits within 2-3% of the height.
- Great: colour match of each view to the concept at or above the pipeline threshold, with no part changing colour between views.
- Great: no part appears in only one view without reason (a shield on the back must show its edge in the side view).
- Great: a TRELLIS.2 run on the front view gives a mesh whose side silhouette matches the side view within the 12% check.
- Acceptable sheets look right individually; great sheets agree with each other.

## Failure modes
- Views drawn separately do not match -> draw front/side/back on one canvas from the same reference and seed, then split; never four independent text prompts.
- Design drift from the concept (new armour, lost horns) -> pass the concept as reference and paste the concept's own prompt words; spec lists every part; remove adjectives that invite invention.
- Side view shows a three-quarter angle -> say "strict side profile, orthographic, the nose pointing exactly left"; reject anything where both eyes show.
- Back view is just a mirrored front with a face -> describe the back explicitly: "back of the head, no face visible, hair/helmet back"; check for eyes in the back view.
- Different heights per view -> fixed margins and "feet on one line, same scale"; crop and rescale per the measured silhouette only if the proportions themselves agree.
- Perspective in the views (feet larger than the head) -> say orthographic and eye level at the waist; remove lens words such as wide angle.
- Arms in the T-pose bent or crossing the body -> state 90 degrees, straight, palms down, fingers together; for creatures with wings, wings spread flat.
- Asymmetric details on the wrong side -> define left/right as the character's own; front view shows the character's left on screen right, the back view the opposite.
- Shadows or a floor in the views -> no ground plane, no cast shadow, flat even light, plain grey.
- Text labels ("FRONT", "SIDE") drawn into the picture -> never ask for labels; the tool lays out the sheet.
- Colour match fails though shapes are fine -> the views were drawn from text; switch to an edit-capable model that takes the concept picture.
- The concept itself hides parts (cropped feet, cape covering the back) -> fix the concept first or write the hidden parts into the spec and say so in OPEN.

## Hand-off
Beyond the constitution's block: the source concept path, the spec file, the sheet and per-view paths, the seed and
model, the ALIGN numbers per view (height %, centre %, colour score), and an explicit line "mesh source:
turnarounds/<name>/front.png; check views: side.png, back.png" for the 3D Artist.

## Tools
- library kind=images search=<name>: find the approved concept and its prompt.
- make_turnaround concept=<images/x.png> subject=<spec text> kind=character|creature|prop|vehicle views=front,side,back[,top] seed=: draws the sheet and splits the views.
- make_image reference=<concept> seed=<same> prompt=<one view>: only to redraw a single failing view.
- run_on_machine machine=pc / machine_job: when the model must run on the PC's GPU.
- asset_pipeline action=submit asset= stage=turnaround files=[...]: hand the sheet into LOKI's pipeline; action=brief to read what the stage is given.
- write_file: turnarounds/<name>/spec.md before drawing.

## References
- LOKI technical-artist specialist - skills/art-pipeline/technical-artist/SKILL.md
- LOKI asset pipeline view checks - engine/asset_pipeline.py (check_views)
- Character turnarounds, form in 2D space - https://binus.ac.id/bandung/dkv/2025/11/04/character-turnarounds-understanding-form-in-2d-space/
- Model sheets for consistent animation - https://wherecreativityworks.com/model-sheets/
- TRELLIS.2 input guidance (clean background, even light, no perspective) - https://fal.ai/learn/devs/trellis-2-image-to-3d-prompt-guide
