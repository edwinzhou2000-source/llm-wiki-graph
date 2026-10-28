#!/usr/bin/env python3
"""Tag taxonomy validator — checks all pages against TAG_TAXONOMY.md."""

import re, sys, os, yaml
from collections import defaultdict
from pathlib import Path
from config import cfg, KB_ROOT, ALL_CONTENT_DIRS, PRODUCT_DIRS, CONCEPT_DIRS, CLINICAL_DIRS, BRIDGE_DIRS

BASE = Path(KB_ROOT)
TAXONOMY = BASE / "_meta/TAG_TAXONOMY.md"

# ── Parse TAG_TAXONOMY.md into allowed values ──
def parse_taxonomy(path):
    """Extract all allowed tag values per dimension from TAG_TAXONOMY.md."""
    if not path.exists():
        return None, "TAG_TAXONOMY.md not found"

    text = path.read_text()
    dimensions = defaultdict(set)
    current_dim = None
    # Map dimension header text to canonical key name
    dim_name_map = {
        '品牌': 'brand', '品牌 (brand)': 'brand',
        '品类': 'category', '品类 (category)': 'category',
        '系列': 'series', '系列 (series)': 'series',
        '产品类型': 'product_type', '产品类型 (product_type)': 'product_type',
        '定位': 'position', '定位 (position)': 'position',
        '特性标签': 'attributes', '特性标签 (attributes)': 'attributes',
    }

    for line in text.split('\n'):
        # Dimension header: ## 维度X：名称
        dim_match = re.match(r'^##\s+维度.+?[：:]\s*(.+)', line)
        if dim_match:
            raw = dim_match.group(1).strip()
            current_dim = dim_name_map.get(raw, raw)
            continue

        if not current_dim:
            continue

        # Sub-section header: ### name — skip, values follow
        if re.match(r'^###\s+', line):
            continue

        stripped = line.strip()
        if not stripped:
            continue

        # Format 1: - **VALUE** — description
        bold_match = re.match(r'^-\s+\*\*(.+?)\*\*', stripped)
        if bold_match:
            dimensions[current_dim].add(bold_match.group(1).strip())
            continue

        # Format 2: - VALUE — description (no bold, e.g. 系列, 定位)
        # Use em-dash or en-dash as delimiter (not plain hyphen — values may contain hyphens)
        dash_val = re.match(r'^-\s+(\S.+?)\s*[—–]', stripped)
        if dash_val:
            dimensions[current_dim].add(dash_val.group(1).strip())
            continue

        # Format 3: Pipe-separated values: VALUE | VALUE | VALUE
        if '|' in stripped and not stripped.startswith('#'):
            parts = [p.strip() for p in stripped.split('|')]
            for p in parts:
                p = p.strip()
                if p and len(p) >= 1:
                    dimensions[current_dim].add(p)

    return dict(dimensions), None


# ── Check which dimension a tag belongs to ──
def classify_tag(tag, taxonomy):
    """Return the dimension(s) a tag belongs to, or None if invalid."""
    dims = []
    for dim, values in taxonomy.items():
        if tag in values:
            dims.append(dim)
    return dims if dims else None


