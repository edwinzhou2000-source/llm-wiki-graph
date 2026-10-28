# adidas LLM-WIKI-GRAPH 版本 — 执行计划书（给 Cursor）

> 目标目录：`/Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/adidas`
> 源知识库（只读，绝不修改）：`/Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB`
> 参考实现（medical 版，勿改动）：`/Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/medical`
> 本计划由 Hermes 代理在 2026-09-07 编写，2026-09-07 修订为 **Neo4j 独立容器**方案。

---

## 0. 一句话目标

做一个 adidas 版「类型化关系图 + 图优先检索」的知识库副本，**边从产品页 frontmatter 字段确定性派生（不是 medical 的「一事一页」边页）**，图是派生检索索引，散文（源 KB 的 Markdown）仍是唯一事实源。图引擎用 **Neo4j（独立容器，不碰 medical 的实例）**。全程只读引用源 KB，不拷贝内容、不回写。

---

## 1. 核心设计决策（已锁定，不要改）

1. **图引擎 = Neo4j，独立容器**（与 medical 完全隔离）。端口 bolt `7688`、browser `7475`，独立 volume，独立凭据 `neo4j/<REMOVED>`。medical 的实例是 `7687/7474`、`<REMOVED>`，两者互不干扰。
2. **边 = frontmatter 字段，不单独开页**。与 medical 的「一事一页」刻意不同，是本版本核心差异。
3. **抽取层与引擎无关**：`extract()` 输出 nodes+edges，`load_data.py` 只负责把它灌进 Neo4j。改引擎不影响抽取。
4. **只读引用源 KB**：`kb-config.yml` 的 `paths.source_kb_root` 指向源 KB；所有扫描/读原文走 `SOURCE_KB_ROOT`，绝无写操作。
5. **端口 8780**（HTTP 服务）：8767=adidas 通用版、8770=medical wiki、8765=medical 可视化，勿冲突。
6. **不用 gbrain、不用 hermes 运行时**；检索/改写直接用 DeepSeek API（key 在 `~/.hermes/.env`）。

---

## 2. 类型化边 schema（5 种，闭集）——与引擎无关，保持不变

| 边类型 | from → to | 派生来源 |
|---|---|---|
| `IN_SERIES` | Product → Series | 产品页 frontmatter `series:` 数组 |
| `USES_TECH` | Product → Tech | 产品页 `tags:` 里 `科技/xxx` 前缀（主）+ `attributes:` 与科技 slug 精确匹配（辅） |
| `IN_CATEGORY` | Product → Category | 产品文件顶层目录名（运动表现产品/三叶草产品/轻运动产品） |
| `HAS_TYPE` | Product → ProductType | 产品页 `type:` 字段（鞋/服装/配件） |
| `SERIES_USES_TECH` | Series → Tech | 系列页正文「核心技术」里的 `[[科技/xxx]]` wikilink |

**Neo4j label 约定**：`Product` / `Tech` / `Series` / `Category` / `ProductType`。每个节点 `name` 唯一（建唯一约束）。

**节点 canonical name 约定：**
- Product = 文件名 slug stem（如 `novawave`），title 存 props
- Tech = 科技目录文件名 stem（如 `boost`、`马牌橡胶`），title 存 props
- Series = 产品页 `series:` 字段原值（如 `CLIMACOOL`、`舒适通勤系列`）
- Category = 顶层目录名；ProductType = `type:` 字段值

---

## 3. 已完成并跑通的代码（勿重写，除非改 bug）

| 文件 | 状态 | 说明 |
|---|---|---|
| `kb-config.yml` | ✅ 完成 | 品类/role/source_kb_root/端口 8780/边 schema 注释 |
| `config.py` | ✅ 完成 | 暴露 `KB_ROOT` 与 `SOURCE_KB_ROOT`，按 role 派生目录 |
| `graph/wiki_graph_extract.py` | ✅ 完成 | 从 frontmatter 派生边。**已验证输出**：nodes=6562 / edges=23818，labels: Product 5454, Series 1028, Tech 74, Category 3, ProductType 3；rels: IN_SERIES 7463, USES_TECH 4695, SERIES_USES_TECH 755, IN_CATEGORY 5457, HAS_TYPE 5448 |
| `graph/render_wiki_relations.py` | ✅ 完成 | 生成 `关系索引.md` |
| `local_wiki_search.py` | ✅ 完成 | jieba 全文检索兜底，扫描 `SOURCE_KB_ROOT` |
| `graph/typed_graph.py` | ⛔ **作废/可删** | 之前的内存图方案，被 Neo4j 取代。可留作离线冒烟，但 `graph_recall.py` 改用 Cypher 后不再依赖它 |
| `graph_recall.py` | ⚠️ 需重写引擎 + 修 3 个路由 bug（见 §4） | 当前是内存遍历版，要改成 Cypher 版 |

