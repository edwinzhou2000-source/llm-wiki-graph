#!/usr/bin/env python3
"""wiki_graph_extract.py — Derive a typed graph from adidas product KB frontmatter.

Unlike the medical replica (一事一页 edge pages with `graph:` frontmatter),
adidas edges are THIN and DERIVABLE: they are typed frontmatter FIELDS on the
product/科技/系列 pages, not separate fact pages. This module reads the source
KB (read-only, never writes) and deterministically derives:

    IN_SERIES        Product -> Series       (product.series)
    USES_TECH        Product -> Tech         (product.tags 科技/* + attributes∩科技)
    IN_CATEGORY      Product -> Category     (file top-level directory)
    HAS_TYPE         Product -> ProductType  (product.type)
    SERIES_USES_TECH Series  -> Tech         (系列 page 核心技术 section)

No LLM, no fuzzy matching — only explicit frontmatter fields and exact
case-insensitive tech-slug matches. The prose stays the source of truth; this
graph is a derived recall index pointing back to source pages via props['slug'].
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))

from config import SOURCE_KB_ROOT, PRODUCT_DIRS, CONCEPT_DIRS, TECH_CONCEPT_DIR, SERIES_CONCEPT_DIR  # noqa: E402

# Closed set of edge types (adidas) — machine contract, not per-page invention
RELATIONS = ("IN_SERIES", "USES_TECH", "IN_CATEGORY", "HAS_TYPE", "SERIES_USES_TECH")

# Product category dirs == node labels' Category values (top-level dir names)
CATEGORY_DIRS = tuple(PRODUCT_DIRS)


def _parse_fm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _slug(path: Path) -> str:
    return str(path.relative_to(SOURCE_KB_ROOT).with_suffix("")).replace("\\", "/")


def _iter_md(dirs: List[str]) -> Iterable[Path]:
    seen: Set[Path] = set()
    for d in dirs:
        base = Path(SOURCE_KB_ROOT) / d
        if not base.is_dir():
            continue
        for md in base.rglob("*.md"):
            if md.name == "index.md" or md in seen:
                continue
            seen.add(md)
            yield md


def _norm_series(name: str) -> str:
    """Normalize a series name for matching: strip 系列 suffix + whitespace."""
    s = re.sub(r"系列$", "", (name or "").strip())
    s = re.sub(r"\s+", "", s)
    return s.lower()


def _build_tech_index() -> Dict[str, str]:
    """Map canonical tech slug stem -> wiki slug (科技/*). Also lowercase aliases."""
    index: Dict[str, str] = {}
    if not TECH_CONCEPT_DIR:
        return index
    base = Path(SOURCE_KB_ROOT) / TECH_CONCEPT_DIR
    if not base.is_dir():
        return index
    for md in base.rglob("*.md"):
        if md.name == "index.md":
            continue
        stem = md.stem
        slug = _slug(md)
        index[stem] = slug
        index[stem.lower()] = slug
        # title (e.g. "BOOST 爆米花科技") as an alias for attribute matching
        fm = _parse_fm(md)
        title = (fm.get("title") or "").strip()
        if title:
            index.setdefault(title, slug)
            index.setdefault(title.lower(), slug)
    return index


def _build_series_page_index() -> Dict[str, str]:
    """Map normalized series name -> series page slug (系列/*)."""
    index: Dict[str, str] = {}
    if not SERIES_CONCEPT_DIR:
        return index
    base = Path(SOURCE_KB_ROOT) / SERIES_CONCEPT_DIR
    if not base.is_dir():
        return index
    for md in base.rglob("*.md"):
        if md.name == "index.md":
            continue
        fm = _parse_fm(md)
        title = (fm.get("title") or md.stem).strip()
        index.setdefault(_norm_series(title), _slug(md))
        index.setdefault(_norm_series(md.stem), _slug(md))
    return index


def _tech_names_from_tags(tags: Any) -> List[str]:
    """Extract tech slug stems from `tags` entries with 科技/ prefix."""
    out: List[str] = []
    if not tags:
        return out
    if isinstance(tags, str):
        tags = [tags]
    for t in tags:
        t = str(t).strip()
        if t.startswith("科技/"):
            name = t[len("科技/"):].strip()
            if name:
                out.append(name)
    return out


def _extract_article_no(fm: dict) -> str:
    """Best-effort article number (货号) — from title or description, no fuzzy."""
    desc = str(fm.get("description") or "")
    m = re.search(r"\b([A-Z]{1,3}\d{4,6})\b", desc)
    if m:
        return m.group(1)
    return ""


def extract() -> Dict[str, Any]:
    tech_index = _build_tech_index()
    series_page_index = _build_series_page_index()

    nodes: Dict[Tuple[str, str], dict] = {}
    edges: Dict[Tuple, dict] = {}

    def add_node(label, name, **props):
        key = (label, name)
        existing = nodes.get(key, {"label": label, "name": name, "props": {}})
        existing["props"].update({k: v for k, v in props.items() if v})
        nodes[key] = existing

    def add_edge(rel, a_label, a, b_label, b, source=""):
        key = (rel, a_label, a, b_label, b)
        existing = edges.get(key)
        if existing:
            if source and source not in existing["sources"]:
                existing["sources"].append(source)
            return
        edges[key] = {
            "type": rel,
            "from_label": a_label,
            "from": a,
            "to_label": b_label,
            "to": b,
            "sources": [source] if source else [],
        }

    # ── 1. Product pages ──
    for path in _iter_md(PRODUCT_DIRS):
        fm = _parse_fm(path)
        slug = _slug(path)
        name = path.stem  # canonical Product name = filename slug
        category = slug.split("/", 1)[0]  # top-level dir = Category
        ptype = str(fm.get("type") or "").strip()
        title = str(fm.get("title") or name).strip()
        brand = str(fm.get("brand") or "").strip()
        series_vals = fm.get("series") or []
        if isinstance(series_vals, str):
            series_vals = [series_vals]
        attrs = fm.get("attributes") or []
        if isinstance(attrs, str):
            attrs = [attrs]

        add_node("Product", name, title=title, slug=slug, brand=brand,
                 product_type=ptype, description=str(fm.get("description") or "").strip(),
                 article_no=_extract_article_no(fm))

        if category in CATEGORY_DIRS:
            add_node("Category", category, slug=category)
            add_edge("IN_CATEGORY", "Product", name, "Category", category, source=slug)

        if ptype:
            add_node("ProductType", ptype)
            add_edge("HAS_TYPE", "Product", name, "ProductType", ptype, source=slug)

        seen_series = set()
        for s in series_vals:
            s = str(s).strip()
            if not s or s in seen_series:
                continue
            seen_series.add(s)
            add_node("Series", s, title=s,
                     slug=series_page_index.get(_norm_series(s), ""))
            add_edge("IN_SERIES", "Product", name, "Series", s, source=slug)

        # USES_TECH: primary = tags 科技/*; secondary = attributes exact-match tech
        seen_tech = set()
        for t in _tech_names_from_tags(fm.get("tags")):
            if t not in seen_tech and t in tech_index:
                seen_tech.add(t)
                add_node("Tech", t, title="", slug=tech_index[t])
                add_edge("USES_TECH", "Product", name, "Tech", t, source=slug)
        for a in attrs:
            a = str(a).strip()
            if not a:
                continue
            canon = tech_index.get(a) or tech_index.get(a.lower())
            if canon and a.lower() not in seen_tech and a not in seen_tech:
                # ensure canonical tech name (stem) used as node name
                stem = canon.rsplit("/", 1)[-1]
                seen_tech.add(stem.lower())
                add_node("Tech", stem, title=a, slug=canon)
                add_edge("USES_TECH", "Product", name, "Tech", stem, source=slug)

    # ── 2. Tech (科技) entity pages — fill titles for already-seen Tech nodes ──
    if TECH_CONCEPT_DIR:
        for path in _iter_md([TECH_CONCEPT_DIR]):
            fm = _parse_fm(path)
            stem = path.stem
            title = str(fm.get("title") or "").strip()
            add_node("Tech", stem, title=title, slug=_slug(path),
                     description=str(fm.get("description") or "").strip())

    # ── 3. Series (系列) pages — SERIES_USES_TECH from 核心技术 section ──
    if SERIES_CONCEPT_DIR:
        for path in _iter_md([SERIES_CONCEPT_DIR]):
            fm = _parse_fm(path)
            title = str(fm.get("title") or path.stem).strip()
            slug = _slug(path)
            # Series node canonical name = the title; also keep a normalized alias
            # Match the Series node created from product.series by normalized name.
            norm = _norm_series(title)
            matched = False
            for (lab, nm) in list(nodes.keys()):
                if lab == "Series" and _norm_series(nm) == norm:
                    add_node("Series", nm, title=title, slug=slug)
                    matched = True
                    break
            if not matched:
                add_node("Series", title, title=title, slug=slug)
            # core tech links: 科技/xxx wikilinks in body
            body = path.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"\[\[科技/([^\]|]+)", body):
                tech_stem = m.group(1).strip()
                if tech_stem in tech_index:
                    series_name = title
                    # resolve to the canonical Series node name actually used
                    for (lab, nm) in list(nodes.keys()):
                        if lab == "Series" and _norm_series(nm) == norm:
                            series_name = nm
                            break
                    add_edge("SERIES_USES_TECH", "Series", series_name, "Tech",
                             tech_stem, source=slug)

    return {
        "nodes": sorted(
            nodes.values(), key=lambda n: (n["label"], n["name"])
        ),
        "edges": sorted(
            edges.values(), key=lambda e: (e["type"], e["from"], e["to"])
        ),
    }


def build_alias_index(extracted: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Map mention (alias / display form) -> canonical node name."""
    data = extracted or extract()
    index: Dict[str, str] = {}
    for n in data["nodes"]:
        name = n["name"]
        index.setdefault(name, name)
        index.setdefault(name.lower(), name)
        title = (n.get("props") or {}).get("title") or ""
        if title:
            index.setdefault(title, name)
            index.setdefault(title.lower(), name)
        if n["label"] == "Series":
            # 舒适通勤系列 -> 舒适通勤系列 (and stripped form)
            norm = _norm_series(name)
            if norm:
                index.setdefault(norm, name)
    return index


if __name__ == "__main__":
    from collections import Counter

    data = extract()
    print(f"nodes={len(data['nodes'])} edges={len(data['edges'])}")
    print("labels:", dict(Counter(n["label"] for n in data["nodes"])))
    print("rels:", dict(Counter(e["type"] for e in data["edges"])))
    # sanity: a few USES_TECH and IN_SERIES examples
    for e in [x for x in data["edges"] if x["type"] == "USES_TECH"][:5]:
        print("USES_TECH:", e["from"], "->", e["to"])
    for e in [x for x in data["edges"] if x["type"] == "IN_SERIES"][:5]:
        print("IN_SERIES:", e["from"], "->", e["to"])
