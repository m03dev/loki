---
name: manga-artist
description: Draw a manga's character sheets and pages with LOKI's Manga Studio so the cast looks the same everywhere.
---
# Manga Artist - sheets and pages

1. **Sheets first**: `manga action=sheet character=<id> variants=2` for every main character before any page. The
   sheet becomes the reference picture of every panel that character is in. Pick the best with `action=pick`.
2. **One page at a time**: `manga action=draw_page page=<n>`. Each panel is drawn on its own at its panel's shape,
   with NO text (LOKI letters it afterwards). The drawing step waits for the owner's OK in Home > For you - submit,
   report the card, stop.
3. **Look at the result**: open pages/page-NN.png. Check every character matches the sheet (face, hair, outfit,
   colours), the shot and angle match the script, nothing is drawn as text.
4. **Fix one panel, not the page**: `manga action=edit_panel page=<n> panel=<k> note="<what is wrong>"` redraws only
   that panel (also an approval card).
5. **Monochrome** books are screentone ink; **colour** books keep each character's palette.

Never: redraw a whole page for one bad panel, draw text into a panel, change a character's outfit unless the script says.
