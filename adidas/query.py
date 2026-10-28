#!/usr/bin/env python3
"""query.py — CLI entry: rewrite gate → graph recall → FTS fallback → optional LLM answer.

Works without DEEPSEEK_API_KEY (prints recall structure + source slugs).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_env, cfg  # noqa: E402
import graph_recall as gr  # noqa: E402
import local_wiki_search as wiki_search  # noqa: E402
import question_rewrite as qr  # noqa: E402

SYSTEM_PROMPT = """你是 adidas 产品知识库助手。只根据下方提供的知识库上下文回答。
规则：
1. 不得编造上下文中不存在的产品、科技、系列或参数。
2. 若上下文不足，明确说「知识库未覆盖」并指出缺口，不要猜测。
3. 图召回结果只是关系线索；细节以原文 Markdown 为准。
4. 若问题是列举产品系列/子系列，列举集合必须 ⊆ 图谱召回行中的系列名；不得编造未召回的系列。
5. 用简洁中文回答。"""


def _api_key() -> str:
    env = load_env()
    return os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY", "") or ""


def ask(question: str, *, use_llm: bool = True, skip_rewrite: bool = False) -> dict:
    """Run full pipeline; always returns a structured dict."""
    original = (question or "").strip()
    out: dict = {
        "question": original,
        "rewritten": original,
        "blocked": False,
        "graph_hit": False,
        "template_id": "",
        "facts": "",
        "source_slugs": [],
        "fts_hits": [],
        "answer": "",
        "mode": "recall_only",
    }

    pre = qr.rule_precheck(original)
    if pre and pre.blocked:
        out["blocked"] = True
        out["answer"] = pre.block_reason
        return out

    q = original
    if not skip_rewrite:
        rw = qr.rewrite_question(original, api_key=_api_key() if use_llm else "")
        if rw.blocked:
            out["blocked"] = True
            out["answer"] = rw.block_reason
            return out
        q = rw.rewritten or original
        out["rewritten"] = q
        out["rewrite"] = qr.to_api_dict(rw)

    result = gr.recall(q)
    context = ""
    loaded: list[str] = []
    if result.hit:
        out["graph_hit"] = True
        out["template_id"] = result.template_id
        out["facts"] = result.facts_text
        out["rows"] = [
            {k: (len(v) if isinstance(v, list) else v) for k, v in row.items()}
            for row in result.rows
        ]
        if result.error:
            out["error"] = result.error
        context, loaded = gr.build_context_block(result)
        out["source_slugs"] = loaded or result.source_slugs

    if not result.hit or not result.rows:
        fts = wiki_search.search(q, limit=6)
        out["fts_hits"] = [
            {"slug": h.get("slug"), "score": h.get("score")}
            for h in fts
        ]
        if fts and not context:
            parts = []
            for h in fts[:4]:
                slug = h.get("slug") or ""
                body = wiki_search.get(slug) if hasattr(wiki_search, "get") else ""
                if not body:
                    body = gr.load_source_page(slug)
                if body:
                    parts.append(f"## {slug}\n{body[:4000]}")
                    if slug not in out["source_slugs"]:
                        out["source_slugs"].append(slug)
            if result.facts_text:
                parts.insert(0, result.facts_text)
            context = "\n\n---\n\n".join(parts)

    key = _api_key() if use_llm else ""
    if key and context:
        out["mode"] = "llm"
        out["answer"] = _llm_answer(q, context, key)
    else:
        out["mode"] = "recall_only"
        lines = []
        if result.hit:
            lines.append(result.facts_text)
            lines.append(f"template={result.template_id} rows={len(result.rows)}")
        if out["fts_hits"]:
            lines.append("FTS: " + ", ".join(h["slug"] for h in out["fts_hits"][:5] if h.get("slug")))
        if out["source_slugs"]:
            lines.append("sources: " + ", ".join(out["source_slugs"][:8]))
        if not lines:
            lines.append("未命中图谱切片，且全文检索无结果。")
        out["answer"] = "\n".join(lines)
    return out


def _llm_answer(question: str, context: str, api_key: str) -> str:
    base = "https://api.deepseek.com"
    try:
        max_tokens = int(cfg.server.qa.max_tokens)
    except Exception:  # noqa: BLE001
        max_tokens = 2500
    payload = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"问题：{question}\n\n知识库上下文：\n{context[:24000]}",
                },
            ],
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser(description="adidas graph KB query CLI")
    ap.add_argument("question", nargs="?", help="用户问题")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM，只打印召回")
    ap.add_argument("--skip-rewrite", action="store_true")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()
    if not args.question:
        ap.error("请提供问题，例如: python3 query.py '哪些产品用了 boost 科技？'")

    result = ask(args.question, use_llm=not args.no_llm, skip_rewrite=args.skip_rewrite)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Q: {result['question']}")
        if result.get("rewritten") != result["question"]:
            print(f"改写: {result['rewritten']}")
        print(f"graph_hit={result['graph_hit']} template={result.get('template_id')} mode={result['mode']}")
        print("---")
        print(result.get("answer") or "")


if __name__ == "__main__":
    main()
