#!/usr/bin/env python3
"""LLM-WIKI KB Server — Graph-first knowledge hub (local Wiki search, no gbrain).

All brand-specific config is in kb-config.yml. Import config.py to access it.
"""
import http.server, os, json, subprocess, cgi, shutil, threading, time, re, hashlib, sys
from typing import Optional
from http import cookies as http_cookies
from socketserver import ThreadingMixIn
import requests
import jieba
import yaml
from config import cfg, KB_ROOT, load_env, ALL_CATEGORY_DIRS, CATEGORY_COLORS, PRODUCT_DIRS, CONCEPT_DIRS, ALL_CONTENT_DIRS, TECH_CONCEPT_DIR, SERIES_CONCEPT_DIR, CLINICAL_DIRS, BRIDGE_DIRS, LOCAL_SOURCE_DIRS
import graph_recall
import local_wiki_search as wiki_search
import question_rewrite

# ── Domain dictionary (from config taxonomy) ──
_DOMAIN_TERMS = []
for vals in cfg.taxonomy.valid_values.__dict__.values():
    for v in vals:
        if isinstance(v, str) and len(v) >= 2:
            _DOMAIN_TERMS.append(v)
# Also add common Chinese domain terms
_EXTRA_TERMS = ["全马", "半马", "碳板", "中底", "大底", "鞋面",
    "竞速", "缓震", "支撑", "稳定", "回弹", "透气", "防水", "防滑",
    "编织鞋面", "马牌橡胶", "马牌", "新中式", "联名", "针织"]
_DOMAIN_TERMS.extend(_EXTRA_TERMS)
for _t in set(_DOMAIN_TERMS):
    jieba.add_word(_t)

# ── ANSI escape sequence stripper ──
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?(\x07|\x1b\\)')
def _strip_ansi(text):
    return _ANSI_RE.sub('', text)

BASE = KB_ROOT
UPLOADS = os.path.join(BASE, "raw", "articles", "_uploads")
QUEUE = os.path.join(BASE, ".ingest-queue.json")
HISTORY = os.path.join(BASE, ".upload-history.json")
STATUS = os.path.join(BASE, ".ingest-status.json")
PORT = cfg.server.port

# ── Security: read-only mode ──
READ_ONLY = os.environ.get("READ_ONLY", "").lower() in ("true", "1", "yes")

# ── Rate limiting for Q&A endpoint ──
QA_RATE_LIMIT = cfg.server.qa_rate_limit_per_minute
_qa_timestamps = []  # sliding window for in-process rate limiting

BUN = '/opt/homebrew/bin/bun'  # unused by search (kept for optional tooling)

# Legacy gbrain paths kept as no-ops / unused — search is local_wiki_search
GBRAIN_CLI = os.path.expanduser("~/gbrain/src/cli.ts")
GBRAIN_ENV = {"DATABASE_URL": "", "GBRAIN_HOME": cfg.paths.gbrain_home}

_ENV = load_env()
DEEPSEEK_API_KEY = _ENV.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))
DEEPSEEK_BASE_URL = _ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = "deepseek-chat"

# ── Portal auth (password gate for public access) ──
# Password is stored in ~/.hermes/.env — never hardcoded in source.
_PORTAL_PASSWORD = _ENV.get("PORTAL_PASSWORD", "")
if not _PORTAL_PASSWORD:
    raise RuntimeError("PORTAL_PASSWORD must be set in ~/.hermes/.env")
_AUTH_COOKIE_NAME = cfg.server.cookie_name
# Cookie secret is independent of password — random hex string in .env
_AUTH_COOKIE_SECRET = _ENV.get("PORTAL_COOKIE_SECRET", "")
if not _AUTH_COOKIE_SECRET:
    # Fallback: derive from password (backward compat) but warn
    print("[auth] WARNING: PORTAL_COOKIE_SECRET not set — deriving from password (less secure)")
    _AUTH_COOKIE_SECRET = hashlib.sha256(
        ("kb-hub-portal-" + _PORTAL_PASSWORD).encode()
    ).hexdigest()

# ── Login rate limiting ──
# 5 attempts per minute per IP; 10 failures → 15-minute lockout
_LOGIN_ATTEMPTS = {}  # ip -> [timestamps]
_LOGIN_LOCKOUT = {}   # ip -> lockout_until_timestamp
_LOGIN_LOCK = threading.Lock()

os.makedirs(UPLOADS, exist_ok=True)
lock = threading.Lock()
ingest_lock = threading.Lock()
qa_lock = threading.Lock()  # protects _qa_timestamps rate-limit window
INGEST_LOCK_FILE = os.path.join(BASE, ".ingest-lock.json")
INGEST_LOCK_TIMEOUT = 900  # 15 min — stale locks are safe to break

def _acquire_ingest_lock():
    """File-based lock: returns True if lock acquired, False if another ingest is running.
    Uses PID+timestamp to detect stale locks (survives daemon-thread death and server restart)."""
    try:
        if os.path.exists(INGEST_LOCK_FILE):
            with open(INGEST_LOCK_FILE) as f:
                stale = json.load(f)
            age = time.time() - stale.get("ts", 0)
            if age < INGEST_LOCK_TIMEOUT:
                print(f"[ingest] locked by PID {stale.get('pid')} ({int(age)}s ago) — skipping")
                return False
            print(f"[ingest] breaking stale lock from PID {stale.get('pid')} ({int(age)}s old)")
        with open(INGEST_LOCK_FILE, 'w') as f:
            json.dump({"pid": os.getpid(), "ts": time.time()}, f)
        return True
    except Exception as e:
        print(f"[ingest] lock error: {e}")
        return False

def _release_ingest_lock():
    try:
        if os.path.exists(INGEST_LOCK_FILE):
            os.remove(INGEST_LOCK_FILE)
    except Exception:
        pass
state = {"phase": "idle", "message": "", "files": [], "started": None, "done": None}

