const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Edwin Zhou";
pres.title = "LLM-Wiki 系统架构";

// ── Color Palette (same as deep-search PPT) ──
const C = {
  navy:     "1E2761", ice: "CADCFC", white: "FFFFFF", dark: "1E293B",
  muted:    "64748B", bg:  "F4F6FC", teal: "0D9488", green: "16A34A",
  red:      "DC2626", orange: "EA580C", amber: "D97706",
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
  slide.addText(title, { x: x+0.15, y: y+0.15, w: w-0.3, h: 0.35, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });
  slide.addText(body, { x: x+0.15, y: y+0.52, w: w-0.3, h: h-0.7, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0, valign: "top" });
}
function arrowBox(slide, y, text) {
  slide.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 9, h: 0.45, fill: { color: C.navy } });
  slide.addText(text, { x: 0.7, y, w: 8.6, h: 0.45, fontSize: 11, fontFace: "Arial", color: C.white, align: "center", valign: "middle", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 1: TITLE
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 3.15, w: 10, h: 0.06, fill: { color: C.teal } });
  s.addText("LLM-Wiki 知识库", { x: 0.8, y: 1.35, w: 8.4, h: 0.8, fontSize: 42, fontFace: "Arial Black", color: C.white, margin: 0 });
  s.addText("整体系统架构", { x: 0.8, y: 2.1, w: 8.4, h: 0.7, fontSize: 24, fontFace: "Arial", color: C.ice, margin: 0 });
  s.addText("文件系统 · 上传工作流 · 自检维护 · gbrain 搜索 · 前端图谱", { x: 0.8, y: 3.55, w: 8.4, h: 0.5, fontSize: 13, fontFace: "Arial", color: C.ice, margin: 0 });
  s.addText("Edwin Zhou · 2026-08-03", { x: 0.8, y: 4.55, w: 8.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "8B9DC3", margin: 0 });
}

// ════════════════════════════════════════
// SLIDE 2: 系统总览
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "系统概览"); slideNum(s, 2);

  const rows = [
    ["层级", "组件", "技术"],
    ["前端", "product-hub.html · 3D 图谱 · 问答面板", "D3.js · marked.js · CSS dark theme"],
    ["后端", "server.py (2,580行) · 多线程 HTTP", "Python 3.9 · http.server"],
    ["AI 引擎", "DeepSeek API · 文档处理 · 问答合成", "deepseek-chat · 4-5 次调用/查询"],
    ["向量搜索", "gbrain · 双通道检索", "Bun · PostgreSQL · pgvector"],
    ["存储", "~6,000 Markdown 文件 · 图片索引", "本地文件系统"],
    ["配置", "kb-config.yml · config.py", "YAML · Python SimpleNamespace"],
  ];
  const tableData = rows.map((row, ri) =>
    row.map((cell, ci) => ({
      text: cell,
      options: ri === 0
        ? { bold: true, color: C.white, fill: { color: C.navy }, fontSize: 10 }
        : { fontSize: 10, color: C.dark, fill: { color: ri%2===0 ? C.bg : C.white } }
    }))
  );
  s.addTable(tableData, {
    x: 0.3, y: 1.15, w: 9.4, fontFace: "Arial",
    border: { pt: 0.5, color: "E5E7EB" },
    colW: [1.2, 4.2, 4.0],
    rowH: [0.35, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42],
    autoPage: false,
  });

  arrowBox(s, 4.55, "品牌无关设计 — 修改 kb-config.yml 即可迁移到新品牌");
}

