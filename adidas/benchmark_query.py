#!/usr/bin/env python3
"""Benchmark runner — parse 测试问题集.txt, report graph/FTS metrics."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import graph_recall as gr  # noqa: E402
import local_wiki_search as wiki_search  # noqa: E402

BENCH_FILE = ROOT / "测试问题集.txt"
REPORT_DIR = ROOT / "_meta" / "benchmark_reports"
CASE_RE = re.compile(r"^(L\d+-\d+|S-\d+)\.\s*(.+)$")

S_TEMPLATE_EXPECT = {
    "S-01": "products_by_tech",
    "S-02": "product_in_series",
    "S-03": "products_in_category",
    "S-04": "products_by_type",
    "S-05": "series_tech",
    "S-06": "products_by_type",
    "S-07": "products_in_category",
    "S-08": "products_by_tech",
    "S-09": "products_by_tech",
    "S-10": "product_in_series",
    "S-11": "products_in_category",
    "S-12": "products_by_type",
    "S-13": "products_by_tech",
    "S-14": None,  # out of slice
}


def load_cases(path: Path) -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    if not path.is_file():
        raise SystemExit(f"Benchmark file not found: {path}")

    in_l = in_s = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("第二节"):
            in_l, in_s = True, False
            continue
        if line.startswith("第三节"):
            in_l, in_s = False, True
            continue
        if line.startswith("第四节"):
            in_l = in_s = False
            continue
        if not (in_l or in_s):
            continue
        m = CASE_RE.match(line.strip())
        if not m:
            continue
        case_id, q = m.group(1), m.group(2).strip()
        if len(q) < 2:
            continue
        cases.append((case_id, q))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", default=True, help="skip rewrite/LLM (default)")
    ap.add_argument("--with-llm", action="store_true", help="enable rewrite if key present")
    args = ap.parse_args()
    no_llm = not args.with_llm

    cases = load_cases(BENCH_FILE)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"benchmark_{ts}.md"

    lines = [
        f"# adidas benchmark {ts}",
        f"- cases: {len(cases)}",
        f"- no_llm: {no_llm}",
        "",
        "| id | question | graph_hit | template | expect | rows | fts | ok |",
        "|---|---|---|---|---|---|---|---|",
    ]

    ok_n = 0
    for case_id, q in cases:
        r = gr.recall(q)
        fts = wiki_search.search(q, limit=3) if (not r.hit or not r.rows) else []
        expect = S_TEMPLATE_EXPECT.get(case_id)
        if case_id.startswith("S-"):
            if expect is None:
                ok = not r.hit
            else:
                ok = r.hit and r.template_id == expect and not r.error
        else:
            ok = True  # L soft
            if r.hit and r.error:
                ok = False
        if ok:
            ok_n += 1
        lines.append(
            f"| {case_id} | {q} | {r.hit} | {r.template_id or '-'} | {expect if case_id.startswith('S-') else '-'} "
            f"| {len(r.rows)} | {len(fts)} | {'PASS' if ok else 'FAIL'} |"
        )
        print(
            f"[{'PASS' if ok else 'FAIL'}] {case_id} hit={r.hit} tid={r.template_id} "
            f"rows={len(r.rows)} fts={len(fts)} | {q}"
        )

    lines.append("")
    lines.append(f"**score**: {ok_n}/{len(cases)}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport: {report_path}")
    print(f"Score: {ok_n}/{len(cases)}")
    # Fail CI-style only if any S-* failed
    s_fail = any(
        line.startswith("| S-") and line.endswith("| FAIL |") for line in lines
    )
    raise SystemExit(1 if s_fail else 0)


if __name__ == "__main__":
    main()
