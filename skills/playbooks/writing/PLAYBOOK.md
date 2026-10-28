---
name: writing
title: Writing
triggers: write, writing, draft, essay, article, blog post, story, short story, novel, chapter, script, screenplay, dialogue, lore, worldbuilding, world building, backstory, character bio, poem, lyrics for, documentation, docs page, readme, guide, tutorial, how-to, manual, letter, email to, speech, outline, rewrite, proofread, edit my, summary of, game design document, gdd, quest text, item descriptions
specialists: Writer, Editor, Researcher, Reviewer
---
# Writing

## Purpose
A finished piece of text written to a brief - documentation, an article, a story or chapter, game lore and quest
text, a script, a letter - saved as a Markdown file in the workspace. Done means the outline was agreed (for anything
longer than a page), the draft was revised against the checklist, facts are sourced or marked as invented, and the
final file is clean, consistent in voice and the length asked. Long fiction follows the novel-writer skill's stages.

## Stages
```json
[
 {
  "id": "brief",
  "specialist": "Writer",
  "objective": "Pin down reader, purpose, form, length, voice and the one thing the reader must take away.",
  "output": "writing/<slug>/brief.md: reader, purpose, form, target length (words), voice (3 adjectives + one sample sentence), key message, must-include, must-avoid",
  "tools": ["memory", "library", "read_file"],
  "check": "the key message fits one sentence; length is a number; voice has a sample sentence; earlier owner notes on tone were recalled",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "gather",
  "specialist": "Researcher",
  "objective": "Collect the material: facts with sources for non-fiction; world, characters and continuity notes for fiction and lore.",
  "output": "writing/<slug>/material.md: facts [n] with URLs or file paths, or the canon (names, places, rules, timeline) the text must respect",
  "tools": ["read_file", "search_files", "web_search", "read_web", "library"],
  "check": "every fact has a source; fiction lists existing canon from the workspace (lore files, earlier chapters) so nothing contradicts it",
  "gate": "",
  "writes": true,
  "depends_on": ["brief"]
 },
 {
  "id": "outline",
  "specialist": "Writer",
  "objective": "Structure the piece: sections or beats with one line each and a word budget per part.",
  "output": "writing/<slug>/outline.md (headings or beats, purpose of each, words per part summing to the target)",
  "tools": ["write_file"],
  "check": "docs lead with the task the reader came for; articles put the main point first; stories have a want, an obstacle, a turn and an ending; budgets add up to the target within 10%",
  "gate": "owner",
  "writes": true,
  "depends_on": ["gather"]
 },
 {
  "id": "draft",
  "specialist": "Writer",
  "objective": "Write the full draft from the outline in the agreed voice, one section at a time, without stopping to polish.",
  "output": "writing/<slug>/draft.md",
  "tools": ["write_file", "read_file"],
  "check": "every outline part is present; length within 15% of the target; no placeholder text (TODO, lorem, [insert])",
  "gate": "",
  "writes": true,
  "depends_on": ["outline"]
 },
 {
  "id": "revise",
  "specialist": "Editor",
  "objective": "Revise in passes: structure, then clarity and cuts, then voice and rhythm, then line edit and facts.",
  "output": "writing/<slug>/final.md and writing/<slug>/edit-notes.md (what changed per pass)",
  "tools": ["read_file", "edit_file", "write_file"],
  "check": "at least 10% of words cut from a first draft unless already under target; passive and filler phrases removed; every fact still matches its source; names and terms spelled the same everywhere",
  "gate": "",
  "writes": true,
  "depends_on": ["draft"]
 },
 {
  "id": "review",
  "specialist": "Reviewer",
  "objective": "Read the final as the target reader and check it against the brief and checklist.",
  "output": "REVIEW: PASS or CHANGES with numbered items (paragraph - problem - fix)",
  "tools": ["read_file"],
  "check": "the key message is findable in the first 2 paragraphs (non-fiction) or the ending lands it (fiction); readability suits the reader; no contradiction with canon",
  "gate": "owner",
  "writes": false,
  "depends_on": ["revise"]
 }
]
```

