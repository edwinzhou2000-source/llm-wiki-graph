#!/usr/bin/env python3
"""Audit: Neo4j edges must match Wiki-extracted facts (bidirectional).

- orphan_in_graph: in Neo4j but not in Wiki → FAIL
- missing_in_graph: in Wiki but not in Neo4j → FAIL
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Set, Tuple

from neo4j import GraphDatabase

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))
if str(GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_DIR))

from wiki_graph_extract import (  # noqa: E402
    AUDITED_RELS,
    SYMMETRIC_RELS,
    edge_signature_set,
    extract,
    path_type_mismatches,
)

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "<REMOVED>")


def _edge_key(rel: str, a_label: str, a: str, b_label: str, b: str) -> Tuple:
    if rel in SYMMETRIC_RELS:
        left, right = sorted([(a_label, a), (b_label, b)])
        return (rel, left[0], left[1], right[0], right[1])
    return (rel, a_label, a, b_label, b)


def neo4j_edge_set() -> Set[Tuple]:
    driver = GraphDatabase.driver(URI, auth=AUTH)
    out: Set[Tuple] = set()
    try:
        with driver.session() as session:
            # Fetch all relationships between named nodes
            rows = session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE a.name IS NOT NULL AND b.name IS NOT NULL
                RETURN type(r) AS rel,
                       labels(a) AS a_labels,
                       a.name AS a,
                       labels(b) AS b_labels,
                       b.name AS b
                """
            )
            for row in rows:
                rel = row["rel"]
                if rel not in AUDITED_RELS:
                    continue
                # Prefer primary ontology labels
                a_lab = _pick_label(row["a_labels"])
                b_lab = _pick_label(row["b_labels"])
                out.add(_edge_key(rel, a_lab, row["a"], b_lab, row["b"]))
    finally:
        driver.close()
    return out


def _pick_label(labels) -> str:
    preferred = [
        "Patient", "Record", "Report", "Procedure", "Drug", "Device",
        "Condition", "Product", "Series", "TechPlatform",
    ]
    labs = list(labels or [])
    for p in preferred:
        if p in labs:
            return p
    return labs[0] if labs else "Entity"


def audit(verbose: bool = True) -> int:
    wiki = edge_signature_set(extract())
    graph = neo4j_edge_set()
    orphan = sorted(graph - wiki)
    missing = sorted(wiki - graph)
    folder_drift = path_type_mismatches()

    if verbose:
        print(f"wiki_edges={len(wiki)} neo4j_edges={len(graph)}")
        print(f"orphan_in_graph={len(orphan)} missing_in_graph={len(missing)}")
        print(f"folder_type_mismatch={len(folder_drift)}")
        if orphan:
            print("\nORPHAN (Neo4j has, Wiki lacks):")
            for e in orphan[:50]:
                print(" ", e)
        if missing:
            print("\nMISSING (Wiki has, Neo4j lacks):")
            for e in missing[:50]:
                print(" ", e)
        if folder_drift:
            print("\nFOLDER/TYPE MISMATCH (directory vs graph.type):")
            for line in folder_drift[:50]:
                print(" ", line)

    if orphan or missing or folder_drift:
        print("\nAUDIT FAILED")
        return 1
    print("\nAUDIT PASSED — Neo4j ⊆ Wiki and Wiki ⊆ Neo4j for audited edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(audit())
