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

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from search.jev_search import find  # noqa: E402

# The UI shows one lead quote plus at most four more sources; sending all 30
# ranked blocks was ~50 KB of unread text per response.
TOP_RESULTS = 5

app = FastAPI(title="potpie-doc-parser", docs_url=None, redoc_url=None)


class AskRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


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
                "page_url": b["page_url"],
                "text": b["text"],
            }
            for b in r["ranked"][:TOP_RESULTS]
        ],
        "usage": r["usage"],
    }


# Local dev only: `uvicorn api.index:app` then open http://127.0.0.1:8000.
# On Vercel the rewrite sends only /api/* here, so this mount never runs.
app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="public")
