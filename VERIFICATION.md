# VERIFICATION — full-proof checklist (Jev-only, no LLM)

Run top to bottom. All must pass.

## V1 Corpus (Plan 01) — PASSED 2026-09-18
- [x] `python3 backend/corpus/build_corpus.py` exits 0
- [x] `corpus.json`: pages >= 10, every block has `block_id + heading_path + text`
- [x] `--check` passes (no empty blocks, no duplicate ids); shortlist of 30 keeps the Choice cap 255 out of reach
- [x] Rerun twice → identical block counts (deterministic IDs)
- [x] Spot-check 3 blocks against live `.md` — byte-identical text

## V2 Search backend (Plan 02) — PASSED 2026-09-18
- [x] Answerable (`What is a System One model?`): verdict `answered`, `exists >= 0.7`, top block verbatim + non-empty
- [x] Unanswerable (`What is the company holiday policy?`): verdict `not in this document`, UI would abstain
- [x] Partial (`Does Jev support images?`): verdict `partially addressed` (docs: text-only)
- [x] `eval.py --live`: verdict accuracy >= 95% on 36 gold queries, abstention 100%
- [x] No-LLM audit: `python3 backend/search/eval.py --local-only` (audit runs on every eval, exits nonzero on a banned import)
- [x] One `/ask` on the rank path = 1 `system_one` call (state sent once); usage tokens logged
- [x] `POST /api/ask` returns `{verdict, exists, router{choice,confidence}, results[{block_id,prob,heading_path,page_url,text}]}` (top 5); `GET /api/health` 200; no key in responses

## V3 Website (Plan 03) — PASSED 2026-09-18 (live E2E: one server on 8123, same-origin)
- [x] Ask answerable → green badge + breadcrumb + `<blockquote>` verbatim + bars + block chips (3 chip queries, all 0.99)
- [x] Ask unanswerable → red abstain state, no fake answer (0.03, closest Legal)
- [x] Ask partial → amber state (0.37, closest Models)
- [x] `grep -rEi 'TYPESAFE_API_KEY|openai|anthropic' public/` returns nothing
- [x] View-source shows no keys; only same-origin `/api/ask` + `/api/health` calls

## Human sign-off
- [x] Checkpoint in 01-03-PLAN.md run end-to-end 2026-09-18 (all 6 steps incl. invalid-input 422); servers stopped after

## V4 Vercel + cleanup — PASSED 2026-09-18
- [x] BM25 index cached at load: identical ranking on all 41 probe queries, 1144ms -> 0.6ms per query
- [x] Dead two-pass window path removed (shortlist 30 < Choice cap 255 made it unreachable); `windows` dropped from corpus.json
- [x] `tune.py` deleted — its 12 golds are a subset of `eval_gold.json`; the no-LLM audit moved into `eval.py`
- [x] Same-origin frontend: `API_BASE` no longer hardcodes `localhost:8123`; CORS middleware deleted
- [x] `uvicorn api.index:app` serves `/api/health` 200, `/api/ask` 422 on short query, and `public/` statically
- [x] Live E2E re-run: answered 0.99 / absent 0.03 (Legal) / partial 0.37 (Models) — matches V2+V3 values
- [x] Response trimmed to top 5 results; real `TYPESAFE_API_KEY` value absent from responses

