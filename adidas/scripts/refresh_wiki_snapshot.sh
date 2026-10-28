#!/usr/bin/env bash
# Refresh adidas/wiki snapshot from the generic LLM-Wiki (explicit, manual only).
# Never writes back to the source; never touches medical.
set -euo pipefail
SRC="${ADIDAS_WIKI_SRC:-/Users/edwin.zhou/Documents/LLM-Wiki/通用版LLM-WIKI-KB}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DST="$ROOT/wiki"
mkdir -p "$DST"
for d in 运动表现产品 三叶草产品 轻运动产品 科技 系列; do
  if [[ ! -d "$SRC/$d" ]]; then
    echo "missing source dir: $SRC/$d" >&2
    exit 1
  fi
  echo "rsync $d ..."
  rsync -a --delete "$SRC/$d/" "$DST/$d/"
done
echo "done → $DST"
du -sh "$DST"
