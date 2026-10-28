---
name: design
title: UI and graphic design
triggers: design, ui design, ux, user interface, mockup, mock-up, wireframe, prototype, layout, screen design, app screen, web page design, landing page design, dashboard design, figma, fig file, openpencil, style guide, design system, components, color palette, colour palette, typography, font pairing, icon set, banner, flyer, poster layout, social card, capsule art, thumbnail layout, hud, game ui, menu screen
specialists: UI Designer, Copywriter, Reviewer, Builder
---
# UI and graphic design

## Purpose
Editable designs made with LOKI's design tool (OpenPencil): screens, wireframes, HUDs, social cards, store capsules,
posters - authored as HTML/CSS, turned into an editable .fig file, rendered to PNG, and linted. Done means the .fig
and the PNG exports exist at the asked sizes, the design follows a stated grid, type scale and colour tokens, the lint
passes (contrast, target size, spacing), and the owner's UI rules hold: icons with tooltips, sizes in %, no overlap,
padding everywhere, no repeated icons.

## Stages
```json
[
 {
  "id": "brief",
  "specialist": "UI Designer",
  "objective": "Define what is designed: the screens or artboards, their sizes, the user's main task on each, the content, and the existing style to match.",
  "output": "design/<slug>/brief.md: artboards with sizes, primary action per screen, content inventory, references (LOKI's own UI, earlier designs), constraints",
  "tools": ["library", "read_file", "search_files", "memory"],
  "check": "every artboard has a size and one primary action; content is real (no lorem) or marked as placeholder; LOKI's app/ui styles were read when the design is for LOKI",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "system",
  "specialist": "UI Designer",
  "objective": "Set the tokens: colour palette with roles, type scale, spacing scale, grid, radius and icon set.",
  "output": "design/<slug>/tokens.css (CSS custom properties) + tokens.md explaining roles",
  "tools": ["write_file", "read_file"],
  "check": "text/background pairs meet 4.5:1 (3:1 for large text and UI parts); spacing on a 4 or 8 px base expressed in % or rem for layout; type scale with 4-6 steps; one icon per meaning",
  "gate": "",
  "writes": true,
  "depends_on": ["brief"]
 },
 {
  "id": "wire",
  "specialist": "UI Designer",
  "objective": "Lay out low-fidelity wireframes in HTML/CSS with the grid and real content, and render them for a structure check.",
  "output": "design/<slug>/wire-<screen>.html and the exported wire PNGs",
  "tools": ["write_file", "design"],
  "check": "hierarchy readable in greyscale; primary action findable in 3 seconds; nothing overlaps at the target size and at 75%/125% widths",
  "gate": "",
  "writes": true,
  "depends_on": ["system"]
 },
 {
  "id": "visual",
  "specialist": "UI Designer",
  "objective": "Build the high-fidelity design with the tokens, real copy and images, and create the editable .fig.",
  "output": "design/<slug>/<slug>.fig and design/<slug>/<screen>.html",
  "tools": ["design", "write_file", "make_image", "library"],
  "check": "design create_from_html succeeded; the tree shows named frames and auto-layout groups (not loose absolute shapes); images drawn by LOKI had their prompts OK'd",
  "gate": "owner",
  "writes": true,
  "depends_on": ["wire"]
 },
 {
  "id": "lint",
  "specialist": "Reviewer",
  "objective": "Lint and inspect: contrast, target sizes, spacing scale, overlap, icon tooltips and repeated icons; fix and re-lint.",
  "output": "design/<slug>/lint.md with the lint output before and after fixes",
  "tools": ["design", "read_file", "edit_file"],
  "check": "lint has 0 errors; pointer targets at least 24x24 px (44 pt iOS / 48 dp Android on touch); every icon has a tooltip label naming it and what it does; no icon used for two meanings",
  "gate": "",
  "writes": true,
  "depends_on": ["visual"]
 },
 {
  "id": "export",
  "specialist": "UI Designer",
  "objective": "Export PNGs at 1x and 2x (or the platform sizes) and write the hand-off notes for the Builder.",
  "output": "design/<slug>/export/<screen>@1x.png @2x.png + design/<slug>/handoff.md (tokens, components, states, measurements in %)",
  "tools": ["design", "write_file"],
  "check": "exports exist at exact sizes; hover, pressed, disabled and empty states covered for interactive parts; handoff names every component and its states",
  "gate": "owner",
  "writes": true,
  "depends_on": ["lint"]
 }
]
```

