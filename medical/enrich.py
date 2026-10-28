#!/usr/bin/env python3
"""Level 1 auto-enrichment: fill TODO entity/concept pages.
   Scans for "TODO: agent enrichment pass", reads frontmatter + related concepts,
   generates 编译概要 + 核心卖点 + 相关概念 via DeepSeek API, writes back.

Usage:
  python3 enrich.py [--batch N] [--dry-run] [--category CAT]
  N: max pages to process per run (default 5)
  CAT: limit to one category (跑步|三叶草|轻运动|童装|TERREX)
"""

import os, re, json, sys, time
import requests
from datetime import datetime
import sys, os, re, json, time, requests, datetime
from config import cfg, KB_ROOT, PRODUCT_DIRS, CONCEPT_DIRS, ALL_CONTENT_DIRS, TECH_CONCEPT_DIR, SERIES_CONCEPT_DIR, load_env

BASE = KB_ROOT

_ENV = load_env()
DEEPSEEK_API_KEY = _ENV.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
DEEPSEEK_BASE_URL = _ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

def parse_page(path):
    """Parse a markdown page into (frontmatter dict, body text, full raw)."""
    with open(path) as f:
        raw = f.read()
    fm = {}
    body = raw
    if raw.startswith('---'):
        parts = raw.split('---', 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
            for line in fm_text.strip().split('\n'):
                if ':' in line:
                    k, _, v = line.partition(':')
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    fm[k] = v
    return fm, body, raw


def has_todo(body):
    """Check if page body contains TODO enrichment marker."""
    return 'TODO' in body and ('enrichment' in body.lower() or 'agent' in body.lower())


def _extract_relevant_section(content, product_hint, max_chars=5000):
    """Find the most relevant section of a source document for a product.
    Searches for the product name or key terms, returns a window around the match.
    Falls back to the first max_chars if no match found."""
    if not content or len(content) <= max_chars:
        return content[:max_chars]
    
    # Try to find the product name in the content
    # Extract product keywords from the hint (e.g. "轻运动-4月-ai语料.md")
    keywords = []
    # Also try common product identifiers
    for pattern in [r'[A-Z]{2,}\\d{3,}', r'[A-Z]{1,2}\\s?\\d{4,}', r'[A-Z][a-z]+\\s+[A-Z]+']:
        for m in re.finditer(pattern, content[:2000]):
            kw = m.group().strip()
            if len(kw) >= 3:
                keywords.append(kw)
    
    # Try each keyword to find the best match location
    for kw in keywords[:5]:
        idx = content.lower().find(kw.lower())
        if idx >= 0:
            # Take a window around the match: 1500 before, 3500 after
            start = max(0, idx - 1500)
            end = min(len(content), idx + 3500)
            # Try to start/end at section boundaries
            snippet = content[start:end]
            # Trim to nearest ## heading
            last_heading = snippet.rfind('\n## ', 0, 500)
            if last_heading > 0:
                snippet = snippet[last_heading:]
            return snippet[:max_chars]
    
    # Fallback: first max_chars
    return content[:max_chars]


def read_concept_context(category, series_str, source_field=''):
    """Read relevant concept pages + source document for context."""
    context_parts = []
    
    # Parse series from frontmatter
    series_list = []
    if series_str:
        m = re.match(r'\\[(.+)\\]', series_str)
        if m:
            series_list = [s.strip() for s in m.group(1).split(',')]
        else:
            series_list = [series_str.strip()]
    
    # Read category overview
    overview_map = {
        '跑步': '系列/runner-classification.md',
        '三叶草': '系列/originals-overview.md',
        '轻运动': '系列/sportswear-overview.md',
        '童装': '系列/kids-overview.md',
        'TERREX': '系列/terrex-overview.md',
    }
    overview_path = overview_map.get(category, '')
    if overview_path:
        full = os.path.join(BASE, overview_path)
        if os.path.exists(full):
            with open(full) as f:
                content = f.read()
            body = content.split('---', 2)[-1] if content.startswith('---') else content
            context_parts.append(f"### 品类概览: {overview_path}\\n{body[:800]}")
    
    # Read series concept pages
    for s in series_list:
        s_slug = s.lower().replace(' ', '-')
        concept_path = os.path.join(BASE, f'系列/{s_slug}-series.md')
        if os.path.exists(concept_path):
            with open(concept_path) as f:
                content = f.read()
            body = content.split('---', 2)[-1] if content.startswith('---') else content
            context_parts.append(f"### 系列概念: 系列/{s_slug}-series.md\\n{body[:600]}")
    
    # Read source document if referenced
    if source_field and not source_field.startswith('自动生成'):
        for src_dir in ['raw/articles/_uploads', 'raw/articles']:
            src_path = os.path.join(BASE, src_dir, source_field)
            if os.path.exists(src_path):
                try:
                    with open(src_path) as f:
                        src_content = f.read()
                    # Smart extraction: find the product title in the source doc
                    # and take a generous window around it
                    snippet = _extract_relevant_section(src_content, source_field[:60])
                    if snippet:
                        context_parts.append(f"### 原始材料: {source_field}\n{snippet}")
                except:
                    pass
                break
    
    return '\\n\\n'.join(context_parts)


def generate_enrichment(fm, context, is_entity, page_body):
    """Call DeepSeek to generate 编译概要 + supplements.
       page_body: the full body text AFTER frontmatter, so AI can see
       existing ## 核心卖点 / ## 定位与价格 / ## 时间线 etc."""
    title = fm.get('title', 'Unknown')
    category = fm.get('type', '')
    product_type = fm.get('product_type', '')
    position = fm.get('position', '')
    series = fm.get('series', '')
    attributes = fm.get('attributes', '')
    
    # Analyze existing page structure
    has_core_selling = '## 核心卖点' in page_body and not re.search(
        r'##\s*核心卖点\s*\n\s*$', page_body)
    has_concepts = '## 相关概念' in page_body and len(
        re.findall(r'\[\[(?:concepts/)?[\w-]+\]\]', page_body)) > 0
    has_price = '## 定位与价格' in page_body
    
    # Build a smart prompt
    build_rules = []
    build_rules.append(f"生成 ## 编译概要（4-6句自然语言 prose），总结这个产品/概念的定位。")
    
    if has_core_selling:
        build_rules.append(f"⚠️ 页面上已有 ## 核心卖点，不要重新生成。编译概要应引用现有卖点的主要信息。")
    else:
        build_rules.append(f"页面上没有 ## 核心卖点，请根据 taxonomy 和参考上下文生成（按 鞋面/中底/大底 或 面料/版型/科技 展开 FAB）。")
    
    if has_concepts:
        build_rules.append(f"⚠️ 页面上已有 ## 相关概念，不要重新生成。如果发现明显缺失的概念链接，追加到输出中（只列新增的）。")
    else:
        build_rules.append(f"页面上没有 ## 相关概念，请根据品类和系列推导应该链接的概念页。")
    
    system_prompt = f"""你是 {cfg.brand.name} 产品知识撰写专家。为以下页面填补缺失内容。

页面信息：
- 名称：{title}  |  品类：{category}  |  系列：{series}
- 产品类型：{product_type}  |  定位：{position}  |  特性：{attributes}
- 类型：{'产品实体' if is_entity else '概念'}

输出格式（严格遵守）：
```markdown
## 编译概要
[一整段 prose，不挂 [[wikilink]]

## 核心卖点
[仅当页面原本没有时输出。有则写 "(已有)" ]

## 相关概念
[仅当页面原本缺失时输出。有则写 "(已有)" 。如部分缺失则只列新增的]
```

⚠️ 严格约束：
- 只基于「页面信息」中的 taxonomy 标签和下方提供的「参考概念上下文」「原始材料」来撰写
- 如果原始材料提供了具体细节（面料名、科技名、数据），可以直接引用
- 如果原始材料未提及某细节，绝对不要自己推断或添加。例如不要假设某鞋用了 EVA 或某面料用了有机棉——除非材料中明确写了
- 对于纯概念页（只有 taxonomy 标签无原始材料），编译概要控制在 2-3 句泛化描述，基于标签推断即可"""

    # Include the page body as context so AI sees what already exists
    user_msg = f"""以下是该页面的当前内容（请仔细阅读已有的 ## 核心卖点 和 ## 定位与价格，不要编造不存在的信息）：

--- PAGE CONTENT ---
{page_body[:3000]}
--- END PAGE ---

参考概念上下文：
{context if context else '(无)'}

请根据以上要求输出。记得只填补缺失的内容，不要覆盖已有信息。只输出 ```markdown 代码块。"""


    if not DEEPSEEK_API_KEY:
        return None, "DEEPSEEK_API_KEY not set"

    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.5,
                "max_tokens": 1200,
            },
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=30,
        )
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        
        # Extract markdown block
        m = re.search(r'```markdown\s*\n(.*?)```', text, re.DOTALL)
        if m:
            return m.group(1).strip(), None
        # If no code block, use the whole response
        return text, None
    except Exception as e:
        return None, str(e)


