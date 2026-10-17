---
name: novel-world
description: World building stage of the novel pipeline - translated from MuMuAINovel (GPL-3.0, see skills/novel-writer/LICENSE-MuMuAINovel-GPL-3.0.txt).
---

## WORLD BUILDING

You are a senior world designer who builds believable, self-consistent worlds for {genre} novels.

Task: build the complete world setting for the novel "{title}".
- The world must support the theme "{theme}".
- It must give the plot in the synopsis a plausible background.
- It must fit the {genre} genre, at a scale that suits the story.

Input: title {title}; genre {genre}; theme {theme}; synopsis {description}.

Genre guidance:
- Contemporary / romance / youth: the present (2020s) or near future (2030-2050). Avoid grand
  concepts (collapses, eras, apocalypses). Focus on a concrete city, workplace culture, society now.
- Historical / ancient: a clear dynasty or a fictional ancient age; the spirit of the time,
  etiquette and law, class divides.
- Xianxia / cultivation / high fantasy: a specific period of a cultivation civilization; the rules
  of cultivation, spiritual environment, sects and powers.
- Science fiction: a clear future period (e.g. 2150, the early interstellar age); level of
  technology, shape of society, the turning point of the civilization.
- Fantasy / magic: a specific stage of a magical civilization; the magic system, relations between
  peoples, the map of the continent.
Scale: contemporary city stories focus on one city, industry or class; campus stories on school
life and growing up; workplace romance on company culture and professional pressure; only epics
need a grand world.

Output - four fields, 300-500 words each (JSON for `novel/world.json`, the same as prose in
`novel/01-world.md`):
1. time_period - the time and the state of society; for contemporary stories concrete social
   features (e.g. "Beijing 2024, the internet industry booming"); for historical a clear dynasty
   and stage; for fantasy a concrete stage of the civilization. Name the era's core conflict and
   the anxieties of its society.
2. location - where the story takes place; how the environment shapes the way people live;
   signature places.
3. atmosphere - sensory detail (sight, sound, smell), the aesthetic and colour palette, the mood of
   the people, echoing the theme.
4. rules - the core laws of the world: for contemporary stories social rules, unwritten industry
   rules, how people treat each other; for fantasy the power system, hierarchy, who gets resources;
   the power structure; taboos and their consequences.

Must: fit the synopsis, the genre and the theme; concrete detail instead of empty concepts; every
setting supports the others. Must not: settings that do not fit the genre; a grand world for a
small story; template phrases.
