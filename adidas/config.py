"""config.py — Shared configuration loader for the adidas LLM-WIKI GRAPH replica.

Key difference from the generic KB config: this replica READS its content from
`paths.source_kb_root` (read-only) and keeps its own metadata/config under
`paths.kb_root`. It never writes to the source KB.

Usage:
    from config import cfg, KB_ROOT, SOURCE_KB_ROOT
    print(cfg.brand.name)            # "adidas"
    print(cfg.server.port)           # 8780
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


def _resolve_path(p, base):
    if p is None:
        return None
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(base, p)
    return p


# Locate kb-config.yml — in this file's directory (graph replica root)
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_CONFIG_DIR, "kb-config.yml")

if not os.path.exists(_CONFIG_PATH):
    raise FileNotFoundError(
        "kb-config.yml not found. Place it in the project root.\n"
        f"Searched: {_CONFIG_PATH}"
    )

with open(_CONFIG_PATH) as f:
    _raw = yaml.safe_load(f)

cfg = _deep_ns(_raw)

# ── Two roots ──
# KB_ROOT = this replica's own dir (config/docs/generated index live here)
KB_ROOT = os.path.dirname(os.path.abspath(_CONFIG_PATH))
# SOURCE_KB_ROOT = wiki snapshot under this replica (isolation B)
SOURCE_KB_ROOT = _resolve_path(cfg.paths.source_kb_root, KB_ROOT) or KB_ROOT

cfg.paths.kb_root = KB_ROOT
cfg.paths.source_kb_root = SOURCE_KB_ROOT
cfg.paths.gbrain_home = _resolve_path(cfg.paths.gbrain_home, KB_ROOT)
cfg.paths.env_file = _resolve_path(cfg.paths.env_file, KB_ROOT)

_KB_ROOT_REAL = os.path.realpath(KB_ROOT)
_SRC_REAL = os.path.realpath(SOURCE_KB_ROOT)
if not (_SRC_REAL == _KB_ROOT_REAL or _SRC_REAL.startswith(_KB_ROOT_REAL + os.sep)):
    raise RuntimeError(
        "Isolation violation: source_kb_root must be inside adidas KB_ROOT.\n"
        f"  KB_ROOT={_KB_ROOT_REAL}\n"
        f"  SOURCE_KB_ROOT={_SRC_REAL}\n"
        "  Fix kb-config.yml or run scripts/refresh_wiki_snapshot.sh"
    )


def assert_writable_under_kb(path: str) -> str:
    """Ensure write target is under adidas KB_ROOT (never medical / external LLM-Wiki)."""
    real = os.path.realpath(os.path.abspath(path))
    if not (real == _KB_ROOT_REAL or real.startswith(_KB_ROOT_REAL + os.sep)):
        raise RuntimeError(f"Refusing write outside adidas KB_ROOT: {real}")
    medical = os.path.realpath("/Users/edwin.zhou/Documents/LLM-WIKI-GRAPH/medical")
    ext_wiki = os.path.realpath("/Users/edwin.zhou/Documents/LLM-Wiki")
    for bad in (medical, ext_wiki):
        if real == bad or real.startswith(bad + os.sep):
            if not real.startswith(_KB_ROOT_REAL + os.sep):
                raise RuntimeError(f"Refusing write into forbidden tree: {real}")
    return real


def _flatten_dirs(cat):
    dirs = [cat.dir]
    for sub in getattr(cat, "subcategories", []) or []:
        dirs.append(os.path.join(cat.dir, sub.dir))
        for child in getattr(sub, "children", []) or []:
            dirs.append(os.path.join(cat.dir, sub.dir, child.dir))
            for grandchild in getattr(child, "children", []) or []:
                dirs.append(os.path.join(cat.dir, sub.dir, child.dir, grandchild.dir))
    return dirs


ALL_CATEGORY_DIRS = []
for c in cfg.categories:
    ALL_CATEGORY_DIRS.extend(_flatten_dirs(c))

CATEGORY_COLORS = {c.dir: c.color for c in cfg.categories}
CATEGORY_IDS = {c.dir: c.id for c in cfg.categories}


def _is_role(cat_dir, role):
    for c in cfg.categories:
        if c.dir == cat_dir:
            return getattr(c, "role", None) == role
    return False


# Pre-computed lists by role (adidas has only product + concept)
PRODUCT_DIRS = [c.dir for c in cfg.categories if getattr(c, "role", None) == "product"]
CONCEPT_DIRS = [c.dir for c in cfg.categories if getattr(c, "role", None) == "concept"]
CLINICAL_DIRS = [c.dir for c in cfg.categories if getattr(c, "role", None) == "clinical"]
BRIDGE_DIRS = [c.dir for c in cfg.categories if getattr(c, "role", None) == "bridge"]
ALL_CONTENT_DIRS = PRODUCT_DIRS + CONCEPT_DIRS + CLINICAL_DIRS + BRIDGE_DIRS

# Concept order matters: first = 科技(tech), second = 系列(series)
TECH_CONCEPT_DIR = CONCEPT_DIRS[0] if len(CONCEPT_DIRS) > 0 else None
SERIES_CONCEPT_DIR = CONCEPT_DIRS[1] if len(CONCEPT_DIRS) > 1 else None

NON_TECH_BLACKLIST = set(getattr(cfg.taxonomy, "non_tech_blacklist", []) or [])


def load_env():
    """Load environment variables from cfg.paths.env_file (file takes precedence)."""
    env = dict(os.environ)
    env_file = cfg.paths.env_file
    if env_file and os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                env[key] = val
    return env


if __name__ == "__main__":
    print("KB_ROOT        =", KB_ROOT)
    print("SOURCE_KB_ROOT =", SOURCE_KB_ROOT)
    print("isolation_ok   =", _SRC_REAL.startswith(_KB_ROOT_REAL))
    print("PRODUCT_DIRS   =", PRODUCT_DIRS)
    print("CONCEPT_DIRS   =", CONCEPT_DIRS)
    print("TECH_CONCEPT   =", TECH_CONCEPT_DIR)
    print("SERIES_CONCEPT =", SERIES_CONCEPT_DIR)
    print("ALL_CONTENT    =", ALL_CONTENT_DIRS)
