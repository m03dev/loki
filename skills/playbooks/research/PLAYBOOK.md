---
name: research
title: Research
triggers: research, research the, look up, find out, find the best, which are the best, compare the, compare them, investigate, compare, comparison, versus, vs, which is best, best way to, what are the options, alternatives to, survey, state of the art, literature, papers, sources, cite, citations, fact check, fact-check, is it true, how does, deep dive, report on, market, competitors, benchmark, pros and cons, recommend a, evaluate
specialists: Researcher, Reviewer, worker
---
# Research

## Purpose
A sourced answer or report: the question restated, a short answer first, the evidence with numbered citations to
primary sources, the disagreements and unknowns, and what to do with it in LOKI. Done means every claim that matters
traces to a source that was actually read, the sources were judged for quality, and the report is saved in
docs/research/ (or answered in chat for a quick question).

## Stages
```json
[
 {
  "id": "scope",
  "specialist": "Researcher",
  "objective": "Restate the question, split it into 2-6 sub-questions, set the effort budget and what a good answer must contain.",
  "output": "SCOPE: question, sub-questions, effort (quick: 3-10 calls / comparison: 10-30 / deep: 30+ with helpers), answer shape (table, recommendation, summary)",
  "tools": ["memory", "read_file", "search_files"],
  "check": "sub-questions do not overlap; each can be answered by sources; memory and docs/research/ were checked for an earlier answer",
  "gate": "",
  "writes": false,
  "depends_on": []
 },
 {
  "id": "search",
  "specialist": "Researcher",
  "objective": "Map the landscape broad-to-narrow: short queries first, then targeted ones; collect candidate sources per sub-question.",
  "output": "a source list per sub-question: title, URL, type (primary docs, paper, repo, vendor page, forum, blog), date",
  "tools": ["web_search", "research_web", "run_subagent"],
  "check": "at least 2 independent sources per sub-question, at least one primary (official docs, the paper, the repo, the standard); no query repeated; sub-agents (for deep work) each got an objective, output format, tool list and boundaries",
  "gate": "",
  "writes": false,
  "depends_on": ["scope"]
 },
 {
  "id": "read",
  "specialist": "Researcher",
  "objective": "Read the best sources and extract claims with exact numbers, dates and conditions; judge each source.",
  "output": "docs/research/<slug>-notes.md: claim - source [n] - quality (primary / secondary / weak) - date",
  "tools": ["read_web", "browse_page", "read_file"],
  "check": "every claim was seen on the page (not in a snippet); numbers carry units and conditions; vendor claims are labelled as vendor claims; dates noted for anything that changes fast",
  "gate": "",
  "writes": true,
  "depends_on": ["search"]
 },
 {
  "id": "synthesize",
  "specialist": "Researcher",
  "objective": "Write the answer: bottom line first, then the evidence by sub-question, the disagreements, the unknowns, and the recommendation for LOKI.",
  "output": "docs/research/<slug>.md (or the chat answer for a quick question) with numbered citations [n] and a sources list",
  "tools": ["write_file"],
  "check": "first paragraph answers the question; each paragraph's key claim has a citation; conflicting sources are shown side by side, not averaged; quotes under a few words",
  "gate": "",
  "writes": true,
  "depends_on": ["read"]
 },
 {
  "id": "verify",
  "specialist": "Reviewer",
  "objective": "Check citations against the sources and test the conclusion: does each cited page say that, and what would change the recommendation?",
  "output": "VERIFY: per citation OK / WRONG / UNSUPPORTED, and the corrected report",
  "tools": ["read_web", "read_file", "edit_file"],
  "check": "at least the 5 most important claims re-opened at their source; no citation points to a page that does not contain the claim; the recommendation states its key assumption",
  "gate": "",
  "writes": true,
  "depends_on": ["synthesize"]
 },
 {
  "id": "deliver",
  "specialist": "worker",
  "objective": "Report the bottom line, link the file, and save the lasting facts to memory.",
  "output": "the hand-off block and memory learn entries",
  "tools": ["memory"],
  "check": "report under 12 lines with the file path; 1-3 durable facts learned with their source",
  "gate": "owner",
  "writes": false,
  "depends_on": ["verify"]
 }
]
```

