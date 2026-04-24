#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
conda run -n video-platform python -m uvicorn apps.api.app.main:app --reload --host 0.0.0.0 --port 8000