// ════════════════════════════════════════
// SLIDE 3: 目录结构
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "目录结构与文件系统"); slideNum(s, 3);

  const dirs = [
    { label: "运动表现产品/", desc: "品类 #1 — 跑步 · F50 · 训练 · 服装 · 配件", color: "FF6B6B" },
    { label: "三叶草产品/",   desc: "品类 #2 — T头鞋 · 板鞋 · 薄底鞋 · 服装",   color: "FFB347" },
    { label: "轻运动产品/",   desc: "品类 #3 — 跑鞋 · 老爹鞋 · 配件",           color: "4ECDC4" },
    { label: "科技/",         desc: "~75 科技概念页 (boost/lighstrike/...)",    color: "9B59B6" },
    { label: "系列/",         desc: "~800 系列概念页 (adizero/samba/...)",      color: "4A4AFF" },
  ];
  dirs.forEach((d, i) => {
    const y = 1.15 + i * 0.78;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.08, h: 0.6, fill: { color: d.color } });
    s.addText(d.label, { x: 0.75, y: y+0.02, w: 2.5, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: d.color, margin: 0 });
    s.addText(d.desc, { x: 0.75, y: y+0.32, w: 4, h: 0.25, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0 });
  });

  // Right: config files
  s.addText("核心文件", { x: 5.5, y: 1.15, w: 4, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.dark, margin: 0 });
  card(s, 5.5, 1.6, 4.2, 0.6, "server.py", "HTTP 服务 · 上传 · 问答 · 自检", C.navy);
  card(s, 5.5, 2.35, 4.2, 0.6, "regenerate-graph.py", "图谱生成 · 上传处理管道", C.teal);
  card(s, 5.5, 3.1, 4.2, 0.6, "enrich.py", "自检维护 · L1/L2/L3", "2563EB");
  card(s, 5.5, 3.85, 4.2, 0.6, "kb-config.yml", "品牌配置 · 分类体系 · 受控词表", "7C3AED");
  card(s, 5.5, 4.6, 4.2, 0.6, "product-hub.html", "前端界面 · 3D 图谱 · 问答面板", C.orange);
}