def apply_enrichment(path, new_content):
    """Replace the TODO section in the file with generated content.
       Cleans up AI output: strips "(已有)" markers, removes empty sections."""
    fm, body, raw = parse_page(path)
    
    # Clean AI output: remove "(已有)" placeholder blocks
    cleaned = re.sub(r'\n## 核心卖点\n\n\(已有\)', '', new_content)
    cleaned = re.sub(r'\n## 相关概念\n\n\(已有\)', '', cleaned)
    cleaned = re.sub(r'\n## 核心卖点\n\(已有\)', '', cleaned)
    cleaned = re.sub(r'\n## 相关概念\n\(已有\)', '', cleaned)
    cleaned = cleaned.strip()
    
    new_body = body
    
    # Replace entire ## 编译概要 section
    pattern = r'##\s*编译概要\s*\n.*?(?=\n##\s|\Z)'
    replacement = f'## 编译概要\n\n{cleaned}'
    new_body = re.sub(pattern, replacement, body, count=1, flags=re.DOTALL)
    
    # Rebuild file
    fm_block = ''
    if raw.startswith('---'):
        parts = raw.split('---', 2)
        if len(parts) >= 2:
            fm_block = parts[1]
    
    result = f'---\n{fm_block}---\n{new_body}' if fm_block else new_body
    
    with open(path, 'w') as f:
        f.write(result)
    
    return True


def append_log(entries):
    """Append enrichment entries to log.md."""
    log_path = os.path.join(BASE, 'log.md')
    with open(log_path) as f:
        log_content = f.read()
    
    # Insert after the date header
    date_header = f'## {TODAY}'
    if date_header not in log_content:
        # Insert before the first existing entry
        log_content = log_content.replace('---\n', f'---\n\n{date_header}\n\n')
    
    new_entries = '\n'.join(entries)
    log_content = log_content.replace(date_header, f'{date_header}\n{new_entries}')
    
    with open(log_path, 'w') as f:
        f.write(log_content)


