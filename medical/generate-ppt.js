const pptxgen = require("pptxgenjs");
const pres = new pptxgen();

pres.layout = "LAYOUT_16x9";
pres.author = cfg.brand.display_name;
pres.title = cfg.brand.display_name;

// === COLOR PALETTE (dark space theme) ===
const C = {
  bgDark:      "0A0A14",
  bgPanel:     "111122",
  bgCard:      "1A1A3A",
  accent:      "4A4AFF",
  accentPink:  "FF6B6B",
  accentOrange:"FFB347",
  accentTeal:  "4ECDC4",
  accentGreen: "6BCB77",
  accentPurple:"9B59B6",
  textPrimary: "E0E0E0",
  textSecondary: "8899AA",
  textMuted:   "556677",
  white:       "FFFFFF",
  darkLine:    "1E1E3A",
};

const FONT = "Calibri";
const FONT_CN = "Microsoft YaHei";

// Helper: create card with left accent bar
function addCard(slide, x, y, w, h, accentColor, title, body, iconEmoji) {
  // Card background
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: C.bgCard },
    shadow: { type: "outer", color: "000000", blur: 8, offset: 2, angle: 135, opacity: 0.3 },
  });
  // Left accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w: 0.06, h,
    fill: { color: accentColor },
  });
  // Icon
  if (iconEmoji) {
    slide.addText(iconEmoji, {
      x: x + 0.3, y: y + 0.2, w: 0.5, h: 0.5,
      fontSize: 22, align: "center", valign: "middle",
    });
  }
  // Title
  slide.addText(title, {
    x: x + 0.3, y: y + 0.65, w: w - 0.6, h: 0.45,
    fontSize: 15, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });
  // Body
  slide.addText(body, {
    x: x + 0.3, y: y + 1.1, w: w - 0.6, h: h - 1.4,
    fontSize: 11, color: C.textSecondary, fontFace: FONT_CN,
    lineSpacingMultiple: 1.4, margin: 0,
  });
}

// Helper: add page number
function addPageNum(slide, num, total) {
  slide.addText(`${num} / ${total}`, {
    x: 8.8, y: 5.2, w: 1, h: 0.3,
    fontSize: 9, color: C.textMuted, fontFace: FONT,
    align: "right",
  });
}

const TOTAL = 13;

// ================================================================
// SLIDE 1: TITLE
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };

  // Decorative stars (small dots)
  const stars = [[1.5,1.2],[7.2,0.8],[3.1,2.8],[8.7,2.1],[6.0,3.5],[2.3,4.1],[0.8,3.2],[9.0,4.0],[4.6,4.5],[7.8,4.8]];
  stars.forEach(([x, y]) => {
    s.addShape(pres.shapes.OVAL, {
      x, y, w: 0.04, h: 0.04,
      fill: { color: C.white, transparency: 70 },
    });
  });

  // Top accent line
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.3, w: 1.5, h: 0.04,
    fill: { color: C.accent },
  });

  // Title
  s.addText(cfg.brand.name, {
    x: 0.8, y: 1.6, w: 8, h: 1.0,
    fontSize: 52, bold: true, color: C.white, fontFace: FONT,
    margin: 0,
  });
  s.addText("Product Knowledge Brain", {
    x: 0.8, y: 2.45, w: 8, h: 0.7,
    fontSize: 28, color: C.accent, fontFace: FONT_CN,
    margin: 0,
  });

  // Subtitle
  s.addText("AI 驱动的产品知识中枢", {
    x: 0.8, y: 3.3, w: 8, h: 0.5,
    fontSize: 16, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  // Bottom stats bar
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 4.4, w: 8.4, h: 0.04,
    fill: { color: C.darkLine },
  });
  const stats = ["305 产品节点", "709 知识连线", "5 大品类", "AI 语义问答"];
  stats.forEach((stat, i) => {
    s.addText(stat, {
      x: 0.8 + i * 2.1, y: 4.55, w: 1.9, h: 0.4,
      fontSize: 12, color: C.textMuted, fontFace: FONT_CN,
      align: i === 0 ? "left" : "center",
    });
  });

  addPageNum(s, 1, TOTAL);
}

// ================================================================
// SLIDE 2: PAIN POINTS
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  // Header
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("零售培训的三大瓶颈", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 30, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });

  const cards = [
    { icon: "📂", title: "信息分散", body: "培训材料散落在邮件、共享盘、课件里。销售想找一个产品信息，不知道去哪翻。", color: C.accentPink },
    { icon: "🐌", title: "更新滞后", body: "新品上市几周后，培训材料才能传到一线店员手里。竞品信息已经过时了。", color: C.accentOrange },
    { icon: "🔍", title: "查询低效", body: "\"这双鞋适合跑全马吗？\"——翻 50 页 PDF 才能回答一个简单问题。", color: C.accentTeal },
  ];

  cards.forEach((card, i) => {
    addCard(s, 0.8 + i * 3.0, 1.5, 2.6, 3.2, card.color, card.title, card.body, card.icon);
  });

  // Bottom insight
  s.addText("信息都在那里，但是找不着、找不到、找不准。", {
    x: 0.8, y: 5.0, w: 8.4, h: 0.4,
    fontSize: 13, italic: true, color: C.textMuted, fontFace: FONT_CN,
    align: "center",
  });

  addPageNum(s, 2, TOTAL);
}

