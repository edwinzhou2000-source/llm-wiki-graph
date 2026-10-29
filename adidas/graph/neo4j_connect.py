"""Neo4j connection settings from environment (no hardcoded passwords).

Prefer ADIDAS_NEO4J_* vars. Optionally load graph/.env (never commit that file).
"""

from __future__ import annotations

import os
from pathlib import Path

_GRAPH_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def neo4j_auth() -> tuple[str, tuple[str, str]]:
    """Return (uri, (user, password)). Raises if password is unset."""
    _load_dotenv(_GRAPH_DIR / ".env")
    uri = os.environ.get("ADIDAS_NEO4J_URI", "bolt://localhost:7688")
    user = os.environ.get("ADIDAS_NEO4J_USER", "neo4j")
    password = os.environ.get("ADIDAS_NEO4J_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "ADIDAS_NEO4J_PASSWORD is required. "
            "Copy adidas/graph/.env.example → adidas/graph/.env and set a local password "
            "(also set NEO4J_AUTH for docker compose)."
        )
    return uri, (user, password)
