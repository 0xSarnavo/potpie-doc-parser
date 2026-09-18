"""Jev-only search backend: stdlib BM25 shortlist + one system_one call.

No LLM, no embeddings, no text generation. Jev ranks candidate blocks
(Choice `where`), judges answerability (Noul `exists` + Noul `fully`),
and picks the best page (Choice `router`) in a SINGLE system_one request. Answer text
is always copied verbatim from corpus blocks — never generated.
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

from typesafe_sdk import Choice, Noul, TypeSafeClient

# Verdict thresholds (tuned by search/eval.py --live; do not hardcode inline).
# Retuned for the Potpie corpus: ABSENT moved 0.35 -> 0.30 because two genuine
# partials scored exists 0.31/0.34 and flipped verdict between runs. The 6
# unanswerable golds score 0.02, so abstention keeps a 0.28 margin.
# FOUND stays at 0.7 deliberately: a sweep showed 0.50 scores one query higher
# on a single run, but a "half-states it" bar is exactly the false confidence
# this tool exists to avoid.
FOUND = 0.7
ABSENT = 0.30

MODEL = "jev-latest"
SHORTLIST = 30  # BM25 candidates sent to Jev (Choice caps at 255 labels)

# Outlier guard (01-05 sweep 2): one unanswerable query's 30-block state
# (~121k chars of code-dense blocks) came back 400 max_tokens_exceeded
# twice while a 122k-char prose state passed — the server counts tokens,
# not chars, so code-dense states can overflow. Trim longest tails first
# (heads carry the markdown content; tails are SDK-boilerplate blobs) only
# when over budget; states under budget are byte-identical to before.
STATE_CHAR_BUDGET = 90_000

VERDICT_ANSWERED = "answered in this document"
VERDICT_PARTIAL = "partially answered in this document"
VERDICT_ABSENT = "not in this document"

CORPUS_PATH = Path(__file__).resolve().parent.parent / "corpus" / "corpus.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HYPHEN_RUN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
_CAMEL_BOUND_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_RUN_RE = re.compile(r"[A-Za-z0-9]+")
_K1 = 1.5
_B = 0.75

# FP2 alias map (01-05): <=15 hand entries for synonym gaps BM25 cannot
# bridge (price/cost, docs/documentation, ...). Applied pre-stem to query
# AND corpus tokens alike, so it is symmetric query expansion, not gold
# fitting. No embeddings, stdlib only.
_ALIASES = {
    "cost": "price",
    "costs": "price",
    "billing": "price",
    "bill": "price",
    "auth": "authentication",
    "installation": "install",
    "configuration": "config",
    "docs": "documentation",
    "doc": "documentation",
    "picture": "image",
    "pictures": "image",
}

# FP2 heading weight: heading_path tokens count HEADING_WEIGHT x (headings
# carry page intent, e.g. "Request structure", "Handling rate limits").
HEADING_WEIGHT = 2


def _stem(tok):
    """Light suffix-strip stemmer for plurals/gerunds/participles (FP1).

    Length-guarded so short words ('as', 'does', 'this') never collapse.
    Applied identically to query and corpus tokens.
    """
    if len(tok) > 5 and tok.endswith("ies"):
        return tok[:-3] + "y"  # queries -> query
    if tok.endswith("sses") and len(tok) > 5:
        return tok[:-2]  # classes -> class
    if len(tok) > 5 and tok.endswith("ing"):
        return tok[:-3]  # reranking -> rerank, routing -> rout
    if len(tok) > 5 and tok.endswith("ed"):
        return tok[:-2]  # supported -> support
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]  # inputs -> input, levels -> level
    return tok


def _tokens(text):
    low = text.lower()
    toks = _TOKEN_RE.findall(low)
    seen = set(toks)  # dedupe the derived forms only; base term counts matter
    # FP1a dehyphen-join: 'Re-ranking' also indexes as 'reranking' so the
    # unhyphenated compound query 'reranking' overlaps (and vice versa).
    for m in _HYPHEN_RUN_RE.findall(low):
        joined = m.replace("-", "")
        if joined and joined not in seen:
            seen.add(joined)
            toks.append(joined)
    # FP1b camelCase split: 'ScoreCriteria' also indexes as 'score' +
    # 'criteria' so spaced queries match code identifiers.
    for run in _RUN_RE.findall(text):
        if any(c.isupper() for c in run) and any(c.islower() for c in run):
            for part in _CAMEL_BOUND_RE.split(run):
                low_part = part.lower()
                if low_part and low_part not in seen:
                    seen.add(low_part)
                    toks.append(low_part)
    return [_stem(_ALIASES.get(t, t)) for t in toks]


_corpus = None  # lazy: {"blocks": [...], "index": {...}}
_client = None  # lazy: one TypeSafeClient, so warm calls reuse the connection


def _build_index(blocks):
    """Tokenize the corpus once at load. Re-tokenizing per query cost ~1.3s.

    Heading tokens are indexed HEADING_WEIGHT x (FP2): the heading_path
    carries page intent, so definitional header blocks outrank long
    siblings that merely mention the terms.
    """
    docs, df = [], {}
    for b in blocks:
        toks = _tokens(b["text"]) + _tokens(" ".join(b.get("heading_path", []))) * HEADING_WEIGHT
        tf = Counter(toks)
        docs.append((b, tf, len(toks) or 1))
        for term in tf:
            df[term] = df.get(term, 0) + 1
    avgdl = sum(dl for _, _, dl in docs) / len(docs) if docs else 1.0
    return {"docs": docs, "df": df, "avgdl": avgdl or 1.0, "n": len(docs)}


def _load_corpus():
    global _corpus
    if _corpus is None:
        blocks = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))["blocks"]
        _corpus = {"blocks": blocks, "index": _build_index(blocks)}
    return _corpus


def _bm25_scores(query):
    """BM25 of the query against every block, using the prebuilt index."""
    idx = _load_corpus()["index"]
    qterms = set(_tokens(query))
    if not qterms:
        return [(b, 0.0) for b, _, _ in idx["docs"]]
    n, df, avgdl = idx["n"], idx["df"], idx["avgdl"]
    idf = {t: math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5)) for t in qterms}
    scored = []
    for block, tf, dl in idx["docs"]:
        score = 0.0
        norm = _K1 * (1 - _B + _B * dl / avgdl)
        for term in qterms:
            freq = tf.get(term)
            if freq:
                score += idf[term] * freq * (_K1 + 1) / (freq + norm)
        scored.append((block, score))
    return scored


def bm25_shortlist(query, k=SHORTLIST):
    """Trim the full corpus to the top-k BM25 candidate blocks."""
    scored = _bm25_scores(query)
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [b for b, _ in scored[:k]]


def verdict(exists, fully):
    if fully >= FOUND:
        return VERDICT_ANSWERED
    if exists < ABSENT:
        return VERDICT_ABSENT
    return VERDICT_PARTIAL


def _state_for(query, candidates):
    blocks = [
        {
            "id": b["block_id"],
            "heading_path": b["heading_path"],
            "text": b["text"],
        }
        for b in candidates
    ]
    total = sum(len(b["text"]) for b in blocks)
    if total > STATE_CHAR_BUDGET:
        over = total - STATE_CHAR_BUDGET
        for i in sorted(range(len(blocks)), key=lambda j: len(blocks[j]["text"]), reverse=True):
            if over <= 0:
                break
            cut = min(len(blocks[i]["text"]) - 500, over)
            if cut <= 0:
                continue
            blocks[i] = dict(
                blocks[i],
                text=blocks[i]["text"][: len(blocks[i]["text"]) - cut] + "…[truncated]",
            )
            over -= cut
    return {"query": query, "blocks": blocks}


def _questions_for(query, candidates):
    titles = list(dict.fromkeys(b["page_title"] for b in candidates))
    return {
        "where": Choice(
            instructions=f'Which block answers: "{query}"?',
            criteria={b["block_id"]: None for b in candidates},
        ),
        "exists": Noul(
            instructions=f'Does any supplied block address or answer: "{query}"?',
            criteria={
                "true": "At least one block states or directly implies the answer",
                "false": "No block addresses this",
            },
        ),
        "fully": Noul(
            # FP3 reword (01-05 sweep 1 evidence): the old "complete ... with
            # nothing material missing" bar read directly-answered overview
            # questions as partial (fully 0.48-0.69 on 7 sweep-1 answerables
            # whose top block states the answer outright). The bar is now
            # "a single block states the answer" — distributed-across-blocks
            # stays false, so genuine partials still land mid-band.
            instructions=f'Does a single supplied block directly state the answer to: "{query}"?',
            criteria={
                "true": "One block states the answer outright, even if background detail lives in other blocks",
                "false": "No single block states the answer; blocks only touch the topic or the answer is scattered across blocks",
            },
        ),
        "router": Choice(
            instructions=f'Which documentation page best covers: "{query}"?',
            criteria={t: None for t in titles},
        ),
    }


def _ranked_from(candidates, probabilities):
    by_id = {b["block_id"]: b for b in candidates}
    ranked = []
    for bid, prob in sorted(probabilities.items(), key=lambda kv: kv[1], reverse=True):
        b = by_id.get(bid)
        if b is None:
            continue
        ranked.append(
            {
                "block_id": bid,
                "prob": prob,
                "text": b["text"],  # verbatim copy — never generated
                "heading_path": b["heading_path"],
                "page_url": b["page_url"],
            }
        )
    return ranked


def _get_client():
    global _client
    if _client is None:
        _client = TypeSafeClient()  # reads TYPESAFE_API_KEY from the environment
    return _client


def find(query, model=MODEL):
    """Answer a docs question extractively. Exactly one system_one call."""
    if not query or not query.strip():
        raise ValueError("query must be non-empty")
    candidates = bm25_shortlist(query)
    resp = _get_client().system_one(
        state=_state_for(query, candidates),
        questions=_questions_for(query, candidates),
        model=model,
    )
    exists = resp.nouls["exists"].noul
    fully = resp.nouls["fully"].noul
    router = resp.choices["router"]
    return {
        "verdict": verdict(exists, fully),
        "exists": exists,
        "fully": fully,
        "ranked": _ranked_from(candidates, resp.choices["where"].probabilities),
        "router": {"choice": router.choice, "confidence": router.confidence},
        "usage": {
            "model": resp.model,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    }