// ================================================================
// SLIDE 3: SOLUTION OVERVIEW
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("一个系统，三个能力", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 30, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });

  const cards = [
    {
      icon: "🔍", title: "搜得到", subtitle: "语义搜索",
      body: "双通道混合检索：关键词全文 + 语义向量并行搜索，同一页面取最高分合并排序。不是关键词匹配。",
      color: C.accentTeal,
    },
    {
      icon: "📊", title: "看得见", subtitle: "知识图谱",
      body: "305 个产品节点，709 条知识连线。一张图看清产品之间的科技、场景、系列关系。",
      color: C.accent,
    },
    {
      icon: "🤖", title: "问得着", subtitle: "AI 问答",
      body: "像问同事一样问系统。AI 基于知识库回答，每条都有出处，5-10 秒出结果。",
      color: C.accentGreen,
    },
  ];

  cards.forEach((card, i) => {
    const x = 0.8 + i * 3.0;
    const y = 1.5;
    const w = 2.6;
    const h = 3.0;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.bgCard },
      shadow: { type: "outer", color: "000000", blur: 8, offset: 2, angle: 135, opacity: 0.3 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: 0.06,
      fill: { color: card.color },
    });
    s.addText(card.icon, {
      x: x + 0.5, y: y + 0.2, w: w - 1.0, h: 0.6,
      fontSize: 36, align: "center",
    });
    s.addText(card.title, {
      x: x + 0.3, y: y + 0.85, w: w - 0.6, h: 0.45,
      fontSize: 22, bold: true, color: C.textPrimary, fontFace: FONT_CN,
      align: "center", margin: 0,
    });
    s.addText(card.subtitle, {
      x: x + 0.3, y: y + 1.25, w: w - 0.6, h: 0.35,
      fontSize: 12, color: card.color, fontFace: FONT_CN,
      align: "center", margin: 0,
    });
    s.addText(card.body, {
      x: x + 0.3, y: y + 1.75, w: w - 0.6, h: 1.0,
      fontSize: 11, color: C.textSecondary, fontFace: FONT_CN,
      lineSpacingMultiple: 1.5, align: "center", margin: 0,
    });
  });

  addPageNum(s, 3, TOTAL);
}

