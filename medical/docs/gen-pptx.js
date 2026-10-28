const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Edwin Zhou";
pres.title = "LLM-Wiki 深度检索架构 v2.0";

// ── Color Palette ──
const C = {
  navy:     "1E2761",
  ice:      "CADCFC",
  white:    "FFFFFF",
  dark:     "1E293B",
  muted:    "64748B",
  bg:       "F4F6FC",
  teal:     "0D9488",
  green:    "16A34A",
  red:      "DC2626",
  orange:   "EA580C",
  amber:    "D97706",
};

// ── Helpers ──
function titleBar(slide, text) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.9, fill: { color: C.navy } });
  slide.addText(text, { x: 0.6, y: 0.12, w: 8.8, h: 0.65, fontSize: 26, fontFace: "Arial Black", color: C.white, margin: 0 });
  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.9, w: 10, h: 0.04, fill: { color: C.teal } });
}

function slideNum(slide, n) {
  slide.addText(String(n), { x: 9.3, y: 5.15, w: 0.5, h: 0.35, fontSize: 10, color: C.muted, align: "right", fontFace: "Arial" });
}

function card(slide, x, y, w, h, title, body, accent) {
  slide.addShape(pres.shapes.RECTANGLE, { x: x, y: y, w: w, h: h, fill: { color: C.white }, shadow: { type: "outer", blur: 4, offset: 1, angle: 135, color: "000000", opacity: 0.08 } });
  slide.addShape(pres.shapes.RECTANGLE, { x: x, y: y, w: w, h: 0.05, fill: { color: accent || C.teal } });
  slide.addText(title, { x: x + 0.15, y: y + 0.15, w: w - 0.3, h: 0.35, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });
  slide.addText(body, { x: x + 0.15, y: y + 0.52, w: w - 0.3, h: h - 0.7, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0, valign: "top" });
}

function iconBadge(slide, x, y, label, color) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: 0.42, h: 0.42, fill: { color } });
  slide.addText(label, { x, y, w: 0.42, h: 0.42, fontSize: 14, fontFace: "Arial Black", color: C.white, align: "center", valign: "middle", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 1: TITLE
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 3.15, w: 10, h: 0.06, fill: { color: C.teal } });
  s.addText("LLM-Wiki 知识库", { x: 0.8, y: 1.35, w: 8.4, h: 0.8, fontSize: 42, fontFace: "Arial Black", color: C.white, margin: 0 });
  s.addText("深度检索架构 v2.0", { x: 0.8, y: 2.1, w: 8.4, h: 0.7, fontSize: 24, fontFace: "Arial", color: C.ice, margin: 0 });
  s.addText("gbrain + DeepSeek · 两阶段 ReAct Agent · 三会话隔离", { x: 0.8, y: 3.55, w: 8.4, h: 0.5, fontSize: 13, fontFace: "Arial", color: C.ice, margin: 0 });
  s.addText("Edwin Zhou · 2026-08-03", { x: 0.8, y: 4.55, w: 8.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "8B9DC3", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 2: 系统概览
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "系统概览");
  slideNum(s, 2);

  // Architecture box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.2, w: 9, h: 2.1, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("架构总览", { x: 0.7, y: 1.3, w: 3, h: 0.35, fontSize: 15, fontFace: "Arial Black", color: C.dark, margin: 0 });

  const boxes = [
    { label: "Markdown 页面\n~6,000 页",   x: 0.7, color: C.navy },
    { label: "gbrain\n向量搜索",            x: 2.9, color: "2563EB" },
    { label: "Q&A 端点\n/ask /ask-stream\n/ask-deep", x: 5.1, color: C.teal },
    { label: "DeepSeek\nAPI",              x: 7.5, color: "7C3AED" },
  ];
  boxes.forEach(b => {
    s.addShape(pres.shapes.RECTANGLE, { x: b.x, y: 1.8, w: 1.9, h: 1.2, fill: { color: b.color } });
    s.addText(b.label, { x: b.x, y: 1.8, w: 1.9, h: 1.2, fontSize: 11, fontFace: "Arial", color: C.white, align: "center", valign: "middle", margin: 0 });
  });
  // Arrows
  for (let ax = 2.65; ax < 7.5; ax += 2.2) {
    s.addText("→", { x: ax, y: 2.15, w: 0.3, h: 0.5, fontSize: 22, fontFace: "Arial", color: C.muted, align: "center", valign: "middle", margin: 0 });
  }

  // Data scale cards
  card(s, 0.5, 3.6, 2.8, 1.3, "📦 数据规模", "产品 ~6,000 | 科技概念 ~75\n系列概念 ~800 | 图片索引 ~308", C.navy);
  card(s, 3.55, 3.6, 2.8, 1.3, "⚡ 推理引擎", "DeepSeek-chat\n双通道搜索 (关键词+语义)\nLLM 改写 + jieba 分词", "2563EB");
  card(s, 6.6, 3.6, 2.8, 1.3, "🔐 三端点", "单轮 /ask-stream (快)\n深度 /ask-deep (全)\n多轮 /ask (Agent)", C.teal);
}