// ════════════════════════════════════════
// SLIDE 4: 上传工作流
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "上传文件工作流 — 双模式设计"); slideNum(s, 4);

  // Review mode
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 3.3, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 0.5, fill: { color: C.teal } });
  s.addText("🔍 上传并审核 (review)", { x: 0.5, y: 1.2, w: 4.2, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const rSteps = ["① 文件入队列 (.ingest-queue.json)", "② AI 处理生成内容提案", "③ 提案列表 → 审核界面", "④ 审批通过 → 写入 KB", "⑤ 同步 gbrain + 重建图谱"];
  rSteps.forEach((step, i) => {
    const y = 1.85 + i * 0.48;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.3, h: 0.3, fill: { color: C.teal }, rectRadius: 0.05 });
    s.addText(String(i+1), { x: 0.5, y, w: 0.3, h: 0.3, fontSize: 10, fontFace: "Arial Black", color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(step, { x: 0.95, y, w: 3.8, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.dark, valign: "middle", margin: 0 });
  });

  // Direct mode
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 3.3, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 0.5, fill: { color: C.orange } });
  s.addText("🤖 AI 全自动收录 (direct)", { x: 5.3, y: 1.2, w: 4.2, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const dSteps = ["① 文件入队列", "② AI 直接写入 KB (--yolo)", "③ 自动同步 gbrain", "④ 自动重建图谱", "⑤ 即时可搜索"];
  dSteps.forEach((step, i) => {
    const y = 1.85 + i * 0.48;
    s.addShape(pres.shapes.RECTANGLE, { x: 5.3, y, w: 0.3, h: 0.3, fill: { color: C.orange }, rectRadius: 0.05 });
    s.addText(String(i+1), { x: 5.3, y, w: 0.3, h: 0.3, fontSize: 10, fontFace: "Arial Black", color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(step, { x: 5.75, y, w: 3.8, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.dark, valign: "middle", margin: 0 });
  });

  arrowBox(s, 4.7, "处理管道: gbrain_sync → link_concepts → sync_pages → graph → index → gbrain_sync");
}

// ════════════════════════════════════════
// SLIDE 5: 后端服务端点
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "HTTP 服务端点全览 — :8767"); slideNum(s, 5);

  // Left: public
  s.addText("公开端点", { x: 0.5, y: 1.15, w: 4, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.green, margin: 0 });
  const pub = [
    ["/ask-stream", "POST", "单轮问答 (SSE 流式)"],
    ["/ask-deep", "POST", "深度多轮问答"],
    ["/kb-tree", "GET", "知识库目录树 JSON"],
    ["/api/page", "GET", "获取单页内容"],
    ["/api/search", "GET", "简易搜索"],
  ];
  pub.forEach(([ep, m, desc], i) => {
    const y = 1.6 + i * 0.35;
    s.addText(ep, { x: 0.5, y, w: 1.5, h: 0.3, fontSize: 9, fontFace: "Courier New", color: C.teal, valign: "middle", margin: 0 });
    s.addText(m, { x: 2.1, y, w: 0.7, h: 0.3, fontSize: 9, fontFace: "Arial", color: C.orange, valign: "middle", margin: 0 });
    s.addText(desc, { x: 2.9, y, w: 2.3, h: 0.3, fontSize: 9, fontFace: "Arial", color: C.muted, valign: "middle", margin: 0 });
  });

  // Right: admin (auth required)
  s.addText("管理端点 (需认证)", { x: 5.2, y: 1.15, w: 4, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.red, margin: 0 });
  const adm = [
    ["/upload", "上传文件 (review|direct)"],
    ["/api/proposals/approve", "审批通过提案"],
    ["/api/tasks/run", "运行维护任务"],
    ["/api/run-check", "运行验证"],
    ["/api/save", "保存页面编辑"],
  ];
  adm.forEach(([ep, desc], i) => {
    const y = 1.6 + i * 0.35;
    s.addText(ep, { x: 5.2, y, w: 2.4, h: 0.3, fontSize: 9, fontFace: "Courier New", color: C.red, valign: "middle", margin: 0 });
    s.addText(desc, { x: 7.7, y, w: 2, h: 0.3, fontSize: 9, fontFace: "Arial", color: C.muted, valign: "middle", margin: 0 });
  });

  // Auth box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.5, w: 9.4, h: 1.8, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("🔐 认证机制", { x: 0.5, y: 3.6, w: 3, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });
  const authItems = [
    ["Portal Password Gate", "访问任何页面 → 检查 cookie → 无则登录页"],
    ["Cookie 30 天有效", "登录成功 → 设置 llm_wiki_auth"],
    ["限流保护", "5 次/分钟 per IP → 10 次失败锁 15 分钟"],
    ["READ_ONLY 模式", "公网部署时禁用所有写端点"],
  ];
  authItems.forEach(([t, d], i) => {
    s.addText(t, { x: 0.5, y: 4.0 + i*0.3, w: 2.5, h: 0.25, fontSize: 10, fontFace: "Arial Black", color: C.navy, margin: 0 });
    s.addText(d, { x: 3.1, y: 4.0 + i*0.3, w: 6.4, h: 0.25, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0 });
  });
}

// ════════════════════════════════════════
// SLIDE 6: 自检维护系统
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "自检维护系统 — 三级体系"); slideNum(s, 6);

  const levels = [
    { l: "L1", name: "自动填充", color: C.green,
      desc: "扫描 TODO 标记的产品页\nDeepSeek 生成内容 → 写入\n定时: 每 2 小时 · 每次 20 页",
      cmd: "enrich.py --batch N" },
    { l: "L2", name: "一致性检查", color: C.navy,
      desc: "4 维度扫描:\n① TODO 页面 ② 未关联产品\n③ 孤立标签 ④ 概念↔产品一致\n输出: _meta/_issues.md",
      cmd: "enrich.py --check" },
    { l: "L3", name: "AI 改善", color: "7C3AED",
      desc: "为孤立标签生成概念页提案\n→ 审核界面 → 审批通过 → 写入\n完整闭环",
      cmd: "enrich.py --improve-concepts" },
  ];

  levels.forEach((lv, i) => {
    const x = 0.3 + i * 3.2;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.15, w: 3.0, h: 2.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.15, w: 3.0, h: 0.55, fill: { color: lv.color } });
    s.addText(lv.l + " · " + lv.name, { x, y: 1.2, w: 3.0, h: 0.45, fontSize: 15, fontFace: "Arial Black", color: C.white, align: "center", margin: 0 });
    s.addText(lv.desc, { x: x+0.2, y: 1.85, w: 2.6, h: 1.2, fontSize: 10, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.4 });
    s.addShape(pres.shapes.RECTANGLE, { x: x+0.2, y: 3.15, w: 2.6, h: 0.02, fill: { color: "E5E7EB" } });
    s.addText(lv.cmd, { x: x+0.2, y: 3.25, w: 2.6, h: 0.3, fontSize: 8, fontFace: "Courier New", color: lv.color, margin: 0 });
  });

  // Fix dataview section
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.95, w: 9.4, h: 1.3, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("🔧 dataview → wikilink 同步", { x: 0.5, y: 4.05, w: 4, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });
  s.addText("python3 enrich.py --fix-dataview", { x: 0.5, y: 4.4, w: 4, h: 0.25, fontSize: 9, fontFace: "Courier New", color: C.teal, margin: 0 });
  s.addText("概念页中的 dataview 动态查询→[[wikilink]] 静态列表\n让 gbrain/DeepSeek 可检索概念页中的产品列表", { x: 0.5, y: 4.7, w: 4, h: 0.4, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.3 });

  s.addText("维护任务顺序", { x: 5.5, y: 4.05, w: 4, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });
  s.addText("sync-concepts → improve-concepts\n→ validate → enrich-l1 → enrich-l3\n→ rebuild", { x: 5.5, y: 4.4, w: 4, h: 0.7, fontSize: 9, fontFace: "Courier New", color: C.muted, margin: 0, lineSpacingMultiple: 1.5 });
}

