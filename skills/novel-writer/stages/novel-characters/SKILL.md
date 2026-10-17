---
name: novel-characters
description: Characters and organizations stage of the novel pipeline - translated from MuMuAINovel (GPL-3.0, see skills/novel-writer/LICENSE-MuMuAINovel-GPL-3.0.txt).
---

## CHARACTERS

You are a professional character designer who creates rounded characters for {genre} novels.

Task: create exactly {count} characters and organizations - at least 1 protagonist, several
supporting characters, optionally an antagonist, optionally 1-2 high-influence organizations
(power level 70-95).

World: time {time_period}; location {location}; atmosphere {atmosphere}; rules {rules}; theme
{theme}; genre {genre}. Special requirements: {requirements}.

Output a JSON array (`novel/characters.json`), each object either:

Character: name, age, gender, is_organization=false, role_type (protagonist / supporting /
antagonist), personality (100-200 words: core traits, strengths and flaws, habits), background
(100-200 words: family, upbringing, turning points), appearance (50-100 words: height, build,
face, style of dress), traits (3 strengths), relationships_array [{target_character_name,
relationship_type, intimacy_level, description}], organization_memberships [{organization_name,
position, rank, loyalty}].

Organization: name, is_organization=true, role_type=supporting, personality (100-200 words: how it
operates, core beliefs, style), background (100-200 words: founding, history, key events),
appearance (50-100 words: headquarters, landmark buildings), organization_type,
organization_purpose, organization_members, power_level, location, motto, color.

Relationship types: family (father, mother, brother, sister, child, spouse, lover), social (master,
apprentice, friend, classmate, colleague, neighbour, confidant), work (boss, subordinate, partner),
hostile (enemy, nemesis, rival, sworn enemy).
Ranges: intimacy_level -100..100 (negative = hostile); loyalty 0..100; rank 0..10; power_level 70..95.

Must: exactly {count} objects; consistent with the world; depth in personality and background; a
believable web of relationships; organizations are forces that drive the plot. Relationships may
only reference characters created earlier in this same batch, and memberships only organizations
in this batch; the first character's relationships_array is empty; never reference anyone who
does not exist. Then write `novel/02-characters.md` from the JSON for the author.
