"""Regenerate eval_gold.json from the corpus, so the gold set cannot rot.

Every label is justified by evidence in the corpus, never by what Jev
happens to answer:

  answerable   the cited block is >=250 chars and its heading names the thing
               the question asks about, so one block states the answer
  unanswerable the question's key noun does not occur anywhere in the corpus
  partial      the feature IS described, but the dimension asked about
               (a price, a date, an SLA) occurs nowhere in the corpus

Usage: python3 build_gold.py [--sample N]
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE.parent / "corpus" / "corpus.json"
OUT = HERE / "eval_gold.json"

ANSWERED = "answered in this document"
PARTIAL = "partially answered in this document"
ABSENT = "not in this document"

MIN_CHARS = 250  # below this a block rarely states a full answer

# Headings too generic to make a question from, even with page context.
SKIP = {"next steps", "options", "examples", "example uses", "results",
        "core concepts", "see also", "overview", "notes", "introduction"}

MD_RE = re.compile(r"[*_`]+|\s*\([^)]*optional[^)]*\)\s*", re.I)

# Generic headings that become specific once the page title is supplied.
CONTEXTUAL = {
    "how it works": "How does {page} work?",
    "before you begin": "What do I need before using {page}?",
    "prerequisites": "What are the prerequisites for {page}?",
    "requirements": "What are the requirements for {page}?",
    "calling the agent": "How do I call the {page}?",
    "get access": "How do I get access to {page}?",
    "installation": "How do I install {page}?",
    "configuration": "How do I configure {page}?",
    "usage": "How do I use {page}?",
    "the problem": "What problem does {page} solve?",
}

VERB_RE = re.compile(
    r"^(install|configure|set up|setup|run|add|create|generate|enable|use|connect|"
    r"build|deploy|explore|review|parse|send|choose|handle|register|import|export|"
    r"make|fix|write|update|manage|check|test|trace|debug|ask|analyze|analyse)\b",
    re.I,
)

# "How It Navigates" -> "How does {page} navigate?"
HOW_IT_RE = re.compile(r"^how it (\w+)s?$", re.I)

# Headings containing these are too vague to stand alone as a question.
VAGUE = ("this", " it ", "it works", "matters", "three modes", "runtime shape")

VERB_TO_BASE = {"navigates": "navigate", "responds": "respond", "works": "work",
                "fits": "fit", "scales": "scale", "runs": "run",
                "investigates": "investigate", "handles": "handle"}

# Words ending in "s" that are singular, so "What is ..." stays correct.
SINGULAR_S = {"analysis", "status", "access", "process", "class"}

# Kept capitalised when a heading is lowercased into a how-to question.
KEEP_CASE = {"API", "AST", "CLI", "SDK", "GitHub", "GitLab", "Jira", "Linear",
             "Confluence", "Potpie", "Python", "Docker", "MCP", "JSON", "Q&A"}


def is_plural(phrase):
    last = phrase.split()[-1].strip("&/'-").lower()
    return last.endswith("s") and not last.endswith("ss") and last not in SINGULAR_S


def verb_case(heading):
    """Lowercase Titlecase words but keep acronyms and product names."""
    out = []
    for w in heading.split():
        out.append(w if w in KEEP_CASE or w.isupper() else
                   (w.lower() if w[:1].isupper() and w[1:].islower() else w))
    return " ".join(out)


def defines(block, subject):
    """True if the block actually states what `subject` IS.

    A block sitting under the heading "Null Pointer" is not automatically an
    answer to "What is Null Pointer?" - examples/null-pointer walks through
    tracing one, and never defines the term. Requiring a definitional
    sentence keeps those out of the gold set instead of scoring the model
    against a question the docs never answer.
    """
    text = re.sub(r"[*_`]", "", block["text"][:900]).lower()
    text = re.sub(r"\s+", " ", text)
    subj = re.sub(r"\s+in potpie$", "", subject.strip().lower())
    subj = re.escape(subj)
    return re.search(rf"\b{subj}\b\s+(is|are|refers to|means|provides|lets|gives)\b", text) is not None


def instructs(block):
    """True if the block carries real instructions (steps, code, or a table)."""
    t = block["text"]
    return "```" in t or "<Steps>" in t or "<Step " in t or re.search(r"^\s*\d+\.\s", t, re.M) or "| ---" in t


def load():
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def question_for(block):
    """Return a well-formed question the block answers, or None to skip it.

    Whitelist, not blacklist: a heading only produces a question when it
    matches a pattern known to read naturally. Skipping a usable block costs
    nothing; emitting a broken question pollutes the benchmark.
    """
    path = block.get("heading_path") or []
    if not path:
        return None
    heading = MD_RE.sub(" ", path[-1]).strip().rstrip("?").strip()
    heading = re.sub(r"\s{2,}", " ", heading)
    page = MD_RE.sub(" ", block["page_title"]).strip()
    low = heading.lower()

    if low in SKIP or len(heading) < 3 or page.lower() in SKIP:
        return None

    def tail(h):
        # Don't append "in Potpie" when the heading already names it.
        return "" if "potpie" in h.lower() else " in Potpie"

    # Heading names the page: definition, unless it reads as a task.
    if low == page.lower():
        if VERB_RE.match(heading) and len(heading.split()) > 1:
            return f"How do I {verb_case(heading)}{tail(heading)}?"
        return f"What {'are' if is_plural(page) else 'is'} {page}?"

    if low in CONTEXTUAL:
        return CONTEXTUAL[low].format(page=page)

    m = HOW_IT_RE.match(heading)
    if m:
        raw = m.group(1).lower()
        return f"How does {page} {VERB_TO_BASE.get(raw, raw)}?"

    if VERB_RE.match(heading) and len(heading.split()) > 1:
        return f"How do I {verb_case(heading)}{tail(heading)}?"

    # Anything still opening with a question word is a statement-shaped
    # heading ("What The Context Engine Does") - it will not read as English.
    if low.startswith(("what ", "how ", "why ", "when ", "where ", "which ")):
        return None

    if any(v in f" {low} " for v in VAGUE):
        return None

    # Skip headings that open with a preposition/conjunction ("With intent").
    if low.split()[0] in {"with", "from", "to", "for", "in", "on", "by", "and", "or", "as", "at"}:
        return None

    # Clean noun phrase: at least two words, no stray punctuation.
    if len(heading.split()) < 2 or not re.match(r"^[A-Za-z][\w &/'-]*$", heading):
        return None
    return f"What {'are' if is_plural(heading) else 'is'} {heading}{tail(heading)}?"


def build_answerables(blocks):
    out, seen = [], set()
    for b in blocks:
        if len(b["text"]) < MIN_CHARS:
            continue
        q = question_for(b)
        if not q or q.lower() in seen:
            continue
        # Two different claims, two different strengths of evidence:
        #  * expected_block is always safe - the heading names the subject, so
        #    this block is the right one to retrieve.
        #  * expected_verdict "answered" is only safe when the block visibly
        #    states the answer (a definition, or real steps/code). Whether one
        #    block "fully" answers is the judgement under test, so where the
        #    evidence is thin the row is graded on rank only.
        graded = False
        if q.startswith(("What is ", "What are ")):
            subject = q.split(" ", 2)[2].rstrip("?")
            graded = defines(b, subject)
        elif q.startswith(("How do I ", "How does ")):
            graded = instructs(b)
        seen.add(q.lower())
        out.append({"query": q, "expected_verdict": ANSWERED if graded else None,
                    "expected_block": b["block_id"], "kind": "answerable",
                    "page": b["page_url"].rsplit("/", 1)[-1].removesuffix(".md")})
    return out


# Off-topic questions. Each is kept only if its key noun is absent from the
# corpus, so "not in this document" is verified, not assumed.
UNANSWERABLE = [
    ("What is the company holiday policy?", "holiday"),
    ("How do I reset my refrigerator's water filter?", "refrigerator"),
    ("Who won the 2024 World Series?", "world series"),
    ("How do I bake sourdough bread from scratch?", "sourdough"),
    ("What is the capital gains tax rate for 2025?", "capital gains"),
    ("What are the parking validation rules downtown?", "parking"),
    ("How long should I marinate chicken?", "marinate"),
    ("What is the tallest mountain in Africa?", "mountain"),
    ("How do I treat a second-degree burn?", "burn"),
    ("What is the offside rule in football?", "offside"),
    ("How much does a flight to Tokyo cost?", "tokyo"),
    ("What vaccinations do I need for Brazil?", "vaccination"),
    ("How do I change a flat tyre?", "tyre"),
    ("What is the boiling point of ethanol?", "ethanol"),
    ("Who painted the Mona Lisa?", "mona lisa"),
    ("How do I file for divorce?", "divorce"),
    ("What is the mortgage rate at my bank?", "mortgage"),
    ("How do I train for a marathon?", "marathon"),
    ("What is the population of Denmark?", "denmark"),
    ("How do I remove a wine stain from carpet?", "wine"),
    ("When does daylight saving time end?", "daylight saving"),
    ("What is the warranty on my dishwasher?", "dishwasher"),
    ("How do I grow tomatoes indoors?", "tomato"),
    ("What is the minimum wage in Ohio?", "minimum wage"),
    ("How do I tune a guitar?", "guitar"),
    ("What are the symptoms of the flu?", "flu"),
    ("How do I apply for a passport?", "passport"),
    ("What is the speed limit on a motorway?", "speed limit"),
    ("How do I knit a scarf?", "knit"),
    ("What is the exchange rate for yen?", "yen"),
    ("How do I adopt a rescue dog?", "rescue dog"),
    ("What is the best fertiliser for roses?", "fertilis"),
    ("How do I make cold brew coffee?", "cold brew"),
    ("What time does the museum open?", "museum"),
    ("How do I replace a bicycle chain?", "bicycle"),
    ("What is the recipe for carbonara?", "carbonara"),
    ("How do I get a fishing licence?", "fishing"),
    ("What is the average rainfall in Seattle?", "rainfall"),
    ("How do I fold a fitted sheet?", "fitted sheet"),
    ("What is the penalty for late tax filing?", "tax filing"),
    ("How do I teach a toddler to swim?", "toddler"),
    ("What is the calorie count of an avocado?", "avocado"),
    ("How do I unclog a kitchen sink?", "unclog"),
    ("What is the history of the Silk Road?", "silk road"),
    ("How do I start a compost heap?", "compost"),
    ("What is the going rate for a plumber?", "plumber"),
    ("How do I read sheet music?", "sheet music"),
    ("What are the rules of cricket?", "cricket"),
    ("How do I whiten my teeth?", "teeth"),
    ("What is the lifespan of a tortoise?", "tortoise"),
]

# Hand-curated answerables: questions worth grading that the heading templates
# do not produce. Each cites a block that visibly states the answer.
HAND_ANSWERABLE = [
    {"query": "Which self-hosted Git providers does Potpie support?",
     "block": "self-hosting-setup-H006",
     "note": "Block enumerates CODE_PROVIDER accepted values: github, gitbucket."},
    {"query": "What Python version does the Potpie CLI require?",
     "block": "cli-installation-H002",
     "note": "Prerequisites table states Python 3.12 or newer."},
    {"query": "Can I run the Potpie CLI on Windows?",
     "block": "cli-installation-H002",
     "note": "Prerequisites table states macOS, Linux, or WSL2 on Windows."},
]


# Hand-curated partials. Each was read and justified individually; the
# `requires` terms are re-checked against the corpus at build time so a doc
# change that invalidates the label drops the row instead of silently rotting.
# Deliberately small: a partial is "topic present, answer absent", and that
# judgement cannot be made by rule without guessing.
PARTIALS = [
    {"query": "How much does Forge cost?",
     "requires": ["forge", "enterprise"], "forbids": ["pricing"],
     "note": "Docs say Forge is part of the enterprise offering and link 'Reach out'; no price is stated."},
    {"query": "Does Potpie support GitLab repositories?",
     "requires": ["gitlab"], "forbids": [],
     "note": "GitLab appears only as a PR target; no GitLab auth or setup path is documented."},
    {"query": "What are the rate limits on the Potpie API?",
     "requires": ["rate limiting", "api"], "forbids": ["requests per minute"],
     "note": "'Rate limiting' appears only as an example of analysing YOUR routes; no API limit figures exist."},
    {"query": "What observability backends can I use with Potpie?",
     "requires": ["logfire", "observability"], "forbids": [],
     "note": "Logfire is documented as optional; no other backend is confirmed or ruled out."},
]


def corpus_text(data):
    return "\n".join(b["text"] for b in data["blocks"]).lower()


def build_unanswerables(joined):
    return [{"query": q, "expected_verdict": ABSENT, "expected_block": None,
             "kind": "unanswerable", "page": None}
            for q, noun in UNANSWERABLE if noun.lower() not in joined]


def build_partials(joined):
    """Keep a hand-curated partial only while its corpus evidence still holds."""
    out = []
    for spec in PARTIALS:
        if any(t.lower() not in joined for t in spec["requires"]):
            continue
        if any(t.lower() in joined for t in spec["forbids"]):
            continue
        out.append({"query": spec["query"], "expected_verdict": PARTIAL,
                    "expected_block": None, "kind": "partial", "page": None,
                    "note": spec["note"]})
    return out


def main():
    data = load()
    joined = corpus_text(data)
    ans = build_answerables(data["blocks"])
    by_id = {b["block_id"]: b for b in data["blocks"]}
    have = {q["query"].lower() for q in ans}
    for spec in HAND_ANSWERABLE:  # drop silently if the cited block is gone
        if spec["block"] in by_id and spec["query"].lower() not in have:
            ans.append({"query": spec["query"], "expected_verdict": ANSWERED,
                        "expected_block": spec["block"], "kind": "answerable",
                        "page": by_id[spec["block"]]["page_url"].rsplit("/", 1)[-1].removesuffix(".md"),
                        "note": spec["note"]})
    una = build_unanswerables(joined)
    par = build_partials(joined)

    if "--sample" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sample") + 1])
        for q in ans[:n]:
            print(f"  [{q['expected_block']}] {q['query']}")
        print(f"\nanswerable {len(ans)} | unanswerable {len(una)} | partial {len(par)}")
        return

    graded_n = sum(1 for q in ans if q["expected_verdict"])
    queries = []
    for i, q in enumerate(ans, 1):
        queries.append({"id": f"A{i:03d}", **q})
    for i, q in enumerate(una, 1):
        queries.append({"id": f"U{i:03d}", **q})
    for i, q in enumerate(par, 1):
        queries.append({"id": f"P{i:03d}", **q})

    out = {
        "description": (
            f"Gold set generated by build_gold.py from the Potpie corpus "
            f"({len(data['pages'])} pages / {len(data['blocks'])} blocks). "
            f"{len(queries)} queries: {len(ans)} answerable, {len(una)} unanswerable, "
            f"{len(par)} partial. Of the answerables, {graded_n} carry a verdict label "
            f"and the rest are graded on retrieval rank only - claiming a block "
            f"'fully answers' a question is the judgement under test, so it is only "
            f"asserted where the block visibly defines the subject or carries real "
            f"steps/code. Labels come from corpus evidence, not model output: "
            f"answerables cite a >={MIN_CHARS}-char block whose heading names the "
            f"subject; unanswerables' key noun is absent from the corpus; "
            f"partials are hand-curated and re-checked against the corpus at build "
            f"time (they cannot be derived by rule without guessing). Questions are "
            f"template-derived, so phrasing is uniform rather than natural - a "
            f"sample was read by hand, not every row."
        ),
        "queries": queries,
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(queries)} queries -> {OUT.name}")
    print(f"  answerable {len(ans)} ({graded_n} verdict-graded, {len(ans)-graded_n} rank-only)"
          f" | unanswerable {len(una)} | partial {len(par)}")


if __name__ == "__main__":
    main()
