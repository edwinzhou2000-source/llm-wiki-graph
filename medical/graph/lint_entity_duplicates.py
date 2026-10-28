#!/usr/bin/env python3
"""Gardener lint: report suspected duplicate entities (never auto-merge).

Compares canonical names + aliases across Wiki entity pages.
Exit 0 by default (report-only). Use --fail-on-findings to exit 1 when pairs found.
"""

from __future__ import annotations

import argparse
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Tuple

GRAPH_DIR = Path(__file__).resolve().parent
KB_ROOT = GRAPH_DIR.parent
if str(KB_ROOT) not in sys.path:
    sys.path.insert(0, str(KB_ROOT))
if str(GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_DIR))

from wiki_graph_extract import extract  # noqa: E402

# "降压片" vs product names are intentional short aliases — skip very short generic pairs
_MIN_ALIAS_LEN = 2
_RATIO = 0.88
_BRAND_PREFIXES = ("福顺",)


def _strip_brand(s: str) -> str:
    for p in _BRAND_PREFIXES:
        if s.startswith(p) and len(s) > len(p) + 1:
            return s[len(p) :]
    return s


def _terms_for_node(n: dict) -> List[str]:
    name = n["name"]
    aliases = list((n.get("props") or {}).get("aliases") or [])
    return [name] + [a for a in aliases if isinstance(a, str) and len(a) >= _MIN_ALIAS_LEN]


def _similar(a: str, b: str) -> float:
    if a == b:
        return 1.0
    # Containment only when shorter is nearly the whole longer name
    if a in b or b in a:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if len(shorter) >= 3 and len(shorter) / max(len(longer), 1) >= 0.75:
            return 0.92
    # Compare with brand prefix stripped so 福顺降压片 ≠ 福顺降糖片
    aa, bb = _strip_brand(a), _strip_brand(b)
    return max(
        SequenceMatcher(None, a.lower(), b.lower()).ratio(),
        SequenceMatcher(None, aa.lower(), bb.lower()).ratio(),
    )


def find_duplicate_pairs(extracted=None) -> List[Tuple[str, str, str, str, float]]:
    """Return list of (label_a, name_a, label_b, name_b, score)."""
    data = extracted or extract()
    nodes = [n for n in data["nodes"] if n["label"] != "Record"]
    pairs: List[Tuple[str, str, str, str, float]] = []
    seen_pair = set()

    # Alias collision: two different canonicals claim same alias string
    owner: Dict[str, Tuple[str, str]] = {}
    for n in nodes:
        label, name = n["label"], n["name"]
        for term in _terms_for_node(n):
            key = term.lower()
            if key in owner and owner[key][1] != name:
                ol, on = owner[key]
                pair_key = tuple(sorted([(ol, on), (label, name)]))
                if pair_key not in seen_pair:
                    seen_pair.add(pair_key)
                    pairs.append((ol, on, label, name, 1.0))
            else:
                owner[key] = (label, name)

    # Fuzzy name similarity across same label
    by_label: Dict[str, List[dict]] = {}
    for n in nodes:
        by_label.setdefault(n["label"], []).append(n)

    for label, group in by_label.items():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                best = 0.0
                for ta in _terms_for_node(a):
                    for tb in _terms_for_node(b):
                        if ta == tb:
                            continue
                        best = max(best, _similar(ta, tb))
                if best >= _RATIO:
                    pair_key = tuple(sorted([(label, a["name"]), (label, b["name"])]))
                    if pair_key not in seen_pair:
                        seen_pair.add(pair_key)
                        pairs.append((label, a["name"], label, b["name"], best))

    pairs.sort(key=lambda x: (-x[4], x[1], x[3]))
    return pairs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lint suspected duplicate Wiki entities")
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Exit 1 when any suspected duplicate pair is found",
    )
    args = parser.parse_args(argv)

    data = extract()
    pairs = find_duplicate_pairs(data)
    print(f"entities_scanned={len(data['nodes'])} suspected_pairs={len(pairs)}")
    if not pairs:
        print("No suspected duplicates.")
        return 0

    print("\nSuspected duplicates (human review — do NOT auto-merge):")
    for la, na, lb, nb, score in pairs[:40]:
        print(f"  [{score:.2f}] {la}:{na}  ≈  {lb}:{nb}")
    print(
        "\nNext: expert merges Wiki pages / updates aliases & wikilinks, "
        "then `python graph/load_data.py`."
    )
    if args.fail_on_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
