#!/usr/bin/env python3
"""Migrate to one-Wiki-page-per-graph-edge (expert-editable prose).

- Creates 临床事实/ / 用药安全/{禁忌,相互作用,...} / 产品桥接/ fact pages
- Strips edges from entity pages (Patient/Drug/Product/... keep kind:entity only)
- HAS_RECORD remains derived (no expert page)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

KB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KB))
sys.path.insert(0, str(KB / "graph"))

from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "medical123")

PREFERRED = [
    "Patient", "Record", "Report", "Procedure", "Drug", "Device",
    "Condition", "Product", "Series", "TechPlatform",
]


def _pick(labels):
    labs = list(labels or [])
    for p in PREFERRED:
        if p in labs:
            return p
    return labs[0] if labs else "Entity"


def load_from_neo4j():
    """Snapshot current demo graph (pre-migration) as nodes/edges."""
    driver = GraphDatabase.driver(URI, auth=AUTH)
    nodes = []
    edges = []
    try:
        with driver.session() as session:
            for row in session.run(
                "MATCH (n) WHERE n.name IS NOT NULL RETURN labels(n) AS labs, n.name AS name, properties(n) AS props"
            ):
                lab = _pick(row["labs"])
                props = dict(row["props"] or {})
                props.pop("name", None)
                nodes.append({"label": lab, "name": row["name"], "props": props})
            for row in session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE a.name IS NOT NULL AND b.name IS NOT NULL
                RETURN type(r) AS rel, labels(a) AS al, a.name AS a,
                       labels(b) AS bl, b.name AS b
                """
            ):
                edges.append({
                    "type": row["rel"],
                    "from_label": _pick(row["al"]),
                    "from": row["a"],
                    "to_label": _pick(row["bl"]),
                    "to": row["b"],
                })
    finally:
        driver.close()
    return {"nodes": nodes, "edges": edges}

REL_DIR = {
    "DIAGNOSES": ("临床事实/诊断", "诊断"),
    "PRESCRIBES": ("临床事实/处方", "处方用药"),
    "ALLERGIC_TO": ("临床事实/过敏", "过敏"),
    "ORDERS": None,  # split by to_label below
    "SHOWS": ("临床事实/检查提示", "检查提示"),
    "USES": ("临床事实/设备使用", "使用设备"),
    "INTERACTS_WITH": ("用药安全/相互作用", "药物相互作用"),
    "CONTRAINDICATED_FOR": ("用药安全/禁忌", "用药禁忌"),
    "CONTRAINDICATED_WITH": ("用药安全/设备互斥", "设备互斥"),
    "TREATS": ("用药安全/治疗", "治疗"),
    "HAS_INGREDIENT": ("产品桥接/含成分", "含有成分"),
    "INDICATED_FOR": ("产品桥接/适应症", "适应症"),
    "IN_SERIES": ("产品桥接/系列归属", "所属系列"),
    "USES_TECH": ("产品桥接/采用技术", "采用技术"),
}

# Map Record name R-王强 → Patient 王强
def patient_of_record(name: str) -> str:
    if name.startswith("R-"):
        return name[2:]
    return name


def safe_name(s: str) -> str:
    s = s.replace("/", "-").replace("·", "-").replace(" ", "")
    return s


def wikilink(name: str, kind: str = "") -> str:
    # best-effort; entity map applied later in render
    mapping = {
        "Drug": f"成分/{name}",
        "Condition": f"疾病/{name}",
        "Device": f"设备/{name}",
        "Patient": f"临床病例/{name}病例",
        "Series": f"产品系列/{name}",
        "TechPlatform": f"技术平台/{name}",
    }
    if kind in mapping:
        return f"[[{mapping[kind]}|{name}]]"
    return name


def prose_template(rel: str, a: str, b: str, a_lab: str, b_lab: str, zh: str) -> str:
    return f"""# {a} — {zh} — {b}

> 本页是图谱关系 **`{rel}`** 的事实正文，供医药专家直接修订。
> 结构化声明仅在文首 `graph:` 中；大模型召回时优先加载本页全文。

## 结论

（请专家填写：一句话结论。）

- 起点：{wikilink(a, a_lab)}（`{a_lab}`）
- 关系：{zh}（`{rel}`）
- 终点：{wikilink(b, b_lab)}（`{b_lab}`）

## 详细说明

（请专家填写：机理、证据、适用边界、注意事项。）

## 相关链接

- 起点：{wikilink(a, a_lab)}
- 终点：{wikilink(b, b_lab)}
"""


