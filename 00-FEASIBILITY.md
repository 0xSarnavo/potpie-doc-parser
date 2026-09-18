# Jev-Only Doc Parser — Feasibility Cross-Check (no LLM)

**Scope (corrected):** TypeSafe's Jev is the **engine**; the **corpus** is the
Potpie docs (`docs.potpie.ai/llms.txt`, 46 pages / 349 blocks). The TypeSafe
cookbooks cited below are evidence that the *method* works — they are not the
thing being indexed.

**Verdict: POSSIBLE — extractive only. No generated prose. Proven by official TypeSafe cookbooks.**

User constraints locked:
- Jev only, zero LLM (no OpenAI/Anthropic/generation deps anywhere)
- No full generated text — verbatim extracts + marks are the output
- Parse docs end-to-end down to heading/subheading/block level

## Why it works (evidence)

| Claim | Proof |
|---|---|
| Jev can point to the exact answering line without generating text | `cookbooks/semantic_find`: `Choice` over 218 tagged line IDs (`L000…L217`) returns per-line probabilities; top line `0.95` for "who owns the code I upload?" |
| Jev can abstain when docs have no answer (ranking alone can't) | Same cookbook: companion `Noul` `exists` check in the SAME request. Arbitration query: rank `0.86` but `exists 0.14` → "not in this document". Thresholds `FOUND 0.7 / ABSENT 0.35` |
| Jev reranks keyword shortlists accurately + cheaply | `cookbooks/rerank_typesafe`: BM25 top-30 → one `Noul` per pair. Top-1 `5%→18%`, top-10 `38%→62%`. 1,200 calls = `$0.0645`. Pattern for large corpus |
| Two-pass windowing beats the 255-option cap | `semantic_find` Step 2: "A `Choice` accepts up to 255 options… Past that, search in two passes: one Choice picks a window, second ranks lines inside it" |
| Block-type classification (heading/list/code/callout) is a solved Jev task | `cookbooks/autoformat` (structure recovery): one request stitches lines, one classifies every block with companion questions |
| Parallel questions cost ~one | `introduction`: "Every question is evaluated in parallel… Adding questions barely changes response time." So `where + exists + section-router` ride in one call |
| Docs are machine-ingestible | `llms.txt` index + every Mintlify page has a `.md` variant. No scraping needed |

## What Jev CANNOT do (boundaries — no LLM to cover them)

1. **No prose answers.** Output = copied source spans + scores + breadcrumbs. "Summarize this page" is out of scope by design.
2. **Text only.** Jev takes strings/JSON/arrays. Images/video in docs are ignored (Potpie docs carry screenshots, not load-bearing diagrams).
3. **Choice ≤ 255 options per question.** Design must window (two-pass) or BM25-shortlist first. Never one giant Choice over the whole corpus.
4. **Calibration is aggregate, not per-answer guarantee.** Thresholds (`FOUND 0.7 / ABSENT 0.30`) are tuned on our own gold set; scores vary run to run near the boundary.
5. **Key server-side.** `TYPESAFE_API_KEY` never ships to the browser; all Jev calls go through our backend.

## Architecture (Jev-only, extractive)

```
fetch llms.txt → fetch *.md → split by heading → tag blocks H001/P002/…
        │
query → section-router Choice (which page?) ─┐
        │                                     ├─ ONE system_one call
        BM25 shortlist (top 30, in code)      │
        → Choice where (line IDs) + Noul exists ┘
        │
code: verdict (answered fully≥0.7 / partial / absent exists<0.30)
   → render verbatim blocks + heading breadcrumb + relevance bars + confidence
```

- One path only: BM25 shortlists 30 blocks, then a single `Choice where + Noul exists + Noul fully + Choice router` call.
- The shortlist is always well under the 255-label `Choice` cap, so the two-pass window fallback was never reachable and has been removed.
- Structure recovery (headings/subheadings) runs at ingest time via block-classify questions, stored in `corpus.json` — not per query.

## Requirements (IDs used by plans)

- `DOC-01` Ingest + parse docs to heading/subheading/block with stable IDs
- `DOC-02` Jev-only search: router + rank + exists gate, no LLM dependency
- `DOC-03` Website rendering verbatim extracts with marks (scores, bars, verdict, breadcrumbs)
- `DOC-04` Verification: cookbook-parity tests + no-LLM audit + abstention tests

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Corpus exceeds 255 Choice options | BM25 pre-filter caps the shortlist at 30, so the cap is structurally unreachable |
| Thresholds misfire on our docs | `eval.py --live --save` dumps raw scores so thresholds sweep offline; 33 gold queries; thresholds in config, not hardcoded |
| Someone adds an LLM "to improve wording" | `DOC-02` verify step greps deps + code for `openai/anthropic/transformers/sentence` and fails if found |
| API key leak | Backend-only calls; frontend never sees key; plan 03 verify checks bundle |
