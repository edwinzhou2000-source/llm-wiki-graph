#!/usr/bin/env python3
"""regenerate-graph.py — Process upload queue: AI ingest → regenerate graph → local Wiki sync.

Called by server.py's _trigger_ingest() background thread.
Supports two modes: 'direct' (AI writes directly) and 'review' (AI generates proposals).
"""
import os, json, subprocess, shutil, time, re, random, sys
from pathlib import Path

# ── Paths ──
BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(BASE, ".ingest-queue.json")
STATUS = os.path.join(BASE, ".ingest-status.json")
HISTORY = os.path.join(BASE, ".upload-history.json")
UPLOADS = os.path.join(BASE, "raw", "articles", "_uploads")
GRAPH = os.path.join(BASE, "graph-data.json")
INDEX = os.path.join(BASE, "index.md")

# ── Process lock (prevent concurrent runs) ──
LOCKFILE = os.path.join(BASE, ".regenerate.lock")
LOCK_TIMEOUT = 1800  # 30 min — stale lock auto-cleared

# ── Config ──
from config import cfg, KB_ROOT, CATEGORY_COLORS, CATEGORY_IDS, PRODUCT_DIRS, CONCEPT_DIRS, ALL_CONTENT_DIRS, TECH_CONCEPT_DIR, SERIES_CONCEPT_DIR

