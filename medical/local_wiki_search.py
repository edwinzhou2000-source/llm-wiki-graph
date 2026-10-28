#!/usr/bin/env python3
"""Local Wiki full-text search — replaces gbrain for the Graph replica.

Scans ALL_CONTENT_DIRS Markdown, scores with jieba keywords + title/slug boost.
No Bun / PGlite / embedding dependency.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import jieba

from config import ALL_CONTENT_DIRS, KB_ROOT

_META_SLUGS = {"tag_taxonomy", "log", "schema", "tag-taxonomy", "关系索引"}
_NOISE_PATTERNS = ("/index", "_uploads/", "articles/", "_meta/", "_proposals/", "_backups/")

# In-memory corpus: slug -> {title, body, path, mtime}
_CORPUS: Dict[str, dict] = {}
_CORPUS_BUILT_AT = 0.0
_CORPUS_TTL = 60.0  # rebuild at most every 60s when called


def _strip_fm(text: str) -> Tuple[str, str]:
    """Return (title_guess, body_without_frontmatter)."""
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
    root = Path(KB_ROOT)
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
    # Also include root 关系索引.md? skip — meta
    return out


def rebuild_corpus(force: bool = False) -> int:
    global _CORPUS, _CORPUS_BUILT_AT
    now = time.time()
    if not force and _CORPUS and (now - _CORPUS_BUILT_AT) < _CORPUS_TTL:
        return len(_CORPUS)

    corpus: Dict[str, dict] = {}
    root = Path(KB_ROOT)
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
    _CORPUS = corpus
    _CORPUS_BUILT_AT = now
    return len(_CORPUS)


def get(slug: str) -> str:
    """Return full markdown (with frontmatter) for slug, or empty string."""
    if not slug:
        return ""
    # normalize
    slug = slug.strip().lstrip("/")
    if slug.endswith(".md"):
        slug = slug[:-3]
    path = Path(KB_ROOT) / f"{slug}.md"
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
    # try rebuild once
    rebuild_corpus(force=True)
    entry = _CORPUS.get(slug)
    if entry and Path(entry["path"]).is_file():
        try:
            return Path(entry["path"]).read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def _extract_terms(question: str) -> List[str]:
    noise = {
        "的", "是", "什么", "怎么", "为什么", "哪些", "如何", "吗", "呢", "了",
        "有", "在", "和", "与", "用", "请", "可以", "能", "告诉", "我", "你",
        "这个", "那个", "一下", "区别", "不同", "比较", "介绍", "说明",
        "请问", "有没有", "能否", "帮我", "我想", "想知道", "了解", "推荐",
        "适合", "哪个", "哪种", "哪款", "哪里", "怎样", "什么样", "库里",
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

        # Full question phrase
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
            # body frequency (capped)
            if tl in hay_body:
                count = hay_body.count(tl)
                score += min(6.0, 2.0 + count * 0.5)

        # Prefer product / concept pages slightly for open product questions
        if slug.startswith(("处方药/", "OTC药品/", "医疗器械/", "产品系列/", "技术平台/")):
            score *= 1.05
        # Soft-prefer fact pages when query looks clinical
        if re.search(r"禁忌|相互作用|过敏|病例|患者", question):
            if slug.startswith(("临床事实/", "用药安全/", "临床病例/", "成分/", "疾病/")):
                score *= 1.15

        if score <= 0:
            continue

        snippet = body.strip().replace("\n", " ")[:240]
        scored.append((score, {"slug": slug, "score": score, "content": snippet}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def sync() -> str:
    """Rebuild corpus (replaces gbrain import)."""
    n = rebuild_corpus(force=True)
    msg = f"local wiki index rebuilt: {n} pages"
    print(f"[sync] {msg}")
    return msg


if __name__ == "__main__":
    sync()
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "缓释降糖"
    for r in search(q, limit=5):
        print(f"[{r['score']:.1f}] {r['slug']} -- {r['content'][:80]}")
