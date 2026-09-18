# 01-02 Summary: Jev-only search backend + /ask API

Built `backend/search/jev_search.py` (215 lines), `backend/search/tune.py`
(114 lines), and `backend/api/server.py` (66 lines). One `find()` call =
one `system_one` call (`where` Choice + `exists` Noul + `router` Choice over
a single state); answers are verbatim block copies, never generated prose.

Verify results:
- Task 1: `find('What is a System One model?')` → `answered in this
  document`, exists 0.99, top `concepts-system-one-H001` (prob 0.98).
  `find('What is the company holiday policy?')` → `not in this document`,
  exists 0.03 — abstains even though top-rank prob was 0.77 (rank tells
  where, exists tells whether; cookbook parity holds).
- Task 2: `tune.py` → verdict accuracy **10/12** at FOUND=0.7/ABSENT=0.35
  (6/6 answerable answered, 4/4 unanswerable abstained with exists
  0.03–0.04; 2/2 partials returned answered at exists 0.94/0.97 — docs do
  cover models list and build guidance, so the partial band never fired).
  Answerable top-1 rank accuracy 2/6 (informational only; returned tops
  genuinely answer, e.g. `introduction-H002` overview table for "What is a
  Choice question?"). Import-aware audit: OK, no banned imports in any
  backend .py file.
- Task 3: uvicorn on 8123 → `GET /health` 200 `{"ok":true}`;
  `POST /ask {"query":"What is Jev?"}` → answered, exists 0.99, router
  Introduction/0.98, 30 results with verbatim text, usage echoed;
  2-char query → 422. Key from env server-side only, never in responses.
- Plan verification: per-/ask cost is exactly 1 system_one call on the
  rank path (no rerank path implemented — single Choice ranking covers it);
  observed usage ~12–20k input / ~600–730 output tokens per call
  (model resolves `jev-latest` → `jev-1.13.0`; output tokens free per
  published Jev pricing). Usage is returned in every `find()` and `/ask`
  response.

Deviations:
- [Import-scope clarification] Plan's raw substring grep flags cookbook
  prose inside `corpus.json` (cookbooks mention OpenAI/Anthropic) and
  `tune.py`'s own audit pattern/strings. The implemented audit matches
  `^(import|from) <banned-lib>` in backend .py files instead — the true
  "no LLM dependency" gate. Naive-grep hits are data/strings, not imports.
- [Module-path adaptation] Plan verifies use `typesafe-doc-parser.backend…`
  dotted paths, invalid as Python imports (hyphen). Ran equivalents:
  `PYTHONPATH=typesafe-doc-parser/backend` + `search.jev_search` /
  `uvicorn api.server:app`. No code impact.
- No git repo in working dir (same as 01-01), so no per-task commits.

Live Jev calls used: 15 total (2 Task-1 verifies + 12 tune run + 1 /ask
verify). Thresholds FOUND=0.7/ABSENT=0.35 hold — no adjustment. No open
issues; `kill %1`-equivalent confirmed port 8123 free, no stray server.
