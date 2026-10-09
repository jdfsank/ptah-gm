#!/bin/bash
set -euo pipefail
workflow_root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$workflow_root"
if [[ ! -x "$workflow_root/.venv/bin/python" ]]; then
  echo "Missing local Python runtime. Follow backend/README.zh-CN.md to install it."
  exit 1
fi
exec "$workflow_root/.venv/bin/python" -m backend.server --port 8765