# ── Product image index (slug → image paths) ──
def _normalize_slug(name):
    """Normalize a product name/slug for matching: lowercase, spaces/hyphens→hyphens, strip extras."""
    import re
    name = re.sub(r'[\(（][^)）]*[\)）]', '', name)
    name = name.strip().lower()
    name = re.sub(r'[\s_]+', '-', name)
    name = re.sub(r'[^a-z0-9\-]', '', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')

def _build_image_index():
    """Scan images/*/manifest.json and build {normalized_slug: [image_paths]} index."""
    index = {}
    images_root = os.path.join(BASE, "images")
    if not os.path.isdir(images_root):
        return index
    for d in os.listdir(images_root):
        manifest_path = os.path.join(images_root, d, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            for page_entry in manifest:
                for prod in page_entry.get("products", []):
                    name = prod.get("product", "")
                    img = prod.get("image", "")
                    if not name or not img:
                        continue
                    full_path = os.path.join(images_root, d, img)
                    # Skip tiny images (< 15KB = likely bad crop)
                    try:
                        if os.path.getsize(full_path) < 15_000:
                            continue
                    except OSError:
                        continue
                    slug = _normalize_slug(name)
                    if not slug:
                        continue
                    rel_path = f"images/{d}/{img}"
                    if slug not in index:
                        index[slug] = []
                    if rel_path not in index[slug]:
                        index[slug].append(rel_path)
        except Exception:
            pass
    return index

# Build once at startup
_IMAGE_INDEX = _build_image_index()
print(f"[img-index] {len(_IMAGE_INDEX)} products indexed with images")

# Cache for kb-tree (invalidated on ingest)
_KBTREE_CACHE = None
_KBTREE_MTIME = 0

# ── Tag → image slug index (Chinese/English keyword matching) ──
def _build_tag_image_index():
    """Scan KB pages: frontmatter tags + directory path components → image slugs."""
    import re as _re2
    tag_index = {}
    _BRAND_DIRS = {}  # populated dynamically below
    for c in cfg.categories:
        if getattr(c, 'role', None) == 'product':
            _BRAND_DIRS[c.dir] = c.name.replace('产品', '')
    for root, dirs, files in os.walk(BASE):
        dirs[:] = [d for d in dirs if not d.startswith('.')
                    and d not in ('images', 'logs', '_meta', 'raw', '.git')]
        for fn in files:
            if not fn.endswith('.md') or fn in ('index.md', 'log.md'):
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath) as f:
                    content = f.read()
                m = _re2.match(r'^---\s*\n(.*?)\n---', content, _re2.DOTALL)
                fm = yaml.safe_load(m.group(1)) if m else {}
                # Collect tags: frontmatter tags + path-derived tags
                tags = list(fm.get('tags', []) or [])
                if isinstance(tags, str):
                    tags = [tags]
                # Path-derived tags: directory structure IS the taxonomy
                rel = os.path.relpath(fpath, BASE)
                slug = rel[:-3]
                path_parts = slug.split('/')
                for part in path_parts[:-1]:  # skip filename
                    # Normalize brand directory names: 三叶草产品 → 三叶草
                    part = _BRAND_DIRS.get(part, part)
                    if part and part not in tags:
                        tags.append(part)
                if not tags:
                    continue
                # Normalize slug for image index matching
                last = slug.rsplit('/', 1)[-1]
                norm_slug = _normalize_slug(last)
                # Also try stripping SKU prefix: hp7107-superstar-ii → superstar-ii
                candidates = [norm_slug]
                sku_match = _re2.match(r'^[a-z]{2}\d+-?(.+)', norm_slug)
                if sku_match:
                    candidates.append(sku_match.group(1))
                for tag in tags:
                    tag_lower = tag.lower().strip()
                    if not tag_lower:
                        continue
                    tag_index.setdefault(tag_lower, set())
                    for c in candidates:
                        if c and c in _IMAGE_INDEX:
                            tag_index[tag_lower].add(c)
            except Exception:
                pass
    return tag_index

_TAG_IMAGE_INDEX = _build_tag_image_index()
print(f"[tag-img-index] {len(_TAG_IMAGE_INDEX)} tags → {sum(len(v) for v in _TAG_IMAGE_INDEX.values())} product-image links")

def _get_images_for_slugs(slugs, question=""):
    """Given gbrain slugs + optional question, return matching image markdown lines.
    Phase 1: Exact slug match (with SKU prefix stripping).
    Phase 2: Fuzzy keyword match against image index.
    Phase 3: Tag-based match (Chinese/English keywords → KB tags → image slugs)."""
    images = []
    seen = set()

    def _add(slug, img_path):
        if img_path not in seen:
            seen.add(img_path)
            alt = slug.replace('-', ' ').title()
            # Extract source document name from image path
            parts = img_path.split('/')
            source = parts[1] if len(parts) > 1 else ''
            # Use NL variable to avoid double-escaping by patch tools
            _NL = '\n'
            images.append(f'![{alt}]({img_path}){_NL}*📂 {source}*')

    # Phase 1: Exact slug match (with SKU prefix stripping)
    for s in slugs:
        name = s.rsplit('/', 1)[-1]
        normalized = _normalize_slug(name)
        # Try exact match
        for img_path in _IMAGE_INDEX.get(normalized, []):
            _add(normalized, img_path)
        # Also try stripping SKU prefix: hp7107-superstar-ii → superstar-ii
        sku_match = re.match(r'^[a-z]{2}\d+-?(.+)', normalized)
        if sku_match:
            alt = sku_match.group(1)
            for img_path in _IMAGE_INDEX.get(alt, []):
                _add(alt, img_path)

    # Phase 2: If no images found, fuzzy keyword match against image index
    if not images and question:
        keywords = set()
        # Use jieba for proper Chinese word segmentation (regex fails on unspaced Chinese)
        for word in jieba.cut(question):
            word = word.strip().lower()
            if len(word) >= 2 and word not in ('有哪些', '哪几款', '系列', '什么', '如何', '怎么', '的', '是', '区别', '推荐', '选择', '新款', '经典', '有', '哪些', '鞋款', '产品', '哪个', '哪款'):
                keywords.add(word)
        if keywords:
            for idx_slug, img_paths in _IMAGE_INDEX.items():
                if any(kw in idx_slug for kw in keywords):
                    for img_path in img_paths:
                        _add(idx_slug, img_path)

    # Phase 3: Tag-based matching (handles Chinese↔English bridging)
    # Only REPLACES Phase 1/2 when 2+ keywords form an intersection —
    # that's strictly more precise than slug/keyword matching alone.
    if question and _TAG_IMAGE_INDEX:
        keywords = set()
        for word in jieba.cut(question):
            word = word.strip().lower()
            if len(word) >= 2 and word not in ('有哪些', '哪几款', '系列', '什么', '如何', '怎么', '的', '是', '区别', '推荐', '选择', '有', '哪些'):
                keywords.add(word)
        # Collect matching slug sets per keyword
        kw_slug_sets = {}  # kw → set of image slugs
        for kw in keywords:
            slugs_for_kw = set()
            if kw in _TAG_IMAGE_INDEX:
                slugs_for_kw = _TAG_IMAGE_INDEX[kw].copy()
            else:
                # Substring match for compound words
                for tag, img_slugs in _TAG_IMAGE_INDEX.items():
                    if kw in tag or tag in kw:
                        slugs_for_kw.update(img_slugs)
            if slugs_for_kw:
                kw_slug_sets[kw] = slugs_for_kw
        # Only replace when multiple keywords form a meaningful intersection
        if len(kw_slug_sets) >= 2:
            final_slugs = set.intersection(*kw_slug_sets.values())
            if final_slugs:  # Non-empty intersection → replace with precise results
                images.clear()
                seen.clear()
                for img_slug in final_slugs:
                    for img_path in _IMAGE_INDEX.get(img_slug, []):
                        _add(img_slug, img_path)

    return images

def _linkify_slugs(answer, seen_slugs):
    """Convert KB slug/SKU references in AI answer to product detail links.
    Handles both full slugs (b75806-samba-og.md) and short SKU codes (b75806)."""
    # Build SKU → slug mapping from seen slugs
    sku_map = {}
    for slug in seen_slugs:
        base = slug.rsplit('/', 1)[-1]
        if len(base) < 5:
            continue
        # Extract SKU: the first segment before '-' in the filename
        # e.g., b75806-samba-og → b75806
        parts = base.split('-', 1)
        sku = parts[0]
        if re.match(r'^[a-z]{1,2}\d+$', sku):
            sku_map[sku] = slug
        # Also map the full base (only if it looks like a product slug)
        if re.match(r'^[a-z]{1,2}\d+-[a-z]', base):
            sku_map[base] = slug
    # Replace SKU codes and full slugs in answer text
    for key, slug in sku_map.items():
        escaped = re.escape(key)
        # Match: `SKU` (backtick-wrapped) → link, or bare SKU → link
        # Handle backtick-wrapped: `b75806` → [b75806](/product/...)
        answer = re.sub(
            rf'`{escaped}(?:\.md)?`',
            f'[{key}](/product/{slug})',
            answer,
            flags=re.IGNORECASE
        )
        # Handle bare SKU/slug, not inside []() links
        answer = re.sub(
            rf'(?<![(\[/]){escaped}(?:\.md)?(?![)\]])',
            f'[{key}](/product/{slug})',
            answer,
            flags=re.IGNORECASE
        )
    return answer

def _load(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def _public_config():
    """Return public-safe config for frontend consumption."""
    categories = []
    for c in cfg.categories:
        cat = {
            "id": c.id,
            "name": c.name,
            "color": c.color,
            "dir": c.dir,
            "role": getattr(c, "role", None),
        }
        subs = []
        for sub in getattr(c, 'subcategories', []) or []:
            sc = {"name": sub.name, "dir": sub.dir}
            if hasattr(sub, 'children') and sub.children:
                sc["children"] = [{"name": ch.name, "dir": ch.dir} for ch in sub.children]
            subs.append(sc)
        if subs:
            cat["subcategories"] = subs
        categories.append(cat)

    return {
        "brand": {
            "name": cfg.brand.name,
            "public_name": cfg.brand.public_name,
            "display_name": cfg.brand.display_name,
        },
        "categories": categories,
        "theme": cfg.theme.__dict__,
        "server": {
            "port": cfg.server.port,
        },
        "upload": {
            "modes": [{"id": m.id, "label": m.label, "description": m.description} for m in cfg.upload.modes],
        },
    }


def _concept_pages():
    """Return all concept pages from 科技/ and 系列/ with their frontmatter."""
    import re
    result = []
    for d in CONCEPT_DIRS:
        dirpath = os.path.join(BASE, d)
        if not os.path.isdir(dirpath): continue
        for fname in os.listdir(dirpath):
            if not fname.endswith('.md') or fname == 'index.md': continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath) as f:
                    raw = f.read(3000)
                title = ''; summary = ''
                m = re.search(r'title:\s*(.+)', raw)
                if m: title = m.group(1).strip().strip('"').strip("'")
                m = re.search(r'description:\s*(.+)', raw)
                if m: summary = m.group(1).strip().strip('"').strip("'")
                result.append({
                    'id': f'{d}/{fname[:-3]}',
                    'title': title or fname[:-3],
                    'category': d,
                    'summary': summary,
                })
            except: pass
    return result


def _kb_tree():
    """Return the full directory tree of the knowledge base (cached)."""
    global _KBTREE_CACHE, _KBTREE_MTIME
    # Check if index.md has been modified since last build
    index_path = os.path.join(BASE, 'index.md')
    index_mtime = os.path.getmtime(index_path) if os.path.exists(index_path) else 0
    if _KBTREE_CACHE is not None and index_mtime <= _KBTREE_MTIME:
        return _KBTREE_CACHE

    import re
    def build_node(dirpath, rel_path):
        node = {'name': os.path.basename(dirpath), 'path': rel_path, 'children': []}
        try:
            items = sorted(os.listdir(dirpath))
        except:
            return node
        # index.md first
        for item in items:
            full = os.path.join(dirpath, item)
            if os.path.isdir(full):
                child_rel = os.path.join(rel_path, item) if rel_path else item
                node['children'].append(build_node(full, child_rel))
            elif item.endswith('.md'):
                child_rel = os.path.join(rel_path, item[:-3]) if rel_path else item[:-3]
                # Read title from frontmatter
                title = item[:-3]
                try:
                    with open(full) as f:
                        raw = f.read(500)
                    m = re.search(r'title:\s*(.+)', raw)
                    if m: title = m.group(1).strip().strip('"').strip("'")
                except: pass
                node['children'].append({
                    'name': title, 'path': child_rel, 'file': item,
                    'is_index': item == 'index.md',
                })
        # Sort: indexes first, then alphabetical
        node['children'].sort(key=lambda c: (not c.get('is_index', False), c['name']))
        return node

    tree = []
    for cat in cfg.categories:
        d = os.path.join(BASE, cat.dir)
        if os.path.isdir(d):
            tree.append(build_node(d, cat.dir))
    _KBTREE_CACHE = tree
    _KBTREE_MTIME = index_mtime
    return tree


def _save(path, data):
    with open(path, 'w') as f: json.dump(data, f, ensure_ascii=False, indent=2)

# ── Clean stale queue entries and reset error status on startup ──
_startup_q = _load(QUEUE, [])
if isinstance(_startup_q, list):
    _startup_q = {"files": _startup_q, "mode": "review"}
_startup_files = _startup_q.get("files", [])
_startup_names = [f["name"] if isinstance(f, dict) else f for f in _startup_files]
_startup_valid = [f for f in _startup_names if os.path.exists(os.path.join(UPLOADS, f))]
if len(_startup_valid) != len(_startup_names):
    # Rebuild file list with only valid entries, preserving dict format for entries that exist
    _startup_q["files"] = [e for e, n in zip(_startup_files, _startup_names) if n in _startup_valid]
    _save(QUEUE, _startup_q)
    print(f"[startup] cleaned stale queue: {len(_startup_names)}→{len(_startup_valid)} files")
# Reset status if it was left in error/idle from a previous run
_startup_status = _load(STATUS, {})
if _startup_status.get("phase") in ("error", "idle"):
    _save(STATUS, {"phase": "idle", "message": ""})
# Clean up stale history entries: mark "queued" entries not in queue as "skipped"
_startup_history = _load(HISTORY, [])
_queued_names = set()
for f in _startup_valid:
    _queued_names.add(f["name"] if isinstance(f, dict) else f)
_history_cleaned = 0
for entry in _startup_history:
    if entry.get("status") == "queued" and entry.get("name") not in _queued_names:
        entry["status"] = "skipped"
        entry["error"] = "队列丢失（服务器重启）"
        _history_cleaned += 1
if _history_cleaned:
    _save(HISTORY, _startup_history)
    print(f"[startup] cleaned stale history: {_history_cleaned} queued entries marked as skipped")
# Remember if we have pending files to re-trigger ingest (deferred until _trigger_ingest is defined)
_startup_has_queued_files = len(_startup_valid) > 0

def _resolve_slug(slug):
    """Resolve a slug to a file path, searching new directory structure as fallback."""
    fpath = os.path.join(BASE, slug + '.md')
    if os.path.isfile(fpath):
        return fpath
    # Fallback: search by filename across new directory structure
    filename = slug.split('/')[-1] + '.md'
    for scan_dir in ALL_CONTENT_DIRS:
        d = os.path.join(BASE, scan_dir)
        if not os.path.isdir(d): continue
        for root, dirs, files in os.walk(d):
            if filename in files:
                return os.path.join(root, filename)
    return None

def parse_page_content(fpath):
    """Parse a .md file into (fm_dict, body_str, raw_str). Used by handle_proposal_action."""
    with open(fpath) as f:
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
                    fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body, raw

def get_state():
    return _load(STATUS, {"phase": "idle", "message": "", "files": []})

def queue_files(files, mode='review'):
    with lock:
        q = _load(QUEUE, [])
        # Upgrade old list-format queue to dict format
        if isinstance(q, list):
            q = {"files": q, "mode": "review"}
        # Normalize files to dict format {name, uploaded_at}
        existing_names = {f["name"] if isinstance(f, dict) else f for f in q.get("files", [])}
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        for f in files:
            name = f["name"] if isinstance(f, dict) else f
            if name not in existing_names:
                q["files"].append({"name": name, "uploaded_at": now})
                existing_names.add(name)
        q["mode"] = mode  # last upload wins mode
        _save(QUEUE, q)
    _save(STATUS, {"phase": "queued", "message": f"{len(q.get('files', []))} 个文件等待处理...", "files": list(q)})

def add_history(entry):
    with lock:
        h = _load(HISTORY, [])
        # Update existing entry for same filename instead of creating duplicate
        name = entry.get("name", "")
        found = False
        for e in h:
            if e.get("name") == name:
                e.update(entry)
                found = True
                break
        if not found:
            h.insert(0, entry)
        _save(HISTORY, h)

def _trigger_ingest():
    """Start a background thread to run regenerate-graph.py if not already running.
    After completion, re-checks the queue in case new files arrived during processing."""
    with ingest_lock:
        if not _acquire_ingest_lock():
            return

    def _run():
        retry_count = 0
        try:
            prev_queue = None
            while True:
                q = _load(QUEUE, [])
                # Normalize queue format: old list → new dict
                if isinstance(q, list):
                    q = {"files": q, "mode": "review"}
                # Normalize file entries: strings → {name, uploaded_at}
                raw_files = q.get("files", [])
                files = [f["name"] if isinstance(f, dict) else f for f in raw_files]
                if not files:
                    break
                # Don't retry the same queue more than once
                if files == prev_queue:
                    retry_count += 1
                    if retry_count >= 2:
                        print(f"[ingest] retried twice — giving up: {', '.join(files)}")
                        _save(QUEUE, {"files": [], "mode": q.get("mode", "review")})
                        _save(STATUS, {"phase": "error", "message": f"处理失败，{len(files)} 个文件已跳过"})
                        break
                    print(f"[ingest] retry #{retry_count} for: {', '.join(files)}")
                else:
                    retry_count = 0
                prev_queue = list(files)
                mode = q.get("mode", "review")
                mode_tag = "（AI 自动收录）" if mode == 'direct' else ""
                _save(STATUS, {"phase": "processing", "message": f"正在处理 {len(files)} 个文件...{mode_tag}"})
                print(f"[ingest] processing {len(files)} file(s): {', '.join(files)}")
                result = subprocess.run(
                    ['python3', os.path.join(BASE, 'regenerate-graph.py')],
                    capture_output=True, text=True, timeout=43200, cwd=BASE
                )
                if result.returncode != 0:
                    print(f"[ingest] error (exit {result.returncode}): {result.stderr[:500]}")
                    _save(STATUS, {"phase": "error", "message": f"处理失败 (exit {result.returncode})"})
                else:
                    print(f"[ingest] ok: {result.stdout.strip()[-200:]}")
                    # regenerate-graph.py manages queue now — just reload for next iteration
                    prev_queue = None
                    _update_history_status(files, "done")
        except subprocess.TimeoutExpired:
            print("[ingest] timeout after 12h")
            _save(STATUS, {"phase": "error", "message": "处理超时 (12小时)"})
        except Exception as e:
            print(f"[ingest] exception: {e}")
            _save(STATUS, {"phase": "error", "message": f"处理异常: {str(e)[:200]}"})
        finally:
            _release_ingest_lock()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

def _update_history_status(files, status):
    """Update upload-history entries for processed files."""
    try:
        h = _load(HISTORY, [])
        updated = False
        for entry in h:
            if entry.get("name") in files and entry.get("status") == "queued":
                entry["status"] = status
                updated = True
        if updated:
            _save(HISTORY, h)
    except Exception:
        pass

def _gbrain_search_raw(query, limit=10):
    """Local Wiki keyword search (gbrain-compatible return shape)."""
    return wiki_search.search(query, limit=limit)


def _rewrite_query(question, timeout=8):
    """Use DeepSeek to rewrite a natural-language question into search-optimized keywords.
       Returns a list of keyword strings, or empty list on failure."""
    if not DEEPSEEK_API_KEY:
        return []
    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "你是 " + cfg.brand.name + " 产品搜索关键词提取器。把用户问题转为空格分隔的搜索关键词。\n"
                        "规则:\n"
                        "- 只输出关键词，不要解释\n"
                        "- 移除疑问词和语气词（怎么、什么、吗、呢、推荐、适合）\n"
                        "- 保留专业术语、产品名、品类名、适应症、技术名等原词\n"
                        "- 提取隐含需求：根据上下文补充相关搜索词\n"
                        "- 输出 2-5 个关键词，空格分隔"
                    )},
                    {"role": "user", "content": question},
                ],
                "temperature": 0.2,
                "max_tokens": 60,
            },
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=timeout,
        )
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        # Split into individual terms, filter noise
        terms = []
        for t in text.split():
            t = t.strip().rstrip('，,。.')
            if len(t) >= 2:
                terms.append(t)
        return terms
    except Exception:
        return []


def _gbrain_query_raw(query, limit=10):
    """Local Wiki search (no separate semantic engine)."""
    return wiki_search.search(query, limit=limit)


def _gbrain_run(mode, query, limit=10):
    """Compatibility shim — both modes use local_wiki_search."""
    return wiki_search.search(query, limit=limit)


