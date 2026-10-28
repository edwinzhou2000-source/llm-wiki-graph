#!/usr/bin/env python3
"""Load adidas typed graph into Neo4j from Wiki frontmatter extract (idempotent MERGE).

Edges are derived from product frontmatter (not medical 一事一页). See wiki_graph_extract.py.
Demo credentials only — not for production.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))
if str(GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_DIR))

from wiki_graph_extract import extract  # noqa: E402
import render_wiki_relations as rwr  # noqa: E402

URI = os.environ.get("ADIDAS_NEO4J_URI", "bolt://localhost:7688")
USER = os.environ.get("ADIDAS_NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("ADIDAS_NEO4J_PASSWORD", "<REMOVED>")
AUTH = (USER, PASSWORD)

LABELS = (
    "Product",
    "Tech",
    "Series",
    "Category",
    "ProductType",
)


def merge_node(tx, label, name, **props):
    props = {**props, "name": name}
    tx.run(f"MERGE (n:{label} {{name: $name}}) SET n += $props", name=name, props=props)


def merge_rel(tx, from_label, a_name, rel, to_label, b_name):
    tx.run(
        f"MATCH (a:{from_label} {{name: $a}}), (b:{to_label} {{name: $b}}) "
        f"MERGE (a)-[:{rel}]->(b)",
        a=a_name,
        b=b_name,
    )


def ensure_constraints(tx):
    for label in LABELS:
        tx.run(
            f"CREATE CONSTRAINT {label.lower()}_name IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.name IS UNIQUE"
        )


def clear_demo_graph(tx):
    tx.run(
        "MATCH (n) WHERE any(l IN labels(n) WHERE l IN $labels) DETACH DELETE n",
        labels=list(LABELS),
    )


def load_from_wiki(tx, data):
    for n in data["nodes"]:
        props = dict(n.get("props") or {})
        merge_node(tx, n["label"], n["name"], **props)
    for e in data["edges"]:
        merge_rel(tx, e["from_label"], e["from"], e["type"], e["to_label"], e["to"])


def main():
    print("[wiki→neo4j] refreshing 关系索引…")
    rwr.render_index()

    data = extract()
    print(f"[wiki→neo4j] extracted nodes={len(data['nodes'])} edges={len(data['edges'])}")
    driver = GraphDatabase.driver(URI, auth=AUTH)
    try:
        with driver.session() as session:
            session.execute_write(ensure_constraints)
            session.execute_write(clear_demo_graph)
            session.execute_write(load_from_wiki, data)
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        print(f"[wiki→neo4j] loaded nodes={node_count} relationships={rel_count}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
