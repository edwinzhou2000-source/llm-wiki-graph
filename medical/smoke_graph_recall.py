#!/usr/bin/env python3
"""Smoke: Wiki↔Neo4j audit + dual-layer graph recall + local Wiki open search."""

import subprocess
import sys
from pathlib import Path

import graph_recall as gr
import local_wiki_search as wiki_search

ROOT = Path(__file__).resolve().parent

CASES = [
    ("王强正在吃的药里有没有相互作用？", True, "clinical", ["华法林", "阿司匹林"], ["用药安全/相互作用/", "临床事实/"]),
    ("李娜对什么药过敏？", True, "clinical", ["青霉素"], ["临床事实/过敏/", "成分/"]),
    ("给王强加二甲双胍有无禁忌？", True, "clinical", ["慢性肾病"], ["用药安全/禁忌/", "临床事实/"]),
    ("福顺心血管系列里用了缓释技术的产品有哪些？", True, "product", ["福顺降压片"], ["产品桥接/", "处方药/"]),
    ("哪些产品含二甲双胍？", True, "product", ["福顺降糖片"], ["产品桥接/含成分/", "成分/"]),
    ("王强有慢性肾病，库里哪些含相关禁忌成分的福顺产品不能用？", True, "cross", ["二甲双胍"], ["用药安全/禁忌/", "产品桥接/", "临床事实/"]),
    ("青霉素相关药品和禁忌有什么？", True, "cross", ["青霉素"], ["用药安全/禁忌/青霉素", "产品桥接/含成分/福顺普洛欣", "成分/青霉素"]),
    ("青霉素有哪些相关产品？哪些相关禁忌？", True, "cross", ["青霉素", "福顺普洛欣"], ["用药安全/禁忌/青霉素", "产品桥接/含成分/福顺普洛欣"]),
    ("李娜不能用什么抗生素？", True, "clinical", ["青霉素", "福顺普洛欣"], ["临床事实/过敏/李娜-青霉素", "用药安全/禁忌/"]),
    ("盘尼西林有什么禁忌？", True, "clinical", ["青霉素"], ["用药安全/禁忌/青霉素"]),
    ("福顺普洛欣的主要活性成分是什么？", True, "product", ["福顺普洛欣"], ["处方药/"]),
    ("福顺普洛欣和青霉素是什么关系？", True, "product", ["青霉素", "福顺普洛欣"], ["产品桥接/", "成分/"]),
    ("今天天气怎么样？", False, "", [], []),
]

TEMPLATE_ASSERTIONS = {
    "青霉素相关药品和禁忌有什么？": "drug_overview",
    "青霉素有哪些相关产品？哪些相关禁忌？": "drug_overview",
    "福顺心血管系列有哪些产品": "product_in_series",
    "李娜不能用什么抗生素？": "patient_unsafe_meds",
    "盘尼西林有什么禁忌？": "ingredient_contraindications",
    "含氨氯地平的产品有哪些？": "products_by_ingredient",
    "福顺普洛欣的主要活性成分是什么？": "product_ingredients",
    "福顺普洛欣和青霉素是什么关系？": "products_by_ingredient",
}

# Paraphrase / alias cases (same intent, different wording)
PARAPHRASE_CASES = [
    ("青霉素关联的药品有哪些", "products_by_ingredient", ["青霉素"]),
    ("penicillin contraindications", "ingredient_contraindications", ["青霉素"]),
    ("李娜什么药不能用", "patient_unsafe_meds", ["青霉素"]),
]

# Open product questions — must hit local FTS without gbrain / without requiring graph hit
OPEN_PRODUCT = [
    ("有什么缓释降糖", ["降糖", "缓释", "二甲双胍"]),
    ("福顺心血管系列有哪些产品", ["心血管", "降压", "福顺"]),
    ("含氨氯地平的产品", ["氨氯地平", "降压"]),
]


def _sync_wiki_graph(verbose: bool = True) -> None:
    import subprocess

    r = subprocess.run(
        [sys.executable, str(ROOT / "graph" / "sync_wiki_graph.py")],
        cwd=str(ROOT),
        capture_output=not verbose,
        text=True,
    )
    if r.returncode != 0 and verbose:
        print((r.stderr or r.stdout or "sync failed")[:400])


