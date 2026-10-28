#!/usr/bin/env python3
"""Extract Neo4j-ready nodes/edges from Wiki fact pages.

Wiki is the sole fact ontology:
  - kind: entity  → node (Patient / Drug / Condition / Product / …)
  - kind: edge    → one relationship (一事一页)
  - HAS_RECORD is derived when a Patient participates in clinical edges

Human prose on fact pages is never parsed — only `graph:` frontmatter.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml

KB_ROOT = Path(__file__).resolve().parent.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))

SYMMETRIC_RELS = frozenset({"INTERACTS_WITH", "CONTRAINDICATED_WITH"})

AUDITED_RELS = frozenset({
    "HAS_RECORD",
    "DIAGNOSES",
    "PRESCRIBES",
    "ORDERS",
    "SHOWS",
    "USES",
    "ALLERGIC_TO",
    "INTERACTS_WITH",
    "TREATS",
    "CONTRAINDICATED_FOR",
    "CONTRAINDICATED_WITH",
    "IN_SERIES",
    "USES_TECH",
    "INDICATED_FOR",
    "HAS_INGREDIENT",
})

# Clinical edges whose `from` is Patient but Neo4j stores via Record
VIA_RECORD = frozenset({"DIAGNOSES", "PRESCRIBES", "ORDERS"})

# Directory → edge type (authoring contract; experts pick folder, system owns type)
FOLDER_TO_REL: Dict[str, str] = {
    "临床事实/诊断": "DIAGNOSES",
    "临床事实/处方": "PRESCRIBES",
    "临床事实/过敏": "ALLERGIC_TO",
    "临床事实/医嘱检查": "ORDERS",
    "临床事实/医嘱手术": "ORDERS",
    "临床事实/检查提示": "SHOWS",
    "临床事实/设备使用": "USES",
    "用药安全/相互作用": "INTERACTS_WITH",
    "用药安全/禁忌": "CONTRAINDICATED_FOR",
    "用药安全/设备互斥": "CONTRAINDICATED_WITH",
    "用药安全/治疗": "TREATS",
    "产品桥接/含成分": "HAS_INGREDIENT",
    "产品桥接/适应症": "INDICATED_FOR",
    "产品桥接/系列归属": "IN_SERIES",
    "产品桥接/采用技术": "USES_TECH",
}


def _load_entity_map() -> Dict[str, str]:
    path = KB_ROOT / "graph-entity-map.yml"
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in (raw.get("entities") or {}).items()}


def infer_rel_from_path(rel_slug: str) -> Optional[str]:
    """Infer closed-set edge type from fact-page directory."""
    parent = str(Path(rel_slug).parent).replace("\\", "/")
    return FOLDER_TO_REL.get(parent)


def _normalize_aliases(raw) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: List[str] = []
    seen = set()
    for a in raw:
        s = str(a).strip()
        if len(s) < 2 or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def build_alias_index(extracted: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Map alias (and canonical name) → canonical entity name."""
    data = extracted or extract()
    index: Dict[str, str] = {}
    for n in data["nodes"]:
        name = n["name"]
        index[name] = name
        for alias in _normalize_aliases((n.get("props") or {}).get("aliases")):
            # First writer wins; lint will flag collisions
            index.setdefault(alias, name)
    return index


def resolve_canonical(name: str, alias_index: Optional[Dict[str, str]] = None) -> str:
    idx = alias_index if alias_index is not None else build_alias_index()
    return idx.get(name, name)


def path_type_mismatches() -> List[str]:
    """Fact pages whose directory disagrees with graph.type (authoring drift)."""
    issues: List[str] = []
    for path in _iter_wiki_md_paths():
        fm = _parse_fm(path)
        g = fm.get("graph")
        if not isinstance(g, dict) or g.get("kind") != "edge":
            continue
        rel_slug = str(path.relative_to(KB_ROOT).with_suffix("")).replace("\\", "/")
        expected = infer_rel_from_path(rel_slug)
        actual = g.get("type")
        if expected and actual and actual != expected:
            issues.append(f"{rel_slug}: type={actual} folder_expects={expected}")
    return issues

def _parse_fm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def _edge_key(rel: str, a_label: str, a: str, b_label: str, b: str) -> Tuple:
    if rel in SYMMETRIC_RELS:
        left, right = sorted([(a_label, a), (b_label, b)])
        return (rel, left[0], left[1], right[0], right[1])
    return (rel, a_label, a, b_label, b)


def _add_node(nodes: Dict[Tuple[str, str], dict], label: str, name: str, props: Optional[dict] = None, source: str = ""):
    key = (label, name)
    existing = nodes.get(key, {"label": label, "name": name, "props": {}, "sources": []})
    if props:
        existing["props"].update({k: v for k, v in props.items() if k != "name"})
    if source and source not in existing["sources"]:
        existing["sources"].append(source)
    nodes[key] = existing


def _add_edge(
    edges: Dict[Tuple, dict],
    rel: str,
    a_label: str,
    a: str,
    b_label: str,
    b: str,
    source: str = "",
):
    key = _edge_key(rel, a_label, a, b_label, b)
    if rel in SYMMETRIC_RELS:
        (_, al, an, bl, bn) = key
        a_label, a, b_label, b = al, an, bl, bn
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


