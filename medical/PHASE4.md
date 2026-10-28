# Phase 4+ — 双层图谱召回（副本）

本目录是 **LLM-Wiki 副本**（原版不动）。Schema 见 [`SCHEMA.md`](SCHEMA.md)。

## 架构

```
用户问题
   │
   ├─ ⓪ 问题改写层（DeepSeek JSON + 规则预检）
   │      ↓ 高置信 auto → 规范化问句；低置信/歧义 → UI 确认
   │
   ├─ ① Graph-first（Neo4j 结构化多跳）
   │      ↓ 命中 → 加载「一事一页」Wiki 原文
   │
   └─ ② 本地 Wiki 全文检索（jieba + 目录扫描）
          ↓ 开放产品问 / 图召回不足时补页
   DeepSeek 依 Wiki 正文回答
```

本副本 **不依赖 gbrain**（Bun/PGlite）；全文通道由 `local_wiki_search.py` 承担。  
原版通用 Wiki 仍可继续用 gbrain。

与常见「LLM Wiki Pattern」对齐的是 **Wiki-as-SoT**；本副本刻意不用 LLM 抽边，而用 **边一事一页 + 确定性 frontmatter**（专家改正文，英文 `type` 由目录/脚手架维护）。详见 [`SCHEMA.md`](SCHEMA.md)。

Wiki 侧：`临床事实/`、`用药安全/{禁忌,相互作用,…}`、`产品桥接/` 均为关系事实页；实体页不含边，可声明 `graph.aliases`。

## 说明书入库（规模化）

大量 PI/说明书：**Agent 起草提案包（实体页 + 边事实页）→ 内容审核 → Wiki → `load_data`**。  
严重程度写在边事实页正文，不把图边属性当本体。详见 [`SCHEMA.md`](SCHEMA.md)「说明书规模化入库」。

| 模式 | 用途 |
|------|------|
| `review` | 通用产品上传审核 |
| `pi` | 说明书专用提示词 + 多页提案包 |
| `direct` | 仅非临床产品快速收录（说明书勿用） |

试点：`python graph/pi_pilot_proposal.py`（可加 `--apply` 落盘并灌图）。

## 端口

| 服务 | URL |
|------|-----|
| Wiki 副本 | http://127.0.0.1:8770 |
| 图可视化 | http://127.0.0.1:8765（`python graph/viz_server.py`） |
| Neo4j Browser | http://localhost:7474（neo4j / <REMOVED>） |

## 启动

```bash
# Neo4j + 灌双层数据
cd /Users/edwin.zhou/Documents/LLM-Wiki/medical-graph-demo && docker compose up -d
cd /Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/medical
source .venv/bin/activate
python graph/load_data.py
python smoke_graph_recall.py
python smoke_question_rewrite.py
python benchmark_query.py --no-llm   # L/S 测试集图谱/FTS 报告
python benchmark_query.py --e2e      # 含 L6 拒答断言 + 写入 _meta/benchmark_reports/

# Wiki
bash run_graph_wiki.sh
```

## 三类演示问题

**临床**：王强正在吃的药里有没有相互作用？  
**产品**：福顺心血管系列里用了缓释技术的产品有哪些？  
**跨层（重点）**：王强有慢性肾病，库里哪些含相关禁忌成分的福顺产品不能用？  
**成分反查**：青霉素相关药品和禁忌有什么？

## Graph / FTS / Deep 分工

| 通道 | 适用 | 不适用 |
|------|------|--------|
| **Graph-first** | 结构化关系：禁忌、相互作用、过敏、成分→产品、`IN_SERIES` 清单（边齐全时） | 未建边的散文、营销长文 |
| **Local FTS** | 边未建全、路由不匹配、别名/拼写模糊 | 图谱可信模板已命中时（见下） |
| **Deep ReAct** | Graph+FTS 仍不足的开放产品长问 | 临床结构化问（单轮即可） |

### 路由优先级（`graph_recall.py`，行业通用意图）

| 问句特征 | 模板 |
|----------|------|
| 产品 + 活性成分/说明书 | `product_ingredients` |
| 患者 + 知识库/库里 + 禁忌产品 | `cross_patient_product_contra` |
| 患者 + 不宜用药/抗生素 | `patient_unsafe_meds` |
| 成分 + 禁忌/相关产品 | `drug_overview` / `ingredient_contraindications` / `products_by_ingredient` |
| 系列 + 技术平台 | `product_series_tech`（系列名从问句/实体图解析，无品牌默认） |
| 适应症 + 产品 | `product_by_indication` |
| 系列 + 产品清单 | `product_in_series` |
| 仅提及产品 | `product_overview` |

