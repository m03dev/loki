---
name: novel-writer
description: Write a long novel in stages (world, characters, outline, chapters, analysis, revision) with a foreshadowing ledger and continuity checks - the long-story pipeline of MuMuAINovel, translated to English.
---

# Novel writer - the long-story pipeline

Translated from MuMuAINovel's prompt pipeline (xiamuceer-j/MuMuAINovel,
backend/app/services/prompt_service.py), GPL-3.0 - `LICENSE-MuMuAINovel-GPL-3.0.txt` beside this
file. The prompt for each stage is its own skill (`stages/novel-world`, `novel-characters`,
`novel-outline`, `novel-chapter`, `novel-analysis` - all of them together in
`references/prompts.md`); this page is the workflow.

Everything lives in files under `novel/` in the workspace, so the work survives restarts and the
author can edit any stage between runs. Before each stage read what exists and continue from it;
never silently overwrite the author's edits.

## The stages (one per run unless the task asks for more)

| Stage | File | Prompt (stage skill) |
| --- | --- | --- |
| 0 Idea | `novel/00-idea.md` - title, genre, theme, premise, audience, narrative perspective, target chapter length | (Inspiration) |
| 1 World | `novel/01-world.md` - time period, location, atmosphere, rules | novel-world |
| 2 Characters | `novel/02-characters.md` (+ `novel/characters.json`) - characters AND organizations with relationships | novel-characters |
| 3 Opening outline | `novel/03-outline.md` - the first N chapters only | novel-outline |
| 4 Outline continuation | append to `novel/03-outline.md` | novel-outline |
| 5 Chapters | `novel/chapters/NN-title.md` + a summary line in `novel/04-summaries.md` | novel-chapter |
| 6 Chapter analysis | `novel/05-analysis.md` + `novel/foreshadows.md` | novel-analysis |
| 7 Revision | `novel/06-revisions.md` | revise from novel-analysis |

## Rules that make a long story hold together

- **Scale the world to the genre.** Contemporary/romance/campus: one city, one industry, one
  social layer - no grand eras or apocalypses. Only epics need a grand world.
- **Characters and organizations are different things.** Keep them apart in every list; an
  organization has a type, purpose, members, power level, base, motto.
- **Relationships only reference people already named** (no invented names), the first
  character has no relationships yet, intimacy runs -100 (enemy) to 100.
- **The opening outline is an opening, not the whole story:** show the world, bring on the
  main cast, plant the core conflict and the hooks, leave room to continue - no closure.
- **Context for every chapter:** this chapter's outline, the previous chapter's summary, the
  last few chapter summaries, the previous chapter's full text (for continuity of the last
  scene), the characters in this chapter, foreshadowing reminders, relevant memories.
- **Chapter prose:** follow the outline strictly; pick up exactly where the last chapter ended;
  keep each character's voice; stay within the word target (+-200 words); no chapter titles or
  meta notes in the prose; no "in conclusion"/"all in all" summaries; no rhetorical open
  question as the last line; never replay events from the previous chapter.
- **Foreshadowing ledger** (`novel/foreshadows.md`): every planted hint gets an id, a short
  title, category (identity, mystery, item, relationship, event, ability, prophecy), strength
  and subtlety (1-10), the characters involved, a keyword quoted from the text, and the chapter
  where it should pay off. When a chapter pays one off, mark that id resolved - same title.
- **Analyse every chapter** (hooks, foreshadowing, conflict, emotional arc, character states
  including who died or left, plot points, pacing) and score pacing, engagement and coherence
  1.0-10.0 honestly; the lower the score the more concrete fixes are required (below 4: 4-5
  fixes; 4-6: 3-4; 6-8: 1-2; 8+: 0-1).
- End each run with a DONE line naming the files written and the next stage.
