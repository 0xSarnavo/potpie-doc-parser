# 01-01 Summary: Ingest TypeSafe docs to heading blocks + windows

Built `backend/corpus/build_corpus.py` (153 lines, stdlib `urllib` only) that fetches
`llms.txt` (111 unique page URLs, all already `.md`-suffixed — appends `.md` only if
missing), fetches each page, splits on ATX headings without splitting inside ``` fences,
and writes `corpus.json` with `{pages, blocks, windows, built_at, source}`.
Block IDs are deterministic per-page zero-padded slugs (`introduction-H004`);
full-path slugs (`sdk-python-api-clients-async-models-H001`) keep colliding basenames
(async/sync `models.md`, python/js `changelog.md`) unique. Windows cover the global
block list at max 200 with 20 overlap; `--check` fails on uncovered blocks or
windows >200 and prints largest page/window sizes.

Verify results:
- Task 1: `111 pages, 998 blocks` — every block has `block_id` + non-empty verbatim
  `text` + `heading_path`. Largest page 44 blocks (APIPromise), far under the 255 cap.
- Task 2: `--check` → `check: OK`, 6 windows, max size 200, W0/W1 overlap exactly 20.
- Plan verification: two consecutive reruns byte-identical on IDs, texts, and windows
  (deterministic); 3/3 spot-checked blocks (`introduction-H000`,
  `cookbooks-semantic_find-H003` code-fence block, `APIPromise-H001`) are exact
  substrings of their live `.md` sources.
- Deviation [Rule 3]: one transient SSL read timeout mid-crawl → added 3-attempt retry
  in `fetch()`; no other changes. No git repo in working dir, so no per-task commits.

Skipped per ponytail: `requests` dep (stdlib `urllib` covers it); per-page windowing
(global windows already guarantee ≤200 < 255); separate config/extra files (one script + one JSON).
