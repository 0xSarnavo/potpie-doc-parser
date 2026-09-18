# 01-04 Summary: Partial-band fine-tune (exists + fully Nouls)

Added one companion Noul `fully` to the same single `system_one` call and
switched `verdict()` to three-way logic (`answered iff fully>=FOUND;
absent iff exists<ABSENT; else partial`). Replaced the 2 mislabeled partial
golds with genuinely-partial queries. Tune now **11/12** (gate >=10/12,
TUNE-DONE) with the partial band demonstrably firing.

## Code changes

`backend/search/jev_search.py` (+13/-4 lines):
- `_questions_for` gains ONE Noul `fully` (same `system_one` request, zero
  extra calls): instructions=`Does a supplied block state the complete,
  direct answer to: "QUERY"?`, true=`A block gives the full answer with
  nothing material missing`, false=`Blocks only touch the topic or answer
  part of it`.
- `verdict(exists, fully)`: `fully>=FOUND` → answered; `exists<ABSENT` →
  absent; else partial. `FOUND=0.7`/`ABSENT=0.35` stay module constants.
- `_ask` reads `resp.nouls["fully"].noul`, returns `fully` alongside
  `exists` (backward-compatible: `server.py` untouched, still works).

`backend/search/tune.py`: 2 partial golds replaced (with inline rationale
comment); table prints `exists` + `fully` columns.

## Golds changed (and why)

- OUT: `What languages does TypeSafe support?` / `How fast is Jev?` — both
  scored answered at 0.94/0.97 in the 10/12 baseline. Docs DO list Python+JS
  SDKs and call Jev "fast", so these were mislabeled answerables; the old
  single-`exists` Noul ("address OR answer") read topical coverage as
  answered, and the partial band could never fire.
- IN: `When will Jev support image inputs?` → **partial** (exists 0.45,
  fully 0.09, top `models-H002`): docs state image/audio/video "not
  supported (yet)" (`concepts-system-one-H001`, `models-H002`) but give no
  date/roadmap — topic touched, answer incomplete. Band fires as designed.
- IN: `What is TypeSafe's monthly subscription price?` → **absent** (exists
  0.07, fully 0.03) — the documented MISS. Docs are purely usage-priced
  ($42/Btok, $0.042/Mtok, output free in `models-H002`) with no subscription
  concept at all, so Jev reads the question as unaddressed, not partially
  addressed. Arguably absent is the *correct* verdict for that wording
  (there is no monthly subscription to be partial about). Two reword probes
  (`volume discounts or monthly minimums…` → exists 0.08; `When is the next
  Jev version releasing?` → exists 0.09) also scored absent: Jev's `exists`
  is strict — blocks that merely sit near the topic don't count as
  addressing it. No threshold change indicated (margins are wide: answerable
  `fully` ≥0.80, unanswerable `exists` ≤0.04, partial mid-band 0.45/0.09).

## Verify results

- Task 1: `tune.py` → verdict accuracy **11/12** at FOUND=0.7/ABSENT=0.35
  (6/6 answerable answered with `fully` 0.80–0.96; 4/4 unanswerable absent
  with `exists` 0.02–0.04; 1/2 partials partial). `TUNE-DONE`, audit OK.
  Unanswerable probe (`What is the company holiday policy?`) → `not in this
  document` (exists 0.04, fully 0.02) even though top-rank prob was 0.84
  (rank tells where, exists/fully tell whether; cookbook parity holds).
- Task 2: `grep -rE '^(import|from) (openai|anthropic|…)' backend/` →
  **AUDIT-CLEAN**. `find('What is Jev?')` → answered (exists 0.99, fully
  0.77), top `introduction-H001` (0.93), router Introduction/0.97, usage
  `{model jev-1.13.0, input 12241, output 624}`.
- 1-call-per-ask: code inspection shows exactly one `client.system_one` on
  the rank path (`_ask`); `_window_prepass` only runs when candidates >200,
  but `SHORTLIST=30` caps candidates at 30, so it never triggers. Four
  questions (`where`+`exists`+`fully`+`router`) ride in that one request —
  parallel questions cost ~one per the feasibility note.

## Regression lock

- 6/6 original answerables still answered; 4/4 unanswerables still absent
  (exists 0.02–0.04, same as 01-02 baseline 0.03–0.04).
- Answerable top-1 rank accuracy 2/6 — identical aggregate to the 01-02
  baseline (#1 `concepts-system-one-H001` top1, #5 `concepts-state-H001`
  top1). Ranking path (`where`/router/BM25) untouched — only a parallel
  Noul added — so ranking is identical by construction.
- Thresholds unchanged: FOUND=0.7/ABSENT=0.35, no adjustment suggested.
- Per-/ask usage: ~12–20k input / ~620–720 output tokens (model resolves
  `jev-latest` → `jev-1.13.0`; output tokens free per Jev pricing).

## Deviations

- [Probes over target, within budget] 2 extra single-query probes spent
  testing replacement-partial phrasings (both scored absent; documented
  above instead of test-fitting golds to the model). Task spend 15 calls
  vs ~25 budget; plan total 16 vs ~30 budget.
- No git repo in working dir (same as 01-01, 01-02), so no per-task commits.
- `tune.py` keeps its pre-existing unused `subprocess` import (ponytail:
  out of scope, untouched).

Live Jev calls used: 16 total (1 holiday-probe + 12 tune + 2 reword-probes +
1 `What is Jev?` probe). No open issues; partial band fires, gate passes,
still 1 call per ask, zero new deps, audit clean.