def run_consistency_check():
    """Level 2: cross-check product pages against concept pages, detect missing links, etc.
       Outputs _issues.md in _meta/."""
    import os, re
    from datetime import datetime
    
    issues = []
    today = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # Directories to scan (new architecture)
    # PRODUCT_DIRS now imported from config
    # CONCEPT_DIRS now imported from config
    ALL_DIRS = PRODUCT_DIRS + CONCEPT_DIRS
    
    # 1. Count TODO pages (pages with "TODO" + "enrichment" in body)
    todo_pages = []
    for cat in ALL_DIRS:
        d = os.path.join(BASE, cat)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fn in sorted(files):
                if not fn.endswith('.md') or fn == 'index.md':
                    continue
                fpath = os.path.join(root, fn)
                with open(fpath) as f:
                    content = f.read()
                if 'TODO' in content and 'enrichment' in content.lower():
                    rel = os.path.relpath(fpath, BASE)[:-3]  # strip .md
                    todo_pages.append(rel)
    
    # 2. Check product→concept link coverage (new markdown link format)
    unlinked = []
    for cat in PRODUCT_DIRS:
        d = os.path.join(BASE, cat)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fn in sorted(files):
                if not fn.endswith('.md') or fn == 'index.md':
                    continue
                fpath = os.path.join(root, fn)
                with open(fpath) as f:
                    body = f.read()
                # Check for concept links in new format: [text](/dir/slug.md)
                links = re.findall(r'\]\(/(?:科技|系列)/[^)]+\.md\)', body)
                if len(links) == 0:
                    rel = os.path.relpath(fpath, BASE)[:-3]
                    unlinked.append(rel)
    
    # 3. Orphan tag detection: tags used by products but missing concept pages
    orphan_tags = []
    graph_path = os.path.join(BASE, 'graph-data.json')
    if os.path.exists(graph_path):
        try:
            import json
            gd = json.load(open(graph_path))
            all_tags = set()
            for n in gd.get('nodes', []):
                for t in n.get('tags', []):
                    all_tags.add(t)
            concept_slugs = set()
            for concept_dir in CONCEPT_DIRS:
                cd = os.path.join(BASE, concept_dir)
                if not os.path.isdir(cd): continue
                for root, dirs, files in os.walk(cd):
                    for fn in files:
                        if fn.endswith('.md') and fn != 'index.md':
                            concept_slugs.add(fn[:-3])
            for tag in sorted(all_tags):
                if ':' in tag:
                    dim, val = tag.split(':', 1)
                    tag_slug = val.strip().lower().replace(' ', '-').replace('·', '-')
                else:
                    tag_slug = tag.lower().replace(' ', '-')
                if tag_slug and tag_slug not in concept_slugs:
                    if not any(tag_slug in c or c in tag_slug for c in concept_slugs):
                        orphan_tags.append({'tag': tag, 'slug': tag_slug, 'dim': dim if ':' in tag else ''})
        except: pass

    # 4. Build _issues.md
    lines = []
    lines.append(f'# 一致性检查报告')
    lines.append(f'')
    lines.append(f'> {today} · 自动生成')
    lines.append(f'')
    lines.append(f'## ⏳ 待填充页面 ({len(todo_pages)})')
    lines.append(f'')
    if todo_pages:
        for p in todo_pages[:20]:
            lines.append(f'- {p}')
        if len(todo_pages) > 20:
            lines.append(f'- ... 还有 {len(todo_pages) - 20} 页')
    else:
        lines.append('✅ 全部已填充')
    
    lines.append(f'')
    lines.append(f'## 🔗 缺少概念链接 ({len(unlinked)})')
    lines.append(f'')
    if unlinked:
        for p in unlinked[:20]:
            lines.append(f'- {p}')
    else:
        lines.append('✅ 所有实体页都有概念链接')
    
    lines.append(f'')
    lines.append(f'## 🏷️ 孤立标签 — 缺少概念页 ({len(orphan_tags)})')
    lines.append(f'')
    if orphan_tags:
        lines.append('以下标签被产品使用，但 `科技/` 或 `系列/` 下没有对应的概念页面：')
        lines.append('')
        for ot in orphan_tags[:30]:
            dim_info = '（' + ot.get('dim', '') + '）' if ot.get('dim') else ''
            lines.append('- `' + ot['tag'] + '` ' + dim_info + ' → 需创建 `' + ot['slug'] + '.md`')
        if len(orphan_tags) > 30:
            lines.append(f'- ... 还有 {len(orphan_tags) - 30} 个孤立标签')
    else:
        lines.append('✅ 所有标签都有对应的概念页面')

    # 4. Concept page ↔ product consistency: products with wikilinks not in concept page
    #    Single-pass optimization: scan products once, then cross-reference
    lines.append(f'')
    lines.append(f'## 🔄 概念页产品列表一致性')
    lines.append(f'')
    concept_issues = []

    # Pass 1: build concept → listed_products from concept pages
    concept_listed = {}  # slug → set of product slugs listed in concept page
    for concept_dir in CONCEPT_DIRS:
        cd = os.path.join(BASE, concept_dir)
        if not os.path.isdir(cd): continue
        for root, dirs, files in os.walk(cd):
            for fn in sorted(files):
                if not fn.endswith('.md') or fn == 'index.md':
                    continue
                fpath = os.path.join(root, fn)
                concept_slug = os.path.relpath(fpath, BASE)[:-3].replace('\\', '/')
                with open(fpath) as f:
                    concept_body = f.read()
                listed = set()
                for m in re.finditer(r'\[\[([^\]]+)\]\]', concept_body):
                    link = m.group(1)
                    if not link.startswith('科技/') and not link.startswith('系列/') and '/' in link:
                        listed.add(link)
                if listed:
                    concept_listed[concept_slug] = listed

    # Pass 2: single scan of all product pages → build concept → actual_products
    concept_actual = {}  # slug → set of product slugs that wikilink TO this concept
    for pcat in PRODUCT_DIRS:
        pd = os.path.join(BASE, pcat)
        if not os.path.isdir(pd): continue
        for proot, pdirs, pfiles in os.walk(pd):
            for pfn in pfiles:
                if not pfn.endswith('.md') or pfn == 'index.md':
                    continue
                ppath = os.path.join(proot, pfn)
                with open(ppath) as f:
                    pbody = f.read()
                pslug = os.path.relpath(ppath, BASE)[:-3].replace('\\', '/')
                for m in re.finditer(r'\[\[(科技/|系列/)([^\]]+)\]\]', pbody):
                    concept_ref = m.group(0)[2:-2]  # strip [[ and ]]
                    concept_actual.setdefault(concept_ref, set()).add(pslug)

    # Cross-reference: for each concept page, compare listed vs actual
    for concept_slug, listed in concept_listed.items():
        actual = concept_actual.get(concept_slug, set())
        missing = actual - listed
        extra = listed - actual
        if missing or extra:
            concept_issues.append({
                'concept': concept_slug,
                'missing': sorted(missing),
                'extra': sorted(extra),
            })

    # Also check concepts that exist but have NO product wikilinks at all (dataview blocks, etc.)
    for concept_dir in CONCEPT_DIRS:
        cd = os.path.join(BASE, concept_dir)
        if not os.path.isdir(cd): continue
        for root, dirs, files in os.walk(cd):
            for fn in sorted(files):
                if not fn.endswith('.md') or fn == 'index.md':
                    continue
                concept_slug = os.path.relpath(os.path.join(root, fn), BASE)[:-3].replace('\\', '/')
                if concept_slug not in concept_listed:
                    # Concept page has no [[wikilinks]] — check if products reference it via wikilinks
                    actual = concept_actual.get(concept_slug, set())
                    if actual:
                        concept_issues.append({
                            'concept': concept_slug,
                            'missing': sorted(actual),
                            'extra': [],
                            'note': '概念页无 wikilink 产品列表'
                        })

    if concept_issues:
        summary_parts = []
        for ci in concept_issues:
            note = ci.get('note', '')
            label = ' 📋 无产品列表' if note else ''
            summary_parts.append(f'- **`{ci["concept"]}`**{label}')
            if ci['missing']:
                summary_parts.append(f'  - ⚠️ 缺少产品 ({len(ci["missing"])}): ' +
                                    ', '.join(p.rsplit('/', 1)[-1] for p in ci['missing'][:5]))
                if len(ci['missing']) > 5:
                    summary_parts.append(f'    ... 还有 {len(ci["missing"]) - 5} 个')
            if ci['extra']:
                summary_parts.append(f'  - ❓ 多余引用 ({len(ci["extra"])}): ' +
                                    ', '.join(p.rsplit('/', 1)[-1] for p in ci['extra'][:3]))
        lines.extend(summary_parts)
        lines.append(f'')
        lines.append(f'共 {len(concept_issues)} 个概念页有产品列表不一致问题。')
    else:
        lines.append('✅ 所有概念页的产品列表与 wikilink 引用一致')
    
    lines.append(f'')
    lines.append(f'## 📊 汇总')
    lines.append(f'')
    lines.append(f'| 指标 | 数值 |')
    lines.append(f'|------|------|')
    lines.append(f'| TODO 页面 | {len(todo_pages)} |')
    n_pages = 0
    for cat in ALL_DIRS:
        d = os.path.join(BASE, cat)
        if os.path.isdir(d):
            for _root, _dirs, _files in os.walk(d):
                n_pages += sum(1 for fn in _files if fn.endswith('.md') and fn != 'index.md')
    lines.append(f'| 无概念链接 | {len(unlinked)}/{n_pages} |')
    lines.append(f'| 概念页不一致 | {len(concept_issues)} |')
    
    out_path = os.path.join(BASE, '_meta/_issues.md')
    with open(out_path, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f'✅ _issues.md written: {len(todo_pages)} TODOs, {len(unlinked)} unlinked, {len(orphan_tags)} orphan tags')
    for line in lines[:15]:
        print(line)


