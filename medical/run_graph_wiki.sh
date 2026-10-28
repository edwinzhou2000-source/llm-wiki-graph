#!/usr/bin/env bash
# Start Graph-副本 Wiki on :8770 (does not touch original :8768)
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  /usr/bin/python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi
# Ensure Neo4j has demo data (idempotent)
if [[ -f graph/sync_wiki_graph.py ]]; then
  python graph/sync_wiki_graph.py --quiet || echo "[warn] graph sync skipped — is Neo4j up?"
fi
exec python server.py
