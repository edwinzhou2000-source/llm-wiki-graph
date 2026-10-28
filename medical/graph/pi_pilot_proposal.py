#!/usr/bin/env python3
"""Build (and optionally apply) a multipage 说明书提案包 for warfarin-style PI demo.

Does not call Hermes — deterministic draft for architecture smoke:
  成分/人参 + 用药安全/相互作用/华法林-人参

Usage:
  python graph/pi_pilot_proposal.py           # write pending proposal only
  python graph/pi_pilot_proposal.py --apply   # write Wiki pages + load Neo4j
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent
KB = GRAPH_DIR.parent
PROPOSALS = KB / "_proposals"
UPLOADS = KB / "raw" / "articles" / "_uploads"
SAMPLE = UPLOADS / "demo-华法林说明书.pi.txt"

ENTITY_MD = """---
title: 人参
type: 成分
entity_kind: 成分
tags:
- 桥接层
- 说明书试点
graph:
  kind: entity
  label: Drug
  aliases:
  - ginseng
  - 西洋参
  props:
    name: 人参
    category: 中药/保健
---

# 人参

> 说明书入库试点实体（演示用，非正式药材标准）。对应 Neo4j `Drug`。

## 概述

人参常作为保健品或中药配伍使用。与抗凝药合用时需关注药效干扰（见相互作用事实页）。
"""

EDGE_MD = """---
title: 华法林 药物相互作用 人参
type: 药物相互作用
entity_kind: 关系事实
tags:
- 事实页
- 药物相互作用
- 说明书试点
graph:
  kind: edge
  type: INTERACTS_WITH
  from: 华法林
  from_label: Drug
  to: 人参
  to_label: Drug
---

# 华法林 — 药物相互作用 — 人参

> 本页是图谱关系 **`INTERACTS_WITH`** 的事实正文（说明书入库试点）。
> 严重程度与机理写在正文，供药师审核与 RAG 加载；Neo4j 边仅作索引。

## 结论

**严重程度：中等（Moderate）。** 人参可能减弱华法林抗凝效果，联用时需加强 INR 监测（演示用语，非正式说明书）。

- 起点：[[成分/华法林|华法林]]（`Drug`）
- 关系：药物相互作用（`INTERACTS_WITH`）
- 终点：[[成分/人参|人参]]（`Drug`）

## 详细说明

演示场景摘自说明书「药物相互作用」小节草稿：

- 机制（示意）：可能诱导代谢或拮抗维生素 K 通路相关效应，导致抗凝减弱。
- 监测：联用期间更频繁复查 INR；必要时调整华法林剂量。
- 来源：试点文件 `raw/articles/_uploads/demo-华法林说明书.pi.txt`。

## 相关链接

- 起点：[[成分/华法林|华法林]]
- 终点：[[成分/人参|人参]]
"""

SAMPLE_TXT = """【演示说明书摘录 · 华法林片】

【药品名称】华法林钠片
【警告】
本品为抗凝药，治疗窗窄。用药期间需定期监测 INR，目标范围通常为 2.0–3.0（个体化调整）。
【相互作用】
与人参（ginseng）合用：可能减弱抗凝效果，建议加强 INR 监测（中等严重程度）。
与阿司匹林合用：增加出血风险（已有事实页，本试点不重复生成）。
【禁忌】活动性出血、妊娠、严重肝肾功能不全等（见禁忌事实页）。
【用法用量】
口服，成人常用起始剂量 2.5–5 mg/日，依 INR 调整（演示数据，非正式说明书）。
"""

WARFARIN_CONTRA_MD = """---
title: 华法林 禁忌 活动性出血
type: 禁忌
entity_kind: 关系事实
tags:
- 事实页
- 禁忌
- 说明书试点
graph:
  kind: edge
  type: CONTRAINDICATED_FOR
  from: 华法林
  from_label: Drug
  to: 活动性出血
  to_label: Condition
---

# 华法林 — 禁忌 — 活动性出血

> 摘自说明书「禁忌」小节试点。Neo4j 边 `CONTRAINDICATED_FOR`。

## 结论

**活动性出血患者禁用华法林**（演示用语）。

- 起点：[[成分/华法林|华法林]]
- 终点：活动性出血（临床状态）