def _load(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except: return d if d is not None else []

def _save(p, data):
    with open(p, 'w') as f: json.dump(data, f, ensure_ascii=False)

def _status(phase, msg):
    _save(STATUS, {"phase": phase, "message": msg, "time": time.strftime('%H:%M:%S')})

def _update_history(fnames, status, error=None):
    h = _load(HISTORY, [])
    for fn in fnames:
        for e in h:
            if e.get("name") == fn:
                # Only update entries that aren't already done
                if e.get("status") == "done" and status == "ingesting":
                    continue  # don't overwrite completed status
                e["status"] = status
                if error: e["error"] = error
                if status == "done": e["done_at"] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save(HISTORY, h)

def _update_history_image(fname, image_status, image_count=None, error=None):
    """Track per-file image extraction status in upload history."""
    h = _load(HISTORY, [])
    for e in h:
        if e.get("name") == fname:
            e["image_status"] = image_status
            if image_count is not None:
                e["image_count"] = image_count
            if error:
                e["image_error"] = error
            if image_status in ("done", "skipped", "failed"):
                e["image_done_at"] = time.strftime('%Y-%m-%d %H:%M:%S')
            break
    _save(HISTORY, h)

def parse_fm(path):
    """Parse YAML frontmatter: returns (fm_dict, body, title)."""
    try:
        with open(path, 'r') as f:
            content = f.read()
    except:
        return {}, "", os.path.splitext(os.path.basename(path))[0]
    fm = {}
    body = content
    title = os.path.splitext(os.path.basename(path))[0]
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            body = parts[2]
            in_list = False
            list_key = None
            for line in parts[1].strip().split('\n'):
                line = line.strip()
                if ':' in line and not line.startswith('-'):
                    k, _, v = line.partition(':')
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == 'title':
                        title = v
                    elif k in ('series', 'attributes', 'tags'):
                        if v.startswith('['):
                            fm[k] = [x.strip().strip('"').strip("'") for x in v.strip('[]').split(',')]
                        else:
                            fm[k] = [v]
                        list_key = None
                    else:
                        fm[k] = v
                        list_key = None
                elif line.startswith('- ') and list_key:
                    if list_key not in fm:
                        fm[list_key] = []
                    fm[list_key].append(line[2:].strip())
    return fm, body, title


# ── Graph Generation ──
# Color map: brand → color
BRAND_COLORS = {
    # Color mapping built dynamically from kb-config.yml categories

}
CATEGORY_DIRS = ALL_CONTENT_DIRS

# ── 3D Force-Directed Layout ──────────────────────────────────────────────
# Pre-computes settled 3D positions so the browser renders instantly
# without running O(n²) physics on every page load.

CLUSTER_Z_MAP = {
    # 3D layout X offsets built dynamically from categories order
    **{c.dir: (i - len(cfg.categories)/2) * 2.0 for i, c in enumerate(cfg.categories)},
}
_FORCE_CX, _FORCE_CY, _FORCE_SCALE = 525, 375, 0.018


def _world_pos(node):
    """Map pixel coords to 3D world space (mirrors JS worldPos)."""
    return (
        (node['cx'] - _FORCE_CX) * _FORCE_SCALE,
        -(node['cy'] - _FORCE_CY) * _FORCE_SCALE,
        CLUSTER_Z_MAP.get(node.get('subcat', ''), 0)
    )


def _run_3d_force_layout(nodes, links, old_nodes=None):
    """Run 3D force-directed layout and bake _x/_y/_z into each node.

    Uses two-phase settling (gather → spread) then stores final positions.
    Existing nodes with prior _x/_y/_z values start from their last position,
    avoiding unnecessary re-layout.
    """
    import math, time
    t0 = time.time()
    old_nodes = old_nodes or {}
    n_count = len(nodes)
    l_count = len(links)

    # ── Initialize positions ──
    for n in nodes:
        nid = n['id']
        old = old_nodes.get(nid, {})
        if '_x' in old and '_y' in old and '_z' in old:
            # Reuse previous settled position
            n['_x'] = old['_x']
            n['_y'] = old['_y']
            n['_z'] = old['_z']
        else:
            n['_x'], n['_y'], n['_z'] = _world_pos(n)
        # Cluster center = initial position (anchors nodes to their category region)
        n['_cx'] = n['_x']
        n['_cy'] = n['_y']
        n['_cz'] = n['_z']
        n['_vx'] = n['_vy'] = n['_vz'] = 0.0

    # ── Build node lookup ──
    node_by_id = {n['id']: n for n in nodes}

    # ── Pre-process links ──
    link_data = []
    for link in links:
        src = node_by_id.get(link['source'])
        tgt = node_by_id.get(link['target'])
        if src is not None and tgt is not None:
            same = src.get('subcat') == tgt.get('subcat')
            link_data.append((src, tgt, 0.4 if same else 0.06, 2.0 if same else 6.0))

    # ── Spatial grid for charge repulsion (O(n·k) instead of O(n²)) ──
    # With 5,961 nodes this is the difference between ~30s and ~1s per run.
    _CELL = 1.5  # grid cell size in world units

    def _build_grid(nodes_list):
        grid = {}
        for idx, n in enumerate(nodes_list):
            cx = int(n['_x'] / _CELL)
            cy = int(n['_y'] / _CELL)
            cz = int(n['_z'] / _CELL)
            key = (cx, cy, cz)
            grid.setdefault(key, []).append(idx)
        return grid

    # ── Run iterations ──
    ITER = 80  # fewer than browser 300 — Python is faster per-iter but runs once
    node_list = nodes  # alias

    for it in range(ITER):
        progress = it / ITER
        phase = 0 if progress < 0.35 else 1
        alpha = (
            max(0.03, 0.3 * (1 - progress / 0.35))
            if phase == 0
            else max(0.02, 0.3 * (1 - (progress - 0.35) / 0.65))
        )

        # Reset forces
        for n in node_list:
            n['_fx'] = n['_fy'] = n['_fz'] = 0.0

        # ── Link springs ──
        for src, tgt, strength, target_dist in link_data:
            dx = tgt['_x'] - src['_x']
            dy = tgt['_y'] - src['_y']
            dz = tgt['_z'] - src['_z']
            dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.001
            force = (dist - target_dist) / dist * strength * alpha
            src['_fx'] += dx * force
            src['_fy'] += dy * force
            src['_fz'] += dz * force
            tgt['_fx'] -= dx * force
            tgt['_fy'] -= dy * force
            tgt['_fz'] -= dz * force

        # ── Cluster attraction ──
        for n in node_list:
            dx = n['_cx'] - n['_x']
            dy = n['_cy'] - n['_y']
            dz = n['_cz'] - n['_z']
            dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.001
            force = 0.25 * alpha * min(dist, 5.0) / 5.0
            n['_fx'] += dx * force
            n['_fy'] += dy * force
            n['_fz'] += dz * force

        # ── Charge repulsion (grid-accelerated) ──
        if phase == 1:
            rep_factor = 0.15 * alpha
            grid = _build_grid(node_list)
            # Check 3×3×3 = 27 neighboring cells for each node
            offsets = [
                (dx, dy, dz)
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for dz in (-1, 0, 1)
            ]
            for i, a in enumerate(node_list):
                ax, ay, az = a['_x'], a['_y'], a['_z']
                ci = int(ax / _CELL)
                cj = int(ay / _CELL)
                ck = int(az / _CELL)
                for ox, oy, oz in offsets:
                    key = (ci + ox, cj + oy, ck + oz)
                    for j in grid.get(key, ()):
                        if j <= i:
                            continue  # only process each pair once
                        b = node_list[j]
                        rx = ax - b['_x']
                        ry = ay - b['_y']
                        rz = az - b['_z']
                        r2 = rx * rx + ry * ry + rz * rz + 0.1
                        r = math.sqrt(r2)
                        f = rep_factor / r2
                        a['_fx'] += (rx / r) * f
                        a['_fy'] += (ry / r) * f
                        a['_fz'] += (rz / r) * f
                        b['_fx'] -= (rx / r) * f
                        b['_fy'] -= (ry / r) * f
                        b['_fz'] -= (rz / r) * f

        # ── Center gravity ──
        for n in node_list:
            n['_fx'] -= n['_x'] * 0.0005 * alpha
            n['_fy'] -= n['_y'] * 0.0005 * alpha
            n['_fz'] -= n['_z'] * 0.0005 * alpha

        # ── Apply forces with velocity damping ──
        damp = 0.82 if phase == 0 else 0.92
        vmax = 0.3 if phase == 0 else 0.5
        for n in node_list:
            n['_vx'] = (n['_vx'] + n['_fx']) * damp
            n['_vy'] = (n['_vy'] + n['_fy']) * damp
            n['_vz'] = (n['_vz'] + n['_fz']) * damp
            speed = math.sqrt(n['_vx'] ** 2 + n['_vy'] ** 2 + n['_vz'] ** 2)
            if speed > vmax:
                s = vmax / speed
                n['_vx'] *= s
                n['_vy'] *= s
                n['_vz'] *= s
            n['_x'] += n['_vx']
            n['_y'] += n['_vy']
            n['_z'] += n['_vz']

    # ── Clean up temp fields ──
    for n in node_list:
        for k in ('_fx', '_fy', '_fz', '_vx', '_vy', '_vz', '_cx', '_cy', '_cz'):
            n.pop(k, None)

    elapsed = time.time() - t0
    print(f"⚡ 3D force layout: {n_count} nodes, {l_count} links → {elapsed:.1f}s")


def generate_graph():
    """Scan all .md files in category directories, build graph-data.json."""
    old_nodes = {}
    if os.path.exists(GRAPH):
        try:
            old = _load(GRAPH, {})
            for n in old.get('nodes', []):
                old_nodes[n['id']] = n
        except: pass

    nodes = []
    seen = set()
    added = 0

    for cat_dir in CATEGORY_DIRS:
        d = os.path.join(BASE, cat_dir)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if not fname.endswith('.md') or fname == 'index.md':
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, BASE)
                node_id = rel[:-3]  # strip .md
                if node_id in seen:
                    continue
                seen.add(node_id)

                fm, body, title = parse_fm(fpath)
                brand = fm.get('brand', cat_dir.replace('产品', ''))
                summary = fm.get('description', '')
                color = BRAND_COLORS.get(brand, '#94a3b8')
                # Derive subcat from category dir for 3D/product-hub coloring (5-category system)
                subcat = cat_dir
                # Build tags from series + attributes
                tags = []
                for s in fm.get('series', []):
                    if s.strip(): tags.append(f'系列/{s.strip()}')
                for a in fm.get('attributes', []):
                    if a.strip(): tags.append(f'特性/{a.strip()}')
                cat = fm.get('type', '')
                if cat: tags.append(f'品类/{cat}')

                if node_id in old_nodes:
                    old = old_nodes[node_id]
                    nodes.append({
                        'id': node_id, 'title': title,
                        'category': cat_dir, 'brand': brand,
                        'subcat': subcat,
                        'tags': tags,
                        'summary': summary,
                        'cx': old.get('cx', random.uniform(200, 1000)),
                        'cy': old.get('cy', random.uniform(100, 600)),
                        'color': old.get('color', color),
                    })
                else:
                    added += 1
                    nodes.append({
                        'id': node_id, 'title': title,
                        'category': cat_dir, 'brand': brand,
                        'subcat': subcat,
                        'tags': tags,
                        'summary': summary,
                        'cx': random.uniform(200, 1000),
                        'cy': random.uniform(100, 600),
                        'color': color,
                    })

    # Build links from [[wikilinks]]
    links = []
    for node in nodes:
        fpath = os.path.join(BASE, node['id'] + '.md')
        try:
            with open(fpath, 'r') as f:
                text = f.read()
            for m in re.finditer(r'\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]', text):
                target_title = m.group(1).strip()
                target_slug = target_title.replace(' ', '-').lower()
                if target_slug in seen and target_slug != node['id']:
                    links.append({'source': node['id'], 'target': target_slug, 'type': 'wikilink'})
        except: pass

    graph_data = {'nodes': nodes, 'links': links}
    _run_3d_force_layout(nodes, links, old_nodes)
    _save(GRAPH, graph_data)

    removed = len(old_nodes) - len(seen)
    changes = []
    if added: changes.append(f"+{added} new")
    if removed: changes.append(f"--{removed} removed")
    change_str = ', '.join(changes) if changes else 'no changes'
    print(f"✅ Graph updated: {len(nodes)} nodes, {len(links)} links ({change_str})")
    return len(nodes), len(links)


