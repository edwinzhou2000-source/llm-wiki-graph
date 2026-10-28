#!/usr/bin/env python3
"""
Automated wikilink builder for the LLM-Wiki knowledge base.
Creates three types of links:
  1. Product ↔ Concept (based on frontmatter series/attributes tags)
  2. Concept ↔ Concept (expert-crafted + body-text co-mentions)
  3. Product ↔ Product (shared tags within same category)

Run:  python3 _link_concepts.py [--dry-run]
"""
import os, re, sys
from config import cfg, KB_ROOT, PRODUCT_DIRS, CONCEPT_DIRS, NON_TECH_BLACKLIST, TECH_CONCEPT_DIR, SERIES_CONCEPT_DIR

BASE = KB_ROOT

# Category directories — driven by kb-config.yml role field
# PRODUCT_DIRS / CONCEPT_DIRS are computed by config.py from category roles

# ── Expert-crafted concept→concept links (based on actual page content) ──
EXPERT_LINKS = {
    # 科技 concepts — cross-reference based on body text mentions
    'cloudfoam':            ['lightstrike', 'eva'],
    'lightstrike':          ['cloudfoam', 'eva', 'lightweight'],
    'eva':                  ['cloudfoam', 'lightstrike', 'lightweight'],
    'lightweight':          ['lightstrike', 'eva'],
    'loose-fit':            ['regular-fit'],
    'regular-fit':          ['loose-fit'],
    'reflective-design':    ['lightweight', '三条纹'],
    'wind-resistant-fabric': ['dwr'],
    'dwr':                  ['wind-resistant-fabric'],
    # 科技 Chinese
    '三条纹':               ['伞兵裤', '弹力腰'],
    '伞兵裤':               ['弹力腰', '抽绳裤脚', '三条纹'],
    '弹力腰':               ['抽绳裤脚', '伞兵裤', '三条纹'],
    '抽绳裤脚':             ['弹力腰', '伞兵裤', '三条纹'],
    # 系列 concepts
    'barreda':              ['vl-court', '轻运动'],
    'vl-court':             ['barreda', 'grand-court', '轻运动'],
    'grand-court':          ['vl-court', '轻运动'],
    'sportswear':           ['轻运动', 'kids', '三条纹'],
    'kids':                 ['sportswear', 'cloudfoam', 'lightstrike', 'eva', 'dwr'],
    '三叶草':               ['轻运动', 'gfx-story'],
    '轻运动':               ['sportswear', '三叶草', 'barreda', 'vl-court', 'grand-court'],
    'gfx-story':            ['三叶草'],
}

DRY_RUN = '--dry-run' in sys.argv

# ── Helpers ──

