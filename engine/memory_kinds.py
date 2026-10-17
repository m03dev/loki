"""What kind of memory a sentence is, which slot it fills, and whether it is worth keeping.

Rules only (no model), so they run on every machine, offline, in microseconds:

  kind_of(text)        profile | preference | person | project | decision | fact
  slot(text, kind)     (subject, verb, value) when the text sets an attribute ("the owner's editor is
                       Zed"); two memories with the same subject+verb and a different value contradict,
                       and the newer one supersedes the older (memory_core keeps the history)
  contradicts(a, b)    that test
  is_secret(text)      a key, token, password or card number is never remembered (auto-learning drops
                       the sentence; an explicit learn stores it with the secret replaced)
  is_junk(text)        too short, a question, small talk, or only about right now
"""
from __future__ import annotations

import re

PEOPLE = (r"wife|husband|partner|girlfriend|boyfriend|fianc[eé]e?|brother|sister|mother|mom|mum|father|dad|"
          r"son|daughter|friend|best friend|boss|manager|colleague|coworker|co-worker|client|cofounder|"
          r"co-founder|teammate|uncle|aunt|cousin|grandma|grandpa|grandmother|grandfather|kid|kids|child|"
          r"children|roommate|neighbo(u)?r|mentor|accountant|lawyer|doctor|designer|artist")
_PERSON = re.compile(r"(?i:\b(my|the owner'?s|his|her|our)\s+(%s)\b)|\b[A-Z][a-z]+\s+(?i:(is|was)\s+(my|the owner'?s|our)\s+(%s))\b"
                     % (PEOPLE, PEOPLE))
_PREF = re.compile(r"\b(prefers?|preferred|likes?|loves?|hates?|dislikes?|enjoys?|favou?rite|rather|wants? .{0,40}"
                   r"(always|never)|always|never|can'?t stand|is into|fan of)\b", re.I)
_DECISION = re.compile(r"\b(decided|decision|chose|chosen|choose to|agreed|going with|go with|went with|settled on|"
                       r"picked|opted|we will use|we'll use|from now on|no longer|instead of)\b", re.I)
_PROJECT = re.compile(r"\b(project|repo|repository|codebase|app|game|website|site|product|startup|working on|"
                      r"building|build of|launch|release|roadmap|milestone|deadline|client work)\b", re.I)
_PROFILE = re.compile(r"\b(name is|called|lives? in|based in|from [A-Z]|time ?zone|works? (at|as|for)|job|"
                      r"birthday|born|years old|email|phone number|speaks?|native language|studies|studied|"
                      r"owner'?s (pc|mac|machine|computer|laptop|phone|gpu|setup)|my (pc|mac|machine|computer|"
                      r"laptop|phone|gpu|setup)|has an? (rtx|mac|pc|iphone|android))\b", re.I)

_SECRET = re.compile(
    r"(sk|gsk|xai|pk|rk|AIza|ghp|gho|github_pat|xox[abp]|hf)[-_A-Za-z0-9]{12,}"
    r"|Bearer\s+[-._A-Za-z0-9]{12,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(password|passwd|passcode|pin|api[_ -]?key|token|secret|private key|seed phrase|recovery phrase)\b\s*(is|=|:)\s*\S+"
    r"|\b(?:\d[ -]?){13,19}\b"                              # card-like numbers
    r"|\b[A-Za-z0-9+/]{40,}={0,2}\b",                       # long opaque blobs
    re.I)

_JUNK = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|cool|nice|great|lol|yes|no|sure)\b[.! ]*$", re.I)
_NOW = re.compile(r"\b(right now|at the moment|today|tonight|this morning|this afternoon|currently busy|"
                  r"for now|this time|just now|in a minute)\b", re.I)

# verbs that hold one value at a time ("lives in Lisbon" then "lives in Porto" -> the newer wins)
SINGLE = ("is called", "is named", "lives in", "is based in", "works at", "works as", "is set to", "runs on",
          "costs", "equals")
# verbs that hold many values: they contradict only when the values talk about the same thing
# ("prefers dark mode" / "prefers light mode", "needs Ollama 0.40.6" / "needs Ollama 0.41")
MULTI = ("is", "are", "was", "prefers", "prefer", "likes", "like", "loves", "love", "wants", "want", "has", "have",
         "hates", "hate", "uses", "use", "needs", "need", "runs")