# ── Index Regeneration ──
def regenerate_index():
    """Regenerate root index.md listing all pages grouped by category."""
    cats = {}
    for cat_dir in CATEGORY_DIRS:
        d = os.path.join(BASE, cat_dir)
        if not os.path.isdir(d):
            continue
        pages = []
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if fname == 'index.md':
                    continue
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(root, fname)
                fm, body, title = parse_fm(fpath)
                rel = os.path.relpath(fpath, BASE)
                slug = rel[:-3]
                summary = fm.get('description', '')
                pages.append({'title': title, 'slug': slug, 'summary': summary})
        if pages:
            cats[cat_dir] = pages

    lines = ['---', 'title: 知识库索引', '---', '', f'# {cfg.brand.public_name}', '',
             f'*共 {sum(len(v) for v in cats.values())} 个页面*', '']
    for cat_name, pages in cats.items():
        lines.append(f'## {cat_name}')
        lines.append('')
        for p in pages:
            s = p['summary'][:80] + ('...' if len(p['summary']) > 80 else '') if p['summary'] else ''
            lines.append(f'- **[[{p["title"]}|{p["slug"]}]]** — {s}')
        lines.append('')

    with open(INDEX, 'w') as f:
        f.write('\n'.join(lines))
    print(f"✅ root index.md regenerated ({sum(len(v) for v in cats.values())} pages)")


def regenerate_sub_indexes():
    """Regenerate sub-index.md files in each category directory."""
    updated = 0
    for cat_dir in CATEGORY_DIRS:
        d = os.path.join(BASE, cat_dir)
        if not os.path.isdir(d):
            continue
        # Gather all pages and subdirectories
        pages = []
        subdirs = set()
        for root, dirs, files in os.walk(d):
            rel_dir = os.path.relpath(root, d)
            for fname in sorted(files):
                if fname == 'index.md':
                    continue
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(root, fname)
                fm, body, title = parse_fm(fpath)
                pages.append({
                    'title': title,
                    'path': os.path.relpath(fpath, d),
                    'subdir': rel_dir if rel_dir != '.' else '',
                })
                if rel_dir != '.':
                    parts = rel_dir.split(os.sep)
                    if parts:
                        subdirs.add(parts[0])

        lines = ['---', f'title: {cat_dir} 索引', '---', '',
                 f'# {cat_dir}', '', f'*{len(pages)} 个产品*', '']
        # Subdirectory listing
        if subdirs:
            lines.append('## 子分类')
            for sd in sorted(subdirs):
                lines.append(f'- [[{cat_dir}/{sd}/index|{sd}]]')
            lines.append('')
        # Page listing
        if pages:
            lines.append('## 产品列表')
            for p in pages:
                sub = f' ({p["subdir"]})' if p['subdir'] else ''
                lines.append(f'- {p["title"]}{sub}')
            lines.append('')

        idx_path = os.path.join(d, 'index.md')
        old = ''
        if os.path.exists(idx_path):
            with open(idx_path) as f:
                old = f.read()
        new = '\n'.join(lines)
        if new != old:
            with open(idx_path, 'w') as f:
                f.write(new)
            updated += 1

    print(f"✅ sub-indexes regenerated ({updated} updated)")
    return updated


def _extract_product_summary(body):
    """Extract a one-line summary from product body text.
    Returns '适应症 | 核心卖点' or just '适应症' if no selling points found.
    Returns empty string if nothing to extract."""
    parts = []

    # Extract adaptation (first non-empty line after ## 适应症)
    m = re.search(r'## 适应症\n(.+)', body)
    if m:
        indication = m.group(1).strip()
        # Trim to first sentence or ~60 chars
        indication = re.sub(r'[。；;].*', '', indication)[:80]
        if indication:
            parts.append(indication)

    # Extract first selling point (first bullet after ## 核心卖点)
    m = re.search(r'## 核心卖点\n((?:- .+\n?)+)', body)
    if m:
        sp_block = m.group(1)
        first_sp = re.search(r'- (.+)', sp_block)
        if first_sp:
            sp = first_sp.group(1).strip()
            # Remove wikilinks for compactness
            sp = re.sub(r'\[\[([^\]]+)\]\]', r'\1', sp)
            sp = sp[:100]
            parts.append(sp)

    return ' | '.join(parts)


def regenerate_series_pages():
    """Generate/update series pages under 系列/ directory.
    Merges products by normalized slug to handle case variants (ADIZERO vs adizero).
    Includes technology summary with links to 科技/ pages."""
    series_dir = os.path.join(BASE, SERIES_CONCEPT_DIR)
    os.makedirs(series_dir, exist_ok=True)
    updated = 0

    # Collect series from all product frontmatter → normalize by slug
    # slug → {display_name, products: [{title, slug, category, attributes}]}
    series_data = {}
    for cat_dir in CATEGORY_DIRS:
        if cat_dir == SERIES_CONCEPT_DIR:
            continue
        d = os.path.join(BASE, cat_dir)
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for fname in sorted(files):
                if fname == 'index.md' or not fname.endswith('.md'):
                    continue
                fpath = os.path.join(root, fname)
                fm, body, title = parse_fm(fpath)
                rel = os.path.relpath(fpath, BASE)
                slug = rel[:-3]
                attrs = fm.get('attributes', [])
                if isinstance(attrs, str):
                    attrs = [attrs]
                for s_name in fm.get('series', []):
                    s_name = s_name.strip()
                    if not s_name:
                        continue
                    s_slug_raw = s_name.lower().replace(' ', '-').replace('/', '-')
                    # Normalize known noise patterns:
                    #   "ADIZERO系列" → "ADIZERO"
                    #   "0系列ADIZERO" → "ADIZERO"
                    #   "ADIZERO 0系列" → "ADIZERO"
                    import re as _re2
                    clean = _re2.sub(r'^\d+系列\s*', '', s_name)       # "0系列ADIZERO"
                    clean = _re2.sub(r'\s*\d+系列$', '', clean)        # "ADIZERO 0系列"
                    clean = _re2.sub(r'系列$', '', clean)               # "ADIZERO系列"
                    clean = clean.strip()
                    s_slug = clean.lower().replace(' ', '-').replace('/', '-')
                    if s_slug not in series_data:
                        series_data[s_slug] = {'display': s_name, 'products': [], 'tech_counter': {}}
                    # Prefer display name: shorter + uppercase wins (ADIZERO > ADIZERO 0系列)
                    existing = series_data[s_slug]['display']
                    if len(s_name) < len(existing) or (s_name.upper() == s_name and existing.upper() != existing):
                        series_data[s_slug]['display'] = s_name
                    series_data[s_slug]['products'].append({
                        'title': title, 'slug': slug, 'category': cat_dir,
                        'summary': _extract_product_summary(body),
                    })
                    # Count technologies referenced in attributes
                    for a in attrs:
                        a_lower = str(a).lower().strip()
                        # Only count English tech names
                        if re.match(r'^[a-z][a-z0-9\-]{2,}$', a_lower):
                            series_data[s_slug]['tech_counter'][a_lower] = \
                                series_data[s_slug]['tech_counter'].get(a_lower, 0) + 1

    # Get existing科技/ pages for cross-linking
    tech_dir = os.path.join(BASE, TECH_CONCEPT_DIR)
    existing_tech = set()
    if os.path.isdir(tech_dir):
        existing_tech = set(f.replace('.md', '') for f in os.listdir(tech_dir)
                           if f.endswith('.md') and f != 'index.md')

    for s_slug, data in series_data.items():
        s_path = os.path.join(series_dir, f"{s_slug}.md")
        products = data['products']
        display = data['display']

        # Build technology summary section
        tech_lines = []
        top_techs = sorted(data['tech_counter'].items(), key=lambda x: -x[1])[:8]
        for tech_name, _count in top_techs:
            if tech_name in existing_tech:
                tech_lines.append(f'- [[科技/{tech_name}]]')
            else:
                tech_lines.append(f'- {tech_name.upper()}')

        lines = [
            '---',
            f'title: {display} 系列',
            'type: 系列',
            f'description: {display} 系列，共 {len(products)} 个产品。',
            '---',
            '',
            f'# {display} 系列',
            '',
            f'> 共 **{len(products)}** 个产品。',
        ]

        if tech_lines:
            lines.append('')
            lines.append('## 核心技术')
            lines.extend(tech_lines)

        lines.append('')
        lines.append('## 产品列表')
        lines.append('')
        # Use slug-based wikilinks (more reliable than title-based), with summary
        for p in products:
            tail = f' — {p["summary"]}' if p.get('summary') else ''
            lines.append(f'- [[{p["slug"]}]] ({p["category"]}){tail}')
        lines.append('')

        new = '\n'.join(lines)
        old = ''
        if os.path.exists(s_path):
            with open(s_path) as f:
                old = f.read()
        if new != old:
            with open(s_path, 'w') as f:
                f.write(new)
            updated += 1

    # Clean up stale series pages (no longer referenced by any product)
    existing_pages = set(f for f in os.listdir(series_dir) if f.endswith('.md') and f != 'index.md')
    expected_pages = set(f'{s}.md' for s in series_data)
    for stale in existing_pages - expected_pages:
        stale_path = os.path.join(series_dir, stale)
        os.remove(stale_path)
        print(f"  🗑  删除过期系列页: {stale}")

    print(f"✅ series pages regenerated ({updated} updated, {len(series_data)} total)")
    return updated


