---
name: manga
title: Manga and comics
triggers: manga, comic, comics, comic strip, 4-koma, 4koma, yonkoma, webtoon, manhwa, graphic novel, panel, panels, speech bubble, speech balloon, lettering, storyboard page, doujinshi, one-shot manga, chapter, character sheet, oc, original character
specialists: Manga Writer, Manga Artist, Manga Editor, Reviewer
---
# Manga and comics

## Purpose
A finished, readable manga made by LOKI's Manga Studio (engine/manga.py, the `manga` tool; Forge > Manga in the
window): from one idea to an outline, a cast with locked looks and reference sheets, a panel script per page, every
panel drawn without text, real typeset lettering, a review against the script, and a PDF / CBZ. Done means every page
is composed with every panel drawn and every line lettered, the review lists no open issue (or the owner accepted
them), and the export files are on disk.

Methods: Oniichan's feature set (outline, OC library with variants, reference sheets, 8 page layouts, page / panel /
dialogue edits, colorize, upscale, present, export, 20+ languages) and FURU's AI 4-koma method (ki-sho-ten-ketsu,
per-panel style tags, dialogue kept apart from the drawing, wardrobe continuity, a QA pass) - re-built for LOKI.

## Stages
```json
[
 {"id": "brief", "specialist": "Manga Writer", "objective": "Turn the request into a project: premise, format (4koma / page / webtoon), page count, colour or mono, style, language, reading direction.", "output": "manga action=project -> the project id", "tools": ["manga"], "check": "the project exists (manga action=list shows it); the format fits the request (a gag strip -> 4koma, a story -> page, a phone read -> webtoon)", "gate": "", "writes": true, "depends_on": []},
 {"id": "outline", "specialist": "Manga Writer", "objective": "Write the outline: logline, tone, ending type, one story job per page, the last page lands the ending.", "output": "manga action=outline data={title, logline, tone, ending, pages:[{n, beat, summary, panels}]}", "tools": ["manga"], "check": "page count matches the brief; each page has a different beat; a 4koma follows ki-sho-ten-ketsu with a real turn in panel 3; no filler page", "gate": "", "writes": true, "depends_on": ["brief"]},
 {"id": "cast", "specialist": "Manga Writer", "objective": "Write the cast with locked looks: face, hair, build, outfit garment by garment with colours, signature colours, props, personality, voice.", "output": "manga action=characters data={characters:[...]}", "tools": ["manga"], "check": "1-6 characters, each look concrete enough to draw the same person twice (no 'cute girl'); names unique; library characters reused when the name matches", "gate": "", "writes": true, "depends_on": ["outline"]},
 {"id": "sheets", "specialist": "Manga Artist", "objective": "Draw a reference sheet (front, side, back, three expressions) for every main character, 2 variants each; pick the best.", "output": "manga/<id>/characters/*.png and each character's sheet set (action=sheet, then action=pick)", "tools": ["manga", "view_image"], "check": "each sheet shows one consistent character in every view, matches the locked look word for word, no text on the sheet", "gate": "owner", "writes": true, "depends_on": ["cast"]},
 {"id": "script", "specialist": "Manga Writer", "objective": "Write every page's panel script: shot, angle, setting, characters, action (what we see), emotion, panel style, dialogue apart from the art.", "output": "manga action=script page=<n> data={panels:[...]} for every page", "tools": ["manga"], "check": "4koma = exactly 4 panels, page = 5-8, webtoon = 4-7; shots and angles vary; no dialogue words in action; max ~18 words per balloon, max 3 per panel; every named character is in the cast", "gate": "", "writes": true, "depends_on": ["cast"]},
 {"id": "pages", "specialist": "Manga Artist", "objective": "Draw every page (each panel separately at its panel's shape, no text), then look at each composed page.", "output": "manga/<id>/pages/page-NN.png for every page (action=draw_page page=<n>)", "tools": ["manga", "view_image"], "check": "every panel drawn; characters match their sheets (hair, outfit, colours); the shot and angle match the script; no letters drawn into the art; bad panels redrawn alone with action=edit_panel", "gate": "owner", "writes": true, "depends_on": ["sheets", "script"]},
 {"id": "letter", "specialist": "Manga Editor", "objective": "Check and fix the lettering: balloon kinds, placement, length, reading order; change words without redrawing.", "output": "re-composed pages (action=letter)", "tools": ["manga", "view_image"], "check": "every line of the script is lettered and spelled exactly; balloons do not cover faces; tails point at the speaker; reading order follows the reading direction", "gate": "", "writes": true, "depends_on": ["pages"]},
 {"id": "review", "specialist": "Manga Editor", "objective": "Run the review and read the book page by page like a reader; export.", "output": "manga action=review (PASS or the issue list) and action=export format=pdf (+cbz)", "tools": ["manga", "view_image"], "check": "review ok, or every open issue named in the hand-off; the PDF has one page per composed page; files listed with paths", "gate": "owner", "writes": true, "depends_on": ["letter"]}
]
```