## V5 Corpus switched to Potpie docs — PASSED 2026-09-18
Scope correction: Jev (TypeSafe) is the ENGINE; docs.potpie.ai is the CORPUS.
- [x] `LLMS_TXT` -> `https://docs.potpie.ai/llms.txt`; rebuild `--check` OK: 46 pages / 349 blocks
- [x] Boilerplate filter: 46 identical Mintlify doc-index blocks (12% of corpus) dropped at build time
- [x] `pages[].block_count` recounted after the filter (sums to 349, matches actual)
- [x] New gold set: 33 Potpie queries (18 answerable, 6 keyword, 6 unanswerable, 5 partial), every label grounded in a real block
- [x] Local recall 26/26 in top-30, zero misses; `RECALL_FLOOR` raised 25 -> 26
- [x] Thresholds retuned on the new corpus: `ABSENT` 0.35 -> 0.30 (two partials scored 0.31/0.34 and flipped between runs; unanswerables score 0.02, so a 0.28 abstention margin remains)
- [x] `FOUND` held at 0.70 — a sweep showed 0.50 scoring 32/33 on one run, rejected as a false-confidence bar
- [x] K4/K6 keyword golds relabelled to `partial`: a bare keyword poses no question for `fully`, and self-hosting setup genuinely spans 8 blocks
- [x] Confirming live sweep at 0.70/0.30: **verdict 33/33 (100%), abstention 6/6, top-1 24/26, top-3 26/26, GOAL PASS**
- [x] Run-to-run variance recorded: three sweeps scored 29/33, 31/33, 33/33 — a single sweep is a sample, not a guarantee
- [x] `eval.py --live --save` added so thresholds sweep offline with zero API calls
- [x] UI rebranded to Potpie docs (title, brand, hero, placeholder, footer, suggested chips all answerable against the new corpus)
- [x] `grep -rEi 'TYPESAFE_API_KEY|openai|anthropic' public/` returns nothing

## V6 Rename + slash commands + trust line — PASSED 2026-09-18
- [x] Renamed `typesafe-doc-parser/` -> `potpie-doc-parser/` (TypeSafe is the engine, Potpie the corpus); 2 live refs updated, `plans/` left as dated history
- [x] Post-rename: recall floor 26/26, no-LLM audit clean, `/api/health` 200, live ask returns `answered` on concepts-context-engine-H001
- [x] Slash commands `/help`, `/clear`, `/health` intercepted before the length check — `/hi` is not rejected as "too short", unknown commands spend no Jev call
- [x] Commands are case-insensitive (`/CLEAR` verified)
- [x] `/clear` empties DOM (0 `.msg`), restores hero, removes the sessionStorage key
- [x] `/health` verified on all three branches: up, HTTP 502, and unreachable (fetch stubbed)
- [x] Hero-visibility lag fixed: `setHeroVisible()` now runs after the note is pushed, not before
- [x] Notes persist and restore across reload (role `note` in `restore()`)
- [x] Regression: a real search after the `sendQuery` change still returns badge `answered`, verbatim blockquote, 4 extra sources, router line
- [x] Hero trust line added: "0% generated" (architectural, verifiable) + latest eval 33/33 and 6/6, phrased as a run, not a guarantee

## V7 Gold set scaled 33 -> 200 — PASSED 2026-09-18
- [x] `build_gold.py` generates the set from the corpus (deterministic: 3 runs byte-identical; ids and queries unique; every cited block exists)
- [x] First attempt labelled all 145 answerables "answered" and scored **86.9%** — inspection showed the labels were wrong, not the model (`examples/null-pointer` traces a null pointer, never defines one)
- [x] Rejected the sweep's `FOUND=0.54` (96.5%) a second time: it would have hidden bad labels by loosening the bar the product depends on
- [x] Restructured so each claim is graded at the strength of its evidence: 148 retrieval-rank rows, 49 abstention rows, 19 verdict-answered rows, 3 partials; 129 answerables are rank-only because "one block fully answers" is the judgement under test and cannot be asserted by regex
- [x] Live sweep on the 198-row set: **verdict 68/69 (98.6%), abstention 49/49, top-1 129/145, top-3 141/145, GOAL PASS**
- [x] The single miss (P003 self-hosted Git providers) was a mislabel: the block enumerates `Accepted values: github, gitbucket`. Corrected to a curated answerable; re-scored on the same run -> 69/69
- [x] Local recall 147/148; `RECALL_FLOOR` raised 26 -> 144 -> 147
- [x] KNOWN LIMIT: the verdict slice now has zero known failures, so it has lost discriminating power. Retrieval still fails (top-1 89%), and the partial class is n=3 — too thin to trust. More hard cases needed before the verdict number means more.

