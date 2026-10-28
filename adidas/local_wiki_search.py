#!/usr/bin/env python3
"""local_wiki_search.py — Local Wiki full-text search (jieba), read-only over source KB.

Scans SOURCE_KB_ROOT content dirs (product/科技/系列), scores with jieba keywords
+ title/slug boost. No Bun / PGlite / embedding dependency — same as medical.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

import jieba

from config import SOURCE_KB_ROOT, ALL_CONTENT_DIRS

_META_SLUGS = {"tag_taxonomy", "log", "schema", "tag-taxonomy", "关系索引"}
_NOISE_PATTERNS = ("/index", "_uploads/", "articles/", "_meta/", "_proposals/", "_backups/")

# In-memory corpus: slug -> {title, body, path, mtime}
_CORPUS: Dict[str, dict] = {}
_CORPUS_BUILT_AT = 0.0
_CORPUS_TTL = 60.0


def _strip_fm(text: str) -> Tuple[str, str]:
    title = ""
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = parts[1]
            body = parts[2]
            m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", fm, re.M)
            if m:
                title = m.group(1).strip()
    return title, body


def _iter_md_files() -> List[Path]:
    root = Path(SOURCE_KB_ROOT)
    out: List[Path] = []
    for d in ALL_CONTENT_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for md in base.rglob("*.md"):
            if md.name == "index.md":
                continue
            rel = str(md.relative_to(root)).replace("\\", "/")
            if any(p in rel for p in _NOISE_PATTERNS):
                continue
            out.append(md)
    return out


def rebuild_corpus(force: bool = False) -> int:
    global _CORPUS, _CORPUS_BUILT_AT
    now = time.time()
    if not force and _CORPUS and (now - _CORPUS_BUILT_AT) < _CORPUS_TTL:
        return len(_CORPUS)

    corpus: Dict[str, dict] = {}
    root = Path(SOURCE_KB_ROOT)
    for md in _iter_md_files():
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        slug = str(md.relative_to(root).with_suffix("")).replace("\\", "/")
        if slug in _META_SLUGS or slug.startswith(("tag_taxonomy", "log", "schema")):
            continue
        title, body = _strip_fm(text)
        if not title:
            title = md.stem
        corpus[slug] = {
            "slug": slug,
            "title": title,
            "body": body,
            "path": str(md),
            "mtime": md.stat().st_mtime,
        }

    # Overlay pages override source
    try:
        from overlay import ACCEPTED_DIR, list_accepted_slugs, read_page
        for slug in list_accepted_slugs():
            text = read_page(slug)
            if not text:
                continue
            title, body = _strip_fm(text)
            if not title:
                title = slug.split("/")[-1]
            corpus[slug] = {
                "slug": slug,
                "title": title,
                "body": body,
                "path": str(Path(ACCEPTED_DIR) / f"{slug}.md"),
                "mtime": time.time(),
            }
    except Exception:  # noqa: BLE001
        pass

    _CORPUS = corpus
    _CORPUS_BUILT_AT = now
    return len(_CORPUS)


def get(slug: str) -> str:
    """Return full markdown (frontmatter stripped) for slug, or empty string.

    Prefers adidas `_accepted/` overlay over read-only SOURCE_KB_ROOT.
    """
    if not slug:
        return ""
    slug = slug.strip().lstrip("/")
    if slug.endswith(".md"):
        slug = slug[:-3]
    try:
        from overlay import read_page
        text = read_page(slug)
    except Exception:  # noqa: BLE001
        path = Path(SOURCE_KB_ROOT) / f"{slug}.md"
        text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
    if not text:
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return text.strip()


def _extract_terms(question: str) -> List[str]:
    noise = {
        "的", "是", "什么", "怎么", "为什么", "哪些", "如何", "吗", "呢", "了",
        "有", "在", "和", "与", "用", "请", "可以", "能", "告诉", "我", "你",
        "这个", "那个", "一下", "区别", "不同", "比较", "介绍", "说明",
        "请问", "有没有", "能否", "帮我", "我想", "想知道", "了解", "推荐",
        "适合", "哪个", "哪种", "哪款", "哪里", "怎样", "什么样", "库里",
        "系列", "科技", "产品", "用了",
    }
    en_words = re.findall(r"[A-Za-z0-9+-]+", question)
    clean = question
    for n in sorted(noise, key=len, reverse=True):
        clean = clean.replace(n, " ")
    cn_words = []
    for w in jieba.cut(clean):
        w = w.strip()
        if len(w) >= 2 and re.search(r"[\u4e00-\u9fff]", w):
            cn_words.append(w)
    bigrams = [cn_words[i] + cn_words[i + 1] for i in range(len(cn_words) - 1)]
    terms: List[str] = []
    seen = set()
    for w in en_words + cn_words + bigrams + [question.strip()]:
        if len(w) < 2:
            continue
        key = w.lower()
        if key not in seen:
            seen.add(key)
            terms.append(w)
    return terms[:12] if terms else [question]


def search(question: str, limit: int = 10) -> List[dict]:
    """Return list of {slug, score, content} sorted by score desc."""
    rebuild_corpus()
    if not _CORPUS:
        rebuild_corpus(force=True)

    terms = _extract_terms(question)
    q_lower = question.lower()
    scored: List[Tuple[float, dict]] = []

    for slug, entry in _CORPUS.items():
        title = entry["title"]
        body = entry["body"]
        hay_title = title.lower()
        hay_slug = slug.lower()
        hay_body = body.lower()
        score = 0.0

        if q_lower and q_lower in hay_title:
            score += 25.0
        if q_lower and q_lower in hay_slug:
            score += 18.0
        if q_lower and q_lower in hay_body:
            score += 8.0

        for term in terms:
            tl = term.lower()
            if tl in hay_title:
                score += 12.0
            if tl in hay_slug:
                score += 9.0
            if tl in hay_body:
                count = hay_body.count(tl)
                score += min(6.0, 2.0 + count * 0.5)

        # Prefer concept pages for tech/series queries
        if slug.startswith(("科技/", "系列/")):
            score *= 1.05
        if re.search(r"科技|系列|用了|搭载", question):
            if slug.startswith(("科技/", "系列/")):
                score *= 1.15

        if score <= 0:
            continue

        snippet = body.strip().replace("\n", " ")[:240]
        scored.append((score, {"slug": slug, "score": score, "content": snippet}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def sync() -> str:
    n = rebuild_corpus(force=True)
    msg = f"local wiki index rebuilt: {n} pages"
    print(f"[sync] {msg}")
    return msg


if __name__ == "__main__":
    sync()
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "boost 科技"
    for r in search(q, limit=5):
        print(f"[{r['score']:.1f}] {r['slug']} -- {r['content'][:80]}")