# ── Concept Index ──
def _build_concept_index():
    """Scan 科技/ and 系列/ directories, return a compact reference text
    showing available concept pages that product pages can wikilink to."""
    lines = []
    tech_names = []  # collect technology names for attributes prompt
    for concept_dir in CONCEPT_DIRS:
        d = os.path.join(BASE, concept_dir)
        if not os.path.isdir(d):
            continue
        pages = sorted([f for f in os.listdir(d) if f.endswith('.md') and f != 'index.md'])
        if not pages:
            continue
        lines.append(f'## {concept_dir} 概念页（可在正文中用 [[{concept_dir}/xxx]] 链接）')
        for fname in pages[:80]:
            slug = fname.replace('.md', '')
            fpath = os.path.join(d, fname)
            fm, _, title = parse_fm(fpath)
            if concept_dir == TECH_CONCEPT_DIR:
                tech_names.append(f'{title}（{slug}）')
            summary = fm.get('description', '')
            if summary:
                lines.append(f'- [[{concept_dir}/{slug}]] — {title}：{summary[:80]}')
            else:
                lines.append(f'- [[{concept_dir}/{slug}]] — {title}')
        if len(pages) > 80:
            lines.append(f'  ... 还有 {len(pages)-80} 个概念页，如需精确匹配请查看 {concept_dir}/ 目录')
    return '\n'.join(lines), tech_names


# ── Link Concepts ──
def _run_link_concepts():
    """Run _link_concepts.py to build product↔concept and concept↔concept wikilinks."""
    script = os.path.join(BASE, '_link_concepts.py')
    if not os.path.exists(script):
        print("⚠️  _link_concepts.py not found, skipping")
        return
    try:
        result = subprocess.run(
            ['python3', script],
            capture_output=True, text=True, timeout=120, cwd=BASE
        )
        if result.returncode == 0:
            print(result.stdout.strip())
        else:
            print(f"⚠️  _link_concepts.py error: {result.stderr[:200]}")
    except Exception as e:
        print(f"⚠️  _link_concepts.py failed: {e}")


def _sync_concept_pages():
    """Run enrich.py --fix-dataview to sync concept page product lists from product wikilinks."""
    script = os.path.join(BASE, 'enrich.py')
    if not os.path.exists(script):
        print("⚠️  enrich.py not found, skipping concept sync")
        return
    try:
        result = subprocess.run(
            ['python3', script, '--fix-dataview'],
            capture_output=True, text=True, timeout=60, cwd=BASE
        )
        if result.returncode == 0:
            # Show summary line only
            for line in result.stdout.strip().split('\n'):
                if 'Fixed' in line or 'skipped' in line:
                    print(f"  {line.strip()}")
        else:
            print(f"⚠️  concept sync error: {result.stderr[:200]}")
    except Exception as e:
        print(f"⚠️  concept sync failed: {e}")


# ── Local Wiki search corpus Sync (replaces gbrain import) ──
def gbrain_sync():
    """Rebuild local Wiki search corpus (no Bun/gbrain dependency)."""
    try:
        import local_wiki_search as wiki_search
        msg = wiki_search.sync()
        print(f"✅ {msg}")
    except Exception as e:
        print(f"⚠️  local Wiki sync error: {e}")


# ── Image Extraction (async) ──
VISION_SCRIPT = os.path.expanduser("~/.hermes/skills/wiki/gbrain-knowledge-base/scripts/vision-ingest.py")

