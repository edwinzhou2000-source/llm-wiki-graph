#!/bin/bash
# gbrain-v2 — wrapper for the new LLM-Wiki knowledge brain (fully isolated)
# Usage: ./gbrain.sh stats | ./gbrain.sh search "boost" | etc.
export GBRAIN_HOME=$HOME/.gbrain-llm-wiki
export DATABASE_URL=""
cd $HOME/Documents/LLM-Wiki/通用版LLM-WIKI-KB
bun run $HOME/gbrain/src/cli.ts "$@"
