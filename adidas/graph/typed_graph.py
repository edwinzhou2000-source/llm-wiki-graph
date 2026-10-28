"""typed_graph.py — Lightweight typed property graph (pure Python, no Neo4j).

This is the adidas graph replica's graph backend. adidas relations are thin and
derivable from frontmatter, so a full Neo4j instance is unnecessary — a typed
adjacency index supports the same graph-first recall (typed multi-hop traversal
+ definitive negatives) with zero external dependency and full isolation.

Nodes are keyed by (label, name); edges are directed and typed.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


class TypedGraph:
    def __init__(self):
        # (label, name) -> props
        self._nodes: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # (label, name, rel) -> set of (label, name)
        self._out: Dict[Tuple[str, str, str], Set[Tuple[str, str]]] = {}
        self._in: Dict[Tuple[str, str, str], Set[Tuple[str, str]]] = {}
        # ordered edge records for rendering / audit
        self._edges: List[Dict[str, Any]] = []

    # ── mutation ──
    def add_node(self, label: str, name: str, **props) -> None:
        key = (label, name)
        existing = self._nodes.get(key)
        if existing is None:
            self._nodes[key] = dict(props)
        else:
            existing.update(props)

    def add_edge(
        self,
        rel: str,
        from_label: str,
        from_name: str,
        to_label: str,
        to_name: str,
        source: str = "",
    ) -> None:
        self.add_node(from_label, from_name)
        self.add_node(to_label, to_name)
        out_key = (from_label, from_name, rel)
        in_key = (to_label, to_name, rel)
        self._out.setdefault(out_key, set()).add((to_label, to_name))
        self._in.setdefault(in_key, set()).add((from_label, from_name))
        for e in self._edges:
            if (
                e["type"] == rel
                and e["from_label"] == from_label
                and e["from"] == from_name
                and e["to_label"] == to_label
                and e["to"] == to_name
            ):
                if source and source not in e["sources"]:
                    e["sources"].append(source)
                return
        self._edges.append(
            {
                "type": rel,
                "from_label": from_label,
                "from": from_name,
                "to_label": to_label,
                "to": to_name,
                "sources": [source] if source else [],
            }
        )

    # ── accessors ──
    def nodes(self, label: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for (lab, name), props in self._nodes.items():
            if label is None or lab == label:
                out.append({"label": lab, "name": name, "props": dict(props)})
        return sorted(out, key=lambda n: (n["label"], n["name"]))

    def edges(self, rel: Optional[str] = None) -> List[Dict[str, Any]]:
        if rel is None:
            return sorted(
                self._edges, key=lambda e: (e["type"], e["from"], e["to"])
            )
        return [e for e in self._edges if e["type"] == rel]

    def has_node(self, label: str, name: str) -> bool:
        return (label, name) in self._nodes

    def outgoing(
        self, label: str, name: str, rel: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """Return (to_label, to_name) pairs reachable via rel (or any rel)."""
        out: Set[Tuple[str, str]] = set()
        for (lab, nm, r), tos in self._out.items():
            if lab != label or nm != name:
                continue
            if rel is None or r == rel:
                out |= tos
        return sorted(out)

    def incoming(
        self, label: str, name: str, rel: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """Return (from_label, from_name) pairs pointing to this node."""
        out: Set[Tuple[str, str]] = set()
        for (lab, nm, r), frm in self._in.items():
            if lab != label or nm != name:
                continue
            if rel is None or r == rel:
                out |= frm
        return sorted(out)

    def names_of_label(self, label: str) -> List[str]:
        return sorted(n for (lab, n) in self._nodes if lab == label)

    # ── multi-hop ──
    def traverse(
        self,
        start_label: str,
        start_name: str,
        rels: Iterable[str],
        depth: int = 2,
    ) -> List[Dict[str, Any]]:
        """BFS over typed edges; returns paths with (label, name) hops."""
        rel_set = set(rels)
        results: List[Dict[str, Any]] = []
        visited = {(start_label, start_name)}

        def walk(cur_label, cur_name, path, d):
            if d <= 0:
                return
            for (to_label, to_name) in self.outgoing(cur_label, cur_name):
                # determine the rel actually used
                used_rel = None
                for r in rel_set:
                    if (to_label, to_name) in self._out.get(
                        (cur_label, cur_name, r), set()
                    ):
                        used_rel = r
                        break
                key = (to_label, to_name)
                if key in visited:
                    continue
                visited.add(key)
                new_path = path + [(used_rel, to_label, to_name)]
                results.append(
                    {
                        "hops": new_path,
                        "endpoint": to_name,
                        "endpoint_label": to_label,
                    }
                )
                walk(to_label, to_name, new_path, d - 1)

        walk(start_label, start_name, [], depth)
        return results


def build_graph(extracted: Dict[str, Any]) -> TypedGraph:
    """Populate a TypedGraph from wiki_graph_extract.extract() output."""
    g = TypedGraph()
    for n in extracted.get("nodes", []):
        g.add_node(n["label"], n["name"], **(n.get("props") or {}))
    for e in extracted.get("edges", []):
        g.add_edge(
            e["type"],
            e["from_label"],
            e["from"],
            e["to_label"],
            e["to"],
            source=(e.get("sources") or [""])[0],
        )
    return g


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from graph.wiki_graph_extract import extract

    data = extract()
    g = build_graph(data)
    print(f"nodes={len(g.nodes())} edges={len(g.edges())}")
    from collections import Counter

    print("labels:", dict(Counter(n["label"] for n in g.nodes())))
    print("rels:", dict(Counter(e["type"] for e in g.edges())))