def _extract_images_async(files):
    """Run vision-ingest.py for each file in a background thread.
    Extracts product images from PDFs/PPTs and links them to KB pages.
    Updates per-file image_status in upload history for frontend tracking."""
    import threading

    def _run():
        for fn in files:
            _update_history_image(fn, "extracting")

            src = os.path.join(UPLOADS, fn)
            if not os.path.exists(src):
                src = os.path.join(UPLOADS, '_archived', fn)
            if not os.path.exists(src):
                print(f"  ⚠️  source not found for image extraction: {fn}")
                _update_history_image(fn, "failed", error="source not found")
                continue

            stem = os.path.splitext(fn)[0]
            img_dir = os.path.join(BASE, "images", stem)
            os.makedirs(img_dir, exist_ok=True)
            kb_dir = BASE

            print(f"  🖼️  提取图片: {fn} → {img_dir}")

            # Step 1: Extract images
            try:
                result = subprocess.run(
                    [sys.executable, VISION_SCRIPT, src,
                     '--extract-images', '--skip-text',
                     '--image-out-dir', img_dir,
                     '--prompt', 'product',
                     '--out-dir', '/tmp/vision_ingest_tmp'],
                    capture_output=True, text=True, timeout=600, cwd=BASE
                )
                if result.returncode != 0:
                    print(f"  ⚠️  extraction failed for {fn}: {result.stderr[:200]}")
                    _update_history_image(fn, "failed", error=result.stderr[:200])
                    continue
            except Exception as e:
                print(f"  ⚠️  extraction error for {fn}: {e}")
                _update_history_image(fn, "failed", error=str(e)[:200])
                continue

            # Check manifest for crop count — no manifest = file has no extractable images
            manifest = os.path.join(img_dir, "manifest.json")
            if not os.path.exists(manifest):
                print(f"  📄 {fn}: no images found (no manifest)")
                _update_history_image(fn, "skipped")
                continue

            try:
                with open(manifest) as f:
                    manifest_data = json.load(f)
                crop_count = sum(len(p.get('products', [])) for p in manifest_data)
                if crop_count == 0:
                    print(f"  📄 {fn}: 0 crops in manifest — no images")
                    _update_history_image(fn, "skipped")
                    continue
            except Exception:
                print(f"  ⚠️  cannot read manifest for {fn}")
                _update_history_image(fn, "failed", error="manifest parse error")
                continue

            # Step 2: Link images to KB pages
            try:
                result = subprocess.run(
                    [sys.executable, VISION_SCRIPT, 'NONE',
                     '--link-only',
                     '--image-out-dir', img_dir,
                     '--kb-dir', kb_dir],
                    capture_output=True, text=True, timeout=120, cwd=BASE
                )
                linked = len([l for l in result.stdout.split('\n') if '[link]' in l])
                print(f"  ✅ {fn}: {linked} images linked")
                _update_history_image(fn, "done", image_count=linked)
            except Exception as e:
                print(f"  ⚠️  linking failed for {fn}: {e}")
                # Images extracted but linking failed — still report with crop count
                _update_history_image(fn, "done", image_count=crop_count,
                                      error=f"linking failed: {str(e)[:100]}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print(f"  📸 图片提取已在后台启动 ({len(files)} files)")


# ── Taxonomy Validation ──
def run_validate():
    """Run validate-taxonomy.py if it exists."""
    script = os.path.join(BASE, 'validate-taxonomy.py')
    if not os.path.exists(script):
        return True
    try:
        result = subprocess.run(
            ['python3', script],
            capture_output=True, text=True, timeout=30, cwd=BASE
        )
        if result.returncode != 0:
            print(f"⚠️  Non-taxonomy issues found — continuing anyway.")
            return False
        print(result.stdout.strip())
        return True
    except Exception as e:
        print(f"⚠️  validate-taxonomy error: {e}")
        return False


def _build_path_guide():
    """Build a dynamic directory path guide for AI ingest prompts, from kb-config.yml."""
    lines = []
    for c in cfg.categories:
        if getattr(c, 'role', None) != 'product':
            continue
        for sub in (c.subcategories or []):
            for child in (getattr(sub, 'children', None) or []):
                lines.append(f'   · {c.name.replace("产品","")}·{child.name} → {c.dir}/{sub.dir}/{child.dir}/\n')
            # Also add the direct subpath
            lines.append(f'   · {c.name.replace("产品","")}·{sub.name} → {c.dir}/{sub.dir}/\n')
    if not lines:
        return '   (请根据配置文件中的品类结构选择路径)\n'
    return ''.join(lines)


def _is_pi_ingest(queue_files, mode=None):
    """True when upload mode is说明书/PI or filenames look like prescribing info."""
    if mode in ("pi", "pi-review"):
        return True
    for f in queue_files:
        fl = f.lower()
        if (
            fl.endswith(".pi.txt")
            or fl.endswith(".pi.md")
            or "说明书" in f
            or "_pi_" in fl
            or fl.startswith("pi-")
            or "prescribing" in fl
        ):
            return True
    return False


def _folder_rel_guide():
    """Directory → edge type lines for PI prompts (from wiki_graph_extract)."""
    try:
        from wiki_graph_extract import FOLDER_TO_REL
    except Exception:
        FOLDER_TO_REL = {
            "用药安全/相互作用": "INTERACTS_WITH",
            "用药安全/禁忌": "CONTRAINDICATED_FOR",
            "用药安全/治疗": "TREATS",
            "成分": "(entity)",
            "疾病": "(entity)",
        }
    lines = []
    for folder, rel in sorted(FOLDER_TO_REL.items()):
        lines.append(f"   · {folder}/ → graph.type={rel}\n")
    lines.append("   · 成分/ → kind:entity label:Drug\n")
    lines.append("   · 疾病/ → kind:entity label:Condition\n")
    return "".join(lines)


def _md_from_fm_body(fm, body, title):
    """Rebuild full markdown from parsed frontmatter + body."""
    import yaml as _yaml
    data = dict(fm or {})
    if title:
        data["title"] = title
    # Prefer dump that keeps unicode
    yml = _yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    body = (body or "").lstrip("\n")
    return f"---\n{yml}\n---\n\n{body}".rstrip() + "\n"


def _iter_staging_md(staging_dir):
    """Yield (rel_slug_without_md, abs_path) for all .md under staging (nested OK)."""
    if not os.path.isdir(staging_dir):
        return
    for root, _dirs, fnames in os.walk(staging_dir):
        for fname in sorted(fnames):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, staging_dir).replace("\\", "/")
            if rel.endswith(".md"):
                rel = rel[:-3]
            yield rel, fpath


def _pi_prompt(queue_files, ingest_note):
    file_list = ", ".join(queue_files)
    guide = _folder_rel_guide()
    return (
        f"你是 {cfg.brand.name} 医药知识库「说明书入库」助手。从说明书文本起草 Wiki 提案草稿（非直接定稿）。\n"
        f"文件列表：{file_list}\n"
        f"所有文件在 raw/articles/_uploads/ 目录下。{ingest_note}\n"
        f"\n"
        f"## 架构硬约束（必须遵守）\n"
        f"- Wiki 是事实本体；图只是索引。\n"
        f"- **一事一页**：每条禁忌/相互作用/适应症单独一个 .md，禁止把相互作用列表塞进成分实体页再靠抽边。\n"
        f"- 严重程度、机理、监测写在边事实页正文「结论/详细说明」，不要发明新的英文边类型。\n"
        f"- 端点名优先复用库内规范中文名（如 华法林、阿司匹林、慢性肾病）；可用 aliases。\n"
        f"- 专家不写英文 type；你按目录写入 graph.type（见下表）。\n"
        f"\n"
        f"## 目录 → 边类型\n"
        f"{guide}\n"
        f"\n"
        f"## 工作步骤\n"
        f"1. read_file 读取说明书原文\n"
        f"2. 若成分/疾病实体页不存在，在 staging 创建 成分/xxx.md 或 疾病/xxx.md（kind: entity）\n"
        f"3. 为每条相互作用/禁忌/治疗关系各写一页到对应子目录（文件名：起点-终点.md）\n"
        f"4. write_file 全部写到 raw/articles/_uploads/_review_staging/ 下，**保持与正式 Wiki 相同的相对路径**\n"
        f"   例：raw/articles/_uploads/_review_staging/用药安全/相互作用/华法林-人参.md\n"
        f"\n"
        f"## 边事实页模板\n"
        f"```\n"
        f"---\n"
        f"title: 华法林 药物相互作用 人参\n"
        f"type: 药物相互作用\n"
        f"entity_kind: 关系事实\n"
        f"graph:\n"
        f"  kind: edge\n"
        f"  type: INTERACTS_WITH\n"
        f"  from: 华法林\n"
        f"  from_label: Drug\n"
        f"  to: 人参\n"
        f"  to_label: Drug\n"
        f"---\n"
        f"\n"
        f"# 华法林 — 药物相互作用 — 人参\n"
        f"\n"
        f"## 结论\n"
        f"严重程度：中等。人参可能减弱抗凝效果（演示用语，非正式说明书）。\n"
        f"\n"
        f"## 详细说明\n"
        f"（机理、监测建议；写给人审与 RAG）\n"
        f"```\n"
        f"\n"
        f"## 严格禁止\n"
        f"- 禁止修改正式库已有文件；只能写 _review_staging/\n"
        f"- 禁止把多条相互作用写在同一个成分页的列表里代替边事实页\n"
        f"- 禁止运行 git / 扫描全库无关目录\n"
    )


