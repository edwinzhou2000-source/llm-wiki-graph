#!/bin/bash
# Batch extract product images from all adidas training PDFs
# Usage: bash batch_extract_images.sh

set -e

SCRIPT="/Users/edwin.zhou/.hermes/skills/wiki/gbrain-knowledge-base/scripts/vision-ingest.py"
KB_DIR="/Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB"
LOG_DIR="$KB_DIR/logs"
LOG_FILE="$LOG_DIR/batch_extract_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== Batch Image Extraction ==="
echo "Started: $(date)"
echo ""

PDFS=(
  "/Users/edwin.zhou/Documents/adidas培训材料/知识库语料/课件+试题+AI语料/SP-RN/跑步-4月-课件.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/知识库语料/课件+试题+AI语料/ORI/三叶草-4月-课件.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/知识库语料/课件+试题+AI语料/SPW/轻运动-4月-课件.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/[季度新品] 2026年4月 三叶草 新品 E-BOOK.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/2026年4月 运动表现 足球 新品 E-Book.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/2026年Q2 4月 轻运动新品.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/26Q2 Kids New Product Training E Book-4月.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/26年4月 FO PP款产品学习手册.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/POC阶段/轻运动新品/2025年Q4 10月 轻运动新品-Final.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/POC阶段/轻运动新品/2025年Q4 11月 轻运动新品-Final.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/POC阶段/轻运动新品/2025年Q4 12月 轻运动新品-Final.pdf"
  "/Users/edwin.zhou/Documents/adidas培训材料/POC阶段/三叶草/[季度新品] 2025年10月 三叶草 新品 E-BOOK.pdf"
)

TOTAL=${#PDFS[@]}
SUCCESS=0
FAILED=0
TOTAL_CROPS=0
TOTAL_LINKED=0

for i in "${!PDFS[@]}"; do
  PDF="${PDFS[$i]}"
  STEM=$(basename "$PDF" .pdf)
  IMAGE_DIR="$KB_DIR/images/$STEM"
  
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "[$((i+1))/$TOTAL] $STEM"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  
  if PYTHONUNBUFFERED=1 python3 "$SCRIPT" "$PDF" \
    --prompt product \
    --extract-images \
    --skip-text \
    --image-out-dir "$IMAGE_DIR" \
    --out-dir /tmp/vision_ingest_tmp 2>&1; then
    
    # Count crops
    MANIFEST="$IMAGE_DIR/manifest.json"
    if [ -f "$MANIFEST" ]; then
      CROPS=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(sum(len(p.get('products',[])) for p in d))")
      echo "  → $CROPS crops extracted"
      TOTAL_CROPS=$((TOTAL_CROPS + CROPS))
      
      # Try linking
      echo "  → linking to KB pages..."
      python3 "$SCRIPT" NONE --link-only \
        --image-out-dir "$IMAGE_DIR" \
        --kb-dir "$KB_DIR" 2>&1 | grep '\[link\]' || true
    fi
    
    SUCCESS=$((SUCCESS + 1))
  else
    echo "  ✗ FAILED"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "═══════════════════════════════════════"
echo "Done: $(date)"
echo "  Succeeded: $SUCCESS/$TOTAL"
echo "  Failed:    $FAILED/$TOTAL"
echo "  Total crops: $TOTAL_CROPS"
echo "  Log: $LOG_FILE"
echo "═══════════════════════════════════════"
