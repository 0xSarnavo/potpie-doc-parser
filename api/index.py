"""Vercel serverless entrypoint: HTTP API over the Jev search backend.

POST /api/ask {query} -> {verdict, exists, router, results, usage}
GET  /api/health      -> {ok: true}

Routes carry the /api prefix because vercel.json rewrites /api/* here and
the function sees the original path. Static files come from public/ — on
Vercel directly, locally via the mount below, so both are same-origin and
no CORS is needed.

The TypeSafe key is read from the environment server-side only and is
never echoed in responses. Answer text is copied verbatim from corpus
blocks by search/jev_search.py — this layer adds no prose.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from typing import Literal  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from search.jev_search import find  # noqa: E402

# The UI shows one lead quote plus at most four more sources; sending all 30
# ranked blocks was ~50 KB of unread text per response.
TOP_RESULTS = 5


def doc_link(md_url, heading_path):
    """Turn the .md source URL into the human-readable docs page.

    The corpus stores the ".md" URL because that is what the ingester
    fetches, but a reader clicking "Source" wants the rendered page, not raw
    Markdown. The deepest heading becomes a Mintlify-style anchor so the link
    lands on the right section; an anchor that does not resolve still opens
    the correct page, so a wrong guess costs nothing.
    """
    url = re.sub(r"\.md$", "", md_url or "")
    heading = (heading_path or [])[-1] if heading_path else ""
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return f"{url}#{slug}" if slug else url

app = FastAPI(title="potpie-doc-parser", docs_url=None, redoc_url=None)

# Where rated answers are appended, one JSON object per line. Vercel's
# filesystem is ephemeral, so on a deploy this collects only within a single
# warm instance — fine for a demo, and the path is swappable for a real store.
FEEDBACK_PATH = Path(
    os.environ.get("FEEDBACK_PATH")
    or (Path("/tmp") / "feedback.jsonl" if os.environ.get("VERCEL") else ROOT / "backend" / "feedback.jsonl")
)
FEEDBACK_MAX_BYTES = 5_000_000  # stop appending rather than fill the disk


class AskRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class FeedbackRequest(BaseModel):
    """A rating for one answer. Every field is bounded: this is a public
    write endpoint, so nothing unvalidated reaches the log."""

    answer_id: str = Field(min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=500)
    rating: Literal["up", "down"]
    verdict: str = Field(max_length=64)
    top_block: str = Field(default="", max_length=128)
    exists: float = Field(default=-1.0, ge=-1.0, le=1.0)
    reason: Literal["", "wrong-section", "not-in-docs", "wrong-verdict", "incomplete"] = ""


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/ask")
def ask(req: AskRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="query must not be empty")
    try:
        r = find(query)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"search failed: {type(e).__name__}")
    return {
        "verdict": r["verdict"],
        "exists": r["exists"],
        "router": r["router"],
        "results": [
            {
                "block_id": b["block_id"],
                "prob": b["prob"],
                "heading_path": b["heading_path"],
                "page_title": b.get("page_title", ""),
                "page_path": re.sub(r"^https?://|\.md$", "", b["page_url"] or ""),
                "page_url": doc_link(b["page_url"], b["heading_path"]),
                "text": b["text"],
            }
            for b in r["ranked"][:TOP_RESULTS]
        ],
        "usage": r["usage"],
    }


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    """Record a thumbs up/down so answers can be tuned against real disputes.

    Append-only JSONL: one rating per line, latest line wins for an answer_id.
    Storing the scores alongside the rating is the point — a disputed verdict
    plus its exists/fully numbers is what a new gold row is made of.
    """
    row = req.model_dump()
    row["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if FEEDBACK_PATH.exists() and FEEDBACK_PATH.stat().st_size > FEEDBACK_MAX_BYTES:
            raise HTTPException(status_code=507, detail="feedback log full")
        with FEEDBACK_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(status_code=503, detail=f"could not record: {type(e).__name__}")
    return {"ok": True}


# Local dev only: `uvicorn api.index:app` then open http://127.0.0.1:8000.
# On Vercel the rewrite sends only /api/* here, so this mount never runs.
app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="public")