def write_edge_page(
    rel: str,
    a: str,
    a_lab: str,
    b: str,
    b_lab: str,
    extra_props: Optional[dict] = None,
) -> str:
    if rel == "ORDERS":
        if b_lab == "Report":
            folder, zh = "临床事实/医嘱检查", "开具检查"
        else:
            folder, zh = "临床事实/医嘱手术", "施行手术"
    else:
        folder, zh = REL_DIR[rel]

    fname = f"{safe_name(a)}-{safe_name(b)}.md"
    # For patient-routed edges, use patient name in filename not R-xxx
    if a_lab == "Record":
        a_display = patient_of_record(a)
        a_lab_out = "Patient"
        a_graph = a_display
        fname = f"{safe_name(a_display)}-{safe_name(b)}.md"
    else:
        a_display = a
        a_lab_out = a_lab
        a_graph = a

    rel_path = f"{folder}/{fname[:-3]}"
    path = KB / f"{rel_path}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    graph: Dict[str, Any] = {
        "kind": "edge",
        "type": rel if rel != "ORDERS" else "ORDERS",
        "from": a_graph,
        "from_label": a_lab_out,
        "to": b,
        "to_label": b_lab,
    }
    if extra_props:
        graph["to_props"] = extra_props

    # Prefer ORDERS subtype clarity in title
    title = f"{a_display} {zh} {b}"
    body = prose_template(graph["type"], a_display, b, a_lab_out, b_lab, zh)
    fm = {
        "title": title,
        "type": zh,
        "entity_kind": "关系事实",
        "tags": ["事实页", zh],
        "graph": graph,
    }
    text = "---\n" + yaml.dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n" + body
    path.write_text(text, encoding="utf-8")
    return rel_path