def _extract_keywords(question):
    """Extract meaningful search keywords from a Chinese/English question
       using jieba word segmentation + English word extraction.
       Noise words are stripped; remaining Chinese words and English tokens
       form the keyword list, plus adjacent-word bigrams for compound concepts."""
    noise = {'的', '是', '什么', '怎么', '为什么', '哪些', '如何', '吗', '呢', '了',
             '有', '在', '和', '与', '用', '请', '可以', '能', '告诉', '我', '你', '它',
             '这个', '那个', '一下', '区别', '不同', '比较', '介绍', '说明',
             '请问', '有没有', '能否', '帮我', '我想', '想知道', '了解', '推荐',
             '适合', '穿', '哪个', '哪种', '哪款', '哪里', '怎样', '什么样'}

    # 1. Extract English / alphanumeric tokens
    en_words = re.findall(r'[A-Za-z0-9+-]+', question)

    # 2. Strip noise words → clean Chinese text
    clean = question
    for n in sorted(noise, key=len, reverse=True):
        clean = clean.replace(n, ' ')

    # 3. jieba segment → keep words with ≥2 chars that contain Chinese
    cn_words = []
    for w in jieba.cut(clean):
        w = w.strip()
        if len(w) >= 2 and re.search(r'[\u4e00-\u9fff]', w):
            cn_words.append(w)

    # 4. Adjacent-word bigrams — capture compound concepts
    #    (e.g. "跑步" + "膝盖" → "跑步膝盖", "碳板" + "跑鞋" → "碳板跑鞋")
    bigrams = []
    for i in range(len(cn_words) - 1):
        bigrams.append(cn_words[i] + cn_words[i + 1])

    # 5. Assemble: English words → full Chinese words → bigrams
    keywords = []
    for w in en_words:
        if len(w) >= 2:
            keywords.append(w)
    for w in cn_words:
        keywords.append(w)
    for bg in bigrams:
        keywords.append(bg)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for k in keywords:
        if k.lower() not in seen:
            seen.add(k.lower())
            unique.append(k)

    if len(unique) < 2:
        return [question]
    return unique


def gbrain_search(question, limit=10, extra_terms=None):
    """Local dual-pass Wiki search (keyword terms + full question).

    Keeps the historical name for call-site compatibility; backend is local_wiki_search.
    extra_terms: optional entity names from rewrite_meta for FTS boost.
    """
    jieba_kw = _extract_keywords(question)
    llm_kw = _rewrite_query(question)
    boost = [t for t in (extra_terms or []) if isinstance(t, str) and len(t.strip()) >= 2]

    all_kw = []
    seen = set()
    for k in boost + llm_kw + jieba_kw:
        if k.lower() not in seen and len(k) >= 2:
            seen.add(k.lower())
            all_kw.append(k)
    kw_terms = all_kw[:5] or [question]

    _GENERIC_TERMS = {'系列', '鞋款', '产品', '科技', '推荐', '选择', '比赛',
                      '新款', '经典', '系列鞋款', '什么', '区别', '哪些', '药品'}

    slug_best = {}
    _META_SLUGS = {'tag_taxonomy', 'log', 'schema', 'tag-taxonomy', '关系索引'}
    _NOISE_PATTERNS = ('/index', '_uploads/', 'articles/')

    def _add_results(results):
        for r in results:
            slug = r['slug']
            if slug in _META_SLUGS or slug.startswith(('tag_taxonomy', 'log', 'schema')):
                continue
            if any(p in slug for p in _NOISE_PATTERNS):
                continue
            if slug not in slug_best or r['score'] > slug_best[slug]['score']:
                slug_best[slug] = r

    _add_results(wiki_search.search(question, limit=limit))
    for term in kw_terms:
        if term in _GENERIC_TERMS:
            continue
        _add_results(wiki_search.search(term, limit=limit if term == kw_terms[0] else 8))

    # Entity / product seeking boost (medical)
    _ENTITY_SEEKING = re.compile(
        r'产品|型号|有哪些|哪几款|哪些款|哪款|推荐|清单|列表|药品|处方药|OTC'
    )
    if _ENTITY_SEEKING.search(question):
        for r in slug_best.values():
            if any(r['slug'].startswith(p + '/') for p in PRODUCT_DIRS):
                r['score'] *= 1.15

    merged = sorted(slug_best.values(), key=lambda r: r['score'], reverse=True)
    return merged[:limit]


def gbrain_get(slug):
    """Get full page content from local Wiki filesystem."""
    return wiki_search.get(slug)


def gbrain_sync():
    """Rebuild local Wiki search corpus (replaces gbrain import)."""
    try:
        wiki_search.sync()
    except Exception as e:
        print(f"[sync] local wiki index error: {e}")


def apply_graph_recall(question, context_parts, seen_slugs, sse=None, search_boost=True):
    """Phase 4: if question is in medical graph slice, recall Neo4j facts + 原文 pages.

    - Graph returns entities / structured facts (召回)
    - Local clinical/bridge Markdown pages are injected as 原文
    - Entity names optionally re-query local Wiki for product KB overlap
    Returns GraphRecallResult (hit may be False).
    """
    result = graph_recall.recall(question)
    if not result.hit:
        return result

    detail = result.title
    if result.layer:
        detail = f"[{result.layer}] {detail}"
    if result.error:
        detail = f"{result.title} (Neo4j 不可用: {result.error[:80]})"
    elif result.entities:
        detail = f"{detail} → {', '.join(result.entities[:8])}"
    if sse:
        try:
            sse('step', {'id': 0, 'type': 'searching', 'action': '🕸',
                         'detail': f'图谱召回: {detail}'})
        except Exception:
            pass
    print(f"[graph-recall] hit layer={result.layer} template={result.template_id} entities={result.entities} err={result.error!r}", flush=True)

    # Prepend structured graph facts
    if result.facts_text:
        context_parts.insert(0, result.facts_text)

    # Inject 原文 markdown for recalled entities
    for slug in result.source_slugs:
        if slug in seen_slugs:
            continue
        body = graph_recall.load_source_page(slug)
        if not body:
            continue
        seen_slugs.add(slug)
        context_parts.insert(1 if result.facts_text else 0, f"## {slug}\n{body}")
        if sse:
            try:
                sse('step', {'id': 0, 'type': 'reading', 'action': '📄',
                             'detail': f'原文 {slug}'})
            except Exception:
                pass

    # Boost local search with entity names (keyword only — no LLM rewrite)
    if search_boost and result.entities:
        for ent in result.entities[:5]:
            boosted = []
            boosted.extend(_gbrain_search_raw(ent, limit=3))
            boosted.extend(_gbrain_query_raw(ent, limit=2))
            for r in boosted:
                if r['slug'] in seen_slugs:
                    continue
                # clinical/bridge already loaded from filesystem
                if any(r['slug'].startswith(d + '/') for d in LOCAL_SOURCE_DIRS):
                    continue
                full = gbrain_get(r['slug'])
                if full and len(full) > 50:
                    body = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                    seen_slugs.add(r['slug'])
                    context_parts.append(f"## {r['slug']}\n{body[:6000]}")

    return result


_GRAPH_ANSWER_NOTE = (
    "\n- 若上下文含「图谱召回」块：那是 Neo4j 多跳演示结果（假数据）。"
    "请优先依据临床层（临床病例/用药安全）与桥接层（疾病/成分）原文回答，"
    "并注明这是演示图谱线索，不是临床建议。\n"
)

_ANTI_HALLUCINATION_NOTE = (
    "\n- 禁止编造知识库中不存在的：生产批号、COA 报告、CAS 号、"
    "未上市试验药数据、临床试验终点（ORR/DFS/PK 参数）、未收录患者或药品。\n"
    "- 库中无依据时必须明确说明「知识库未找到相关记录」，不得用训练知识补全。\n"
)

_NO_KB_MARKERS = ("(未找到相关内容)", "(未找到)")

_FICTIONAL_INDICATION_RE = re.compile(
    r"虚构|罕见基因|基因缺陷|\[虚构",
    re.I,
)

_OUT_OF_SCOPE_RE = re.compile(
    r"ABC-123|未上市试验|双盲试验|临床试验结果|"
    r"COA|出厂报告|批号\s*[A-Z]{3}-\d+|"
    r"今天天气怎么样|system\s*prompt",
    re.I,
)

_FICTIONAL_PATIENT_NAMES = frozenset({"小明", "小红", "小刚", "张三"})


def _unknown_patient_name(question: str) -> Optional[str]:
    """Return unknown patient name when question is patient-specific."""
    if not question:
        return None
    for name in _FICTIONAL_PATIENT_NAMES:
        if name in question:
            return name
    if not re.search(r"能否用|能不能|可不可以|患者", question):
        return None
    for p in graph_recall.PATIENTS:
        if p in question:
            return None
    m = re.search(r"[「『]([^」』]{2,4})[」』]", question)
    if m:
        cand = m.group(1).strip()
        if cand and cand not in graph_recall.PATIENTS:
            return cand
    return None


def _should_force_reject(question: str, graph_hit, context_parts: list) -> bool:
    if _unknown_patient_name(question):
        return True
    if _FICTIONAL_INDICATION_RE.search(question):
        return True
    if _OUT_OF_SCOPE_RE.search(question) and not getattr(graph_hit, "hit", False):
        return True
    if _context_is_empty(context_parts):
        return True
    ctx = "\n\n".join(context_parts)
    if ctx.strip() in _NO_KB_MARKERS:
        return True
    return False


def _rejection_answer(lang: str) -> str:
    if lang == 'en':
        return (
            "No relevant records were found in the knowledge base for this question. "
            "Try specifying a patient name, drug, or product series, or confirm the content is indexed."
        )
    return (
        "知识库中未找到与您问题相关的记录。"
        "请尝试补充具体患者名、药品名或产品系列，或确认该内容是否已入库。"
    )


def _context_is_empty(context_parts: list) -> bool:
    if not context_parts:
        return True
    substantive = [
        p for p in context_parts
        if len(re.sub(r'^【图谱召回.*?】\s*', '', p, flags=re.DOTALL).strip()) > 60
    ]
    return len(substantive) == 0


def _parse_rewrite_meta(body: dict) -> dict:
    raw = body.get('rewrite_meta') or {}
    if not isinstance(raw, dict):
        return {}
    entities = raw.get('entities') or []
    return {
        'intent_hint': str(raw.get('intent_hint') or '').strip(),
        'entities': [str(x) for x in entities if x],
        'confidence': raw.get('confidence'),
    }


def _emit_rewrite_meta_step(sse, rewrite_meta: dict, lang: str = 'zh') -> None:
    if not rewrite_meta:
        return
    hint = rewrite_meta.get('intent_hint') or ''
    entities = rewrite_meta.get('entities') or []
    conf = rewrite_meta.get('confidence')
    parts = []
    if hint:
        parts.append(f"改写意图: {hint}" if lang == 'zh' else f"Rewrite intent: {hint}")
    if entities:
        ent = ', '.join(entities[:8])
        parts.append(f"实体: {ent}" if lang == 'zh' else f"Entities: {ent}")
    if conf is not None:
        parts.append(f"置信度: {conf}" if lang == 'zh' else f"Confidence: {conf}")
    if not parts:
        return
    try:
        sse('step', {
            'id': 0,
            'type': 'planning',
            'action': '✏️',
            'detail': ' · '.join(parts),
            'rewrite_meta': rewrite_meta,
        })
    except Exception:
        pass


def _emit_graph_template_step(sse, graph_hit, lang: str = 'zh') -> None:
    if not graph_hit.hit or not graph_hit.template_id:
        return
    label = graph_hit.template_id
    detail = f"图谱模板: {label}" if lang == 'zh' else f"Graph template: {label}"
    try:
        sse('step', {
            'id': 0,
            'type': 'searching',
            'action': '🕸',
            'detail': detail,
            'graph_template': label,
        })
    except Exception:
        pass

_FORCE_LOCAL_RE = re.compile(
    r'禁忌|成分|相关药|相关产品|过敏|相互作用|含.*成分|哪些药|不能用|不宜'
)

_GRAPH_CONFIDENT = frozenset({
    "drug_overview",
    "ingredient_contraindications",
    "products_by_ingredient",
    "allergies_to_drug",
    "product_in_series",
    "product_ingredients",
    "product_overview",
    "cross_patient_product_contra",
    "patient_unsafe_meds",
})


def _resolve_series_concept_slug(question: str) -> Optional[str]:
    """Locate series overview Wiki slug from question (entity map + config-driven fallbacks)."""
    direct = graph_recall.series_slug_for_question(question)
    if direct:
        return direct
    m = re.search(r'([A-Za-z0-9\u4e00-\u9fff]+?)\s*系列', question)
    if not m:
        return None
    fragment = m.group(1).strip()
    for pattern in graph_recall._series_slug_candidates(fragment):
        content = gbrain_get(pattern)
        if content and len(content) > 50:
            return pattern
    return None


def _need_local_search(question: str, graph_hit, context_parts: list) -> bool:
    """When to supplement graph recall with local FTS."""
    if not graph_hit.hit or len(context_parts) < 4:
        return True
    if not graph_recall.template_matches_question(
        question, graph_hit.template_id, graph_hit.entities
    ):
        return True
    if _FORCE_LOCAL_RE.search(question):
        if graph_hit.template_id in _GRAPH_CONFIDENT:
            return False
        return True
    return False


def _inject_series_coverage_if_needed(graph_hit, context_parts, seen_slugs, sse=None):
    """If IN_SERIES edges are incomplete, inject series overview page."""
    gap_slug = graph_recall.series_coverage_gap(graph_hit)
    if not gap_slug or gap_slug in seen_slugs:
        return
    body = graph_recall.load_source_page(gap_slug)
    if not body:
        return
    seen_slugs.add(gap_slug)
    context_parts.append(f"## {gap_slug}\n{body}")
    if sse:
        try:
            sse('step', {'id': 0, 'type': 'reading', 'action': '📋',
                         'detail': f'系列边不全，补拉概览页 {gap_slug}'})
        except Exception:
            pass


def expand_concept_links(context_parts, seen_slugs, max_extra=4, sse=None):
    """Follow wikilinks from concept pages already in context."""
    added = 0
    for part in context_parts[:]:
        m = re.match(r'^## (.+)$', part, re.MULTILINE)
        if not m: continue
        slug = m.group(1).strip()
        if not any(slug.startswith(d + '/') for d in CONCEPT_DIRS + PRODUCT_DIRS): continue
        full_page = gbrain_get(slug)
        if not full_page: continue
        body = re.sub(r'^---.*?---\s*', '', full_page, flags=re.DOTALL)
        linked = set()
        for link in re.findall(r'\[\[([^\]]+?)(?:\||\]\])', body):
            linked.add(link.strip())
        for target in linked:
            if added >= max_extra: break
            # When expanding from a product page, only follow 科技/ links
            is_product = not (slug.startswith('系列/') or slug.startswith('科技/'))
            if is_product and not target.startswith('科技/'):
                continue
            if target in seen_slugs: continue
            full = gbrain_get(target)
            if full and len(full) > 80:
                seen_slugs.add(target)
                body_text = re.sub(r'^---.*?---\\s*', '', full, flags=re.DOTALL)
                context_parts.append(f"## {target}\\n{body_text[:10000]}")
                added += 1
                if sse:
                    sse('step', {'id': 90 + added, 'type': 'reading', 'action': '🔗',
                                 'detail': f'展开概念: {target}'})
    return added

class HubHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE, **kwargs)

    def end_headers(self):
        if 'Cache-Control' not in self._headers_buffer_str():
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

    def _headers_buffer_str(self):
        return b''.join(self._headers_buffer).decode('latin-1')

    def _reject_write(self):
        """Return 403 if READ_ONLY mode is active. Call at top of write endpoints."""
        if READ_ONLY:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "error": "写入操作已禁用（READ_ONLY 模式）。如需管理知识库，请通过本地端口访问。",
                "read_only": True
            }, ensure_ascii=False).encode())
            return True
        return False

    def _check_qa_rate(self):
        """Return 429 if Q&A rate limit exceeded. Thread-safe via qa_lock."""
        if QA_RATE_LIMIT <= 0:
            return False
        with qa_lock:
            now = time.time()
            window = 60  # 1-minute sliding window
            cutoff = now - window
            while _qa_timestamps and _qa_timestamps[0] < cutoff:
                _qa_timestamps.pop(0)
            if len(_qa_timestamps) >= QA_RATE_LIMIT:
                retry_after = int(window - (now - _qa_timestamps[0])) + 1
                self.send_response(429)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Retry-After', str(retry_after))
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": f"请求过于频繁，每分钟最多 {QA_RATE_LIMIT} 次问答。请稍后再试。",
                    "retry_after_seconds": retry_after
                }, ensure_ascii=False).encode())
                return True
            _qa_timestamps.append(now)
        return False

    # ── Portal auth ──
    _LOGIN_PAGE = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{cfg.brand.public_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,system-ui,sans-serif;background:#0a0a0a;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.login-box{{background:#141414;border:1px solid #2a2a2a;border-radius:12px;padding:48px;width:360px;max-width:90vw;text-align:center}}
.login-box h1{{font-size:20px;font-weight:600;margin-bottom:8px}}
.login-box .subtitle{{font-size:13px;color:#888;margin-bottom:32px}}
.login-box input{{width:100%;padding:12px 16px;background:#1a1a1a;border:1px solid #333;border-radius:8px;color:#fff;font-size:15px;outline:none}}
.login-box input:focus{{border-color:#555}}
.login-box button{{width:100%;padding:12px;margin-top:16px;background:#fff;color:#000;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer}}
.login-box button:hover{{background:#e0e0e0}}
.login-box .error{{color:#ff5555;font-size:13px;margin-top:12px;display:none}}
</style></head><body>
<div class="login-box">
<h1>{cfg.brand.public_name}</h1>
<p class="subtitle">请输入访问密码</p>
<form id="f"><input type="password" id="pwd" placeholder="密码" autofocus><button type="submit">进入</button></form>
<p class="error" id="err">密码错误，请重试</p>
</div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{{e.preventDefault()
const r=await fetch('/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{password:document.getElementById('pwd').value}})}})
r.ok?window.location.href='/portal':(document.getElementById('err').style.display='block',document.getElementById('pwd').value='')}})
</script></body></html>"""

    _PORTAL_PAGE = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{cfg.brand.public_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,system-ui,sans-serif;background:#0a0a0a;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.portal{{text-align:center;max-width:500px;width:90vw}}
.portal h1{{font-size:22px;font-weight:600;margin-bottom:4px}}
.portal .subtitle{{font-size:13px;color:#666;margin-bottom:36px}}
.cards{{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}}
.card{{background:#141414;border:1px solid #2a2a2a;border-radius:12px;padding:32px 24px;width:200px;cursor:pointer;text-decoration:none;color:#e0e0e0;transition:border-color .2s}}
.card:hover{{border-color:#555}}
.card-icon{{font-size:36px;margin-bottom:12px}}
.card-title{{font-size:16px;font-weight:600;margin-bottom:6px}}
.card-desc{{font-size:12px;color:#666}}
.logout{{margin-top:32px;font-size:12px;color:#666}}
.logout a{{color:#888;text-decoration:none}}
.logout a:hover{{color:#fff}}
</style></head><body>
<div class="portal">
<h1>{cfg.brand.public_name}</h1>
<p class="subtitle">选择要访问的功能</p>
<div class="cards">
<a class="card" href="/product-hub.html"><div class="card-icon">🧠</div><div class="card-title">产品中心</div><div class="card-desc">Q&A 智能问答 · 知识搜索 · 自检计划</div></a>
<a class="card" href="/knowledge-graph-3d.html"><div class="card-icon">🌐</div><div class="card-title">3D 知识图谱</div><div class="card-desc">可视化浏览概念、系列、产品关联</div></a>
</div>
<p class="logout"><a href="/logout">退出登录</a></p>
</div></body></html>"""

    def _check_auth(self):
        cookie_str = self.headers.get('Cookie', '')
        if not cookie_str:
            return False
        try:
            c = http_cookies.SimpleCookie()
            c.load(cookie_str)
            token = c.get(_AUTH_COOKIE_NAME)
            return token and token.value == _AUTH_COOKIE_SECRET
        except Exception:
            return False

    def _set_auth_cookie(self):
        c = http_cookies.SimpleCookie()
        c[_AUTH_COOKIE_NAME] = _AUTH_COOKIE_SECRET
        c[_AUTH_COOKIE_NAME]['path'] = '/'
        c[_AUTH_COOKIE_NAME]['httponly'] = True
        c[_AUTH_COOKIE_NAME]['max-age'] = 86400 * 30
        self.send_header('Set-Cookie', c.output(header='', sep='; '))

    def _serve_login_page(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(self._LOGIN_PAGE.encode())

    def _serve_portal_page(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(self._PORTAL_PAGE.encode())

    def handle_login(self):
        # ── Rate limiting: check lockout and attempts ──
        client_ip = self.client_address[0]
        now = time.time()
        with _LOGIN_LOCK:
            # Check if IP is locked out
            lockout_until = _LOGIN_LOCKOUT.get(client_ip, 0)
            if lockout_until > now:
                remaining = int(lockout_until - now)
                self.send_response(429)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    "ok": False, "error": f"登录尝试过多，请 {remaining} 秒后再试",
                    "retry_after_seconds": remaining
                }, ensure_ascii=False).encode())
                return
            # Clean old attempts (older than 60s)
            attempts = _LOGIN_ATTEMPTS.get(client_ip, [])
            cutoff = now - 60
            attempts = [t for t in attempts if t > cutoff]
            _LOGIN_ATTEMPTS[client_ip] = attempts

        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        pwd = body.get('password', '')

        if pwd == _PORTAL_PASSWORD:
            # Success: clear attempts
            with _LOGIN_LOCK:
                _LOGIN_ATTEMPTS.pop(client_ip, None)
                _LOGIN_LOCKOUT.pop(client_ip, None)
            self.send_response(200)
            self._set_auth_cookie()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        else:
            # Failure: record attempt, maybe lock out
            with _LOGIN_LOCK:
                attempts = _LOGIN_ATTEMPTS.get(client_ip, [])
                cutoff = now - 60
                attempts = [t for t in attempts if t > cutoff]
                attempts.append(now)
                _LOGIN_ATTEMPTS[client_ip] = attempts
                remaining = max(0, 5 - len(attempts))
                if len(attempts) >= 10:
                    _LOGIN_LOCKOUT[client_ip] = now + 900  # 15 min
                    self.send_response(429)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "ok": False,
                        "error": "登录尝试过多，已锁定 15 分钟",
                        "retry_after_seconds": 900
                    }, ensure_ascii=False).encode())
                    return
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": False,
                "error": f"密码错误（还剩 {remaining} 次尝试）" if remaining <= 2 else "密码错误"
            }, ensure_ascii=False).encode())

    def handle_logout(self):
        c = http_cookies.SimpleCookie()
        c[_AUTH_COOKIE_NAME] = ''
        c[_AUTH_COOKIE_NAME]['path'] = '/'
        c[_AUTH_COOKIE_NAME]['max-age'] = 0
        self.send_response(302)
        self.send_header('Set-Cookie', c.output(header='', sep='; '))
        self.send_header('Location', '/login')
        self.end_headers()

    def do_GET(self):
        # Public endpoints (no auth required)
        if self.path == '/login' or self.path == '/':
            self._serve_login_page()
        elif self.path == '/portal':
            if self._check_auth():
                self._serve_portal_page()
            else:
                self._serve_login_page()
        elif self.path == '/logout':
            self.handle_logout()
        elif self.path == '/status':
            self._json(get_state())
        elif self.path == '/api/config':
            # Public: expose brand config to frontend (no auth required)
            self._json(_public_config())
        elif self.path == '/api/concept-pages':
            # Public: list all concept pages (used by tag view for real-time display)
            self._json(_concept_pages())
        elif self.path == '/api/kb-tree':
            # Public: full directory tree for knowledge base overview
            self._json(_kb_tree())
        elif self.path.startswith('/api/'):
            # API routes — auth required
            if not self._check_auth():
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "authentication required"}).encode())
                return
            if self.path.startswith('/api/page'):
                self.handle_page_get()
            elif self.path == '/api/issues':
                self.handle_issues()
            elif self.path == '/api/enrich-status':
                self.handle_enrich_status()
            elif self.path == '/api/proposals':
                self.handle_proposals()
            elif self.path == '/api/tasks':
                self.handle_tasks()
            else:
                self.send_error(404)
        elif self.path == '/knowledge-graph.html':
            self.send_response(301)
            self.send_header('Location', '/product-hub.html')
            self.end_headers()
        elif self.path in ('/history', '/queue'):
            if not self._check_auth():
                self._serve_login_page()
                return
            if self.path == '/history':
                self._json({"history": _load(HISTORY, [])})
            else:
                self._json({"queue": _load(QUEUE, [])})
        else:
            # Static files — auth required
            if not self._check_auth():
                self._serve_login_page()
            else:
                super().do_GET()

    def _check_post_auth(self):
        """Check auth for POST write endpoints. Sends 401 JSON and returns True if unauthenticated."""
        if not self._check_auth():
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "authentication required"}).encode())
            return True
        return False

    def do_POST(self):
        # Strip query string for routing — handlers parse params themselves
        path = self.path.split('?')[0]
        # Public endpoints (no auth required)
        if path == '/login':
            self.handle_login()
        elif path == '/ask':
            if self._check_qa_rate(): return
            self.handle_ask()
        elif path == '/ask-stream':
            if self._check_qa_rate(): return
            self.handle_ask_stream()
        elif path == '/ask-deep':
            if self._check_qa_rate(): return
            self.handle_ask_deep()
        elif path == '/ask-rewrite':
            if self._check_qa_rate(): return
            self.handle_ask_rewrite()
        # All write endpoints — auth required
        elif path == '/upload':
            if self._check_post_auth(): return
            self.handle_upload()
        elif path == '/history/clear':
            if self._check_post_auth(): return
            if self._reject_write(): return
            _save(HISTORY, [])
            self._json({"ok": True})
        elif path == '/api/save':
            if self._check_post_auth(): return
            self.handle_save()
        elif path in ('/api/proposals/approve', '/api/proposals/reject'):
            if self._check_post_auth(): return
            self.handle_proposal_action()
        elif path == '/api/run-check':
            if self._check_post_auth(): return
            self.handle_run_check()
        elif path == '/api/run-improve':
            if self._check_post_auth(): return
            self.handle_run_improve()
        elif path == '/api/run-improve-concepts':
            if self._check_post_auth(): return
            self.handle_run_improve_concepts()
        elif path == '/api/tasks/run':
            if self._check_post_auth(): return
            self.handle_tasks_run()
        else:
            self.send_error(404)

    # ── Proposal endpoints ──
    def handle_proposals(self):
        """GET /api/proposals — list all proposals."""
        props_dir = os.path.join(BASE, '_proposals')
        proposals = []
        if os.path.isdir(props_dir):
            for fn in sorted(os.listdir(props_dir)):
                if fn.endswith('.json'):
                    with open(os.path.join(props_dir, fn)) as f:
                        proposals.append(json.load(f))
        self._json(proposals)

    def handle_proposal_action(self):
        """POST /api/proposals/approve or /reject — {slug, status}."""
        if self._reject_write(): return
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        slug = body.get('slug', '')
        action = 'approve' if self.path.endswith('/approve') else 'reject'
        
        safe_name = slug.replace('/', '_')
        prop_path = os.path.join(BASE, '_proposals', f"{safe_name}.json")
        if not os.path.exists(prop_path):
            self._json({"ok": False, "error": "proposal not found"}); return
        
        with open(prop_path) as f:
            proposal = json.load(f)
        
        if action == 'approve':
            # Apply the proposed content to the actual page(s)
            try:
                is_upload = proposal.get('source') == 'upload'
                is_concept = proposal.get('source') == 'concept-proposal'
                is_pi = proposal.get('source') == 'pi-ingest'
                is_create = proposal.get('action') == 'create'
                pages = proposal.get('pages') or []

                def _write_full_md(target_slug, proposed_content, create=True):
                    if not proposed_content:
                        raise ValueError(f"empty content for {target_slug}")
                    content = proposed_content
                    if content.strip().startswith('```'):
                        lines = content.strip().split('\n')
                        if lines[0].startswith('```'):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == '```':
                            lines = lines[:-1]
                        content = '\n'.join(lines).strip() + '\n'
                    safe = target_slug.replace('/', '_')
                    fpath = os.path.join(BASE, target_slug + '.md')
                    if create:
                        os.makedirs(os.path.dirname(fpath), exist_ok=True)
                    else:
                        resolved = _resolve_slug(target_slug)
                        if not resolved:
                            raise ValueError(f"page not found: {target_slug}")
                        fpath = resolved
                    if os.path.isfile(fpath):
                        backup_dir = os.path.join(BASE, '_backups')
                        os.makedirs(backup_dir, exist_ok=True)
                        ts = time.strftime('%Y%m%d_%H%M%S')
                        shutil.copy2(fpath, os.path.join(backup_dir, f"{safe}.{ts}.md"))
                    with open(fpath, 'w') as f:
                        f.write(content)
                    return fpath

                if pages:
                    # Multipage package (说明书 / PI)
                    written = []
                    for page in pages:
                        pslug = page.get('slug') or ''
                        pcontent = page.get('proposed_content') or ''
                        _write_full_md(pslug, pcontent, create=True)
                        written.append(pslug)
                    proposal['written_slugs'] = written
                elif is_upload or is_concept or is_pi:
                    proposed_content = proposal.get('proposed_content', '')
                    if not proposed_content and proposal.get('content'):
                        # Rebuild from legacy upload fields
                        fm = dict(proposal.get('frontmatter') or {})
                        fm['title'] = proposal.get('title') or slug.split('/')[-1]
                        import yaml as _yaml
                        yml = _yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
                        proposed_content = f"---\n{yml}\n---\n\n{proposal.get('content','')}\n"
                    if is_concept and proposed_content.strip().startswith('```'):
                        lines = proposed_content.strip().split('\n')
                        if lines[0].startswith('```'): lines = lines[1:]
                        if lines and lines[-1].strip() == '```': lines = lines[:-1]
                        proposed_content = '\n'.join(lines).strip() + '\n'
                    _write_full_md(slug, proposed_content, create=is_create or is_upload or is_pi)
                else:
                    # Existing enrich/improve proposal logic
                    proposed_content = proposal.get('proposed_content', '')
                    fpath = _resolve_slug(slug)
                    if not fpath:
                        self._json({"ok": False, "error": "page not found"}); return

                    fm, old_body, raw = parse_page_content(fpath)

                    # Handle improve proposals (targeted fragment replacement)
                    if proposal.get('source') == 'improve' and proposal.get('original_fragment'):
                        old_fragment = proposal['original_fragment']
                        new_fragment = proposal.get('suggested_change', '')
                        if old_fragment and new_fragment:
                            if old_fragment in raw:
                                new_raw = raw.replace(old_fragment, new_fragment, 1)
                            else:
                                # Convert proposal's [[concepts/X|Y]] → page's [Y](/dir/X.md) format
                                # Try both 系列/ and 科技/ prefixes
                                def _to_page_fmt(text, prefix):
                                    return re.sub(
                                        r'\[\[concepts/([^\]|]+)\|([^\]]+)\]\]',
                                        r'[\2](/' + prefix + r'/\1.md)', text)
                                matched = False
                                for prefix in CONCEPT_DIRS:
                                    frag_pf = _to_page_fmt(old_fragment, prefix)
                                    if frag_pf in raw:
                                        new_raw = raw.replace(frag_pf, _to_page_fmt(new_fragment, prefix), 1)
                                        matched = True
                                        break
                                if not matched:
                                    # Looser: whitespace-insensitive match
                                    old_clean = re.sub(r'\s+', ' ', old_fragment).strip()
                                    raw_clean = re.sub(r'\s+', ' ', raw)
                                    if old_clean in raw_clean:
                                        idx = raw_clean.index(old_clean)
                                        end = idx + len(old_clean)
                                        new_raw = raw[:idx] + new_fragment + raw[end:]
                                    else:
                                        self._json({"ok": False, "error": "fragment not found in page"}); return
                        else:
                            self._json({"ok": False, "error": "missing fragment data"}); return
                    else:
                        # Old-style TODO fill replacement
                        new_content = proposal['proposed_content']
                        new_body = old_body
                        if new_body.count('## 编译概要') > 1:
                            new_body = re.sub(r'## 编译概要\s*\n\s*\n(?=## 编译概要)', '', new_body, count=1)
                        pattern = r'##\s*编译概要\s*\n.*?(?=\n##\s|\Z)'
                        replacement = f'## 编译概要\n\n{new_content}'
                        new_body = re.sub(pattern, replacement, new_body, count=1, flags=re.DOTALL)
                        fm_block = raw.split('---', 2)[1] if raw.startswith('---') else ''
                        new_raw = f'---\n{fm_block}---\n{new_body}' if fm_block else new_body

                    # Backup
                    backup_dir = os.path.join(BASE, '_backups')
                    os.makedirs(backup_dir, exist_ok=True)
                    ts = time.strftime('%Y%m%d_%H%M%S')
                    shutil.copy2(fpath, os.path.join(backup_dir, f"{safe_name}.{ts}.md"))

                    # Write
                    with open(fpath, 'w') as f:
                        f.write(new_raw)
                
                proposal['status'] = 'approved'
                proposal['approved_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                
                # Log
                log_path = os.path.join(BASE, 'log.md')
                today = time.strftime('%Y-%m-%d')
                n_pages = len(proposal.get('written_slugs') or [])
                entry = f"\n- [approved] {today} {slug} — 审核通过，应用提案" + (f"（{n_pages} 页）" if n_pages else "")
                if os.path.exists(log_path):
                    with open(log_path) as f:
                        lt = f.read()
                    lt = lt.replace(f'## {today}', f'## {today}{entry}') if f'## {today}' in lt else lt.replace('---\n', f'---\n\n## {today}{entry}\n')
                else:
                    lt = f'# 操作日志\n\n## {today}{entry}\n'
                with open(log_path, 'w') as f:
                    f.write(lt)

                # Refresh local Wiki search corpus + regenerate hub graph
                if proposal.get('source') in ('upload', 'concept-proposal', 'pi-ingest'):
                    threading.Thread(target=gbrain_sync, daemon=True).start()
                    def _regen_graph():
                        subprocess.run(
                            ['python3', os.path.join(BASE, 'regenerate-graph.py')],
                            capture_output=True, timeout=60, cwd=BASE
                        )
                    threading.Thread(target=_regen_graph, daemon=True).start()
                    # Wiki 事实页 → Neo4j（PI / 上传 / 概念提案均尝试）
                    def _load_neo4j():
                        subprocess.run(
                            [sys.executable, os.path.join(BASE, 'graph', 'sync_wiki_graph.py'), '--quiet'],
                            capture_output=True, timeout=300, cwd=BASE
                        )
                    threading.Thread(target=_load_neo4j, daemon=True).start()
                    
            except Exception as e:
                self._json({"ok": False, "error": str(e)}); return
        else:
            # Reject — just mark status
            proposal['status'] = 'rejected'
            proposal['rejected_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            # If reject reason provided
            if body.get('reason'):
                proposal['reject_reason'] = body['reason']
        
        # Save updated proposal
        with open(prop_path, 'w') as f:
            json.dump(proposal, f, ensure_ascii=False, indent=2)
        
        self._json({"ok": True, "status": proposal['status'], "slug": slug})

    def handle_run_check(self):
        """POST /api/run-check — run validate-taxonomy.py and return results."""
        if self._reject_write(): return
        try:
            result = subprocess.run(
                ['python3', 'validate-taxonomy.py'],
                capture_output=True, text=True, timeout=30, cwd=BASE
            )
            self._json({
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "output": result.stdout[-3000:],
                "errors": result.stderr[:1000] if result.stderr else ""
            })
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "output": "⏰ 自检超时（30秒）"})
        except Exception as e:
            self._json({"ok": False, "output": f"❌ {str(e)[:200]}"})

    def handle_run_improve(self):
        """POST /api/run-improve — run enrich.py --improve and return results."""
        if self._reject_write(): return
        try:
            result = subprocess.run(
                ['python3', 'enrich.py', '--improve', '--batch', '5'],
                capture_output=True, text=True, timeout=120, cwd=BASE
            )
            # Count pending proposals
            proposals_dir = os.path.join(BASE, '_proposals')
            pending = 0
            if os.path.isdir(proposals_dir):
                for fn in os.listdir(proposals_dir):
                    if fn.endswith('.json'):
                        try:
                            d = json.loads(open(os.path.join(proposals_dir, fn)).read())
                            if d.get('status') == 'pending':
                                pending += 1
                        except: pass
            self._json({
                "ok": result.returncode == 0,
                "output": (result.stdout + result.stderr)[-2500:],
                "pending_proposals": pending
            })
        except subprocess.TimeoutExpired:
            self._json({"ok": False, "output": "⏰ 改进生成超时（120秒）"})
        except Exception as e:
            self._json({"ok": False, "output": f"❌ {str(e)[:200]}"})

    # ── Task management ──

    TASKS = [
        {"id": "validate", "name": "🔍 全量自检", "desc": "Taxonomy · 索引 · 缺页 · 断链",
         "cmd": ["python3", "validate-taxonomy.py"], "timeout": 30},
        {"id": "enrich-l1", "name": "📝 L1 自动填充", "desc": "批 20 页填充编译概要",
         "cmd": ["python3", "enrich.py", "--batch", "20"], "timeout": 300},
        {"id": "enrich-l3", "name": "🛠️ L3 改进审阅", "desc": "批 5 页生成改进提案",
         "cmd": ["python3", "enrich.py", "--improve", "--batch", "5"], "timeout": 120},
        {"id": "improve-concepts", "name": "🏷️ 补齐概念页", "desc": "为孤立标签生成概念页",
         "cmd": ["python3", "enrich.py", "--improve-concepts"], "timeout": 120},
        {"id": "sync-concepts", "name": "🔗 同步概念页", "desc": "扫描产品wikilink回写概念页列表",
         "cmd": ["python3", "enrich.py", "--fix-dataview"], "timeout": 60},
        {"id": "rebuild", "name": "🔄 重建索引+同步", "desc": "刷新 index.md + 本地 Wiki 检索语料",
         "cmd": ["python3", "regenerate-graph.py"], "timeout": 60},
    ]
    _task_results = {}


    def handle_run_improve_concepts(self):
        """POST /api/run-improve-concepts."""
        if self._reject_write(): return
        try:
            import subprocess as sp
            result = sp.run(
                ['python3', os.path.join(BASE, 'enrich.py'), '--improve-concepts'],
                capture_output=True, text=True, timeout=120, cwd=BASE
            )
            pending = len([f for f in os.listdir(os.path.join(BASE, '_proposals'))
                          if f.endswith('.json')]) if os.path.isdir(os.path.join(BASE, '_proposals')) else 0
            self._json({
                "ok": result.returncode == 0,
                "output": (result.stdout + result.stderr)[-2500:],
                "pending_proposals": pending
            })
        except sp.TimeoutExpired:
            self._json({"ok": False, "output": "concept gen timeout"})
        except Exception as e:
            self._json({"ok": False, "output": f"error: {str(e)[:200]}"})

    def handle_tasks(self):
        """GET /api/tasks — list all tasks with last-run status."""
        tasks_out = []
        for t in self.TASKS:
            last = self._task_results.get(t['id'], {})
            tasks_out.append({
                "id": t['id'], "name": t['name'], "desc": t['desc'],
                "last_ok": last.get('ok'), "last_time": last.get('time', ''),
                "last_output": (last.get('output', '') or '')[-300:]
            })
        self._json({"tasks": tasks_out})

    def handle_tasks_run(self):
        """POST /api/tasks/run — run one task."""
        if self._reject_write(): return
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        task_id = body.get('task', '')
        # Validate task_id
        matched = [t for t in self.TASKS if t['id'] == task_id]
        if not matched:
            self._json({"ok": False, "error": f"unknown task: {task_id}"})
            return
        results = []
        for t in matched:
            try:
                result = subprocess.run(t['cmd'], capture_output=True, text=True, timeout=t['timeout'], cwd=BASE)
                ok = result.returncode == 0
                output = (result.stdout + result.stderr)[-2000:]
                self._task_results[t['id']] = {'ok': ok, 'time': time.strftime('%H:%M:%S'), 'output': output}
                results.append({"id": t['id'], "ok": ok, "output": output})
            except subprocess.TimeoutExpired:
                self._task_results[t['id']] = {'ok': False, 'time': time.strftime('%H:%M:%S'), 'output': '⏰ 超时'}
                results.append({"id": t['id'], "ok": False, "output": "⏰ 超时"})
            except Exception as e:
                self._task_results[t['id']] = {'ok': False, 'time': time.strftime('%H:%M:%S'), 'output': str(e)[:200]}
                results.append({"id": t['id'], "ok": False, "output": str(e)[:200]})
        self._json({"ok": True, "results": results})

    def handle_page_get(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        slug = qs.get('slug', [None])[0]
        if not slug:
            self.send_error(400, "missing slug"); return
        # Security: only allow alphanumeric, Chinese, hyphens, slashes, underscores
        if not re.match(r'^[\u4e00-\u9fff\w/\-]+$', slug):
            self.send_error(403, "invalid slug"); return
        fpath = _resolve_slug(slug)
        if not fpath:
            self._json({"content": "", "error": "not found"}); return
        with open(fpath, 'r') as f:
            content = f.read()
        self._json({"content": content, "slug": slug})

    def handle_save(self):
        """POST /api/save {slug, content} — save edited markdown."""
        if self._reject_write(): return
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        slug = body.get('slug', '')
        content = body.get('content', '')
        if not slug or not content:
            self._json({"ok": False, "error": "missing slug or content"}); return
        if not re.match(r'^[a-z0-9_/\-]+$', slug):
            self._json({"ok": False, "error": "invalid slug"}); return
        fpath = os.path.join(BASE, slug + '.md')
        if not os.path.isfile(fpath):
            self._json({"ok": False, "error": "file not found"}); return
        # Backup to _backups/
        backup_dir = os.path.join(BASE, '_backups')
        os.makedirs(backup_dir, exist_ok=True)
        ts = time.strftime('%Y%m%d_%H%M%S')
        safe_name = slug.replace('/', '_')
        backup_path = os.path.join(backup_dir, f"{safe_name}.{ts}.md")
        shutil.copy2(fpath, backup_path)
        # Write new content
        with open(fpath, 'w') as f:
            f.write(content)
        # Log
        log_path = os.path.join(BASE, 'log.md')
        today = time.strftime('%Y-%m-%d')
        entry = f"\n- [edit] {today} {slug} — 前端编辑保存"
        if os.path.exists(log_path):
            log_text = open(log_path).read()
            if f'## {today}' in log_text:
                log_text = log_text.replace(f'## {today}', f'## {today}{entry}')
            else:
                log_text = log_text.replace('---\n', f'---\n\n## {today}{entry}\n')
        else:
            log_text = f'# 操作日志\n\n## {today}{entry}\n'
        with open(log_path, 'w') as f:
            f.write(log_text)
        self._json({"ok": True, "backup": os.path.basename(backup_path)})

    def handle_issues(self):
        """GET /api/issues — consistency check report."""
        import_path = os.path.join(BASE, '_meta/_issues.md')
        if os.path.exists(import_path):
            with open(import_path) as f:
                content = f.read()
        else:
            # Live TODO count across new directory structure
            todo_count = 0
            for cat in ALL_CONTENT_DIRS:
                d = os.path.join(BASE, cat)
                if not os.path.isdir(d):
                    continue
                for root, dirs, files in os.walk(d):
                    for fn in files:
                        if not fn.endswith('.md') or fn == 'index.md':
                            continue
                        with open(os.path.join(root, fn)) as f:
                            text = f.read()
                        if 'TODO' in text and 'enrichment' in text.lower():
                            todo_count += 1
            content = f"# 一致性检查\n\n- ⏳ TODO 页面: {todo_count}/305\n- 检查脚本: `python3 enrich.py --check`\n"
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(content.encode())

    def handle_enrich_status(self):
        """GET /api/enrich-status — count of remaining TODO pages."""
        todo_count = 0
        enriched_count = 0
        for cat in ALL_CONTENT_DIRS:
            d = os.path.join(BASE, cat)
            if not os.path.isdir(d):
                continue
            for root, dirs, files in os.walk(d):
                for fn in files:
                    if not fn.endswith('.md') or fn == 'index.md':
                        continue
                    with open(os.path.join(root, fn)) as f:
                        text = f.read()
                    if 'TODO' in text and 'enrichment' in text.lower():
                        todo_count += 1
                    else:
                        enriched_count += 1
        self._json({"todo": todo_count, "enriched": enriched_count, "total": todo_count + enriched_count})

    def handle_ask_stream(self):
        """SSE streaming: Graph-first → local Wiki search → DeepSeek synthesis."""
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        question = body.get('question', '')
        lang = body.get('lang', 'zh')  # 'zh' or 'en'
        rewrite_meta = _parse_rewrite_meta(body)
        if not question:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":"missing question"}'); return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        def sse(event, data):
            msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(msg.encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        proc = None
        try:
            context_parts = []
            seen_slugs = set()

            _emit_rewrite_meta_step(sse, rewrite_meta, lang)

            # Step 1: Graph-first recall (structured clinical / product / cross)
            sse('step', {'id': 1, 'type': 'searching', 'action': '🕸',
                         'detail': f'图谱优先召回: {question}'})
            graph_hit = apply_graph_recall(question, context_parts, seen_slugs, sse=sse)
            _emit_graph_template_step(sse, graph_hit, lang)
            _inject_series_coverage_if_needed(graph_hit, context_parts, seen_slugs, sse=sse)

            # Step 2: Local Wiki search to supplement (always for open product Q; fill if graph thin)
            need_local = _need_local_search(question, graph_hit, context_parts)
            search_results = []
            fts_terms = rewrite_meta.get('entities') if rewrite_meta else None
            if need_local:
                sse('step', {'id': 2, 'type': 'searching', 'action': '🔍',
                             'detail': f'本地 Wiki 检索: {question}'})
                search_results = gbrain_search(question, limit=10, extra_terms=fts_terms)

            # ---- Series concept page injection ----
            _SERIES_LISTING = re.compile(
                r'(?:系列).*(?:有哪些|哪几款|哪些款|产品|型号|药品|清单)'
            )
            series_concept_slug = None
            if _SERIES_LISTING.search(question):
                series_concept_slug = _resolve_series_concept_slug(question)
                if series_concept_slug:
                    sse('step', {'id': 0, 'type': 'reading', 'action': '📋',
                                 'detail': f'定位系列概览页 {series_concept_slug}'})

            want_shoes = bool(re.search(r'鞋款|跑鞋|球鞋|运动鞋|板鞋|篮球鞋|足球鞋|网球鞋|徒步鞋|训练鞋', question))
            want_apparel = bool(re.search(r'服装|衣服|上衣|裤子|短袖|夹克|卫衣', question))
            q_filter_note = ''
            if want_shoes and not want_apparel:
                q_filter_note = '\n⚠️ 用户只问鞋款，请只列出鞋类产品，不要提服装。\n'

            if series_concept_slug and series_concept_slug not in seen_slugs:
                seen_slugs.add(series_concept_slug)
                full = gbrain_get(series_concept_slug)
                if full and len(full) > 50:
                    body_text = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                    if want_shoes and not want_apparel:
                        filtered = []
                        for line in body_text.split('\n'):
                            if '/鞋/' in line or not line.startswith('- [['):
                                filtered.append(line)
                        body_text = '\n'.join(filtered)
                    context_parts.append(f"## {series_concept_slug}\n{body_text[:5000]}")

            for r in search_results:
                if want_shoes and not want_apparel and ('服装' in r['slug'] or '配件' in r['slug']):
                    continue
                if r['slug'] in seen_slugs:
                    continue
                seen_slugs.add(r['slug'])
                if len([c for c in context_parts if not c.startswith('【图谱召回')]) < 6:
                    full = gbrain_get(r['slug'])
                    if full and len(full) > 50:
                        body = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                        context_parts.append(f"## {r['slug']}\n{body[:10000]}")
                        sse('step', {'id': len(context_parts) + 1, 'type': 'reading', 'action': '📖', 'detail': f'读取 {r["slug"]}'})
                    else:
                        context_parts.append(f"## {r['slug']} [仅摘要]\n{r['content'][:1000]}")
                else:
                    context_parts.append(f"## {r['slug']} [仅摘要]\n{r['content'][:1000]}")

            context = "\n\n---\n\n".join(context_parts) if context_parts else "(未找到相关内容)"

            # Follow wikilinks from concept pages
            expanded = expand_concept_links(context_parts, seen_slugs, max_extra=8, sse=sse)
            if expanded:
                context = "\n\n---\n\n".join(context_parts)
                sse('step', {'id': 0, 'type': 'reading', 'action': '🔗', 'detail': f'展开概念页链接 +{expanded} 页'})

            context = "\n\n---\n\n".join(context_parts) if context_parts else "(未找到相关内容)"

            # Strip markdown images from context to prevent LLM from hallucinating broken image links
            # (real images are injected by _get_images_for_slugs at answer end)
            context = re.sub(r'!\[.*?\]\(.*?\)\s*', '', context)

            if _should_force_reject(question, graph_hit, context_parts):
                msg = _rejection_answer(lang)
                sse('answer', {'answer': msg})
                sse('done', {})
                return

            # Step 3: LLM synthesis via DeepSeek API (streaming)
            sse('step', {'id': 99, 'type': 'thinking', 'action': '🤔', 'detail': 'AI 综合分析中...'})

            _sys_extra = (_GRAPH_ANSWER_NOTE if graph_hit.hit else "") + _ANTI_HALLUCINATION_NOTE
            messages = [
                {"role": "system", "content": (
                    "你是 " + cfg.brand.name + " 产品知识专家。基于提供的知识库内容，给出尽可能详尽全面的回答。\n"
                    + q_filter_note +
                    "规则:\n"
                    "- ⚠️ 严格只使用下方提供的知识库内容回答，不要补充你自身的训练知识\n"
                    "- 如果知识库没有某项信息，直接说「知识库未收录」，不要推测或补充\n"
                    "- 用户问「有哪些」→ 列全所有产品，按定位/类别分组，不允许遗漏\n"
                    "- 用户问「区别/对比」→ 逐维度对比差异（定位/价格/科技/适用场景）\n"
                    "- 用户问「推荐」→ 根据需求给出建议并说明理由\n"
                    "- 用户问科技/概念 → 解释原理、特性、应用产品，关联相关技术\n"
                    "- 如果知识库信息不完整，诚实说明缺什么\n"
                    "- 使用中文回答，Markdown 格式，结构清晰"
                    + _sys_extra
                ) if lang == 'zh' else (
                    "You are a " + cfg.brand.name + " product knowledge expert. Based on the provided knowledge base content, "
                    "answer comprehensively with thorough detail.\n"
                    "Use ONLY knowledge base content. Say when information is not indexed.\n"
                    "Use English, Markdown format, be thorough."
                    + _sys_extra
                )},
                {"role": "user", "content": (
                    f"=== 知识库内容 ===\n{context}\n=== 内容结束 ===\n\n问题：{question}"
                ) if lang == 'zh' else (
                    f"=== Knowledge Base Content ===\n{context}\n=== End of Content ===\n\nQuestion: {question}"
                )}
            ]

            if not DEEPSEEK_API_KEY:
                raise RuntimeError("DEEPSEEK_API_KEY not configured")

            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.5,
                    "max_tokens": 2500,
                },
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            total_text = []
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        total_text.append(content)
                        sse('token', {'token': content})
                except json.JSONDecodeError:
                    continue

            answer = ''.join(total_text).strip()
            if answer:
                # Inject product images using slug-based lookup + question-based fuzzy match
                slugs = list(seen_slugs)
                image_markdowns = _get_images_for_slugs(slugs, question)
                if image_markdowns:
                    NL = '\n'
                    answer += f'{NL}{NL}---{NL}{NL}**📷 产品图片**{NL}{NL}' + f'{NL}{NL}'.join(image_markdowns)
                # Convert bare slug references to product detail links
                answer = _linkify_slugs(answer, slugs)
                # MUST send answer BEFORE any debug prints — stdout may be a broken pipe
                sse('answer', {'answer': answer})  # final complete answer as fallback
                try:
                    print(f'[img-inject] seen_slugs={slugs[:3]}... ({len(slugs)} total), found {len(image_markdowns)} images', flush=True)
                except Exception:
                    pass

        except requests.exceptions.Timeout:
            sse('error', {'message': '⏰ AI 响应超时，请稍后重试。'})
        except requests.exceptions.HTTPError as e:
            sse('error', {'message': f'❌ API {e.response.status_code}: {"服务繁忙，请稍后重试" if e.response.status_code >= 500 else "请检查 API Key 配置"}'})
        except BrokenPipeError:
            pass
        except Exception as e:
            sse('error', {'message': f'❌ {str(e)[:200]}'})
        finally:
            try:
                sse('done', {})
            except:
                pass

    def handle_ask_deep(self):
        """深度多轮检索: ReAct agent loop with function calling.
        LLM can call kb_search / kb_get_page multiple rounds before synthesizing."""
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        question = body.get('question', '')
        lang = body.get('lang', 'zh')
        rewrite_meta = _parse_rewrite_meta(body)
        if not question:
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{"error":"missing question"}'); return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        def sse(event, data):
            msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(msg.encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        # Determine category filter
        want_shoes = bool(re.search(r'鞋款|跑鞋|球鞋|运动鞋|板鞋|篮球鞋|足球鞋|网球鞋|徒步鞋|训练鞋', question))
        want_apparel = bool(re.search(r'服装|衣服|上衣|裤子|短袖|夹克|卫衣', question))
        q_filter_note = ''
        if want_shoes and not want_apparel:
            q_filter_note = '\n⚠️ 用户只问鞋款，请只列出鞋类产品，不要提服装。\n'

        context_parts = []
        seen_slugs = set()

        _emit_rewrite_meta_step(sse, rewrite_meta, lang)

        # Step 1: Graph-first
        sse('step', {'id': 1, 'type': 'searching', 'action': '🕸',
                     'detail': f'图谱优先召回: {question[:80]}'})
        graph_hit = apply_graph_recall(question, context_parts, seen_slugs, sse=sse)
        _emit_graph_template_step(sse, graph_hit, lang)
        _inject_series_coverage_if_needed(graph_hit, context_parts, seen_slugs, sse=sse)

        # Step 2: Local Wiki search (deep: always broader for multi-round foundation)
        sse('step', {'id': 2, 'type': 'searching', 'action': '🔍',
                     'detail': f'本地 Wiki 深度检索: {question[:80]}'})
        fts_terms = rewrite_meta.get('entities') if rewrite_meta else None
        search_results = gbrain_search(question, limit=20, extra_terms=fts_terms)
        sse('step', {'id': 3, 'type': 'searching', 'action': '📊',
                     'detail': f'找到 {len(search_results)} 条相关内容'})

        # Series concept injection
        _SERIES_LISTING = re.compile(
            r'(?:系列).*(?:有哪些|哪几款|哪些款|产品|型号|药品|清单)'
        )
        series_concept_slug = None
        if _SERIES_LISTING.search(question):
            series_concept_slug = _resolve_series_concept_slug(question)
            if series_concept_slug:
                sse('step', {'id': 0, 'type': 'reading', 'action': '📋',
                             'detail': f'定位系列概览页 {series_concept_slug}'})

        if series_concept_slug and series_concept_slug not in seen_slugs:
            seen_slugs.add(series_concept_slug)
            full = gbrain_get(series_concept_slug)
            if full and len(full) > 50:
                body_text = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                if want_shoes and not want_apparel:
                    filtered = []
                    for line in body_text.split('\n'):
                        if '/鞋/' in line or not line.startswith('- [['):
                            filtered.append(line)
                    body_text = '\n'.join(filtered)
                context_parts.append(f"## {series_concept_slug}\n{body_text[:5000]}")

        for r in search_results:
            if want_shoes and not want_apparel and ('服装' in r['slug'] or '配件' in r['slug']):
                continue
            if r['slug'] in seen_slugs:
                continue
            seen_slugs.add(r['slug'])
            if len([c for c in context_parts if not c.startswith('【图谱召回')]) < 10:
                full = gbrain_get(r['slug'])
                if full and len(full) > 50:
                    body = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                    context_parts.append(f"## {r['slug']}\n{body[:10000]}")
                    sse('step', {'id': len(context_parts) + 2, 'type': 'reading',
                                 'action': '📖', 'detail': f'读取 {r["slug"]}'})
                else:
                    context_parts.append(f"## {r['slug']} [仅摘要]\n{r['content'][:1000]}")
            else:
                context_parts.append(f"## {r['slug']} [仅摘要]\n{r['content'][:1000]}")

        # Expand concept links
        expanded = expand_concept_links(context_parts, seen_slugs, max_extra=8, sse=sse)
        if expanded:
            sse('step', {'id': 0, 'type': 'reading', 'action': '🔗',
                         'detail': f'展开概念页链接 +{expanded} 页'})

        # Auto-inject technology / ingredient concept pages from wikilinks
        tech_slugs = set()
        for part in context_parts:
            for m in re.finditer(r'\[\[([^\]]+)\]\]', part):
                link = m.group(1)
                if (link.startswith('科技/') or link.startswith('成分/') or link.startswith('疾病/')) and link not in seen_slugs:
                    tech_slugs.add(link)
        if tech_slugs:
            injected = 0
            for slug in sorted(tech_slugs):
                if injected >= 6:
                    break
                full = gbrain_get(slug)
                if full and len(full) > 50:
                    body = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                    context_parts.append(f"## {slug}\n{body}")
                    seen_slugs.add(slug)
                    injected += 1
            if injected:
                sse('step', {'id': 0, 'type': 'reading', 'action': '🔬',
                             'detail': f'自动注入 {injected} 个概念页'})

        context = "\n\n---\n\n".join(context_parts) if context_parts else "(未找到相关内容)"

        # Strip markdown images from context to prevent LLM from hallucinating broken image links
        context = re.sub(r'!\[.*?\]\(.*?\)\s*', '', context)

        if _should_force_reject(question, graph_hit, context_parts):
            sse('answer', {'answer': _rejection_answer(lang)})
            sse('done', {})
            return

        # Cap Phase 1 context to prevent exceeding DeepSeek 64K token limit
        # Must be high enough to include full product lists (ADIZERO = ~15K just for products)
        if len(context) > 45000:
            context = context[:45000] + "\n\n...(内容过长，已截断)..."

        if not DEEPSEEK_API_KEY:
            sse('error', {'message': 'DEEPSEEK_API_KEY not configured'})
            sse('done', {}); return

        # ---- Tool definitions for Phase 1: gap analysis only (kb_get_page) ----
        # No kb_search tool — initial search already provides comprehensive results.
        # Phase 1 identifies gaps and reads specific pages the model needs more detail on.
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "kb_get_page",
                    "description": "获取知识库页面的完整内容。当你发现某个产品的科技信息不完整，或需要深入了解某个概念时调用。传入页面的 slug。" if lang == 'zh' else "Get the full content of a knowledge base page. Call when you need to read full details of a page — when a product's tech info is missing or a concept needs deeper exploration. Pass the page slug.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slug": {
                                "type": "string",
                                "description": "页面的唯一标识符 (slug)，例如 '科技/boost-technology' 或 '运动表现产品/鞋/跑步/adizero-sl2'" if lang == 'zh' else "The page slug, e.g. '科技/boost-technology' or 'products/shoes/running/adizero-sl2'"
                            }
                        },
                        "required": ["slug"]
                    }
                }
            }
        ]

        # ---- Build messages for the agent loop ----
        _deep_graph_note = (_GRAPH_ANSWER_NOTE if graph_hit.hit else "") + _ANTI_HALLUCINATION_NOTE
        messages = [
            {"role": "system", "content": (
                "你是 " + cfg.brand.name + " 产品知识专家。你可以用 kb_get_page 读取特定页面获取详细信息。\n"
                + q_filter_note +
                "工作流程:\n"
                "1. 我已为你执行了全面的初始搜索（20条结果），结果在 <initial_context> 标签内\n"
                "2. 快速浏览初始结果：如果产品页已包含科技说明，不需要再读。只对确实缺少科技信息的关键产品，用 kb_get_page 补充读取\n"
                "3. ⚠️ 限制：最多读取 3-5 个页面，只读信息缺口最明显的。不要为了「完整性」而遍历所有产品\n"
                "4. 之后会有后续阶段综合所有信息生成最终回答\n\n"
                "规则:\n"
                "- ⚠️ 严格只使用知识库内容回答，不要补充你自身的训练知识\n"
                "- 初始上下文已经涵盖了最相关的产品页面，只在科技信息完全空白时才读取\n"
                "- 最多读取 3-5 个页面，选择信息缺口最大的产品\n"
                "- 不要为了「确认」而重复读取已有足够信息的页面\n"
                "- 如果知识库没有某项信息，直接说「知识库未收录」，不要推测或补充"
                + _deep_graph_note
            ) if lang == 'zh' else (
                "You are a " + cfg.brand.name + " product knowledge expert. You can use kb_get_page to read specific pages.\n"
                "Workflow:\n"
                "1. I've done a comprehensive initial search (20 results) — see <initial_context>\n"
                "2. Analyze: identify products with incomplete tech info, concepts needing depth\n"
                "3. Use kb_get_page to read those specific pages (don't search — initial results are comprehensive)\n"
                "4. Later rounds will synthesize the final answer\n\n"
                "Rules:\n"
                "- Use ONLY knowledge base content — do NOT supplement from training data\n"
                "- The initial context already covers the most relevant products\n"
                "- Only read pages where info is clearly insufficient (e.g. snippet-only entries)\n"
                "- Don't re-read pages that already have enough detail"
                + _deep_graph_note
            )},
            {"role": "user", "content": (
                f"<initial_context>\n{context}\n</initial_context>\n\n问题：{question}"
            ) if lang == 'zh' else (
                f"<initial_context>\n{context}\n</initial_context>\n\nQuestion: {question}"
            )}
        ]

        # ---- Two-phase agent: Phase 1 (tools) → Phase 2 (synthesis, no tools) ----
        answer_lines = []

        try:
            # ── Phase 1: Supplement search with tools ──
            sse('step', {'id': 101, 'type': 'thinking', 'action': '🤔',
                         'detail': 'AI 分析初始结果，识别信息缺口...'})

            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0.5,
                    "max_tokens": 8000,
                },
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
            finish = choice.get("finish_reason", "?")
            try:
                print(f"[deep-p1] finish={finish}, content={bool(msg.get('content'))}, "
                      f"tool_calls={len(msg.get('tool_calls', []))}", flush=True)
            except Exception:
                pass

            if msg.get("tool_calls"):
                messages.append(msg)
                # Cap Phase 1 tool calls at 8 — enough for complex queries,
                # and 8000 max_tokens prevents JSON truncation
                max_p1_calls = min(len(msg["tool_calls"]), 8)
                if len(msg["tool_calls"]) > 8:
                    print(f"[deep-p1] capping tool_calls from {len(msg['tool_calls'])} to 8", flush=True)
                for tc in msg["tool_calls"][:max_p1_calls]:
                    fn = tc["function"]
                    tool_id = tc["id"]
                    fn_name = fn["name"]
                    try:
                        fn_args = json.loads(fn["arguments"])
                    except json.JSONDecodeError as e:
                        print(f"[deep-p1] bad tool args for {fn_name}: {e}", flush=True)
                        messages.append({
                            "role": "tool", "tool_call_id": tool_id,
                            "content": f"工具参数解析失败: {e}"
                        })
                        continue

                    if fn_name == "kb_search":
                        keywords = fn_args.get("keywords", "")
                        sse('step', {'id': 201, 'type': 'searching', 'action': '🔍',
                                     'detail': f'追加搜索: {keywords[:80]}'})
                        results = gbrain_search(keywords, limit=8)
                        sse('step', {'id': 202, 'type': 'searching', 'action': '📊',
                                     'detail': f'找到 {len(results)} 条补充内容'})
                        # Read full content for top results (not just 300-char snippets)
                        # to match the quality of the initial context pages
                        result_text = "找到以下相关内容:\n"
                        for i, r in enumerate(results[:6]):
                            if r['slug'] not in seen_slugs:
                                seen_slugs.add(r['slug'])
                            # Try to get full page content, fall back to snippet
                            full = gbrain_get(r['slug'])
                            if full and len(full) > 100:
                                body = re.sub(r'^---.*?---\\s*', '', full, flags=re.DOTALL)
                                result_text += f"{i+1}. ## {r['slug']}\n{body[:3000]}\n---\n"
                            else:
                                result_text += f"{i+1}. [{r['slug']}] (分数: {r['score']:.1f}) {r['content'][:300]}\n"
                        if not results:
                            result_text = "未找到匹配结果。"
                        messages.append({
                            "role": "tool", "tool_call_id": tool_id,
                            "content": result_text
                        })

                    elif fn_name == "kb_get_page":
                        slug = fn_args.get("slug", "")
                        sse('step', {'id': 211, 'type': 'reading', 'action': '📖',
                                     'detail': f'读取: {slug[:80]}'})
                        full = gbrain_get(slug)
                        if full and len(full) > 50:
                            body = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                            page_content = body[:6000]
                            if slug not in seen_slugs:
                                seen_slugs.add(slug)
                        else:
                            page_content = f"页面 '{slug}' 未找到或内容为空。"
                        messages.append({
                            "role": "tool", "tool_call_id": tool_id,
                            "content": page_content
                        })

            # If Phase 1 already produced content (no tools needed), skip Phase 2
            if not msg.get("tool_calls") and msg.get("content"):
                content_text = msg["content"]
            else:
                # ── Phase 2: Two-step fresh conversation ──
                # Step 2a: Model can kb_get_page to read specific product pages for tech info
                # Step 2b: Without tools — synthesize final answer
                sse('step', {'id': 301, 'type': 'thinking', 'action': '🤔',
                             'detail': '综合信息，补充读取产品详情...'})

                # Build gathered context: start with the FULL initial context (never truncated),
                # then append ONLY kb_get_page results from Phase 1 (the model explicitly asked
                # for these pages). Skip kb_search results — they are redundant with initial
                # context which was built from the same underlying gbrain_search.
                gathered = context  # original full context, always preserved
                for m in messages:
                    if m.get("role") != "tool":
                        continue
                    tr = m.get("content", "").strip()
                    # Only include kb_get_page results (not kb_search which overlaps with context)
                    if tr.startswith("找到以下相关内容:"):
                        continue
                    if len(tr) > 8000:
                        tr = tr[:8000] + "\n...(已截断)..."
                    gathered += "\n\n---\n\n" + tr
                # Cap at 40000 chars total (prevents 503 on context-heavy queries)
                if len(gathered) > 40000:
                    gathered = gathered[:40000] + "\n\n...(内容过长，已截断)..."
                # Strip markdown images from context
                gathered = re.sub(r'!\[.*?\]\(.*?\)\s*', '', gathered)
                try:
                    print(f"[deep-p2-gathered] len={len(gathered)}", flush=True)
                except Exception:
                    pass

                # Build fresh conversation — model can read pages but NOT search
                read_tool = [{
                    "type": "function",
                    "function": {
                        "name": "kb_get_page",
                        "description": "读取知识库页面的完整内容。当你列出产品清单后，如果某些产品缺少科技信息，调用此工具读取对应产品页。" if lang == 'zh' else "Read the full content of a KB page. Call when tech info is missing.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "slug": {"type": "string", "description": "页面 slug"}
                            },
                            "required": ["slug"]
                        }
                    }
                }]

                fresh_messages = [
                    {"role": "system", "content": (
                        "你是 " + cfg.brand.name + " 产品知识专家。你可以用 kb_get_page 读取产品页面的完整内容来获取科技信息。\n"
                        + q_filter_note +
                        "工作流程:\n"
                        "1. 分析知识库内容，列出产品和已有科技\n"
                        "2. 对缺少科技的产品，调用 kb_get_page 读取完整页面\n"
                        "3. 综合所有信息，给出完整回答\n\n"
                        "规则:\n"
                        "- ⚠️ 严格只使用知识库内容回答\n"
                        "- 如果知识库没有某项信息，说「知识库未收录」\n"
                        "- 用户问「有哪些」→ 列全所有产品，按定位/类别分组\n"
                        "- 用户问「区别/对比」→ 逐维度对比差异\n"
                        "- 使用中文回答，Markdown 格式，结构清晰\n"
                        "- 用 kb_get_page 读取产品页获取科技信息"
                    )},
                    {"role": "user", "content": (
                        f"=== 知识库内容 ===\n{gathered}\n=== 内容结束 ===\n\n问题：{question}\n\n"
                        "请分析以上内容，先列出所有产品。对于缺少科技信息的产品，用 kb_get_page 读取对应页面补充科技详情。"
                    )}
                ]

                # Step 2a: With kb_get_page tool
                try:
                    print(f"[deep-p2a] sending request, messages={len(fresh_messages)}, gathered_len={len(gathered)}", flush=True)
                except: pass
                resp2 = requests.post(
                    f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": fresh_messages,
                        "tools": read_tool,
                        "tool_choice": "auto",
                        "temperature": 0.5,
                        "max_tokens": 3000,
                    },
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    timeout=120,
                )
                resp2.raise_for_status()
                data2 = resp2.json()
                msg2 = data2["choices"][0]["message"]
                try: print(f"[deep-p2a] ok, finish={data2['choices'][0].get('finish_reason','?')}, tool_calls={len(msg2.get('tool_calls',[]))}, content_len={len(msg2.get('content','') or '')}", flush=True)
                except: pass

                # Execute kb_get_page calls (cap at 8 to prevent context explosion)
                p2a_loaded = 0
                if msg2.get("tool_calls"):
                    fresh_messages.append(msg2)
                    for tc in msg2["tool_calls"]:
                        if p2a_loaded >= 8:
                            print(f"[deep-p2a] capping tool_calls at 8 (total {len(msg2['tool_calls'])})", flush=True)
                            break
                        fn = tc["function"]
                        try:
                            slug = json.loads(fn["arguments"]).get("slug", "")
                        except json.JSONDecodeError:
                            print(f"[deep-p2a] bad tool args for {fn.get('name','?')}", flush=True)
                            continue
                        sse('step', {'id': 401, 'type': 'reading', 'action': '📖',
                                     'detail': f'补充读取: {slug[:80]}'})
                        full = gbrain_get(slug)
                        if full and len(full) > 50:
                            body = re.sub(r'^---.*?---\\s*', '', full, flags=re.DOTALL)
                            page_content = body[:5000]
                            if slug not in seen_slugs:
                                seen_slugs.add(slug)
                        else:
                            page_content = f"页面 '{slug}' 未找到。"
                        fresh_messages.append({
                            "role": "tool", "tool_call_id": tc["id"],
                            "content": page_content
                        })
                        p2a_loaded += 1

                # Step 2a (round 2): Second pass — read any still-missing pages
                # Skip if we already capped tool calls in round 1 (context would be too large)
                if msg2.get("tool_calls") and not (p2a_loaded >= 8 and len(msg2["tool_calls"]) > 8):
                    sse('step', {'id': 403, 'type': 'thinking', 'action': '🤔',
                                 'detail': '检查遗漏，补充读取...'})
                    resp2b = requests.post(
                        f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                        json={
                            "model": DEEPSEEK_MODEL,
                            "messages": fresh_messages,
                            "tools": read_tool,
                            "tool_choice": "auto",
                            "temperature": 0.5,
                            "max_tokens": 3000,
                        },
                        headers={
                            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        timeout=120,
                    )
                    resp2b.raise_for_status()
                    msg2b = resp2b.json()["choices"][0]["message"]

                    if msg2b.get("tool_calls"):
                        fresh_messages.append(msg2b)
                        for tc in msg2b["tool_calls"]:
                            fn = tc["function"]
                            try:
                                slug = json.loads(fn["arguments"]).get("slug", "")
                            except json.JSONDecodeError:
                                print(f"[deep-p2a5] bad tool args for {fn.get('name','?')}", flush=True)
                                continue
                            sse('step', {'id': 410, 'type': 'reading', 'action': '📖',
                                         'detail': f'补充读取(2): {slug[:80]}'})
                            full = gbrain_get(slug)
                            if full and len(full) > 50:
                                body = re.sub(r'^---.*?---\\s*', '', full, flags=re.DOTALL)
                                page_content = body[:5000]
                                if slug not in seen_slugs:
                                    seen_slugs.add(slug)
                            else:
                                page_content = f"页面 '{slug}' 未找到。"
                            fresh_messages.append({
                                "role": "tool", "tool_call_id": tc["id"],
                                "content": page_content
                            })

                # Step 2b: FRESH conversation (no tools, no function calling history)
                sse('step', {'id': 402, 'type': 'thinking', 'action': '🤔',
                             'detail': '综合所有信息，生成最终回答...'})

                # Collect ALL info as plain text for a clean conversation
                final_info = []
                # Start with initial context (already in gathered)
                final_info.append(gathered)
                # Add all tool results from Steps 2a/2a-round2
                for m in fresh_messages:
                    if m["role"] == "tool":
                        final_info.append(m["content"])
                final_gathered = "\n\n---\n\n".join(final_info)
                if len(final_gathered) > 40000:
                    final_gathered = final_gathered[:40000] + "\n\n...(已截断)..."
                # Strip markdown images from context
                final_gathered = re.sub(r'!\[.*?\]\(.*?\)\s*', '', final_gathered)

                # Brand NEW conversation — model has NEVER seen function calling
                final_messages = [
                    {"role": "system", "content": (
                        "你是 " + cfg.brand.name + " 产品知识专家。基于提供的知识库内容回答问题。\n"
                        + q_filter_note +
                        "规则:\n"
                        "- ⚠️ 严格只使用下方提供的知识库内容回答\n"
                        "- 如果知识库没有某项信息，说「知识库未收录」\n"
                        "- 用户问「有哪些」→ 列全所有产品，按定位/类别分组\n"
                        "- 用户问「区别/对比」→ 逐维度对比差异\n"
                        "- 使用中文回答，Markdown 格式，结构清晰\n"
                        "- 直接输出回答，不要使用任何 XML 标签"
                    )},
                    {"role": "user", "content": (
                        f"=== 知识库内容 ===\n{final_gathered}\n=== 内容结束 ===\n\n"
                        f"问题：{question}\n\n请基于以上知识库内容直接回答。"
                    )}
                ]

                resp3 = requests.post(
                    f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                    json={
                        "model": DEEPSEEK_MODEL,
                        "messages": final_messages,
                        "stream": True,
                        "temperature": 0.5,
                        "max_tokens": 2500,
                    },
                    headers={
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    stream=True,
                    timeout=120,
                )
                resp3.raise_for_status()

                total_text = []
                for line in resp3.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            total_text.append(content)
                            sse('token', {'token': content})
                    except json.JSONDecodeError:
                        continue

                content_text = ''.join(total_text)
                try:
                    print(f"[deep-p2] content_len={len(content_text)}", flush=True)
                except Exception:
                    pass

            if content_text:
                # Strip hallucinated tool call syntax from output (line-by-line, more robust)
                lines = content_text.split('\n')
                cleaned = []
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith(('<invoke', '</invoke', '<parameter', '</parameter',
                                           '<tool_calls', '</tool_calls')):
                        continue
                    cleaned.append(line)
                content_text = '\n'.join(cleaned)
                answer = content_text.strip()
                answer_lines = [answer]
                # Image injection
                slugs = list(seen_slugs)
                image_markdowns = _get_images_for_slugs(slugs, question)
                if image_markdowns:
                    NL = '\n'
                    answer += f'{NL}{NL}---{NL}{NL}**📷 产品图片**{NL}{NL}' + f'{NL}{NL}'.join(image_markdowns)
                answer = _linkify_slugs(answer, slugs)
                sse('answer', {'answer': answer})
                try:
                    print(f'[deep-search] slugs={len(slugs)}, images={len(image_markdowns)}, answer_preview={answer[:120]!r}', flush=True)
                except Exception:
                    pass
            else:
                sse('error', {'message': 'AI 未返回有效回答'})

        except requests.exceptions.Timeout:
            try: print(f"[deep-err] Timeout", flush=True)
            except: pass
            sse('error', {'message': '⏰ AI 响应超时，请稍后重试。'})
        except requests.exceptions.HTTPError as e:
            try:
                body = e.response.text[:200] if e.response else 'no body'
                print(f"[deep-err] HTTPError type={type(e).__name__}, status={e.response.status_code if e.response else '?'}, body={body}", flush=True)
            except: pass
            sse('error', {'message': f'❌ API {e.response.status_code}: {"服务繁忙，请稍后重试" if e.response and e.response.status_code >= 500 else "请检查 API Key 配置"}'})
        except BrokenPipeError:
            pass
        except Exception as e:
            sse('error', {'message': f'❌ {str(e)[:200]}'})
        finally:
            try:
                sse('done', {})
            except:
                pass

    def handle_ask_rewrite(self):
        """POST /ask-rewrite — normalize user question before graph recall."""
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        question = body.get('question', '')
        lang = body.get('lang', 'zh')
        feedback = body.get('feedback', '')
        previous_rewrite = body.get('previous_rewrite', '')

        result = question_rewrite.rewrite_question(
            question,
            lang=lang,
            feedback=feedback,
            previous_rewrite=previous_rewrite,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
        )
        self._json(question_rewrite.to_api_dict(result))

    def handle_ask(self):
        """Blocking Q&A (non-streaming)."""
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        question = body.get('question', '')
        lang = body.get('lang', 'zh')  # 'zh' or 'en'
        if not question:
            self._json({"answer": "请输入问题。"}); return

        try:
            context_parts = []
            seen_slugs = set()

            # Graph-first, then local Wiki supplement
            graph_hit = apply_graph_recall(question, context_parts, seen_slugs, sse=None)
            _inject_series_coverage_if_needed(graph_hit, context_parts, seen_slugs, sse=None)
            need_local = _need_local_search(question, graph_hit, context_parts)
            search_results = gbrain_search(question, limit=5) if need_local else []
            for r in search_results[:6]:
                if r['slug'] in seen_slugs:
                    continue
                seen_slugs.add(r['slug'])
                full = gbrain_get(r['slug'])
                if full and len(full) > 50:
                    body_text = re.sub(r'^---.*?---\s*', '', full, flags=re.DOTALL)
                    context_parts.append(f"## {r['slug']}\n{body_text[:10000]}")
                else:
                    context_parts.append(f"## {r['slug']}\n{r['content'][:1000]}")

            expand_concept_links(context_parts, seen_slugs, max_extra=8)
            context = "\n\n---\n\n".join(context_parts) if context_parts else "(未找到)"

            # Strip markdown images from context
            context = re.sub(r'!\[.*?\]\(.*?\)\s*', '', context)

            if _should_force_reject(question, graph_hit, context_parts):
                self._json({"answer": _rejection_answer(lang)})
                return

            _ask_graph_note = (_GRAPH_ANSWER_NOTE if graph_hit.hit else "") + _ANTI_HALLUCINATION_NOTE
            prompt = (
                f'你是 {cfg.brand.name} 产品知识专家。根据以下知识库内容回答用户问题。\n'
                f'规则：只回答用户问的，不要添加用户没问的维度（如定位/价格）。\n'
                f'问「有哪些」→ 只列清单；问「区别」→ 对比差异。\n'
                f'{_ask_graph_note}\n'
                f'=== 知识库内容 ===\n{context}\n=== 结束 ===\n\n'
                f'问题：{question}\n'
                f'最后用一行 ===ANSWER_END=== 结束你的回答。'
            ) if lang == 'zh' else (
                f'You are a {cfg.brand.name} product knowledge expert. Based on the knowledge base content below, answer the user question.\n'
                f'{_ask_graph_note}\n'
                f'=== Knowledge Base Content ===\n{context}\n=== End ===\n\n'
                f'Question: {question}\n'
                f'End your response with a single line ===ANSWER_END===.'
            )

            cmd = ['hermes', 'chat', '--quiet', '-q', prompt,
                   '--toolsets', 'terminal', '--yolo', '--max-turns', '3']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=BASE)
            output = result.stdout

            if '===ANSWER_END===' in output:
                idx = output.rfind('===ANSWER_END===')
                before = output[:idx]
                lines = before.split('\n')
                clean_lines = []
                for line in lines:
                    s = line.strip()
                    if not s: continue
                    if s.startswith('session_id:'): continue
                    if '⚠' in s and ('Reached maximum' in s or 'requesting summary' in s.lower()): continue
                    clean_lines.append(line)
                answer = '\n'.join(clean_lines).strip()
            else:
                answer = "抱歉，查询失败。请重试。" if lang == 'zh' else "Sorry, query failed. Please try again."

        except subprocess.TimeoutExpired:
            answer = "⏰ 查询超时，请稍后重试。" if lang == 'zh' else "⏰ Query timed out. Please try again later."
        except Exception as e:
            answer = f"❌ {str(e)[:200]}"

        self._json({"answer": answer})

    def _json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def handle_upload(self):
        if self._reject_write(): return
        ct = self.headers.get('Content-Type','')
        if 'multipart/form-data' not in ct:
            self.send_error(400); return
        # Parse mode from query string (?mode=review|direct)
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        mode = params.get('mode', ['review'])[0]  # default to review
        if mode not in ('review', 'direct'):
            mode = 'review'
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                environ={'REQUEST_METHOD':'POST','CONTENT_TYPE':ct})
        ALLOWED_EXTS = {'.pdf','.docx','.xlsx','.md','.txt',
                        '.png','.jpg','.jpeg','.webp','.gif','.bmp',
                        '.pptx','.ppt'}
        saved = []
        rejected = []
        for key in form:
            item = form[key]
            if item.filename:
                fname = os.path.basename(item.filename)
                ext = os.path.splitext(fname)[1].lower()
                if ext not in ALLOWED_EXTS:
                    rejected.append(fname)
                    continue
                fpath = os.path.join(UPLOADS, fname); c = 1
                while os.path.exists(fpath):
                    n, e = os.path.splitext(fname)
                    fpath = os.path.join(UPLOADS, f"{n}-{c}{e}"); c += 1
                with open(fpath, 'wb') as f:
                    shutil.copyfileobj(item.file, f)
                entry = {
                    "name": os.path.basename(fpath), "original": fname,
                    "size": os.path.getsize(fpath), "status": "queued",
                    "mode": mode,
                    "uploaded_at": time.strftime('%Y-%m-%d %H:%M:%S'),
                }
                add_history(entry)
                saved.append(entry)

        if saved:
            queue_files([s["name"] for s in saved], mode)
            direct_msg = "（AI 自动收录）" if mode == 'direct' else ""
            _save(STATUS, {"phase": "queued", "message": f"{len(saved)} 个文件等待处理...{direct_msg}"})
            _trigger_ingest()

        self._json({"ok": True, "files": saved, "rejected": rejected, "mode": mode})

    def log_message(self, *args): pass

class ThreadingHTTPServer(ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

if __name__ == '__main__':
    mode_tag = "🔒 只读模式" if READ_ONLY else "🔓 完整模式"
    rate_info = f" | Q&A 限流: {QA_RATE_LIMIT}/min" if QA_RATE_LIMIT > 0 else ""
    print(f"🚀 {cfg.brand.public_name}  http://localhost:{PORT}/product-hub.html")
    print(f"   {mode_tag}{rate_info}")
    if READ_ONLY:
        print(f"   写入端点已禁用: upload / save / approve / reject / run-check / run-improve / tasks/run")
    # ── Re-trigger ingest for files left in queue from previous run ──
    if _startup_has_queued_files:
        remaining = _load(QUEUE, {})
        if isinstance(remaining, list):
            remaining = {"files": remaining, "mode": "review"}
        queued = remaining.get("files", [])
        if queued:
            print(f"[startup] re-triggering ingest for {len(queued)} queued file(s): {[f['name'] if isinstance(f, dict) else f for f in queued]}")
            _trigger_ingest()
    ThreadingHTTPServer(('', PORT), HubHandler).serve_forever()
