#!/usr/bin/env bash
# =============================================================================
# setup.sh — LLM-WIKI KB 一键初始化脚本
# =============================================================================
# 运行: bash setup.sh
# 功能:
#   1. 检查依赖 (Python3, PyYAML, gbrain CLI)
#   2. 从 kb-config.yml 读取配置
#   3. 创建品类目录结构
#   4. 生成 index.md (首页)
#   5. 初始化 gbrain 数据库
#   6. 生成 .gbrainignore
#   7. 创建状态文件
# =============================================================================

set -e
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  LLM-WIKI KB — 一键初始化${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# ── 1. Check dependencies ──────────────────────────────────────────
echo -e "${YELLOW}[1/6] 检查依赖...${NC}"

# Python3
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}❌ 未找到 python3${NC}"
    exit 1
fi
echo "  ✅ python3 $(python3 --version)"

# PyYAML
python3 -c "import yaml" 2>/dev/null || {
    echo -e "${YELLOW}  ⚠️  缺少 PyYAML, 正在安装...${NC}"
    pip3 install pyyaml
}
echo "  ✅ PyYAML"

# gbrain CLI (optional — warn but don't fail)
if command -v bun &>/dev/null && [ -f ~/gbrain/src/cli.ts ]; then
    echo "  ✅ gbrain CLI (Bun)"
else
    echo -e "${YELLOW}  ⚠️  gbrain CLI 未找到 — 搜索功能需要 gbrain${NC}"
    echo "     安装: brew install oven-sh/bun/bun && cd ~ && git clone <gbrain-repo>"
fi

# hermes CLI (optional — for upload ingest)
if command -v hermes &>/dev/null; then
    echo "  ✅ hermes CLI"
else
    echo -e "${YELLOW}  ⚠️  hermes CLI 未找到 — 上传入库需要 hermes${NC}"
fi

echo ""

# ── 2. Load config ──────────────────────────────────────────────────
echo -e "${YELLOW}[2/6] 加载 kb-config.yml...${NC}"

CONFIG="$SCRIPT_DIR/kb-config.yml"
if [ ! -f "$CONFIG" ]; then
    echo -e "${RED}❌ 未找到 kb-config.yml${NC}"
    exit 1
fi