def run_audit() -> None:
    print("=== Wiki → Graph sync (pre-audit) ===")
    _sync_wiki_graph(verbose=True)
    print()

    r0 = subprocess.run(
        [sys.executable, str(ROOT / "graph" / "render_wiki_relations.py"), "--check"],
        cwd=str(ROOT),
    )
    if r0.returncode != 0:
        raise SystemExit("render_wiki_relations --check failed — run: python graph/render_wiki_relations.py")

    r = subprocess.run(
        [sys.executable, str(ROOT / "graph" / "audit_wiki_graph.py")],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        raise SystemExit("audit_wiki_graph failed — fix Wiki/Neo4j drift before recall smoke")


def run_gardener() -> None:
    """Report-only entity duplicate lint (never fails the smoke)."""
    print("=== Entity gardener lint (report-only) ===")
    subprocess.run(
        [sys.executable, str(ROOT / "graph" / "lint_entity_duplicates.py")],
        cwd=str(ROOT),
    )
    print()


def run_alias_smoke() -> int:
    """Aliases resolve to canonical names / slugs without gbrain."""
    from wiki_graph_extract import build_alias_index, resolve_canonical

    failed = 0
    idx = build_alias_index()
    cases = [
        ("盐酸二甲双胍", "二甲双胍", "成分/二甲双胍"),
        ("CKD", "慢性肾病", "疾病/慢性肾病"),
        ("metformin", "二甲双胍", "成分/二甲双胍"),
        ("penicillin", "青霉素", "成分/青霉素"),
        ("盘尼西林", "青霉素", "成分/青霉素"),
    ]
    print("=== Alias resolution smoke ===")
    for alias, expect_canon, expect_slug in cases:
        got = resolve_canonical(alias, idx)
        slug = gr.ENTITY_SLUGS.get(alias) or gr.ENTITY_SLUGS.get(got)
        ok = got == expect_canon and slug == expect_slug
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {alias} → {got} slug={slug}")
    print()
    return failed


def run_open_product() -> int:
    """Verify local_wiki_search returns product-ish pages for open questions."""
    failed = 0
    wiki_search.sync()
    print("=== Local Wiki open-product search (no gbrain) ===")
    for q, needles in OPEN_PRODUCT:
        hits = wiki_search.search(q, limit=8)
        blob = " ".join(f"{h['slug']} {h['content']}" for h in hits).lower()
        ok = len(hits) >= 1 and any(n.lower() in blob for n in needles)
        status = "PASS" if ok else "FAIL"
        if status == "FAIL":
            failed += 1
        top = hits[0]["slug"] if hits else "(none)"
        print(f"[{status}] {q}")
        print(f"  top={top} n={len(hits)} needles={needles}")
    print()
    return failed


def main():
    failed = 0
    assert gr.ENTITY_SLUGS, "graph-entity-map.yml failed to load"
    assert "图谱演示" not in str(list(gr.ENTITY_SLUGS.values()))

    print("=== Wiki↔Neo4j audit ===")
    run_audit()
    print()

    run_gardener()
    failed += run_alias_smoke()

    print("=== Graph recall smoke ===")
    for q, expect_hit, expect_layer, expect_ents, expect_slug_prefixes in CASES:
        r = gr.recall(q)
        ok_hit = r.hit == expect_hit
        ok_layer = (not expect_hit) or (r.layer == expect_layer)
        ok_template = TEMPLATE_ASSERTIONS.get(q, r.template_id) == r.template_id if expect_hit else True
        ok_ents = True
        ok_prefix = True
        if expect_hit and not r.error:
            ok_ents = all(e in r.entities for e in expect_ents)
            _, loaded = gr.build_context_block(r)
            ok_src = len(loaded) >= 1
            if expect_slug_prefixes:
                blob = " ".join(loaded)
                ok_prefix = any(p in blob for p in expect_slug_prefixes)
        else:
            loaded, ok_src = [], True

        status = "PASS" if (ok_hit and ok_layer and ok_template and ok_ents and ok_src and ok_prefix and not r.error) else "FAIL"
        if status == "FAIL":
            failed += 1
        print(f"[{status}] {q}")
        print(f"  hit={r.hit} layer={r.layer} template={r.template_id}")
        print(f"  entities={r.entities}")
        print(f"  sources={loaded} error={r.error!r}")
    print()

    # Series completeness: IN_SERIES should return all 14 福顺心血管 products
    print("=== Series IN_SERIES completeness ===")
    q_series = "福顺心血管系列有哪些产品"
    r_series = gr.recall(q_series)
    n_products = 0
    if r_series.rows:
        products = r_series.rows[0].get("products", [])
        n_products = len(products) if isinstance(products, list) else 0
    gap = gr.series_coverage_gap(r_series)
    ok_series = (
        r_series.template_id == "product_in_series"
        and n_products == 14
        and gap is None
    )
    if not ok_series:
        failed += 1
    print(f"[{'PASS' if ok_series else 'FAIL'}] {q_series}")
    print(f"  template={r_series.template_id} n_products={n_products} gap={gap!r}")
    print()

    print("=== Paraphrase / alias recall ===")
    for q, expect_tid, expect_ents in PARAPHRASE_CASES:
        r = gr.recall(q)
        ok = (
            r.hit
            and r.template_id == expect_tid
            and all(e in r.entities for e in expect_ents)
            and not r.error
        )
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {q}")
        print(f"  template={r.template_id} entities={r.entities} error={r.error!r}")
    print()

    failed += run_open_product()

    if failed:
        raise SystemExit(f"{failed} smoke case(s) failed")
    print("All wiki-graph + local-search smoke cases passed.")


if __name__ == "__main__":
    main()
