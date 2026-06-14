#!/usr/bin/env bash
# 手动触发 Outbound Agent：导入示例线索并批量发送开发信
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

# 加载 .env（如有）
if [[ -f .env ]]; then
  while IFS='=' read -r k v; do
    [[ -z "$k" || "$k" =~ ^# ]] && continue
    v="${v%\"}"; v="${v#\"}"
    v="${v%\'}"; v="${v#\'}"
    export "$k=$v"
  done < .env
fi

MODE="${1:-real}"
LIMIT="${2:-10}"

echo "[outbound_agent] mode=$MODE limit=$LIMIT"
./.venv/bin/python - <<PY
import asyncio
import sys
sys.path.insert(0, ".")

from backend.storage_backend import storage
from backend.agents.outbound.scheduler import import_sample_leads, process_outbound_batch

async def main():
    await storage.init()
    created, skipped = await import_sample_leads()
    print(f"[import] created={created} skipped={skipped}")
    result = await process_outbound_batch(limit=int("$LIMIT"), dry_run=("$MODE" == "dry-run"))
    print(f"[outbound] {result}")

asyncio.run(main())
PY
