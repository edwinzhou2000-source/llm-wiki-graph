#!/usr/bin/env python3
"""Run the 7 demo Cypher queries and check expected results."""

from neo4j import GraphDatabase

from neo4j_connect import neo4j_auth

URI, AUTH = neo4j_auth()

QUERIES = [
    (
        "1 药物相互作用",
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d1:Drug)
        MATCH (d1)-[:INTERACTS_WITH]-(d2:Drug)
        WHERE EXISTS { (p)-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d2) }
        RETURN DISTINCT d1.name AS d1, d2.name AS d2
        """,
        lambda rows: any(
            {"华法林", "阿司匹林"} == {r["d1"], r["d2"]} for r in rows
        ),
        "华法林 ↔ 阿司匹林",
    ),
    (
        "2 过敏",
        "MATCH (p:Patient {name:'李娜'})-[:ALLERGIC_TO]->(d:Drug) RETURN d.name AS name",
        lambda rows: [r["name"] for r in rows] == ["青霉素"],
        "青霉素",
    ),
    (
        "3 报告→禁忌药",
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:ORDERS]->(:Report)-[:SHOWS]->(c:Condition)
        MATCH (d:Drug)-[:CONTRAINDICATED_FOR]->(c)
        RETURN c.name AS condition, collect(d.name) AS drugs
        """,
        lambda rows: any(
            r["condition"] == "慢性肾病" and r["drugs"] == ["二甲双胍"] for r in rows
        ),
        "慢性肾病 → [二甲双胍]",
    ),
    (
        "4 起搏器→MRI禁忌",
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:ORDERS]->(:Procedure)-[:USES]->(dev:Device)
        MATCH (mri:Device)-[:CONTRAINDICATED_WITH]->(dev)
        RETURN dev.name AS device, mri.name AS mri
        """,
        lambda rows: any(
            r["device"] == "心脏起搏器" and r["mri"] == "MRI设备" for r in rows
        ),
        "心脏起搏器 ↔ MRI设备",
    ),
    (
        "5 妊娠禁忌",
        """
        MATCH (p:Patient {name:'赵敏'})-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d:Drug)
        MATCH (d)-[:CONTRAINDICATED_FOR]->(c:Condition {name:'妊娠'})
        RETURN d.name AS name
        """,
        lambda rows: [r["name"] for r in rows] == ["布洛芬"],
        "布洛芬",
    ),
    (
        "6 适应症",
        "MATCH (d:Drug)-[:TREATS]->(c:Condition {name:'2型糖尿病'}) RETURN d.name AS name",
        lambda rows: [r["name"] for r in rows] == ["二甲双胍"],
        "二甲双胍",
    ),
    (
        "7 加药安全检查",
        """
        MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:DIAGNOSES]->(c:Condition)
        MATCH (d:Drug {name:'二甲双胍'})-[:CONTRAINDICATED_FOR]->(c)
        RETURN c.name AS name
        """,
        lambda rows: [r["name"] for r in rows] == ["慢性肾病"],
        "慢性肾病",
    ),
]

EXPECTED_NODES = {
    "Patient": 5,
    "Drug": 9,
    "Device": 4,
    "Condition": 7,
    "Record": 5,
    "Report": 3,
    "Procedure": 3,
}


def main():
    driver = GraphDatabase.driver(URI, auth=AUTH)
    passed = 0
    with driver.session() as session:
        rows = session.run(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS cnt ORDER BY label"
        ).data()
        counts = {r["label"]: r["cnt"] for r in rows}
        print("Node counts:")
        node_ok = True
        for label, expected in EXPECTED_NODES.items():
            actual = counts.get(label, 0)
            ok = actual == expected
            node_ok = node_ok and ok
            mark = "OK" if ok else "FAIL"
            print(f"  [{mark}] {label}: {actual} (expected {expected})")

        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()["cnt"]
        print(f"Relationship count: {rel_count}")
        print()

        for title, cypher, check, expected in QUERIES:
            result = session.run(cypher).data()
            ok = check(result)
            passed += int(ok)
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {title}")
            print(f"  expected: {expected}")
            print(f"  got:      {result}")

    driver.close()
    print()
    print(f"Queries: {passed}/{len(QUERIES)} passed")
    if not node_ok or passed != len(QUERIES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