// ════════════════════════════════════════
// SLIDE 7: gbrain 向量搜索
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "gbrain 向量搜索 — 检索引擎"); slideNum(s, 7);

  // Left: architecture
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 2.8, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 0.5, fill: { color: C.navy } });
  s.addText("双通道检索", { x: 0.5, y: 1.2, w: 4.2, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const ch = [
    { label: "通道 1: 关键词", sub: "tsvector 全文搜索", desc: "精确匹配 · 产品名/型号 · 快速", color: "2563EB" },
    { label: "通道 2: 语义", sub: "pgvector 向量搜索", desc: "概念理解 · 自然语言 · 深度", color: C.teal },
  ];
  ch.forEach((c, i) => {
    const y = 1.8 + i * 0.85;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 4.2, h: 0.7, fill: { color: C.white } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 0.06, h: 0.7, fill: { color: c.color } });
    s.addText(c.label, { x: 0.7, y: y+0.05, w: 2, h: 0.25, fontSize: 12, fontFace: "Arial Black", color: c.color, margin: 0 });
    s.addText(c.sub, { x: 2.8, y: y+0.05, w: 1.8, h: 0.25, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0 });
    s.addText(c.desc, { x: 0.7, y: y+0.35, w: 4, h: 0.25, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0 });
  });

  // Multi-keyword query
  s.addText("多渠道查询", { x: 0.5, y: 3.55, w: 4, h: 0.25, fontSize: 12, fontFace: "Arial Black", color: C.dark, margin: 0 });
  s.addText("① 原始问题  ② LLM 改写关键词  ③ jieba 分词  ④ bigram 组合", { x: 0.5, y: 3.8, w: 4.2, h: 0.2, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0 });

  // Right: enhancements
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 2.8, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 0.5, fill: { color: "7C3AED" } });
  s.addText("搜索结果增强", { x: 5.3, y: 1.2, w: 4.2, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  const boosts = [
    ["主页提升", "×1.15", "同目录最短 slug → 产品主页优先"],
    ["实体增强", "×1.2", "\"推荐/有哪些\" → entities/ 优先"],
    ["通用词过滤", "—", "跳过 \"系列/鞋款/推荐\" 噪声词"],
    ["主页提升", "×1.15", "配色变体不淹没技术主页"],
  ];
  boosts.forEach(([n, v, d], i) => {
    const y = 1.85 + i * 0.45;
    s.addText(n, { x: 5.3, y, w: 1.3, h: 0.3, fontSize: 10, fontFace: "Arial Black", color: C.dark, valign: "middle", margin: 0 });
    s.addText(v, { x: 6.7, y, w: 0.8, h: 0.3, fontSize: 12, fontFace: "Arial Black", color: "7C3AED", valign: "middle", margin: 0 });
    s.addText(d, { x: 7.6, y, w: 2, h: 0.3, fontSize: 8, fontFace: "Arial", color: C.muted, valign: "middle", margin: 0 });
  });

  arrowBox(s, 4.2, "gbrain CLI: bun run gbrain.ts search|query|get|import");
}

// ════════════════════════════════════════
// SLIDE 8: 前端架构
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "前端架构 — product-hub.html"); slideNum(s, 8);

  // Layout diagram
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.15, w: 2, h: 3.8, fill: { color: "EEF0F8" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.15, w: 2, h: 0.5, fill: { color: C.navy } });
  s.addText("Sidebar", { x: 0.5, y: 1.2, w: 2, h: 0.4, fontSize: 12, fontFace: "Arial Black", color: C.white, align: "center", margin: 0 });
  const nav = ["📊 图谱", "📋 列表", "💬 问答", "📤 上传", "🔍 自检"];
  nav.forEach((item, i) => {
    s.addText(item, { x: 0.5, y: 1.8 + i*0.42, w: 2, h: 0.3, fontSize: 11, fontFace: "Arial", color: C.ice, align: "center", margin: 0 });
  });
  s.addText("Stats", { x: 0.5, y: 4.3, w: 2, h: 0.3, fontSize: 10, fontFace: "Arial", color: "8B9DC3", align: "center", margin: 0 });

  // Main area
  s.addShape(pres.shapes.RECTANGLE, { x: 2.7, y: 1.15, w: 6.8, h: 3.8, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("主视图区", { x: 2.9, y: 1.25, w: 6.4, h: 0.4, fontSize: 14, fontFace: "Arial Black", color: C.dark, margin: 0 });

  const views = [
    { name: "3D 知识图谱", tech: "D3.js + Three.js 力导向图", desc: "品牌→品类→系列→产品层级\n节点颜色区分品类\n连线 = wikilink 关系", color: C.navy },
    { name: "智能问答面板", tech: "SSE 流式 · 双模式切换", desc: "⚡ 单轮 / 🔍 深度\nMarkdown 渲染 + 图片注入\n步骤可视化", color: C.teal },
    { name: "自检计划面板", tech: "任务调度 · 进度跟踪", desc: "L1/L2/L3 一键触发\n提案审核界面\n结果实时展示", color: "7C3AED" },
  ];
  views.forEach((v, i) => {
    const y = 1.8 + i * 1.05;
    card(s, 2.9, y, 6.4, 0.85, v.name + " · " + v.tech, v.desc, v.color);
  });
}

// ════════════════════════════════════════
// SLIDE 9: 数据流 & 管道
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "数据处理管道"); slideNum(s, 9);

  const pipe = [
    { step: "① 上传", desc: "PDF/DOCX/PPTX\n→ raw/articles/", color: C.navy },
    { step: "② AI 处理", desc: "DeepSeek 文档理解\n→ 提取产品信息", color: "2563EB" },
    { step: "③ 生成页面", desc: "Markdown + frontmatter\n→ 品类目录结构", color: C.teal },
    { step: "④ 链接概念", desc: "wikilink 建立\n产品↔科技↔系列", color: C.green },
    { step: "⑤ 同步概念", desc: "dataview → wikilinks\n概念页可检索", color: "7C3AED" },
    { step: "⑥ 图谱生成", desc: "graph-data.json\n品牌→品类→产品", color: C.orange },
    { step: "⑦ 索引重建", desc: "index.md 更新\ngbrain import", color: C.red },
  ];

  pipe.forEach((p, i) => {
    const x = 0.3 + i * 1.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.4, w: 1.2, h: 2.0, fill: { color: p.color }, shadow: { type: "outer", blur: 2, offset: 1, angle: 135, color: "000000", opacity: 0.1 } });
    s.addText(p.step, { x, y: 1.5, w: 1.2, h: 0.35, fontSize: 12, fontFace: "Arial Black", color: C.white, align: "center", margin: 0 });
    s.addText(p.desc, { x: x+0.08, y: 2.0, w: 1.04, h: 1.2, fontSize: 8, fontFace: "Arial", color: C.ice, align: "center", margin: 0, lineSpacingMultiple: 1.3 });
    if (i < pipe.length - 1) {
      s.addText("→", { x: x+1.2, y: 2.1, w: 0.15, h: 0.4, fontSize: 16, fontFace: "Arial", color: C.muted, align: "center", valign: "middle", margin: 0 });
    }
  });

  // Bottom: config
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.7, w: 9.4, h: 1.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("📋 产品页面结构 (Frontmatter + 正文)", { x: 0.5, y: 3.8, w: 9, h: 0.3, fontSize: 13, fontFace: "Arial Black", color: C.dark, margin: 0 });

  const fm = [
    ["type", "运动表现产品 / 三叶草产品 / ..."],
    ["series", "adizero / ultraboost / samba / ..."],
    ["product_type", "鞋·跑鞋 / 服装·夹克 / ..."],
    ["position", "竞速 / 训练 / 缓震 / 休闲 / 户外"],
    ["attributes", "boost / lightstrike / gore-tex / ..."],
    ["price / tags", "价格 · 标签 · created · updated"],
  ];
  fm.forEach(([k, v], i) => {
    const col = i < 3 ? 0 : 1;
    const row = i < 3 ? i : i-3;
    const x = 0.5 + col * 4.7;
    const y = 4.2 + row * 0.32;
    s.addText(k, { x, y, w: 1.3, h: 0.25, fontSize: 9, fontFace: "Courier New", color: C.teal, margin: 0 });
    s.addText(v, { x: x+1.4, y, w: 2.8, h: 0.25, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0 });
  });
}

