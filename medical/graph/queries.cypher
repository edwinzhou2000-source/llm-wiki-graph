// 1. 药物相互作用(2 跳) — 王强正在吃的药里,有没有两两相互作用?
// 预期: 华法林 ↔ 阿司匹林
MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d1:Drug)
MATCH (d1)-[:INTERACTS_WITH]-(d2:Drug)
WHERE EXISTS { (p)-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d2) }
RETURN DISTINCT d1.name, d2.name;

// 2. 过敏(1 跳) — 李娜对什么药过敏?
// 预期: 青霉素
MATCH (p:Patient {name:'李娜'})-[:ALLERGIC_TO]->(d:Drug) RETURN d.name;

// 3. 报告→疾病→药物禁忌(3 跳) — 王强化验提示慢性肾病,哪些药对它有禁忌?
// 预期: 慢性肾病 → [二甲双胍]
MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:ORDERS]->(:Report)-[:SHOWS]->(c:Condition)
MATCH (d:Drug)-[:CONTRAINDICATED_FOR]->(c)
RETURN c.name, collect(d.name) AS 禁忌药;

// 4. 手术→设备→设备互斥(3 跳) — 王强装了起搏器,哪项检查设备对他禁忌?
// 预期: 心脏起搏器 ↔ MRI设备
MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:ORDERS]->(:Procedure)-[:USES]->(dev:Device)
MATCH (mri:Device)-[:CONTRAINDICATED_WITH]->(dev)
RETURN dev.name, mri.name;

// 5. 妊娠禁忌(2 跳) — 赵敏怀孕了,在吃的药里哪些有禁忌?
// 预期: 布洛芬
MATCH (p:Patient {name:'赵敏'})-[:HAS_RECORD]->(:Record)-[:PRESCRIBES]->(d:Drug)
MATCH (d)-[:CONTRAINDICATED_FOR]->(c:Condition {name:'妊娠'})
RETURN d.name;

// 6. 反向查适应症(1 跳) — 哪些药能治 2 型糖尿病?
// 预期: 二甲双胍
MATCH (d:Drug)-[:TREATS]->(c:Condition {name:'2型糖尿病'}) RETURN d.name;

// 7. 加药安全检查(3 跳) — 给王强加二甲双胍,有无禁忌?
// 预期: 慢性肾病
MATCH (p:Patient {name:'王强'})-[:HAS_RECORD]->(:Record)-[:DIAGNOSES]->(c:Condition)
MATCH (d:Drug {name:'二甲双胍'})-[:CONTRAINDICATED_FOR]->(c)
RETURN c.name;