## Questions
```json
[
 {
  "header": "Form",
  "question": "What kind of text is it?",
  "multi": false,
  "options": [
    {"label": "Docs / guide", "description": "Instructions people follow step by step"},
    {"label": "Article", "description": "An explainer or opinion piece"},
    {"label": "Story / lore", "description": "Fiction, world and character writing"},
    {"label": "Script", "description": "Dialogue and directions for a video or game"}
  ],
  "skip_if": "(?i)\\b(docs?|readme|guide|tutorial|article|blog|essay|story|novel|chapter|lore|script|screenplay|dialogue|letter|email)\\b"
 },
 {
  "header": "Length",
  "question": "How long should it be?",
  "multi": false,
  "options": [
    {"label": "Short", "description": "Up to 500 words"},
    {"label": "Medium", "description": "About 1,000-2,000 words"},
    {"label": "Long", "description": "3,000 words or more, in parts"}
  ],
  "skip_if": "(?i)\\b(\\d[\\d,]*\\s*(words?|pages?|chapters?)|short|brief|long)\\b"
 },
 {
  "header": "Voice",
  "question": "Which voice?",
  "multi": false,
  "options": [
    {"label": "Plain and direct", "description": "Short sentences, no jargon"},
    {"label": "Warm", "description": "Friendly, personal"},
    {"label": "Literary", "description": "Rich imagery and rhythm"},
    {"label": "Technical", "description": "Precise terms for experts"}
  ],
  "skip_if": "(?i)\\b(plain|simple|casual|friendly|warm|formal|literary|poetic|technical|in the style of)\\b"
 }
]
```

## Checklist
- Reader, purpose, length and voice written down before drafting.
- The key message fits one sentence and appears early (non-fiction) or is earned by the ending (fiction).
- Outline agreed by the owner for anything over ~800 words.
- Docs: task-first headings, numbered steps for procedures (one action per step), the expected result after key steps, prerequisites at the top.
- Articles: inverted pyramid - the main point first, details after; headings a skimmer can follow.
- Fiction: each scene has a point-of-view character with a want, an obstacle and a change; show through action and dialogue.
- Lore and game text: names, dates and rules match the existing canon in the workspace.
- Sentences average under ~20 words for plain writing; paragraphs 1-4 sentences on screen.
- Active voice by default; filler cut (very, really, in order to, it is important to note).
- One term per concept, used the same way everywhere; names spelled consistently.
- Facts carry sources; invented facts in fiction are consistent with each other.
- No placeholder text left.
- Length within 10% of the target in the final.
- Markdown renders cleanly (headings in order, lists, code blocks for commands).
- Quotes from sources only a few words, attributed.
- Long fiction follows the novel-writer stages and its foreshadowing ledger.

## Quality bar
- Great: a reader can say the key message after 30 seconds of skimming.
- Great docs: someone new completes the task without asking a question; every command copy-pastes and works on Mac and Windows (both shown when they differ).
- Great prose: the revision cut 10-25% of the draft and nothing was lost.
- Great fiction: dialogue lines are distinguishable without tags; every scene changes something.
- Great: readability matched to the reader (general audience around grade 8-9; experts can go higher, never padded).
- Acceptable text is correct; great text is correct, short and has a voice.

## Failure modes
- Generic, voiceless prose -> write the voice sample sentence in the brief and match it; replace abstractions with concrete nouns and verbs.
- The point is buried in paragraph 5 -> move the key message to the first two sentences; cut the warm-up.
- Docs steps fail on Windows -> show both commands where they differ (venv path, slashes); test the commands.
- Lore contradicts earlier canon -> collect canon in the gather stage; check names, dates and rules before the review.
- Draft far too long -> cut by outline part against its word budget; delete restatements and hedges first.
- Characters sound alike -> give each a speech habit (vocabulary, sentence length, what they avoid saying).
- Endless polishing of the first section -> draft everything first, revise after.
- Facts invented in non-fiction -> every fact needs a source or is removed or marked as an assumption.
- List-heavy text that should flow -> prose for argument and story; lists only for steps and parallel items.
- Copying from a source -> paraphrase and cite; quote a few words only.
- Owner's previous notes ignored (e.g. "less flowery") -> recall them in the brief and apply them to every pass.

## Hand-off
Beyond the constitution's block: the brief file, the final file with its word count, the edit notes (what each pass
changed), the sources list for non-fiction or the canon notes for fiction, and any part the owner still has to decide
(names, endings, claims marked uncertain).

## Tools
- memory action=recall query=<project or tone>: the owner's earlier style notes.
- library / search_files / read_file: earlier chapters, lore files, docs to stay consistent with.
- web_search + read_web url= query=: facts for non-fiction; cite them.
- write_file: brief, material, outline, draft and final under writing/<slug>/.
- edit_file: targeted revisions in the final.
- run_subagent agent=writer: one self-contained section when the piece is long; give it the brief, outline part and voice sample.
- voice action=speak: read a script aloud to check rhythm when it will be spoken.

## References
- Nielsen Norman Group, F-pattern reading on the web - https://www.nngroup.com/videos/f-pattern-reading-digital-content/
- Writing for the web (front-load, scannable) - https://sjsu.edu/digital/standards/writing-for-the-web.php
- Newcastle University design system, readability - https://www.ncl.ac.uk/design-system/ux/editorial/readability/
- LOKI novel-writer skill (long-story stages, foreshadowing ledger) - skills/novel-writer/SKILL.md