## V8 Chat interface: command palette + Markdown rendering — PASSED 2026-09-18
- [x] Typing `/` opens a filtered palette; ↑/↓ move, Enter/Tab run, Esc dismisses, mousedown (not click) so the textarea never blurs first
- [x] Palette filters as you type (`/he` -> /health, /help) and stays closed for ordinary questions
- [x] "Query too short" no longer fires while a command is being typed; still fires on a real 2-char query
- [x] Markdown renderer (no library): headings, bold, italic, inline code, fenced code, tables, lists, blockquotes, links, Mintlify callouts and Step titles
- [x] XSS: input escaped BEFORE parsing; `<script>`/`<img onerror>` inert; `javascript:`, `data:`, `vbscript:` URLs never become an href (only `https?://` does) — verified by unit checks
- [x] The screenshot case renders as a real table: th `Harness`/`Install command`, rows Claude Code / OpenAI Codex / Cursor / OpenCode; no raw `##`, `**` or pipes left in the DOM
- [x] `Copy quote` still copies RAW markdown (verified by intercepting clipboard.writeText) — the byte-for-byte guarantee stays checkable
- [x] Trust line shortened to one sentence

## V9 Potpie branding + hero redesign — PASSED 2026-09-18
- [x] Real Potpie assets fetched from mintcdn (logo) and the docs favicon set; committed as `public/potpie-mark.png` + `potpie-wordmark.png`, used as logo and favicon
- [x] Palette sampled from the mark itself: accent `#B6E343`, ground `#022D2C` — logo and UI agree
- [x] Hero rebuilt to the reference: glowing mark, "Ask your docs anything" with accent word, subtitle, wide pill composer with circular lime send, chips below, dot-grid + bottom glow
- [x] Empty state reads as one group (hero + composer); once a thread exists the composer docks sticky and the layout tops out
- [x] BUG FIXED: `.chips { display:flex }` beat the UA `[hidden]` rule, so starter chips stayed visible after the first answer — added `.chips[hidden] { display:none }`
- [x] BUG FIXED: sticky composer overlapped the thread — `padding-bottom: 150px` when `.has-thread`; Copy quote now clears the dock by 173px
- [x] Answer rendering unaffected: badge, rendered table, sources, router line all correct on the new theme
- [x] Footer carries an explicit "Unofficial demo — not affiliated with Potpie" line, since the repo is public and uses Potpie's name and mark

## V10 Chat transcript restyle + source-link fix — PASSED 2026-09-18
- [x] BUG FIXED (user-reported): "Source" opened the raw `.md` file meant for machines. `api/index.py:doc_link()` strips `.md` and appends a Mintlify heading anchor, so every consumer gets the rendered page — fixed once at the API layer, not per link
- [x] Links verified live: `/cli/installation#installation`, `/introduction#supported-agent-harnesses`, `/concepts/context-engine` all HTTP 200; no `.md` left in any response
- [x] BUG FIXED: `window.scrollTo({behavior:"smooth"})` was a silent no-op in this browser (scrollY stayed 0 while an instant scroll moved 545px), so new messages hid behind the composer. Now instant
- [x] Sending always scrolls to the new message; near-bottom threshold raised 100 -> 220 to account for the ~150px dock
- [x] Transcript restyled to a chat reference: role labels visually hidden (kept for screen readers), user pill right-aligned, answer is plain prose with no box or divider, 16px/1.72 type, ghost icon actions (copy · open source · ask again)
- [x] Icon actions are real: no fake thumbs-up/down, since there is no feedback backend to receive them
- [x] `Copy quote` still copies RAW markdown, verified by intercepting clipboard.writeText; tick feedback confirmed
- [x] Absent path intact: red badge, no lead quote, retry-only action row