# Extract values using Python (handles YAML properly)
BRAND_NAME=$(python3 -c "
from config import cfg
print(cfg.brand.name)
")
DISPLAY_NAME=$(python3 -c "
from config import cfg
print(cfg.brand.display_name)
")
PUBLIC_NAME=$(python3 -c "
from config import cfg
print(cfg.brand.public_name)
")
GBRAIN_HOME=$(python3 -c "
from config import cfg
print(cfg.paths.gbrain_home)
")
SERVER_PORT=$(python3 -c "
from config import cfg
print(cfg.server.port)
")
COOKIE_NAME=$(python3 -c "
from config import cfg
print(cfg.server.cookie_name)
")

echo "  品牌: $BRAND_NAME"
echo "  展示名: $DISPLAY_NAME"
echo "  公网名: $PUBLIC_NAME"
echo "  gbrain 路径: $GBRAIN_HOME"
echo "  端口: $SERVER_PORT"
echo ""

# ── 3. Create directory structure ───────────────────────────────────
echo -e "${YELLOW}[3/6] 创建目录结构...${NC}"

python3 << 'PYEOF'
from config import cfg, KB_ROOT
import os

created = 0
for c in cfg.categories:
    # Main category dir
    d = os.path.join(KB_ROOT, c.dir)
    os.makedirs(d, exist_ok=True)
    # index.md
    idx = os.path.join(d, "index.md")
    if not os.path.exists(idx):
        with open(idx, "w") as f:
            f.write(f"---\ntitle: \"{c.name} 索引\"\ncategory: \"{c.name}\"\n---\n\n# {c.name}\n\n")
        created += 1

    # Subcategories
    for sub in getattr(c, 'subcategories', []) or []:
        sd = os.path.join(KB_ROOT, c.dir, sub.dir)
        os.makedirs(sd, exist_ok=True)
        sidx = os.path.join(sd, "index.md")
        if not os.path.exists(sidx):
            with open(sidx, "w") as f:
                f.write(f"---\ntitle: \"{c.name} — {sub.name} 索引\"\ncategory: \"{c.name}\"\n---\n\n# {c.name} — {sub.name}\n\n")
            created += 1

        # Grandchildren
        for child in getattr(sub, 'children', []) or []:
            cd = os.path.join(KB_ROOT, c.dir, sub.dir, child.dir)
            os.makedirs(cd, exist_ok=True)
            cidx = os.path.join(cd, "index.md")
            if not os.path.exists(cidx):
                with open(cidx, "w") as f:
                    f.write(f"---\ntitle: \"{c.name} — {sub.name} — {child.name} 索引\"\ncategory: \"{c.name}\"\n---\n\n# {c.name} — {sub.name} — {child.name}\n\n")
                created += 1

print(f"  ✅ 创建了 {created} 个 index.md, 目录已就绪")
PYEOF

echo ""

# ── 4. Generate root index.md ───────────────────────────────────────
echo -e "${YELLOW}[4/6] 生成首页...${NC}"

python3 << 'PYEOF'
from config import cfg, KB_ROOT
import os
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")

# Build category tree for markdown
cat_list = []
for c in cfg.categories:
    cat_list.append(f"- **{c.name}** ({c.dir}/)")
    for sub in getattr(c, 'subcategories', []) or []:
        cat_list.append(f"  - {sub.name} ({c.dir}/{sub.dir}/)")
        for child in getattr(sub, 'children', []) or []:
            cat_list.append(f"    - {child.name} ({c.dir}/{sub.dir}/{child.dir}/)")

content = f"""---
title: "{cfg.brand.display_name}"
category: "index"
---

# {cfg.brand.display_name}

> 初始化时间: {today}
> 基于 LLM-WIKI KB 通用框架构建

## 知识库结构

{chr(10).join(cat_list)}

## 使用指南

- 🔍 **智能问答**: 输入产品相关问题，AI 自动检索并回答
- 📤 **上传资料**: 上传 docx/pdf 文档，AI 自动提取并入库
- ✅ **审核提案**: 审核 AI 生成的改进建议
- 📦 **产品浏览**: 按品类浏览所有产品页面
- 🏷️ **标签管理**: 管理分类标签体系

## 技术架构

- 双通道混合检索 (关键词 + 语义向量)
- SSE 流式 AI 问答
- 链接增强 RAG (知识图谱)
- L1/L2/L3 三级自维护
"""

idx_path = os.path.join(KB_ROOT, "index.md")
with open(idx_path, "w") as f:
    f.write(content)
print(f"  ✅ index.md 已生成")
PYEOF

echo ""

# ── 5. Initialize gbrain ────────────────────────────────────────────
echo -e "${YELLOW}[5/6] 初始化 gbrain 数据库...${NC}"

mkdir -p "$GBRAIN_HOME"

# Create gbrain.yml
cat > "$SCRIPT_DIR/gbrain.yml" << GBYML
storage:
  db_tracked:
$(python3 -c "
from config import cfg
for c in cfg.categories:
    print(f'    - {c.dir}/')
")
GBYML
echo "  ✅ gbrain.yml"

# Create .gbrainignore
cat > "$SCRIPT_DIR/.gbrainignore" << IGNORE
_backups/
_proposals/
_meta/
node_modules/
raw/
images/
logs/
.ingest-queue.json
.ingest-status.json
.upload-history.json
IGNORE
echo "  ✅ .gbrainignore"

# Init gbrain (if CLI available)
if command -v bun &>/dev/null && [ -f ~/gbrain/src/cli.ts ]; then
    DATABASE_URL='' GBRAIN_HOME="$GBRAIN_HOME" bun run ~/gbrain/src/cli.ts import . --no-embed 2>&1 || true
    echo "  ✅ gbrain import 完成"
else
    echo -e "  ${YELLOW}⚠️  跳过 gbrain (CLI 未安装)${NC}"
fi

echo ""

# ── 6. Create state files ──────────────────────────────────────────
echo -e "${YELLOW}[6/6] 创建状态文件...${NC}"

echo '{"phase":"idle","message":""}' > "$SCRIPT_DIR/.ingest-status.json"
echo '{"files":[],"mode":"review"}' > "$SCRIPT_DIR/.ingest-queue.json"
echo '[]' > "$SCRIPT_DIR/.upload-history.json"
echo '# 操作日志' > "$SCRIPT_DIR/log.md"

# Create _meta
mkdir -p "$SCRIPT_DIR/_meta"
cat > "$SCRIPT_DIR/_meta/TAG_TAXONOMY.md" << 'TAXEOF'
# 标签分类体系

由 kb-config.yml 动态生成。请编辑 kb-config.yml 的 taxonomy.valid_values 部分来修改受控词汇。
TAXEOF

echo "  ✅ 状态文件已初始化"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  ✅ 初始化完成!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  启动服务器:"
echo "    cd $SCRIPT_DIR"
echo "    python3 server.py"
echo ""
echo "  然后打开:"
echo "    http://localhost:$SERVER_PORT/product-hub.html"
echo ""
echo "  公网隧道:"
echo "    cloudflared tunnel --url http://localhost:$SERVER_PORT \\"
echo "      --logfile $SCRIPT_DIR/logs/cloudflared.log &"
echo ""
echo "  迁移到其他品牌:"
echo "    1. 复制整个目录到新位置"
echo "    2. 编辑 kb-config.yml (改 brand.name, categories, taxonomy)"
echo "    3. 运行 bash setup.sh"
echo ""
