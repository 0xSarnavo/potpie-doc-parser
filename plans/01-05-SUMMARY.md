---
phase: 01-jev-doc-parser
plan: 5
subsystem: search
tags: [jev, system-one, bm25, eval, typesafe-sdk, stdlib]

# Dependency graph
requires:
  - phase: 01-jev-doc-parser plan 4
    provides: [fully Noul with FOUND/ABSENT bands, 11/12 tune gate, firing partial]
provides:
  - Page-derived 36-query eval set (eval_gold.json) with local + live runners (eval.py)
  - BM25 FP1/FP2 fixes (stemmer, dehyphen-join, camelCase split, heading 2x, 11-entry alias map)
  - FP3 fully-criteria reword from sweep evidence; 90k-char outlier state guard
  - Measured final scores (34/36 verdict, 6/6 abstention) with documented residuals
affects: [website search UI (DOC-03), confidence display, near-band UX, token-budget handling]

# Tech tracking
tech-stack:
  added: []
  patterns: [single system_one call per ask (where+exists+fully+router), BM25 shortlist with heading boost, eval-gold JSON with local-recall + live-sweep runners]

key-files:
  created: [typesafe-doc-parser/backend/search/eval_gold.json, typesafe-doc-parser/backend/search/eval.py]
  modified: [typesafe-doc-parser/backend/search/jev_search.py]

key-decisions:
  - "FP3 fully-criteria reword (not threshold move): sweep-1 showed systematic fully under-read on directly-answered overviews"
  - "No threshold moves and no gold relabeling: P1/P2 residuals documented, not fitted"
  - "Outlier-only 90k-char state guard for max_tokens_exceeded; under-budget states byte-identical"
  - "Freeze at 34/36 + 6/6 after 3 sweeps per plan stop rule"

patterns-established:
  - "Eval golds stay frozen once sweeps start; residuals documented as gold-error vs model-limit vs infra"
  - "Live-call budget counted and reported per plan (~120)"

requirements-completed: [DOC-02, DOC-04]

# Metrics
duration: 27min
completed: 2026-09-18
---

# Phase 01 Plan 5: Deep fine-tune to measured goal Summary

**36-query page-derived eval (19 answerable + 8 keyword + 6 unanswerable + 3 partial): final live verdict 34/36 = 94.4% (goal >=95%, narrow miss), abstention 6/6 = 100% (goal met); stdlib-only BM25 fixes + one sweep-evidenced fully reword, 1 call/ask intact, zero new deps**

## Performance

- **Duration:** 27 min
- **Started:** 2026-09-18T08:36:41Z
- **Completed:** 2026-09-18T09:03:23Z
- **Tasks:** 3/3
- **Files modified:** 3 (2 created, 1 modified)

## Scores vs goal

| Metric | Goal | Sweep 1 | Sweep 2 | Sweep 3 (final) |
|---|---|---|---|---|
| Verdict accuracy (36 queries) | >=95% (≥35/36) | 25/32 run* | 33/36 = 91.7% | **34/36 = 94.4%** |
| Abstention (6 unanswerables → absent) | 100% | 4/4 run | 5/5 + 1 ERROR | **6/6 = 100%** |
| Local BM25 top-30 recall (30 retrievables) | 100% or misses listed | 20/30 | 25/30 | **25/30, 5 listed** |
| Rank top-1 / top-3 (track only, FP5) | — | — | 17/30 / 25/30 | 18/30 / 25/30 |
| tune.py gate (FOUND=0.7/ABSENT=0.35) | ≥10/12 + audit | — | — | **10/12, TUNE-DONE, audit clean** |

\* Sweep 1 crashed on U5 (`max_tokens_exceeded`, no retry hardening yet): 32 calls, 7 systematic fully under-reads + 4 unrun.

## Failure-point table (fix or stop-reason each)