// ================================================================
// SLIDE 4: KNOWLEDGE SYSTEM
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("5 维度 × 5 品类", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 30, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("每个产品都有完整画像", {
    x: 0.8, y: 0.9, w: 8, h: 0.4,
    fontSize: 14, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  // Left: taxonomy table
  const taxRows = [
    ["品类", "跑步 · 三叶草 · 轻运动 · 童装 · TERREX"],
    ["系列", "ADIZERO · SUPERNOVA · CAMPUS · SPORTSWEAR…"],
    ["类型", "跑鞋 · 夹克 · T恤 · 板鞋 · 长裤…"],
    ["定位", "入门 → 中端 → 中高端 → 高端 → 旗舰"],
    ["特性", "碳板 · BOOST · GORE-TEX · 新中式…"],
  ];

  // Table header
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.5, w: 5.2, h: 0.45,
    fill: { color: C.accent },
  });
  s.addText("5 维度分类体系", {
    x: 1.0, y: 1.5, w: 4.8, h: 0.45,
    fontSize: 13, bold: true, color: C.white, fontFace: FONT_CN,
    valign: "middle", margin: 0,
  });

  taxRows.forEach((row, i) => {
    const y = 2.02 + i * 0.45;
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.8, y, w: 5.2, h: 0.42,
      fill: { color: i % 2 === 0 ? C.bgCard : C.bgPanel },
    });
    s.addText(row[0], {
      x: 1.0, y, w: 1.0, h: 0.42,
      fontSize: 12, bold: true, color: C.accent, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
    s.addText(row[1], {
      x: 2.1, y, w: 3.7, h: 0.42,
      fontSize: 11, color: C.textSecondary, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
  });

  // Right: big stats
  s.addText("知识库规模", {
    x: 6.5, y: 1.5, w: 3.0, h: 0.45,
    fontSize: 13, bold: true, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  const bigStats = [
    { num: "305", label: "产品节点", color: C.accentPink },
    { num: "53", label: "概念节点", color: C.accentPurple },
    { num: "952", label: "知识连线", color: C.accentTeal },
  ];

  bigStats.forEach((stat, i) => {
    const y = 2.1 + i * 1.05;
    s.addText(stat.num, {
      x: 6.5, y, w: 2.5, h: 0.6,
      fontSize: 38, bold: true, color: stat.color, fontFace: FONT,
      margin: 0,
    });
    s.addText(stat.label, {
      x: 6.5, y: y + 0.55, w: 2.5, h: 0.35,
      fontSize: 12, color: C.textMuted, fontFace: FONT_CN,
      margin: 0,
    });
  });

  addPageNum(s, 4, TOTAL);
}

// ================================================================
// SLIDE 5: GRAPH DEMO (CORE)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("一张图看懂 " + cfg.brand.display_name + " 产品宇宙", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 30, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });

  // Simulated graph area
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.4, w: 5.4, h: 3.8,
    fill: { color: "06060F" },
  });

  // Decorative "starfield" dots in graph
  const dots = [];
  for (let i = 0; i < 40; i++) {
    dots.push([Math.random() * 5.0 + 1.0, Math.random() * 3.4 + 1.6]);
  }
  dots.forEach(([dx, dy]) => {
    s.addShape(pres.shapes.OVAL, {
      x: dx, y: dy, w: 0.03, h: 0.03,
      fill: { color: C.white, transparency: 40 + Math.random() * 50 },
    });
  });

  // Simulated node clusters
  const clusters = [
    { color: C.accentPink, cx: 1.8, cy: 2.4, count: 8, label: "跑步" },
    { color: C.accentOrange, cx: 3.3, cy: 2.0, count: 6, label: "三叶草" },
    { color: C.accentTeal, cx: 2.2, cy: 3.8, count: 10, label: "轻运动" },
    { color: C.accentGreen, cx: 4.2, cy: 3.2, count: 5, label: "童装" },
    { color: C.accentPurple, cx: 4.0, cy: 4.4, count: 4, label: "TERREX" },
  ];

  clusters.forEach(cl => {
    for (let i = 0; i < cl.count; i++) {
      const angle = (i / cl.count) * Math.PI * 2;
      const r = 0.2 + Math.random() * 0.4;
      const nx = cl.cx + Math.cos(angle) * r;
      const ny = cl.cy + Math.sin(angle) * r;
      s.addShape(pres.shapes.OVAL, {
        x: nx, y: ny, w: 0.13, h: 0.13,
        fill: { color: cl.color },
        shadow: { type: "outer", color: cl.color, blur: 4, offset: 1, angle: 135, opacity: 0.5 },
      });
    }
    // Cluster label
    s.addText(cl.label, {
      x: cl.cx - 0.3, y: cl.cy - 0.15, w: 0.6, h: 0.3,
      fontSize: 7, color: C.white, fontFace: FONT_CN,
      align: "center", valign: "middle",
    });
  });

  // Legend
  s.addText("图例", {
    x: 6.7, y: 1.4, w: 2.5, h: 0.35,
    fontSize: 12, bold: true, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  const legend = [
    { color: C.accentPink, label: "跑步" },
    { color: C.accentOrange, label: "三叶草" },
    { color: C.accentTeal, label: "轻运动" },
    { color: C.accentGreen, label: "童装" },
    { color: C.accentPurple, label: "TERREX" },
  ];

  legend.forEach((item, i) => {
    const y = 1.85 + i * 0.4;
    s.addShape(pres.shapes.OVAL, {
      x: 6.8, y: y + 0.02, w: 0.22, h: 0.22,
      fill: { color: item.color },
      shadow: { type: "outer", color: item.color, blur: 3, offset: 1, angle: 135, opacity: 0.4 },
    });
    s.addText(item.label, {
      x: 7.15, y, w: 2.0, h: 0.28,
      fontSize: 11, color: C.textSecondary, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
  });

  // Features list
  s.addText("交互功能", {
    x: 6.7, y: 4.0, w: 2.8, h: 0.35,
    fontSize: 12, bold: true, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("拖拽 · 缩放 · Hover标签\n点击看详情 · 图谱内搜索\nPWA 离线可用", {
    x: 6.7, y: 4.35, w: 2.8, h: 0.8,
    fontSize: 10, color: C.textMuted, fontFace: FONT_CN,
    lineSpacingMultiple: 1.5, margin: 0,
  });

  addPageNum(s, 5, TOTAL);
}

// ================================================================
// SLIDE 6: AI Q&A DEMO (CORE)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("像问同事一样问系统", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 30, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });

  // Question bubble
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.8, y: 1.4, w: 5.2, h: 0.8,
    fill: { color: C.accent, transparency: 20 },
    rectRadius: 0.15,
  });
  s.addText("💬 ADIZERO ADIOS PRO 4 的碳板适合跑全马吗？为什么？", {
    x: 1.1, y: 1.4, w: 4.6, h: 0.8,
    fontSize: 13, color: C.textPrimary, fontFace: FONT_CN,
    valign: "middle", margin: 0,
  });

  // Answer area
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 2.5, w: 8.4, h: 2.2,
    fill: { color: C.bgCard },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 2.5, w: 0.06, h: 2.2,
    fill: { color: C.accentGreen },
  });

  s.addText([
    { text: "ADIZERO ADIOS PRO 4 是专为全马竞速设计的旗舰碳板跑鞋。\n\n", options: { fontSize: 13, color: C.textPrimary, fontFace: FONT_CN } },
    { text: "• 碳柱 + LIGHTBOOST 中底，提供持续强劲回弹，42 公里后衰减极小\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 定价 1699 元，旗舰定位，多位精英选手全马 2:05 以内\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 代际对比：PRO 4 比 PRO 3 减重 12g，能量回馈提升 8%\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "\n📎 来源: entities/adizero-adios-pro-4 · concepts/碳板 · concepts/BOOST", options: { fontSize: 9, color: C.textMuted, fontFace: FONT_CN } },
  ], {
    x: 1.2, y: 2.6, w: 7.8, h: 2.0,
    valign: "top", margin: 0,
  });

  // More examples
  s.addText("试试这些：", {
    x: 0.8, y: 4.95, w: 2, h: 0.35,
    fontSize: 11, bold: true, color: C.textMuted, fontFace: FONT_CN,
    margin: 0,
  });

  const examples = [
    "BOOST 和 LIGHTBOOST 有什么区别？",
    "2025 年三叶草有哪些新中式产品？",
    "童装跑步系列有哪些适合夏季的？",
  ];

  examples.forEach((ex, i) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 0.8 + i * 3.0, y: 5.2, w: 2.7, h: 0.35,
      fill: { color: C.bgCard },
      rectRadius: 0.1,
    });
    s.addText(ex, {
      x: 0.95 + i * 3.0, y: 5.2, w: 2.4, h: 0.35,
      fontSize: 9, color: C.textSecondary, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
  });

  addPageNum(s, 6, TOTAL);
}

// ================================================================
// SLIDE 7: HYBRID RETRIEVAL (NEW - EXTERNAL)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("混合检索：双通道 + 链接增强", {
    x: 0.8, y: 0.4, w: 8, h: 0.6,
    fontSize: 28, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });

  // --- Channel A (left) ---
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 4.2, h: 2.2,
    fill: { color: C.bgCard },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.2, w: 0.06, h: 2.2,
    fill: { color: C.accentOrange },
  });
  s.addText("通道 1: 关键词检索", {
    x: 0.8, y: 1.3, w: 3.7, h: 0.35,
    fontSize: 14, bold: true, color: C.accentOrange, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("gbrain search — tsvector 全文索引", {
    x: 0.8, y: 1.65, w: 3.7, h: 0.25,
    fontSize: 10, color: C.textMuted, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText([
    { text: "• 原句 + 每个关键词独立搜索\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 命中条件: 页面正文精确包含搜索词\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 精度高，召回窄\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 例: 搜\"碳板\" → 必须包含\"碳板\"二字", options: { fontSize: 10, color: C.textMuted, fontFace: FONT_CN } },
  ], {
    x: 0.8, y: 2.0, w: 3.7, h: 1.2,
    valign: "top", margin: 0,
  });

  // --- Channel B (right) ---
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.3, y: 1.2, w: 4.2, h: 2.2,
    fill: { color: C.bgCard },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.3, y: 1.2, w: 0.06, h: 2.2,
    fill: { color: C.accentTeal },
  });
  s.addText("通道 2: 语义+混合检索", {
    x: 5.6, y: 1.3, w: 3.7, h: 0.35,
    fontSize: 14, bold: true, color: C.accentTeal, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("gbrain query — pgvector + BM25 + boosts", {
    x: 5.6, y: 1.65, w: 3.7, h: 0.25,
    fontSize: 9, color: C.textMuted, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText([
    { text: "• pgvector 余弦相似度 (语义)\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• BM25 关键词匹配\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 反向链接 boost (log-scale)\n", options: { fontSize: 11, color: C.textSecondary, fontFace: FONT_CN } },
    { text: "• 例: 搜\"碳板\" → 也能命中\"碳柱\"\"碳纤维\"", options: { fontSize: 10, color: C.textMuted, fontFace: FONT_CN } },
  ], {
    x: 5.6, y: 2.0, w: 3.7, h: 1.2,
    valign: "top", margin: 0,
  });

  // --- Merge arrow ---
  s.addShape(pres.shapes.RECTANGLE, {
    x: 4.3, y: 1.9, w: 1.4, h: 0.06,
    fill: { color: C.accent },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 1.8, y: 1.9, w: 0.06, h: 0.5,
    fill: { color: C.accent },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 8.1, y: 1.9, w: 0.06, h: 0.5,
    fill: { color: C.accent },
  });
  s.addText("↓", {
    x: 4.4, y: 2.1, w: 1.2, h: 0.3,
    fontSize: 18, color: C.accent, fontFace: FONT,
    align: "center", margin: 0,
  });

  // --- Merge box ---
  s.addShape(pres.shapes.RECTANGLE, {
    x: 2.0, y: 3.65, w: 6.0, h: 0.7,
    fill: { color: C.accent, transparency: 18 },
  });
  s.addText("slug_best 融合 → 同一页面取最高分 → 按分降序 → Top-8", {
    x: 2.2, y: 3.65, w: 5.6, h: 0.7,
    fontSize: 14, bold: true, color: C.accent, fontFace: FONT_CN,
    align: "center", valign: "middle", margin: 0,
  });

  // --- Bottom callout ---
  s.addText("💡 双通道互补: 关键词保证精确, 语义保证泛化。取最高分而非求和 — 避免一边低分拖累另一边。", {
    x: 0.8, y: 4.6, w: 8.4, h: 0.4,
    fontSize: 11, italic: true, color: C.textMuted, fontFace: FONT_CN,
    align: "center", margin: 0,
  });

  // --- Link enhancement callout ---
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 5.1, w: 8.4, h: 0.04,
    fill: { color: C.darkLine },
  });
  s.addText("+ 链接增强: 图遍历扩张 → 153 个正文不含\"夹克\"的页面通过链接被发现", {
    x: 0.8, y: 5.2, w: 8.4, h: 0.3,
    fontSize: 10, color: C.accentPurple, fontFace: FONT_CN,
    align: "center", margin: 0,
  });

  addPageNum(s, 7, TOTAL);
}

// ================================================================
// SLIDE 8: CONTINUOUS UPDATE
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("不是一次性项目，是活的系统", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 30, bold: true, color: C.textPrimary, fontFace: FONT_CN,
    margin: 0,
  });

  // Pipeline flow
  const steps = [
    { icon: "📤", label: "上传", desc: "docx/pdf 拖入" },
    { icon: "🤖", label: "解析", desc: "自动提取内容" },
    { icon: "🏷️", label: "打标签", desc: "5 维度分类" },
    { icon: "📄", label: "生成", desc: "页面自动创建" },
    { icon: "🔄", label: "重建", desc: "图谱即时更新" },
    { icon: "✅", label: "可搜", desc: "AI 可问可答" },
  ];

  steps.forEach((step, i) => {
    const x = 0.8 + i * 1.43;
    const y = 1.6;

    // Step circle
    s.addShape(pres.shapes.OVAL, {
      x: x + 0.35, y, w: 0.7, h: 0.7,
      fill: { color: C.bgCard },
      line: { color: C.accent, width: 2 },
    });
    s.addText(step.icon, {
      x: x + 0.35, y, w: 0.7, h: 0.7,
      fontSize: 22, align: "center", valign: "middle",
    });

    // Arrow (except last)
    if (i < 5) {
      s.addText("→", {
        x: x + 1.05, y, w: 0.35, h: 0.7,
        fontSize: 16, color: C.accent, fontFace: FONT,
        align: "center", valign: "middle",
      });
    }

    // Label
    s.addText(step.label, {
      x: x + 0.1, y: y + 0.8, w: 1.2, h: 0.3,
      fontSize: 11, bold: true, color: C.textPrimary, fontFace: FONT_CN,
      align: "center", margin: 0,
    });
    s.addText(step.desc, {
      x: x + 0.1, y: y + 1.05, w: 1.2, h: 0.25,
      fontSize: 9, color: C.textMuted, fontFace: FONT_CN,
      align: "center", margin: 0,
    });
  });

  // Bottom automation section
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.6, w: 8.4, h: 1.4,
    fill: { color: C.bgCard },
  });

  s.addText([
    { text: "⚡ 全自动流水线\n\n", options: { fontSize: 16, bold: true, color: C.accent, fontFace: FONT_CN, breakLine: true } },
    { text: "上传新品资料 → 自动解析内容 → 自动选取合法标签 → 自动生成产品页面 → ", options: { fontSize: 12, color: C.textSecondary, fontFace: FONT_CN, breakLine: true } },
    { text: "自动重建知识图谱 → 自动入库 → AI 可搜可答", options: { fontSize: 12, color: C.textSecondary, fontFace: FONT_CN, breakLine: true } },
    { text: "\n最后一步：人工审核通过 ✓", options: { fontSize: 12, bold: true, color: C.accentGreen, fontFace: FONT_CN } },
  ], {
    x: 1.2, y: 3.8, w: 7.6, h: 1.2,
    margin: 0,
  });

  addPageNum(s, 8, TOTAL);
}

