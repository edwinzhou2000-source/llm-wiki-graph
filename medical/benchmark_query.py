#!/usr/bin/env python3
"""Benchmark runner — parse 测试问题集.txt L/S cases, report graph/FTS/rewrite/E2E metrics."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import graph_recall as gr
import local_wiki_search as wiki_search

BENCH_FILE = ROOT / "测试问题集.txt"
REPORT_DIR = ROOT / "_meta" / "benchmark_reports"
CASE_RE = re.compile(r"^(L\d+-\d+|S-\d+)\.\s*(.+)$")
SKIP_PREFIXES = ("对应 ", "通道", "期望", "注：", "例：", "（", "若 ", "日期 ")

# Cases that must trigger rejection (no LLM answer with fabricated facts)
REJECT_CASE_IDS = frozenset({
    "L6-1", "L6-2", "L6-3", "L6-4", "L6-5", "L6-6",
})

# S-series graph template expectations
S_TEMPLATE_EXPECT = {
    "S-01": "drug_interaction",
    "S-02": "allergy",
    "S-03": "ingredient_contraindications",
    "S-04": "device_contra",
    "S-05": "product_series_tech",
    "S-06": "product_in_series",
    "S-07": "products_by_ingredient",
    "S-08": "products_by_ingredient",
    "S-09": "drug_overview",
    "S-10": "drug_overview",
    "S-11": "patient_unsafe_meds",
    "S-12": "patient_unsafe_meds",
    "S-13": "ingredient_contraindications",
    "S-14": "patient_overview",
}

# L-series soft template hints (industry-generic routing goals; not strict gate)
L_TEMPLATE_HINT = {
    "L1-1": "product_ingredients",
    "L2-3": "products_by_ingredient",
    "L4-1": "product_ingredients",
    "L4-2": "ingredient_contraindications",
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
        case_id, rest = m.group(1), m.group(2).strip()
        if any(rest.startswith(p) for p in SKIP_PREFIXES):
            continue
        if "确认卡片" in rest or rest.startswith("空问题") or "超长输入" in rest:
            continue
        q = re.sub(r"\s{2,}\[.+?\]\s*$", "", rest).strip()
        q = q.strip("「」")
        if len(q) < 4:
            continue
        cases.append((case_id, q))
    return cases


def run_rewrite(q: str, no_llm: bool) -> dict:
    if no_llm:
        return {"auto_proceed": None, "intent_hint": "", "blocked": False}
    try:
        import question_rewrite as qr
        from config import load_env

        key = os.environ.get("DEEPSEEK_API_KEY") or load_env().get("DEEPSEEK_API_KEY", "")
        if not key:
            return {"auto_proceed": None, "intent_hint": "", "blocked": False, "skip": "no_key"}
        r = qr.rewrite_question(q, api_key=key)
        return {
            "auto_proceed": r.auto_proceed,
            "intent_hint": r.intent_hint,
            "blocked": r.blocked,
            "confidence": r.confidence,
        }
    except Exception as exc:  # noqa: BLE001
        return {"auto_proceed": None, "intent_hint": "", "blocked": False, "error": str(exc)}


def simulate_e2e_reject(question: str) -> tuple[bool, str]:
    """Mirror server context assembly + _should_force_reject (no HTTP/LLM)."""
    import server

    context_parts: list[str] = []
    seen_slugs: set[str] = set()
    graph_hit = server.apply_graph_recall(question, context_parts, seen_slugs, sse=None)
    server._inject_series_coverage_if_needed(graph_hit, context_parts, seen_slugs, sse=None)
    need_local = server._need_local_search(question, graph_hit, context_parts)
    if need_local:
        search_results = server.gbrain_search(question, limit=6)
        for r in search_results:
            if r["slug"] in seen_slugs:
                continue
            seen_slugs.add(r["slug"])
            full = server.gbrain_get(r["slug"])
            if full and len(full) > 50:
                body = re.sub(r"^---.*?---\s*", "", full, flags=re.DOTALL)
                context_parts.append(f"## {r['slug']}\n{body[:8000]}")
    server.expand_concept_links(context_parts, seen_slugs, max_extra=6, sse=None)
    if server._should_force_reject(question, graph_hit, context_parts):
        reason = "unknown_patient" if server._unknown_patient_name(question) else "out_of_scope_or_empty"
        return True, reason
    return False, ""


def format_markdown_report(rows: list[dict], summary: dict) -> str:
    lines = [
        "# RAG Benchmark Report",
        "",
        f"Generated: {summary['timestamp']}",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['total']}",
        f"- Graph hit: {summary['graph_hits']}/{summary['total']} ({summary['graph_rate']:.0%})",
        f"- S-series graph: {summary['s_hits']}/{summary['s_total']} ({summary['s_rate']:.0%})",
        f"- E2E reject (L6): {summary['reject_ok']}/{summary['reject_total']}",
        "",
        "## Results",
        "",
        "| ID | hit | template | e2e_reject | auto | question |",
        "|----|-----|----------|------------|------|----------|",
    ]
    for r in rows:
        q = r["question"][:36].replace("|", "/")
        lines.append(
            f"| {r['id']} | {'Y' if r['hit'] else 'N'} | {r['template'] or '-'} | "
            f"{r.get('e2e_reject', '-')} | {r['rewrite_auto']} | {q} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run L/S benchmark from 测试问题集.txt（默认：改写层 + Wiki→Graph 同步）",
    )
    parser.add_argument("--file", default=str(BENCH_FILE), help="Benchmark file path")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="跳过改写层（默认启用 DeepSeek 改写，需 DEEPSEEK_API_KEY）",
    )
    parser.add_argument("--e2e", action="store_true", help="Simulate E2E rejection guard")
    parser.add_argument("--markdown", action="store_true", help="Print markdown table")
    parser.add_argument(
        "--no-sync-graph",
        action="store_true",
        help="跳过跑测前的 Wiki→Neo4j/FTS 同步（默认自动 sync）",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Write markdown report to path (default: _meta/benchmark_reports/ if --e2e)",
    )
    args = parser.parse_args()

    if not args.no_sync_graph:
        print("=== Pre-run: Wiki → Graph sync ===")
        import subprocess

        r = subprocess.run(
            [sys.executable, str(ROOT / "graph" / "sync_wiki_graph.py")],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            print("[warn] graph sync failed — Neo4j 可能未启动")
        print()

    cases = load_cases(Path(args.file))
    if not cases:
        raise SystemExit("No L/S cases parsed from benchmark file")

    rows = []
    graph_hits = 0
    s_hits = 0
    s_total = 0
    reject_ok = 0
    reject_total = 0
    l_hint_ok = 0
    l_hint_total = 0
    rw_auto_true = 0
    rw_auto_false = 0
    rw_blocked = 0
    rw_skipped = 0

    for case_id, question in cases:
        rw = run_rewrite(question, args.no_llm)
        if rw.get("blocked"):
            rw_blocked += 1
        elif rw.get("skip"):
            rw_skipped += 1
        elif rw.get("auto_proceed") is True:
            rw_auto_true += 1
        elif rw.get("auto_proceed") is False:
            rw_auto_false += 1
        result = gr.recall(question)
        hits = wiki_search.search(question, limit=3)
        top_slugs = [h["slug"] for h in hits[:3]]
        if result.hit:
            graph_hits += 1
        if case_id.startswith("S-"):
            s_total += 1
            expect = S_TEMPLATE_EXPECT.get(case_id)
            ok = result.hit and (
                not expect or result.template_id == expect
                or expect in (result.template_id or "")
            )
            if ok:
                s_hits += 1

        e2e_reject = None
        template_hint_ok = None
        if case_id.startswith("L") and case_id in L_TEMPLATE_HINT:
            hint = L_TEMPLATE_HINT[case_id]
            template_hint_ok = result.hit and result.template_id == hint

        if template_hint_ok is not None:
            l_hint_total += 1
            if template_hint_ok:
                l_hint_ok += 1

        if args.e2e and case_id in REJECT_CASE_IDS:
            reject_total += 1
            rejected, _ = simulate_e2e_reject(question)
            e2e_reject = rejected
            if rejected:
                reject_ok += 1

        rows.append({
            "id": case_id,
            "question": question,
            "rewrite_auto": rw.get("auto_proceed"),
            "intent_hint": rw.get("intent_hint") or "",
            "template": result.template_id or "",
            "hit": result.hit,
            "entities": ",".join(result.entities[:5]),
            "top_slugs": "|".join(top_slugs),
            "e2e_reject": e2e_reject,
            "template_hint_ok": template_hint_ok,
        })

    total = len(rows)
    hit_rate = graph_hits / total if total else 0.0
    s_rate = s_hits / s_total if s_total else 0.0
    print(
        f"=== Benchmark: {total} cases, Graph hit {graph_hits}/{total} ({hit_rate:.0%}), "
        f"S-series {s_hits}/{s_total} ({s_rate:.0%}) ==="
    )
    if args.e2e and reject_total:
        print(f"=== E2E reject L6: {reject_ok}/{reject_total} ===")

    if l_hint_total:
        print(f"=== L-series template hints: {l_hint_ok}/{l_hint_total} ===")
    if not args.no_llm:
        print(
            f"=== Rewrite: auto={rw_auto_true} confirm={rw_auto_false} "
            f"blocked={rw_blocked} skip_no_key={rw_skipped} ==="
        )

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "graph_hits": graph_hits,
        "graph_rate": hit_rate,
        "s_hits": s_hits,
        "s_total": s_total,
        "s_rate": s_rate,
        "reject_ok": reject_ok,
        "reject_total": reject_total,
        "l_hint_ok": l_hint_ok,
        "l_hint_total": l_hint_total,
        "rewrite_auto_true": rw_auto_true,
        "rewrite_auto_false": rw_auto_false,
        "rewrite_blocked": rw_blocked,
        "rewrite_skipped": rw_skipped,
    }

    out_path = args.output
    if args.e2e and not out_path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(REPORT_DIR / f"benchmark_{stamp}.md")

    if out_path:
        Path(out_path).write_text(format_markdown_report(rows, summary), encoding="utf-8")
        print(f"Report written: {out_path}")

    if args.markdown:
        print("\n| ID | 问句 | auto | template | hit | top3 |")
        print("|----|------|------|----------|-----|------|")
        for r in rows:
            q = r["question"][:40].replace("|", "/")
            print(
                f"| {r['id']} | {q} | {r['rewrite_auto']} | {r['template']} | "
                f"{'Y' if r['hit'] else 'N'} | {r['top_slugs'][:60]} |"
            )
    elif not out_path:
        for r in rows:
            print(
                f"{r['id']:8} hit={'Y' if r['hit'] else 'N':1} "
                f"tpl={r['template'] or '-':28} auto={str(r['rewrite_auto']):5} "
                f"{r['question'][:50]}"
            )
            if r["top_slugs"]:
                print(f"         fts: {r['top_slugs']}")
    print()

    failed = 0
    if s_total and s_hits < s_total:
        failed += s_total - s_hits
    if reject_total and reject_ok < reject_total:
        failed += reject_total - reject_ok
    if failed:
        raise SystemExit(f"{failed} benchmark assertion(s) failed")


if __name__ == "__main__":
    main()
