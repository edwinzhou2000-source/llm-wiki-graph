# LLM-WIKI-GRAPH

类型化关系图 + 图优先检索的 Wiki 副本演示。本仓库用于对照展示两套 Graph 实现，以及它们与 adidas 通用版 Wiki 主库的差异。

| 目录 | 是什么 |
|------|--------|
| [`adidas/`](adidas/) | adidas 产品 Graph 副本：frontmatter 派生五类边，独立 Neo4j `7688` / 门户 `8780` |
| [`medical/`](medical/) | 医药 Graph 样板：「一事一页」边页 + 临床/桥接层，Neo4j `7687` / 门户 `8770` |
| [`三系统对比-adidas-wiki-graph-medical.md`](三系统对比-adidas-wiki-graph-medical.md) | 与通用版 adidas Wiki 主库的详细对比 |

通用版主库不在本仓库（路径示例：`LLM-Wiki/通用版LLM-WIKI-KB`，门户 `8767`）。adidas 产品 Wiki 正文快照也不入库；clone 后需自行放到 `adidas/wiki/`（见 `adidas/scripts/refresh_wiki_snapshot.sh`）。

## 本仓库包含 / 不包含

**包含：** Graph 抽取与灌图代码、Cypher 召回、门户、medical 演示 Wiki（假患者 + 产品/禁忌边页）、架构文档。

**不包含：** adidas 产品 Markdown 快照、`node_modules` / `.venv`、上传附件、API 密钥。Neo4j 凭据仅为本地 demo（`adidas123` / `medical123`），**非生产**。

## 快速看懂差异

1. 先读 [三系统对比](三系统对比-adidas-wiki-graph-medical.md)。
2. adidas 边模型：[`adidas/SCHEMA.md`](adidas/SCHEMA.md)。
3. medical 边模型：[`medical/SCHEMA.md`](medical/SCHEMA.md)。

一句话：**Wiki 是事实源；Neo4j 只做定位索引；答案仍由 Markdown 原文合成。** adidas 用产品页字段投影边；medical 为每条关系单独开边页。

## 本地运行（摘要）

两套副本端口隔离，可同时启动。详情见各目录 README。

```bash
# adidas Graph
cd adidas
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
docker compose -f graph/docker-compose.yml up -d
# 将 wiki 快照放到 adidas/wiki/ 后再灌图
python3 graph/load_data.py
python3 server.py   # http://127.0.0.1:8780/

# medical Graph
cd ../medical
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
docker compose -f graph/docker-compose.yml up -d
python3 graph/load_data.py
python3 server.py   # 默认 http://127.0.0.1:8770/
```

门户密码与 DeepSeek key 来自本机 `~/.hermes/.env`（`PORTAL_PASSWORD`、`DEEPSEEK_API_KEY`），不要提交该文件。
