---
name: novel-analysis
description: Chapter analysis stage of the novel pipeline (hooks, foreshadowing, scores) - translated from MuMuAINovel (GPL-3.0, see skills/novel-writer/LICENSE-MuMuAINovel-GPL-3.0.txt).
---

## CHAPTER ANALYSIS

You are a professional fiction editor and plot analyst.

Task: analyse chapter {chapter_number} "{title}" in depth: plot elements, hooks, foreshadowing,
conflict and character development. Foreshadowing is TRACKED: the open items of
`novel/foreshadows.md` are given with their ids; when this chapter pays one off, name its id.

Dimensions:
1. Hooks - mystery (unanswered questions), emotional (moments that resonate), conflict
   (confrontation, tension), cognitive (information that overturns expectations). Each: type,
   content, strength 1-10, position (opening / middle / end), and a keyword: 8-25 words copied
   VERBATIM from the text, to locate it.
2. Foreshadowing - new hints planted (content, intended use, subtlety 1-10) and old ones paid off
   (with their id). Each: title (short; a payoff keeps the ORIGINAL title, no "resolved" suffix),
   content, type planted | resolved, strength, subtlety, reference_chapter (for a payoff),
   reference_foreshadow_id (required for a payoff), keyword (verbatim 8-25 words), category
   (identity / mystery / item / relationship / event / ability / prophecy), is_long_term (pays
   off more than 10 chapters later), related_characters, estimated_resolve_chapter (required).
3. Conflict - type (person vs person / self / environment / society), the sides and their
   positions, intensity 1-10, resolution progress 0-100%.
4. Emotional arc - dominant emotion (a few words), intensity 1-10, how it moves.
5. Character states - for each character in the chapter: inner state before -> after,
   relationship changes, key actions and decisions, growth or decline, survival status (active /
   deceased / missing / retired - only when the chapter clearly shows it; never guess), and
   changes of organization membership (joined, left, promoted, demoted, expelled, betrayed).
   Organizations: power change, new base, new purpose, status, the triggering event, destroyed
   (only when the chapter clearly shows it).
6. Plot points - 3-5: content, type (revelation / conflict / resolution / transition), importance
   0.0-1.0, impact, keyword.
7. Scenes and pacing - main scenes, pace (fast / medium / slow), dialogue vs description.
8. Scores 1.0-10.0 (one decimal; use the whole range, do not give everything a middling score):
   pacing (1-3.9 chaotic, 4-5.9 readable with clear problems, 6-7.9 smooth with small issues,
   8-9.4 precise, 9.5+ masterful), engagement (dull ... irresistible), coherence (contradictory
   ... airtight); overall = the mean of the three, +-0.5 for the overall impression.
9. Improvements tied to the score: overall < 4.0: 4-5 concrete fixes for serious problems;
   4.0-5.9: 3-4 for the main problems; 6.0-7.9: 1-2 optimisations; 8.0+: 0-1. Each names where
   the problem is, why it is a problem, and how to fix it.

Write the analysis to `novel/05-analysis.md` and update `novel/foreshadows.md`.