# ── Validate all pages ──
def validate(taxonomy):
    errors = []
    warnings = []
    pages_ok = 0
    pages_warn = 0
    pages_err = 0

    # Scan all .md files in new directory structure
    all_md = []
    for scan_dir in ALL_CONTENT_DIRS:
        if os.path.isdir(os.path.join(BASE, scan_dir)):
            all_md.extend(sorted(Path(BASE).glob(f"{scan_dir}/**/*.md")))
    for md in all_md:
        rel = str(md.relative_to(BASE))
        
        # Skip index.md files (navigation pages, no frontmatter required)
        if md.name == 'index.md':
            continue
        
        content = md.read_text()
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            errors.append(f"{rel}: no valid frontmatter")
            pages_err += 1
            continue

        fm = fm_match.group(1)
        page_errors = []

        # Determine page role
        is_product = any(rel.startswith(d + '/') for d in PRODUCT_DIRS)
        is_concept = any(rel.startswith(d + '/') for d in CONCEPT_DIRS)
        is_clinical = any(rel.startswith(d + '/') for d in CLINICAL_DIRS)
        is_bridge = any(rel.startswith(d + '/') for d in BRIDGE_DIRS)

        # Check brand (only required for product pages)
        if is_product:
            brand = re.search(r'^brand:\s*(.+)$', fm, re.MULTILINE)
            if not brand:
                page_errors.append("  missing brand")
            elif 'brand' in taxonomy and brand.group(1).strip() not in taxonomy.get('brand', set()):
                page_errors.append(f"  brand '{brand.group(1).strip()}' not in taxonomy")

        # Series validation
        ser = re.search(r'^series:\s*\[(.+)\]', fm, re.MULTILINE)
        if ser:
            for s in ser.group(1).split(','):
                s = s.strip()
                if 'series' in taxonomy and s not in taxonomy.get('series', set()):
                    page_errors.append(f"  series '{s}' not in taxonomy")

        # Product type validation
        pt = re.search(r'^product_type:\s*(.+)$', fm, re.MULTILINE)
        if pt:
            p = pt.group(1).strip()
            if 'product_type' in taxonomy and p not in taxonomy.get('product_type', set()):
                page_errors.append(f"  product_type '{p}' not in taxonomy")

        # Position validation
        pos = re.search(r'^position:\s*(.+)$', fm, re.MULTILINE)
        if pos:
            p = pos.group(1).strip()
            if 'position' in taxonomy and p not in taxonomy.get('position', set()):
                page_errors.append(f"  position '{p}' not in taxonomy")

        # Attributes validation
        attrs = re.search(r'^attributes:\s*\[(.+)\]', fm, re.MULTILINE)
        if attrs:
            for a in attrs.group(1).split(','):
                a = a.strip()
                if 'attributes' in taxonomy and a not in taxonomy.get('attributes', set()):
                    # Check if it's in any dimension
                    found = classify_tag(a, taxonomy)
                    if found is None:
                        page_errors.append(f"  attribute '{a}' not in taxonomy")

        # Derived tags validation
        tags_match = re.search(r'^tags:\s*\[(.+)\]', fm, re.MULTILINE)
        if tags_match:
            for t in tags_match.group(1).split(','):
                t = t.strip()
                found = classify_tag(t, taxonomy)
                if found is None:
                    page_errors.append(f"  tag '{t}' not in taxonomy")

        # Entity-to-entity link check (wikilinks + markdown links)
        body = content[fm_match.end():]
        # Wikilinks
        wiki_links = re.findall(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', body)
        for link in wiki_links:
            for d in PRODUCT_DIRS:
                target = BASE / d / f"{link}.md"
                if target.exists():
                    page_errors.append(f"  entity-to-entity link: [[{link}]]")
                    break
        # Markdown links to other product pages
        md_links = re.findall(r'\]\(/([^)]+)\)', body)
        product_dirs = PRODUCT_DIRS
        current_dir = str(md.parent.relative_to(BASE)).split('/')[0]
        if current_dir in product_dirs:
            for mlink in md_links:
                target_dir = mlink.split('/')[0]
                if target_dir in product_dirs and target_dir != current_dir:
                    page_errors.append(f"  cross-brand entity link: /{mlink}")

        if page_errors:
            errors.append(f"❌ {rel}:")
            errors.extend(page_errors)
            pages_err += 1
        else:
            pages_ok += 1

    return errors, warnings, pages_ok, pages_err, pages_warn


# ── Index validation ──
def validate_indexes():
    """Validate all index.md files are complete and correct.
    Returns (errors, warnings, ok_count, err_count)."""
    errors = []
    warnings = []
    ok_count = 0
    err_count = 0

    SCAN_DIRS = ALL_CONTENT_DIRS

    # Collect all actual .md files (non-index)
    actual_files = set()
    for cat in SCAN_DIRS:
        cat_dir = BASE / cat
        if not cat_dir.is_dir():
            continue
        for md in cat_dir.rglob('*.md'):
            if md.name == 'index.md':
                continue
            actual_files.add(str(md.relative_to(BASE)))

    # ── Validate root index.md ──
    root_index = BASE / 'index.md'
    if not root_index.exists():
        errors.append("❌ root index.md is missing")
        err_count += 1
    else:
        root_content = root_index.read_text()
        # Extract all markdown links: [text](path)
        root_links = set()
        for m in re.finditer(r'\]\(([^)]+)\)', root_content):
            root_links.add(m.group(1))

        # Check page count header
        count_match = re.search(r'共 (\d+) 页', root_content)
        if count_match:
            declared = int(count_match.group(1))
            actual = len(actual_files)
            if declared != actual:
                errors.append(f"❌ root index.md: declares {declared} pages, actual {actual}")
                err_count += 1
            else:
                ok_count += 1
        else:
            warnings.append("⚠️ root index.md: no page count found in header")

        # Check every actual file appears in root index
        missing_from_root = actual_files - root_links
        if missing_from_root:
            for f in sorted(missing_from_root)[:10]:
                errors.append(f"❌ root index.md: missing '{f}'")
            if len(missing_from_root) > 10:
                errors.append(f"  ... and {len(missing_from_root) - 10} more")
            err_count += len(missing_from_root)

        # Check no stale links in root index
        stale_in_root = root_links - actual_files
        # Filter out directory links (ending with /)
        stale_in_root = {l for l in stale_in_root if not l.endswith('/')}
        if stale_in_root:
            for f in sorted(stale_in_root)[:10]:
                errors.append(f"❌ root index.md: stale link '{f}'")
            if len(stale_in_root) > 10:
                errors.append(f"  ... and {len(stale_in_root) - 10} more")
            err_count += len(stale_in_root)

    # ── Validate sub-directory index.md files ──
    for cat in SCAN_DIRS:
        cat_dir = BASE / cat
        if not cat_dir.is_dir():
            continue
        for index_path in cat_dir.rglob('index.md'):
            rel_index = str(index_path.relative_to(BASE))
            parent_dir = index_path.parent
            rel_parent = str(parent_dir.relative_to(BASE))

            # Gather actual content in this directory
            direct_md_files = set()
            for f in parent_dir.iterdir():
                if f.name.endswith('.md') and f.name != 'index.md':
                    direct_md_files.add(f.name)

            content_subdirs = set()
            for d in parent_dir.iterdir():
                if d.is_dir():
                    # Check if this subdir contains any .md files
                    if any(d.rglob('*.md')):
                        content_subdirs.add(d.name)

            # Parse index.md links
            idx_content = index_path.read_text()
            idx_links = set()
            idx_dirs = set()
            for m in re.finditer(r'\]\(([^)]+)\)', idx_content):
                link = m.group(1)
                if link.endswith('/'):
                    idx_dirs.add(link.rstrip('/'))
                else:
                    idx_links.add(link)

            # Check direct .md files
            missing = direct_md_files - idx_links
            for fname in sorted(missing):
                errors.append(f"❌ {rel_parent}/index.md: missing '{fname}'")
                err_count += 1

            stale = idx_links - direct_md_files
            for fname in sorted(stale):
                errors.append(f"❌ {rel_parent}/index.md: stale link '{fname}'")
                err_count += 1

            # Check subdirectory links
            missing_dirs = content_subdirs - idx_dirs
            for d in sorted(missing_dirs):
                errors.append(f"❌ {rel_parent}/index.md: missing subdirectory '{d}/'")
                err_count += 1

            stale_dirs = idx_dirs - content_subdirs
            for d in sorted(stale_dirs):
                errors.append(f"❌ {rel_parent}/index.md: stale subdirectory '{d}/'")
                err_count += 1

            if not missing and not stale and not missing_dirs and not stale_dirs:
                ok_count += 1

    return errors, warnings, ok_count, err_count


# ── Missing product page detection ──
def validate_missing_product_pages(auto_create=False):
    """Scan concept pages (系列/, 科技/) for product references in tables.
    Flag products that don't have their own .md pages.
    If auto_create=True, generate stub pages for missing products."""
    errors = []
    created = []

    # Collect all existing product page titles → path mapping
    product_titles = {}  # normalized_title → relative_path
    product_dirs = PRODUCT_DIRS
    slug_to_file = {}  # slugified_name → relative_path
    for d in product_dirs:
        dd = BASE / d
        if not dd.is_dir():
            continue
        for md in dd.rglob('*.md'):
            if md.name == 'index.md':
                continue
            rel = str(md.relative_to(BASE))
            slug_to_file[md.stem.lower().replace(' ', '-')] = rel
            fm, body, title = parse_frontmatter_simple(md)
            if title:
                product_titles[title.upper().strip()] = rel

    # Scan concept pages for product matrix tables
    for concept_dir in CONCEPT_DIRS:
        cd = BASE / concept_dir
        if not cd.is_dir():
            continue
        for md in sorted(cd.glob('*.md')):
            if md.name == 'index.md':
                continue
            rel = str(md.relative_to(BASE))
            content = md.read_text()

            # Extract product names from table rows
            # Only process rows that are inside a product matrix
            # (table with header containing "产品" or "鞋款" in second column)
            in_product_table = False
            for line in content.split('\n'):
                line = line.strip()
                # Detect product table header
                if re.match(r'^\|.+\|\s*产品\s*\|', line):
                    in_product_table = True
                    continue
                if re.match(r'^\|.+\|\s*鞋款\s*\|', line):
                    in_product_table = True
                    continue
                # End of table section
                if line == '' or (not line.startswith('|') and in_product_table):
                    in_product_table = False
                    continue
                if not in_product_table:
                    continue
                # Skip separator lines
                if re.match(r'^\|[\s\-:]+\|[\s\-:]+\|', line):
                    continue
                # Match table row: | col1 | PRODUCT_NAME | col3 ... |
                m = re.match(r'^\|[^|]+\|\s*(.+?)\s*\|', line)
                if not m:
                    continue
                product_name = m.group(1).strip()
                # Skip non-product rows
                if not product_name or len(product_name) < 3:
                    continue
                # Skip metadata / non-product values
                if product_name.startswith('¥') or product_name.startswith('TODO'):
                    continue
                # Skip descriptions: long Chinese text without model numbers
                if len(product_name) > 15 and not re.search(r'[A-Z0-9]{2,}', product_name):
                    continue
                # Skip rows that are clearly not product names
                skip_patterns = [
                    r'^[-—–]+$',           # separator dashes
                    r'^[0-9]+g$',           # weight like 173g
                    r'^[0-9]+%',            # percentage
                    r'^[0-9+\-><=,.]',      # starts with number/symbol
                    r'^(男|女)(大|小)童$',   # audience
                    r'^(代表|推荐)产品$',      # header labels
                    r'^(产品类型|科技特点)$',   # section labels
                ]
                skip = False
                for sp in skip_patterns:
                    if re.match(sp, product_name):
                        skip = True
                        break
                if skip:
                    continue

                # Check if this product has a page
                normalized = product_name.upper().strip()
                if normalized in product_titles:
                    continue

                # Try slug matching
                slug = product_name.lower().replace(' ', '-').replace('/', '-')
                found = False
                for sf, srel in slug_to_file.items():
                    if slug in sf or sf in slug:
                        found = True
                        break
                if found:
                    continue

                # Missing!
                errors.append(f"❌ {rel}: 引用产品 '{product_name}' 但无对应页面")

                if auto_create:
                    stub_path = _create_product_stub(product_name, rel, product_dirs, slug_to_file)
                    if stub_path:
                        created.append(stub_path)

    return errors, created


def parse_frontmatter_simple(md_path):
    """Lightweight frontmatter parser returning (fm_dict, body, title)."""
    try:
        content = md_path.read_text()
    except Exception:
        return {}, '', ''
    fm = {}
    title = md_path.stem
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split('\n'):
                if ':' in line:
                    k, _, v = line.partition(':')
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == 'title':
                        title = v
                    elif k in ('brand', 'type', 'position'):
                        fm[k] = v
    return fm, '', title


def _create_product_stub(product_name, concept_rel, product_dirs, slug_to_file):
    """Create a stub .md for a product referenced in a concept page.
    Infers brand/series/directory from the concept context and similar products."""

    # Try to infer brand from concept page context
    brand = None
    series_from_concept = None
    # Extract series name from concept filename stem
    series_match = re.match(r'.*/([a-z0-9-]+?)(?:-series|-xilie)?\.md$', concept_rel)
    if series_match:
        series_from_concept = series_match.group(1).upper()

    # Try to find sibling products in the same series to infer directory
    target_dir = None
    for sf, srel in slug_to_file.items():
        if series_from_concept and series_from_concept.lower() in sf:
            # Found a sibling - use its directory
            target_dir = os.path.dirname(os.path.join(BASE, srel))
            # Infer brand from directory
            for d in product_dirs:
                if srel.startswith(d + '/'):
                    brand = d.replace('产品', '')
                    break
            break

    if not target_dir:
        # Fallback: use first product dir (config-driven)
        brand = PRODUCT_DIRS[0].replace('产品', '') if PRODUCT_DIRS else 'products'

    # Create slug from product name
    slug = product_name.lower().replace(' ', '-').replace('/', '-')
    stub_path = os.path.join(target_dir, slug + '.md')

    # Don't overwrite existing files
    if os.path.exists(stub_path):
        return None

    # Build frontmatter
    fm_lines = ['---']
    fm_lines.append('type: 跑鞋')
    fm_lines.append(f'title: {product_name}')
    if brand:
        fm_lines.append(f'brand: {brand}')
    fm_lines.append('type: 鞋')
    if series_from_concept:
        fm_lines.append('series:')
        fm_lines.append(f'- {series_from_concept}')
    fm_lines.append('tags:')
    if brand:
        fm_lines.append(f'- {brand}')
    fm_lines.append('- 跑步')
    if series_from_concept:
        fm_lines.append(f'- {series_from_concept}')
    fm_lines.append('- 跑鞋')
    fm_lines.append(f'source: {concept_rel} 产品矩阵')
    fm_lines.append('---')
    fm_lines.append('')
    fm_lines.append(f'# {product_name}')
    fm_lines.append('')
    fm_lines.append('## 编译概要')
    fm_lines.append('')
    fm_lines.append(f'TODO: agent enrichment pass — {product_name}。')
    fm_lines.append('')
    fm_lines.append(f'> 此页根据概念页 [{concept_rel.split("/")[-1]}](/{concept_rel}) 产品矩阵自动生成。')
    fm_lines.append('> 信息来自系列概览页，待后续补充详细内容。')
    fm_lines.append('')

    os.makedirs(target_dir, exist_ok=True)
    with open(stub_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(fm_lines) + '\n')

    return stub_path


# ── Link integrity validation ──
def validate_links():
    """Scan all pages for broken wikilinks and markdown links.
    Returns (errors, ok_count, err_count)."""
    errors = []
    ok_count = 0
    err_count = 0

    SCAN_DIRS = ALL_CONTENT_DIRS

    # Build a set of all valid link targets (relative paths without .md)
    valid_targets = set()
    for cat in SCAN_DIRS:
        cat_dir = BASE / cat
        if not cat_dir.is_dir():
            continue
        for md in cat_dir.rglob('*.md'):
            if md.name == 'index.md':
                continue
            rel = str(md.relative_to(BASE))
            valid_targets.add(rel[:-3])                    # 运动表现产品/鞋/跑步/...
            parts = rel.split('/', 1)
            if len(parts) == 2:
                valid_targets.add(parts[1][:-3])           # 鞋/跑步/...
            valid_targets.add(md.stem)                      # filename only

    for cat in SCAN_DIRS:
        cat_dir = BASE / cat
        if not cat_dir.is_dir():
            continue
        for md in cat_dir.rglob('*.md'):
            if md.name == 'index.md':
                continue
            rel = str(md.relative_to(BASE))
            content = md.read_text()

            # Wikilinks: [[target]] or [[target|label]]
            for m in re.finditer(r'\[\[([^\]|#]+)', content):
                target = m.group(1).strip()
                if not target:
                    continue
                # Skip raw/ references — these are source citations, not internal links
                if target.startswith('raw/'):
                    continue
                if not _resolve_link(target, valid_targets):
                    errors.append(f"❌ {rel}: broken wikilink [[{target}]]")
                    err_count += 1
                else:
                    ok_count += 1

            # Markdown links: [text](/path/file.md)
            for m in re.finditer(r'\]\(/([^)]+)\)', content):
                target = m.group(1).strip()
                if target.endswith('.md'):
                    target = target[:-3]
                if not _resolve_link(target, valid_targets):
                    full_path = BASE / target
                    if not full_path.with_suffix('.md').exists():
                        errors.append(f"❌ {rel}: broken link /{target}")
                        err_count += 1
                    else:
                        ok_count += 1
                else:
                    ok_count += 1

    return errors, ok_count, err_count


def _resolve_link(target, valid_targets):
    """Try to resolve a link target against valid_targets set."""
    if target in valid_targets:
        return True
    # concepts/ → 系列/ or 科技/
    if target.startswith('concepts/'):
        for prefix in ['系列/', '科技/']:
            if target.replace('concepts/', prefix, 1) in valid_targets:
                return True
    # Try prefixing with each top-level dir
    for prefix in [d + '/' for d in ALL_CONTENT_DIRS]:
        if prefix + target in valid_targets:
            return True
    # Basename match
    basename = target.split('/')[-1]
    for vt in valid_targets:
        if vt.endswith('/' + basename) or vt == basename:
            return True
    return False


if __name__ == '__main__':
    taxonomy, tax_err = parse_taxonomy(TAXONOMY)
    if tax_err:
        print(f"❌ {tax_err}")
        sys.exit(1)

    errors, warnings, ok, err, warn = validate(taxonomy)

    print(f"\n{'='*60}")
    print(f"  Taxonomy Validation Report")
    print(f"{'='*60}")
    print(f"  Pages OK:   {ok}")
    print(f"  Errors:     {err}")
    print(f"  Warnings:   {warn}")
    print(f"  Taxonomy dimensions: {list(taxonomy.keys())}")
    print(f"{'='*60}")

    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for e in errors:
            print(e)

    if warnings:
        print(f"\n⚠️  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(w)

    if not errors and not warnings:
        print("\n✅ All pages comply with taxonomy.")

    # ── Index validation ──
    idx_errors, idx_warnings, idx_ok, idx_err = validate_indexes()

    print(f"\n{'='*60}")
    print(f"  Index Validation Report")
    print(f"{'='*60}")
    print(f"  Indexes OK: {idx_ok}")
    print(f"  Errors:     {idx_err}")
    print(f"{'='*60}")

    if idx_errors:
        print(f"\n❌ INDEX ERRORS ({len(idx_errors)}):")
        for e in idx_errors:
            print(e)

    if idx_warnings:
        print(f"\n⚠️  INDEX WARNINGS ({len(idx_warnings)}):")
        for w in idx_warnings:
            print(w)

    if not idx_errors and not idx_warnings:
        print("\n✅ All indexes up to date.")

    # ── Missing product page detection ──
    mp_errors, mp_created = validate_missing_product_pages(auto_create=False)

    print(f"\n{'='*60}")
    print(f"  Missing Product Pages Report")
    print(f"{'='*60}")
    print(f"  Missing:    {len(mp_errors)}")
    print(f"{'='*60}")

    if mp_errors:
        print(f"\n❌ MISSING PRODUCT PAGES ({len(mp_errors)}):")
        for e in mp_errors:
            print(e)

    if not mp_errors:
        print("\n✅ All concept-referenced products have pages.")

    # ── Link integrity validation ──
    link_errors, link_ok, link_err = validate_links()

    print(f"\n{'='*60}")
    print(f"  Link Integrity Report")
    print(f"{'='*60}")
    print(f"  Links OK:   {link_ok}")
    print(f"  Broken:     {link_err}")
    print(f"{'='*60}")

    if link_errors:
        print(f"\n❌ BROKEN LINKS ({len(link_errors)}):")
        for e in link_errors:
            print(e)

    if not link_errors:
        print("\n✅ All internal links resolve correctly.")

    total_errors = len(errors) + idx_err + len(mp_errors) + link_err
    sys.exit(1 if total_errors else 0)
