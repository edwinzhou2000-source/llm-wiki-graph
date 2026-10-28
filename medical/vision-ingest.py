#!/usr/bin/env python3
"""
Vision-based file ingest: PPT/PDF → 1080p images → qwen3.7-plus → markdown.

Usage:
    python3 vision-ingest.py <file.pptx|file.pdf> [--prompt PROMPT_NAME] [--out-dir DIR]

Prompt presets:
    product   - 产品资料提取（SKU、名称、特性、科技）
    training  - 培训材料理解（知识点、要点归纳）
    general   - 通用文本+图像描述（默认）
"""

import os, sys, json, base64, io, shutil, tempfile, time, argparse, subprocess
from pathlib import Path

# ── path config ──
BASE = Path(__file__).resolve().parent
UPLOADS = BASE / "raw" / "articles" / "_uploads"

# ── env ──
def _load_env():
    env = {}
    env_path = os.path.expanduser("~/.hermes/.env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env

_ENV = _load_env()
DASHSCOPE_API_KEY = _ENV.get("DASHSCOPE_API_KEY", os.environ.get("DASHSCOPE_API_KEY", ""))
DASHSCOPE_BASE_URL = _ENV.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VISION_MODEL = "qwen3.7-plus"

# ── image conversion ──
TARGET_LONG_EDGE = 1920  # 1080p equivalent

def pptx_to_images(pptx_path, work_dir):
    """Convert PPTX to PNG images via LibreOffice → PDF → fitz."""
    import fitz  # PyMuPDF

    # Step 1: PPTX → PDF via LibreOffice headless
    pdf_path = os.path.join(work_dir, "_temp.pptx.pdf")
    print(f"  [1/3] Converting PPTX to PDF...")
    result = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", work_dir, pptx_path],
        capture_output=True, text=True, timeout=120, cwd=work_dir
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice PPTX→PDF failed: {result.stderr[:300]}")

    # LibreOffice names the output based on the input filename
    input_stem = os.path.splitext(os.path.basename(pptx_path))[0]
    expected_pdf = os.path.join(work_dir, f"{input_stem}.pdf")
    if not os.path.exists(expected_pdf):
        # Try to find any PDF that was generated
        pdfs = [f for f in os.listdir(work_dir) if f.endswith('.pdf')]
        if pdfs:
            expected_pdf = os.path.join(work_dir, pdfs[0])
        else:
            raise RuntimeError(f"PDF not generated, LibreOffice output:\n{result.stdout}")

    return _pdf_to_images(expected_pdf, work_dir)

def pdf_to_images(pdf_path, work_dir):
    """Convert PDF to PNG images via fitz (PyMuPDF)."""
    return _pdf_to_images(pdf_path, work_dir)

def _pdf_to_images(pdf_path, work_dir):
    """Render PDF pages to 1080p PNGs."""
    import fitz
    print(f"  [2/3] Rendering pages to images...")
    doc = fitz.open(pdf_path)
    image_paths = []

    for i, page in enumerate(doc):
        # Calculate zoom to hit target long edge
        rect = page.rect
        long_edge = max(rect.width, rect.height)
        zoom = TARGET_LONG_EDGE / long_edge if long_edge > 0 else 2.0

        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_path = os.path.join(work_dir, f"page_{i+1:03d}.png")
        pix.save(img_path)
        image_paths.append(img_path)

    doc.close()
    print(f"  → {len(image_paths)} pages rendered ({TARGET_LONG_EDGE}px long edge)")
    return image_paths

# ── Vision API ──
import requests
from config import cfg, KB_ROOT, load_env

PROMPTS = {
    "product": """你是 {{cfg.brand.display_name}} 产品资料分析助手。请仔细查看这张幻灯片/页面图片，提取以下信息：

1. **产品名称/货号 (SKU)**：所有可见的产品编号和名称
2. **产品分类**：属于运动表现 / 三叶草 / 轻运动 / 科技 / 系列 中的哪一类
3. **核心特性**：科技（BOOST/LIGHTSTRIKE/PRIMEKNIT等）、面料、功能特点
4. **关键数据**：价格、尺码范围、上市时间等
5. **图片内容描述**：产品图、模特图、场景图中展示的内容

请用中文回答，按上述结构组织。如果某类信息不可见，标注"（未提及）"。""",

    "training": """你是 {{cfg.brand.display_name}} 培训材料分析助手。请仔细查看这张幻灯片/页面图片，提取以下信息：

1. **幻灯片标题和核心主题**
2. **关键知识点**：列出本页讲授的所有要点
3. **重要数据/案例**：任何数字、图表、案例
4. **总结**：用 2-3 句话归纳本页核心内容

请用中文回答，简洁清晰。""",

    "general": """请仔细查看这张图片，完整提取：

1. **所有可见文字**：逐行复述，保留层级和格式
2. **图片/图表内容描述**：描述所有非文字视觉元素
3. **整体页面主题**：一句话总结

请用中文回答。""",
}

def call_vision(image_path, prompt_name="general", max_tokens=2000):
    """Call qwen3.7-plus vision API with a single image."""
    # Load and encode image
    with open(image_path, "rb") as f:
        img_data = f.read()

    # Resize if too large (>10MB base64 encoded)
    b64 = base64.b64encode(img_data).decode()
    if len(b64) > 10_000_000:
        # Compress: reduce to 75% quality JPEG
        from PIL import Image
        img = Image.open(io.BytesIO(img_data))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode()
        print(f"    (compressed image for API: {len(b64)//1024}KB base64)")

    prompt = PROMPTS.get(prompt_name, PROMPTS["general"])
    mime = "image/png" if image_path.endswith(".png") else "image/jpeg"

    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]
        }],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }

    resp = requests.post(
        f"{DASHSCOPE_BASE_URL}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
        timeout=90,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Vision API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

# ── Main ──
def process_file(file_path, prompt_name="general", out_dir=None):
    """Convert a PPTX/PDF to images, run vision on each, produce markdown."""
    file_path = os.path.abspath(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    stem = os.path.splitext(os.path.basename(file_path))[0]

    if out_dir is None:
        out_dir = str(UPLOADS)
    os.makedirs(out_dir, exist_ok=True)

    work_dir = tempfile.mkdtemp(prefix="vision_ingest_")
    print(f"Processing: {os.path.basename(file_path)}")
    print(f"  Prompt: {prompt_name}")
    print(f"  Work dir: {work_dir}")

    try:
        # Step 1 & 2: Convert to images
        if ext == ".pdf":
            image_paths = pdf_to_images(file_path, work_dir)
        elif ext in (".pptx", ".ppt"):
            image_paths = pptx_to_images(file_path, work_dir)
        else:
            raise ValueError(f"Unsupported format: {ext} (only .pptx/.ppt/.pdf)")

        if not image_paths:
            print("  ⚠️ No images generated")
            return None

        # Step 3: Call vision API per image
        print(f"  [3/3] Running vision API on {len(image_paths)} page(s)...")
        results = []
        for i, img_path in enumerate(image_paths):
            page_num = i + 1
            print(f"    Page {page_num}/{len(image_paths)}...", end=" ", flush=True)
            try:
                text = call_vision(img_path, prompt_name)
                results.append((page_num, text))
                print(f"✓ ({len(text)} chars)")
            except Exception as e:
                results.append((page_num, f"[ERROR: {e}]"))
                print(f"✗ {e}")

            # Small delay to avoid rate limiting
            if i < len(image_paths) - 1:
                time.sleep(1)

        # Step 4: Save incrementally (so partial results survive timeouts)
        out_name = f"{stem}.vision.md"
        out_path = os.path.join(out_dir, out_name)

        # Write header
        header = "\n".join([
            f"---",
            f"title: {stem}",
            f"source: vision-ingest ({ext})",
            f"pages: {len(image_paths)}",
            f"prompt: {prompt_name}",
            f"model: {VISION_MODEL}",
            f"---",
            f"",
            f"# {stem}",
            f"",
            f"*{len(image_paths)} pages processed via vision API*",
            f"",
        ])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(header)

        # Append each page as it completes
        for page_num, text in results:
            page_block = f"## 第 {page_num} 页\n\n{text}\n\n"
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(page_block)

        print(f"\n✅ Saved: {out_path}")
        print(f"   {len(image_paths)} pages → {os.path.getsize(out_path)} bytes markdown")
        return out_path

    finally:
        # Cleanup work dir (keep images? for now, delete)
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vision-based PPT/PDF ingest")
    parser.add_argument("file", help="PPTX or PDF file to process")
    parser.add_argument("--prompt", default="general",
                        choices=["product", "training", "general"],
                        help="Prompt preset (default: general)")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory for markdown (default: _uploads)")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}")
        sys.exit(1)

    process_file(args.file, args.prompt, args.out_dir)
