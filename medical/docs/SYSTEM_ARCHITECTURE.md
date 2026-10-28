# LLM-Wiki 知识库 — 整体系统架构

> 版本: 1.0 | 日期: 2026-08-03 | 维护者: Edwin Zhou

---

## 目录

1. [系统概览](#1-系统概览)
2. [目录结构与文件系统](#2-目录结构与文件系统)
3. [配置体系](#3-配置体系)
4. [知识库数据模型](#4-知识库数据模型)
5. [HTTP 服务端点全览](#5-http-服务端点全览)
6. [上传文件工作流](#6-上传文件工作流)
7. [智能问答系统](#7-智能问答系统)
8. [自检维护系统](#8-自检维护系统)
9. [gbrain 向量搜索](#9-gbrain-向量搜索)
10. [知识图谱与前端](#10-知识图谱与前端)
11. [图片索引系统](#11-图片索引系统)
12. [部署架构](#12-部署架构)
13. [维护工作流](#13-维护工作流)

---

## 1. 系统概览

### 1.1 什么是 LLM-Wiki

LLM-Wiki 是一个**品牌无关的产品知识库系统**，将产品资料（PDF/DOCX/PPTX/Markdown）自动转化为结构化知识库，支持智能问答、3D 知识图谱浏览、上传审核和自检维护。

```
┌────────────────────────────────────────────────────────────────────┐
│                        LLM-Wiki 系统架构                            │
│                                                                    │
│  ┌──────────┐   ┌─────────────┐   ┌──────────────┐                │
│  │ 文件上传  │──→│ AI 自动处理  │──→│  知识库页面   │                │
│  │ (2种模式) │   │ (regenerate) │   │  ~6,000 页    │                │
│  └──────────┘   └─────────────┘   └──────┬───────┘                │
│                                          │                         │
│                    ┌─────────────────────┼─────────────────────┐   │
│                    │                     │                     │   │
│                    ▼                     ▼                     ▼   │
│            ┌─────────────┐     ┌──────────────┐     ┌──────────┐  │
│            │   gbrain    │     │  自检维护     │     │  3D 图谱  │  │
│            │  (向量搜索)  │     │  (enrich.py)  │     │  (D3.js)  │  │
│            └──────┬──────┘     └──────────────┘     └──────────┘  │
│                   │                                               │
│                   ▼                                               │
│            ┌─────────────┐                                        │
│            │  智能问答     │                                        │
│            │  (3 端点)    │                                        │
│            └─────────────┘                                        │
└────────────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | HTML/CSS/JS + D3.js + marked.js | 单页应用，暗色主题，3D 力导向图 |
| 后端 | Python 3.9 + http.server | 单体 HTTP 服务，多线程 |
| 向量搜索 | gbrain (Bun + PostgreSQL + pgvector) | 关键字 + 语义双通道检索 |
| AI 引擎 | DeepSeek API (deepseek-chat) | 文档处理、智能问答、关键词改写 |
| 存储 | 本地文件系统 (Markdown) | 约 6,000 个 .md 文件 |
| 配置 | YAML (kb-config.yml) | 品牌无关，一次配置即可迁移 |

---

## 2. 目录结构与文件系统

```
通用版LLM-WIKI-KB/
├── kb-config.yml              ← 全局配置（品牌/分类/服务/主题）
├── config.py                  ← 配置加载器
├── server.py                  ← HTTP 服务主程序 (2,580行)
├── regenerate-graph.py        ← 图谱生成 + 上传处理管道
├── enrich.py                  ← 自检维护引擎 (1,170行)
├── validate-taxonomy.py       ← taxonomy 验证
├── product-hub.html           ← 前端界面 (1,962行)
├── graph-data.json            ← 3D 图谱数据
├── knowledge-graph-3d.html    ← 独立 3D 图谱页
│
├── 运动表现产品/              ← 品类 #1: 运动表现
│   ├── 鞋/跑步/竞速/         ←   子分类层级
│   ├── 鞋/跑步/训练/
│   ├── 鞋/F50/
│   ├── 服装/
│   └── 配件/
├── 三叶草产品/                ← 品类 #2: Originals
│   ├── 鞋/T头鞋/
│   ├── 鞋/板鞋/
│   ├── 服装/
│   └── 配件/
├── 轻运动产品/                ← 品类 #3: Sportswear
├── 童装产品/                  ← 品类 #4: Kids
├── 科技/                      ← 科技概念页 (~75 个)
│   ├── boost.md
│   ├── lightstrike.md
│   └── ...
├── 系列/                      ← 系列概念页 (~800 个)
│   ├── adizero.md
│   ├── ultraboost.md
│   └── ...
├── 待分类/                    ← 未分类产品
│
├── raw/                       ← 原始上传文件
│   ├── articles/
│   └── extracted/
├── images/                    ← 产品图片 + manifest
│   ├── <source-doc>/
│   │   ├── manifest.json      ← 图片→产品映射
│   │   └── page_001_xxx.png
│   └── ...
│
├── _proposals/                ← AI 生成的内容提案
├── _backups/                  ← 页面历史备份
├── _meta/_issues.md           ← 自检问题报告
│
├── docs/                      ← 架构文档
├── deploy/                    ← 部署配置
│   ├── nginx-site.conf
│   └── adidas-hub.service
└── scripts/                   ← 辅助脚本
```

### 2.1 产品页面结构

```
运动表现产品/鞋/跑步/竞速/adizero-adios-pro-4.md

---
title: ADIZERO ADIOS PRO 4
type: 运动表现产品
series: adizero
product_type: 鞋·跑鞋
position: 竞速
price: 1699
attributes: [lightstrike-pro, energyrods, continental-rubber]
tags: [竞速跑鞋, 碳板跑鞋, 马拉松]
created: 2026-01-15
updated: 2026-07-20
---

## ADIZERO ADIOS PRO 4

ADIZERO ADIOS PRO 4 是 adidas 顶级马拉松竞速鞋...

## 核心科技

- **LIGHTSTRIKE PRO**: 超临界发泡中底，轻量高回弹...
- **ENERGYRODS 2.0**: 仿跖骨碳纤维能量柱...

## 相关概念

- [[科技/lightstrike-pro]]
- [[科技/energyrods]]
- [[系列/adizero]]
```

每个产品页面包含：
- **Frontmatter**: 结构化元数据（类型/系列/定位/价格/属性/标签/时间戳）
- **正文**: Markdown 格式的产品介绍
- **Wikilinks**: `[[科技/xxx]]` `[[系列/xxx]]` 交叉引用

---

## 3. 配置体系

### 3.1 配置层次

```
kb-config.yml (单一配置源)
    │
    ├── config.py (Python 加载器 → cfg 对象)
    │   └── 所有脚本 import cfg 读取
    │
    ├── ~/.hermes/.env (敏感信息)
    │   ├── DEEPSEEK_API_KEY
    │   ├── PORTAL_PASSWORD
    │   └── PORTAL_COOKIE_SECRET
    │
    └── ~/.gbrain-llm-wiki (gbrain 数据库)
        └── DATABASE_URL (隐含)
```

### 3.2 配置结构

```yaml
brand:                        # 品牌信息（迁移时改这里）
  name: "adidas"
  public_name: "llm-wiki 知识库"

categories:                   # 品类体系（5 大类 + 子分类树）
  - id: performance
    dir: "运动表现产品"
    subcategories: [鞋→跑步→竞速, ...]

taxonomy:                     # 分类法规则
  dimensions: [type, series, product_type, position, attributes]
  valid_values:               # 受控词表（所有合法值）

server:                       # 服务配置
  port: 8767
  qa_rate_limit_per_minute: 10

upload:                       # 上传配置
  allowed_extensions: [.pdf, .docx, ...]
  modes:
    - review   # 🔍 上传并审核
    - direct   # 🤖 AI 全自动收录

maintenance:                  # 自检配置
  l1_auto_fill: { cron: "0 */2 * * *", pages_per_run: 20 }
```

---

## 4. 知识库数据模型

### 4.1 页面类型

```
┌──────────────────────────────────────────────────────────────────┐
│                      知识库页面体系                                │
│                                                                   │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐          │
│  │ 产品页   │   │ 科技概念 │   │ 系列概念 │   │ 索引页   │          │
│  │ ~6,000  │   │  ~75    │   │  ~800   │   │  1      │          │
│  └────┬────┘   └────┬────┘   └────┬────┘   └────┬────┘          │
│       │             │             │             │                │
│       ▼             ▼             ▼             ▼                │
│  运动表现产品/     科技/          系列/          index.md         │
│  三叶草产品/       boost.md       adizero.md    全站索引          │
│  轻运动产品/       lightstrike.md ultraboost.md                  │
│                                                                   │
│  关系:                                                            │
│   产品 ──wikilink──→ 科技概念                                     │
│   产品 ──wikilink──→ 系列概念                                     │
│   系列 ──wikilink──→ 产品列表 (enrich.py --fix-dataview 生成)      │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 受控词表（Taxonomy）

| 维度 | 示例值 | 用途 |
|------|--------|------|
| `type` | 运动表现产品 / 三叶草产品 / 轻运动产品 / 科技 / 系列 | 页面大类 |
| `series` | adizero / ultraboost / samba / gazelle / ... | 产品系列归属 |
| `product_type` | 鞋·跑鞋 / 鞋·板鞋 / 服装·夹克 / ... | 产品形态 |
| `position` | 竞速 / 训练 / 缓震 / 休闲 / 户外 | 运动定位 |
| `attributes` | boost / lightstrike / gore-tex / carbon-plate / ... | 科技属性 |

---

## 5. HTTP 服务端点全览

`server.py` 在 `:8767` 端口提供以下端点：

### 5.1 查询端点（公开）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ask-stream` | POST | 单轮问答（SSE 流式），默认模式 |
| `/ask-deep` | POST | 深度多轮问答（SSE 步骤级） |
| `/ask` | POST | 多轮 Agent 问答（阻塞式） |
| `/kb-tree` | GET | 知识库目录树 JSON |
| `/api/page` | GET | 获取单页内容 |
| `/api/links` | GET | 获取页面 wikilinks |
| `/api/search` | GET | 简易搜索 |

### 5.2 管理端点（需认证）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/upload` | POST | 上传文件（mode=review\|direct） |
| `/api/save` | POST | 保存页面编辑 |
| `/api/proposals` | GET | 获取提案列表 |
| `/api/proposals/approve` | POST | 审批通过提案 |
| `/api/proposals/reject` | POST | 驳回提案 |
| `/api/run-check` | POST | 运行 taxonomy 验证 |
| `/api/run-improve` | POST | 运行 L1 自动填充 |
| `/api/run-improve-concepts` | POST | 运行概念页改善 |
| `/api/tasks/run` | POST | 运行指定维护任务 |
| `/history/clear` | POST | 清空上传历史 |

### 5.3 认证机制

```
Portal Password Gate:
  1. 访问任何页面 → 检查 cookie (llm_wiki_auth)
  2. 无有效 cookie → 显示登录页
  3. 登录成功 → 设置 30 天 cookie
  4. 限流: 5 次/分钟 per IP → 10 次失败锁 15 分钟
  5. READ_ONLY 模式: 公网部署时禁用所有写端点
```

---

## 6. 上传文件工作流

### 6.1 双模式设计

```
文件上传
    │
    ├── 🔍 上传并审核 (review)
    │   ┌──────────────────────────────────────┐
    │   │ ① 文件入队列 → ② AI 处理生成提案      │
    │   │ ③ 提案列表待审核 → ④ 审批通过/驳回    │
    │   │ ⑤ 通过后写入 KB + 同步 gbrain         │
    │   └──────────────────────────────────────┘
    │
    └── 🤖 AI 全自动收录 (direct)
        ┌──────────────────────────────────────┐
        │ ① 文件入队列 → ② AI 直接写入 KB      │
        │ ③ 自动同步 gbrain + 重建图谱          │
        │ (--yolo 模式，无需审核)                │
        └──────────────────────────────────────┘
```

### 6.2 处理管道

```
_trigger_ingest()  →  regenerate-graph.py
                          │
                          ├── ① gbrain import (同步新页面到向量库)
                          ├── ② AI 文档理解 (DeepSeek API)
                          ├── ③ 生成产品页 (frontmatter + 正文)
                          ├── ④ _run_link_concepts (建立 wikilink)
                          ├── ⑤ _sync_concept_pages (enrich.py --fix-dataview)
                          ├── ⑥ generate_graph (graph-data.json)
                          ├── ⑦ regenerate_index (index.md)
                          └── ⑧ gbrain import (再次同步)
```

### 6.3 文件锁机制

```python
# 防止并发处理同一文件
INGEST_LOCK_FILE = ".ingest-lock.json"
# 格式: {"pid": 12345, "ts": 1691000000}
# 15 分钟超时自动释放（防止进程崩溃死锁）
```

---

## 7. 智能问答系统

详见 [ARCHITECTURE.md](./ARCHITECTURE.md) — 深度检索架构。

快速概览：

| 端点 | LLM 调用 | 延迟 | 场景 |
|------|---------|------|------|
| `/ask-stream` | 2 次 (改写+合成) | ~5-8s | 快速问答 |
| `/ask-deep` | 4-5 次 | ~15-18s | 需要科技深度 |
| `/ask` | Hermes 子进程 | ~20-30s | 复杂多轮 |

---

## 8. 自检维护系统

### 8.1 三级体系

```
Level 1: 自动填充 (enrich.py --batch N)
  扫描 TODO 标记的产品页 → DeepSeek 生成内容 → 写入
  定时: 每 2 小时，每次 20 页

Level 2: 一致性检查 (enrich.py --check)
  4 维度扫描:
    ① TODO 页面数
    ② 未关联概念的产品数
    ③ 孤立标签数
    ④ 概念页↔产品一致性 (O(P+C) 单次扫描)
  输出: _meta/_issues.md

Level 3: AI 改善 (enrich.py --improve-concepts)
  为孤立标签生成概念页提案 → 审核界面 → 审批
```

### 8.2 维护任务

前端 "自检计划" 面板通过 `/api/tasks/run` 触发：

| 任务 ID | 命令 | 说明 |
|---------|------|------|
| `sync-concepts` | `python3 enrich.py --fix-dataview` | dataview → wikilinks |
| `improve-concepts` | `python3 enrich.py --improve-concepts` | 生成概念页提案 |
| `validate` | `python3 validate-taxonomy.py` | taxonomy 验证 |
| `enrich-l1` | `python3 enrich.py --batch 10` | L1 自动填充 |
| `enrich-l3` | `python3 enrich.py --check && 提案流程` | L3 改善 |
| `rebuild` | `python3 regenerate-graph.py` | 重建图谱+索引 |

顺序执行: `sync-concepts → improve-concepts → validate → enrich-l1 → enrich-l3 → rebuild`

### 8.3 enrich.py 子命令

```bash
python3 enrich.py --check           # 4 维一致性检查 → _meta/_issues.md
python3 enrich.py --fix-dataview    # 概念页 dataview 块 → [[wikilink]] 列表
python3 enrich.py --improve-concepts # 为孤立标签生成概念页提案
python3 enrich.py --batch 10        # L1: 填充 10 个 TODO 页
python3 enrich.py --dry-run         # 预览模式（不写入）
```

---

## 9. gbrain 向量搜索

### 9.1 是什么

gbrain 是一个基于 Bun 运行的本地向量搜索工具，使用 PostgreSQL + pgvector：
- `gbrain search <query>` — 全文搜索（tsvector）
- `gbrain query <query>` — 语义搜索（pgvector）
- `gbrain get <slug>` — 获取页面完整内容
- `gbrain import` — 增量同步 Markdown → 向量库

### 9.2 双通道检索

```
用户问题
    │
    ├── 通道 1: 关键词搜索 (tsvector)
    │   精确匹配，适合产品名/型号
    │
    └── 通道 2: 语义搜索 (pgvector)
        概念理解，适合自然语言
```

### 9.3 搜索结果增强

| 增强 | 触发条件 | 效果 |
|------|---------|------|
| 主页提升 (×1.15) | 同目录下是最短 slug | 产品主页 > 配色变体 |
| 实体查询增强 (×1.2) | "推荐/有哪些" 类问题 | entities/ 页面优先 |
| 多渠道查询 | 所有搜索 | 原问题 + LLM 改写 + jieba |
| 通用词过滤 | "系列/鞋款/推荐" 等 | 跳过噪声词 |

---

## 10. 知识图谱与前端

### 10.1 3D 知识图谱

`knowledge-graph-3d.html` 使用 D3.js 力导向图 + Three.js 渲染：

```
品牌层
  ├── 运动表现产品 ● (红色)
  ├── 三叶草产品 ● (橙色)
  ├── 轻运动产品 ● (青色)
  ├── 科技 ● (紫色)
  └── 系列 ● (蓝色)
       │
       └── 节点连接 = wikilink 关系
```

### 10.2 product-hub.html 布局

```
┌──────────┬──────────────────────────────────────────────┐
│ Sidebar  │  Top Bar (视图切换: 图谱 / 列表 / Q&A)       │
│          ├──────────────────────────────────────────────┤
│ 📊 图谱   │                                              │
│ 📋 列表   │            3D 知识图谱 / 列表 / 问答         │
│ 💬 问答   │                                              │
│ 📤 上传   │                                              │
│ 🔍 自检   │                                              │
│          │                                              │
│ Stats    │                                              │
└──────────┴──────────────────────────────────────────────┘
```

---

## 11. 图片索引系统

### 11.1 架构

```
images/
  <source-doc>/
    ├── manifest.json          ← AI 提取的图片→产品映射
    │   [{"products": [{"product": "ADIZERO SL2", "image": "page_003.png"}]}]
    └── page_003.png

启动时:
  ① _build_image_index()    → {normalized_slug: [image_paths]}
     - 308 产品，过滤 <15KB 缩略图
  ② _build_tag_image_index() → {tag: [image_slugs]}
     - 1,080 标签 → 874 产品-图片链接
```

### 11.2 Q&A 图片注入

问答完成后，从 `seen_slugs` 查找关联图片，注入到答案末尾。

---

## 12. 部署架构

### 12.1 本地开发

```bash
python3 server.py
# → http://localhost:8767/product-hub.html
```

### 12.2 公网部署

```
┌─────────┐     ┌──────────┐     ┌───────────┐
│ 用户浏览器 │ ←──→│ cloudflared│ ←──→│ localhost │
│         │     │ tunnel    │     │ :8767     │
└─────────┘     └──────────┘     └───────────┘
                    │
              公网 URL (quick tunnel, 每次重启变化)
```

```bash
# 启动隧道
cloudflared tunnel --url http://localhost:8767

# 生产部署（nginx 反代 + systemd）
deploy/deploy.sh
```

### 12.3 安全配置

```bash
# 公网只读模式
READ_ONLY=true python3 server.py
# → 禁用所有 /upload /api/save /api/proposals/approve 等写端点
```

---

## 13. 维护工作流

### 13.1 日常

```bash
cd /Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB

# 检查健康
python3 enrich.py --check
cat _meta/_issues.md

# 修复 dataview
python3 enrich.py --fix-dataview

# 重启
lsof -i :8767 -t | xargs kill
sleep 1 && python3 server.py &
```

### 13.2 上传文件后

自动触发全管道：`gbrain_sync → link_concepts → sync_concept_pages → graph → index → gbrain_sync`

### 13.3 迁移到新品牌

只需修改 `kb-config.yml`：
```yaml
brand:
  name: "newbrand"
  display_name: "NewBrand Product Knowledge Hub"
categories:
  - id: main
    dir: "主品类"
    subcategories: [...]
```

> 最后更新: 2026-08-03 | LLM-Wiki 系统架构 v1.0