实体槽位由 `graph-entity-map.yml` 的 slug 前缀驱动（`临床病例/`、`成分/`、`产品系列/` 等）；品牌名仅作实体数据，不写进路由正则。

模板相关性检查：问句提及成分但跨层模板未召回该成分 → 回退 `drug_overview`。

### FTS 触发条件（`server.py`，修订后）

- 图谱未命中或上下文 < 4 块 → FTS
- `template_matches_question` 为 False → FTS
- 问句含禁忌/成分等关键词，但模板**不在**可信集合（`drug_overview`、`product_in_series` 等）→ FTS
- 图谱可信模板已命中 → **不强制** FTS
- `IN_SERIES` 边不全 → 补拉 `产品系列/{系列名}.md`（覆盖度检查，非 FTS）

实体驱动模板：问句提及成分时优先 `drug_overview`，不再默认落入无关的 `drug_interaction` 模板。

### 表达鲁棒性（paraphrase）

| 机制 | 作用 |
|------|------|
| `graph.aliases`（如 penicillin、盘尼西林 → 青霉素） | 换名仍认成分 |
| 意图正则 `_CONTRA_RE` / `_DRUG_PRODUCT_RE` / `_UNSAFE_MED_RE` | 同义问法（相关产品、关联药品、不能用什么药） |
| `patient_unsafe_meds` 模板 | 患者 + 不能用什么药/抗生素 → 过敏链 + 交叉禁忌 + 含成分产品 |
| `smoke_graph_recall.py` `PARAPHRASE_CASES` | 回归多种说法 |

## 问题改写层（Rewrite Gate）

在 Graph-first 检索**之前**，用 `question_rewrite.py` 把口语/歧义问句规范化为图谱友好表述；与 `server._rewrite_query`（内部搜索关键词提取，用户不可见）**分离**。

```
用户原问 → POST /ask-rewrite
         ├─ 规则预检（长度 / 注入 regex）→ blocked
         ├─ DeepSeek JSON 改写（实体提示来自 graph-entity-map）
         └─ auto_proceed?
              ├─ true  (confidence ≥ 0.75 且非 ambiguous) → 直接 /ask-stream|/ask-deep
              └─ false → product-hub 展示确认卡片（确认 / 原问 / 反馈再改）
```

| 配置项 (`kb-config.yml` → `rewrite`) | 默认 |
|--------------------------------------|------|
| `enabled` | `true` |
| `confidence_auto` | `0.75` |
| `max_chars` | `500` |

**安全边界**：规则层拦截常见 injection；改写 LLM 只输出 JSON；答题上下文仍用 Wiki 原文，不把改写结果注入答题 system message。

冒烟：`python smoke_question_rewrite.py`（规则层无需 API Key；有 Key 时跑「李娜打青霉素要注意吗」集成样例）。

Benchmark：`python benchmark_query.py`（解析 [`测试问题集.txt`](测试问题集.txt) L/S 节；`--no-llm` 跳过改写 API）。  
领导演示：见 [`演示脚本.md`](演示脚本.md)。

## 关键文件

| 文件 | 作用 |
|------|------|
| `SCHEMA.md` | 双层 + 桥接模型 + Wiki 四层 |
| `kb-config.yml` | role 分类配置 |
| `graph-entity-map.yml` | Neo4j 实体 → Wiki slug |
| `local_wiki_search.py` | 本地全文检索（替代 gbrain） |
| `graph/wiki_graph_extract.py` | 从 Wiki `graph:` 抽取事实 |
| `graph/render_wiki_relations.py` | 生成正文「图关系」+ `关系索引.md` |
| `graph/load_data.py` | Wiki → Neo4j 灌数（先 render 再 load） |
| `graph/audit_wiki_graph.py` | Wiki ↔ Neo4j 双向审计 + 目录/type 一致 |
| `graph/lint_entity_duplicates.py` | 实体重复 Gardener（只报告） |
| `graph/pi_pilot_proposal.py` | 说明书多页提案试点 |
| `question_rewrite.py` | 问句规范化 + 注入预检 + auto/confirm 决策 |
| `smoke_question_rewrite.py` | 改写层规则/集成冒烟 |
| `benchmark_query.py` | 测试问题集 L/S 自动化 Benchmark |
| `测试问题集.txt` | Gemini 六维 + 本库映射 + S 回归 |
| `演示脚本.md` | 5 分钟领导 Demo 脚本 |
| `关系索引.md` | 全部边的中文总览 |
| `临床病例/` `用药安全/` | 临床原文 |
| `疾病/` `成分/` `设备/` | 桥接原文 |
| 产品 Markdown | 产品原文（既有 + demo `graph:`） |