## 说明书摘录

见 [[说明书/华法林钠片.pi|华法林钠片说明书摘录]]。
"""

WARFARIN_PI_MD = """---
title: 华法林钠片说明书摘录（试点）
type: 说明书
tags:
- 说明书试点
- PI
---

# 华法林钠片 — 说明书摘录（试点）

> 来源：`raw/articles/_uploads/demo-华法林说明书.pi.txt`。供 FTS / L4 数值与警告类问答测试。

## 警告

- 抗凝药，治疗窗窄；需定期监测 INR，常见目标 2.0–3.0。
- 与阿司匹林合用：出血风险增加。
- 与人参合用：可能减弱抗凝，需加强 INR 监测。

## 禁忌

活动性出血、妊娠、严重肝肾功能不全（演示列举）。

## 用法用量（演示）

口服，成人常用起始剂量 2.5–5 mg/日，根据 INR 调整。
"""



def build_proposal() -> dict:
    pages = [
        {
            "slug": "成分/人参",
            "title": "人参",
            "proposed_content": ENTITY_MD,
        },
        {
            "slug": "用药安全/相互作用/华法林-人参",
            "title": "华法林 药物相互作用 人参",
            "proposed_content": EDGE_MD,
        },
        {
            "slug": "用药安全/禁忌/华法林-活动性出血",
            "title": "华法林 禁忌 活动性出血",
            "proposed_content": WARFARIN_CONTRA_MD,
        },
        {
            "slug": "说明书/华法林钠片.pi",
            "title": "华法林钠片说明书摘录",
            "proposed_content": WARFARIN_PI_MD,
        },
    ]
    summary = "\n\n".join(
        f"### {p['title']} (`{p['slug']}`)\n\n"
        + p["proposed_content"].split("---", 2)[-1].strip()[:600]
        for p in pages
    )
    pack_id = "pi-ingest_demo-华法林说明书.pi.txt"
    slug = f"pi-ingest/{pack_id}"
    return {
        "title": f"说明书入库提案包（{len(pages)} 页）— demo-华法林说明书.pi.txt",
        "slug": slug,
        "source": "pi-ingest",
        "action": "create",
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_files": ["demo-华法林说明书.pi.txt"],
        "pages": pages,
        "proposed_content": f"# 提案包预览（共 {len(pages)} 页）\n\n{summary}\n",
    }


def write_proposal(proposal: dict) -> Path:
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(SAMPLE_TXT, encoding="utf-8")
    path = PROPOSALS / f"{proposal['slug'].replace('/', '_')}.json"
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def apply_pages(proposal: dict) -> list:
    written = []
    for page in proposal.get("pages") or []:
        slug = page["slug"]
        fpath = KB / f"{slug}.md"
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(page["proposed_content"], encoding="utf-8")
        written.append(slug)
        print(f"  wrote {slug}.md")
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write Wiki pages and run load_data.py")
    args = ap.parse_args(argv)

    proposal = build_proposal()
    path = write_proposal(proposal)
    print(f"proposal → {path}")
    print(f"  pages: {[p['slug'] for p in proposal['pages']]}")

    if not args.apply:
        print("Pending review. Approve in UI, or re-run with --apply.")
        return 0

    written = apply_pages(proposal)
    proposal["status"] = "approved"
    proposal["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    proposal["written_slugs"] = written
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(GRAPH_DIR / "load_data.py")],
        cwd=str(KB),
    )
    if r.returncode != 0:
        return r.returncode

    # Quick presence check via extract
    sys.path.insert(0, str(GRAPH_DIR))
    from wiki_graph_extract import extract

    data = extract()
    edge_ok = any(
        e["type"] == "INTERACTS_WITH"
        and {e["from"], e["to"]} == {"华法林", "人参"}
        for e in data["edges"]
    )
    contra_ok = any(
        e["type"] == "CONTRAINDICATED_FOR"
        and e.get("from") == "华法林"
        for e in data["edges"]
    )
    print(f"extract INTERACTS_WITH 华法林-人参: {'OK' if edge_ok else 'MISSING'}")
    print(f"extract CONTRAINDICATED_FOR 华法林: {'OK' if contra_ok else 'MISSING'}")
    return 0 if edge_ok and contra_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
