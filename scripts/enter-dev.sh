#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="video-platform"

cd "$ROOT_DIR"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is not available on PATH."
  exit 1
fi

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Conda environment '$ENV_NAME' does not exist."
  echo "Create it with:"
  echo "  conda create -n video-platform --override-channels -c conda-forge python=3.12 pip ffmpeg -y"
  echo "  conda activate video-platform"
  echo "  pip install -r requirements.txt"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Please start Docker Desktop, then run this script again."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

docker compose up -d

conda run -n "$ENV_NAME" alembic upgrade head

echo
echo "Development environment is ready."
echo
echo "Run these commands to enter the Python environment and start the API:"
echo "  cd $ROOT_DIR"
echo "  conda activate $ENV_NAME"
echo "  ./scripts/start-api.sh"
echo
echo "Run this command to start the frontend:"
echo "  ./scripts/start-web.sh"
echo
echo "Useful URLs:"
echo "  API docs:      http://localhost:8000/docs"
echo "  Web app:       http://localhost:3000"
echo "  MinIO console: http://localhost:9001"
echo
echo "MinIO login:"
echo "  user:     minioadmin"
echo "  password: minioadmin"
