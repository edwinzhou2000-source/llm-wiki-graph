"""graph_recall.py — Neo4j Cypher recall for the adidas product KB replica.

图只做召回：问题落在类型化边切片 → Cypher → 实体名 + 结构化事实。
答案仍由源 KB 原文（产品/科技/系列 Markdown）产出。实体 → slug 映射在
ENTITY_INDEXES（由 extract 派生）里。

与 medical 的差异：边从 frontmatter 派生（非一事一页）；无 clinical/cross 层；
边类型为 IN_SERIES / USES_TECH / IN_CATEGORY / HAS_TYPE / SERIES_USES_TECH。
Cypher 使用参数绑定（不用 f-string 拼实体名）。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

KB_ROOT = Path(__file__).resolve().parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))

from config import SOURCE_KB_ROOT  # noqa: E402
from graph.wiki_graph_extract import extract, _norm_series  # noqa: E402

from graph.neo4j_connect import neo4j_auth  # noqa: E402

NEO4J_URI, (NEO4J_USER, NEO4J_PASSWORD) = neo4j_auth()

# ── Lazy extract + entity indexes (avoid import-time scan when unused) ──
_EXTRACTED: Optional[dict] = None
_ENTITY_INDEXES: Optional[Dict[str, Dict[str, str]]] = None
_ALIAS_MAPS: Optional[Dict[str, Dict[str, str]]] = None


def reload_indexes() -> None:
    """Re-run extract and rebuild entity/alias indexes."""
    global _EXTRACTED, _ENTITY_INDEXES, _ALIAS_MAPS
    _EXTRACTED = extract()
    _ENTITY_INDEXES = _build_entity_indexes(_EXTRACTED)
    _ALIAS_MAPS = _build_alias_maps(_EXTRACTED)


def _extracted() -> dict:
    global _EXTRACTED
    if _EXTRACTED is None:
        reload_indexes()
    assert _EXTRACTED is not None
    return _EXTRACTED


def _indexes() -> Dict[str, Dict[str, str]]:
    global _ENTITY_INDEXES
    if _ENTITY_INDEXES is None:
        reload_indexes()
    assert _ENTITY_INDEXES is not None
    return _ENTITY_INDEXES


def _aliases() -> Dict[str, Dict[str, str]]:
    global _ALIAS_MAPS
    if _ALIAS_MAPS is None:
        reload_indexes()
    assert _ALIAS_MAPS is not None
    return _ALIAS_MAPS


# Module-level proxies used by question_rewrite / smoke (lazy via __getattr__)
def __getattr__(name: str):
    if name == "ENTITY_INDEXES":
        return _indexes()
    if name == "ALIAS_MAPS":
        return _aliases()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _build_entity_indexes(data: dict) -> Dict[str, Dict[str, str]]:
    idx: Dict[str, Dict[str, str]] = {
        "techs": {}, "series": {}, "categories": {}, "types": {}, "products": {},
    }
    for n in data["nodes"]:
        lab, name = n["label"], n["name"]
        props = n.get("props") or {}
        if lab == "Tech":
            idx["techs"][name] = props.get("slug", "")
        elif lab == "Series":
            idx["series"][name] = props.get("slug", "")
        elif lab == "Category":
            idx["categories"][name] = props.get("slug", "")
        elif lab == "ProductType":
            idx["types"][name] = ""
        elif lab == "Product":
            idx["products"][name] = props.get("slug", "")
    return idx


def _build_alias_maps(data: dict) -> Dict[str, Dict[str, str]]:
    """mention (normalized) -> canonical name, per label."""
    maps: Dict[str, Dict[str, str]] = {
        "techs": {}, "series": {}, "categories": {}, "types": {},
    }
    label_of = {"techs": "Tech", "series": "Series", "categories": "Category", "types": "ProductType"}
    for n in data["nodes"]:
        lab = n["label"]
        for key, target in label_of.items():
            if lab != target:
                continue
            name = n["name"]
            m = maps[key]
            m.setdefault(name.lower(), name)
            m.setdefault(name, name)
            title = (n.get("props") or {}).get("title") or ""
            if title:
                m.setdefault(title.lower(), name)
                m.setdefault(title, name)
            if lab == "Series":
                norm = _norm_series(name)
                if norm:
                    m.setdefault(norm, name)
                    # spaced ASCII forms: ultraboost → ultra boost
                    if re.fullmatch(r"[a-z0-9]+", norm) and len(norm) >= 6:
                        for i in range(3, len(norm) - 2):
                            spaced = f"{norm[:i]} {norm[i:]}"
                            m.setdefault(spaced, name)
    return maps


# Soft type/category synonyms only (no TECH_SYNONYMS — avoid guessing missing tech slugs)
TYPE_SYNONYMS = {
    "跑鞋": "鞋", "板鞋": "鞋", "t头鞋": "鞋", "薄底鞋": "鞋", "老爹鞋": "鞋",
    "户外鞋": "鞋", "鞋": "鞋", "服装": "服装", "夹克": "服装", "t恤": "服装",
    "卫衣": "服装", "裤": "服装", "配件": "配件", "包": "配件", "袜": "配件",
    "帽": "配件",
}
CATEGORY_SYNONYMS = {
    "运动表现": "运动表现产品", "三叶草": "三叶草产品", "originals": "三叶草产品",
    "轻运动": "轻运动产品", "sportswear": "轻运动产品",
}

# Explicit tech intent (no bare「哪些」)
_TECH_INTENT_RE = re.compile(r"科技|技术|用了|搭载|采用|含", re.I)

_SERIES_LISTING_RE = re.compile(
    r"系列.*(?:有哪些|哪几款|产品|清单)|(?:有哪些|哪几款|多少).*(?:产品|款).*系列",
    re.I,
)
# 「有哪些产品系列 / 子系列 / 各自特点」→ 列举系列家族，而非系列内产品
_SERIES_FAMILY_RE = re.compile(
    r"有哪些(?:产品)?系列|哪些(?:产品)?系列|子系列|各自(?:有什么|有何)?特点",
    re.I,
)
_TECH_PRODUCTS_RE = re.compile(
    r"哪些.*产品.*(?:用|搭载|有|含)|(?:用|搭载|采用).*(?:科技|技术).*产品|含.*科技.*产品",
    re.I,
)
_TYPE_LISTING_RE = re.compile(r"有哪些(?:跑鞋|板鞋|鞋|服装|配件|夹克)|哪些是(?:鞋|服装)", re.I)


def _ascii_token_hit(mention: str, q_lower: str) -> bool:
    """Whole-token match so short series like 'rim' do not hit inside 'primeknit'."""
    return (
        re.search(rf"(?<![a-z0-9]){re.escape(mention.lower())}(?![a-z0-9])", q_lower)
        is not None
    )


def _mentioned_from_map(question: str, key: str) -> List[str]:
    q_lower = question.lower()
    q_compact = re.sub(r"[\s\-]+", "", q_lower)
    found: List[str] = []
    seen = set()
    for mention in sorted(_aliases()[key].keys(), key=len, reverse=True):
        if len(mention) < 2:
            continue
        if mention.isascii():
            hit = _ascii_token_hit(mention, q_lower)
            # Spaced/hyphen aliases (e.g. "ultra boost") also match compacted question
            if not hit and (" " in mention or "-" in mention):
                mcompact = re.sub(r"[\s\-]+", "", mention.lower())
                if len(mcompact) >= 6 and mcompact in q_compact:
                    hit = True
        else:
            hit = mention in question
        if hit:
            canon = _aliases()[key][mention]
            if canon not in seen:
                seen.add(canon)
                found.append(canon)
    return found


def _mentioned_tech(question: str) -> List[str]:
    return _mentioned_from_map(question, "techs")


def _mentioned_type(question: str) -> List[str]:
    q_lower = question.lower()
    found: List[str] = []
    for syn, canon in TYPE_SYNONYMS.items():
        if syn in q_lower and canon not in found:
            found.append(canon)
    return found


def _mentioned_category(question: str) -> List[str]:
    q_lower = question.lower()
    found: List[str] = []
    for syn, canon in CATEGORY_SYNONYMS.items():
        if syn in q_lower and canon not in found:
            found.append(canon)
    return found


def _resolve_series(question: str) -> Optional[str]:
    found = _mentioned_from_map(question, "series")
    if found:
        return found[0]
    m = re.search(
        r"([A-Za-z0-9\u4e00-\u9fff]+(?:\s+[A-Za-z0-9\u4e00-\u9fff]+)?)\s*系列",
        question,
    )
    if m:
        frag = m.group(1).strip()
        norm = _norm_series(frag)
        for name in _aliases()["series"].values():
            if _norm_series(name) == norm:
                return name
    return None


def _family_token(question: str) -> Optional[str]:
    """Stem used for Series.name CONTAINS match (e.g. adizero → ADIZERO, ADIZERO/CLIMAWARM)."""
    series = _resolve_series(question)
    if series:
        stem = series.split("/")[0].strip()
        return _norm_series(stem) or None
    m = re.search(
        r"([A-Za-z][A-Za-z0-9\-]{2,}|[\u4e00-\u9fff]{2,})\s*(?:有哪些|哪些|的)?(?:产品)?系列",
        question,
        re.I,
    )
    if m:
        return _norm_series(m.group(1)) or None
    return None


def _resolve_product(question: str) -> Optional[str]:
    q_lower = question.lower()
    products = _indexes()["products"]
    for name in sorted(products.keys(), key=len, reverse=True):
        if len(name) < 3:
            continue
        if name in q_lower:
            return name
    m = re.search(r"\b([A-Z]{1,3}\d{4,6})\b", question.upper())
    if m:
        code = m.group(1)
        for name, slug in products.items():
            if code.lower() in name.lower() or code.lower() in slug.lower():
                return name
    return None


@dataclass
class GraphRecallResult:
    hit: bool = False
    template_id: str = ""
    title: str = ""
    layer: str = ""
    entities: List[str] = field(default_factory=list)
    facts_text: str = ""
    rows: List[dict] = field(default_factory=list)
    source_slugs: List[str] = field(default_factory=list)
    error: str = ""


def in_graph_slice(question: str) -> bool:
    if not question:
        return False
    if _mentioned_tech(question):
        return True
    if _resolve_series(question):
        return True
    if _SERIES_FAMILY_RE.search(question) and _family_token(question):
        return True
    if _mentioned_category(question):
        return True
    if _mentioned_type(question) and _TYPE_LISTING_RE.search(question):
        return True
    if _TECH_PRODUCTS_RE.search(question) or _SERIES_LISTING_RE.search(question):
        return True
    return False


# Cypher templates (parameterized)
_CYPHER = {
    "products_by_tech": (
        "MATCH (p:Product)-[:USES_TECH]->(t:Tech {name:$tech}) "
        "RETURN t.name AS tech, collect(DISTINCT p.name) AS products"
    ),
    "product_in_series": (
        "MATCH (p:Product)-[:IN_SERIES]->(s:Series {name:$series}) "
        "RETURN s.name AS series, collect(DISTINCT p.name) AS products"
    ),
    "series_family_listing": (
        "MATCH (s:Series) "
        "WHERE toLower(s.name) CONTAINS $family "
        "RETURN s.name AS series, coalesce(s.slug, '') AS slug "
        "ORDER BY s.name"
    ),
    "products_in_category": (
        "MATCH (p:Product)-[:IN_CATEGORY]->(c:Category {name:$cat}) "
        "RETURN c.name AS category, collect(DISTINCT p.name) AS products"
    ),
    "products_by_type": (
        "MATCH (p:Product)-[:HAS_TYPE]->(ty:ProductType {name:$type}) "
        "RETURN ty.name AS type, collect(DISTINCT p.name) AS products"
    ),
    "series_tech": (
        "MATCH (s:Series {name:$series})-[:SERIES_USES_TECH]->(t:Tech) "
        "RETURN s.name AS series, collect(DISTINCT t.name) AS techs"
    ),
    "series_tech_products": (
        "MATCH (p:Product)-[:IN_SERIES]->(s:Series {name:$series}), "
        "(p)-[:USES_TECH]->(t:Tech {name:$tech}) "
        "RETURN s.name AS series, t.name AS tech, collect(DISTINCT p.name) AS products"
    ),
    "product_overview": (
        "MATCH (p:Product {name:$product}) "
        "OPTIONAL MATCH (p)-[:USES_TECH]->(t:Tech) "
        "OPTIONAL MATCH (p)-[:IN_SERIES]->(s:Series) "
        "OPTIONAL MATCH (p)-[:IN_CATEGORY]->(c:Category) "
        "OPTIONAL MATCH (p)-[:HAS_TYPE]->(ty:ProductType) "
        "RETURN p.name AS product, collect(DISTINCT t.name) AS techs, "
        "collect(DISTINCT s.name) AS series, collect(DISTINCT c.name) AS category, "
        "collect(DISTINCT ty.name) AS type"
    ),
}


def _pick_template(question: str) -> Tuple[str, str, str, dict]:
    """Return (template_id, title, layer, params) or ("no_match", ...).

    Priority (PLAN §4 Bug A/C + series family):
    1. type listing
    1b. series family listing（有哪些产品系列 / 子系列 / 各自特点）
    2. series (+ series_tech if asking tech)
    3. series ∩ tech products
    4. tech with explicit tech intent
    5. category
    6. product overview
    7. tech fallback
    """
    techs = _mentioned_tech(question)
    series = _resolve_series(question)
    cats = _mentioned_category(question)
    types = _mentioned_type(question)
    product = _resolve_product(question)

    # 1. type listing first (avoid「跑鞋」series collision)
    if types and _TYPE_LISTING_RE.search(question):
        return ("products_by_type", f"{types[0]} 类产品", "product", {"type": types[0]})

    # 1b. family of series pages (must beat product_in_series for「有哪些产品系列」)
    if _SERIES_FAMILY_RE.search(question):
        family = _family_token(question)
        if family:
            return (
                "series_family_listing",
                f"{family} 家族系列",
                "product",
                {"family": family},
            )

    # 2. series — prefer when question contains「系列」
    if series and "系列" in question:
        if techs and _TECH_PRODUCTS_RE.search(question):
            return (
                "series_tech_products",
                f"{series} ∩ {techs[0]}",
                "product",
                {"series": series, "tech": techs[0]},
            )
        if _TECH_INTENT_RE.search(question) and not _TECH_PRODUCTS_RE.search(question):
            return ("series_tech", f"{series} 系列科技", "product", {"series": series})
        return ("product_in_series", f"{series} 系列产品", "product", {"series": series})

    # 3. series ∩ tech without「系列」literal but both resolved
    if series and techs and _TECH_PRODUCTS_RE.search(question):
        return (
            "series_tech_products",
            f"{series} ∩ {techs[0]}",
            "product",
            {"series": series, "tech": techs[0]},
        )

    # 4. tech with explicit tech intent (no bare「哪些」)
    if techs and (
        _TECH_PRODUCTS_RE.search(question)
        or _TECH_INTENT_RE.search(question)
    ):
        return (
            "products_by_tech",
            f"采用 {techs[0]} 科技的产品",
            "product",
            {"tech": techs[0]},
        )

    # 5. category
    if cats and re.search(r"产品|系列", question):
        return (
            "products_in_category",
            f"{cats[0]} 产品",
            "product",
            {"cat": cats[0]},
        )

    # series listing without「系列」already handled; leftover series + 产品/哪些
    if series and (_SERIES_LISTING_RE.search(question) or re.search(r"产品", question)):
        return ("product_in_series", f"{series} 系列产品", "product", {"series": series})

    # 6. product overview
    if product:
        return ("product_overview", f"{product} 产品邻域", "product", {"product": product})

    # 7. tech fallback
    if techs:
        return (
            "products_by_tech",
            f"采用 {techs[0]} 科技的产品",
            "product",
            {"tech": techs[0]},
        )

    return ("no_match", "", "", {})


def _run_cypher(cypher: str, params: dict) -> List[dict]:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            return [dict(r) for r in session.run(cypher, **params)]
    finally:
        driver.close()


def _filter_empty_collects(rows: List[dict]) -> List[dict]:
    """Drop rows where all list values are empty (OPTIONAL MATCH artifacts)."""
    out = []
    for row in rows:
        lists = [v for v in row.values() if isinstance(v, list)]
        if lists and all(len(v) == 0 for v in lists) and not any(
            isinstance(v, str) and v for v in row.values()
        ):
            continue
        # products_by_* : empty products list → treat as no rows (deterministic empty)
        if "products" in row and isinstance(row["products"], list) and not row["products"]:
            continue
        if "techs" in row and isinstance(row["techs"], list) and not row["techs"]:
            continue
        out.append(row)
    return out


def _slugs_for(entities: List[str], question: str) -> List[str]:
    slugs: List[str] = []
    seen = set()
    idx = _indexes()
    for ent in entities:
        for key in ("techs", "series", "categories", "products"):
            mapping = idx[key]
            if ent in mapping and mapping[ent]:
                s = mapping[ent]
                if s and s not in seen:
                    seen.add(s)
                    slugs.append(s)
                break
    return slugs


def _entities_from_rows(rows: List[dict]) -> List[str]:
    out: List[str] = []
    seen = set()
    for row in rows:
        for v in row.values():
            vals = v if isinstance(v, list) else [v]
            for item in vals:
                if isinstance(item, str) and item and item not in seen:
                    seen.add(item)
                    out.append(item)
    return out


def _format_facts(title: str, rows: List[dict]) -> str:
    if not rows:
        return f"【图谱召回 · 产品层 · {title}】\n(查询无结果 — 覆盖集内无匹配，属确定性否定)"
    lines = [f"【图谱召回 · 产品层 · {title}】", "以下为类型化图多跳结构化结果："]
    for i, row in enumerate(rows, 1):
        parts = []
        for k, v in row.items():
            if isinstance(v, list):
                parts.append(f"{k}={len(v)}项")
            else:
                parts.append(f"{k}={v}")
        lines.append(f"  {i}. " + "; ".join(parts))
    lines.append("说明：请结合下方「原文」文档回答；图结果仅作实体与关系线索。")
    return "\n".join(lines)


def recall(question: str) -> GraphRecallResult:
    if not in_graph_slice(question):
        return GraphRecallResult(hit=False)

    tid, title, layer, params = _pick_template(question)
    if tid == "no_match":
        return GraphRecallResult(hit=False)

    cypher = _CYPHER.get(tid, "")
    if not cypher:
        return GraphRecallResult(hit=False)

    try:
        rows = _run_cypher(cypher, params)
        rows = _filter_empty_collects(rows)
    except Exception as exc:  # noqa: BLE001
        return GraphRecallResult(
            hit=True,
            template_id=tid,
            title=title,
            layer=layer,
            error=str(exc),
            facts_text=f"【图谱召回失败】{exc}",
        )

    entities = _entities_from_rows(rows)
    for ent in (
        _mentioned_tech(question)
        + ([_resolve_series(question)] if _resolve_series(question) else [])
        + _mentioned_category(question)
        + _mentioned_type(question)
    ):
        if ent and ent not in entities:
            entities.append(ent)

    if tid == "series_family_listing":
        # Prefer series page slugs from Cypher; do not pull product pages.
        slugs: List[str] = []
        seen_slugs: set = set()
        idx_series = _indexes()["series"]
        for row in rows:
            sname = row.get("series") or ""
            slug = (row.get("slug") or "").strip() or (idx_series.get(sname) or "")
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                slugs.append(slug)
        entities = [r.get("series") for r in rows if r.get("series")]
    else:
        slugs = _slugs_for(entities, question)

    return GraphRecallResult(
        hit=True,
        template_id=tid,
        title=title,
        layer=layer,
        entities=entities,
        facts_text=_format_facts(title, rows),
        rows=rows,
        source_slugs=slugs,
    )


def load_source_page(slug: str, max_chars: int = 8000) -> str:
    try:
        from overlay import read_page
        text = read_page(slug, max_chars=max_chars + 2000)
    except Exception:  # noqa: BLE001
        path = Path(SOURCE_KB_ROOT) / f"{slug}.md"
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="ignore")
    if not text:
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return text.strip()[:max_chars]


def build_context_block(result: GraphRecallResult, *, max_pages: Optional[int] = None):
    if not result.hit:
        return "", []
    parts = [result.facts_text]
    loaded = []
    # Family listing: load every recalled series page (answers come from those pages).
    if max_pages is None:
        max_pages = None if result.template_id == "series_family_listing" else 12
    for slug in result.source_slugs:
        if max_pages is not None and len(loaded) >= max_pages:
            break
        body = load_source_page(slug)
        if body:
            parts.append(f"## {slug}\n{body}")
            loaded.append(slug)
    return "\n\n---\n\n".join(parts), loaded


def graph_stats() -> dict:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return {"nodes": nodes, "relationships": rels, "uri": NEO4J_URI}
    finally:
        driver.close()


if __name__ == "__main__":
    for q in [
        "哪些产品用了 boost 科技？",
        "climacool 系列有哪些产品？",
        "adizero有哪些产品系列？各自有什么特点？",
        "运动表现有哪些产品？",
        "哪些产品用了碳板科技？",
        "有哪些跑鞋？",
        "ULTRABOOST 系列用了什么科技？",
    ]:
        r = recall(q)
        print(f"\nQ: {q}\n  hit={r.hit} template={r.template_id} rows={len(r.rows)} slugs={r.source_slugs[:4]}")
        if r.error:
            print("  error:", r.error)
        if r.rows:
            print("  ", {k: (len(v) if isinstance(v, list) else v) for k, v in r.rows[0].items()})