## Questions
```json
[
 {
  "header": "What",
  "question": "What are we designing?",
  "multi": false,
  "options": [
    {"label": "App screens", "description": "Screens of an app or LOKI panel"},
    {"label": "Game UI / HUD", "description": "Menus, HUD and in-game panels"},
    {"label": "Graphic", "description": "Social card, poster, store capsule"},
    {"label": "Design system", "description": "Tokens and components only"}
  ],
  "skip_if": "(?i)\\b(screens?|app|panel|hud|menu|game ui|poster|flyer|banner|card|capsule|thumbnail|design system|tokens|components)\\b"
 },
 {
  "header": "Fidelity",
  "question": "How finished should it be?",
  "multi": false,
  "options": [
    {"label": "Wireframe", "description": "Structure only, greyscale"},
    {"label": "Full visual", "description": "Final colours, type and images"},
    {"label": "Both", "description": "Wireframe first, then the visual"}
  ],
  "skip_if": "(?i)\\b(wireframe|low.?fi|high.?fi|final|polished|mock.?up)\\b"
 },
 {
  "header": "Target",
  "question": "Which screen size?",
  "multi": false,
  "options": [
    {"label": "Desktop", "description": "1440x900 artboards"},
    {"label": "Phone", "description": "390x844 artboards"},
    {"label": "Both", "description": "Desktop and phone"}
  ],
  "skip_if": "(?i)\\b(desktop|phone|mobile|tablet|ipad|\\d{3,4}\\s*x\\s*\\d{3,4}|responsive)\\b"
 }
]
```

## Checklist
- Each artboard has a size, a user, and one primary action.
- Real content used (or clearly marked placeholders); no lorem in the final.
- Tokens defined once (colour roles, type scale, spacing, radius) and used everywhere.
- Contrast: body text 4.5:1, large text and UI components 3:1.
- Pointer targets at least 24x24 CSS px; touch targets 44 pt (iOS) / 48 dp (Android).
- Layout sizes in % (the owner's rule) with padding on every container; nothing overlaps at 75%, 100% and 125% widths.
- Every icon has a hover tooltip with its name and what it does; no icon repeated for different meanings; no duplicate icons in one toolbar.
- Visual hierarchy: one dominant element per screen; at most 3 type sizes per screen.
- Alignment to a grid (e.g. 12 columns desktop, 4 phone) with consistent gutters.
- States designed: default, hover, pressed, focus, disabled, empty, loading, error.
- Focus order logical and visible for keyboard users.
- Text in graphics is real text (set in HTML), not generated pixels.
- The .fig is editable: named frames, auto-layout groups, components for repeated parts.
- design lint shows 0 errors after fixes.
- Exports at 1x and 2x (or platform sizes) at exact pixel dimensions.
- For LOKI's own UI: matches app/ui styles, does not look like Godot, Forge stays Maya-like.
- Pictures drawn by LOKI had their prompts OK'd.

## Quality bar
- Great: a first-time user finds the primary action in under 3 seconds (squint test on the wire).
- Great: spacing uses only scale values; zero one-off margins.
- Great: lint clean on the first pass after the system stage - tokens prevent errors rather than fixing them later.
- Great graphics: the headline is readable at 25% size (feed thumbnail); 1 focal point, 1 message.
- Great hand-off: a Builder can implement without guessing a single size, colour or state.
- Acceptable designs look good at one size; great ones hold at 75-125% and in both themes when asked.

## Failure modes
- Elements overlap at other widths -> use flex/grid with % widths and gaps, min/max sizes; check 75% and 125%.
- The .fig is a flat picture (not editable) -> author with semantic HTML and flex/grid so create_from_html maps it to frames and auto layout; avoid absolute positioning.
- Low contrast caught late -> set colour roles with contrast pairs in the tokens before any screen.
- Icons without labels confuse -> add tooltip text (name + action) to every icon button; add aria-label in the HTML.
- Same icon used for two actions -> one icon per meaning; pick a different glyph or add a label.
- Tiny click targets in toolbars -> 24 px minimum hit area with padding even when the glyph is 16 px.
- Generated image contains garbled text -> generate imagery without text; put all text in HTML.
- Design does not match LOKI's existing UI -> read app/ui CSS first and reuse its tokens.
- Too many fonts and sizes -> one family (two at most), 4-6 sizes in the scale, 3 per screen.
- Missing states make the build guess -> list every interactive component with all its states in the hand-off.
- Export blurry on retina -> export @2x; keep vector icons as SVG.

## Hand-off
Beyond the constitution's block: the .fig path, the export list with sizes, the tokens file, the lint result (before
and after), a component list with states, measurements in %, the icon list with tooltip texts, and open questions
on content.

## Tools
- design action=create_from_html html=<path or markup>: makes the editable .fig from HTML/CSS and renders a PNG.
- design action=tree: inspect the frame/auto-layout structure of the made design.
- design action=lint: contrast, target size, spacing and token checks; fix and run again.
- design action=export: PNG at the given scale (1x, 2x) for each artboard.
- write_file / edit_file: tokens.css, screen HTML, brief and hand-off notes.
- read_file / search_files: LOKI's app/ui styles and existing components.
- make_image / library: imagery for the design (owner OKs prompts); reuse library renders first.

## References
- OpenPencil features (.fig, auto layout, components, export, lint) - https://openpencil-docs.pages.dev/guide/features
- W3C, Understanding target size minimum (WCAG 2.2, 24x24) - https://w3c.github.io/wcag/understanding/target-size-minimum.html
- WCAG 2.2 contrast minimum - https://w3c-wiki.pages.dev/wcag/2.2/aa/1.4.3
- Touch target sizes (Apple 44 pt, Material 48 dp) - https://frontendchecklist.io/rules/accessibility/touch-targets
- Anthropic frontend-design skill (distinct visual direction) - skills/anthropic/frontend-design/SKILL.md
