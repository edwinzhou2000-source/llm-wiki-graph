#!/usr/bin/env python3
"""Wiki → 关系索引 → Neo4j → 本地 FTS 一键同步。

新 Markdown（实体页 `graph.kind: entity`、一事一页边、产品桥接）写入后执行本脚本即可进图。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))
if str(GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_DIR))


def sync_wiki_to_graph(
    *,
    rebuild_index: bool = True,
    load_neo4j: bool = True,
    sync_fts: bool = True,
    verbose: bool = True,
) -> dict:
    """Refresh relation index, Neo4j, and local_wiki_search index."""
    summary: dict = {"index": False, "neo4j": False, "fts": False, "errors": []}

    if rebuild_index:
        try:
            import render_wiki_relations as rwr

            rwr.render_index()
            summary["index"] = True
            if verbose:
                print("[sync] 关系索引已刷新")
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"render_index: {exc}")
            if verbose:
                print(f"[sync] 关系索引失败: {exc}")

    if load_neo4j:
        try:
            r = subprocess.run(
                [sys.executable, str(GRAPH_DIR / "load_data.py")],
                cwd=str(KB_ROOT),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0:
                summary["neo4j"] = True
                if verbose:
                    tail = (r.stdout or "").strip().splitlines()[-1:]
                    print("[sync] Neo4j:", tail[0] if tail else "ok")
            else:
                err = (r.stderr or r.stdout or "load_data failed").strip()[:500]
                summary["errors"].append(f"load_data: {err}")
                if verbose:
                    print(f"[sync] Neo4j 跳过/失败: {err}")
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"load_data: {exc}")
            if verbose:
                print(f"[sync] Neo4j 异常: {exc}")

    if sync_fts:
        try:
            import local_wiki_search as wiki_search

            wiki_search.sync()
            summary["fts"] = True
            if verbose:
                print("[sync] 本地 FTS 索引已重建")
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"fts: {exc}")
            if verbose:
                print(f"[sync] FTS 失败: {exc}")

    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync Wiki markdown into Neo4j + FTS")
    ap.add_argument("--skip-neo4j", action="store_true", help="Only refresh index + FTS")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    summary = sync_wiki_to_graph(
        load_neo4j=not args.skip_neo4j,
        verbose=not args.quiet,
    )
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