| FP | Failure point | Disposition |
|---|---|---|
| FP1 | BM25 miss on compounds/hyphens (`reranking` vs `Re-ranking`; `ScoreCriteria` vs `score criteria`) | **FIXED in code.** `_tokens()` now: (a) dehyphen-join (`Re-ranking` also indexes `reranking`), (b) camelCase split (`ScoreCriteria` → `score`+`criteria`), (c) light suffix-strip stemmer (plurals/gerunds/participles, length-guarded). Verified locally before any Jev call: A13 58→13, K8 42→5, P1 45→2 (all top-30 HIT). |
| FP2 | Synonym gap (price/cost, fast/latency class) | **FIXED in code.** Heading tokens indexed 2x extra (`HEADING_WEIGHT=2`; headings carry intent) + 11-entry hand alias map (`_ALIASES`: cost/costs/billing/bill→price, auth→authentication, installation→install, configuration→config, docs/doc→documentation, picture/pictures→image). Verified locally: A10 37→14, A11 45→7, A19 163→32. ≤15 entries, symmetric on query+corpus, no embeddings. |
| FP3 | exists/fully band edges | **FIXED via criteria reword (sweep-evidenced, no threshold move).** Sweep 1 showed systematic error: 7 directly-answered overviews read partial (`fully` 0.48–0.69, e.g. A08 confidence-H002 top-1 yet `fully` 0.48). `fully` reworded from "complete ... nothing material missing" to "a single block states the answer outright (background elsewhere OK); scattered-across-blocks stays false". Sweep 2: all 7 flipped to answered (`fully` 0.74–0.95); P3 true partial stayed partial; unanswerables untouched (`exists` unchanged, 0.02–0.04). FOUND/ABSENT still 0.7/0.35. |
| FP4 | Router wrong page but rank right | **NO FIX (per plan: rank is extract source of truth, display-only).** Observed harmless: A03 top `introduction-H002`, A04 `api-H005`, A05 `api-H007`, A19 `patterns-H002` — verdicts all correct from sibling blocks. |
| FP5 | Choice dilution over 30 options (low top-1, good top-3) | **NO FIX (per plan: track top-3, don't chase top-1).** Final top-1 18/30, top-3 25/30; all 4 exact-block rank misses (A03/A04/A05/A19) still verdict OK via siblings. |
| FP6 (found in sweep) | `max_tokens_exceeded` 400 on code-dense 30-block states (U5 failed twice; ~121k chars) | **FIXED via outlier-only guard.** `_state_for` trims longest tails to `STATE_CHAR_BUDGET=90k` chars when over budget; under-budget states byte-identical. Sweep 3: U5 → absent (0.08/0.07), all 8 other trimmed queries kept their verdicts. Also hardened `eval.py --live` with per-query try + 1 retry, ERROR recorded not crashed. |

## Residuals (frozen after 3 sweeps — no fitting)

1. **P2 `What is TypeSafe's monthly subscription price?` → absent (exists 0.05), gold partial. Probable GOLD ERROR.** Docs have no subscription concept (usage-only pricing); absent is arguably the correct verdict for that wording (same argument as 01-04). Deliberately NOT relabeled — that would be test-fitting golds to the model.
2. **P1 `When will Jev support image inputs?` → absent (exists 0.32, fully 0.12; sweep 2: 0.33), gold partial. MODEL-LIMIT / band-edge.** Stable across two sweeps (01-04's 0.45 did not repeat): Jev reads the WHEN question as unaddressed since docs give no timeline. Thresholds NOT moved for one query.
3. **Local recall 25/30.** Remaining BM25 misses: A03/A04/A05 (definitional H001 headers outranked by longer same-page siblings — Jev still answers correctly from siblings, all verdict OK), A19 (rank 32, same-page siblings dominate), P2 (186 — no `monthly`/`subscription` terms near the price block; Jev never sees it, consistent with residual 1).

## Live-call spend (budget ~120 for the whole plan)

- Sweep 1: 32 (31 complete + U5 crash, no retry path yet)
- Sweep 2: 37 (36 + 1 U5 retry, still 400)
- Sweep 3: 36 (all complete, U5 fixed by guard)
- Final `tune.py` lock: 12
- **Total: 117 live calls (6 answerable probes from prior research excluded — pre-plan). Zero extra probes; no test-fit loops.**

## Task Commits

No git repository exists in the working directory (same as 01-01, 01-02, 01-04), so per-task commits were impossible. Files are on disk as listed below; commit manually when a repo is initialized.

1. **Task 1: Page-derived eval set + local recall** — uncommitted (no repo)
2. **Task 2: Iterate to goal, 3 sweeps** — uncommitted (no repo)
3. **Task 3: Lock, audit, summary** — uncommitted (no repo)

## Files Created/Modified

- `typesafe-doc-parser/backend/search/eval_gold.json` — (created) 36-query gold set: 19 answerables (A01–A19, one per page family), 8 keyword variants (K1–K8 incl. rerank/rate-limit/tiny-alias weak spots), 6 unanswerables (U1–U6: 4 tune keeps + sourdough + capital-gains), 3 partials (P1–P3 with rationale notes)
- `typesafe-doc-parser/backend/search/eval.py` — (created, 156 lines) `--local-only` BM25 recall table ($0) + `--live` verdict/abstain/top-1/top-3 sweep with goal PASS/FAIL, per-query retry, `jev_search import find + bm25_shortlist`
- `typesafe-doc-parser/backend/search/jev_search.py` — (modified, +92 lines) FP1 tokenizer (dehyphen-join, camelCase split, stemmer, 11-entry alias map), FP2 `HEADING_WEIGHT=2`, FP3 `fully` reword, `STATE_CHAR_BUDGET` outlier guard. Still 1 `system_one` per ask on the rank path, stdlib-only imports, no new deps

## Decisions Made

- FP3 as criteria reword, not threshold move: sweep-1 evidence showed a systematic `fully` bias (7 queries), and rewording keeps genuine partials mid-band while thresholds stay 0.7/0.35 for tune continuity.
- No ABSENT move (0.35→0.30) for borderline P1 and no P2 relabel: both would be single-query fitting; documented as residuals instead.
- Outlier-only state guard instead of global truncation or shortlist shrink: 9/36 queries trimmed at tails, 27 byte-identical, zero verdict flips among previously-passing queries.
- tune.py untouched (shares jev_search thresholds/criteria): final 10/12 still passes gate (≥10) + TUNE-DONE + audit clean. The two misses are the partial golds, consistent with eval P1/P2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] eval.py crashed mid-sweep on API 400, losing unrun queries**
- **Found during:** Task 2, sweep 1 (U5 `max_tokens_exceeded`, traceback, 4 queries unrun)
- **Issue:** No per-query error handling; one bad query killed the whole sweep
- **Fix:** try/except per query + 1 retry, ERROR recorded as miss with reason, sweep continues
- **Files modified:** typesafe-doc-parser/backend/search/eval.py
- **Verification:** Sweeps 2–3 completed all 36 rows with ERROR/U5 rows printed inline

**2. [Rule 3 - Blocking] max_tokens_exceeded root cause (code-dense states overflow server token count)**
- **Found during:** Task 2, sweep-2 analysis (U5 failed twice deterministically; size/token-density comparison vs passing A10)
- **Issue:** 30-block states of code-dense blocks can exceed the API token limit; website layer would hit the same wall
- **Fix:** `STATE_CHAR_BUDGET=90_000` outlier guard in `_state_for` (trim longest tails first; under-budget states unchanged)
- **Files modified:** typesafe-doc-parser/backend/search/jev_search.py
- **Verification:** Sweep 3 — U5 passes (absent 0.08/0.07); all 8 other trimmed queries kept sweep-2 verdicts

---

**Total deviations:** 2 auto-fixed (both blocking/infra, no scope creep; fixes are website-relevant robustness, not gold fitting)

## Issues Encountered

- Sweep-1 crash (above) cost 4 unrun queries but only 32 calls; absorbed by budget (total 117/120).
- One `python3 -c` analysis command hit the 120 s tool timeout (cold BM25 over 998 blocks × 36 queries); reran with 300 s, no live cost.
- A shell chaining quirk (`echo ===` after `||`) truncated Task-3 verify output; audit + imports re-verified in a follow-up command (grep exit 1 = clean).

## User Setup Required

None - no external service configuration required. (`TYPESAFE_API_KEY` was provided via env var for this plan's sweeps only, never written to disk.)

## Residual risks for the website layer (DOC-03)

1. **Near-band verdicts are load-bearing UX, not just eval trivia.** P1 (exists 0.32 vs ABSENT 0.35) shows the partial band edge is ±0.1 noisy run-to-run. The UI should render a low-confidence/uncertain state for exists/fully within ~0.1 of a threshold (e.g. "possibly covered — related blocks below") rather than a hard absent.
2. **Token budget per ask is real.** Code-dense queries can still approach limits even with the 90k-char guard (server counts tokens, we count chars). If the website adds context (chat history, filters) into state, re-measure worst-case input tokens; consider surfacing a graceful "query too broad, narrowed to top-N blocks" path.
3. **Rank ≠ extract quality for header blocks.** Definitional H001 headers sometimes lose BM25 to longer siblings (A03/A04/A05) — harmless today because siblings answer, but snippet display should prefer the cited `where` top block, not the BM25 top block.
4. **Partial golds are the weakest contract.** P2 shows "partial" is a judgment call Jev may read as absent when docs lack the concept entirely. Website copy for `partially answered` should hedge ("docs touch on this but may not fully answer") rather than promise coverage.
5. **No test-fit debt.** Golds were frozen before sweep 1 and never relabeled to match outputs; 34/36 + 6/6 is an honest ceiling for this backend, not a tuned peak. Future threshold/criteria changes must re-run `eval.py --live` (36 calls) and `tune.py` (12 calls) before shipping.

## Self-Check: PASSED

- FOUND: typesafe-doc-parser/backend/search/eval_gold.json (36 queries verified via --local-only header count)
- FOUND: typesafe-doc-parser/backend/search/eval.py (156 lines, ≥80 required)
- FOUND: typesafe-doc-parser/backend/search/jev_search.py (FP1/FP2/FP3/guard present, verified via grep of `_ALIASES`, `HEADING_WEIGHT`, `STATE_CHAR_BUDGET`, reworded `fully`)
- FOUND: typesafe-doc-parser/plans/01-05-SUMMARY.md (this file)
- Commits: none (no git repo — documented above, same as 01-01/01-02/01-04)
- 1 call/ask: exactly one `client.system_one` on rank path (`_ask`); `_window_prepass` unreachable (SHORTLIST=30 < MAX_LABELS=200)
- No new deps: imports are json/math/re/pathlib/argparse/sys + typesafe_sdk only; banned-import grep clean

---
*Phase: 01-jev-doc-parser*
*Completed: 2026-09-18*