def _iter_wiki_md_paths() -> Iterable[Path]:
    try:
        from config import CLINICAL_DIRS, BRIDGE_DIRS, CONCEPT_DIRS, PRODUCT_DIRS
    except Exception:
        CLINICAL_DIRS = ["临床病例", "用药安全", "临床事实"]
        BRIDGE_DIRS = ["疾病", "成分", "设备", "产品桥接"]
        CONCEPT_DIRS = ["技术平台", "产品系列"]
        PRODUCT_DIRS = ["处方药", "OTC药品", "医疗器械"]

    dirs = list(CLINICAL_DIRS) + list(BRIDGE_DIRS) + list(CONCEPT_DIRS) + list(PRODUCT_DIRS)
    seen: Set[Path] = set()
    for d in dirs:
        root = KB_ROOT / d
        if not root.is_dir():
            continue
        for md in root.rglob("*.md"):
            if md.name == "index.md":
                continue
            if md in seen:
                continue
            seen.add(md)
            yield md


def _ensure_patient_record(nodes, edges, patient: str, source: str):
    _add_node(nodes, "Patient", patient, source=source)
    rec = f"R-{patient}"
    _add_node(nodes, "Record", rec, source=source)
    _add_edge(edges, "HAS_RECORD", "Patient", patient, "Record", rec, source=source)
    return rec


def _process_page(path: Path, nodes: Dict, edges: Dict) -> None:
    fm = _parse_fm(path)
    g = fm.get("graph")
    if not g or not isinstance(g, dict):
        return
    rel_slug = str(path.relative_to(KB_ROOT).with_suffix("")).replace("\\", "/")
    kind = g.get("kind")

    # Legacy: pages with label+edges (pre-migration) — ignore edges if kind missing but has label
    if kind is None and g.get("label"):
        kind = "entity"
    if kind is None and g.get("type") and ("from" in g or "to" in g):
        kind = "edge"
    # Legacy aggregate with only edges list
    if kind is None and g.get("edges"):
        # skip — should have been migrated
        return

    if kind == "entity":
        label = g.get("label")
        props = dict(g.get("props") or {})
        name = props.get("name")
        # Prefer graph.aliases; fall back to props.aliases
        aliases = _normalize_aliases(g.get("aliases") or props.get("aliases"))
        if aliases:
            props["aliases"] = aliases
        if label and name:
            _add_node(nodes, label, name, props, source=rel_slug)
        return

    if kind != "edge":
        return

    rel = g.get("type") or infer_rel_from_path(rel_slug)
    if not rel:
        return
    a = str(g.get("from", ""))
    b = str(g.get("to", ""))
    a_lab = g.get("from_label") or "Entity"
    b_lab = g.get("to_label") or "Entity"
    if not a or not b:
        return

    to_props = dict(g.get("to_props") or {})
    from_props = dict(g.get("from_props") or {})

    # Patient clinical edges → via Record
    if rel in VIA_RECORD and a_lab == "Patient":
        rec = _ensure_patient_record(nodes, edges, a, rel_slug)
        _add_node(nodes, b_lab, b, to_props, source=rel_slug)
        _add_edge(edges, rel, "Record", rec, b_lab, b, source=rel_slug)
        return

    if rel == "ALLERGIC_TO" and a_lab == "Patient":
        _add_node(nodes, "Patient", a, from_props, source=rel_slug)
        _add_node(nodes, b_lab, b, to_props, source=rel_slug)
        _add_edge(edges, rel, "Patient", a, b_lab, b, source=rel_slug)
        return

    _add_node(nodes, a_lab, a, from_props, source=rel_slug)
    _add_node(nodes, b_lab, b, to_props, source=rel_slug)
    _add_edge(edges, rel, a_lab, a, b_lab, b, source=rel_slug)


def extract() -> Dict[str, Any]:
    nodes: Dict[Tuple[str, str], dict] = {}
    edges: Dict[Tuple, dict] = {}
    for path in _iter_wiki_md_paths():
        _process_page(path, nodes, edges)

    # Ensure Patient entity pages still create HAS_RECORD placeholder? Only if they have clinical edges.
    # Also ensure entity-only Patients still exist as nodes
    return {
        "nodes": sorted(nodes.values(), key=lambda n: (n["label"], n["name"])),
        "edges": sorted(edges.values(), key=lambda e: (e["type"], e["from"], e["to"])),
    }


def edge_signature_set(extracted: Optional[Dict[str, Any]] = None) -> Set[Tuple]:
    data = extracted or extract()
    out: Set[Tuple] = set()
    for e in data["edges"]:
        if e["type"] not in AUDITED_RELS:
            continue
        out.add(_edge_key(e["type"], e["from_label"], e["from"], e["to_label"], e["to"]))
    return out


def edge_pages_for_entities(entity_names: List[str], extracted: Optional[Dict[str, Any]] = None, both_ends: bool = False) -> List[str]:
    """Return fact-page slugs whose edge endpoints intersect entity_names.

    If both_ends=True, only edges where BOTH endpoints are in entity_names.
    """
    data = extracted or extract()
    names = set(entity_names)
    scored: List[Tuple[int, str]] = []
    seen = set()
    for e in data["edges"]:
        a_hit = e["from"] in names
        b_hit = e["to"] in names
        if both_ends and not (a_hit and b_hit):
            continue
        if not (a_hit or b_hit):
            continue
        score = 2 if (a_hit and b_hit) else 1
        for s in e.get("sources") or []:
            if s.startswith(("临床事实/", "用药安全/禁忌", "用药安全/相互作用", "用药安全/设备互斥", "用药安全/治疗", "产品桥接/")):
                if s not in seen:
                    seen.add(s)
                    scored.append((score, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [s for _, s in scored]


if __name__ == "__main__":
    data = extract()
    print(f"nodes={len(data['nodes'])} edges={len(data['edges'])}")
    from collections import Counter
    print("labels", Counter(n["label"] for n in data["nodes"]))
    print("rels", Counter(e["type"] for e in data["edges"]))
