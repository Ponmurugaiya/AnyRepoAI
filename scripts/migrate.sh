#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# migrate.sh — Run Alembic database migrations
#
# Usage:
#   ./scripts/migrate.sh upgrade head     # Apply all pending migrations
#   ./scripts/migrate.sh downgrade -1     # Rollback one migration
#   ./scripts/migrate.sh revision --autogenerate -m "add user table"
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT/backend"

echo "🗄  Running Alembic: alembic $*"
python -m alembic "$@"
echo "✅ Migration complete"