def _proposals_from_staging_product(staging_dir, proposals_dir):
    """Legacy product staging → one proposal per flat .md (brand-based slug)."""
    generated = 0
    for fname in sorted(os.listdir(staging_dir)):
        if not fname.endswith(".md"):
            continue
        # skip nested (handled by PI path)
        if os.path.isdir(os.path.join(staging_dir, fname)):
            continue
        fpath = os.path.join(staging_dir, fname)
        if not os.path.isfile(fpath):
            continue
        fm, body, title = parse_fm(fpath)
        if not title or not fm.get("brand"):
            print(f"  ⚠️  skipping {fname}: missing title/brand")
            continue
        brand = fm.get("brand", "")
        brand_dir = None
        for cat_obj in cfg.categories:
            if cat_obj.name == brand or cat_obj.name.startswith(brand):
                brand_dir = cat_obj.dir
                break
        if not brand_dir:
            brand_dir = PRODUCT_DIRS[0] if PRODUCT_DIRS else "products"
        slug = f"{brand_dir}/待分类/{title.lower().replace(' ', '-')}"
        safe_name = slug.replace("/", "_")
        prop_path = os.path.join(proposals_dir, f"{safe_name}.json")
        if os.path.exists(prop_path):
            ep = _load(prop_path, {})
            if ep.get("status") == "pending":
                print(f"  ⏭  {safe_name}: 已有待审批提案")
                continue
        full_md = _md_from_fm_body(fm, body, title)
        proposal = {
            "title": title,
            "slug": slug,
            "brand": brand,
            "category": fm.get("category", ""),
            "series": fm.get("series", []),
            "source": "upload",
            "action": "create",
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "content": body,
            "frontmatter": {k: v for k, v in fm.items() if k != "title"},
            "proposed_content": full_md,
        }
        _save(prop_path, proposal)
        generated += 1
    return generated


def _proposals_from_staging_pi(staging_dir, proposals_dir, source_files):
    """PI staging (nested Wiki paths) → one multipage proposal package."""
    pages = []
    for rel_slug, fpath in _iter_staging_md(staging_dir) or []:
        # Only accept known ontology roots
        root = rel_slug.split("/", 1)[0]
        if root not in (
            "成分", "疾病", "设备", "用药安全", "临床事实", "产品桥接",
            "临床病例", "处方药", "OTC药品", "医疗器械", "技术平台", "产品系列",
        ):
            print(f"  ⚠️  skip unexpected staging path: {rel_slug}")
            continue
        fm, body, title = parse_fm(fpath)
        title = title or Path(rel_slug).name
        full_md = _md_from_fm_body(fm, body, title)
        # If graph.type missing on edge path, inject from folder
        if "graph:" in full_md or (fm.get("graph") or {}).get("kind") == "edge":
            pass
        pages.append({
            "slug": rel_slug,
            "title": title,
            "proposed_content": full_md,
        })

    if not pages:
        return 0

    src_label = ", ".join(source_files) if source_files else "pi"
    pack_id = "pi-ingest_" + re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", source_files[0] if source_files else "pack")[:80]
    slug = f"pi-ingest/{pack_id}"
    safe_name = slug.replace("/", "_")
    prop_path = os.path.join(proposals_dir, f"{safe_name}.json")
    if os.path.exists(prop_path):
        ep = _load(prop_path, {})
        if ep.get("status") == "pending":
            print(f"  ⏭  {safe_name}: 已有待审批提案包")
            return 0

    summary = "\n\n".join(
        f"### {p['title']} (`{p['slug']}`)\n\n" + (
            p["proposed_content"].split("---", 2)[-1].strip()[:800]
            if p["proposed_content"].startswith("---")
            else p["proposed_content"][:800]
        )
        for p in pages
    )
    proposal = {
        "title": f"说明书入库提案包（{len(pages)} 页）— {src_label}",
        "slug": slug,
        "source": "pi-ingest",
        "action": "create",
        "status": "pending",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_files": list(source_files),
        "pages": pages,
        "proposed_content": f"# 提案包预览（共 {len(pages)} 页）\n\n{summary}\n",
    }
    _save(prop_path, proposal)
    print(f"  📦 multipage proposal {safe_name}: {len(pages)} pages")
    return 1