def run_review_mode(batch_size=5, category_filter=None):
    """Level 3: generate proposals to _proposals/ for human review.
       Does NOT modify any .md files directly."""
    proposals_dir = os.path.join(BASE, '_proposals')
    os.makedirs(proposals_dir, exist_ok=True)
    
    # Collect TODO pages
    todo_pages = []
    for cat_dir in ALL_CONTENT_DIRS:
        d = os.path.join(BASE, cat_dir)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if not fname.endswith('.md') or fname == 'index.md':
                    continue
                fpath = os.path.join(root, fname)
                fm, body, raw = parse_page(fpath)
                if not has_todo(body):
                    continue
                if category_filter and fm.get('type', '') != category_filter:
                    continue
                # Skip if proposal already exists and is pending
                slug = os.path.relpath(fpath, BASE)[:-3]  # strip .md
                prop_path = os.path.join(proposals_dir, f"{slug.replace('/', '_')}.json")
                if os.path.exists(prop_path):
                    with open(prop_path) as f:
                        prop = json.load(f)
                    if prop.get('status') == 'pending':
                        continue  # already proposed
                
                todo_pages.append({
                    'path': fpath,
                    'slug': slug,
                    'fm': fm,
                    'is_entity': cat_dir in PRODUCT_DIRS,
                'raw': raw,
            })
    
    if not todo_pages:
        print("No TODO pages to propose.")
        return
    
    print(f"Found {len(todo_pages)} TODO pages. Generating up to {batch_size} proposals...")
    
    generated = 0
    for page in todo_pages[:batch_size]:
        slug = page['slug']
        fm = page['fm']
        print(f"\n[{generated+1}/{batch_size}] {slug}")
        
        context = read_concept_context(fm.get('type', ''), fm.get('series', ''))
        _, page_body_raw, _ = parse_page(page['path'])
        result, error = generate_enrichment(fm, context, page['is_entity'], page_body_raw)
        
        if error:
            print(f"  ❌ Error: {error[:120]}")
            continue
        if not result:
            print(f"  ❌ Empty response")
            continue
        
        # Extract original body snippet (first 200 chars after frontmatter)
        parts = page['raw'].split('---', 2)
        original_body = parts[2] if len(parts) >= 3 else page['raw']
        original_snippet = original_body.strip()[:300]
        
        proposal = {
            'slug': slug,
            'title': fm.get('title', slug),
            'category': fm.get('type', ''),
            'is_entity': page['is_entity'],
            'original_snippet': original_snippet,
            'proposed_content': result,
            'status': 'pending',
            'generated_at': datetime.now().isoformat(),
        }
        
        safe_name = slug.replace('/', '_')
        prop_path = os.path.join(proposals_dir, f"{safe_name}.json")
        with open(prop_path, 'w') as f:
            json.dump(proposal, f, ensure_ascii=False, indent=2)
        
        print(f"  ✅ Proposal saved: {safe_name}.json ({len(result)} chars)")
        generated += 1
    
    print(f"\n✅ {generated} proposals generated in {proposals_dir}/")
    print(f"   打开前端「审核」视图查看和审批")