// ════════════════════════════════════════
// SLIDE 3: 三端点对比
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "三端点对比 — 何时用哪个？");
  slideNum(s, 3);

  const cols = [
    { name: "/ask-stream ⚡", sub: "单轮快速",   ac: "2563EB", desc: "gbrain → DeepSeek\n单次搜索 + 概念展开\n2 次 LLM 调用\n~5-8s",    use: "快速问答\n\"什么是 BOOST？\"" },
    { name: "/ask-deep 🔍",   sub: "深度多轮",   ac: C.teal,  desc: "宽搜索 → 缺口分析\n→ 补读 → 纯文本合成\n4-5 次 LLM 调用\n~15-18s", use: "复合问题\n\"有哪些鞋款？各自什么科技？\"" },
    { name: "/ask 🤖",        sub: "Agent 多轮", ac: "7C3AED", desc: "Hermes 子进程\n多轮迭代搜索/读取\n最高质量\n最慢",             use: "深度对比\n全方位分析" },
  ];

  cols.forEach((col, i) => {
    const x = 0.5 + i * 3.15;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.2, w: 2.95, h: 3.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.2, w: 2.95, h: 0.65, fill: { color: col.ac } });
    s.addText(col.name, { x, y: 1.25, w: 2.95, h: 0.35, fontSize: 15, fontFace: "Arial Black", color: C.white, align: "center", margin: 0 });
    s.addText(col.sub, { x, y: 1.55, w: 2.95, h: 0.25, fontSize: 10, fontFace: "Arial", color: C.ice, align: "center", margin: 0 });
    s.addText(col.desc, { x: x + 0.2, y: 2.0, w: 2.55, h: 1.7, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.5 });
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.2, y: 3.85, w: 2.55, h: 0.02, fill: { color: "E5E7EB" } });
    s.addText("适用", { x: x + 0.2, y: 3.95, w: 2.55, h: 0.25, fontSize: 9, fontFace: "Arial Black", color: C.dark, margin: 0 });
    s.addText(col.use, { x: x + 0.2, y: 4.2, w: 2.55, h: 0.45, fontSize: 10, fontFace: "Arial", color: col.ac, margin: 0, lineSpacingMultiple: 1.3 });
  });

  arrowBox(s, 4.95, "选型建议: 简单问题用单轮⚡  科技深度问题用深度🔍  全方位对比用Agent🤖");
}