// ════════════════════════════════════════
// SLIDE 10: 图片 + 部署
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "图片索引 + 部署架构"); slideNum(s, 10);

  // Image index
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 2.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 1.15, w: 4.6, h: 0.45, fill: { color: C.orange } });
  s.addText("🖼️ 图片索引系统", { x: 0.5, y: 1.2, w: 4.2, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  card(s, 0.5, 1.8, 4.2, 0.7, "启动时构建", "扫描 images/*/manifest.json\n308 产品 · 1080 标签 → 874 链接\n过滤 <15KB 缩略图", C.orange);
  card(s, 0.5, 2.65, 4.2, 0.85, "Q&A 图片注入", "从 seen_slugs 查找关联图片\n去重 · 质量过滤\n注入到答案末尾 (Markdown)", C.orange);

  // Deploy
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 2.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 1.15, w: 4.6, h: 0.45, fill: { color: C.navy } });
  s.addText("🚀 部署架构", { x: 5.3, y: 1.2, w: 4.2, h: 0.35, fontSize: 14, fontFace: "Arial Black", color: C.white, margin: 0 });

  card(s, 5.3, 1.8, 4.2, 0.7, "本地开发", "python3 server.py\n→ localhost:8767", C.navy);
  card(s, 5.3, 2.65, 4.2, 0.85, "公网部署", "cloudflared tunnel\n→ 公网 URL (每次重启变化)\nREAD_ONLY=true 安全模式", C.navy);

  // Bottom: migration
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.95, w: 9.4, h: 1.3, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("🔄 品牌迁移 — 只需改一个文件", { x: 0.5, y: 4.05, w: 9, h: 0.3, fontSize: 14, fontFace: "Arial Black", color: C.green, margin: 0 });
  s.addText("kb-config.yml", { x: 0.5, y: 4.45, w: 2, h: 0.25, fontSize: 11, fontFace: "Courier New", color: C.teal, margin: 0 });
  s.addText("brand.name → 品牌名\ncategories → 品类体系\ntaxonomy.valid_values → 受控词表\ntheme → 颜色主题", { x: 0.5, y: 4.75, w: 3, h: 0.45, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.4 });
  s.addText("所有脚本 (server, enrich, regenerate)\n都从 config.py 读取配置\nconfig.py → kb-config.yml (单源)", { x: 4.5, y: 4.45, w: 5, h: 0.7, fontSize: 9, fontFace: "Arial", color: C.muted, margin: 0, lineSpacingMultiple: 1.4 });
}

