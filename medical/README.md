# LLM-WIKI KB — 通用品牌知识库系统

基于 adidas-gbrain-v2 提炼的通用品牌无关知识库框架。
**改一个 yml, 换一个品牌。** 旧版 `adidas-gbrain-v2` 不受影响。

## 快速开始

```bash
cd /Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB

# 1. 编辑配置 (改品牌名、品类、配色)
vim kb-config.yml

# 2. 一键初始化
bash setup.sh

# 3. 启动服务
python3 server.py
# → http://localhost:8767/product-hub.html
```

## 项目结构

```
通用版LLM-WIKI-KB/
├── kb-config.yml              ← 🔑 唯一配置文件 (改品牌只需改这个)
├── config.py                  ← 共享配置加载器 (所有脚本导入)
├── setup.sh                   ← 一键初始化脚本
├── server.py                  ← HTTP 服务 (config 驱动)
├── product-hub.html           ← SPA 前端 (fetch /api/config)
├── regenerate-graph.py        ← 入库管线 + 图谱生成
├── enrich.py                  ← L1/L2/L3 自维护
├── validate-taxonomy.py       ← 分类合规检查
├── vision-ingest.py           ← 图片 OCR + 分类
├── knowledge-graph-3d.html    ← 3D 知识图谱
├── README.md                  ← 本文件
├── deploy/                    ← 部署配置 (nginx + systemd)
├── scripts/                   ← 辅助脚本
├── images/                    ← 产品图片
├── logs/                      ← 运行日志
├── raw/                       ← 原始资料
│
└── [品类目录]                  ← setup.sh 根据 config 自动创建
    ├── index.md
    └── ...
```

## 迁移到新品牌

```bash
# 1. 复制整个目录
cp -r 通用版LLM-WIKI-KB nike-kb

# 2. 编辑 kb-config.yml
vim nike-kb/kb-config.yml
# 改 brand.name="Nike"
# 改 categories (篮球/跑步/足球...)
# 改 taxonomy.valid_values (你的标签体系)
# 改 theme 配色 (选你的品牌色)

# 3. 初始化
cd nike-kb && bash setup.sh

# 4. 启动
python3 server.py
```

## kb-config.yml 关键配置项

| 配置节 | 说明 |
|--------|------|
| `brand` | 品牌名 (内网/公网双名) |
| `paths` | kb_root, gbrain_home, env_file |
| `categories` | 品类树 (含子品类、配色) |
| `taxonomy` | 标签维度和受控词汇表 |
| `server` | 端口、cookie、限流参数 |
| `upload` | 上传模式 (审核/快速) |
| `theme` | 深空主题配色 |
| `maintenance` | 自维护 cron 配置 |

## 架构特性

- **双通道混合检索**: 关键词 (tsvector) + 语义 (pgvector) → slug_best 融合
- **SSE 流式问答**: DeepSeek 直连, token 级实时渲染
- **链接增强 RAG**: wikilinks 图遍历 → 召回覆盖率提升 4.4×
- **双模式上传**: 审核提案 (人工审核) / 快速收录 (AI 直写)
- **三级自维护**: L1 自动填充 / L2 一致性检查 / L3 AI 改进提案
- **四层安全**: 密码外置 · 登录限流 · Cookie 签名 · 写入认证

## 外部依赖

| 依赖 | 用途 | 能否脱离 |
|------|------|----------|
| DeepSeek API | Q&A + enrichment | ✅ 可替换 (改 env) |
| gbrain CLI (Bun) | 搜索引擎 | ✅ 可替换 (换搜索后端) |
| **hermes CLI** | **上传入库 / Q&A / 语义匹配** | ❌ 当前版本不可脱离 |
| DashScope Vision | OCR + 图片分类 | ✅ 可替换 (换 Vision API) |
| cloudflared | 公网隧道 | ✅ 可替换 (换隧道方案) |

### hermes 依赖详解

当前版本对 hermes 的依赖远超 "上传入库" 四个字能概括。实际上 **hermes 是系统的 AI Agent 运行时**，`regenerate-graph.py` 和 `server.py` 都通过 `subprocess.run(['hermes', 'chat', ...])` 调用 hermes 来完成以下任务：

