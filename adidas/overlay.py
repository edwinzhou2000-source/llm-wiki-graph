"""overlay.py — Writable layer under adidas KB_ROOT (never writes SOURCE_KB_ROOT).

Approved / direct-ingest pages live in `_accepted/<slug>.md`.
Readers should prefer overlay over the read-only source KB.
"""

from __future__ import annotations

import os
from pathlib import Path

from config import KB_ROOT, SOURCE_KB_ROOT, assert_writable_under_kb

ACCEPTED_DIR = os.path.join(KB_ROOT, "_accepted")
PROPOSALS_DIR = os.path.join(KB_ROOT, "_proposals")
UPLOADS_DIR = os.path.join(KB_ROOT, "_uploads")
BACKUPS_DIR = os.path.join(KB_ROOT, "_backups")
META_DIR = os.path.join(KB_ROOT, "_meta")


def ensure_dirs() -> None:
    for d in (ACCEPTED_DIR, PROPOSALS_DIR, UPLOADS_DIR, BACKUPS_DIR, META_DIR,
              os.path.join(UPLOADS_DIR, "_archived"),
              os.path.join(UPLOADS_DIR, "_review_staging")):
        os.makedirs(d, exist_ok=True)


def accepted_path(slug: str) -> str:
    slug = slug.strip().lstrip("/").removesuffix(".md")
    return os.path.join(ACCEPTED_DIR, slug + ".md")


def source_path(slug: str) -> str:
    slug = slug.strip().lstrip("/").removesuffix(".md")
    return os.path.join(SOURCE_KB_ROOT, slug + ".md")


def resolve_readable(slug: str) -> str | None:
    """Return filesystem path for slug: overlay first, then source."""
    ap = accepted_path(slug)
    if os.path.isfile(ap):
        return ap
    sp = source_path(slug)
    if os.path.isfile(sp):
        return sp
    return None


def read_page(slug: str, max_chars: int = 50000) -> str:
    path = resolve_readable(slug)
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return text[:max_chars]


def write_accepted(slug: str, content: str) -> str:
    """Write markdown into overlay. Returns absolute path written."""
    ensure_dirs()
    path = assert_writable_under_kb(accepted_path(slug))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        import shutil
        import time
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe = slug.replace("/", "_")
        bak = assert_writable_under_kb(os.path.join(BACKUPS_DIR, f"{safe}.{ts}.md"))
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    return path


def list_accepted_slugs() -> list[str]:
    ensure_dirs()
    out = []
    root = Path(ACCEPTED_DIR)
    if not root.is_dir():
        return out
    for md in root.rglob("*.md"):
        out.append(str(md.relative_to(root).with_suffix("")).replace("\\", "/"))
    return out
