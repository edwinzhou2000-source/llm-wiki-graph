"""
config.py — Shared configuration loader for LLM-WIKI KB.

All scripts import this module to get brand-agnostic config.
The single source of truth is kb-config.yml in the project root.

Usage:
    from config import cfg
    print(cfg.brand.name)           # "adidas"
    print(cfg.server.port)          # 8767
    print(cfg.theme.accent)         # "4A4AFF"
"""

import os
import yaml
from pathlib import Path
from types import SimpleNamespace


def _deep_ns(obj):
    """Recursively convert dicts to SimpleNamespace for dot access."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _deep_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_deep_ns(v) for v in obj]
    return obj


def _resolve_path(p):
    """Resolve ~ and relative paths."""
    if p is None:
        return None
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(KB_ROOT, p)
    return p


# Locate kb-config.yml — look in project root (where this file lives or parent)
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "kb-config.yml")

if not os.path.exists(_CONFIG_PATH):
    # Fallback: maybe config.py is in a subdirectory (e.g. scripts/)
    _CONFIG_PATH = os.path.join(os.path.dirname(_CONFIG_DIR), "kb-config.yml")

if not os.path.exists(_CONFIG_PATH):
    raise FileNotFoundError(
        "kb-config.yml not found. Place it in the project root.\n"
        f"Searched: {_CONFIG_PATH}"
    )

with open(_CONFIG_PATH) as f:
    _raw = yaml.safe_load(f)

cfg = _deep_ns(_raw)

# Resolve paths
KB_ROOT = os.path.dirname(os.path.abspath(_CONFIG_PATH))
cfg.paths.kb_root = KB_ROOT
cfg.paths.gbrain_home = _resolve_path(cfg.paths.gbrain_home)
cfg.paths.env_file = _resolve_path(cfg.paths.env_file)

# Build a flat list of all category dirs for validation
def _flatten_dirs(cat):
    dirs = [cat.dir]
    for sub in getattr(cat, 'subcategories', []) or []:
        dirs.append(os.path.join(cat.dir, sub.dir))
        for child in getattr(sub, 'children', []) or []:
            dirs.append(os.path.join(cat.dir, sub.dir, child.dir))
            for grandchild in getattr(child, 'children', []) or []:
                dirs.append(os.path.join(cat.dir, sub.dir, child.dir, grandchild.dir))
    return dirs

ALL_CATEGORY_DIRS = []
for c in cfg.categories:
    ALL_CATEGORY_DIRS.extend(_flatten_dirs(c))

# Build category color map
CATEGORY_COLORS = {c.dir: c.color for c in cfg.categories}
CATEGORY_IDS = {c.dir: c.id for c in cfg.categories}

# ── V2: role-based category access (replaces hardcoded lists) ──
def _get_category(cat_dir):
    """Return the category config object by directory name, or None."""
    for c in cfg.categories:
        if c.dir == cat_dir:
            return c
    return None

def _is_product_dir(cat_dir):
    """True if this directory is a product category (role='product')."""
    cat = _get_category(cat_dir)
    return cat is not None and getattr(cat, 'role', None) == 'product'

def _is_concept_dir(cat_dir):
    """True if this directory is a concept category (role='concept')."""
    cat = _get_category(cat_dir)
    return cat is not None and getattr(cat, 'role', None) == 'concept'

def _is_clinical_dir(cat_dir):
    """True if this directory is a clinical category (role='clinical')."""
    cat = _get_category(cat_dir)
    return cat is not None and getattr(cat, 'role', None) == 'clinical'

def _is_bridge_dir(cat_dir):
    """True if this directory is a bridge category (role='bridge')."""
    cat = _get_category(cat_dir)
    return cat is not None and getattr(cat, 'role', None) == 'bridge'

# Pre-computed lists — use these instead of hardcoded ['运动表现产品', ...]
PRODUCT_DIRS = [c.dir for c in cfg.categories if getattr(c, 'role', None) == 'product']
CONCEPT_DIRS = [c.dir for c in cfg.categories if getattr(c, 'role', None) == 'concept']
CLINICAL_DIRS = [c.dir for c in cfg.categories if getattr(c, 'role', None) == 'clinical']
BRIDGE_DIRS = [c.dir for c in cfg.categories if getattr(c, 'role', None) == 'bridge']
ALL_CONTENT_DIRS = PRODUCT_DIRS + CONCEPT_DIRS + CLINICAL_DIRS + BRIDGE_DIRS
# Graph-recall 原文走本地 FS（不依赖 gbrain 索引）
LOCAL_SOURCE_DIRS = CLINICAL_DIRS + BRIDGE_DIRS

# Semantic concept types — order in kb-config.yml matters:
# First concept dir = technology/features, second = series/collections
TECH_CONCEPT_DIR = CONCEPT_DIRS[0] if len(CONCEPT_DIRS) > 0 else None
SERIES_CONCEPT_DIR = CONCEPT_DIRS[1] if len(CONCEPT_DIRS) > 1 else None

# Non-tech blacklist (from config, P3)
NON_TECH_BLACKLIST = set(getattr(cfg.taxonomy, 'non_tech_blacklist', []) or [])


def load_env():
    """Load environment variables from cfg.paths.env_file.
    Returns a dict. Merges with os.environ (file takes precedence).
    """
    env = dict(os.environ)
    env_file = cfg.paths.env_file
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                env[key] = val
    return env
