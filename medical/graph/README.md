# 医疗 Neo4j 知识图谱 Demo

独立小项目：假数据 + 多跳 Cypher + 可视化。不接入现有 LLM-Wiki。

## 快速开始

```bash
# 0. 本地凭据（勿提交 .env）
cp .env.example .env   # 填写 NEO4J_AUTH 与 MEDICAL_NEO4J_PASSWORD

# 1. 起 Neo4j
docker compose --env-file .env up -d

# 2. Python 环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 灌数据（可重复跑）
python load_data.py

# 4. 验证 7 条查询
python verify_queries.py

# 5. Phase 3 可视化
python viz_server.py
# 浏览器打开 http://127.0.0.1:8765
```

Neo4j Browser：http://localhost:7474（用户/密码见本目录 `.env`，勿写入仓库）

## 文件

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | Neo4j 5 |
| `load_data.py` | 幂等灌假数据 |
| `queries.cypher` | 7 条演示查询 |
| `verify_queries.py` | 自动验收 |
| `viz_server.py` + `index.html` | Phase 3 可视化（本地代理，浏览器不直连 Bolt） |

## 说明

- 全是假数据，仅用于学 Neo4j / 演示多跳能力。
- Phase 4（接入 LLM-Wiki 召回）暂缓。