def main():
    dry_run = '--dry-run' in sys.argv
    batch_size = 5
    
    for i, arg in enumerate(sys.argv):
        if arg == '--batch' and i + 1 < len(sys.argv):
            batch_size = int(sys.argv[i + 1])
    
    category_filter = None
    for i, arg in enumerate(sys.argv):
        if arg == '--category' and i + 1 < len(sys.argv):
            category_filter = sys.argv[i + 1]
    
    # Collect TODO pages
    todo_pages = []
    for cat_dir in ALL_CONTENT_DIRS:
        d = os.path.join(BASE, cat_dir)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if not fname.endswith('.md') or fname == 'index.md':
                    continue
                fpath = os.path.join(root, fname)
                fm, body, raw = parse_page(fpath)
                
                if not has_todo(body):
                    continue
                if category_filter and fm.get('type', '') != category_filter:
                    continue
                
                rel = os.path.relpath(fpath, BASE)[:-3]  # strip .md
                todo_pages.append({
                    'path': fpath,
                    'slug': rel,
                    'fm': fm,
                    'is_entity': cat_dir in PRODUCT_DIRS,
                })
    
    if not todo_pages:
        print("✅ No TODO pages found.")
        return
    
    print(f"Found {len(todo_pages)} TODO pages. Processing up to {batch_size}...")
    
    processed = 0
    log_entries = []
    
    for page in todo_pages[:batch_size]:
        slug = page['slug']
        fm = page['fm']
        print(f"\n[{processed+1}/{batch_size}] {slug}")
        
        # Build context from concept pages + source doc
        context = read_concept_context(
            fm.get('type', ''),
            fm.get('series', ''),
            fm.get('source', '')
        )
        
        # Generate enrichment (pass full page body so AI sees existing content)
        _, page_body_raw, _ = parse_page(page['path'])
        result, error = generate_enrichment(fm, context, page['is_entity'], page_body_raw)
        
        if error:
            print(f"  ❌ Error: {error[:120]}")
            continue
        if not result:
            print(f"  ❌ Empty response")
            continue
        
        if dry_run:
            print(f"  [DRY RUN] Would write:")
            for line in result.split('\n')[:10]:
                print(f"  | {line[:100]}")
            processed += 1
            continue
        
        # Apply
        try:
            apply_enrichment(page['path'], result)
            print(f"  ✅ Enriched ({len(result)} chars)")
            log_entries.append(f"- [auto] {slug} — Level 1 编译概要自动填充")
            processed += 1
        except Exception as e:
            print(f"  ❌ Write error: {e}")
    
    if processed > 0 and not dry_run:
        append_log(log_entries)
        print(f"\n✅ {processed} pages enriched. Log updated.")
    elif dry_run:
        print(f"\n🏁 Dry run complete. {processed} pages would be updated.")


