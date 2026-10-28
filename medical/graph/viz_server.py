#!/usr/bin/env python3
"""Phase 3: local viz server — proxies Neo4j so the browser never talks Bolt."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
AUTH = ("neo4j", "medical123")
HOST, PORT = "127.0.0.1", 8765
ROOT = Path(__file__).resolve().parent

LABEL_COLORS = {
    "Patient": "#3b82f6",
    "Drug": "#ef4444",
    "Device": "#8b5cf6",
    "Condition": "#f59e0b",
    "Record": "#10b981",
    "Report": "#06b6d4",
    "Procedure": "#ec4899",
    "Product": "#38bdf8",
    "Series": "#4f46e5",
    "TechPlatform": "#a855f7",
}

DEMO_QUERIES = {
    "full": (
        "MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 120",
        "全图概览",
    ),
    "q1": (
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(rec:Record)-[:PRESCRIBES]->(d1:Drug)
        MATCH (d1)-[r:INTERACTS_WITH]-(d2:Drug)
        WHERE EXISTS { (p)-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d2) }
        RETURN p, rec, d1, r, d2
        """,
        "临床·王强用药相互作用",
    ),
    "q2": (
        "MATCH (p:Patient {name:'李娜'})-[r:ALLERGIC_TO]->(d:Drug) RETURN p, r, d",
        "临床·李娜过敏",
    ),
    "q3": (
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(rec:Record)-[:ORDERS]->(rep:Report)-[:SHOWS]->(c:Condition)
        MATCH (d:Drug)-[r:CONTRAINDICATED_FOR]->(c)
        RETURN p, rec, rep, c, d, r
        """,
        "临床·化验→禁忌药",
    ),
    "q4": (
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(rec:Record)-[:ORDERS]->(proc:Procedure)-[:USES]->(dev:Device)
        MATCH (mri:Device)-[r:CONTRAINDICATED_WITH]->(dev)
        RETURN p, rec, proc, dev, mri, r
        """,
        "临床·起搏器→MRI禁忌",
    ),
    "q5": (
        """
        MATCH (p:Patient {name:'赵敏'})-[:HAS_RECORD]->(rec:Record)-[:PRESCRIBES]->(d:Drug)
        MATCH (d)-[r:CONTRAINDICATED_FOR]->(c:Condition {name:'妊娠'})
        RETURN p, rec, d, r, c
        """,
        "临床·妊娠禁忌药",
    ),
    "q6": (
        "MATCH (d:Drug)-[r:TREATS]->(c:Condition {name:'2型糖尿病'}) RETURN d, r, c",
        "临床·2型糖尿病适应症",
    ),
    "q7": (
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(rec:Record)-[:DIAGNOSES]->(c:Condition)
        MATCH (d:Drug {name:'二甲双胍'})-[r:CONTRAINDICATED_FOR]->(c)
        RETURN p, rec, c, d, r
        """,
        "临床·加药安全检查",
    ),
    "p1": (
        """
        MATCH (prod:Product)-[r1:IN_SERIES]->(s:Series {name:'福顺心血管'})
        MATCH (prod)-[r2:USES_TECH]->(t:TechPlatform {name:'缓释技术'})
        RETURN prod, r1, s, r2, t
        """,
        "产品·心血管∩缓释",
    ),
    "p2": (
        """
        MATCH (prod:Product)-[r:HAS_INGREDIENT]->(d:Drug {name:'二甲双胍'})
        OPTIONAL MATCH (prod)-[:IN_SERIES]->(s:Series)
        RETURN prod, r, d, s
        """,
        "产品·含二甲双胍",
    ),
    "x1": (
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(rec:Record)-[:DIAGNOSES]->(c:Condition)
        MATCH (d:Drug)-[r1:CONTRAINDICATED_FOR]->(c)
        MATCH (prod:Product)-[r2:HAS_INGREDIENT]->(d)
        RETURN p, rec, c, d, prod, r1, r2
        """,
        "跨层·王强禁忌→福顺产品",
    ),
}


def node_payload(node) -> dict:
    labels = list(node.labels)
    label = labels[0] if labels else "Node"
    props = dict(node)
    name = props.get("name", str(node.element_id))
    return {
        "id": node.element_id,
        "label": name,
        "group": label,
        "color": LABEL_COLORS.get(label, "#94a3b8"),
        "title": f"{label}: {name}",
        "props": props,
    }


def fetch_graph(cypher: str) -> dict:
    driver = GraphDatabase.driver(URI, auth=AUTH)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[str] = set()

    with driver.session() as session:
        result = session.run(cypher)
        for record in result:
            for value in record.values():
                if value is None:
                    continue
                # Node
                if hasattr(value, "labels") and hasattr(value, "element_id"):
                    nodes[value.element_id] = node_payload(value)
                # Relationship
                elif hasattr(value, "type") and hasattr(value, "start_node"):
                    start = value.start_node
                    end = value.end_node
                    nodes[start.element_id] = node_payload(start)
                    nodes[end.element_id] = node_payload(end)
                    key = f"{start.element_id}|{value.type}|{end.element_id}"
                    if key not in edge_keys:
                        edge_keys.add(key)
                        edges.append(
                            {
                                "id": value.element_id,
                                "from": start.element_id,
                                "to": end.element_id,
                                "label": value.type,
                                "arrows": "to",
                            }
                        )
                # Path
                elif hasattr(value, "nodes") and hasattr(value, "relationships"):
                    for n in value.nodes:
                        nodes[n.element_id] = node_payload(n)
                    for rel in value.relationships:
                        start, end = rel.start_node, rel.end_node
                        nodes[start.element_id] = node_payload(start)
                        nodes[end.element_id] = node_payload(end)
                        key = f"{start.element_id}|{rel.type}|{end.element_id}"
                        if key not in edge_keys:
                            edge_keys.add(key)
                            edges.append(
                                {
                                    "id": rel.element_id,
                                    "from": start.element_id,
                                    "to": end.element_id,
                                    "label": rel.type,
                                    "arrows": "to",
                                }
                            )

    driver.close()
    return {"nodes": list(nodes.values()), "edges": edges}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[viz] {self.address_string()} {fmt % args}")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._file(ROOT / "index.html", "text/html; charset=utf-8")
            return

        if path == "/api/demos":
            demos = [
                {"id": k, "title": title}
                for k, (_cypher, title) in DEMO_QUERIES.items()
            ]
            self._json(200, {"demos": demos})
            return

        if path == "/api/graph":
            qs = parse_qs(parsed.query)
            demo_id = (qs.get("demo") or ["full"])[0]
            if demo_id not in DEMO_QUERIES:
                self._json(400, {"error": f"unknown demo: {demo_id}"})
                return
            cypher, title = DEMO_QUERIES[demo_id]
            try:
                graph = fetch_graph(cypher)
                graph["demo"] = demo_id
                graph["title"] = title
                self._json(200, graph)
            except Exception as exc:  # noqa: BLE001 — surface to UI
                self._json(500, {"error": str(exc)})
            return

        self.send_error(404)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Phase 3 viz: http://{HOST}:{PORT}")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