---

## 4. 路由的 3 个已知 bug + 精确修复方案（引擎无关，改 `_pick_template` 即可）

测试命令（改完后）：`cd /Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/adidas && python3 graph_recall.py`

**Bug A — "climacool 系列有哪些产品？" 被误路由到 tech**
现象：`climacool` 既是科技又是系列，当前 tech 分支排在 series 之前，且触发条件 `re.search(r"产品|哪些", question)` 太宽。
修复：`_pick_template` 重排优先级，**删掉「哪些」这个宽触发**。正确优先级：
1. `_TYPE_LISTING_RE`（`有哪些跑鞋|板鞋|鞋|服装|配件`）命中且 `_mentioned_type` 非空 → `products_by_type`
2. 问句含「系列」且 `_resolve_series` 命中 → `product_in_series`（若同时问科技 → `series_tech`）
3. series ∩ tech 都显式命中且 `_TECH_PRODUCTS_RE` → `series_tech_products`
4. tech 命中且**有显式科技意图**（`科技|技术|用了|搭载|采用|含`，不再用「哪些」）→ `products_by_tech`
5. category 命中且问「产品/系列」→ `products_in_category`
6. `_resolve_product` 命中 → `product_overview`
7. 兜底：tech 命中 → `products_by_tech`

**Bug B — 「碳板科技」返回空（同义词猜错）**
现象：`TECH_SYNONYMS` 硬编码 `碳板→carbon-plate`，但科技目录无 `carbon-plate`。
修复：**删除整个 `TECH_SYNONYMS` 字典**。口语同义交给改写层和 FTS 兜底，不在召回层猜。

**Bug C — 「有哪些跑鞋？」误路由到 series**
现象：「跑鞋」既是类型词也是系列名（系列/跑鞋.md），series 分支先命中返回 4 个产品。
修复：Bug A 的第 1 条（类型意图优先）即解决。

**关键词汇表（已实测，直接写死进代码，别再扫描推断）：**

- 科技 74 项（`Tech` 节点名）：`adimove, adiplus, adisoft, adituff, adiwear, aeroready, airchill, boost, bounce, bubblecomfy, chito, climacool, climaproof, climawarm, cloudfoam, continental, cordura, deltapeak, dreamstrike, dwr, energyrods, eva, fastcore, fiberskin, fibertouch, formotion, fusionfeel, fusionskin, gore-tex, hybridfeel, hybridtouch, lightboost, lightmotion, lightstrike, lighttraxion, lighttraxtion, lightweight, loose-fit, lycra, megaride, nanostrike, ortholite, polygiene, powerspine, primaloft, primeblue, primeknit, qmax, reflective-design, regular-fit, rematrixpad, repetitor, rheon, seamless, solotex, speedframe, sprintgrid, sprintweb, strikeframe, strikescale, strikeskin, techfit, torsion, tpu, traxion, wind-resistant-fabric, windrdy, 三条纹, 伞兵裤, 凉感面料, 弹力腰, 抽绳裤脚, 马牌大底, 马牌橡胶`
- 与类型词冲突的系列名：`T头鞋, 板鞋, 薄底鞋, 跑鞋, 配件`

---

## 5. 剩余待办（按顺序执行）

### 5.1 Neo4j 独立容器
新建 `graph/docker-compose.yml`：
```yaml
services:
  neo4j:
    image: neo4j:5
    container_name: adidas-graph-neo4j
    ports:
      - "7688:7687"      # bolt（宿主 7688 → 容器 7687）
      - "7475:7474"      # browser
    environment:
      - NEO4J_AUTH=neo4j/<REMOVED>
    volumes:
      - adidas_neo4j_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:7474 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12
volumes:
  adidas_neo4j_data:
```
启动：`docker compose -f graph/docker-compose.yml up -d`（勿碰 medical 的 `medical-graph-demo` compose）。

### 5.2 `graph/load_data.py`（extract → Neo4j）
照抄 medical 的 `graph/load_data.py`（`/Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/medical/graph/load_data.py`），改动：
- `URI = "bolt://localhost:7688"`，`AUTH = ("neo4j", "<REMOVED>")`
- `LABELS = ("Product", "Tech", "Series", "Category", "ProductType")`
- `load_from_wiki` 直接吃 `extract()` 的 nodes/edges（`merge_node`/`merge_rel` 逻辑照抄）
- `main()` 里先 `render_index()`（可选）再 extract → 清图 → 灌图，打印 nodes/relationships 计数
- 唯一约束：每个 label 的 `name` 唯一

### 5.3 `graph_recall.py` 重写为 Cypher 版
保留现有实体检测（`_mentioned_tech`/`_resolve_series`/`_mentioned_category`/`_mentioned_type`/`_resolve_product`、`ALIAS_MAPS`、`_build_entity_indexes`）与 `GraphRecallResult` dataclass，把执行层从 `TypedGraph` 换成 Neo4j：
- `NEO4J_URI = os.environ.get("ADIDAS_NEO4J_URI", "bolt://localhost:7688")`，`AUTH = ("neo4j", "<REMOVED>")`
- 每个模板输出 Cypher 字符串，`_run_cypher` 用 `neo4j` driver 执行（照抄 medical 的 `_run_cypher`）
- 模板 Cypher（label 用 adidas 的）：
  - `products_by_tech`：`MATCH (p:Product)-[:USES_TECH]->(t:Tech {name:$tech}) RETURN t.name AS tech, collect(DISTINCT p.name) AS products`
  - `product_in_series`：`MATCH (p:Product)-[:IN_SERIES]->(s:Series {name:$series}) RETURN s.name AS series, collect(DISTINCT p.name) AS products`
  - `products_in_category`：`MATCH (p:Product)-[:IN_CATEGORY]->(c:Category {name:$cat}) RETURN c.name AS category, collect(DISTINCT p.name) AS products`
  - `products_by_type`：`MATCH (p:Product)-[:HAS_TYPE]->(ty:ProductType {name:$type}) RETURN ty.name AS type, collect(DISTINCT p.name) AS products`
  - `series_tech`：`MATCH (s:Series {name:$series})-[:SERIES_USES_TECH]->(t:Tech) RETURN s.name AS series, collect(DISTINCT t.name) AS techs`
  - `series_tech_products`：`MATCH (p:Product)-[:IN_SERIES]->(s:Series {name:$series}), (p)-[:USES_TECH]->(t:Tech {name:$tech}) RETURN s.name AS series, t.name AS tech, collect(DISTINCT p.name) AS products`
  - `product_overview`：`MATCH (p:Product {name:$product}) OPTIONAL MATCH (p)-[:USES_TECH]->(t:Tech) OPTIONAL MATCH (p)-[:IN_SERIES]->(s:Series) OPTIONAL MATCH (p)-[:IN_CATEGORY]->(c:Category) OPTIONAL MATCH (p)-[:HAS_TYPE]->(ty:ProductType) RETURN p.name AS product, collect(DISTINCT t.name) AS techs, collect(DISTINCT s.name) AS series, collect(DISTINCT c.name) AS category, collect(DISTINCT ty.name) AS type`
  - 注意：Cypher 里变量不要和 label 名冲突（`ty` 而非 `type`；`cat` 而非 `category`）
- `load_source_page` / `build_context_block` 不变（仍读 `SOURCE_KB_ROOT` 原文）
- `_slugs_for` 用 `ENTITY_INDEXES`（节点名 → slug），已在 `_build_entity_indexes` 里，保留

### 5.4 `question_rewrite.py`（问句改写门）
参考 medical 的 `question_rewrite.py`，实体提示换成 adidas 的科技/系列/品类/类型名；规则层（注入拦截、长度、空问句）无需 key；改写层用 DeepSeek JSON；无 `DEEPSEEK_API_KEY` 时降级 `rewritten=original, confidence=0.5, ambiguous=True, auto_proceed=False`。