def strip_to_entity(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return
    parts = text.split("---", 2)
    fm = yaml.safe_load(parts[1]) or {}
    g = fm.get("graph")
    if not isinstance(g, dict):
        return
    label = g.get("label")
    props = g.get("props") or {}
    if not label:
        # safety aggregate pages — remove graph entirely
        fm.pop("graph", None)
    else:
        fm["graph"] = {"kind": "entity", "label": label, "props": props}
    # Remove auto-generated relation blocks from body
    body = parts[2]
    body = re.sub(
        r"\n?<!-- graph-relations:start -->.*?<!-- graph-relations:end -->\n?",
        "\n",
        body,
        flags=re.S,
    )
    dumped = yaml.dump(fm, allow_unicode=True, sort_keys=False)
    path.write_text(f"---\n{dumped}---{body}", encoding="utf-8")
    print("entity-only", path.relative_to(KB))


def write_folder_index(folder: str, title: str, pages: List[str]) -> None:
    path = KB / folder / "index.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"title: {title}",
        f"type: {title}",
        "tags: [事实索引]",
        "---",
        "",
        f"# {title}",
        "",
        "> 一事一页：每条图谱关系对应一篇可人工修订的正文。",
        "",
    ]
    for slug in sorted(pages):
        lines.append(f"- [[{slug}]]")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    data = load_from_neo4j()
    print(f"snapshot neo4j nodes={len(data['nodes'])} edges={len(data['edges'])}")
    pages_by_folder: Dict[str, List[str]] = {}
    created = []

    # Collect Report/Procedure props from nodes
    node_props = {(n["label"], n["name"]): n.get("props") or {} for n in data["nodes"]}

    for e in data["edges"]:
        rel = e["type"]
        if rel == "HAS_RECORD":
            continue  # derived
        a, a_lab = e["from"], e["from_label"]
        b, b_lab = e["to"], e["to_label"]
        extra = None
        if rel == "ORDERS" and b_lab in ("Report", "Procedure"):
            extra = dict(node_props.get((b_lab, b), {}))
            if not extra:
                extra = None
        slug = write_edge_page(rel, a, a_lab, b, b_lab, extra)
        created.append(slug)
        folder = str(Path(slug).parent)
        pages_by_folder.setdefault(folder, []).append(slug)
        print("fact", slug)

    # Strip entity pages under known dirs
    for pattern in [
        "临床病例/*.md",
        "成分/*.md",
        "疾病/*.md",
        "设备/*.md",
        "产品系列/*.md",
        "技术平台/*.md",
        "用药安全/*.md",
        "处方药/**/*.md",
    ]:
        for path in KB.glob(pattern):
            if path.name == "index.md":
                continue
            if "用药安全/禁忌" in str(path) or "用药安全/相互作用" in str(path):
                continue
            if "用药安全/设备互斥" in str(path) or "用药安全/治疗" in str(path):
                continue
            strip_to_entity(path)

    # Folder indexes
    folder_titles = {
        "临床事实/诊断": "诊断事实",
        "临床事实/处方": "处方事实",
        "临床事实/过敏": "过敏事实",
        "临床事实/医嘱检查": "医嘱检查事实",
        "临床事实/医嘱手术": "医嘱手术事实",
        "临床事实/检查提示": "检查提示事实",
        "临床事实/设备使用": "设备使用事实",
        "用药安全/禁忌": "用药禁忌",
        "用药安全/相互作用": "药物相互作用",
        "用药安全/设备互斥": "设备互斥",
        "用药安全/治疗": "治疗关系",
        "产品桥接/含成分": "含成分桥接",
        "产品桥接/适应症": "适应症桥接",
        "产品桥接/系列归属": "系列归属桥接",
        "产品桥接/采用技术": "采用技术桥接",
    }
    for folder, title in folder_titles.items():
        write_folder_index(folder, title, pages_by_folder.get(folder, []))

    # Top indexes
    (KB / "临床事实").mkdir(exist_ok=True)
    (KB / "临床事实/index.md").write_text(
        "---\ntitle: 临床事实\ntype: 临床事实\ntags: [事实索引]\n---\n\n"
        "# 临床事实\n\n"
        "- [[临床事实/诊断/index|诊断]]\n"
        "- [[临床事实/处方/index|处方]]\n"
        "- [[临床事实/过敏/index|过敏]]\n"
        "- [[临床事实/医嘱检查/index|医嘱检查]]\n"
        "- [[临床事实/医嘱手术/index|医嘱手术]]\n"
        "- [[临床事实/检查提示/index|检查提示]]\n"
        "- [[临床事实/设备使用/index|设备使用]]\n",
        encoding="utf-8",
    )
    (KB / "产品桥接").mkdir(exist_ok=True)
    (KB / "产品桥接/index.md").write_text(
        "---\ntitle: 产品桥接\ntype: 产品桥接\ntags: [事实索引]\n---\n\n"
        "# 产品桥接\n\n"
        "- [[产品桥接/含成分/index|含成分]]\n"
        "- [[产品桥接/适应症/index|适应症]]\n"
        "- [[产品桥接/系列归属/index|系列归属]]\n"
        "- [[产品桥接/采用技术/index|采用技术]]\n",
        encoding="utf-8",
    )

    # Rewrite aggregate safety pages as indexes
    for agg, folder, title in [
        ("用药安全/药物禁忌规则.md", "用药安全/禁忌", "药物禁忌规则"),
        ("用药安全/药物相互作用规则.md", "用药安全/相互作用", "药物相互作用规则"),
        ("用药安全/设备禁忌规则.md", "用药安全/设备互斥", "设备禁忌规则"),
    ]:
        path = KB / agg
        pages = pages_by_folder.get(folder, [])
        links = "\n".join(f"- [[{s}]]" for s in sorted(pages))
        path.write_text(
            f"---\ntitle: {title}\ntype: 用药安全\ntags: [事实索引]\n---\n\n"
            f"# {title}\n\n> 已拆成一事一页，请在下列页面修订具体事实。\n\n{links}\n",
            encoding="utf-8",
        )
        print("index", agg)

    print(f"created {len(created)} fact pages")


if __name__ == "__main__":
    main()
