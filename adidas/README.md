# adidas LLM-WIKI-GRAPH

类型化关系图 + 图优先检索的 adidas 产品知识库副本。边从产品页 frontmatter 派生（非 medical「一事一页」）。图引擎：独立 Neo4j 容器（bolt `7688` / browser `7475`）。

> Neo4j 凭据来自 `graph/.env`（见 `graph/.env.example`）— **本地 demo，非生产**。
>
> **隔离 B**：Wiki 正文快照在本仓 `wiki/`（`source_kb_root`）；写入仅 `_uploads/_proposals/_accepted/_meta`。绝不读写 medical，也不回写通用版 LLM-Wiki。刷新快照：`scripts/refresh_wiki_snapshot.sh`。

## 快速开始

```bash
cd /Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/adidas
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 0. 本地 Neo4j 凭据（勿提交 .env）
cp graph/.env.example graph/.env   # 填写 NEO4J_AUTH 与 ADIDAS_NEO4J_PASSWORD

# 1. 独立 Neo4j（勿碰 medical 的 7687/7474）
docker compose -f graph/docker-compose.yml --env-file graph/.env up -d

# 2. 灌图（读本仓 wiki/）
python3 graph/load_data.py

# 3. 冒烟
python3 smoke_graph_recall.py

# 4. CLI（无 key 也可）
python3 query.py "哪些产品用了 boost 科技？" --no-llm

# 5. 门户（medical 风格聊天 + 改写确认 + SSE）
python3 server.py   # http://127.0.0.1:8780/ → product-hub.html
```

打开浏览器访问 **http://127.0.0.1:8780/**（需 `PORTAL_PASSWORD`，与 medical 相同，在 `~/.hermes/.env`）。

登录后进入门户 → 产品中心。写入落在副本目录 `_uploads` / `_proposals` / `_accepted` / `_meta`，**绝不写源 wiki 快照**。
## 架构要点

- 抽取：`graph/wiki_graph_extract.py` → nodes/edges
- 灌入：`graph/load_data.py` → Neo4j
- 召回：`graph_recall.py`（参数化 Cypher；含 `series_family_listing`）
- 兜底：`local_wiki_search.py`（jieba FTS）
- 改写门：`question_rewrite.py`（DeepSeek；无 key 降级）
- 门户：`server.py` + `product-hub.html`

详见 [SCHEMA.md](SCHEMA.md) / [PHASE.md](PHASE.md)。

与通用版 adidas Wiki、medical Graph 的定位与架构对照见上级目录 [三系统对比-adidas-wiki-graph-medical.md](../三系统对比-adidas-wiki-graph-medical.md)。
