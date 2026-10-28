#!/usr/bin/env python3
"""render_wiki_relations.py — Build 关系索引.md from the derived typed graph.

Unlike medical, there is no 事实页 to edit — each edge points back to the
product/科技/系列 page that DECLARED it (via frontmatter). This index is a
read-only overview; the actual fact lives in the source page.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))

from graph.wiki_graph_extract import extract  # noqa: E402

REL_ZH = {
    "IN_SERIES": "所属系列",
    "USES_TECH": "采用科技",
    "IN_CATEGORY": "归属品类",
    "HAS_TYPE": "产品类型",
    "SERIES_USES_TECH": "系列科技",
}


def render_index() -> None:
    data = extract()
    edges = data["edges"]
    lines = [
        "---",
        "title: 关系索引",
        "type: 索引",
        "tags: [图关系, 类型化边]",
        "---",
        "",
        "# 关系索引",
        "",
        "> 由产品/科技/系列页 **frontmatter 字段**确定性派生（非一事一页边页）。",
        "> 每条边指向声明它的源页面；正文即源页面，无独立事实页。",
        "",
        f"共 **{len(edges)}** 条边 / **{len(data['nodes'])}** 个节点。",
        "",
    ]
    by_rel: dict[str, list] = defaultdict(list)
    for e in edges:
        by_rel[e["type"]].append(e)

    for rel in sorted(by_rel.keys(), key=lambda r: REL_ZH.get(r, r)):
        zh = REL_ZH.get(rel, rel)
        items = by_rel[rel]
        lines.append(f"## {zh}（`{rel}`）· {len(items)} 条")
        lines.append("")
        lines.append("| 起点 | 终点 | 源页面 |")
        lines.append("|------|------|--------|")
        for e in sorted(items, key=lambda x: (x["from"], x["to"]))[:200]:
            src = (e.get("sources") or ["—"])[0]
            a = e["from"]
            b = e["to"]
            if e["from_label"] in ("Product", "Series") and e["from"]:
                a = f"[[{src or e['from']}|{e['from']}]]"
            lines.append(f"| {a} | {b} | {src} |")
        if len(items) > 200:
            lines.append(f"| … | 其余 {len(items)-200} 条略 | |")
        lines.append("")

    lines += [
        "## 维护约定",
        "",
        "1. **边不单独开页**：关系是产品页 frontmatter 的字段（`series`/`tags`/`type`）",
        "2. 改关系 → 改源产品页 frontmatter 或 科技/系列页",
        "3. `python graph/wiki_graph_extract.py` — 重新派生图",
        "4. `python graph/render_wiki_relations.py` — 刷新本索引",
        "",
    ]
    out = KB_ROOT / "关系索引.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote 关系索引.md  edges={len(edges)} nodes={len(data['nodes'])}")


if __name__ == "__main__":
    render_index()