LIKING = ("prefers", "likes", "loves", "hates")       # one opinion per thing: "likes X" then "hates X"
_VERBS = sorted(SINGLE + MULTI, key=len, reverse=True)
_SLOT = re.compile(r"^(?P<subj>.{2,80}?)\s+(?:(?P<neg>no longer|doesn'?t|does not|don'?t|do not|now|still|"
                   r"also|really|always|never)\s+)?(?P<verb>%s)\s+(?P<val>.+?)[.!]?$"
                   % "|".join(re.escape(v) for v in _VERBS), re.I)
_ARTICLES = {"the", "a", "an", "his", "her", "my", "our", "their", "its"}


def kind_of(text: str, tier: str = "semantic", source: str = "") -> str:
    text = str(text or "")
    if tier == "episodic":
        if source in ("reflexion", "lesson", "evolve") or re.search(r"\b(lesson|next time|avoid|don'?t|"
                                                                     r"never again|should have|remember to)\b", text, re.I):
            return "lesson"
        return "episode"
    if tier == "procedural":
        return "skill"
    if _PERSON.search(text):
        return "person"
    if _DECISION.search(text):
        return "decision"
    if _PREF.search(text):
        return "preference"
    if _PROFILE.search(text):
        return "profile"
    if _PROJECT.search(text):
        return "project"
    if re.match(r"\s*(the owner\b|my\b|i\b)", text, re.I):
        return "profile"          # anything else the owner is, has or does
    return "fact"


def _norm_subject(subj: str) -> str:
    out = []
    for w in re.findall(r"[a-z0-9']+", subj.lower()):
        w = w.replace("'s", "").replace("'", "")
        if w in _ARTICLES:
            continue
        if w in ("i", "me", "owner", "user"):
            w = "owner"
        out.append(w)
    return " ".join(out)


def slot(text: str) -> tuple:
    """(subject, verb, value, negated, attribute) for a sentence that sets something, else ()."""
    text = " ".join(str(text or "").split())
    if len(text) > 240:
        return ()
    m = _SLOT.match(text)
    if not m:
        return ()
    subj = _norm_subject(m.group("subj"))
    if not subj or len(subj.split()) > 6:
        return ()
    verb = m.group("verb").lower()
    verb = {"use": "uses", "need": "needs", "prefer": "prefers", "like": "likes", "love": "loves",
            "want": "wants", "have": "has", "hate": "hates", "are": "is", "was": "is"}.get(verb, verb)
    neg = (m.group("neg") or "").lower()
    negated = neg in ("no longer", "doesn't", "doesnt", "does not", "don't", "dont", "do not")
    raw = m.group("subj").lower()
    attribute = bool(re.search(r"'s\b|\bof\b|^my\b|^our\b", raw))
    return subj, verb, m.group("val").strip().lower(), negated, attribute


def _value_words(value: str) -> set:
    import memory_search  # pylint: disable=import-outside-toplevel
    return set(memory_search.words(value))


def contradicts(new: str, old: str) -> bool:
    """True when `new` sets the same thing as `old` to something else (so it supersedes it)."""
    a, b = slot(new), slot(old)
    if not a or not b or a[0] != b[0]:
        return False
    if a[1] != b[1] and not (a[1] in LIKING and b[1] in LIKING):
        return False                      # "is working on X" and "uses X" are both true
    if a[2] == b[2] and a[3] == b[3]:
        return False                      # the same statement: a duplicate, not a contradiction
    va, vb = _value_words(a[2]), _value_words(b[2])
    if a[3] != b[3]:
        return bool(va & vb)              # "likes X" vs "no longer likes X"
    if a[1] == b[1] and a[1] in SINGLE:
        return True                       # "lives in Lisbon" vs "lives in Porto"
    if a[1] == b[1] == "is" and (a[4] or b[4]):
        return True                       # an attribute: "the owner's editor is Zed" vs "... is VS Code"
    return bool(va & vb) and va != vb


def is_secret(text: str) -> bool:
    return bool(_SECRET.search(str(text or "")))


def is_junk(text: str) -> bool:
    text = " ".join(str(text or "").split())
    if len(text) < 8 or len(text) > 300:
        return True
    if text.endswith("?") or _JUNK.match(text):
        return True
    return bool(_NOW.search(text))