def run_improve_mode(batch_size=5, category_filter=None):
    """Level 3: AI reviews enriched pages, proposes ONE specific improvement each.
       These are real editorial suggestions that need human judgment."""
    proposals_dir = os.path.join(BASE, '_proposals')
    os.makedirs(proposals_dir, exist_ok=True)
    
    # Directories to scan for enriched pages (matching project structure)
    # PRODUCT_DIRS now imported from config
    # CONCEPT_DIRS now imported from config
    
    # Collect enriched (non-TODO) pages
    candidates = []
    for is_entity, dirs in [(True, PRODUCT_DIRS), (False, CONCEPT_DIRS)]:
        for cat_dir in dirs:
            d = os.path.join(BASE, cat_dir)
            if not os.path.isdir(d):
                continue
            for root, dirs_walk, files in sorted(os.walk(d)):
                for fname in sorted(files):
                    if not fname.endswith('.md') or fname == 'index.md':
                        continue
                    fpath = os.path.join(root, fname)
                    fm, body, raw = parse_page(fpath)
                    if has_todo(body):
                        continue  # skip TODO pages (Level 1 handles those)
                    if category_filter and fm.get('type', '') != category_filter:
                        continue
                    rel = os.path.relpath(fpath, BASE)[:-3]  # strip .md
                    slug = rel
                    prop_path = os.path.join(proposals_dir, f"{slug.replace('/', '_')}.json")
                    if os.path.exists(prop_path):
                        with open(prop_path) as f:
                            prop = json.load(f)
                        if prop.get('status') == 'pending':
                            continue
                    
                    candidates.append({
                        'path': fpath, 'slug': slug, 'fm': fm,
                        'is_entity': is_entity, 'raw': raw,
                    })
    
    if not candidates:
        print("No enriched pages to improve.")
        return
    
    print(f"Found {len(candidates)} enriched pages. Reviewing up to {batch_size}...")
    
    generated = 0
    for page in candidates[:batch_size]:
        slug = page['slug']
        fm = page['fm']
        print(f"\n[{generated+1}/{batch_size}] {slug}")
        
        # Extract body for AI review
        parts = page['raw'].split('---', 2)
        body_text = parts[2] if len(parts) >= 3 else page['raw']
        
        system_prompt = f"""你是 {cfg.brand.name} 产品知识库审阅编辑。仔细阅读以下页面，找出 **一处** 具体可改进的地方。

改进方向（只选一个最值得的）：
- 编译概要太简短或缺失关键信息 → 重写
- 缺少重要概念链接 → 在 ## 相关概念 区域追加 [[concepts/slug|显示名]]（禁止在正文中内联链接！）
- 核心卖点表述模糊 → 更具体的 FAB 描述
- 信息与 frontmatter 不一致 → 修正
- 无改进建议 → 写 "无需改进"

重要规则：所有 [[concepts/...]] 链接只能放在页面最底部的 ## 相关概念 区域。
正文（编译概要、核心卖点等）中绝对不可出现 wikilink。正文是给人读的，链接区是给机器索引的。

输出格式（严格遵守）：
```markdown
## 改进类型
[一个简短标签，如：补充概念链接 / 重写编译概要 / 修正信息 / 无需改进]

## 原文片段
[补充链接时：输出当前的 ## 相关概念 完整区域（含标题行）
 重写/修正时：输出需要修改的那段原文]

## 改进建议
[补充链接时：输出更新后的 ## 相关概念 完整区域（含标题行），新链接追加在末尾，每行一个
 重写/修正时：输出完整的修改后文本
 禁止输出 "在XX后添加" 这种描述性指令，必须给出完整结果]

补充概念链接的正确示例：
原文片段：
## 相关概念
- [[concepts/adizero-series|ADIZERO 系列]]
- [[concepts/running-competition|竞速跑鞋]]

改进建议：
## 相关概念
- [[concepts/adizero-series|ADIZERO 系列]]
- [[concepts/running-competition|竞速跑鞋]]
- [[concepts/energyrods|ENERGYRODS 能量碳柱]]

补充概念链接的错误示例（绝对禁止）：
错误：在"过度内旋"后补充链接
错误：- **双重密度泡棉**：...减少跑步时的过度内旋[[concepts/overpronation|过度内旋]]...
（链接嵌在正文中，违反规则）
```"""

        user_msg = f"""页面: {slug}
标题: {fm.get('title', '')}
品类: {fm.get('type', '')}
系列: {fm.get('series', '')}

--- PAGE CONTENT ---
{body_text[:2500]}
--- END PAGE ---

请审阅并提出一处改进建议。如果页面质量已经很好，写"无需改进"。
只输出 ```markdown 代码块。"""

        if not DEEPSEEK_API_KEY:
            print("  ❌ DEEPSEEK_API_KEY not set")
            continue
        
        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500,
                },
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                timeout=30,
            )
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            
            m = re.search(r'```markdown\s*\n(.*?)```', text, re.DOTALL)
            result = m.group(1).strip() if m else text
            
            # Skip if no improvement needed
            if '无需改进' in result:
                print(f"  ✅ 无需改进")
                continue
            
            # Parse AI output to extract original_fragment and suggested_change
            # for precise string replacement during approval
            orig_frag = ""
            sugg_change = ""
            frag_m = re.search(r'##\s*原文片段\s*\n(.*?)(?=\n##\s|\Z)', result, re.DOTALL)
            if frag_m:
                orig_frag = frag_m.group(1).strip()
            sugg_m = re.search(r'##\s*改进建议\s*\n(.*?)(?=\n##\s|\Z)', result, re.DOTALL)
            if sugg_m:
                sugg_change = sugg_m.group(1).strip()
            # If parsing failed, skip — don't create a broken proposal
            if not orig_frag or not sugg_change:
                print(f"  ⚠️  Could not parse fragment/suggestion from AI output, skipping")
                continue
            
            proposal = {
                'slug': slug,
                'title': fm.get('title', slug),
                'category': fm.get('type', ''),
                'is_entity': page['is_entity'],
                'original_snippet': body_text[:400],
                'proposed_content': result,
                'status': 'pending',
                'generated_at': datetime.now().isoformat(),
                'source': 'improve',
                'original_fragment': orig_frag,
                'suggested_change': sugg_change,
            }
            
            safe_name = slug.replace('/', '_')
            prop_path = os.path.join(proposals_dir, f"{safe_name}.json")
            with open(prop_path, 'w') as f:
                json.dump(proposal, f, ensure_ascii=False, indent=2)
            
            print(f"  ✅ Proposal: {result.split(chr(10))[0][:80]}...")
            generated += 1
            
        except Exception as e:
            print(f"  ❌ Error: {str(e)[:120]}")
    
    print(f"\n✅ {generated} improvement proposals generated.")