# ── Ingest: Direct Mode ──
def ingest_direct(queue_files):
    """AI directly creates product pages in the KB, then rebuild graph."""
    file_list = ', '.join(queue_files)

    # Check for special file types
    has_ocr = any(f.endswith('.txt') for f in queue_files)
    has_vision = any(f.endswith('.vision.md') for f in queue_files)
    ingest_note = ''
    if has_vision:
        ingest_note = '这些 .vision.md 是 AI 视觉模型分析 PPT/PDF 图片后生成的结果，请直接读取文本内容。'
    elif has_ocr:
        ingest_note = '这些是 OCR 提取的文本文件，请直接读取文本内容。'

    concept_index, tech_names = _build_concept_index()
    tech_list = ', '.join(tech_names[:30])  # top 30 tech names for the prompt
    prompt = (
        f'你是 {cfg.brand.name} 产品知识库编辑助手。请处理以下文件，为每个文件创建产品页面。\n'
        f'文件列表：{file_list}\n'
        f'所有文件在 raw/articles/_uploads/ 目录下。{ingest_note}\n'
        f'\n'
        f'## 已知技术名称（attributes 必须包含其中匹配的）\n'
        f'{tech_list}\n'
        f'\n'
        f'## 概念页索引（产品正文中应使用 [[wikilink]] 链接到相关概念）\n'
        f'{concept_index}\n'
        f'\n'
        f'## 工作步骤\n'
        f'1. 用 read_file 逐个读取文件\n'
        f'2. 提取产品信息：产品名、品牌(运动表现/三叶草/轻运动)、品类(鞋/服装/配件)、系列、定位、价格、科技等\n'
        f'3. 如果一个文件包含多个产品（如男女款、不同配色），为每个产品创建独立的 .md 文件\n'
        f'4. 为每个产品创建 .md 文件到对应的子目录，根据品牌+品类+系列选择路径，不要全部放待分类：\n'
        + _build_path_guide() +
        f'   不确定子类型时，才放到对应品牌的 待分类/ 目录\n'
        f'5. ⚠️ 重要：在正文中主动使用 [[系列/xxx]] 和 [[科技/xxx]] wikilink 链接到相关概念页\n'
        f'   例如写到 BOOST 科技时加 [[科技/BOOST]]，写到 ADIZERO 系列时加 [[系列/adizero]]\n'
        f'   在「核心卖点」和「适用场景」章节自然嵌入 wikilink\n'
        f'\n'
        f'## 输出格式（每个产品一个 .md 文件）\n'
        f'文件名：用英文小写+连字符。必须包含 YAML frontmatter：\n'
        f'```\n'
        f'---\n'
        f'title: 产品名称\n'
        f'brand: 运动表现|三叶草|轻运动\n'
        f'type: 鞋|服装|配件\n'
        f'series: [系列名]  ⚠️ 只用核心系列名，去掉「系列」「0系列」「新」「经典」等后缀，如 ADIZERO 而非 ADIZERO 0系列\n'
        f'attributes: [特性标签 + 技术名称]  ⚠️ 必须包含产品使用的所有技术名（如 LIGHTSTRIKE, BOOST, PRIMEKNIT, CONTINENTAL 等），参考上方「已知技术名称」列表\n'
        f'description: 一句话简介\n'
        f'---\n'
        f'# 产品名称\n'
        f'## 编辑概要\n'
        f'(产品概述，涉及科技/系列时使用 [[wikilink]])\n'
        f'## 定位与价格\n'
        f'## 核心卖点\n'
        f'### 鞋面/中底/大底\n'
        f'(每个科技点后面用 [[科技/xxx]] 链接)\n'
        f'## 适用场景\n'
        f'```\n'
        f'\n'
        f'## 严格禁止\n'
        f'- 禁止修改 index.md、log.md 或任何已有文件\n'
        f'- 禁止运行脚本、git 命令\n'
        f'- 禁止扫描目录\n'
        f'- 一个文件生成一个产品页面\n'
    )
    cmd = ['hermes', 'chat', '-q', prompt,
           '--toolsets', 'file,terminal',
           '--yolo', '--max-turns', '25']

    print(f"  Running Hermes (direct, {len(queue_files)} files)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=BASE)

    if result.returncode != 0:
        print(f"  Hermes error (exit {result.returncode}): {result.stderr[:500]}")
        raise Exception(f"Hermes exit {result.returncode}")

    print(f"  Hermes ok: {result.stdout.strip()[-300:]}")


# ── Ingest: Review Mode ──
def ingest_review(queue_files, mode=None):
    """AI generates proposals for review instead of writing directly.

    mode=pi or PI-like filenames → 说明书 multipage package (实体+边事实页).
    Otherwise → legacy product page proposals.
    """
    has_ocr = any(f.endswith('.txt') for f in queue_files)
    has_vision = any(f.endswith('.vision.md') for f in queue_files)
    ingest_note = ''
    if has_vision:
        ingest_note = '这些 .vision.md 是 AI 视觉模型分析 PPT/PDF 图片后生成的结果，请直接读取文本内容。'
    elif has_ocr:
        ingest_note = '这些是 OCR 提取的文本文件，请直接读取文本内容。'

    staging_dir = os.path.join(UPLOADS, '_review_staging')
    # Fresh staging for this batch
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    pi_mode = _is_pi_ingest(queue_files, mode=mode)
    if pi_mode:
        prompt = _pi_prompt(queue_files, ingest_note)
        label = "pi-review"
        max_turns = 40
    else:
        concept_index, tech_names = _build_concept_index()
        tech_list = ', '.join(tech_names[:30])
        file_list = ', '.join(queue_files)
        prompt = (
            f'你是 {cfg.brand.name} 产品知识库编辑助手。请处理以下文件，为每个文件生成一个产品页面。\n'
            f'文件列表：{file_list}\n'
            f'所有文件在 raw/articles/_uploads/ 目录下。{ingest_note}\n'
            f'\n'
            f'## 已知技术名称（attributes 必须包含其中匹配的）\n'
            f'{tech_list}\n'
            f'\n'
            f'## 概念页索引（产品正文中应使用 [[wikilink]] 链接到相关概念）\n'
            f'{concept_index}\n'
            f'\n'
            f'## 工作步骤\n'
            f'1. 用 read_file 逐个读取 raw/articles/_uploads/ 下的文件\n'
            f'2. 提取产品信息：产品名、品类、系列、定位、科技、适用场景等\n'
            f'3. 如果一个文件包含多个产品，为每个产品创建独立的 .md 文件\n'
            f'4. 用 write_file 创建产品页面到 raw/articles/_uploads/_review_staging/ 目录（扁平文件名即可）\n'
            f'5. 正文中使用 [[产品系列/xxx]] / [[技术平台/xxx]] wikilink\n'
            f'\n'
            f'## 输出格式（每个产品一个 .md 文件）\n'
            f'须含 YAML frontmatter：title, type, series, description 等\n'
            f'\n'
            f'## 严格禁止\n'
            f'- 禁止修改 index.md、log.md 或正式库文件\n'
            f'- 只能写 raw/articles/_uploads/_review_staging/\n'
            f'- 禁止运行 git\n'
        )
        label = "review"
        max_turns = 25

    cmd = ['hermes', 'chat', '-q', prompt,
           '--toolsets', 'file,terminal',
           '--yolo', '--max-turns', str(max_turns)]

    print(f"  Running Hermes ({label}, {len(queue_files)} files)...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=BASE)

    if result.returncode != 0:
        print(f"  Hermes error (exit {result.returncode}): {result.stderr[:500]}")
        raise Exception(f"Hermes exit {result.returncode}")

    print(f"  Hermes done")

    proposals_dir = os.path.join(BASE, '_proposals')
    os.makedirs(proposals_dir, exist_ok=True)
    if pi_mode:
        generated = _proposals_from_staging_pi(staging_dir, proposals_dir, queue_files)
    else:
        generated = _proposals_from_staging_product(staging_dir, proposals_dir)

    print(f"  ✅ 生成 {generated} 个审核提案" + ("包" if pi_mode else ""))


# ── Main ──
def _remove_from_queue(fn):
    """Remove a single file from the queue."""
    q = _load(QUEUE, {})
    if isinstance(q, list):
        q = {"files": q, "mode": "review"}
    q["files"] = [f for f in q.get("files", [])
                  if (f["name"] if isinstance(f, dict) else f) != fn]
    _save(QUEUE, q)

def main():
    # ── Acquire process lock ──
    if os.path.exists(LOCKFILE):
        try:
            with open(LOCKFILE) as f:
                lock_data = json.load(f)
            lock_age = time.time() - lock_data.get("ts", 0)
            if lock_age < LOCK_TIMEOUT:
                # Check if the lock owner is still alive
                lock_pid = lock_data.get("pid", 0)
                try:
                    os.kill(lock_pid, 0)
                    print(f"⚠️  另一个 regenerate-graph 正在运行 (PID {lock_pid}, {int(lock_age)}s ago)，跳过。")
                    return
                except OSError:
                    print(f"[lock] breaking stale lock (PID {lock_pid} gone, {int(lock_age)}s old)")
        except:
            pass
    with open(LOCKFILE, 'w') as f:
        json.dump({"pid": os.getpid(), "ts": time.time()}, f)

    try:
        _main_body()
    finally:
        if os.path.exists(LOCKFILE):
            os.remove(LOCKFILE)

def _main_body():
    queue = _load(QUEUE, [])
    # Normalize queue format
    if isinstance(queue, list):
        queue = {"files": queue, "mode": "review"}

    raw_files = queue.get("files", [])
    files = [f["name"] if isinstance(f, dict) else f for f in raw_files]
    mode = queue.get("mode", "direct")
    mode_label = "AI 自动收录" if mode == 'direct' else "AI 分析"

    if not files:
        print("No files in queue, checking graph freshness...")
        if os.path.exists(GRAPH):
            gmtime = os.path.getmtime(GRAPH)
            newest = 0
            for cat_dir in CATEGORY_DIRS:
                d = os.path.join(BASE, cat_dir)
                if os.path.isdir(d):
                    for root, dirs, fnames in os.walk(d):
                        for fname in fnames:
                            if fname.endswith('.md'):
                                newest = max(newest, os.path.getmtime(os.path.join(root, fname)))
            if gmtime >= newest:
                print("Graph is up to date, nothing to do.")
                return
        # Always run series pages + graph generation (even without new files)
        regenerate_series_pages()
        generate_graph()
        return

    # ── Process each file individually ──
    succeeded = []
    failed = []
    total = len(files)

    # Snapshot existing pages to track which ones are created by each file
    _existing_pages_before = set()
    for cat_dir in CATEGORY_DIRS:
        d = os.path.join(BASE, cat_dir)
        if os.path.isdir(d):
            for root, dirs, fnames in os.walk(d):
                for fname in fnames:
                    if fname.endswith('.md') and fname != 'index.md':
                        _existing_pages_before.add(os.path.relpath(os.path.join(root, fname), BASE))

    for i, fn in enumerate(files, 1):
        print(f"\n{'='*50}")
        print(f"[{i}/{total}] Processing: {fn}")
        _status("ingesting", f"[{i}/{total}] 处理 {fn}...（{mode_label}）")
        _update_history([fn], "ingesting")

        try:
            if mode == 'direct':
                ingest_direct([fn])
            else:
                ingest_review([fn], mode=mode)
            succeeded.append(fn)
            _remove_from_queue(fn)
            _update_history([fn], "done")

            # Track newly created pages for this file
            _existing_after = set()
            for cat_dir in CATEGORY_DIRS:
                d = os.path.join(BASE, cat_dir)
                if os.path.isdir(d):
                    for root, dirs, fnames in os.walk(d):
                        for fname in fnames:
                            if fname.endswith('.md') and fname != 'index.md':
                                _existing_after.add(os.path.relpath(os.path.join(root, fname), BASE))
            new_pages = sorted(_existing_after - _existing_pages_before)
            if new_pages:
                h = _load(HISTORY, [])
                for e in h:
                    if e.get("name") == fn:
                        e["pages_created"] = new_pages
                        break
                _save(HISTORY, h)
                print(f"  📄 tracked {len(new_pages)} new pages: {new_pages[:3]}...")
            _existing_pages_before = _existing_after
            print(f"  ✅ {fn} done")
        except Exception as e:
            print(f"  ❌ {fn} failed: {e}")
            failed.append(fn)
            _update_history([fn], "error", str(e)[:200])
            # Don't remove from queue — can retry later

    if not succeeded:
        _status("error", f"全部 {total} 个文件处理失败")
        return

    # ── Post-processing: run full pipeline once ──
    print(f"\n{'='*50}")
    print(f"✅ {len(succeeded)} succeeded, {len(failed)} failed — running full pipeline...")

    try:
        _status("syncing", "同步本地 Wiki 检索语料...")
        gbrain_sync()

        _status("linking", "构建概念链接...")
        _run_link_concepts()

        _status("concepts", "同步概念页产品列表...")
        _sync_concept_pages()

        _status("regenerating", "重建知识图谱...")
        generate_graph()

        regenerate_index()
        regenerate_sub_indexes()
        regenerate_series_pages()

        gbrain_sync()
        run_validate()

        _status("neo4j", "Wiki 事实页 → Neo4j…")
        subprocess.run(
            [sys.executable, os.path.join(BASE, "graph", "sync_wiki_graph.py"), "--quiet"],
            cwd=BASE,
            timeout=300,
        )

        # ── Auto-extract images from PDFs/PPTs/images (background, non-blocking) ──
        img_exts = {'.pdf', '.pptx', '.ppt', '.jpg', '.jpeg', '.png', '.webp'}
        extract_files = [fn for fn in succeeded if os.path.splitext(fn)[1].lower() in img_exts]
        if extract_files:
            _status("extracting", f"提取 {len(extract_files)} 个文件的产品图片...")
            _extract_images_async(extract_files)
    except Exception as e:
        print(f"⚠️  Post-processing error (files already ingested): {e}")
        _status("done", f"{len(succeeded)} 成功, {len(failed)} 失败 — 后处理异常: {str(e)[:100]}")

    # Archive successfully processed files
    archived = os.path.join(UPLOADS, '_archived')
    os.makedirs(archived, exist_ok=True)
    for fn in succeeded:
        src = os.path.join(UPLOADS, fn)
        if os.path.isfile(src):
            dst = os.path.join(archived, fn)
            c = 1
            while os.path.exists(dst):
                n, e = os.path.splitext(fn)
                dst = os.path.join(archived, f"{n}-{c}{e}")
                c += 1
            shutil.move(src, dst)

    # Count pages
    page_count = 0
    for cat_dir in CATEGORY_DIRS:
        d = os.path.join(BASE, cat_dir)
        if os.path.isdir(d):
            for root, dirs, fnames in os.walk(d):
                page_count += len([f for f in fnames if f.endswith('.md') and f != 'index.md'])

    if failed:
        _status("done", f"{len(succeeded)} 成功, {len(failed)} 失败 — 共 {page_count} 页")
    else:
        _status("done", f"全部 {total} 个文件处理完成 — 共 {page_count} 页")


if __name__ == '__main__':
    main()
