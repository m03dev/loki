---
name: marketing
title: Marketing drafts
triggers: marketing, market it, promote, promotion, launch, announce, announcement, social post, social media, tweet, x post, instagram, tiktok caption, youtube description, reddit post, newsletter, press release, ad copy, ads, campaign, landing page, store page, steam page, itch page, app store, tagline, slogan, headline, hook, copywriting, copy for, devlog, community post, influencer, outreach, seo, brand voice
specialists: Copywriter, Concept Artist, Video Director, Reviewer
---
# Marketing drafts

## Purpose
Ready-to-review marketing drafts for the owner's work: positioning, posts per platform, store or landing page copy,
an announcement, and the matching visuals (made by LOKI and OK'd). Drafts only - LOKI never posts, sends, schedules
or submits anything. Done means a drafts folder with copy per channel that fits each platform's limits, visuals at the
right sizes, claims backed by real features, and a posting checklist the owner can follow himself.

## Stages
```json
[
 {
  "id": "position",
  "specialist": "Copywriter",
  "objective": "Write the positioning: who it is for, the problem, what it does differently, proof points from the real product, and the one-line pitch.",
  "output": "marketing/<slug>/positioning.md: audience, pain, promise, 3 proof points (each tied to a real feature/file), one-liner under 15 words, voice notes",
  "tools": ["read_file", "search_files", "library", "memory", "web_search"],
  "check": "every proof point exists in the product (file, feature, screenshot); the one-liner names the audience or the outcome; competitors checked briefly so the claim of difference is true",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "plan",
  "specialist": "Copywriter",
  "objective": "Pick channels and formats for the goal and list each draft to make with its size and length limit.",
  "output": "marketing/<slug>/plan.md: per channel - format, length limit, visual size, call to action, best posting time suggestion",
  "tools": ["web_search", "read_web", "write_file"],
  "check": "only channels the owner uses or asked for; limits stated per platform; one clear call to action per draft",
  "gate": "",
  "writes": true,
  "depends_on": ["position"]
 },
 {
  "id": "copy",
  "specialist": "Copywriter",
  "objective": "Write the copy per channel: 3 hook variants, the body, the call to action, alt text and hashtags where they fit.",
  "output": "marketing/<slug>/<channel>.md for each channel (variants labelled A/B/C)",
  "tools": ["write_file"],
  "check": "within each platform's character limit; hook in the first line (the part shown before 'more'); no claim beyond the proof points; no fake urgency, fake reviews or invented numbers",
  "gate": "",
  "writes": true,
  "depends_on": ["plan"]
 },
 {
  "id": "visuals",
  "specialist": "Concept Artist",
  "objective": "Make the visuals each draft needs - key art, store capsule, thumbnail, short clip - from the real product renders where possible.",
  "output": "marketing/<slug>/visuals/<channel>-<size>.png or .mp4 at the platform sizes",
  "tools": ["library", "make_image", "render_scene", "make_video", "design"],
  "check": "every prompt OK'd by the owner; sizes exact per platform; any text on images added in the design tool, not generated; real product shots preferred over invented ones",
  "gate": "owner",
  "writes": true,
  "depends_on": ["plan"]
 },
 {
  "id": "review",
  "specialist": "Reviewer",
  "objective": "Check every draft for truth, tone, limits, legal disclosures and typos, and assemble the posting checklist.",
  "output": "marketing/<slug>/README.md: each draft with its visual, the checklist the owner follows to post, and REVIEW findings",
  "tools": ["read_file", "edit_file"],
  "check": "character counts measured; every claim traceable; licences/credits for assets listed; sponsored or affiliate content marked as such; nothing was posted or sent",
  "gate": "owner",
  "writes": true,
  "depends_on": ["copy", "visuals"]
 }
]
```

## Questions
```json
[
 {
  "header": "Platform",
  "question": "Where will it go?",
  "multi": true,
  "options": [
    {"label": "X / Bluesky", "description": "Short posts and a thread"},
    {"label": "Reddit / forums", "description": "Community posts, devlog style"},
    {"label": "Store page", "description": "Steam / itch.io page copy and capsules"},
    {"label": "Short video", "description": "TikTok, Reels, Shorts captions and a clip"}
  ],
  "skip_if": "(?i)\\b(twitter|x post|bluesky|reddit|forum|steam|itch|store page|tiktok|reels|shorts|youtube|instagram|newsletter|linkedin)\\b"
 },
 {
  "header": "Goal",
  "question": "What should it achieve?",
  "multi": false,
  "options": [
    {"label": "Wishlists / installs", "description": "Drive people to the store page"},
    {"label": "Awareness", "description": "Show what it is, grow followers"},
    {"label": "Feedback", "description": "Get testers and opinions"}
  ],
  "skip_if": "(?i)\\b(wishlist|install|download|sign.?ups?|awareness|followers|feedback|testers|beta)\\b"
 },
 {
  "header": "Tone",
  "question": "Which tone?",
  "multi": false,
  "options": [
    {"label": "Indie dev", "description": "Personal, behind the scenes"},
    {"label": "Hype", "description": "Energetic, big claims backed by visuals"},
    {"label": "Professional", "description": "Clear, product-focused"}
  ],
  "skip_if": "(?i)\\b(indie|personal|hype|energetic|professional|formal|playful|funny)\\b"
 }
]
```

## Checklist
- Nothing is posted, sent, scheduled or submitted; every output is a draft file.
- Positioning names the audience, the pain and the promise in plain words.
- Each proof point maps to a real feature, file or render.
- One clear call to action per draft.
- The hook is in the first line (the part visible before truncation).
- Character limits respected per platform (e.g. X 280 for standard accounts; titles and meta descriptions sized for their surface).
- 2-3 hook variants per channel for the owner to choose or A/B.
- Hashtags few and relevant (0-3 on X, a handful on Instagram/TikTok); none on Reddit.
- Reddit/community drafts follow the community's self-promotion rules and read as a devlog, not an ad.
- Visual sizes exact for each platform (store capsules, thumbnails 1280x720, vertical video 1080x1920).
- Text on images set in the design tool, legible at phone size, contrast at least 4.5:1.
- Alt text written for every image.
- No invented numbers, testimonials, reviews or scarcity.
- Paid, sponsored or affiliate relationships disclosed clearly where they apply.
- Assets credited when licences require it; no third-party trademarks or likenesses without permission.
- Spelling and names checked; links are placeholders the owner fills in.
- Every visual prompt OK'd by the owner before drawing.

## Quality bar
- Great: the one-liner makes a stranger understand what it is and why it matters in under 5 seconds.
- Great hooks lead with a concrete result or a striking visual moment, not with "Introducing".
- Great: each claim is specific and checkable ("retopo to clean quads in one click", not "powerful tools").
- Great: the first 2 seconds of any clip show the most interesting motion.
- Great: copy reads like the owner, not like an ad template; AI tells removed (no "it's not X, it's Y" reveal formulas, no emoji walls).
- Acceptable drafts are on-brand; great drafts are on-brand and could be posted after one read.

## Failure modes
- Drafts sound generic -> rewrite around one concrete proof point and the owner's own words from devlogs or chats.
- Claims the product cannot back -> tie each claim to a feature; delete the rest.
- An agent tried to post -> never; marketing is drafts only; the owner posts himself from the README checklist.
- Over the platform limit -> count characters in the review stage and trim; put the overflow in a thread or the description.
- Reddit post reads like an ad and would be removed -> lead with what was learned or built, share the process, mention the product last, follow the subreddit rules.
- Text in generated images is garbled -> generate the visual without text; add titles in the design tool.
- Stock-looking key art that is not the product -> use real renders and screenshots from the library first.
- Too many hashtags and emojis -> keep 0-3 relevant tags; emojis only where the owner uses them.
- Visuals at the wrong size get cropped -> make each size from the source composition with safe margins (title safe area).
- Missing disclosure on sponsored content -> state the relationship clearly and close to the claim.

## Hand-off
Beyond the constitution's block: the positioning one-liner, a table of channel - draft file - visual file - length
used / limit, the hook variants to choose from, the posting checklist path, open legal or licence questions, and an
explicit line "nothing was posted or sent".

## Tools
- read_file / search_files / library: the real features, renders, clips and devlogs to build claims from.
- memory action=recall query=<brand voice>: earlier tone notes and approved messaging.
- web_search / read_web: platform limits and community rules; a quick look at comparable products.
- write_file / edit_file: drafts under marketing/<slug>/.
- make_image / render_scene / make_video: visuals (owner OKs every prompt); real product renders first.
- design action=create_from_html then export: store capsules, thumbnails and social cards with real text and exact sizes; lint for contrast.
- Specialist library skills in skills/marketing/ (copywriting, social, launch, aso, ad-creative) for channel-specific detail.

## References
- FTC, Disclosures 101 for social media influencers - https://www.ftc.gov/business-guidance/resources/disclosures-101-social-media-influencers
- Updated FTC endorsement guides overview (2023) - https://www.dwt.com/insights/2023/07/ftc-advertising-endorsement-and-testimonial-guides
- WCAG 2.2 contrast minimum - https://w3c-wiki.pages.dev/wcag/2.2/aa/1.4.3
- LOKI marketing skill library - skills/marketing/