def run_concept_proposals():
    """Generate concept page proposals for orphan tags found in graph-data.json.
    Uses DeepSeek to create a concept page for each tag without a matching concept file."""
    import json
    from datetime import datetime

    proposals_dir = os.path.join(BASE, '_proposals')
    os.makedirs(proposals_dir, exist_ok=True)

    # Collect orphan tags (same logic as consistency check)
    graph_path = os.path.join(BASE, 'graph-data.json')
    if not os.path.exists(graph_path):
        print("❌ graph-data.json not found — run regenerate-graph.py first")
        return

    gd = json.load(open(graph_path))
    all_tags = set()
    for n in gd.get('nodes', []):
        for t in n.get('tags', []):
            all_tags.add(t)

    # CONCEPT_DIRS now imported from config
    concept_slugs = set()
    for concept_dir in CONCEPT_DIRS:
        cd = os.path.join(BASE, concept_dir)
        if not os.path.isdir(cd): continue
        for root, dirs, files in os.walk(cd):
            for fn in files:
                if fn.endswith('.md') and fn != 'index.md':
                    concept_slugs.add(fn[:-3])

    orphans = []
    tags_with_products = {}  # tag → [product names for context]
    for n in gd.get('nodes', []):
        for t in n.get('tags', []):
            if t not in tags_with_products:
                tags_with_products[t] = []
            tags_with_products[t].append(n.get('title', n['id'].split('/')[-1]))

    for tag in sorted(all_tags):
        if ':' in tag:
            dim, val = tag.split(':', 1)
            tag_slug = val.strip().lower().replace(' ', '-').replace('·', '-')
        else:
            dim, tag_slug = 'tag', tag.lower().replace(' ', '-')
        if tag_slug and tag_slug not in concept_slugs:
            if not any(tag_slug in c or c in tag_slug for c in concept_slugs):
                # Determine target directory
                target_dir = TECH_CONCEPT_DIR if dim == '特性' else SERIES_CONCEPT_DIR
                orphans.append({
                    'tag': tag, 'slug': tag_slug, 'dim': dim,
                    'val': val.strip() if ':' in tag else tag,
                    'target_dir': target_dir,
                    'products': tags_with_products.get(tag, [])[:5]
                })

    if not orphans:
        print("✅ No orphan tags — all tags have concept pages.")
        return

    print(f"Found {len(orphans)} orphan tags. Generating concept page proposals...\n")

    generated = 0
    for ot in orphans:
        safe_name = ot['target_dir'] + '_' + ot['slug']
        prop_path = os.path.join(proposals_dir, f"{safe_name}.json")

        # Skip if proposal already exists
        if os.path.exists(prop_path):
            try:
                ep = json.load(open(prop_path))
                if ep.get('status') == 'pending':
                    print(f"  ⏭  {ot['tag']}: 已有待审批提案")
                    continue
            except: pass

        # Collect source material from product pages that use this tag
        source_context = ''
        tag_val = ot['val'].lower()
        for n in gd.get('nodes', []):
            if ot['tag'] in n.get('tags', []):
                fpath = os.path.join(BASE, n['id'] + '.md')
                if os.path.exists(fpath):
                    try:
                        with open(fpath) as f:
                            content = f.read()
                        lines = content.split('\n')
                        relevant = []
                        for i, line in enumerate(lines):
                            if tag_val in line.lower():
                                start = max(0, i-1)
                                end = min(len(lines), i+3)
                                ctx = '\n'.join(lines[start:end]).strip()
                                if ctx and ctx not in relevant:
                                    relevant.append(ctx)
                        if relevant:
                            source_context += f'\n### 来自 {n["title"]} ({n["id"]})\n' + '\n---\n'.join(relevant[:5])
                    except: pass
        if not source_context:
            source_context = f'（以下产品使用了此标签：{product_ctx}，但未能提取到相关原文段落，请基于标签含义撰写）'

        product_ctx = ', '.join(ot['products'][:5]) if ot['products'] else '（新标签）'
        prompt = (
            f"为 adidas 产品知识库创建一个概念页面，解释「{ot['val']}」这个概念。\n"
            f"概念维度：{ot['dim']}\n"
            f"\n"
            f"=== 知识库原始材料（请严格基于以下内容撰写，不要添加外部知识）===\n"
            f"{source_context[:4000]}\n"
            f"=== 材料结束 ===\n"
            f"\n"
            f"目标路径：{ot['target_dir']}/{ot['slug']}.md\n"
            f"\n"
            f"要求：\n"
            f"1. 直接输出 markdown 正文，开头就是 --- frontmatter，绝对不要用代码块包裹\n"
            f"2. frontmatter 至少包含：title, type, description\n"
            f"3. 正文包含：概念定义、技术原理/设计特点、代表产品（列出原始材料中提及的产品）、适用场景\n"
            f"4. 只基于原始材料撰写，不要编造信息；材料未提及的特性不要写\n"
            f"5. 用中文撰写\n"
            f"6. 只输出概念页内容，不要解释"
        )

        try:
            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3, "max_tokens": 2000
                },
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                timeout=30
            )
            if resp.status_code != 200:
                print(f"  ❌ {ot['tag']}: API error {resp.status_code}")
                continue
            content = resp.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"  ❌ {ot['tag']}: {str(e)[:100]}")
            continue

        proposal = {
            'slug': f"{ot['target_dir']}/{ot['slug']}",
            'title': ot['val'],
            'action': 'create',
            'is_entity': False,
            'proposed_content': content,
            'change_summary': f"为孤立标签「{ot['tag']}」自动生成概念页。关联产品：{product_ctx}",
            'status': 'pending',
            'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'source': 'concept-proposal',
            'source_tags': [ot['tag']],
            'target_dir': ot['target_dir'],
        }
        with open(prop_path, 'w') as f:
            json.dump(proposal, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 提案: {safe_name}.json — {ot['val']}")
        generated += 1

    print(f"\n✅ {generated} concept proposals generated in _proposals/")


def run_fix_dataview():
    """Replace dataview query blocks in concept pages with real [[wikilinks]] to products."""
    from collections import defaultdict

    # PRODUCT_DIRS now imported from config
    # CONCEPT_DIRS now imported from config

    # Step 1: Scan all product pages → build concept → products map
    print("Scanning product pages for concept wikilinks...")
    concept_products = defaultdict(set)
    for pcat in PRODUCT_DIRS:
        pd = os.path.join(BASE, pcat)
        if not os.path.isdir(pd): continue
        for root, dirs, files in os.walk(pd):
            for fn in files:
                if not fn.endswith('.md') or fn == 'index.md': continue
                ppath = os.path.join(root, fn)
                with open(ppath) as f:
                    body = f.read()
                pslug = os.path.relpath(ppath, BASE)[:-3]
                for m in re.finditer(r'\[\[(科技/|系列/)([^\]]+)\]\]', body):
                    concept_ref = m.group(0)[2:-2]
                    concept_products[concept_ref].add(pslug)
    print(f"  Found {len(concept_products)} concept references in products")

    # Step 2: For each concept page, add/update wikilink product list
    fixed = 0
    skipped = 0
    for concept_dir in CONCEPT_DIRS:
        cd = os.path.join(BASE, concept_dir)
        if not os.path.isdir(cd): continue
        for root, dirs, files in os.walk(cd):
            for fn in sorted(files):
                if not fn.endswith('.md') or fn == 'index.md': continue
                fpath = os.path.join(root, fn)
                concept_slug = os.path.relpath(fpath, BASE)[:-3]
                with open(fpath) as f:
                    body = f.read()

                products = sorted(concept_products.get(concept_slug, set()))
                if not products:
                    continue

                # Build wikilink list
                product_links = '\n'.join(f'- [[{p}]]' for p in products[:100])
                if len(products) > 100:
                    product_links += f'\n- ... 还有 {len(products) - 100} 个产品'

                new_body = body

                # Case 1: Replace dataview block
                if 'dataview' in body.lower():
                    new_body = re.sub(
                        r'```dataview\s*\n.*?\n```',
                        product_links,
                        body,
                        flags=re.DOTALL
                    )

                # Case 2: No concept list at all — add new ## 相关产品 section
                elif '## 相关产品' not in body and '## 代表产品' not in body:
                    new_body = body.rstrip() + f'\n\n## 相关产品\n\n{product_links}\n'

                # Case 3: Has ## 相关产品 or ## 代表产品 but no product wikilinks — append
                elif not re.search(r'\[\[(?:运动表现|三叶草|轻运动)[^\]]+\]\]', body):
                    new_body = body.rstrip() + f'\n\n{product_links}\n'
                if new_body != body:
                    with open(fpath, 'w') as f:
                        f.write(new_body)
                    fixed += 1
                    print(f"  ✅ {concept_slug}: {len(products)} products")

    print(f"\n✅ Fixed {fixed} concept pages, {skipped} skipped")


if __name__ == '__main__':
    if '--fix-dataview' in sys.argv:
        run_fix_dataview()
    elif '--check' in sys.argv or '--find-orphan-tags' in sys.argv:
        run_consistency_check()
    elif '--improve-concepts' in sys.argv:
        run_concept_proposals()
    elif '--improve' in sys.argv:
        batch = 5
        cat = None
        for i, arg in enumerate(sys.argv):
            if arg == '--batch' and i + 1 < len(sys.argv):
                batch = int(sys.argv[i + 1])
            if arg == '--category' and i + 1 < len(sys.argv):
                cat = sys.argv[i + 1]
        run_improve_mode(batch, cat)
    elif '--review' in sys.argv:
        batch = 5
        cat = None
        for i, arg in enumerate(sys.argv):
            if arg == '--batch' and i + 1 < len(sys.argv):
                batch = int(sys.argv[i + 1])
            if arg == '--category' and i + 1 < len(sys.argv):
                cat = sys.argv[i + 1]
        run_review_mode(batch, cat)
    else:
        main()