function arrowBox(slide, y, text) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 9, h: 0.55, fill: { color: C.navy } });
  slide.addText(text, { x: 0.7, y, w: 8.6, h: 0.55, fontSize: 11, fontFace: "Arial", color: C.white, align: "center", valign: "middle", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 4: 深度检索完整流程
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "深度检索完整流程 — 五阶段");
  slideNum(s, 4);

  const phases = [
    { id: "0", name: "宽基础搜索",   detail: "gbrain_search(20)\n读 10 页全文\n系列注入 + 概念展开",    dur: "0.5-2s",  color: C.navy },
    { id: "1", name: "缺口分析",     detail: "仅 kb_get_page\n最多 3-5 次\nmax_tokens=8000",        dur: "5-10s",  color: "2563EB" },
    { id: "2a", name: "补充读取",    detail: "全新对话 #2\n40K 上限\n初始上下文完整",                  dur: "3-5s",   color: C.teal },
    { id: "2b", name: "纯文本合成",  detail: "全新对话 #3\n零工具历史\n逐行过滤 XML",                  dur: "5-8s",   color: "7C3AED" },
    { id: "→",  name: "后处理",     detail: "图片注入\nSlug 链接化\nSSE 流式输出",                     dur: "0.2s",  color: C.orange },
  ];

  phases.forEach((p, i) => {
    const y = 1.2 + i * 0.82;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.55, h: 0.65, fill: { color: p.color } });
    s.addText(p.id, { x: 0.5, y, w: 0.55, h: 0.65, fontSize: 18, fontFace: "Arial Black", color: C.white, align: "center", valign: "middle", margin: 0 });

    s.addText(p.name, { x: 1.2, y: y + 0.02, w: 1.8, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: p.color, margin: 0 });
    s.addText(p.detail, { x: 1.2, y: y + 0.32, w: 4.5, h: 0.35, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.2 });

    s.addText(p.dur, { x: 7.2, y, w: 1.2, h: 0.65, fontSize: 10, fontFace: "Arial", color: C.muted, align: "right", valign: "middle", margin: 0 });

    if (i < phases.length - 1) {
      s.addText("▼", { x: 0.6, y: y + 0.62, w: 0.35, h: 0.22, fontSize: 12, fontFace: "Arial", color: C.muted, align: "center", margin: 0 });
    }
  });

  s.addText("总计: ~15-18s (含 4-5 次 LLM 调用)", { x: 0.5, y: 5.32, w: 9, h: 0.3, fontSize: 11, fontFace: "Arial Bold", color: C.navy, align: "right", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 5: Phase 0 + Phase 1 详解
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "Phase 0 宽搜索 + Phase 1 缺口分析");
  slideNum(s, 5);

  // Left: Phase 0
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 3.85, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 0.55, fill: { color: C.navy } });
  s.addText("Phase 0 · 宽基础搜索", { x: 0.5, y: 1.22, w: 4.2, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const p0items = [
    "① gbrain_search(limit=20) — 2× 单轮的 10",
    "② 双通道: 关键词 (tsvector) + 语义 (pgvector)",
    "③ 多渠道: 原问题 + LLM改写 + jieba分词",
    "④ 读前 10 页全文 (单轮只读 6 页)",
    "⑤ 系列概览页注入 (regex 匹配)",
    "⑥ 概念链接展开 (max 8) + 科技自动注入 (max 6)",
    "",
    "输出: context · 20-30K 字符 · 永不截断",
  ];
  p0items.forEach((item, i) => {
    s.addText(item, { x: 0.5, y: 1.85 + i * 0.3, w: 4.2, h: 0.27, fontSize: 9, fontFace: "Arial", color: item.startsWith("输出") ? C.teal : C.muted, margin: 0, bold: item.startsWith("输出") });
  });

  // Right: Phase 1
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 3.85, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 0.55, fill: { color: "2563EB" } });
  s.addText("Phase 1 · 缺口分析 (会话 #1)", { x: 5.3, y: 1.22, w: 4.2, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const p1items = [
    "工具: 仅 kb_get_page (无 kb_search！)",
    "  初始搜索已全面，不需要重新搜索",
    "",
    "模型任务:",
    "  \"快速浏览初始上下文\"",
    "  \"只在科技信息完全空白时才读取\"",
    "  \"最多 3-5 个页面\"",
    "",
    "安全: 硬上限 8 次 · json.loads 防崩溃",
    "max_tokens: 8000 · temperature: 0.5",
    "每个结果: body[:6000]",
  ];
  p1items.forEach((item, i) => {
    s.addText(item, { x: 5.3, y: 1.85 + i * 0.3, w: 4.2, h: 0.27, fontSize: 9, fontFace: "Arial", color: item.startsWith("工具") || item.startsWith("安全") ? C.teal : (item.startsWith("  ") ? C.muted : C.dark), margin: 0, bold: item.startsWith("工具") || item.startsWith("安全") });
  });

  arrowBox(s, 5.25, "设计哲学: 宽基础 + 缺口分析 → 不是 \"更多搜索\"，而是 \"更聪明地读\"");
}

// ════════════════════════════════════════
// SLIDE 6: Phase 2 + 三会话隔离
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "Phase 2 + 三会话隔离原理");
  slideNum(s, 6);

  // Phase 2a/b
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 2.45, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 0.45, fill: { color: C.teal } });
  s.addText("Phase 2a · 补充读取 (会话 #2)", { x: 0.5, y: 1.2, w: 4.2, h: 0.35, fontSize: 13, fontFace: "Arial Black", color: C.white, margin: 0 });

  card(s, 0.5, 1.8, 4.2, 0.8, "gathered 构建", "= 完整初始 context (永不截断)\n+ Phase 1 kb_get_page 结果 (跳过冗余搜索)", C.teal);
  card(s, 0.5, 2.8, 4.2, 0.65, "执行", "kb_get_page 补读 + 第二轮检查遗漏\nmax_tokens: 3000 · 上限 40K chars", C.teal);

  // 2b
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 2.45, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 0.45, fill: { color: "7C3AED" } });
  s.addText("Phase 2b · 纯文本合成 (会话 #3)", { x: 5.3, y: 1.2, w: 4.2, h: 0.35, fontSize: 13, fontFace: "Arial Black", color: C.white, margin: 0 });

  card(s, 5.3, 1.8, 4.2, 1.6, "核心设计", "⚠️ 全新对话 · 零 function calling 历史\n防止 DeepSeek 幻觉 <invoke> XML 标签\nmax_tokens: 2500 · 逐行过滤残留标签\n图片注入 + Slug 链接化 → 流式输出", "7C3AED");

  // Three-session isolation diagram
  arrowBox(s, 3.85, "");
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.9, w: 9.4, h: 1.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("⚡ 三会话隔离 — 唯一可靠的 XML 幻觉防御", { x: 0.5, y: 3.98, w: 9, h: 0.35, fontSize: 13, fontFace: "Arial Black", color: C.red, margin: 0 });

  const sessions = [
    { label: "会话 #1\nPhase 1",           color: "2563EB" },
    { label: "会话 #2\nPhase 2a/2a.5",    color: C.teal },
    { label: "会话 #3\nPhase 2b",          color: C.green },
  ];
  sessions.forEach((sess, i) => {
    const sx = 1.0 + i * 3.0;
    s.addShape(pres.shapes.RECTANGLE, { x: sx, y: 4.4, w: 2.5, h: 0.8, fill: { color: sess.color } });
    s.addText(sess.label, { x: sx, y: 4.4, w: 2.5, h: 0.5, fontSize: 12, fontFace: "Arial Black", color: C.white, align: "center", valign: "middle", margin: 0 });
    if (i < 2) {
      s.addText("✗ 不共享", { x: sx + 2.5, y: 4.55, w: 0.5, h: 0.4, fontSize: 8, fontFace: "Arial", color: C.red, align: "center", margin: 0 });
    }
  });
  s.addText("如果共享历史 → 即使禁用工具，DeepSeek 也会模仿输出 <invoke> XML 标签", { x: 0.5, y: 5.25, w: 9, h: 0.3, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 7: v1 → v2 优化历程
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "v1 → v2 优化历程");
  slideNum(s, 7);

  // v1 problem
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 2.3, fill: { color: "FEF2F2" }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 0.45, fill: { color: C.red } });
  s.addText("v1 的问题", { x: 0.5, y: 1.2, w: 4.2, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const v1items = [
    "① 初始搜索与单轮相同 (limit=10)",
    "   没有\"深度\"优势",
    "② kb_search 返回 300 字符摘要",
    "   远低于初始上下文的 10K 全文",
    "③ gathered 截断丢失初始页面",
    "   最终上下文不如单轮",
    "④ 冗余搜索 → 延迟 ×3",
    "   答案质量可能更差",
  ];
  v1items.forEach((item, i) => {
    s.addText(item, { x: 0.5, y: 1.75 + i * 0.26, w: 4.2, h: 0.24, fontSize: 9, fontFace: "Arial", color: item.startsWith("①") || item.startsWith("②") || item.startsWith("③") || item.startsWith("④") ? C.dark : C.muted, margin: 0 });
  });

  // v2 fixes
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 2.3, fill: { color: "F0FDF4" }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 0.45, fill: { color: C.green } });
  s.addText("v2 的修复", { x: 5.3, y: 1.2, w: 4.2, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const v2items = [
    "① 宽初始搜索 limit=20, 读10页",
    "   给 Phase 1 更丰富的素材",
    "② 去掉 kb_search, 仅 kb_get_page",
    "   不重新搜索, 针对性补读",
    "③ context 为基础, 跳过冗余结果",
    "   初始高质量页面永不丢失",
    "④ 上限 40K (原 30K), 优先级截断",
    "   context 始终完整保留在最前面",
  ];
  v2items.forEach((item, i) => {
    s.addText(item, { x: 5.3, y: 1.75 + i * 0.26, w: 4.2, h: 0.24, fontSize: 9, fontFace: "Arial", color: item.startsWith("①") || item.startsWith("②") || item.startsWith("③") || item.startsWith("④") ? C.dark : C.muted, margin: 0 });
  });

  // Parameter table
  s.addText("参数变更对照", { x: 0.3, y: 3.7, w: 3, h: 0.35, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });

  const tableRows = [
    [{ text: "参数", options: { bold: true, color: C.white, fill: { color: C.navy } } },
     { text: "v1", options: { bold: true, color: C.white, fill: { color: C.navy } } },
     { text: "v2", options: { bold: true, color: C.white, fill: { color: C.navy } } },
     { text: "原理", options: { bold: true, color: C.white, fill: { color: C.navy } } }],
    ["初始搜索",   "10 (6页)",   "20 (10页)",  "2× 广度"],
    ["Phase 1 工具","kb_search+\nkb_get_page","仅 kb_get_page","缺口分析"],
    ["Phase 1 tokens","2500",    "8000",        "防 JSON 截断"],
    ["调用上限",   "无",          "8 次",        "防失控"],
    ["gathered 上限","30K",      "40K",         "优先级截断"],
    ["Phase 2a tokens","2000",   "3000",        "分析空间"],
  ];

  s.addTable(tableRows, {
    x: 0.3, y: 4.1, w: 9.4,
    fontSize: 9, fontFace: "Arial", color: C.dark,
    border: { pt: 0.5, color: "E5E7EB" },
    colW: [1.8, 1.8, 1.8, 2.2],
    rowH: [0.32, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3],
    autoPage: false,
  });
}

// ════════════════════════════════════════
// SLIDE 8: 实测对比
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "实测对比 — ADIZERO 鞋款 × 科技查询");
  slideNum(s, 8);

  // Before
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 2.5, fill: { color: "FEF2F2" }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 0.09, h: 2.5, fill: { color: C.red } });
  s.addText("v1 · 优化前", { x: 0.55, y: 1.25, w: 4, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.red, margin: 0 });

  const beforeStats = [
    ["Phase 1 调用", "12-20 次 (过度)"],
    ["gathered 大小", "30K+ (触发截断)"],
    ["答案完整性", "部分鞋款缺科技"],
    ["错误率", "20 次调用时 JSON 崩溃"],
    ["答案长度", "不确定"],
  ];
  beforeStats.forEach(([l, v], i) => {
    s.addText(l, { x: 0.55, y: 1.75 + i * 0.38, w: 1.5, h: 0.28, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0 });
    s.addText(v, { x: 2.1, y: 1.75 + i * 0.38, w: 2.6, h: 0.28, fontSize: 10, fontFace: "Arial Bold", color: C.red, margin: 0 });
  });

  // After
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 2.5, fill: { color: "F0FDF4" }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 0.09, h: 2.5, fill: { color: C.green } });
  s.addText("v2 · 优化后", { x: 5.35, y: 1.25, w: 4, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.green, margin: 0 });

  const afterStats = [
    ["Phase 1 调用", "4-5 次 (适度)"],
    ["gathered 大小", "~19K (远低于上限)"],
    ["答案完整性", "17 款鞋 · 完整科技表格"],
    ["错误率", "零错误"],
    ["答案长度", "1,774 字符"],
  ];
  afterStats.forEach(([l, v], i) => {
    s.addText(l, { x: 5.35, y: 1.75 + i * 0.38, w: 1.5, h: 0.28, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0 });
    s.addText(v, { x: 6.9, y: 1.75 + i * 0.38, w: 2.6, h: 0.28, fontSize: 10, fontFace: "Arial Bold", color: C.green, margin: 0 });
  });

  // Big stat callouts
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 3.95, w: 2.8, h: 1.2, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("20 → 5", { x: 0.5, y: 4.05, w: 2.8, h: 0.55, fontSize: 32, fontFace: "Arial Black", color: C.green, align: "center", margin: 0 });
  s.addText("工具调用次数", { x: 0.5, y: 4.6, w: 2.8, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.muted, align: "center", margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, { x: 3.6, y: 3.95, w: 2.8, h: 1.2, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("0", { x: 3.6, y: 4.05, w: 2.8, h: 0.55, fontSize: 32, fontFace: "Arial Black", color: C.teal, align: "center", margin: 0 });
  s.addText("崩溃次数", { x: 3.6, y: 4.6, w: 2.8, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.muted, align: "center", margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, { x: 6.7, y: 3.95, w: 2.8, h: 1.2, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("17", { x: 6.7, y: 4.05, w: 2.8, h: 0.55, fontSize: 32, fontFace: "Arial Black", color: C.navy, align: "center", margin: 0 });
  s.addText("覆盖鞋款数", { x: 6.7, y: 4.6, w: 2.8, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.muted, align: "center", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 9: 关键参数表
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "关键参数表");
  slideNum(s, 9);

  const params = [
    ["参数", "值", "位置", "调整依据"],
    ["初始搜索 limit", "20", "handle_ask_deep", "2× 单轮宽度"],
    ["初始全文读取", "10 页", "len(context_parts)<10", "覆盖结果前 50%"],
    ["Phase 1 max_tokens", "8000", "requests.post", "每个调用 ~200 字符 × 8 + 分析"],
    ["Phase 1 调用上限", "8 次", "msg['tool_calls'][:8]", "prompt 限制 3-5, 硬上限 8"],
    ["Phase 1 单结果上限", "6000 字符", "body[:6000]", "产品页 ~400-1000"],
    ["Phase 2a max_tokens", "3000", "Phase 2a POST", "补读 + 分析空间"],
    ["Phase 2b max_tokens", "2500", "Phase 2b POST", "纯文本合成"],
    ["gathered 总上限", "40K chars", "gathered[:40000]", "25K 初始 + 5×3K 工具"],
    ["概念链接展开", "max 8", "expand_concept_links", "覆盖相关科技"],
    ["科技自动注入", "max 6", "tech_slugs[:6]", "科技页可达 10K+"],
    ["temperature", "0.5", "全局", "平衡创造性和稳定性"],
  ];

  const rowOpts = (i) => i === 0
    ? { bold: true, color: C.white, fill: { color: C.navy }, fontSize: 9 }
    : { fontSize: 9, color: C.dark, fill: { color: i % 2 === 0 ? C.bg : C.white } };

  const tableData = params.map((row, ri) =>
    row.map((cell) => ({ text: cell, options: rowOpts(ri) }))
  );

  s.addTable(tableData, {
    x: 0.3, y: 1.15, w: 9.4,
    fontFace: "Arial",
    border: { pt: 0.5, color: "E5E7EB" },
    colW: [2.2, 1.3, 2.5, 3.4],
    rowH: [0.32, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3],
    autoPage: false,
  });
}

// ════════════════════════════════════════
// SLIDE 10: 上下文优先级策略
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "上下文优先级策略 — gathered 构建规则");
  slideNum(s, 10);

  const tiers = [
    { p: "P1 永不截断", color: C.navy,  items: ["初始 context (10 页 + 系列/科技概念)", "gbrain 搜索的最相关结果", "占据 gathered 前 15-25K 字符"] },
    { p: "P2 追加",     color: C.teal,  items: ["Phase 1 kb_get_page 结果", "模型明确请求的页面", "每个结果上限 8K 字符"] },
    { p: "P3 跳过",     color: C.muted, items: ["Phase 1 kb_search 结果", "与初始 context 高度冗余", "同一个 gbrain_search 数据源 → 直接跳过"] },
  ];

  tiers.forEach((tier, i) => {
    const y = 1.2 + i * 1.35;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 9, h: 1.1, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.08, h: 1.1, fill: { color: tier.color } });
    s.addText(tier.p, { x: 0.75, y: y + 0.08, w: 2, h: 0.3, fontSize: 14, fontFace: "Arial Black", color: tier.color, margin: 0 });
    tier.items.forEach((item, j) => {
      s.addText("• " + item, { x: 0.75, y: y + 0.42 + j * 0.22, w: 8.5, h: 0.2, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0 });
    });
  });

  arrowBox(s, 5.25, "总上限: 40K · 如果超过 → 末尾截断 · 初始 context 在最前面始终完整");
}

// ════════════════════════════════════════
// SLIDE 11: 陷阱与修复
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "已知陷阱与修复");
  slideNum(s, 11);

  const pitfalls = [
    { title: "XML 幻觉", sev: "P0", color: C.red,
      sym: "答案出现 <invoke> XML 标签", cause: "Phase 2b 共享了 function calling 历史",
      fix: "三会话隔离 · 逐行过滤残留标签" },
    { title: "工具调用失控", sev: "P0", color: C.red,
      sym: "❌ Unterminated string 崩溃", cause: "20 调用 × ~200 字符 → max_tokens 截断 JSON",
      fix: "硬上限 8 次 · try/except · max_tokens=8000" },
    { title: "上下文稀释", sev: "P0", color: C.orange,
      sym: "深度答案不如单轮", cause: "300 字摘要替换了 10K 全文",
      fix: "跳过 kb_search 结果 · context 为基础" },
    { title: "503 请求过大", sev: "P1", color: C.amber,
      sym: "resp.status_code==503", cause: "请求体 >~50K 字符",
      fix: "gathered 上限 40K · 优先级截断" },
  ];

  pitfalls.forEach((p, i) => {
    const y = 1.2 + i * 1.05;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y, w: 9.4, h: 0.9, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y, w: 0.08, h: 0.9, fill: { color: p.color } });

    s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: y + 0.1, w: 0.45, h: 0.26, fill: { color: p.color } });
    s.addText(p.sev, { x: 0.55, y: y + 0.1, w: 0.45, h: 0.26, fontSize: 9, fontFace: "Arial Black", color: C.white, align: "center", valign: "middle", margin: 0 });

    s.addText(p.title, { x: 1.15, y: y + 0.08, w: 2.5, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: p.color, margin: 0 });
    s.addText("症状: " + p.sym, { x: 1.15, y: y + 0.38, w: 3.5, h: 0.32, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.1 });
    s.addText("原因: " + p.cause, { x: 4.7, y: y + 0.38, w: 2.3, h: 0.32, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.1 });
    s.addText("修复: " + p.fix, { x: 7.1, y: y + 0.38, w: 2.5, h: 0.32, fontSize: 9, fontFace: "Arial", color: C.teal, margin: 0, lineSpacingMultiple: 1.1 });
  });
}