## Questions
```json
[
 {"header": "Format", "question": "What kind of manga should it be?", "multi": false, "options": [{"label": "Story pages", "description": "5-8 panels per page, a short story"}, {"label": "4-koma strip", "description": "Four panels: setup, development, turn, punchline"}, {"label": "Webtoon", "description": "A tall scroll for phones, in colour"}], "skip_if": "(?i)\\b(4-?koma|yonkoma|webtoon|strip|pages?\\b)"},
 {"header": "Look", "question": "Which look should the pages have?", "multi": false, "options": [{"label": "Classic ink", "description": "Black and white with screentones"}, {"label": "Full colour", "description": "Cel-shaded colour"}, {"label": "Chibi gag", "description": "Cute, big heads, comedy"}, {"label": "Gekiga drama", "description": "Serious, heavy hatching"}], "skip_if": "(?i)\\b(colou?r|black and white|b&w|mono|ink|chibi|gekiga|watercolou?r|pop)\\b"},
 {"header": "Length", "question": "How long should it be?", "multi": false, "options": [{"label": "1 page", "description": "A single page or strip"}, {"label": "4 pages", "description": "A short scene"}, {"label": "8-12 pages", "description": "A one-shot chapter"}], "skip_if": "(?i)\\b(\\d+|one|two|three|four|five|six|eight|ten|twelve) (pages?|strips?|chapters?)\\b"}
]
```

## Checklist
- The project exists and its format, colour, style, language and reading direction match the request.
- The outline gives each page one job; the last page is the ending; a 4-koma has a real turn in panel 3.
- Every main character has a locked look and a picked reference sheet before any page is drawn.
- Panel counts: 4-koma exactly 4, page 5-8, webtoon 4-7; the layout follows the count, never the reverse.
- Shots and angles vary across a page; the biggest moment has the biggest panel.
- No dialogue words in any panel's action; no text drawn into the art.
- Every script line is lettered, spelled exactly, in the right balloon kind (speech, thought, shout, whisper, narration, sfx).
- Balloons do not cover faces or key action; tails point at the speaker; reading order is right.
- Characters match their sheets on every page (hair, eyes, outfit, colours, props).
- Bad panels were redrawn alone (edit_panel), not whole pages.
- manga action=review run at the end; open issues named.
- Exports on disk: PDF (and CBZ when asked); paths listed.
- Every drawing step was submitted for the owner's OK (For you) and reported - none drawn another way.

## Quality bar
- Great: a reader understands each page without the outline; the 4-koma's punchline lands in panel 4.
- Great: the same character is recognisable in every panel from hair, outfit and colours alone.
- Great: balloons hold at most 18 words; at most 3 per panel; no balloon touches a panel border.
- Great: at least 3 different shot sizes per page; one establishing shot at each new location.
- Great: the export is a clean PDF at 150 dpi, one page per page, under 30 MB for 12 pages.

## Failure modes
- A character looks different on every page -> the look was vague or the sheet was skipped: lock the look in concrete words, draw and pick the sheet, redraw only the drifting panels with edit_panel.
- Garbled letters inside the art -> the model drew text: the panel prompt already says no text; redraw that panel with a note "no letters, no signs"; LOKI letters every word itself.
- The script has 9 panels for a page -> split the page in two (script the next page) rather than squeezing; a layout never changes the count.
- The 4-koma has no turn -> rewrite panel 3 so the situation changes (a reveal, a misunderstanding, a reversal) before drawing.
- Balloons cover faces -> move them (place=top-left / top-right ...) with action=letter; the picture is not redrawn.
- Writing step answered nonsense or no JSON -> write the JSON yourself in data= (action=outline without data shows the format).
- Drawing failed (no image backend) -> the PC's ComfyUI does pictures: check machines, then retry; on the Mac never load a heavy image model next to Blender.
- A long book stalls -> work page by page: script page n, draw page n, check, next.
- The owner sends a page back -> the note is the fix: edit_panel with that note for the panels it names; never redraw approved pages.

## Hand-off
Beyond the constitution's block: the project id, the page files in order, the export paths (PDF / CBZ), the
character sheets used, the review result, and which pages or panels still wait for the owner's OK.
