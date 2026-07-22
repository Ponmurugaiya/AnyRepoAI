#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start-dev.sh — Start the full development environment
#
# Usage:
#   ./scripts/start-dev.sh           # Start all services
#   ./scripts/start-dev.sh --build   # Rebuild images before starting
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# ── Environment setup ─────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
  echo "⚠  .env not found — copying from .env.example"
  cp .env.example .env
  echo "✏  Edit .env with your secrets before running in production"
fi

# ── Docker Compose ────────────────────────────────────────────────────────────
BUILD_FLAG=""
if [[ "${1:-}" == "--build" ]]; then
  BUILD_FLAG="--build"
fi

echo "🚀 Starting Codebase Intelligence Platform..."
docker compose up $BUILD_FLAG --remove-orphans

echo "✅ Services started. URLs:"
echo "   Backend API : http://localhost:8000/api/v1/health"
echo "   API Docs    : http://localhost:8000/api/docs"
echo "   Frontend    : http://localhost:3000"
echo "   Neo4j UI    : http://localhost:7474"
echo "   Qdrant UI   : http://localhost:6333/dashboard"