## Questions
```json
[
 {
  "header": "Depth",
  "question": "How deep should the research go?",
  "multi": false,
  "options": [
    {"label": "Quick answer", "description": "A few sources, an answer in chat"},
    {"label": "Comparison", "description": "A table of the options with a recommendation"},
    {"label": "Deep report", "description": "Many sources, a saved report with citations"}
  ],
  "skip_if": "(?i)\\b(quick|briefly|compare|comparison|versus|vs\\.?|table|deep|thorough|report|in depth)\\b"
 },
 {
  "header": "Sources",
  "question": "Which sources matter most?",
  "multi": false,
  "options": [
    {"label": "Official docs", "description": "Vendor docs, standards, the code itself"},
    {"label": "Papers", "description": "Academic papers and benchmarks"},
    {"label": "Practitioners", "description": "Forums, studio talks, real user reports"}
  ],
  "skip_if": "(?i)\\b(docs|documentation|papers?|arxiv|academic|reddit|forums?|practitioners?)\\b"
 }
]
```

## Checklist
- The question is restated and split into sub-questions before searching.
- Effort matches the ask: a quick fact is 3-10 calls, a comparison 10-30, a deep report uses helpers with clear boundaries.
- Memory and docs/research/ checked first for an existing answer.
- Queries start short and broad, then narrow; none repeated.
- At least one primary source per sub-question (official docs, the paper, the source code, the standard).
- SEO content farms and AI-written listicles are not used as evidence.
- Each claim was read on the page itself, not taken from a search snippet.
- Lateral reading for unknown sources: what do others say about this site or author?
- Numbers carry units, dates and conditions (hardware, version, dataset).
- Vendor and marketing claims labelled as such.
- Dates checked: anything about software or models older than ~12 months is re-checked for a newer version.
- Conflicts between sources shown, with which one is more credible and why.
- Unknowns listed plainly.
- Bottom line in the first paragraph.
- Numbered citations [n] on every key claim; sources list with URLs at the end.
- No paragraph copied; quotes only a few words.
- A recommendation for LOKI when the question is about a choice, with its key assumption.
- The top claims re-verified at their source.
- Lasting facts saved to memory with their source.

## Quality bar
- Great: a reader can act on the first paragraph alone; acceptable reports make them read to the end.
- Great: 100% of key claims cited, at least 50% of citations to primary sources.
- Great: comparisons in a table with the same criteria for every option and a clear winner per use case.
- Great: numbers are reproducible (version, settings, hardware stated), e.g. "81 frames at 480p on an 8 GB card".
- Great: says what would change the recommendation.
- Great: no citation error when the reviewer re-opens the top 5 claims.

## Failure modes
- Long, specific queries return nothing -> start with 2-4 word queries, read what exists, then narrow.
- The answer leans on SEO blogs -> go to the vendor docs, the repo README, the paper, the standard; use blogs only to find primaries.
- A claim from a snippet turns out wrong -> read_web the page with query= before citing; cite only what the page says.
- Outdated facts (old model versions, deprecated APIs) -> check release notes and dates; prefer sources from the last 12 months for fast-moving tools.
- Sub-agents duplicate each other's work -> give each a distinct sub-question, output format, tool list and stop condition.
- Endless research with no answer -> stop at the effort budget, write what is known, list the open questions.
- Sources disagree and the report averages them -> show both with their conditions and say which applies to LOKI's setup (Mac M4 16 GB, PC RTX 3070 Ti 8 GB).
- Copying paragraphs -> paraphrase; quote a few words at most; cite.
- A page cannot be fetched (blocked) -> find a mirror, the repo or another primary; note the gap rather than guessing.
- Report recommends something that conflicts with the owner's rules (cloud-only, non-open-source, heavy on the Mac) -> check the recommendation against AGENTS.md before delivering.
- Hallucinated URLs -> only cite URLs that came back from a search or were opened.

## Hand-off
Beyond the constitution's block: the bottom line in one sentence, the report path, the number of sources read with
how many are primary, the claims marked uncertain, the open questions, and the memory entries added.

## Tools
- memory action=recall query=<topic>: earlier findings first.
- search_files / read_file: docs/research/ and docs/ for what LOKI already knows.
- web_search query= mode=web|academic|discussion|news: short queries first; academic for papers, discussion for practitioner reports.
- research_web question= queries=[...]: one-call sourced answer for a sub-question; still verify the key claims.
- read_web url= query=<what you need>: read the relevant part of a page; the evidence comes from here.
- browse_page action=open url=: pages that need clicking through (docs navigation, forms).
- run_subagent agent=researcher tasks=[...]: deep reports, one sub-question per helper with a clear output format.
- write_file: docs/research/<slug>.md and <slug>-notes.md.
- memory action=learn text=<fact with source>: 1-3 durable facts at the end.

## References
- Anthropic, How we built our multi-agent research system (delegation, effort scaling, broad-to-narrow, citations, source quality) - https://www.anthropic.com/engineering/multi-agent-research-system
- SIFT / four moves for evaluating sources (lateral reading) - https://library.cod.edu/evaluating/SIFT
- OpenAI, GPT-5 prompting guide (context gathering budgets, stop conditions) - https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide
