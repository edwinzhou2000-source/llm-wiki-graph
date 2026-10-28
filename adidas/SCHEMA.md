# adidas LLM-WIKI-GRAPH — Schema

## 双层模型

| 层 | 角色 | 事实源 |
|---|---|---|
| 散文层 | 唯一事实源 | 源 KB Markdown（只读）：产品 / 科技 / 系列 |
| 图层 | 派生检索索引 | Neo4j（独立容器）；由 frontmatter 确定性派生 |

图不回答；最终答案由 LLM 读原文合成。图只提供实体与关系线索。

## 与 medical 的差异

| | medical | adidas |
|---|---|---|
| 边来源 | 一事一页 fact pages 的 `graph:` frontmatter | 产品页 frontmatter 字段 + 目录名 |
| 边是否单独开页 | 是 | **否** |
| 图引擎 | Neo4j `:7687` | Neo4j `:7688`（独立容器） |

## 节点 labels

`Product` / `Tech` / `Series` / `Category` / `ProductType`

每个 label 的 `name` 有唯一约束。

**注意（已知语义损耗）**：Product `name` = 文件名 stem。跨品类同 stem 的 3 个产品会合并为一个节点、可有多条 `IN_CATEGORY`。演示可接受；严格隔离需复合键（本阶段不做）。

## 边类型（闭集 5 种）

| 边 | from → to | 派生来源 |
|---|---|---|
| `IN_SERIES` | Product → Series | 产品 `series:` |
| `USES_TECH` | Product → Tech | `tags:` 里 `科技/xxx` + `attributes:`∩科技 slug |
| `IN_CATEGORY` | Product → Category | 顶层目录名 |
| `HAS_TYPE` | Product → ProductType | 产品 `type:` |
| `SERIES_USES_TECH` | Series → Tech | 系列页「核心技术」里的 `[[科技/xxx]]` |

## 维护流程

1. 只改源 KB 的 frontmatter / 系列页（本副本不写源 KB）
2. `python3 graph/wiki_graph_extract.py`（可选自检）
3. `python3 graph/load_data.py`（刷新关系索引 + 清图重灌）
4. `python3 smoke_graph_recall.py`