| 调用位置 | 功能 | hermes 命令 |
|----------|------|-------------|
| `regenerate-graph.py` (direct 模式) | AI 自动收录 — 读取原始文档，提取产品信息，写入结构化 .md 页面 | `hermes chat --yolo --max-turns 15` |
| `regenerate-graph.py` (review 模式) | AI 生成审核提案 — 写入 staging 目录，供人工审批 | `hermes chat --yolo --max-turns 20` |
| `regenerate-graph.py` (LLM 语义匹配) | 判断新上传内容是否与已有产品重复 | `hermes chat --yolo --max-turns 1` |
| `server.py` (Q&A 深入模式) | 知识库问答的深入推理链路 | `hermes chat --yolo --max-turns 3` |

### hermes skills 依赖

除了 CLI 本身，系统还依赖以下 hermes skills（由 hermes 在运行时自动加载）：

| Skill | 用途 | 被谁使用 |
|-------|------|----------|
| `wiki-ingest` | 定义上传入库的结构化格式（frontmatter、章节、文件命名规范），确保 hermes 产出的 .md 页面格式一致 | `regenerate-graph.py` 中的 `hermes chat` 调用 |
| `gbrain-knowledge-base` | 提供 `vision-ingest.py` 脚本用于 PDF 图片提取和 OCR 分类 | `batch_extract_images.sh` 直接引用 `~/.hermes/skills/wiki/gbrain-knowledge-base/scripts/vision-ingest.py` |
| `wiki-query` / `wiki-stage-commit` 等 | 自维护（enrich.py）中间接依赖的问答和审核流程 | `enrich.py` 的 L1/L2/L3 自维护链路 |

### 为什么当前版本不能脱离 hermes

1. **hermes 是 Agent，不是简单的 LLM wrapper。** 上传入库流程需要多轮自主操作：hermes 先 `read_file` 读取原始文档，分析内容，提取产品信息，再 `write_file` 写入结构化页面。这需要 hermes 的工具调用能力和 `--max-turns` 的多轮推理。直接调用 DeepSeek API 只能做单轮问答，无法替代。

2. **wiki-ingest skill 定义了输出格式规范。** 产品页面的 YAML frontmatter 字段（title, brand, category, series, attributes, summary）和章节结构（编辑概要、定位与价格、核心卖点、适用场景）都由 `wiki-ingest` skill 定义和约束。脱离 hermes 意味着需要在自己的代码里重新实现这套格式逻辑。

3. **环境变量集中在 `~/.hermes/.env`。** API key、密码等敏感配置都由 hermes 的 .env 管理，系统通过 `python-dotenv` 加载。

4. **自维护系统（enrich.py）建立在 hermes 的 skill 生态之上。** L1 自动填充、L3 AI 改进提案都依赖 hermes 调用 wiki 系列 skill 来理解知识库结构和生成改进建议。

**脱离 hermes 的迁移路径（未实现）**：理论上可以从 `regenerate-graph.py` 中抽出 prompt 模板，用 OpenAI/DeepSeek SDK 直接调用 LLM + 自行实现文件读写逻辑；同时将 wiki-ingest skill 的格式定义内联到 `config.py` 中；最后把环境变量迁移到独立的 `.env` 文件。但这需要大量重构，且会丧失 hermes 的多轮 Agent 能力和 skill 生态，因此当前版本未做此迁移。

## 环境变量

全部在 `~/.hermes/.env`:

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | 必填 — Q&A + enrichment |
| `PORTAL_PASSWORD` | 必填 — 门户登录密码 |
| `PORTAL_COOKIE_SECRET` | 必填 — 64位 hex Cookie 签名 |

## 与旧版 adidas-gbrain-v2 的关系

- 旧版 (`/Users/edwin.zhou/adidas-gbrain-v2`) **不受影响**, 继续独立运行
- 新版从旧版提取了所有功能, 但将所有品牌特定配置抽到了 `kb-config.yml`
- 旧版端口 8767, 新版也默认 8767 — **不要同时启动两个**
- 旧版 gbrain DB: `~/.gbrain-adidas-v2`, 新版: `~/.gbrain-llm-wiki`
