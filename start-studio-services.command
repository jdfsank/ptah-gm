#!/bin/bash
set -euo pipefail
studio_repository="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$studio_repository"
exec "$studio_repository/.venv/bin/python" -m tools.studio_services start "$@"
