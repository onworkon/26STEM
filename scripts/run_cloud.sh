#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm_config_cache="$PWD/../.npm-cache" npm ci && npm run build)
fi
.venv/bin/python scripts/generate_frames.py
exec .venv/bin/python -m backend.app.run
