"""Build corpus.json: fetch llms.txt index, fetch each page .md, split by ATX headings.

Stdlib only (urllib). No LLM/embedding deps. Deterministic block IDs.
Usage: python3 build_corpus.py [--check]
"""
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

LLMS_TXT = "https://docs.potpie.ai/llms.txt"
OUT = Path(__file__).resolve().parent / "corpus.json"
UA = {"User-Agent": "potpie-doc-parser/1.0"}

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
CLOSE_HASH_RE = re.compile(r"\s+#+\s*$")


def fetch(url, tries=3):
    last = None
    for _ in range(tries):  # transient read timeouts over 111 pages
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
    raise last


def slug_for(url):
    path = urlparse(url).path.strip("/").removesuffix(".md")
    return path.replace("/", "-") or "index"


def split_blocks(md, page_url, page_title, slug):
    """Split markdown into heading blocks. Never splits inside ``` fences."""
    segs, cur, in_fence = [], None, False
    for line in md.split("\n"):
        m = None
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            m = HEADING_RE.match(line)
        if m:
            if cur and "\n".join(cur[2]).strip():
                segs.append(cur)
            level = len(m.group(1))
            title = CLOSE_HASH_RE.sub("", m.group(2)).strip()
            cur = [level, title, [line]]
        else:
            if cur is None:
                cur = [0, "", []]
            cur[2].append(line)
    if cur and "\n".join(cur[2]).strip():
        segs.append(cur)

    real_title = next((s[1] for s in segs if s[0] == 1), page_title)
    blocks, stack = [], []
    for level, title, lines in segs:
        if level == 0:
            stack = [real_title]
        else:
            stack = stack[: level - 1] + [title]
        blocks.append(
            {
                "block_id": f"{slug}-H{len(blocks):03d}",
                "page_url": page_url,
                "page_title": real_title,
                "heading_path": list(stack),
                "level": level,
                "text": "\n".join(lines).strip("\n"),
            }
        )
    return blocks, real_title


def drop_boilerplate(blocks, page_count):
    """Drop text repeated on most pages (nav preambles, doc-index banners).

    Such a block is identical everywhere, so it can never be the answer to a
    question — it only burns shortlist slots and state budget.
    """
    counts = {}
    for b in blocks:
        counts[b["text"]] = counts.get(b["text"], 0) + 1
    boiler = {t for t, n in counts.items() if n > page_count / 2}
    return [b for b in blocks if b["text"] not in boiler], len(boiler)


def main():
    check = "--check" in sys.argv
    index = fetch(LLMS_TXT)
    seen, links = set(), []
    for title, url in LINK_RE.findall(index):
        url = url.strip()
        if not url.endswith(".md"):
            url += ".md"  # append only if missing (index already ends in .md)
        if url not in seen:
            seen.add(url)
            links.append((title.strip(), url))

    pages, blocks = [], []
    for title, url in links:
        md = fetch(url)
        slug = slug_for(url)
        page_blocks, real_title = split_blocks(md, url, title, slug)
        pages.append(
            {"url": url, "title": real_title, "slug": slug,
             "block_count": len(page_blocks)}
        )
        blocks.extend(page_blocks)
        print(f"{slug}: {len(page_blocks)} blocks")

    blocks, n_boiler = drop_boilerplate(blocks, len(pages))
    if n_boiler:
        print(f"dropped {n_boiler} boilerplate text(s) repeated across pages")
    kept = {}
    for b in blocks:
        kept[b["page_url"]] = kept.get(b["page_url"], 0) + 1
    for pg in pages:  # recount after the filter so the metadata stays true
        pg["block_count"] = kept.get(pg["url"], 0)

    corpus = {
        "pages": pages,
        "blocks": blocks,
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "llms.txt",
    }
    OUT.write_text(json.dumps(corpus, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"pages={len(pages)} blocks={len(blocks)}")

    if check:
        by_page = {}
        for b in blocks:
            by_page.setdefault(b["page_url"], []).append(b["block_id"])
        big_page = max(by_page.items(), key=lambda kv: len(kv[1]))
        print(f"largest page: {big_page[0]} ({len(big_page[1])} blocks)")
        # Search sends only the top-SHORTLIST BM25 blocks to a Choice, so the
        # 255-label cap binds on the shortlist, not on any page.
        missing = [b["block_id"] for b in blocks if not b["text"].strip()]
        if missing:
            raise SystemExit(f"FAIL: {len(missing)} blocks have empty text")
        ids = [b["block_id"] for b in blocks]
        if len(ids) != len(set(ids)):
            raise SystemExit("FAIL: duplicate block_ids")
        print("check: OK")


if __name__ == "__main__":
    main()
