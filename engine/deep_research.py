"""Deep research: a cited report from the web, the STORM way, sized for a small local model.

The pipeline and its prompts are STORM's (stanford-oval/storm, knowledge_storm/storm_wiki/modules:
persona_generator.py GenPersona + the default "Basic fact writer", knowledge_curation.py
AskQuestionWithPersona / QuestionToQuery / AnswerQuestion, outline_generation.py WritePageOutline,
article_generation.py WriteSection with inline [n] citations), MIT - see engine/licenses/STORM-MIT.txt.
Paper: "Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models"
(Shao et al., NAACL 2024).

  1. perspectives - a few "editors", each with a different focus on the topic (+ a basic fact writer)
  2. questions    - each editor asks the questions their focus needs
  3. queries      - each question becomes 1-2 search queries; results are read (read_web) and the
                    question is answered ONLY from what was read, citing sources as [n]
  4. outline      - the report's sections, from the topic and the answers
  5. sections     - each section written from the gathered answers, keeping the [n] citations
  6. references   - [n] title - url, numbered once for the whole report

STORM runs a multi-turn simulated conversation per editor through DSPy; LOKI asks each editor for
its questions in one call and caps everything (editors, questions, sources, characters), because
a 7-9B model on 8 GB has a small context and every call costs seconds. Search needs no key:
DuckDuckGo's HTML page, or a SearXNG instance when LOKI_SEARXNG_URL is set.
The model, search and page reader are injected; tests run on fakes with no network.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEPTHS = {1: (2, 2, 6), 2: (3, 3, 10), 3: (4, 3, 14)}   # editors, questions each, max sources
READ_CHARS = 3500
ANSWER_INFO_CHARS = 7000
SEARCH_TIMEOUT = 20

GEN_PERSONA = (
    "You need to select a group of editors who will work together to create a comprehensive report on the "
    "topic. Each of them represents a different perspective, role, or affiliation related to this topic. "
    "For each editor, add a description of what they will focus on.\n"
    "Give your answer in the following format: 1. short summary of editor 1: description\n"
    "2. short summary of editor 2: description\n...\n\nTopic of interest: {topic}\nNumber of editors: {n}\n")
BASIC_PERSONA = ("Basic fact writer: Basic fact writer focusing on broadly covering the basic facts about the "
                 "topic.")
ASK_QUESTIONS = (
    "You are an experienced writer and want to research a specific topic. Besides your identity as a writer, "
    "you have a specific focus when researching the topic. Ask good questions to get more useful information. "
    "Do not ask what is already asked. Your questions should be related to the topic you want to write.\n"
    "Write {n} questions, one per line, each starting with '- '.\n\n"
    "Topic you want to write: {topic}\nYour persona besides being a writer: {persona}\n")
QUESTION_TO_QUERY = (
    "You want to answer the question using a web search. What do you type in the search box?\n"
    "Write the queries you will use in the following format:\n- query 1\n- query 2\n(at most 2 queries)\n\n"
    "Topic you are discussing about: {topic}\nQuestion you want to answer: {question}\n")
ANSWER_QUESTION = (
    "You are an expert who can use information effectively. You have gathered the related information and "
    "will now use the information to form a response. Make your response as informative as possible, "
    "ensuring that every sentence is supported by the gathered information, and cite the source of each "
    "sentence in the form [n] using the source numbers given. If the gathered information is not directly "
    "related to the topic or question, provide the most relevant answer based on the available information. "
    "If no appropriate answer can be formulated, respond with \"I cannot answer this question based on the "
    "available information\" and explain any limitations or gaps.\n\n"
    "Topic you are discussing about: {topic}\nQuestion:\n{question}\nGathered information:\n{info}\n\n"
    "Now give your response. (Try to use as many different sources as possible and do not hallucinate.)\n")
WRITE_OUTLINE = (
    "Write an outline for a report on the topic, using what the research found.\n"
    "Here is the format of your writing:\n1. Use \"# Title\" to indicate section title, \"## Title\" to indicate "
    "subsection title.\n2. Do not include other information.\n3. Do not include the topic name itself in the "
    "outline.\n4. At most {n} sections.\n\nThe topic you want to write: {topic}\nWhat the research found:\n{notes}\n"
    "\nWrite the outline:\n")
WRITE_SECTION = (
    "Write a report section based on the collected information.\n"
    "Here is the format of your writing:\n1. Use \"#\" Title\" to indicate section title, \"##\" Title\" to "
    "indicate subsection title.\n2. Use [1], [2], ..., [n] in line (for example, \"The capital of the United "
    "States is Washington, D.C.[1][3].\"). You DO NOT need to include a References or Sources section.\n"
    "Only use the source numbers that appear in the collected information.\n\n"
    "The collected information:\n{info}\n\nThe topic of the report: {topic}\nThe section you need to write: "
    "{section}\n\nWrite the section with proper inline citations (Start your writing with # section title. "
    "Don't include the report title or try to write other sections):\n")


# --------------------------------------------------------------------------- search (no key)

class _DDGParser(HTMLParser):
    """Results from html.duckduckgo.com: <a class="result__a" href=...> and <a class="result__snippet">."""

    def __init__(self):
        super().__init__()
        self.results, self._field = [], ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "a" and "result__a" in cls:
            self.results.append({"title": "", "url": _ddg_target(a.get("href", "")), "snippet": ""})
            self._field = "title"
        elif "result__snippet" in cls and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "td", "div"):
            self._field = ""

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _ddg_target(href: str) -> str:
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        return target or href
    return href


def parse_ddg(page: str, limit: int = 8) -> list:
    parser = _DDGParser()
    parser.feed(page or "")
    out, seen = [], set()
    for r in parser.results:
        url = r["url"].strip()
        if not url.startswith("http") or url in seen or "duckduckgo.com/y.js" in url:
            continue
        seen.add(url)
        out.append({"title": " ".join(r["title"].split()), "url": url, "snippet": " ".join(r["snippet"].split())})
        if len(out) >= limit:
            break
    return out


def parse_searxng(body: str, limit: int = 8) -> list:
    try:
        data = json.loads(body or "{}")
    except ValueError:
        return []
    return [{"title": str(r.get("title", "")), "url": str(r.get("url", "")), "snippet": str(r.get("content", ""))}
            for r in (data.get("results") or [])[:limit] if str(r.get("url", "")).startswith("http")]


def search(query: str, limit: int = 8, opener=None, env=None) -> list:
    """[{title, url, snippet}] for a query. SearXNG if LOKI_SEARXNG_URL is set, else DuckDuckGo HTML."""
    env = os.environ if env is None else env
    opener = opener or urllib.request.urlopen
    query = " ".join(str(query or "").split())[:300]
    if not query:
        return []
    searx = str(env.get("LOKI_SEARXNG_URL", "") or "").rstrip("/")
    headers = {"User-Agent": "Mozilla/5.0 (LOKI research) AppleWebKit/537.36 Chrome/149.0 Safari/537.36",
               "Accept-Language": "en-US,en;q=0.8"}
    if searx:
        url = searx + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
        with opener(urllib.request.Request(url, headers=headers), timeout=SEARCH_TIMEOUT) as resp:
            return parse_searxng(resp.read().decode("utf-8", "replace"), limit)
    req = urllib.request.Request("https://html.duckduckgo.com/html/",
                                 data=urllib.parse.urlencode({"q": query}).encode(), headers=headers)
    with opener(req, timeout=SEARCH_TIMEOUT) as resp:
        return parse_ddg(resp.read().decode("utf-8", "replace"), limit)


def format_results(results: list) -> str:
    if not results:
        return "(no results)"
    return "\n".join("%d. %s\n   %s\n   %s" % (i, r["title"] or r["url"], r["url"], r["snippet"][:240])
                     for i, r in enumerate(results, 1))


# --------------------------------------------------------------------------- parsing model text

def parse_personas(text: str, n: int) -> list:
    personas = []
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*])\s*(.+)$", line)
        if m and len(m.group(1).strip()) > 3:
            personas.append(m.group(1).strip().strip("*"))
    return [BASIC_PERSONA] + personas[:max(0, n - 1)]


def parse_list(text: str, limit: int) -> list:
    items = []
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+[.)])\s*(.+)$", line)
        if m:
            item = m.group(1).strip().strip('"').strip()
            if item and item.lower() not in {i.lower() for i in items}:
                items.append(item)
    return items[:limit]


def parse_outline(text: str, limit: int) -> list:
    sections = []
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*#\s+(.+)$", line)
        if m:
            title = m.group(1).strip()
            if title.lower() not in ("references", "sources", "see also") and title not in sections:
                sections.append(title)
    return sections[:limit]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:60] or "research"


# --------------------------------------------------------------------------- the pipeline

class Sources:
    """One numbering for every source the report cites."""

    def __init__(self, limit: int):
        self.limit, self.items, self.by_url = limit, [], {}

    def add(self, url: str, title: str, text: str):
        if url in self.by_url:
            return self.by_url[url]
        if len(self.items) >= self.limit:
            return None
        self.items.append({"n": len(self.items) + 1, "url": url, "title": title or url, "text": text})
        self.by_url[url] = len(self.items)
        return self.by_url[url]

    def references(self) -> str:
        return "\n".join("[%d] %s - %s" % (s["n"], s["title"], s["url"]) for s in self.items)


async def run(topic: str, ask, search_fn, read_fn, depth: int = 1, progress=None) -> dict:
    """The whole report. ask(prompt)->str, search_fn(query)->[{title,url,snippet}], read_fn(url)->str
    (all async). Returns {"report": markdown, "sources": [...], "questions": [...]}."""
    editors, per_editor, max_sources = DEPTHS.get(int(depth or 1), DEPTHS[1])
    say = progress or (lambda _text: None)
    topic = " ".join(str(topic).split())
    sources = Sources(max_sources)
    say("finding perspectives")
    personas = parse_personas(await ask(GEN_PERSONA.format(topic=topic, n=editors - 1)), editors)
    questions = []
    for persona in personas:
        for q in parse_list(await ask(ASK_QUESTIONS.format(n=per_editor, topic=topic, persona=persona)), per_editor):
            if q.lower() not in {x.lower() for x in questions}:
                questions.append(q)
    if not questions:
        questions = [topic]
    notes = []
    for question in questions:
        say("researching: %s" % question[:80])
        queries = parse_list(await ask(QUESTION_TO_QUERY.format(topic=topic, question=question)), 2) or [question]
        info = []
        for query in queries:
            try:
                results = await search_fn(query)
            except Exception as exc:  # noqa: BLE001 - one failed search is not the end of the report
                say("search failed: %s" % exc)
                results = []
            for r in results[:3]:
                n = sources.by_url.get(r["url"])
                if n is None:
                    try:
                        text = await read_fn(r["url"])
                    except Exception:  # noqa: BLE001
                        text = ""
                    if not text or str(text).startswith("error"):
                        text = r.get("snippet", "")
                    if not text:
                        continue
                    n = sources.add(r["url"], r.get("title", ""), str(text)[:READ_CHARS])
                    if n is None:
                        continue
                info.append("[%d] %s\n%s" % (n, sources.items[n - 1]["title"], sources.items[n - 1]["text"]))
        if not info:
            continue
        answer = await ask(ANSWER_QUESTION.format(topic=topic, question=question,
                                                  info="\n\n".join(info)[:ANSWER_INFO_CHARS]))
        notes.append({"question": question, "answer": " ".join(str(answer).split())})
    if not notes:
        return {"report": "", "sources": sources.items, "questions": questions,
                "error": "no sources could be found or read for this topic"}
    note_text = "\n\n".join("Q: %s\nA: %s" % (n["question"], n["answer"]) for n in notes)
    say("writing the outline")
    sections = parse_outline(await ask(WRITE_OUTLINE.format(n=editors + 2, topic=topic,
                                                             notes=note_text[:ANSWER_INFO_CHARS])), editors + 2)
    if not sections:
        sections = ["Overview", "Details", "Open questions"]
    body = []
    for section in sections:
        say("writing: %s" % section)
        text = str(await ask(WRITE_SECTION.format(info=note_text[:ANSWER_INFO_CHARS], topic=topic,
                                                  section=section))).strip()
        if not text.startswith("#"):
            text = "## %s\n\n%s" % (section, text)
        else:
            text = "#" + text if not text.startswith("##") else text
        body.append(text)
    used = set(int(x) for x in re.findall(r"\[(\d+)\]", "\n".join(body)))
    known = {s["n"] for s in sources.items}
    report = "# %s\n\n%s\n\n## References\n\n%s\n" % (topic, "\n\n".join(body), sources.references())
    return {"report": report, "sources": sources.items, "questions": questions,
            "cited": sorted(used & known), "unknown_citations": sorted(used - known)}