// ================================================================
// SLIDE 9: VALUE SUMMARY
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };

  // Stars
  const stars2 = [[1.2,0.6],[8.5,1.0],[3.5,3.2],[7.0,3.8],[1.8,4.5],[8.3,4.6],[5.5,5.0]];
  stars2.forEach(([x, y]) => {
    s.addShape(pres.shapes.OVAL, {
      x, y, w: 0.04, h: 0.04,
      fill: { color: C.white, transparency: 60 },
    });
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.2, w: 1.5, h: 0.04,
    fill: { color: C.accent },
  });

  s.addText("让每一位销售都像产品经理", {
    x: 0.8, y: 1.5, w: 8.4, h: 0.8,
    fontSize: 32, bold: true, color: C.white, fontFace: FONT_CN,
    margin: 0,
  });

  // Three value props
  const values = [
    { icon: "🔍", title: "搜得到", body: "语义搜索替代翻文档" },
    { icon: "📊", title: "看得清", body: "知识图谱替代 Excel 表" },
    { icon: "🤖", title: "问得着", body: "AI 问答替代问同事" },
  ];

  values.forEach((v, i) => {
    const x = 0.8 + i * 3.0;
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: 2.7, w: 2.6, h: 1.5,
      fill: { color: C.bgCard, transparency: 30 },
    });
    s.addText(v.icon, {
      x, y: 2.8, w: 2.6, h: 0.5,
      fontSize: 30, align: "center",
    });
    s.addText(v.title, {
      x: x + 0.3, y: 3.3, w: 2.0, h: 0.4,
      fontSize: 18, bold: true, color: C.white, fontFace: FONT_CN,
      align: "center", margin: 0,
    });
    s.addText(v.body, {
      x: x + 0.3, y: 3.65, w: 2.0, h: 0.35,
      fontSize: 12, color: C.textSecondary, fontFace: FONT_CN,
      align: "center", margin: 0,
    });
  });

  // CTA
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 4.6, w: 8.4, h: 0.04,
    fill: { color: C.darkLine },
  });
  s.addText("🌐 在线体验 · 定制咨询 · 技术合作", {
    x: 0.8, y: 4.75, w: 8.4, h: 0.4,
    fontSize: 14, color: C.accent, fontFace: FONT_CN,
    align: "center",
  });

  addPageNum(s, 9, TOTAL);
}

