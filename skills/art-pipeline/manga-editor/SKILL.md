---
name: manga-editor
description: Letter, review and export a manga made in LOKI's Manga Studio.
---
# Manga Editor - lettering, review, export

1. **Review**: `manga action=review project=<id>` lists every problem: undrawn panels, unlettered pages, too many
   words in a balloon, a character not in the cast, a 4-koma without exactly 4 panels, a character without a sheet.
2. **Lettering**: words change without redrawing - `manga action=letter page=<n> panel=<k> data={"dialogue": [...]}`.
   Keep balloons short; split a long line into two balloons; narration goes in boxes, sound effects as sfx.
3. **Layout**: the layout follows the script's panel count (`action=layout layout=<name>` only with the same count).
4. **Read it like a reader**: open every page in order - does each page do its job, does the last page land?
5. **Export**: `manga action=export format=pdf` (and `cbz` for comic readers). Report the file paths.

Hand-off: the exported files, the review result (PASS / the open issues), what the owner should look at first.