def parse_frontmatter(path):
    """Return (frontmatter_dict, body_str)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except:
        return {}, ''
    if not text.startswith('---'):
        return {}, text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return {}, text
    fm = {}
    fm_text = parts[1]
    body = parts[2]
    # Simple YAML parser for flat keys + inline lists
    lines = fm_text.strip().split('\n')
    key = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if ':' in stripped and not stripped.startswith('-'):
            k, v = stripped.split(':', 1)
            key = k.strip()
            val = v.strip()
            if val == '':
                fm[key] = []  # multi-line list
            elif val.startswith('[') and val.endswith(']'):
                # inline list: [a, b, c]
                inner = val[1:-1].strip()
                fm[key] = [x.strip().strip("'\"") for x in inner.split(',') if x.strip()]
            else:
                fm[key] = val.strip("'\"")
        elif stripped.startswith('-') and key:
            val = stripped[1:].strip().strip("'\"")
            if key not in fm:
                fm[key] = []
            fm[key].append(val)
    return fm, body


def get_existing_links(body):
    """Extract wikilink targets from body text."""
    return set(re.findall(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', body))


def add_wikilinks_to_body(body, new_links):
    """Append wikilinks to body under '## 相关链接' section.
    Returns (new_body, count_added)."""
    existing = get_existing_links(body)
    links_to_add = [l for l in new_links if l not in existing]
    if not links_to_add:
        return body, 0

    link_lines = '\n'.join(f'- [[{l}]]' for l in links_to_add)
    if '## 相关链接' in body:
        new_body = body.rstrip() + '\n' + link_lines + '\n'
    else:
        new_body = body.rstrip() + '\n\n## 相关链接\n\n' + link_lines + '\n'
    return new_body, len(links_to_add)


def inject_concept_tags(full_content, new_links):
    """Add concept tags to page frontmatter so Dataview queries work.
    E.g. when a product links to [[科技/climacool]], add '科技/climacool' to its tags.
    Returns modified full_content."""
    import re as _re
    # Only process links to 科技/ or 系列/ concept pages
    concept_tags = set()
    for link in new_links:
        if link.startswith(TECH_CONCEPT_DIR + '/') or link.startswith(SERIES_CONCEPT_DIR + '/'):
            concept_tags.add(link)

    if not concept_tags:
        return full_content

    fm_match = _re.match(r'^(---\s*\n.*?\n---)', full_content, _re.DOTALL)
    if not fm_match:
        return full_content

    original_fm = fm_match.group(1)
    body = full_content[fm_match.end():]

    # Extract existing tags
    existing_tags = set()
    tag_match = _re.search(r'^tags:\s*\[(.+?)\]', original_fm, _re.MULTILINE)
    if tag_match:
        for t in tag_match.group(1).split(','):
            t = t.strip().strip("'\"")
            if t:
                existing_tags.add(t)
    else:
        # Check for multi-line tags
        in_tags = False
        for line in original_fm.split('\n'):
            stripped = line.strip()
            if stripped.startswith('tags:'):
                in_tags = True
                val = stripped.split(':', 1)[1].strip()
                if val and val != '[]':
                    existing_tags.add(val.strip("'\""))
                continue
            if in_tags:
                if stripped.startswith('-'):
                    existing_tags.add(stripped[1:].strip().strip("'\""))
                elif ':' in stripped and not stripped.startswith('-'):
                    in_tags = False

    # Add new concept tags
    new_tags = concept_tags - existing_tags
    if not new_tags:
        return full_content

    all_tags = sorted(existing_tags | concept_tags)

    # Build new tags line(s)
    if len(all_tags) <= 5:
        tags_str = ', '.join(all_tags)
        new_tags_line = f'tags: [{tags_str}]'
    else:
        tags_lines = ['tags:'] + [f'  - {t}' for t in sorted(all_tags)]
        new_tags_line = '\n'.join(tags_lines)

    # Replace or insert tags into frontmatter
    if tag_match or in_tags:
        # Replace existing tags section
        if tag_match:
            new_fm = original_fm[:tag_match.start()] + new_tags_line + original_fm[tag_match.end():]
        else:
            # Multi-line tags removal + re-insert is complex; simplify by replacing entire FM
            new_fm = _re.sub(r'^tags:.*?(\n(?:  - .*?\n)*)?', new_tags_line + '\n', original_fm, flags=_re.MULTILINE)
    else:
        # No tags field — insert before the closing ---
        new_fm = original_fm[:-4] + '\n' + new_tags_line + '\n---'

    return new_fm + body


def slug_for(rel_path):
    """Convert relative path to slug (strip .md prefix)."""
    if rel_path.endswith('.md'):
        rel_path = rel_path[:-3]
    return rel_path


# ── Index all pages ──

def build_index():
    """Scan all KB pages and build a lookup index.
    Returns {
        'products': {slug: {path, title, series, attributes, brand, category}},
        'concepts': {slug: {path, title, category, base_dir}},
        'slug_to_name': {slug: title},   # for display
        'attr_to_products': {attr_value: [slug, ...]},
        'series_to_products': {series_value: [slug, ...]},
    }
    """
    products = {}
    concepts = {}
    slug_to_name = {}
    attr_to_products = {}
    series_to_products = {}

    # Scan product directories
    for cat in PRODUCT_DIRS:
        d = os.path.join(BASE, cat)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if not fname.endswith('.md') or fname == 'index.md':
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, BASE)
                slug = slug_for(rel)
                fm, body = parse_frontmatter(fpath)
                title = fm.get('title', slug.split('/')[-1])
                slug_to_name[slug] = title

                series = fm.get('series', [])
                attrs = fm.get('attributes', [])
                brand = fm.get('brand', '')
                category = fm.get('type', '')

                products[slug] = {
                    'path': fpath, 'title': title,
                    'series': series if isinstance(series, list) else [series],
                    'attributes': attrs if isinstance(attrs, list) else [attrs],
                    'brand': brand, 'category': category,
                    'body': body,  # for body-text concept scanning
                }

                for s in products[slug]['series']:
                    sv = s.lower().strip()
                    series_to_products.setdefault(sv, []).append(slug)
                for a in products[slug]['attributes']:
                    av = a.lower().strip()
                    attr_to_products.setdefault(av, []).append(slug)

    # Scan concept directories (including subdirectories)
    for cat in CONCEPT_DIRS:
        d = os.path.join(BASE, cat)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if not fname.endswith('.md') or fname == 'index.md':
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, BASE)
                slug = slug_for(rel)
                fm, body = parse_frontmatter(fpath)
                title = fm.get('title', slug.split('/')[-1])
                slug_to_name[slug] = title
                concepts[slug] = {
                    'path': fpath, 'title': title,
                    'category': cat,
                }

    return {
        'products': products,
        'concepts': concepts,
        'slug_to_name': slug_to_name,
        'attr_to_products': attr_to_products,
        'series_to_products': series_to_products,
    }


# ── Link building ──

def _normalize(s):
    """Normalize a string for fuzzy matching: lowercase, remove spaces/hyphens/underscores."""
    return s.lower().replace(' ', '').replace('-', '').replace('_', '')


def build_product_concept_links(index):
    """
    For each product: match attributes → 科技/ pages, series → 系列/ pages.
    Uses three-tier matching:
      1. Exact filename stem match
      2. Normalized substring match (e.g. '轻量化' ↔ concept 'lightweight')
      3. Path-based inference (product path segments → related concept pages)
    Returns list of (product_slug, concept_slug).
    """
    links = set()
    concepts = index['concepts']

    # Pre-build normalized lookup for concepts
    norm_concepts = {}  # normalized_stem → [(slug, category)]
    for cslug, cinfo in concepts.items():
        cstem = cslug.split('/')[-1]
        nstem = _normalize(cstem)
        norm_concepts.setdefault(nstem, []).append((cslug, cinfo['category']))

    for pslug, pinfo in index['products'].items():
        # ── Tier 1+2: attributes → 科技/ (product→concept only, no reverse) ──
        for attr in pinfo['attributes']:
            attr_norm = _normalize(attr)
            matched = False

            # Tier 1: exact match
            for cslug, cinfo in concepts.items():
                if cinfo['category'] != TECH_CONCEPT_DIR:
                    continue
                cstem = cslug.split('/')[-1].lower()
                if cstem == attr.lower().strip().replace(' ', '-'):
                    links.add((pslug, cslug))
                    matched = True

            if matched:
                continue

            # Tier 2: normalized substring match
            for nstem, candidates in norm_concepts.items():
                if not candidates:
                    continue
                tech_candidates = [(s, c) for s, c in candidates if c == TECH_CONCEPT_DIR]
                if not tech_candidates:
                    continue
                if len(nstem) < 3:
                    continue
                if nstem in attr_norm or attr_norm in nstem:
                    for cslug, _ in tech_candidates:
                        links.add((pslug, cslug))
                    matched = True

        # ── Tier 1+2: series → 系列/ (product→concept only, no reverse) ──
        for ser in pinfo['series']:
            ser_norm = _normalize(ser)
            matched = False

            # Tier 1: exact match
            ser_slug = ser.lower().strip().replace(' ', '-')
            for cslug, cinfo in concepts.items():
                if cinfo['category'] != SERIES_CONCEPT_DIR:
                    continue
                cstem = cslug.split('/')[-1].lower()
                if cstem == ser_slug:
                    links.add((pslug, cslug))
                    matched = True

            if matched:
                continue

            # Tier 2: normalized substring match
            for nstem, candidates in norm_concepts.items():
                if not candidates:
                    continue
                series_candidates = [(s, c) for s, c in candidates if c == SERIES_CONCEPT_DIR]
                if not series_candidates:
                    continue
                if len(nstem) < 3 or len(ser_norm) < 3:
                    continue
                if nstem in ser_norm or ser_norm in nstem:
                    for cslug, _ in series_candidates:
                        links.add((pslug, cslug))
                    matched = True

        # ── Tier 3: path-based inference (product→concept only) ──
        # Match whole path segments exactly against concept stems.
        # E.g. 运动表现产品/鞋/跑步/竞速 → matches 系列/跑步 (stem=跑步, part=跑步)
        # Does NOT match substrings — 训练 won't match true-purpose训练系列.
        path_parts = [p.lower() for p in pslug.split('/')]
        for cslug, cinfo in concepts.items():
            cstem = cslug.split('/')[-1].lower()
            cstem_norm = _normalize(cstem)
            if len(cstem_norm) < 2:
                continue
            for part in path_parts:
                # Only match when the concept stem EQUALS a path segment
                # (not substring), OR when the path segment equals the concept stem
                if cstem == part or cstem_norm == _normalize(part):
                    if len(cstem_norm) >= 2:
                        links.add((pslug, cslug))
                        break

        # ── Tier 4: body text scan (tech concepts only + note filtering) ──
        # Scan product body for technology concept names that weren't captured
        # in frontmatter attributes. Filters out mentions in notes/disclaimers.
        body_lower = pinfo.get('body', '').lower()
        if body_lower:
            # Strip note/disclaimer lines before scanning
            # Remove lines starting with > (blockquotes, often notes)
            # Remove lines containing disclaimer keywords
            clean_body_lines = []
            skip_keywords = ['疑为', '错误', '免责', '不是', '并非']
            for line in body_lower.split('\n'):
                stripped = line.strip()
                if stripped.startswith('>'):
                    continue
                if any(kw in stripped for kw in skip_keywords):
                    continue
                clean_body_lines.append(line)
            clean_body = '\n'.join(clean_body_lines)

            # Build once: technology concept title/stem → slug
            if not hasattr(build_product_concept_links, '_body_index'):
                _body_lookup = {}
                for cslug, cinfo in concepts.items():
                    if cinfo['category'] != TECH_CONCEPT_DIR:  # only tech concepts
                        continue
                    cstem = cslug.split('/')[-1].lower()
                    ctitle = cinfo.get('title', '').lower()
                    for term in {cstem, ctitle}:
                        if len(term) >= 3:
                            _body_lookup.setdefault(term, []).append(cslug)
                build_product_concept_links._body_terms = sorted(_body_lookup.keys(), key=len, reverse=True)
                build_product_concept_links._body_index = _body_lookup

            if hasattr(build_product_concept_links, '_body_index'):
                for term in build_product_concept_links._body_terms:
                    if term in clean_body:
                        for cslug in build_product_concept_links._body_index[term]:
                            links.add((pslug, cslug))

    return links


def build_concept_concept_links(index):
    """
    Expert-crafted links between concept pages (within 科技/ and 系列/).
    Returns list of (concept_slug_a, concept_slug_b).
    """
    links = set()
    concepts = index['concepts']

    for source_stem, target_stems in EXPERT_LINKS.items():
        # Find the full slug for source
        source_slug = None
        for cslug in concepts:
            if cslug.split('/')[-1] == source_stem:
                source_slug = cslug
                break
        if not source_slug:
            continue

        for tstem in target_stems:
            target_slug = None
            for cslug in concepts:
                if cslug.split('/')[-1] == tstem:
                    target_slug = cslug
                    break
            if target_slug and target_slug != source_slug:
                links.add((source_slug, target_slug))
                links.add((target_slug, source_slug))

    return links


def build_product_product_links(index):
    """
    Product → Product links are DISABLED by design decision (2026-07-29).
    Product-to-product links should only exist for genuine cross-sell / bundle
    relationships (e.g. "this jacket goes with these pants"), not for
    tag-driven auto-linking. All such links must be manually curated.

    Keep this function as a no-op placeholder so callers don't break.
    """
    return set()


# ── Main ──

def main():
    print("🔗 LLM-Wiki 自动链接构建器")
    print(f"   KB 根目录: {BASE}")
    print()

    index = build_index()
    print(f"   产品页: {len(index['products'])}  概念页: {len(index['concepts'])}")
    print()

    # Build all link sets
    pc_links = build_product_concept_links(index)
    cc_links = build_concept_concept_links(index)
    pp_links = build_product_product_links(index)

    # Merge all links, group by source page (product→concept only, no cap)
    all_links = pc_links | cc_links | pp_links
    source_to_targets = {}
    for src, tgt in all_links:
        source_to_targets.setdefault(src, []).append(tgt)

    # Stats
    print(f"   产品↔概念: {len(pc_links)}  概念↔概念: {len(cc_links)}  产品↔产品: {len(pp_links)}")
    print(f"   总链接: {len(all_links)}  (涉及 {len(source_to_targets)} 个页面)")
    print()

    # Apply
    total_added = 0
    pages_modified = 0

    for src_slug, targets in sorted(source_to_targets.items()):
        # Determine file path
        if src_slug in index['products']:
            fpath = index['products'][src_slug]['path']
        elif src_slug in index['concepts']:
            fpath = index['concepts'][src_slug]['path']
        else:
            print(f"  ⚠ 未知页面: {src_slug}")
            continue

        with open(fpath, 'r', encoding='utf-8') as f:
            original = f.read()

        new_body, n = add_wikilinks_to_body(original, targets)
        if n == 0:
            continue

        # Inject concept tags into frontmatter so Dataview queries work
        new_body = inject_concept_tags(new_body, targets)

        if not DRY_RUN:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(new_body)

        total_added += n
        pages_modified += 1
        name = index['slug_to_name'].get(src_slug, src_slug)
        print(f"  ✚ {src_slug:45s} +{n:2d} links → {name[:30]}")

    print()
    print(f"{'='*60}")
    print(f"总计: {total_added} 个 wikilink 添加到 {pages_modified} 个页面")
    print(f"  产品↔概念: {len(pc_links)} | 概念↔概念: {len(cc_links)} | 产品↔产品: {len(pp_links)}")
    if DRY_RUN:
        print(f"  ⚠️  DRY RUN — 使用 python3 _link_concepts.py 执行。")
    else:
        print(f"  ✅ 已写入磁盘。运行 python3 regenerate-graph.py 重建图谱。")

    # ── Post-link validation: flag suspicious product→concept links ──
    suspicious = 0
    for pslug, pinfo in index['products'].items():
        product_series = {s.lower().strip() for s in pinfo.get('series', [])}
        for cslug in source_to_targets.get(pslug, []):
            cinfo = index['concepts'].get(cslug, {})
            if cinfo.get('category') != SERIES_CONCEPT_DIR:
                continue
            cstem = cslug.split('/')[-1].lower()
            # Flag if: concept is a series, but the product's series list
            # doesn't contain this concept name or any overlap
            body = pinfo.get('body', '').lower()
            # Strip notes for validation
            clean = '\n'.join(l for l in body.split('\n')
                             if not l.strip().startswith('>') and '疑为' not in l)
            if cstem not in clean and not any(cstem in s or s in cstem for s in product_series):
                if suspicious < 10:
                    print(f"  ⚠️  可疑: {pslug} → {cslug} (产品 series={product_series}, 正文未提及)")
                suspicious += 1
    if suspicious:
        print(f"\n⚠️  发现 {suspicious} 个可疑的产品→系列链接（产品 series 和正文均未提及该概念）")

    # ── Auto-stub: detect missing tech concept pages ──
    if not DRY_RUN:
        _auto_stub_missing_tech(index)


def _auto_stub_missing_tech(index, min_products=3):
    """Detect technology names referenced by products that have no 科技/ concept page,
    and auto-create stub pages for the most frequently referenced ones."""
    from collections import Counter
    import re

    # Blacklist from kb-config.yml taxonomy.non_tech_blacklist

    # Get existing concept stems
    existing_stems = set()
    for cslug in index['concepts']:
        if cslug.startswith(TECH_CONCEPT_DIR + '/'):
            existing_stems.add(cslug.split('/')[-1].lower())

    # Count tech-like attribute values across all products
    attr_counter = Counter()
    attr_examples = {}  # attr → example product slug
    for pslug, pinfo in index['products'].items():
        for attr in pinfo.get('attributes', []):
            a = str(attr).lower().strip()
            # Only auto-stub English tech names (alphanumeric + hyphens, ≥3 chars)
            # Skip mixed Chinese-English and pure Chinese — too ambiguous to auto-classify
            if not re.match(r'^[a-z][a-z0-9\-]{2,}$', a):
                continue
            if a in NON_TECH_BLACKLIST:
                continue
            if a in existing_stems:
                continue
            attr_counter[a] += 1
            if a not in attr_examples:
                attr_examples[a] = pslug

    # Create stubs for frequently referenced tech names
    tech_dir = os.path.join(BASE, TECH_CONCEPT_DIR)
    os.makedirs(tech_dir, exist_ok=True)
    created = 0

    for attr, count in attr_counter.most_common(50):
        if count < min_products:
            break
        if attr in existing_stems:
            continue

        # Generate a readable title: capitalize, replace hyphens with spaces
        title = attr.upper().replace('-', ' ')

        stub_content = f"""---
title: {title}
type: 科技
tags:
  - 科技/{attr}
description: {title} 技术概念（自动生成 stub，待补全）。
created: {__import__('time').strftime('%Y-%m-%d')}
updated: {__import__('time').strftime('%Y-%m-%d')}
---

# {title}

> **TODO**: 自动创建的 stub。{count} 个产品引用了此技术，但概念页尚未编写。
> 示例产品：{attr_examples.get(attr, '')}

## 相关产品

```dataview
LIST FROM #科技/{attr}
SORT file.name ASC
```
"""
        filepath = os.path.join(tech_dir, f'{attr}.md')
        if os.path.exists(filepath):
            continue

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(stub_content)
        created += 1
        print(f"  📄 自动创建概念页: 科技/{attr}.md（{count} 个产品引用）")
        existing_stems.add(attr)  # prevent duplicates in this run

    if created:
        print(f"\n📄 自动创建了 {created} 个缺失的技术概念页 stub。重跑 _link_concepts.py 即可生效。")
    else:
        print("✅ 所有常用技术名均有对应概念页。")

if __name__ == '__main__':
    main()