// ================================================================
// SLIDE 10: TECH ARCHITECTURE (INTERNAL)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  // Divider bar
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accentOrange },
  });

  s.addText("技术架构", {
    x: 0.8, y: 0.2, w: 4, h: 0.5,
    fontSize: 22, bold: true, color: C.accentOrange, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("8 层架构，端到端闭环", {
    x: 0.8, y: 0.65, w: 8, h: 0.4,
    fontSize: 14, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  // Architecture layers
  const layers = [
    { num: "1", name: "数据接入", desc: "server.py · docx/pdf 上传 · 原始语料", color: C.accentTeal },
    { num: "2", name: "内容创建", desc: "wiki-ingest → TAG_TAXONOMY + SCHEMA", color: C.accent },
    { num: "3", name: "内容结构", desc: "252 实体 + 53 概念 · 5 维 taxonomy", color: C.accentPink },
    { num: "4", name: "质量网关", desc: "validate-taxonomy.py · gbrain doctor 71 项检查", color: C.accentOrange },
    { num: "5", name: "图谱可视化", desc: "D3.js v7 · 709 条边 · 深空主题 · PWA", color: C.accentGreen },
    { num: "6", name: "混合检索", desc: "关键词(tsvector) ∥ 语义(pgvector+BM25) → slug_best 融合 → Top-8", color: C.accentPurple },
    { num: "7", name: "AI 问答", desc: "gbrain search → context assembly → hermes SSE", color: C.accentTeal },
    { num: "8", name: "用户界面", desc: "Python HTTP + ThreadingMixIn · 端口 8767", color: C.accent },
  ];

  layers.forEach((layer, i) => {
    const y = 1.25 + i * 0.52;
    // Number circle
    s.addShape(pres.shapes.OVAL, {
      x: 0.8, y: y + 0.03, w: 0.32, h: 0.32,
      fill: { color: layer.color },
    });
    s.addText(layer.num, {
      x: 0.8, y: y + 0.03, w: 0.32, h: 0.32,
      fontSize: 12, bold: true, color: C.white, fontFace: FONT,
      align: "center", valign: "middle",
    });
    s.addText(layer.name, {
      x: 1.3, y, w: 1.2, h: 0.38,
      fontSize: 12, bold: true, color: C.textPrimary, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
    s.addText(layer.desc, {
      x: 2.6, y, w: 6.2, h: 0.38,
      fontSize: 10, color: C.textSecondary, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
  });

  // Tech stack badge
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 5.1, w: 8.4, h: 0.04,
    fill: { color: C.darkLine },
  });
  s.addText("技术栈: PGLite + pgvector | D3.js v7 (vanilla JS) | Python http.server + ThreadingMixIn | OpenAI text-embedding-3-large | Hermes Agent", {
    x: 0.8, y: 5.2, w: 8.4, h: 0.3,
    fontSize: 8, color: C.textMuted, fontFace: FONT_CN,
    margin: 0,
  });

  addPageNum(s, 10, TOTAL);
}

// ================================================================
// SLIDE 11: RETRIEVAL PIPELINE (NEW - INTERNAL)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accentOrange },
  });

  s.addText("检索全链路详解", {
    x: 0.8, y: 0.2, w: 4, h: 0.5,
    fontSize: 22, bold: true, color: C.accentOrange, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText(`一条查询"轻运动有哪些夹克？"的完整旅程`, {
    x: 0.8, y: 0.65, w: 8, h: 0.35,
    fontSize: 13, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  // Stage boxes as a vertical flow
  const stages = [
    { num: "1", title: "双通道召回", desc: "关键词(tsvector) + 语义(pgvector+BM25)\n各 5 次调用 → slug_best 融合去重\n直接命中: ~60 候选", color: C.accentOrange },
    { num: "2", title: "图遍历扩张", desc: "沿 wikilinks 展开关联实体\nsportswear-overview 122 入链 → +122 页\njacket-attack-series → +N 页\n扩张至: 198 候选 (4.4x)", color: C.accentPurple },
    { num: "3", title: "五维排序", desc: "embedding余弦 + BM25 + log(入链数)\n+ 时效衰减 + title精确匹配\n→ 按综合分降序 → Top-8", color: C.accent },
    { num: "4", title: "上下文组装", desc: "Top-4 读全文 ≤1500字/篇\nTop 5-8 取摘要 ≤1000字/篇\n→ ~5000字符上下文 → LLM回答", color: C.accentGreen },
  ];

  stages.forEach((stage, i) => {
    const y = 1.15 + i * 1.05;
    // Stage number circle
    s.addShape(pres.shapes.OVAL, {
      x: 0.7, y: y + 0.05, w: 0.38, h: 0.38,
      fill: { color: stage.color },
    });
    s.addText(stage.num, {
      x: 0.7, y: y + 0.05, w: 0.38, h: 0.38,
      fontSize: 14, bold: true, color: C.white, fontFace: FONT,
      align: "center", valign: "middle",
    });
    // Arrow between stages
    if (i < 3) {
      s.addText("▼", {
        x: 0.75, y: y + 0.42, w: 0.3, h: 0.2,
        fontSize: 10, color: C.textMuted, fontFace: FONT,
        align: "center",
      });
    }
    // Stage title
    s.addText(stage.title, {
      x: 1.3, y, w: 2.0, h: 0.35,
      fontSize: 14, bold: true, color: stage.color, fontFace: FONT_CN,
      valign: "middle", margin: 0,
    });
    // Stage description
    s.addText(stage.desc, {
      x: 3.5, y: y - 0.02, w: 5.5, h: 0.85,
      fontSize: 10, color: C.textSecondary, fontFace: FONT_CN,
      lineSpacingMultiple: 1.3, valign: "top", margin: 0,
    });
  });

  // Bottom insight
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 5.1, w: 8.4, h: 0.04,
    fill: { color: C.darkLine },
  });
  s.addText("核心差异: 纯 RAG 只有阶段 1 的 embedding 部分 → 召回仅 45 页。链接增强后 → 198 页 + 更准的排序。", {
    x: 0.8, y: 5.2, w: 8.4, h: 0.3,
    fontSize: 10, italic: true, color: C.textMuted, fontFace: FONT_CN,
    align: "center", margin: 0,
  });

  addPageNum(s, 11, TOTAL);
}

// ================================================================
// SLIDE 12: QUALITY ASSURANCE (INTERNAL)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accentOrange },
  });

  s.addText("质量保障", {
    x: 0.8, y: 0.2, w: 4, h: 0.5,
    fontSize: 22, bold: true, color: C.accentOrange, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("每一页都经过自动校验", {
    x: 0.8, y: 0.65, w: 8, h: 0.4,
    fontSize: 14, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  // Validation checks
  s.addText("validate-taxonomy.py", {
    x: 0.8, y: 1.25, w: 3.5, h: 0.35,
    fontSize: 14, bold: true, color: C.accent, fontFace: FONT_CN,
    margin: 0,
  });

  const checks = [
    "✓ category 在 taxonomy 中?",
    "✓ series 每个值合法?",
    "✓ product_type 合法?",
    "✓ position 合法?",
    "✓ attributes 每个值合法?",
    "✓ tags 派生值一致?",
    "✓ 实体→实体链接 = 0",
  ];

  checks.forEach((check, i) => {
    const col = i < 4 ? 0 : 1;
    const row = i % 4;
    s.addText(check, {
      x: 0.8 + col * 4.2, y: 1.65 + row * 0.32,
      w: 3.8, h: 0.28,
      fontSize: 11, color: C.textSecondary, fontFace: FONT_CN,
      margin: 0,
    });
  });

  // gbrain doctor
  s.addText("gbrain doctor — 71 项自动检查", {
    x: 0.8, y: 3.05, w: 4, h: 0.35,
    fontSize: 14, bold: true, color: C.accent, fontFace: FONT_CN,
    margin: 0,
  });

  // Health score gauge (text-based)
  s.addText("84", {
    x: 0.8, y: 3.4, w: 1.5, h: 0.8,
    fontSize: 48, bold: true, color: C.accentGreen, fontFace: FONT,
    margin: 0,
  });
  s.addText("/ 100", {
    x: 2.1, y: 3.8, w: 1, h: 0.4,
    fontSize: 18, color: C.textMuted, fontFace: FONT,
    margin: 0,
  });
  s.addText("脑健康分", {
    x: 0.8, y: 4.15, w: 2.5, h: 0.3,
    fontSize: 12, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  // Metrics table
  const metrics = [
    ["指标", "目标", "当前", "状态"],
    ["嵌入覆盖", "100%", "100%", "✅"],
    ["链接覆盖", "70%", "55%", "⚠️"],
    ["实体违规", "0", "0", "✅"],
    ["图谱信号", "≥30%", "45%", "✅"],
    ["孤页率", "-", "42%", "—"],
  ];

  const colW = [1.5, 0.8, 0.8, 0.6];
  const tableX = 4.0;
  const tableY = 1.25;

  metrics.forEach((row, ri) => {
    let cx = tableX;
    row.forEach((cell, ci) => {
      const isHeader = ri === 0;
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: tableY + ri * 0.38, w: colW[ci], h: 0.35,
        fill: { color: isHeader ? C.accent : (ri % 2 === 0 ? C.bgCard : C.bgPanel) },
      });
      s.addText(cell, {
        x: cx + 0.1, y: tableY + ri * 0.38, w: colW[ci] - 0.2, h: 0.35,
        fontSize: 10, bold: isHeader, color: isHeader ? C.white : C.textSecondary,
        fontFace: FONT_CN, valign: "middle", margin: 0,
      });
      cx += colW[ci];
    });
  });

  // Rebuild gate mechanism
  s.addText("门禁机制", {
    x: 4.0, y: 3.8, w: 2, h: 0.35,
    fontSize: 14, bold: true, color: C.accent, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("regenerate-graph.py 第 0 步：\n跑 validate-taxonomy.py\n→ 不通过就拒绝生成图谱", {
    x: 4.0, y: 4.15, w: 4.5, h: 0.9,
    fontSize: 11, color: C.textSecondary, fontFace: FONT_CN,
    lineSpacingMultiple: 1.5, margin: 0,
  });

  addPageNum(s, 12, TOTAL);
}

// ================================================================
// SLIDE 13: ROADMAP (INTERNAL)
// ================================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bgPanel };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0, w: 9, h: 0.04,
    fill: { color: C.accentOrange },
  });

  s.addText("扩展路线图", {
    x: 0.8, y: 0.2, w: 4, h: 0.5,
    fontSize: 22, bold: true, color: C.accentOrange, fontFace: FONT_CN,
    margin: 0,
  });
  s.addText("下一步可以做什么（按业务优先级推进）", {
    x: 0.8, y: 0.65, w: 8, h: 0.4,
    fontSize: 14, color: C.textSecondary, fontFace: FONT_CN,
    margin: 0,
  });

  const roadmap = [
    { icon: "🔗", title: "链接覆盖提升", desc: "自动提取 wikilinks，55% → 70% 目标，+181 条链接", priority: "短期" },
    { icon: "🏃", title: "跑步品类深挖", desc: "竞品对比、代际演进时间线、完整产品矩阵", priority: "短期" },
    { icon: "🖼️", title: "多媒体嵌入", desc: "产品图片 → CLIP 向量 → 以图搜图", priority: "中期" },
    { icon: "☁️", title: "云端部署", desc: "PGLite → Supabase，支持多人协作", priority: "中期" },
    { icon: "📱", title: "移动端优化", desc: "PWA 已就绪，补充移动端自适应布局", priority: "中期" },
    { icon: "📈", title: "数据分析层", desc: "新品上市节奏、品类价格带分析、趋势报表", priority: "长期" },
  ];

  roadmap.forEach((item, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.8 + col * 4.6;
    const y = 1.25 + row * 1.3;
    const w = 4.2;
    const h = 1.1;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.bgCard },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 135, opacity: 0.15 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: 0.05,
      fill: { color: C.accent },
    });

    s.addText(item.icon, {
      x: x + 0.2, y: y + 0.1, w: 0.5, h: 0.45,
      fontSize: 22, valign: "middle",
    });
    s.addText(item.title, {
      x: x + 0.75, y: y + 0.08, w: 2.2, h: 0.3,
      fontSize: 13, bold: true, color: C.textPrimary, fontFace: FONT_CN,
      margin: 0,
    });
    // Priority badge
    const priColor = item.priority === "短期" ? C.accentGreen : (item.priority === "中期" ? C.accentOrange : C.accentPurple);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x + w - 0.8, y: y + 0.08, w: 0.6, h: 0.25,
      fill: { color: priColor, transparency: 30 },
      rectRadius: 0.1,
    });
    s.addText(item.priority, {
      x: x + w - 0.8, y: y + 0.08, w: 0.6, h: 0.25,
      fontSize: 8, bold: true, color: priColor, fontFace: FONT_CN,
      align: "center", valign: "middle",
    });
    s.addText(item.desc, {
      x: x + 0.75, y: y + 0.42, w: 3.2, h: 0.55,
      fontSize: 10, color: C.textSecondary, fontFace: FONT_CN,
      lineSpacingMultiple: 1.4, margin: 0,
    });
  });

  addPageNum(s, 13, TOTAL);
}

// ================================================================
// EXPORT
// ================================================================
const outPath = "os.path.join(cfg.paths.kb_root, "knowledge-brain.pptx")";
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("✅ PPT generated: " + outPath);
}).catch(err => {
  console.error("❌ Error:", err);
});