// ════════════════════════════════════════
// SLIDE 11: 维护 & 日常
// ════════════════════════════════════════
{
  const s = pres.addSlide(); s.background = { color: C.bg };
  titleBar(s, "日常维护工作流"); slideNum(s, 11);

  card(s, 0.5, 1.15, 4.3, 1.0, "健康检查", "python3 enrich.py --check\ncat _meta/_issues.md", C.green);
  card(s, 5.2, 1.15, 4.5, 1.0, "概念页同步", "python3 enrich.py --fix-dataview\ndataview → [[wikilinks]]", C.teal);
  card(s, 0.5, 2.35, 4.3, 1.0, "重启服务", "lsof -i :8767 -t | xargs kill\nsleep 1 && python3 server.py &", C.orange);
  card(s, 5.2, 2.35, 4.5, 1.0, "语法验证", "python3 -c \"import ast;\nast.parse(open('server.py').read());\nprint('OK')\"", "2563EB");

  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 3.6, w: 9.4, h: 1.6, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 } });
  s.addText("📤 上传后的自动化", { x: 0.5, y: 3.7, w: 9, h: 0.3, fontSize: 14, fontFace: "Arial Black", color: C.dark, margin: 0 });
  const autoSteps = [
    "① gbrain import — 同步新页面到向量库",
    "② AI 文档理解 — DeepSeek 提取产品信息",
    "③ 生成产品页 — Markdown + frontmatter",
    "④ _run_link_concepts — 建立 wikilink 关系",
    "⑤ _sync_concept_pages — enrich.py --fix-dataview",
    "⑥ generate_graph — 重建 graph-data.json",
    "⑦ regenerate_index — 更新 index.md",
    "⑧ gbrain import — 再次同步变更",
  ];
  autoSteps.forEach((step, i) => {
    s.addText(step, { x: 0.5, y: 4.1 + i*0.16, w: 9, h: 0.15, fontSize: 9, fontFace: i<2 ? "Arial Bold" : "Arial", color: i<2 ? C.teal : C.muted, margin: 0 });
  });

  // Page number
  slideNum(s, 11);
}

// ════════════════════════════════════════
// SLIDE 12: THANK YOU
// ════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 2.8, w: 10, h: 0.06, fill: { color: C.teal } });
  s.addText("Thank You", { x: 0.8, y: 1.5, w: 8.4, h: 0.9, fontSize: 48, fontFace: "Arial Black", color: C.white, align: "center", margin: 0 });
  s.addText("LLM-Wiki 知识库 · 整体系统架构", { x: 0.8, y: 3.15, w: 8.4, h: 0.5, fontSize: 18, fontFace: "Arial", color: C.ice, align: "center", margin: 0 });
  s.addText("文档: docs/SYSTEM_ARCHITECTURE.md  ·  docs/ARCHITECTURE.md", { x: 0.8, y: 4.0, w: 8.4, h: 0.4, fontSize: 13, fontFace: "Arial", color: "8B9DC3", align: "center", margin: 0 });
}

// ════════════════════════════════════════
// WRITE
// ════════════════════════════════════════
pres.writeFile({ fileName: "/Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB/docs/LLM-Wiki-系统架构.pptx" })
  .then(() => console.log("OK"))
  .catch(err => console.error(err));
