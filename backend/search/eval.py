"""Page-derived eval + no-LLM audit for the Jev search backend (01-05).

Local recall and audit (zero Jev calls):
    python3 eval.py --local-only
Live verdict sweep (one system_one call per query):
    TYPESAFE_API_KEY=xxx python3 eval.py --live [--limit N]

eval_gold.json holds 36 queries: 19 answerables, 8 keyword variants,
6 unanswerables, 3 partials. Live goal: verdict accuracy >=95% AND
abstention (unanswerables -> absent) 100%. Exits nonzero if the audit
finds a banned LLM import, or if --live misses either goal.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jev_search import find  # noqa: E402

BANNED_IMPORT_RE = re.compile(
    r"^\s*(import|from)\s+"
    r"(openai|anthropic|transformers|sentence_transformers|langchain|llama_index)\b",
    re.MULTILINE,
)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FEEDBACK_PATH = REPO_ROOT / "backend" / "feedback.jsonl"

GOLD_PATH = Path(__file__).resolve().parent / "eval_gold.json"
SHORTLIST = 30  # must match jev_search.SHORTLIST: what Jev actually sees

GOAL_VERDICT = 0.95
GOAL_ABSTAIN = 1.0
# Recorded baseline on the Potpie corpus: 147 of 148 retrievable golds reach
# the top-30 shortlist. The one miss ("How do I install Potpie?") is a real
# ambiguity — CLI install vs self-hosted install — and is kept deliberately.
# This is a regression floor, not a target (rank within the shortlist is
# Jev's job, FP5).
RECALL_FLOOR = 147


def load_gold():
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))["queries"]


def run_audit():
    """Fail if any .py file in the repo imports a banned LLM library."""
    files = sorted(p for p in REPO_ROOT.rglob("*.py") if "__pycache__" not in p.parts)
    hits = [
        f"{py.relative_to(REPO_ROOT)}: {m.group(0).strip()}"
        for py in files
        for m in BANNED_IMPORT_RE.finditer(py.read_text(encoding="utf-8"))
    ]
    print(f"audit: scanned {len(files)} .py files under {REPO_ROOT.name}/")
    if hits:
        print("audit: FAIL — banned LLM imports found:")
        for h in hits:
            print(f"  {h}")
        return False
    print("audit: OK — no banned LLM imports (openai/anthropic/transformers/langchain/llama)")
    return True


def review_feedback():
    """Turn collected thumbs into tuning work.

    A rating alone is noise; a rating next to the scores that produced it is a
    candidate gold row. Down-votes are grouped by what the user said was wrong,
    because each reason points at a different fix:
      not-in-docs   -> abstention missed: exists was too high
      wrong-verdict -> threshold candidate: check exists/fully against the band
      wrong-section -> retrieval miss: the block should not have ranked first
      incomplete    -> a genuine partial the gold set probably lacks
    """
    if not FEEDBACK_PATH.exists():
        print(f"no feedback yet at {FEEDBACK_PATH.relative_to(REPO_ROOT)}")
        return True
    rows = [json.loads(line) for line in
            FEEDBACK_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest = {}
    for r in rows:  # last word per answer wins
        latest[r.get("answer_id", r.get("query", ""))] = r
    final = list(latest.values())
    ups = [r for r in final if r["rating"] == "up"]
    downs = [r for r in final if r["rating"] == "down"]
    print(f"feedback: {len(rows)} events, {len(final)} rated answers "
          f"({len(ups)} up, {len(downs)} down)")
    if not downs:
        print("no disputed answers.")
        return True
    by_reason = {}
    for r in downs:
        by_reason.setdefault(r.get("reason") or "(no reason given)", []).append(r)
    print("\ndisputed answers — each is a candidate gold row:")
    for reason, group in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {reason}  ({len(group)})")
        for r in group:
            print(f"    exists={r.get('exists', -1):<6.2f} verdict={r.get('verdict','')[:26]:<26} "
                  f"top={r.get('top_block','')[:30]:<30} {r.get('query','')[:44]!r}")
    print("\nnext: add the ones you agree with to eval_gold.json (build_gold.py "
          "HAND_ANSWERABLE / PARTIALS), then re-run --live to see the effect.")
    return True


def bm25_rank(query, expected_block):
    """1-based BM25 rank of expected_block over the full corpus (None if absent)."""
    from jev_search import _bm25_scores

    scored = _bm25_scores(query)
    scored.sort(key=lambda pair: pair[1], reverse=True)
    for i, (b, _) in enumerate(scored, 1):
        if b["block_id"] == expected_block:
            return i
    return None  # pragma: no cover - every expected block exists


def local_only():
    gold = load_gold()
    retrievable = [g for g in gold if g["expected_block"] is not None]
    print(f"local recall: BM25 rank of expected block over full corpus (k={SHORTLIST})")
    print(f"{'id':<4} {'rank':<6} {'hit?':<6} {'expected block':<58} query")
    hits = 0
    misses = []
    for g in retrievable:
        r = bm25_rank(g["query"], g["expected_block"])
        hit = r is not None and r <= SHORTLIST
        hits += hit
        if not hit:
            misses.append(g)
        print(f"{g['id']:<4} {str(r):<6} {'HIT' if hit else 'MISS':<6} "
              f"{g['expected_block']:<58} {g['query']}")
    print(f"\nlocal recall: {hits}/{len(retrievable)} in top-{SHORTLIST}")
    if misses:
        print("MISSES (query -> expected block):")
        for g in misses:
            print(f"  {g['id']}: {g['query']!r} -> {g['expected_block']}")
    else:
        print("no misses — every expected block reaches the Jev shortlist.")
    print("live calls used: 0")
    if hits < RECALL_FLOOR:
        print(f"FAIL: recall {hits} below floor {RECALL_FLOOR} — retrieval regressed.")
        return False
    print(f"recall floor OK ({hits} >= {RECALL_FLOOR}).")
    return True


def live(limit=None, save=None):
    gold = load_gold()
    if limit:
        gold = gold[:limit]
    print(f"live sweep: {len(gold)} queries, 1 system_one call each "
          f"(budget: {len(gold)} calls)")
    print(f"{'id':<4} {'exists':<7} {'fully':<7} {'verdict':<34} "
          f"{'expected':<34} {'top-block':<40} {'v?':<3} {'rank'}")
    verdict_hits = 0
    verdict_total = 0
    abstain_hits = 0
    abstain_total = 0
    top1 = top3 = rank_total = 0
    verdict_misses = []
    errors = []
    rows = []  # raw (exists, fully) per query, so thresholds can be swept offline
    for g in gold:
        try:
            r = find(g["query"])
        except Exception as e:  # transient API error: one retry, then record
            try:
                r = find(g["query"])
            except Exception as e2:
                errors.append((g, f"{type(e2).__name__}: {e2}"))
                print(f"{g['id']:<4} ERROR {type(e2).__name__}: {e2}")
                verdict_misses.append((g, None))
                continue
        graded = g["expected_verdict"] is not None
        vok = graded and r["verdict"] == g["expected_verdict"]
        verdict_hits += vok
        verdict_total += graded
        if g["kind"] == "unanswerable":
            abstain_total += 1
            abstain_hits += r["verdict"] == "not in this document"
        top = r["ranked"][0]
        mark = "-"
        if g["expected_block"] is not None:
            rank_total += 1
            if top["block_id"] == g["expected_block"]:
                top1 += 1
                mark = "top1"
            elif any(x["block_id"] == g["expected_block"] for x in r["ranked"][:3]):
                top3 += 1
                mark = "top3"
            else:
                mark = "MISS"
        rows.append({"id": g["id"], "kind": g["kind"], "query": g["query"],
                     "graded": graded,
                     "exists": r["exists"], "fully": r["fully"],
                     "expected_verdict": g["expected_verdict"],
                     "top_block": top["block_id"]})
        if graded and not vok:
            verdict_misses.append((g, r))
        print(f"{g['id']:<4} {r['exists']:<7.3f} {r['fully']:<7.3f} "
              f"{r['verdict']:<34} {str(g['expected_verdict'] or '(rank only)'):<34} "
              f"{top['block_id']:<40} {('OK' if vok else 'MISS') if graded else '-':<4} [{mark}]")
    vacc = verdict_hits / verdict_total if verdict_total else 1.0
    abst = abstain_hits / abstain_total if abstain_total else 1.0
    print(f"\nverdict accuracy: {verdict_hits}/{verdict_total} = {vacc:.1%} "
          f"(goal >= {GOAL_VERDICT:.0%}; {len(gold) - verdict_total} rows are rank-only)")
    print(f"abstention: {abstain_hits}/{abstain_total} unanswerables absent "
          f"(goal = {GOAL_ABSTAIN:.0%})")
    if rank_total:
        print(f"rank: top-1 {top1}/{rank_total}, top-3 {top1 + top3}/{rank_total} "
              f"(track only — FP5: do not chase top-1)")
    goal = vacc >= GOAL_VERDICT and abst >= GOAL_ABSTAIN
    print(f"GOAL: {'PASS' if goal else 'FAIL'}")
    if verdict_misses:
        print("VERDICT MISSES:")
        for g, r in verdict_misses:
            if r is None:
                print(f"  {g['id']}: {g['query']!r} ERROR (no result)")
                continue
            print(f"  {g['id']}: {g['query']!r} got {r['verdict']!r} "
                  f"(exists {r['exists']:.3f}, fully {r['fully']:.3f}), "
                  f"want {g['expected_verdict']!r}, top {r['ranked'][0]['block_id']}")
    if save:
        Path(save).write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        print(f"saved {len(rows)} rows to {save} (sweep thresholds offline, no API calls)")
    print(f"live calls used: {len(gold)} (+1 per retried ERROR)")
    if errors:
        print(f"query errors (retried once, still failing): {len(errors)}")
    return goal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--save", default=None, help="write raw exists/fully rows to this JSON path")
    ap.add_argument("--feedback", action="store_true", help="summarise collected user ratings")
    args = ap.parse_args()
    if args.feedback:
        sys.exit(0 if review_feedback() else 1)
    ok = live(args.limit, args.save) if args.live else local_only()
    print()
    if not run_audit() or not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
