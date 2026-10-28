"""graph_recall.py — Dual-layer Neo4j recall (clinical + product + cross).

图只做召回：问题落在图谱切片 → Cypher → 实体名 + 结构化事实。
答案仍由知识库原文（临床层 + 桥接层 + 产品 Markdown）产出。
实体 → slug 映射见 graph-entity-map.yml。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

KB_ROOT = Path(__file__).resolve().parent
if str(KB_ROOT / "graph") not in sys.path:
    sys.path.insert(0, str(KB_ROOT / "graph"))

NEO4J_URI = os.environ.get("MEDICAL_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("MEDICAL_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("MEDICAL_NEO4J_PASSWORD", "medical123")


def _load_entity_map() -> tuple[dict[str, str], dict[str, str], set[str]]:
    path = KB_ROOT / "graph-entity-map.yml"
    if not path.is_file():
        return {}, {}, set()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entities = {str(k): str(v) for k, v in (raw.get("entities") or {}).items()}
    safety = {str(k): str(v) for k, v in (raw.get("safety_pages") or {}).items()}
    canonical = set(entities.keys())
    return entities, safety, canonical


ENTITY_SLUGS, SAFETY_PAGES, CANONICAL_ENTITIES = _load_entity_map()

from wiki_graph_extract import edge_pages_for_entities, build_alias_index  # noqa: E402

# alias → canonical; ENTITY_SLUGS expanded so aliases resolve to same Wiki slug
ALIAS_TO_CANONICAL = build_alias_index()
for _alias, _canon in ALIAS_TO_CANONICAL.items():
    if _alias == _canon:
        continue
    slug = ENTITY_SLUGS.get(_canon)
    if slug and _alias not in ENTITY_SLUGS:
        ENTITY_SLUGS[_alias] = slug

PRODUCT_SLUG_PREFIXES = ("处方药/", "OTC药品/", "医疗器械/")


def _build_entity_indexes() -> dict[str, dict[str, str]]:
    """Partition ENTITY_SLUGS by Wiki slug prefix (industry-generic entity types)."""
    indexes: dict[str, dict[str, str]] = {
        "patients": {},
        "drugs": {},
        "conditions": {},
        "series": {},
        "techs": {},
        "products": {},
    }
    for name, slug in ENTITY_SLUGS.items():
        if name not in CANONICAL_ENTITIES:
            continue
        if slug.startswith("临床病例/"):
            indexes["patients"][name] = slug
        elif slug.startswith("成分/"):
            indexes["drugs"][name] = slug
        elif slug.startswith("疾病/"):
            indexes["conditions"][name] = slug
        elif slug.startswith("产品系列/"):
            indexes["series"][name] = slug
        elif slug.startswith("技术平台/"):
            indexes["techs"][name] = slug
        elif any(slug.startswith(p) for p in PRODUCT_SLUG_PREFIXES):
            indexes["products"][name] = slug
    return indexes


ENTITY_INDEXES = _build_entity_indexes()
PATIENTS = tuple(sorted(ENTITY_INDEXES["patients"].keys(), key=len, reverse=True))


def _mentioned_from_index(question: str, index: dict[str, str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    q_lower = question.lower()
    for name in sorted(index.keys(), key=len, reverse=True):
        matched = name in question if not name.isascii() else name.lower() in q_lower
        if matched and name not in seen:
            seen.add(name)
            found.append(name)
    return found


def _mentioned_series(question: str) -> list[str]:
    """Series names as Neo4j Series.name (canonical, not display aliases like *系列)."""
    found: list[str] = []
    seen: set[str] = set()
    q_lower = question.lower()
    series_keys = set(ENTITY_INDEXES["series"].keys())
    for alias in sorted(ALIAS_TO_CANONICAL.keys(), key=len, reverse=True):
        canon = ALIAS_TO_CANONICAL[alias]
        if canon not in series_keys:
            continue
        matched = alias in question if not alias.isascii() else alias.lower() in q_lower
        if matched and canon not in seen:
            seen.add(canon)
            found.append(canon)
    return found


def _mentioned_products(question: str) -> list[str]:
    """Product names as Neo4j Product.name (canonical)."""
    found: list[str] = []
    seen: set[str] = set()
    q_lower = question.lower()
    product_keys = set(ENTITY_INDEXES["products"].keys())
    for alias in sorted(ALIAS_TO_CANONICAL.keys(), key=len, reverse=True):
        canon = ALIAS_TO_CANONICAL[alias]
        if canon not in product_keys:
            continue
        matched = alias in question if not alias.isascii() else alias.lower() in q_lower
        if matched and canon not in seen:
            seen.add(canon)
            found.append(canon)
    return found


def _mentioned_conditions(question: str) -> list[str]:
    return _mentioned_from_index(question, ENTITY_INDEXES["conditions"])


def _mentioned_tech(question: str) -> list[str]:
    return _mentioned_from_index(question, ENTITY_INDEXES["techs"])


def _resolve_series_from_question(question: str) -> Optional[str]:
    """Resolve Series entity name from question; no brand default."""
    mentioned = _mentioned_series(question)
    if mentioned:
        return mentioned[0]
    m = re.search(r"([A-Za-z0-9\u4e00-\u9fff]+?)\s*系列", question)
    if not m:
        return None
    fragment = m.group(1).strip()
    if not fragment:
        return None
    series_index = ENTITY_INDEXES["series"]
    if fragment in series_index:
        return fragment
    matches = [name for name in series_index if fragment in name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Prefer longest name containing fragment (e.g. 心血管 → 福顺心血管)
        return max(matches, key=len)
    return None


def _resolve_tech_from_question(question: str) -> Optional[str]:
    techs = _mentioned_tech(question)
    if techs:
        return techs[0]
    if re.search(r"缓释", question):
        return "缓释技术" if "缓释技术" in ENTITY_INDEXES["techs"] else None
    if re.search(r"靶向", question):
        return "靶向递送" if "靶向递送" in ENTITY_INDEXES["techs"] else None
    if re.search(r"纳米", question):
        return "纳米制剂" if "纳米制剂" in ENTITY_INDEXES["techs"] else None
    return None


def series_slug_for_question(question: str) -> Optional[str]:
    """Wiki slug for series overview page referenced in question."""
    series = _resolve_series_from_question(question)
    if not series:
        return None
    return ENTITY_SLUGS.get(series)


def _series_slug_candidates(series_fragment: str) -> list[str]:
    """Build candidate Wiki slugs for a series name fragment (config-driven brand prefix)."""
    candidates: list[str] = []
    resolved = _resolve_series_from_question(series_fragment) or series_fragment
    slug = ENTITY_SLUGS.get(resolved)
    if slug:
        candidates.append(slug)
    candidates.append(f"产品系列/{resolved}")
    try:
        from config import cfg

        brand = getattr(cfg.brand, "name", "") or ""
        if brand:
            candidates.append(f"产品系列/{brand}{resolved}")
            candidates.append(f"产品系列/{brand}-{resolved}")
    except Exception:  # noqa: BLE001
        pass
    candidates.append(f"产品系列/{series_fragment}")
    candidates.append(f"产品系列/{series_fragment}-series")
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _build_cross_re() -> re.Pattern:
    if not PATIENTS:
        patient_alt = ""
    else:
        patient_alt = "|".join(re.escape(p) for p in PATIENTS)
    parts = [
        r"库里哪些|知识库.*禁忌|库内|库中|含二甲双胍.*产品",
    ]
    if patient_alt:
        parts.insert(
            0,
            f"({patient_alt}).*(产品).*(禁忌|肾病|妊娠|过敏)|"
            f"({patient_alt}).*(库里哪些|知识库.*禁忌)",
        )
    return re.compile("|".join(parts), re.I)


def _build_clinical_re() -> re.Pattern:
    patient_alt = "|".join(re.escape(p) for p in PATIENTS) if PATIENTS else ""
    drug_alt = "|".join(re.escape(d) for d in ENTITY_INDEXES["drugs"].keys())
    terms = [
        r"相互作用|过敏|禁忌|起搏器|MRI|妊娠|化验|加药|"
        r"正在吃的药|药物相互作用|抗生素|"
        r"不能用什么|不宜用|什么药不能|哪些药不能",
    ]
    extras = [t for t in (patient_alt, drug_alt) if t]
    if extras:
        terms.insert(0, "|".join(extras))
    return re.compile("|".join(terms), re.I)


_CLINICAL_RE = _build_clinical_re()

_PRODUCT_RE = re.compile(
    r"系列|缓释|靶向|纳米|"
    r"技术平台|产品.*技术|"
    r"哪些产品|哪款产品|哪些药.*产品|的产品有哪些|含.+产品|适应症",
    re.I,
)

_CROSS_RE = _build_cross_re()

# ── Intent patterns (paraphrase-tolerant) ──
_UNSAFE_MED_RE = re.compile(
    r"不能用什么|不宜用|不应使用|禁用|哪些药不能|什么药不能|"
    r"不能开|不宜开|avoid|contraindicated",
    re.I,
)
_CONTRA_RE = re.compile(
    r"禁忌|不能用|不宜|禁用|不宜使用|不能开|contraindication",
    re.I,
)
_DRUG_PRODUCT_RE = re.compile(
    r"相关药|相关产品|关联.{0,4}产品|关联.{0,4}药|含.*产品|成分.*产品|"
    r"哪些产品|哪些药|对应产品|对应药",
    re.I,
)
_ANTIBIOTIC_RE = re.compile(r"抗生素|antibiotic", re.I)
_INGREDIENT_INTENT_RE = re.compile(
    r"活性成分|主要成分|成分是什么|说明书|规格|剂量",
    re.I,
)
_SERIES_LISTING_RE = re.compile(
    r"系列.*(?:有哪些|哪几款|产品|清单|药品)|"
    r"(?:有哪些|哪几款).*(?:产品|药品).*系列",
    re.I,
)
_CROSS_KB_RE = re.compile(r"库里|知识库|库内|库中", re.I)
_RENAL_THRESHOLD_RE = re.compile(
    r"CrCl|eGFR|肾小球滤过|肾功能.*门槛|门槛.*肾功能|肌酐清除率",
    re.I,
)
_ADR_SKIN_RE = re.compile(r"皮肤发红|发红发痒|皮疹|发痒|过敏样", re.I)
_OUT_OF_SCOPE_RE = re.compile(
    r"ABC-123|未上市|双盲试验|COA|批号\s*XYZ|帕博利珠|K药|PD-L1|"
    r"曲妥珠单抗|H20\d{7}|NMPA.*指导原则",
    re.I,
)


@dataclass
class GraphRecallResult:
    hit: bool = False
    template_id: str = ""
    title: str = ""
    layer: str = ""  # clinical | product | cross
    entities: list[str] = field(default_factory=list)
    facts_text: str = ""
    rows: list[dict] = field(default_factory=list)
    source_slugs: list[str] = field(default_factory=list)
    error: str = ""


def in_graph_slice(question: str) -> bool:
    if not question:
        return False
    if _CLINICAL_RE.search(question) or _PRODUCT_RE.search(question) or _CROSS_RE.search(question):
        return True
    if _RENAL_THRESHOLD_RE.search(question) and re.search(
        r"慢性肾病|CKD|肾病|禁忌|规则|二甲双胍", question, re.I
    ):
        return True
    if (
        _mentioned_drugs(question)
        or _mentioned_products(question)
        or _mentioned_series(question)
    ):
        return True
    # 成分 + 产品清单问法（如「含氨氯地平的产品有哪些」）
    if _mentioned_drugs(question) and _DRUG_PRODUCT_RE.search(question):
        return True
    q_lower = question.lower()
    # Alias mentions (e.g. CKD, metformin, penicillin) also enter the graph slice
    for alias, canon in ALIAS_TO_CANONICAL.items():
        if alias == canon:
            continue
        if alias.isascii():
            if alias.lower() in q_lower:
                return True
        elif alias in question:
            return True
    return False


def canonicalize_mentioned(question: str) -> list[str]:
    """Return canonical entity names mentioned via name or alias in question."""
    found: list[str] = []
    seen = set()
    q_lower = question.lower()
    # Longer aliases first to prefer specific matches
    for alias in sorted(ALIAS_TO_CANONICAL.keys(), key=len, reverse=True):
        matched = (
            alias.lower() in q_lower
            if alias.isascii()
            else alias in question
        )
        if not matched:
            continue
        canon = ALIAS_TO_CANONICAL[alias]
        if canon not in seen:
            seen.add(canon)
            found.append(canon)
    return found


def _detect_patient(question: str) -> Optional[str]:
    for name in PATIENTS:
        if name in question:
            return name
    return None


def _is_cross_patient_product_intent(question: str) -> bool:
    if not _detect_patient(question):
        return False
    if _CROSS_RE.search(question):
        return True
    if _CROSS_KB_RE.search(question) and re.search(
        r"禁忌|成分|产品|不能用|不宜", question
    ):
        return True
    if re.search(r"产品", question) and re.search(
        r"禁忌|成分|肾病|妊娠|过敏|不能用", question
    ):
        return True
    return False


def _mentioned_drugs(question: str) -> list[str]:
    """Canonical Drug names mentioned in question (成分/* slugs)."""
    drugs: list[str] = []
    seen: set[str] = set()
    for canon in canonicalize_mentioned(question):
        slug = ENTITY_SLUGS.get(canon, "")
        if slug.startswith("成分/") and canon not in seen:
            seen.add(canon)
            drugs.append(canon)
    for name, slug in ENTITY_SLUGS.items():
        if not slug.startswith("成分/"):
            continue
        if name in question and name not in seen:
            seen.add(name)
            drugs.append(name)
        elif name.isascii() and name.lower() in question.lower() and name not in seen:
            seen.add(name)
            drugs.append(name)
    return drugs


def _cypher_drug_overview(drug: str) -> str:
    return f"""
    MATCH (d:Drug {{name:'{drug}'}})
    OPTIONAL MATCH (d)-[:CONTRAINDICATED_FOR]->(c:Condition)
    OPTIONAL MATCH (prod:Product)-[:HAS_INGREDIENT]->(d)
    OPTIONAL MATCH (p:Patient)-[:ALLERGIC_TO]->(d)
    RETURN d.name AS drug,
           collect(DISTINCT c.name) AS contraindications,
           collect(DISTINCT prod.name) AS products,
           collect(DISTINCT p.name) AS allergic_patients
    """


def _cypher_patient_unsafe_meds(patient: str) -> str:
    """Allergies → contraindication conditions → cross-unsafe drugs + products."""
    return f"""
    MATCH (p:Patient {{name:'{patient}'}})
    OPTIONAL MATCH (p)-[:ALLERGIC_TO]->(ad:Drug)
    OPTIONAL MATCH (ad)-[:CONTRAINDICATED_FOR]->(cond:Condition)
    OPTIONAL MATCH (prod:Product)-[:HAS_INGREDIENT]->(ad)
    OPTIONAL MATCH (cross_d:Drug)-[:CONTRAINDICATED_FOR]->(cond)
    RETURN p.name AS patient,
           collect(DISTINCT ad.name) AS allergy_drugs,
           collect(DISTINCT cond.name) AS related_conditions,
           collect(DISTINCT prod.name) AS unsafe_products,
           collect(DISTINCT cross_d.name) AS cross_unsafe_drugs
    """


def _patient_unsafe_intent(question: str) -> Optional[str]:
    """Patient + 'what drugs to avoid' phrasing (paraphrase-tolerant)."""
    patient = _detect_patient(question)
    if not patient:
        return None
    # Cross-layer product queries take precedence over generic unsafe-med intent
    if re.search(r"库里|知识库|库内|含.*禁忌.*产品|禁忌成分.*产品|相关禁忌成分", question):
        return None
    if _UNSAFE_MED_RE.search(question):
        return patient
    if _CONTRA_RE.search(question) and re.search(r"什么|哪些|哪类", question):
        return patient
    if re.search(r"不能|不宜|禁用", question) and re.search(
        r"药|抗生素|antibiotic", question, re.I
    ):
        return patient
    return None


def _pick_entity_driven(question: str, drug: str) -> Optional[tuple[str, str, str, str]]:
    """Route by mentioned Drug when no patient context."""
    if _CONTRA_RE.search(question) and _DRUG_PRODUCT_RE.search(question):
        return (
            "drug_overview",
            f"{drug}禁忌与相关产品",
            _cypher_drug_overview(drug),
            "cross",
        )
    if _CONTRA_RE.search(question):
        return (
            "ingredient_contraindications",
            f"{drug}用药禁忌",
            f"""
            MATCH (d:Drug {{name:'{drug}'}})-[:CONTRAINDICATED_FOR]->(c:Condition)
            RETURN d.name AS drug, collect(DISTINCT c.name) AS conditions
            """,
            "clinical",
        )
    if _DRUG_PRODUCT_RE.search(question):
        return (
            "products_by_ingredient",
            f"含{drug}的相关产品",
            f"""
            MATCH (prod:Product)-[:HAS_INGREDIENT]->(d:Drug {{name:'{drug}'}})
            OPTIONAL MATCH (prod)-[:IN_SERIES]->(s:Series)
            RETURN prod.name AS product, d.name AS ingredient,
                   collect(DISTINCT s.name) AS series
            """,
            "product",
        )
    if re.search(r"过敏", question):
        return (
            "allergies_to_drug",
            f"对{drug}过敏的患者",
            f"""
            MATCH (p:Patient)-[:ALLERGIC_TO]->(d:Drug {{name:'{drug}'}})
            RETURN d.name AS drug, collect(DISTINCT p.name) AS patients
            """,
            "clinical",
        )
    return None


def template_matches_question(question: str, template_id: str, entities: list[str]) -> bool:
    """True when picked template is relevant to drugs mentioned in the question."""
    drugs = _mentioned_drugs(question)
    if not drugs:
        return True
    drug = drugs[0]
    if template_id == "cross_patient_product_contra" and drug not in entities:
        return False
    return True


def _fallback_drug_template(question: str) -> tuple[str, str, str, str]:
    drugs = _mentioned_drugs(question)
    if not drugs:
        return ("no_match", "", "", "")
    drug = drugs[0]
    return (
        "drug_overview",
        f"{drug}图谱邻域",
        _cypher_drug_overview(drug),
        "clinical",
    )


def _cypher_product_ingredients(product: str) -> str:
    return f"""
    MATCH (prod:Product {{name:'{product}'}})-[:HAS_INGREDIENT]->(d:Drug)
    RETURN prod.name AS product, collect(DISTINCT d.name) AS ingredients
    """


def _cypher_product_overview(product: str) -> str:
    return f"""
    MATCH (prod:Product {{name:'{product}'}})
    OPTIONAL MATCH (prod)-[:HAS_INGREDIENT]->(d:Drug)
    OPTIONAL MATCH (prod)-[:IN_SERIES]->(s:Series)
    RETURN prod.name AS product,
           collect(DISTINCT d.name) AS ingredients,
           collect(DISTINCT s.name) AS series
    """


def _pick_template(question: str) -> tuple[str, str, str, str]:
    """Return (template_id, title, cypher, layer)."""
    patient = _detect_patient(question)
    drugs = _mentioned_drugs(question)
    products = _mentioned_products(question)

    # ── 0. Renal function threshold / CrCl rules (L4-2) ──
    if _RENAL_THRESHOLD_RE.search(question) and (
        _mentioned_conditions(question)
        or re.search(r"慢性肾病|CKD|肾病", question, re.I)
    ):
        if re.search(r"禁忌|规则|门槛|二甲双胍|降糖", question, re.I):
            return (
                "ingredient_contraindications",
                "慢性肾病肾功能门槛与二甲双胍禁忌",
                """
                MATCH (d:Drug {name:'二甲双胍'})-[:CONTRAINDICATED_FOR]->(c:Condition {name:'慢性肾病'})
                RETURN d.name AS drug, collect(DISTINCT c.name) AS conditions
                """,
                "clinical",
            )

    # ── 1. Product + ingredient / PI intent ──
    if products and _INGREDIENT_INTENT_RE.search(question):
        product = products[0]
        return (
            "product_ingredients",
            f"{product}活性成分",
            _cypher_product_ingredients(product),
            "product",
        )

    # ── 2. Cross-layer (patient + product / KB inventory intent) ──
    if _is_cross_patient_product_intent(question):
        p = patient or "王强"
        return (
            "cross_patient_product_contra",
            f"{p}诊断 → 禁忌成分 → 相关产品",
            f"""
            MATCH (p:Patient {{name:'{p}'}})-[:HAS_RECORD]->(:Record)-[:DIAGNOSES]->(c:Condition)
            MATCH (d:Drug)-[:CONTRAINDICATED_FOR]->(c)
            MATCH (prod:Product)-[:HAS_INGREDIENT]->(d)
            RETURN p.name AS patient, c.name AS condition, d.name AS drug,
                   collect(DISTINCT prod.name) AS products
            """,
            "cross",
        )

    # ── 3. Patient medication safety ──
    unsafe_patient = _patient_unsafe_intent(question)
    if unsafe_patient:
        title = f"{unsafe_patient}应避免用药"
        if _ANTIBIOTIC_RE.search(question):
            title = f"{unsafe_patient}应避免抗生素"
        return (
            "patient_unsafe_meds",
            title,
            _cypher_patient_unsafe_meds(unsafe_patient),
            "clinical",
        )

    # ── 4. Drug entity-driven (no patient) ──
    if drugs and not patient:
        picked = _pick_entity_driven(question, drugs[0])
        if picked:
            return picked

    # ── 5. Product + drug relationship (e.g. 产品与青霉素的关系) ──
    if products and drugs and re.search(r"关系|关联|含有|成分", question):
        drug = drugs[0]
        return (
            "products_by_ingredient",
            f"含{drug}的相关产品",
            f"""
            MATCH (prod:Product)-[:HAS_INGREDIENT]->(d:Drug {{name:'{drug}'}})
            OPTIONAL MATCH (prod)-[:IN_SERIES]->(s:Series)
            RETURN prod.name AS product, d.name AS ingredient,
                   collect(DISTINCT s.name) AS series
            """,
            "product",
        )

    # ── 6. Series + technology platform ──
    series_name = _resolve_series_from_question(question)
    tech_name = _resolve_tech_from_question(question)
    if series_name and tech_name and re.search(r"缓释|靶向|纳米|技术", question):
        return (
            "product_series_tech",
            f"{series_name} ∩ {tech_name}",
            f"""
            MATCH (prod:Product)-[:IN_SERIES]->(s:Series {{name:'{series_name}'}})
            MATCH (prod)-[:USES_TECH]->(t:TechPlatform {{name:'{tech_name}'}})
            RETURN s.name AS series, t.name AS tech, collect(DISTINCT prod.name) AS products
            """,
            "product",
        )

    # ── 7. Drug → products ──
    if _DRUG_PRODUCT_RE.search(question) and drugs:
        drug = drugs[0]
        return (
            "products_by_ingredient",
            f"含{drug}的相关产品",
            f"""
            MATCH (prod:Product)-[:HAS_INGREDIENT]->(d:Drug {{name:'{drug}'}})
            OPTIONAL MATCH (prod)-[:IN_SERIES]->(s:Series)
            RETURN prod.name AS product, d.name AS ingredient,
                   collect(DISTINCT s.name) AS series
            """,
            "product",
        )

    # ── 8. Indication → products ──
    conditions = _mentioned_conditions(question)
    cond_name = conditions[0] if conditions else None
    if not cond_name and re.search(r"高血压", question):
        cond_name = "高血压"
    if cond_name and re.search(r"产品|哪些药|药品", question):
        return (
            "product_by_indication",
            f"适应症={cond_name}的产品",
            f"""
            MATCH (prod:Product)-[:INDICATED_FOR]->(c:Condition {{name:'{cond_name}'}})
            OPTIONAL MATCH (prod)-[:USES_TECH]->(t:TechPlatform)
            RETURN prod.name AS product, c.name AS condition,
                   collect(DISTINCT t.name) AS techs
            """,
            "product",
        )

    # ── 9. Series product listing ──
    if series_name and _SERIES_LISTING_RE.search(question):
        return (
            "product_in_series",
            f"{series_name}系列产品",
            f"""
            MATCH (prod:Product)-[:IN_SERIES]->(s:Series {{name:'{series_name}'}})
            RETURN s.name AS series, collect(DISTINCT prod.name) AS products
            """,
            "product",
        )

    # ── 10. Product overview (product mentioned, no stronger intent) ──
    if products:
        product = products[0]
        return (
            "product_overview",
            f"{product}产品邻域",
            _cypher_product_overview(product),
            "product",
        )

    # ── Drug entity-driven when patient also present ──
    if drugs:
        picked = _pick_entity_driven(question, drugs[0])
        if picked:
            return picked

    # ── Clinical layer ──
    if patient and re.search(r"相互作用|一起吃|合用|对比", question):
        return (
            "drug_interaction",
            f"{patient}用药相互作用",
            f"""
            MATCH (p:Patient {{name:'{patient}'}})-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d1:Drug)
            MATCH (d1)-[:INTERACTS_WITH]-(d2:Drug)
            WHERE EXISTS {{ (p)-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d2) }}
            RETURN DISTINCT d1.name AS a, d2.name AS b
            """,
            "clinical",
        )

    if re.search(r"相互作用|对比", question) and len(drugs) >= 2:
        d1, d2 = drugs[0], drugs[1]
        return (
            "drug_interaction_pair",
            f"{d1}与{d2}相互作用",
            f"""
            MATCH (d1:Drug {{name:'{d1}'}})-[:INTERACTS_WITH]-(d2:Drug {{name:'{d2}'}})
            RETURN d1.name AS a, d2.name AS b
            """,
            "clinical",
        )

    if re.search(r"过敏", question) and patient:
        return (
            "allergy",
            f"{patient}药物过敏",
            f"""
            MATCH (p:Patient {{name:'{patient}'}})-[:ALLERGIC_TO]->(d:Drug)
            RETURN d.name AS drug
            """,
            "clinical",
        )

    if patient and re.search(r"起搏器|MRI|互斥|检查设备", question):
        return (
            "device_contra",
            f"{patient}设备禁忌",
            f"""
            MATCH (p:Patient {{name:'{patient}'}})-[:HAS_RECORD]->(:Record)-[:ORDERS]->(:Procedure)-[:USES]->(dev:Device)
            MATCH (mri:Device)-[:CONTRAINDICATED_WITH]->(dev)
            RETURN dev.name AS device, mri.name AS contraindicated_device
            """,
            "clinical",
        )

    if re.search(r"妊娠|怀孕|孕妇", question):
        preg_patient = patient
        preg_drug = drugs[0] if drugs else None
        if preg_patient or preg_drug:
            if preg_drug:
                return (
                    "pregnancy_contra",
                    f"{preg_drug}妊娠用药禁忌",
                    f"""
                    MATCH (d:Drug {{name:'{preg_drug}'}})-[:CONTRAINDICATED_FOR]->(c:Condition {{name:'妊娠'}})
                    RETURN d.name AS drug, c.name AS condition
                    """,
                    "clinical",
                )
            return (
                "pregnancy_contra",
                f"{preg_patient}妊娠用药禁忌",
                f"""
                MATCH (p:Patient {{name:'{preg_patient}'}})-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d:Drug)
                MATCH (d)-[:CONTRAINDICATED_FOR]->(c:Condition {{name:'妊娠'}})
                RETURN d.name AS drug, c.name AS condition
                """,
                "clinical",
            )

    if patient and re.search(r"化验|报告.*禁忌|提示.*禁忌|禁忌药", question) and not re.search(
        r"加.*二甲双胍|加药", question
    ):
        return (
            "lab_contra",
            f"{patient}化验→药物禁忌",
            f"""
            MATCH (p:Patient {{name:'{patient}'}})-[:HAS_RECORD]->(:Record)-[:ORDERS]->(:Report)-[:SHOWS]->(c:Condition)
            MATCH (d:Drug)-[:CONTRAINDICATED_FOR]->(c)
            RETURN c.name AS condition, collect(DISTINCT d.name) AS drugs
            """,
            "clinical",
        )

    if re.search(r"能治|适应症|哪些药.*糖尿病|治.*糖尿病", question) and "产品" not in question:
        return (
            "treats",
            "适应症反查（成分层）",
            """
            MATCH (d:Drug)-[:TREATS]->(c:Condition {name:'2型糖尿病'})
            RETURN d.name AS drug, c.name AS condition
            """,
            "clinical",
        )

    if patient and re.search(r"加.*二甲双胍|加药|能不能加|有无禁忌", question):
        return (
            "add_drug_safety",
            f"给{patient}加二甲双胍安全检查",
            f"""
            MATCH (p:Patient {{name:'{patient}'}})-[:HAS_RECORD]->(:Record)-[:DIAGNOSES]->(c:Condition)
            MATCH (d:Drug {{name:'二甲双胍'}})-[:CONTRAINDICATED_FOR]->(c)
            RETURN c.name AS condition, d.name AS drug
            """,
            "clinical",
        )

    if patient:
        return (
            "patient_overview",
            f"{patient}病历邻域",
            f"""
            MATCH (p:Patient {{name:'{patient}'}})-[:HAS_RECORD]->(r:Record)
            OPTIONAL MATCH (r)-[:DIAGNOSES]->(c:Condition)
            OPTIONAL MATCH (r)-[:PRESCRIBES]->(d:Drug)
            OPTIONAL MATCH (p)-[:ALLERGIC_TO]->(a:Drug)
            RETURN p.name AS patient,
                   collect(DISTINCT c.name) AS conditions,
                   collect(DISTINCT d.name) AS drugs,
                   collect(DISTINCT a.name) AS allergies
            """,
            "clinical",
        )

    if drugs:
        drug = drugs[0]
        return (
            "drug_overview",
            f"{drug}图谱邻域",
            _cypher_drug_overview(drug),
            "clinical",
        )

    return ("no_match", "", "", "")


def _run_cypher(cypher: str) -> list[dict]:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            return [dict(r) for r in session.run(cypher)]
    finally:
        driver.close()


def _entities_from_rows(rows: list[dict]) -> list[str]:
    names: list[str] = []
    seen = set()
    for row in rows:
        for v in row.values():
            vals = v if isinstance(v, list) else [v]
            for item in vals:
                if isinstance(item, str) and item and item not in seen:
                    seen.add(item)
                    names.append(item)
    return names


def _format_facts(title: str, layer: str, rows: list[dict]) -> str:
    layer_zh = {"clinical": "临床层", "product": "产品层", "cross": "跨层桥接"}.get(layer, layer)
    if not rows:
        return f"【图谱召回 · {layer_zh} · {title}】\n(查询无结果)"
    lines = [
        f"【图谱召回 · {layer_zh} · {title}】",
        "以下为 Neo4j 多跳结构化结果（演示用，非临床建议）：",
    ]
    for i, row in enumerate(rows, 1):
        parts = [f"{k}={v}" for k, v in row.items()]
        lines.append(f"  {i}. " + "; ".join(parts))
    lines.append("说明：请结合下方「原文」文档回答；图结果仅作实体与关系线索。")
    return "\n".join(lines)


def _slugs_for_entities(entities: list[str], question: str) -> list[str]:
    """Map entities to wiki slugs; prefer 一事一页 fact pages, then entity pages."""
    slugs: list[str] = []
    seen = set()

    def _add(slug: Optional[str]):
        if slug and slug not in seen:
            seen.add(slug)
            slugs.append(slug)

    # Prefer fact pages where BOTH endpoints were recalled; then one-sided; cap for RAG
    both = edge_pages_for_entities(entities, both_ends=True)
    either = edge_pages_for_entities(entities, both_ends=False)
    for slug in both + either:
        _add(slug)
        if len(slugs) >= 10:
            break

    for ent in entities:
        _add(ENTITY_SLUGS.get(ent))
        if len(slugs) >= 14:
            break
    for name, slug in ENTITY_SLUGS.items():
        if name in question:
            _add(slug)

    # Index hubs when question mentions relation families
    if re.search(r"相互作用|联合用药", question):
        _add(SAFETY_PAGES.get("interactions"))
    if re.search(r"禁忌|加药|不能用|不宜", question):
        _add(SAFETY_PAGES.get("contraindications"))
    if re.search(r"起搏器|MRI|设备", question):
        _add(SAFETY_PAGES.get("device"))
    if _RENAL_THRESHOLD_RE.search(question):
        _add(SAFETY_PAGES.get("renal_dosing"))
    if _ADR_SKIN_RE.search(question):
        _add(SAFETY_PAGES.get("adverse_reaction"))
        _add(SAFETY_PAGES.get("adr_grading"))
    if _RENAL_THRESHOLD_RE.search(question) or re.search(
        r"抗菌药.*剂量|剂量.*抗菌", question
    ):
        _add(SAFETY_PAGES.get("antibiotic_renal"))
    if _OUT_OF_SCOPE_RE.search(question):
        _add(SAFETY_PAGES.get("out_of_scope"))
    if re.search(r"Child-Pugh|肝功能不全|肝损", question, re.I):
        _add(SAFETY_PAGES.get("hepatic_dosing"))
    if re.search(r"氯吡格雷|脑卒中.*预防", question):
        _add("用药安全/对比-阿司匹林与氯吡格雷-卒中预防")

    return slugs


def load_source_page(slug: str, max_chars: int = 8000) -> str:
    path = KB_ROOT / f"{slug}.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    return text.strip()[:max_chars]


def series_coverage_gap(result: GraphRecallResult) -> Optional[str]:
    """If IN_SERIES recall returns fewer products than series page declares, return series slug."""
    if result.template_id != "product_in_series" or not result.rows:
        return None
    row = result.rows[0]
    series_name = row.get("series", "")
    products = row.get("products", [])
    graph_count = len(products) if isinstance(products, list) else (1 if products else 0)
    series_slug = ENTITY_SLUGS.get(series_name)
    if not series_slug:
        return None
    body = load_source_page(series_slug, max_chars=12000)
    m = re.search(r"共\s*\*\*(\d+)\*\*", body)
    if m and graph_count < int(m.group(1)):
        return series_slug
    return None


def recall(question: str) -> GraphRecallResult:
    if not in_graph_slice(question):
        return GraphRecallResult(hit=False)

    tid, title, cypher, layer = _pick_template(question)
    if tid == "no_match" or not cypher.strip():
        return GraphRecallResult(hit=False)

    try:
        rows = _run_cypher(cypher)
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
    p = _detect_patient(question)
    if p and p not in entities:
        entities.insert(0, p)
    for canon in canonicalize_mentioned(question):
        if canon not in entities:
            entities.append(canon)

    if not template_matches_question(question, tid, entities):
        fb_tid, fb_title, fb_cypher, fb_layer = _fallback_drug_template(question)
        if fb_tid != "no_match":
            tid, title, cypher, layer = fb_tid, fb_title, fb_cypher, fb_layer
            rows = _run_cypher(cypher)
            entities = _entities_from_rows(rows)
            for canon in canonicalize_mentioned(question):
                if canon not in entities:
                    entities.append(canon)

    slugs = _slugs_for_entities(entities, question)
    return GraphRecallResult(
        hit=True,
        template_id=tid,
        title=title,
        layer=layer,
        entities=entities,
        facts_text=_format_facts(title, layer, rows),
        rows=rows,
        source_slugs=slugs,
    )


def build_context_block(result: GraphRecallResult) -> tuple[str, list[str]]:
    if not result.hit:
        return "", []
    parts = [result.facts_text]
    loaded = []
    for slug in result.source_slugs:
        body = load_source_page(slug)
        if body:
            parts.append(f"## {slug}\n{body}")
            loaded.append(slug)
    return "\n\n---\n\n".join(parts), loaded