// ════════════════════════════════════════
// SLIDE 12: 调试 + 维护
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  titleBar(s, "调试方法 + 维护工作流");
  slideNum(s, 12);

  // Left: Debug logs
  s.addText("🔧 关键日志行", { x: 0.5, y: 1.15, w: 4.5, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.dark, margin: 0 });
  const logLines = [
    "[deep-p1] finish=tool_calls, tool_calls=5",
    "[deep-p2-gathered] len=19155",
    "[deep-p2] content_len=1774",
    "[deep-search] slugs=31, images=3",
  ];
  logLines.forEach((l, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.6 + i * 0.38, w: 4.3, h: 0.3, fill: { color: C.navy } });
    s.addText(l, { x: 0.6, y: 1.6 + i * 0.38, w: 4.1, h: 0.3, fontSize: 8, fontFace: "Courier New", color: C.ice, valign: "middle", margin: 0 });
  });

  // Right: Health checks
  s.addText("🏥 健康检查", { x: 5.2, y: 1.15, w: 4.5, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.dark, margin: 0 });
  card(s, 5.2, 1.6, 4.5, 1.35, "curl 测试", "curl -X POST :8767/ask-deep\n  -d '{\"question\":\"你好\"}' --max-time 30", C.teal);
  card(s, 5.2, 3.1, 4.5, 0.9, "语法验证", "python3 -c \"import ast;\n  ast.parse(open('server.py').read());\n  print('OK')\"", "2563EB");

  // Bottom: Maintenance
  s.addText("🔄 日常维护", { x: 0.5, y: 4.2, w: 4.5, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.dark, margin: 0 });
  card(s, 0.5, 4.6, 4.3, 0.8, "一致性检查 + 概念页同步", "python3 enrich.py --check\npython3 enrich.py --fix-dataview", C.navy);
  card(s, 5.2, 4.2, 4.5, 1.2, "重启服务", "lsof -i :8767 -t | xargs kill\nsleep 1\npython3 server.py &", C.orange);
}

// ════════════════════════════════════════
// SLIDE 13: THANK YOU
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.8, w: 10, h: 0.06, fill: { color: C.teal } });

  s.addText("Thank You", { x: 0.8, y: 1.5, w: 8.4, h: 0.9, fontSize: 48, fontFace: "Arial Black", color: C.white, align: "center", margin: 0 });
  s.addText("LLM-Wiki 深度检索架构 v2.0", { x: 0.8, y: 3.15, w: 8.4, h: 0.5, fontSize: 18, fontFace: "Arial", color: C.ice, align: "center", margin: 0 });
  s.addText("gbrain + DeepSeek · ReAct Agent · Three-Session Isolation", { x: 0.8, y: 4.0, w: 8.4, h: 0.4, fontSize: 13, fontFace: "Arial", color: "8B9DC3", align: "center", margin: 0 });
}

// ════════════════════════════════════════
// WRITE
// ════════════════════════════════════════
pres.writeFile({ fileName: "/Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB/docs/LLM-Wiki-深度检索架构-v2.pptx" })
  .then(() => console.log("OK"))
  .catch(err => console.error(err));
