# LLM-Wiki 知识库 — 深度检索架构文档

> 版本: 2.0 | 日期: 2026-08-03 | 维护者: Edwin Zhou

---

## 目录

1. [系统概览](#1-系统概览)
2. [三个问答端点对比](#2-三个问答端点对比)
3. [深度检索完整架构](#3-深度检索完整架构)
4. [关键组件详解](#4-关键组件详解)
5. [v1→v2 优化历程](#5-v1v2-优化历程)
6. [性能指标与参数](#6-性能指标与参数)
7. [已知陷阱与修复](#7-已知陷阱与修复)
8. [调试方法](#8-调试方法)
9. [维护工作流](#9-维护工作流)

---

## 1. 系统概览

### 1.1 项目定位

LLM-Wiki 是一个**品牌无关的产品知识库**（通用版），基于 gbrain（PostgreSQL + pgvector）存储和检索，通过 DeepSeek API 实现智能问答。

```
┌──────────────────────────────────────────────────────┐
│                    LLM-Wiki KB                        │
│                                                       │
│  ┌─────────┐   ┌──────────┐   ┌───────────────────┐  │
│  │ Markdown │ → │  gbrain  │ → │  Q&A Endpoints    │  │
│  │ 页面文件  │   │ (向量搜索) │   │  /ask /ask-stream │  │
│  │ (~6000页) │   │          │   │  /ask-deep        │  │
│  └─────────┘   └──────────┘   └───────────────────┘  │
│                                       ↓               │
│                                 DeepSeek API          │
│                                 (deepseek-chat)       │
└──────────────────────────────────────────────────────┘
```

### 1.2 核心文件

| 文件 | 作用 |
|------|------|
| `server.py` (2559行) | HTTP 服务，三个问答端点，上传管理 |
| `regenerate-graph.py` | 知识图谱生成（品牌→品类→系列→产品） |
| `enrich.py` | 一致性检查 + dataview→wikilink 转换 |
| `product-hub.html` | 前端界面（3D图谱 + 智能问答） |
| `config.py` / `kb-config.yml` | 品牌无关配置 |
| `~/.gbrain-llm-wiki` | gbrain 向量数据库目录 |

### 1.3 数据规模

- 产品页面: ~6,000（运动表现 / 三叶草 / 轻运动）
- 科技概念页: ~75
- 系列概念页: ~800
- 图片索引: 308 产品，1,080 标签→874 图片链接

---

## 2. 三个问答端点对比

| 维度 | `/ask` | `/ask-stream` (单轮) | `/ask-deep` (深度) |
|------|--------|---------------------|--------------------|
| **机制** | Hermes 子进程 | gbrain → DeepSeek | 两阶段 ReAct Agent |
| **流式** | ✗ 阻塞 | ✓ SSE token 级 | ✓ SSE 步骤级 |
| **LLM 调用** | 1 次 | 2 次 (改写+合成) | 4-5 次 |
| **检索深度** | 单次搜索 | 单次搜索 + 概念展开 | 宽搜索 + 缺口分析 + 定向读取 |
| **前端按钮** | (未暴露) | ⚡ 单轮 | 🔍 深度 |
| **适用场景** | 多轮对话 | 快速问答 | 需要科技深度的问题 |

### 选择建议

```
简单问题 "什么是 BOOST？"            → ⚡ 单轮 (快)
列表问题 "ADIZERO 有哪些鞋款？"       → ⚡ 单轮 (够用)
复合问题 "有哪些鞋款？各自什么科技？"  → 🔍 深度 (单轮难以同时列全+补科技)
对比问题 "ADIOS PRO 4 vs VAPORFLY"   → 🔍 深度 (需要多维度对比)
```

---

## 3. 深度检索完整架构

### 3.1 整体流程

```
用户问题
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 0: 宽基础搜索 (0.5-2s)                                     │
│                                                                  │
│ ① gbrain_search(question, limit=20)  双通道 (关键字+语义)        │
│ ② 读前10页全文 (gbrain_get)                                      │
│ ③ 系列概览页注入 (regex 匹配 "X系列有哪些...")                    │
│ ④ 概念链接展开 (expand_concept_links, max 8)                      │
│ ⑤ 科技概念自动注入 (扫描 [[科技/...]] wikilink, max 6)            │
│                                                                  │
│ 输出: context (初始上下文，20-30K 字符，永不截断)                  │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: 缺口分析 (会话 #1，~5-10s)                               │
│                                                                  │
│ 工具: 仅 kb_get_page (无 kb_search！初始搜索已全面)               │
│                                                                  │
│ DeepSeek API:                                                    │
│   model: deepseek-chat                                          │
│   tools: [kb_get_page]                                          │
│   max_tokens: 8000 (防止 8-10 个调用时 JSON 截断)                │
│   temperature: 0.5                                              │
│                                                                  │
│ 模型任务:                                                        │
│   "快速浏览初始上下文，只在科技信息完全空白时才读取。               │
│    最多 3-5 个页面，选信息缺口最大的。"                            │
│                                                                  │
│ 安全限制:                                                        │
│   - 硬上限 8 次工具调用 (for tc in tool_calls[:8])               │
│   - json.loads() 包裹 try/except (防畸形 JSON 崩溃)              │
│   - 每个 kb_get_page 返回 body[:6000]                            │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2a: 补充读取 (会话 #2，全新对话，~3-5s)                      │
│                                                                  │
│ 对话完全隔离 — 不共享 Phase 1 历史                                │
│                                                                  │
│ gathered = 完整初始 context (永不截断!)                           │
│          + Phase 1 的 kb_get_page 结果                           │
│          (跳过 Phase 1 的 kb_search 结果 — 与 context 冗余)       │
│                                                                  │
│ 工具: 仅 kb_get_page                                             │
│ max_tokens: 3000                                                │
│ 总上限: 40K 字符 (从 30K 提升，初始上下文始终完整)                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2a.5: 第二轮补充 (如果 2a 有工具调用，~2-3s)                │
│                                                                  │
│ 模型检查是否还有遗漏，再读取一轮                                   │
│ max_tokens: 3000                                                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2b: 纯文本合成 (会话 #3，完全干净，~5-8s)                   │
│                                                                  │
│ ⚠️ 关键: 全新对话，零 function calling 历史                       │
│ (防止 DeepSeek 在纯文本中幻觉出 <invoke> XML 标签)               │
│                                                                  │
│ 工具: 无                                                         │
│ max_tokens: 2500                                                │
│                                                                  │
│ final_gathered = gathered + Phase 2a/2a.5 工具结果               │
│                                                                  │
│ 安全网: 逐行过滤残留 XML 标签                                     │
│   <invoke, </invoke, <parameter, </parameter,                    │
│   <tool_calls, </tool_calls                                     │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ 后处理                                                           │
│                                                                  │
│ ① 图片注入 (_get_images_for_slugs)                               │
│   从 seen_slugs 查找关联图片，去重，质量过滤 (≥15KB)              │
│                                                                  │
│ ② Slug 链接化 (_linkify_slugs)                                   │
│   将答案中的 slug 引用转为产品详情链接                             │
│                                                                  │
│ ③ SSE 发送                                                       │
│   event: answer → 前端渲染完整 Markdown 答案                      │
│   event: done   → 结束标记                                       │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 三会话隔离的设计原因

```
Phase 1  (会话 #1): 有 tool_calls → 对话历史被 "function calling" 污染
Phase 2a (会话 #2): 有 tool_calls → 同样被污染
Phase 2b (会话 #3): 纯文本，零污染 → 不会幻觉 XML 标签

如果 Phase 2b 共享 Phase 2a 的历史:
  → DeepSeek 看到 "assistant: tool_calls=[{...}]"
  → 即使没有工具可用，模型也会模仿输出 <invoke name="kb_get_page">...</invoke>
  → 答案中出现 XML 垃圾

三会话隔离是唯一可靠的解决方案。
系统消息 "不要输出工具调用" 无效 — 模型模仿它看到的模式。
```

### 3.3 上下文优先级策略

```
gathered 构建规则 (Phase 2a):

优先级 1 (永不截断):
  ┌─────────────────────────────────────────┐
  │ 初始 context                            │
  │ = 10 个产品页 + 系列/科技概念页          │
  │ 这些是 gbrain 搜索的最相关结果           │
  │ 占据 gathered 的前 15-25K 字符           │
  └─────────────────────────────────────────┘

优先级 2 (追加):
  ┌─────────────────────────────────────────┐
  │ Phase 1 kb_get_page 结果                │
  │ 模型明确认为信息不足而请求读取的页面       │
  │ 每个结果上限 8K 字符                     │
  └─────────────────────────────────────────┘

优先级 3 (跳过):
  ┌─────────────────────────────────────────┐
  │ Phase 1 kb_search 结果                  │
  │ 与初始 context 高度冗余                   │
  │ (同一个 gbrain_search 的数据源)          │
  │ → 直接跳过，不追加到 gathered            │
  └─────────────────────────────────────────┘

总上限: 40K 字符
如果超过: 从末尾截断 (初始 context 在最前面，始终完整)
```

---

## 4. 关键组件详解

### 4.1 gbrain_search — 双通道搜索

```python
def gbrain_search(question, limit=20):
    """
    位置: server.py line 775

    双通道:
      通道 1: gbrain search  (tsvector 全文搜索 — 精确关键词匹配)
      通道 2: gbrain query   (pgvector 语义搜索 — 概念相似度)

    多渠道查询:
      ① 原始问题 → search + query (保留短语语义)
      ② LLM 改写关键词 → search (DeepSeek 提取搜索优化词)
      ③ jieba 分词关键词 → search + query (最大召回)
         - 跳过通用词: 系列/鞋款/产品/推荐/选择...
         - 保留专业词: BOOST/LIGHTSTRIKE/ADIZERO...

    排名优化:
      - 实体查询增强 (×1.2): 问题含 "鞋款/推荐/有哪些" → entities/ 页面加分
      - 主页提升 (×1.15): 同目录下最短 slug → 产品主页 > 配色变体页
    """
```

### 4.2 expand_concept_links — 概念链接展开

```
初始上下文中有: "## 系列/adizero\n- [[运动表现产品/鞋/跑步/竞速/adios-pro-4]] ..."

expand_concept_links 扫描每个上下文页面的 [[wikilinks]]:
  - 从产品页: 只追踪 [[科技/...]] 链接 (产品→科技)
  - 从概念页: 追踪所有链接

对每个未读取的链接目标:
  → gbrain_get(target) → 追加到 context_parts
  → 上限 8 个额外页面

效果: 自动把相关的科技概念页拉入上下文，无需模型主动搜索
```

### 4.3 Phase 1: 缺口分析 prompt 设计

```
你是 llm-wiki 产品知识专家。你可以用 kb_get_page 读取特定页面。

工作流程:
  1. 我已为你执行了全面的初始搜索（20条结果），结果在 <initial_context> 内
  2. 快速浏览初始结果：如果产品页已包含科技说明，不需要再读。
     只对确实缺少科技信息的关键产品，用 kb_get_page 补充读取
  3. ⚠️ 限制：最多读取 3-5 个页面，只读信息缺口最明显的。
     不要为了「完整性」而遍历所有产品
  4. 之后会有后续阶段综合所有信息生成最终回答

规则:
  - 严格只使用知识库内容回答
  - 初始上下文已经涵盖了最相关的产品页面，只在科技信息完全空白时才读取
  - 最多读取 3-5 个页面，选择信息缺口最大的产品
  - 不要重复读取已有足够信息的页面

设计要点:
  ✓ 强调初始上下文已足够 → 避免 "确认性重复读取"
  ✓ 明确数量上限 → 防止遍历所有产品
  ✓ "科技信息完全空白" (不是 "可能不完整") → 提高触发门槛
```

### 4.4 工具调用安全机制

```python
# server.py Phase 1 工具调用循环 (line ~2106)

if msg.get("tool_calls"):
    messages.append(msg)

    # ① 硬上限: 最多 8 次调用
    max_p1_calls = min(len(msg["tool_calls"]), 8)

    for tc in msg["tool_calls"][:max_p1_calls]:
        fn = tc["function"]
        fn_name = fn["name"]

        # ② 防崩溃: try/except 包裹 json.loads
        try:
            fn_args = json.loads(fn["arguments"])
        except json.JSONDecodeError as e:
            # DeepSeek 可能因 max_tokens 截断而产生畸形 JSON
            # 跳过这个调用，不崩溃整个请求
            print(f"[deep-p1] bad tool args for {fn_name}: {e}")
            messages.append({
                "role": "tool", "tool_call_id": tc["id"],
                "content": f"工具参数解析失败: {e}"
            })
            continue

        # ③ 质量: kb_get_page 返回完整页面 (6000 字符)
        if fn_name == "kb_get_page":
            full = gbrain_get(slug)
            body = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
            page_content = body[:6000]
```

### 4.5 图片注入

```python
def _get_images_for_slugs(slugs, question=""):
    """
    位置: server.py line 225

    从 seen_slugs (问答涉及的所有页面) 查找关联产品图片:
      1. 精确匹配: slug 直接命中图片标签
      2. 产品名匹配: 从 slug 提取产品名，模糊匹配图片文件名
      3. 问题匹配: 从问题提取关键词，匹配图片标签

    过滤:
      - 去重 (同一图片文件不重复)
      - 质量过滤 (≥15KB，太小的是缩略图/噪声)

    输出: Markdown 图片列表
    """
```

---

## 5. v1→v2 优化历程

### 5.1 v1 的问题（2026-07 之前）

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ 初始搜索(10) │ ──→ │ Phase 1      │ ──→ │ Phase 2 上下文   │
│ 读6页全文    │     │ kb_search 🔴  │     │ = 初始 + 搜索结果 │
│ 单轮同款     │     │ (300字摘要)   │     │ → 30K 截断 🔴    │
└─────────────┘     │ kb_get_page  │     └─────────────────┘
                    └──────────────┘

问题链:
  ① 初始搜索与单轮相同 → 没有"深度"优势
  ② kb_search 返回 300 字符片段 → 远低于初始上下文的 10000 字符全文
  ③ gathered 截断丢失初始高质量页面 → 最终上下文不如单轮
  ④ 冗余的 kb_search 调用 → 延迟 ×3，答案质量可能更差
```

### 5.2 v2 的核心改进（2026-08-03）

| # | 改进 | 旧值 | 新值 | 原理 |
|---|------|------|------|------|
| 1 | 初始搜索广度 | limit=10, 读6页 | limit=20, 读10页 | 宽基础: 给 Phase 1 更丰富的素材 |
| 2 | Phase 1 工具 | kb_search + kb_get_page | 仅 kb_get_page | 不重新搜索: 初始搜索已足够 |
| 3 | 上下文构建 | 从 messages 解析, 30K 截断 | context 为基础, 40K 上限 | 永不丢失初始高质量页面 |
| 4 | 冗余过滤 | 所有工具结果都追加 | 跳过 kb_search 结果 | 避免低质片段稀释 |
| 5 | Phase 1 max_tokens | 2500 | 8000 | 防止 8-10 调用时 JSON 截断 |
| 6 | 调用上限 | 无 | 8 次 | 防止 prompt 过激时的遍历行为 |
| 7 | JSON 解析 | 裸 json.loads | try/except 包裹 | 防止畸形 JSON 导致整个请求崩溃 |
| 8 | Phase 1 prompt | "找出信息不完整的产品" | "只在完全空白时读取, 3-5 个" | 提高触发门槛, 减少不必要读取 |
| 9 | Phase 2a max_tokens | 2000 | 3000 | 给模型空间分析+调用工具 |

### 5.3 实测对比

**测试问题: "ADIZERO 系列有哪些鞋款？各自用了什么科技？"**

| 指标 | v1 (优化前) | v2 (优化后) |
|------|------------|------------|
| Phase 1 tool_calls | 12-20 (过度) | 4-5 (适度) |
| gathered 大小 | 30K+ (触发截断) | ~19K (远低于上限) |
| 答案完整性 | 部分鞋款缺科技 | 17 款鞋 完整科技表格 |
| 错误率 | 20 次调用时 JSON 崩溃 | 零错误 |
| 答案长度 | 不确定 | 1774 字符 |

---

## 6. 性能指标与参数

### 6.1 延迟分解 (典型查询)

```
Phase 0: 初始搜索        0.3s  gbrain_search(20)
         页面读取         1.5s  10 × gbrain_get
         概念展开         0.5s  expand_concept_links
         DeepSeek 改写    1.0s  _rewrite_query
Phase 1: 缺口分析        1.5s  DeepSeek API + 4-5 × gbrain_get
Phase 2a: 补充读取       2.0s  DeepSeek API (3000 tokens)
Phase 2a.5: (可选)       1.5s  如果 2a 有工具调用
Phase 2b: 纯文本合成     8.0s  DeepSeek API (2500 tokens), 上下文 ~20K chars
后处理: 图片+链接        0.2s  _get_images_for_slugs + _linkify_slugs
─────────────────────────────────
总计:                    ~15-18s (含 4-5 次 LLM 调用)
```

### 6.2 关键参数表

| 参数 | 值 | 位置 | 调整依据 |
|------|-----|------|---------|
| 初始搜索 limit | 20 | handle_ask_deep line 1919 | 2× 单轮, 给 Phase 1 更宽素材 |
| 初始全文读取 | 10 页 | handle_ask_deep line 1965 | 覆盖搜索结果前 50% |
| Phase 1 max_tokens | 8000 | line 2087 | 每个 tool call JSON ~200 字符, 8 个 ≈ 1600 字符, 加分析文本 2000 字符 → ~3600 字符, 8000 token 余量充足 |
| Phase 1 调用上限 | 8 | line 2107 | prompt 限制 3-5, 硬上限 8 做安全网 |
| Phase 1 单结果上限 | 6000 字符 | line 2148 | 大部分产品页 ~400-1000 字符, 概念页可达 10K+ (截断) |
| Phase 2a max_tokens | 3000 | line 2250 | 补读 + 初步分析需要空间 |
| Phase 2b max_tokens | 2500 | line 2370 | 纯文本合成, 与单轮一致 |
| gathered 总上限 | 40K 字符 | line 2208 | 初始 context ~25K + 5 个工具结果 × 3K → 不触发截断 |
| 概念链接展开 | max 8 | expand_concept_links | 8 个额外页面通常足够覆盖相关科技 |
| 科技自动注入 | max 6 | handle_ask_deep line 1991 | 避免科技页过多 (每个可达 10K+) |
| temperature | 0.5 | 全局 | 平衡创造性和稳定性 |

### 6.3 规模考量

```
上下文体积预算:
  初始 context:    ~20-25K chars  (10 产品页 × 1K + 系列/科技页 × 10-15K)
  概念展开:         ~5-10K chars   (8 × ~1K)
  科技注入:         ~5-20K chars   (6 × ~3K, 长列表页可达 10K)
  Phase 1 补充:     ~5-15K chars   (4-5 × ~3K)
  ─────────────────────────────
  gathered 合计:    ~25-35K chars  (通常不触发 40K 上限)
```

---

## 7. 已知陷阱与修复

### 7.1 Function Calling XML 幻觉 (P0)

**症状**: 最终答案中出现 `<invoke name="kb_get_page">...</invoke>` XML 标签

**根因**: Phase 2b 如果共享 Phase 1 或 Phase 2a 的对话历史，DeepSeek 会模仿历史中的 tool_calls 模式，即使当前请求没有工具可用。

**修复**: 三会话隔离。Phase 2b 使用全新的 `final_messages`，只包含 `[system + gathered_text + question]`，零 function calling 历史。

**安全网**: 逐行过滤残留标签:
```python
if stripped.startswith(('<invoke', '</invoke', '<parameter',
                        '</parameter', '<tool_calls', '</tool_calls')):
    continue
```

### 7.2 Phase 1 工具调用失控 + JSON 崩溃 (P0)

**症状**: 用户看到 `❌ Unterminated string starting at: line 1 column 2 (char 1)`

**根因链**:
```
旧 prompt "找出所有信息不完整的产品"
  → 模型生成 20 个 tool_call
  → 20 × ~200 字符 JSON ≈ 4000 字符
  → 超过 max_tokens=2500/4000 → DeepSeek 截断最后一个 JSON
  → json.loads() 收到残缺 JSON → 崩溃
```

**修复 (4层)**:
1. max_tokens: 2500 → 4000 → 8000 (根除 JSON 截断)
2. 硬上限: 8 次调用 (for tc in tool_calls[:8])
3. try/except: 三处 json.loads 全部包裹
4. prompt: "最多 3-5 个，只在完全空白时读"

### 7.3 patch 工具双重转义 `\n` (P0 工作流陷阱)

**症状**: 用 patch() 编辑 Python 源码中的 `"字符串\\n"` 后，文件变成 `"字符串\\\\n"`

**检测**: `xxd server.py | grep '5c5c6e'` → 看到两个 `5c` (双反斜杠) ← 坏了

**正确**: `5c6e` (一个反斜杠 + n) ← Python raw string `\n`

**Workaround**: 不要用 patch() 编辑含 `\n` 转义的 Python 字符串。
改用 `python3 << 'PYEOF'` heredoc + `content.replace()`。

### 7.4 DeepSeek 503 (请求过大)

**症状**: `resp.status_code == 503`，但简单 "hi" 请求返回 200

**根因**: 请求体 >~50K 字符时 DeepSeek 拒绝

**修复**: gathered 上限 40K，优先级截断（初始上下文永不丢失）

### 7.5 主页被配色变体淹没

**症状**: 产品技术页面被 14 个配色变体页挤到后面

**修复**: `gbrain_search` 中的主页提升 (×1.15):
```python
# 同目录下最短 slug → 产品主页
if longer.startswith(short + '-') or longer.startswith(short + '/'):
    slug_best[short]['score'] *= 1.15
```

---

## 8. 调试方法

### 8.1 实时日志

```bash
# 查看服务器日志 (含所有 [deep-p*] 标记)
tail -f /path/to/server-output

# 关键日志行:
[deep-p1] finish=tool_calls, content=True, tool_calls=5   # Phase 1 完成, 5次调用
[deep-p2-gathered] len=19155                               # 上下文大小
[deep-p2] content_len=1774                                 # 答案长度
[deep-search] slugs=31, images=3, answer_preview='...'     # 最终结果
```

### 8.2 健康检查

```bash
# 1. 简单测试
curl -X POST http://localhost:8767/ask-deep \
  -H "Content-Type: application/json" \
  -d '{"question":"你好","lang":"zh"}' --max-time 30

# 2. 复杂查询测试
curl -X POST http://localhost:8767/ask-deep \
  -H "Content-Type: application/json" \
  -d '{"question":"ADIZERO 系列有哪些鞋款？各自用了什么科技？","lang":"zh"}' \
  --max-time 90

# 3. 单轮对比
curl -X POST http://localhost:8767/ask-stream \
  -H "Content-Type: application/json" \
  -d '{"question":"ADIZERO 系列有哪些鞋款？","lang":"zh"}' \
  --max-time 30

# 4. 语法验证
python3 -c "import ast; ast.parse(open('server.py').read()); print('OK')"
```

### 8.3 问题诊断决策树

```
用户报告答案质量差:
  ├─ 答案有 XML 标签?
  │   └─ Phase 2b 会话隔离失效 → 检查 final_messages 构建
  │
  ├─ 答案说 "知识库未收录" 很多次?
  │   ├─ 检查 Phase 1 tool_calls 数量 (日志 [deep-p1])
  │   ├─ 如果 < 3: prompt 太保守 → 放宽 "完全空白" 条件
  │   └─ 如果 > 8: 被硬上限截断 → 检查哪些页面被跳过
  │
  ├─ 答案遗漏重要产品?
  │   ├─ 检查初始搜索是否包含 (gbrain_search 结果)
  │   └─ 系列概览页是否注入成功 (日志 "定位系列概览页")
  │
  ├─ 回答太慢 (>30s)?
  │   ├─ 检查 tool_calls 数量 → 过多读取
  │   ├─ 检查 gathered 大小 → >40K 可能触发截断+重试
  │   └─ 检查 DeepSeek API 延迟 → 可能 503 重试
  │
  └─ 报错 "Unterminated string"?
      └─ JSON 截断 → 检查 max_tokens 是否 >= 8000
```

---

## 9. 维护工作流

### 9.1 日常维护

```bash
cd /Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB

# 一致性检查 → 输出 _meta/_issues.md
python3 enrich.py --check

# 修复概念页 dataview 块 → wikilinks (让 gbrain 可检索)
python3 enrich.py --fix-dataview

# 重启服务
lsof -i :8767 -t | xargs kill
sleep 1
python3 server.py &
```

### 9.2 上传文件后的处理管道

```
文件上传 → 队列 → AI 处理:
  1. gbrain_sync        (导入新页面到向量数据库)
  2. _run_link_concepts  (建立产品→概念 wikilink)
  3. _sync_concept_pages (enrich.py --fix-dataview)
  4. generate_graph      (regenerate-graph.py → graph-data.json)
  5. regenerate_index    (重建索引)
  6. gbrain_sync         (同步变更)
```

### 9.3 修改代码后的检查清单

- [ ] `python3 -c "import ast; ast.parse(open('server.py').read()); print('OK')"`
- [ ] 重启 server
- [ ] 简单查询冒烟测试 (`curl /ask-deep -d '{"question":"你好"}'`)
- [ ] 复杂查询测试 (ADIZERO 鞋款+科技)
- [ ] 检查日志 `[deep-p1] tool_calls=` 在 3-8 范围
- [ ] 检查日志 `[deep-p2-gathered] len=` < 40000
- [ ] 更新本架构文档 (如果有参数变更)
- [ ] 更新 `~/.hermes/skills/wiki/llm-wiki-deep-search/SKILL.md`

---

> 最后更新: 2026-08-03 | 深度检索 v2.0
