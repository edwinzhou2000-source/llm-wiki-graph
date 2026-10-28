#!/usr/bin/env python3
"""Build 关系索引.md from Wiki fact pages (does NOT rewrite expert prose)."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import yaml

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))
if str(GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_DIR))

from wiki_graph_extract import _load_entity_map, extract  # noqa: E402

REL_ZH = {
    "DIAGNOSES": "诊断",
    "PRESCRIBES": "处方用药",
    "ALLERGIC_TO": "过敏",
    "INTERACTS_WITH": "药物相互作用",
    "CONTRAINDICATED_FOR": "用药禁忌",
    "CONTRAINDICATED_WITH": "设备互斥",
    "TREATS": "治疗",
    "HAS_INGREDIENT": "含有成分",
    "INDICATED_FOR": "适应症",
    "IN_SERIES": "所属系列",
    "USES_TECH": "采用技术",
    "ORDERS": "医嘱",
    "SHOWS": "检查提示",
    "USES": "使用设备",
    "HAS_RECORD": "病历记录",
}

LABEL_DIR = {
    "Patient": "临床病例",
    "Drug": "成分",
    "Condition": "疾病",
    "Device": "设备",
    "Series": "产品系列",
    "TechPlatform": "技术平台",
}


def _wikilink(name: str, label: Optional[str] = None) -> str:
    emap = _load_entity_map()
    if name in emap:
        return f"[[{emap[name]}|{name}]]"
    if label == "Patient":
        return f"[[临床病例/{name}病例|{name}]]"
    if label and label in LABEL_DIR:
        return f"[[{LABEL_DIR[label]}/{name}|{name}]]"
    return name


def render_index() -> None:
    data = extract()
    lines = [
        "---",
        "title: 关系索引",
        "type: 索引",
        "tags: [图关系, 事实本体]",
        "---",
        "",
        "# 关系索引",
        "",
        "> 由 Wiki **一事一页** 事实页汇总生成。每条边对应一篇可供医药专家修订的 Markdown。",
        "> Graph / Neo4j 仅作检索索引；问答时按边召回对应 Wiki 原文。",
        "",
        f"共 **{len(data['edges'])}** 条边 / **{len(data['nodes'])}** 个节点。",
        "",
    ]
    by_rel: Dict[str, List[dict]] = defaultdict(list)
    for e in data["edges"]:
        by_rel[e["type"]].append(e)

    for rel in sorted(by_rel.keys(), key=lambda r: REL_ZH.get(r, r)):
        zh = REL_ZH.get(rel, rel)
        items = by_rel[rel]
        lines.append(f"## {zh}（`{rel}`）")
        lines.append("")
        lines.append("| 起点 | 终点 | 事实页（请在此修订） |")
        lines.append("|------|------|----------------------|")
        for e in sorted(items, key=lambda x: (x["from"], x["to"])):
            a = _wikilink(e["from"], e["from_label"])
            b = _wikilink(e["to"], e["to_label"])
            srcs = e.get("sources") or []
            # Prefer fact pages (临床事实/用药安全/产品桥接) over entity pages
            fact = [s for s in srcs if s.startswith(("临床事实/", "用药安全/禁忌", "用药安全/相互作用", "用药安全/设备互斥", "用药安全/治疗", "产品桥接/"))]
            show = fact or srcs
            src_links = ", ".join(f"[[{s}]]" for s in show) if show else "—"
            lines.append(f"| {a} | {b} | {src_links} |")
        lines.append("")

    lines += [
        "## 维护约定",
        "",
        "1. **新增/修改关系**：新建或编辑对应事实页正文；文首 `graph:` 只保留 type/from/to",
        "2. `python graph/render_wiki_relations.py` — 刷新本索引",
        "3. `python graph/load_data.py` — 灌 Neo4j",
        "4. `python graph/audit_wiki_graph.py` — Wiki ↔ Neo4j 校验",
        "",
    ]
    out = KB_ROOT / "关系索引.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out.relative_to(KB_ROOT)} edges={len(data['edges'])}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="ensure 关系索引.md exists and extract succeeds")
    args = ap.parse_args()
    data = extract()
    if args.check:
        if not (KB_ROOT / "关系索引.md").is_file():
            print("MISSING 关系索引.md")
            raise SystemExit(1)
        if len(data["edges"]) < 1:
            print("NO edges extracted")
            raise SystemExit(1)
        print(f"check ok edges={len(data['edges'])}")
        raise SystemExit(0)
    render_index()


if __name__ == "__main__":
    main()
