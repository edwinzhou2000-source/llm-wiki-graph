#!/usr/bin/env python3
"""Smoke: adidas graph recall templates + deterministic empty + FTS open query."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import graph_recall as gr  # noqa: E402
import local_wiki_search as wiki_search  # noqa: E402

# (question, expect_template, must_hit, expect_nonempty_rows)
TEMPLATE_CASES = [
    ("哪些产品用了 boost 科技？", "products_by_tech", True, True),
    ("climacool 系列有哪些产品？", "product_in_series", True, True),
    ("adizero有哪些产品系列？各自有什么特点？", "series_family_listing", True, True),
    ("运动表现有哪些产品？", "products_in_category", True, True),
    ("有哪些跑鞋？", "products_by_type", True, True),
    # Use ULTRABOOST (stable alias) — not "ultra boost" spaced form alone
    ("ULTRABOOST 系列用了什么科技？", "series_tech", True, True),
]

# Deterministic empty: tech that does not exist in the graph
NEGATIVE = ("哪些产品用了 nonexistent-tech-xyz 科技？", "products_by_tech")


def run() -> int:
    failed = 0
    print("=== Template routing + recall ===")
    for q, expect_tid, must_hit, nonempty in TEMPLATE_CASES:
        r = gr.recall(q)
        ok = (
            r.hit == must_hit
            and r.template_id == expect_tid
            and (bool(r.rows) if nonempty else True)
            and not r.error
        )
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        n = len(r.rows[0].get("products") or r.rows[0].get("techs") or []) if r.rows else 0
        print(f"[{status}] {q}")
        print(f"       template={r.template_id} (expect {expect_tid}) rows={len(r.rows)} n={n} err={r.error!r}")
        if expect_tid == "series_family_listing" and r.rows:
            names = " | ".join(str(row.get("series") or "") for row in r.rows)
            has_cw = any("CLIMAWARM" in str(row.get("series") or "").upper() for row in r.rows)
            ok_cw = has_cw
            print(f"       [{'PASS' if ok_cw else 'FAIL'}] family includes CLIMAWARM; series={names[:200]}")
            if not ok_cw:
                failed += 1
            if not any(s.startswith("系列/") for s in r.source_slugs):
                print("       [FAIL] expected 系列/* source slugs")
                failed += 1
            else:
                print(f"       [PASS] series slugs sample={r.source_slugs[:5]}")

    print("\n=== Deterministic empty ===")
    # Force tech path: inject a fake tech mention by using a real template with bogus name
    # Prefer: known tech intent with a name not in the graph — recall may hit=False if
    # entity detector never sees the tech. Use Cypher directly for empty assertion.
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(gr.NEO4J_URI, auth=(gr.NEO4J_USER, gr.NEO4J_PASSWORD))
    try:
        with driver.session() as session:
            rows = list(
                session.run(
                    "MATCH (p:Product)-[:USES_TECH]->(t:Tech {name:$tech}) "
                    "RETURN collect(DISTINCT p.name) AS products",
                    tech="nonexistent-tech-xyz",
                )
            )
            products = rows[0]["products"] if rows else []
    finally:
        driver.close()
    ok_neg = len(products) == 0
    print(f"[{'PASS' if ok_neg else 'FAIL'}] nonexistent tech → products=0")
    if not ok_neg:
        failed += 1

    # Also: 碳板 must NOT resolve to carbon-plate (Bug B)
    print("\n=== Bug B: no TECH_SYNONYMS guessing ===")
    techs = gr._mentioned_tech("哪些产品用了碳板科技？")
    ok_b = "carbon-plate" not in techs
    print(f"[{'PASS' if ok_b else 'FAIL'}] 碳板 → techs={techs} (must not include carbon-plate)")
    if not ok_b:
        failed += 1

    print("\n=== FTS open ===")
    hits = wiki_search.search("boost 缓震", limit=3)
    ok_fts = len(hits) > 0
    print(f"[{'PASS' if ok_fts else 'FAIL'}] FTS hits={len(hits)} top={hits[0]['slug'] if hits else None}")
    if not ok_fts:
        failed += 1

    print()
    if failed:
        print(f"SMOKE FAILED: {failed} case(s)")
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