### 5.5 `query.py`（CLI 入口，验证全链路）
`python3 query.py "哪些产品用了 boost 科技？"`：`rule_precheck` → `graph_recall.recall` → 命中则 `build_context_block` 拼事实+原文；图未命中 → `local_wiki_search.search` 兜底；有 `DEEPSEEK_API_KEY` 则拼 system prompt（KB-only）作答，否则打印召回结构 + 源 slug。**无 key 也必须能跑通。**

### 5.6 `server.py`（最小 HTTP，端口 8780）
仅核心端点：`GET /health`、`POST /ask`（走 query.py 逻辑）、`GET /graph/stats`（连 Neo4j 数 nodes/edges）。用 stdlib `http.server` 或 Flask（避免新增依赖优先 stdlib）。

### 5.7 `smoke_graph_recall.py` + `benchmark_query.py` + `测试问题集.txt`
- 冒烟：断言「boost 科技→products_by_tech」「climacool 系列→product_in_series」「运动表现→products_in_category」「有哪些跑鞋→products_by_type」「ultra boost 系列用了什么科技→series_tech」都 hit，且一个确定性否定（不存在的科技）rows=0。
- benchmark：15~20 条 adidas 查询，跑 recall+FTS，输出 `_meta/benchmark_reports/benchmark_<ts>.md`，`--no-llm` 默认跳过改写。

### 5.8 文档 + 依赖
- `SCHEMA.md`：双层模型、5 边、与 medical「一事一页」的差异、目录→边映射、维护流程（改 frontmatter → extract → load_data）
- `README.md`：快速开始（compose up → load_data → smoke → query）
- `PHASE.md`：为何用 Neo4j 独立容器、为何边=字段不=页、诚实边界
- `requirements.txt`：`neo4j>=5.0,<6.0`、`pyyaml`、`jieba`
- 建独立 venv：`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`（**不要**复用 medical 的 `.venv`，保持隔离）

---

## 6. 验证清单（Cursor 完成后逐条跑通才算 done）

```bash
cd /Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/adidas
source .venv/bin/activate

# 1. 起独立 Neo4j
docker compose -f graph/docker-compose.yml up -d
#    等 healthcheck 通过（docker ps 显示 healthy）

# 2. 图派生（引擎无关）
python3 graph/wiki_graph_extract.py
#    期望 nodes=6562 edges=23818（源 KB 新增会略变）

# 3. 灌图
python3 graph/load_data.py
#    期望打印 loaded nodes/relationships 计数

# 4. 关系索引
python3 graph/render_wiki_relations.py

# 5. 召回冒烟（全绿）
python3 smoke_graph_recall.py

# 6. CLI（无 key 也跑通）
python3 query.py "哪些产品用了 boost 科技？"
python3 query.py "climacool 系列有哪些产品？"

# 7. benchmark
python3 benchmark_query.py --no-llm

# 8. server（可选）
python3 server.py   # curl http://127.0.0.1:8780/health
```

**隔离校验（必须做）**：
1. `docker ps` 里 medical 的 `medical-graph-demo-neo4j-1` 仍在 7687/7474 运行，adidas 的是新的 `adidas-graph-neo4j` 在 7688/7475。
2. 源 KB 与 medical 目录零改动：`git -C /Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB status`（非 git 仓库则比对目录无新增文件）。
3. 本版本唯一写操作：写本目录的 `关系索引.md` 和 `_meta/`，以及向自己的 Neo4j 容器灌图。绝无写源 KB / medical 容器。

---

## 7. 诚实边界（写进 PHASE.md，不要夸大）

1. **adidas 的 `series:` frontmatter 有噪声**（1028 个 Series 节点混有 `ORIGINALS`/`TRAINING`/`SPORTSWEAR`/`HIIT 高强度间歇性训练` 等非系列标签）。图如实反映数据；文档须明说「图覆盖质量取决于 frontmatter 规范程度」。
2. **确定性否定只在「边已派生」时成立**：`products_by_tech` 返回空 = 覆盖集内无产品用该科技，前提是产品页 `tags`/`attributes` 已规范填写。
3. **Neo4j 是能力上位替代，但有运维成本**：多一个容器、bolt 依赖、load 步骤、图与源 KB 的一致性维护（靠 load_data 重灌，不靠自动同步）。
4. 本版本是**检索架构演示**，不是生产系统；最终答案由 LLM 读源 KB 原文合成，图只做召回。
