#!/usr/bin/env python3
"""
scripts/init_db.py
──────────────────
Database initialization script for the Codebase Intelligence Platform.

Responsibilities:
  1. Load environment variables from .env / backend/.env
  2. Verify PostgreSQL connectivity
  3. Create the target database if it does not exist
  4. Run Alembic migrations (upgrade head)

Usage:
    # From the project root
    python scripts/init_db.py

    # Or with a custom env file
    ENV_FILE=backend/.env python scripts/init_db.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ── Resolve project root and add to sys.path ──────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env before importing app settings ───────────────────────────────────
try:
    from dotenv import load_dotenv  # type: ignore[import]

    _env_files = [PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"]
    for _f in _env_files:
        if _f.exists():
            load_dotenv(_f, override=False)
            print(f"  Loaded env: {_f}")
except ImportError:
    # python-dotenv not installed — rely on os.environ being pre-set
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✔{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✘{RESET}  {msg}")


def info(msg: str) -> None:
    print(f"  {CYAN}→{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def banner(title: str) -> None:
    width = 60
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}\n")


# ── PostgreSQL check ──────────────────────────────────────────────────────────

def verify_postgres() -> dict:
    """Return connection params loaded from environment."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "dbname": os.getenv("POSTGRES_DB", "codebase_intel"),
    }


def check_postgres(params: dict) -> bool:
    """Try to connect to PostgreSQL. Returns True on success."""
    try:
        import psycopg2  # type: ignore[import]
    except ImportError:
        fail("psycopg2 not installed. Run: pip install psycopg2-binary")
        return False

    # First connect to 'postgres' default DB to allow creating the target DB
    try:
        conn = psycopg2.connect(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            dbname="postgres",
            connect_timeout=5,
        )
        conn.autocommit = True
        ok(f"PostgreSQL reachable at {params['host']}:{params['port']}")
        return True, conn
    except Exception as exc:
        fail(f"Cannot connect to PostgreSQL: {exc}")
        return False, None


def ensure_database_exists(conn, dbname: str) -> None:
    """Create the target database if it doesn't already exist."""
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
    exists = cursor.fetchone()
    if not exists:
        cursor.execute(f'CREATE DATABASE "{dbname}"')
        ok(f"Created database '{dbname}'")
    else:
        ok(f"Database '{dbname}' already exists")
    cursor.close()
    conn.close()


# ── Alembic migration ─────────────────────────────────────────────────────────

def run_alembic_migrations() -> bool:
    """Run `alembic upgrade head` from the backend directory."""
    alembic_dir = PROJECT_ROOT / "backend"
    if not (alembic_dir / "alembic.ini").exists():
        fail(f"alembic.ini not found in {alembic_dir}")
        return False

    info("Running: alembic upgrade head")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(alembic_dir),
        capture_output=False,
    )

    if result.returncode == 0:
        ok("Alembic migrations applied successfully")
        return True
    else:
        fail(f"Alembic exited with code {result.returncode}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    banner("Codebase Intelligence Platform — Database Init")

    # Step 1: Load + verify PostgreSQL params
    params = verify_postgres()
    info(
        f"Connecting to PostgreSQL: {params['user']}@{params['host']}:{params['port']}"
        f" / db={params['dbname']}"
    )

    success, conn = check_postgres(params)
    if not success:
        print(
            f"\n  {RED}Fix your PostgreSQL connection settings in backend/.env and retry.{RESET}\n"
        )
        return 1

    # Step 2: Ensure target DB exists
    print()
    info(f"Ensuring database '{params['dbname']}' exists...")
    ensure_database_exists(conn, params["dbname"])

    # Step 3: Run Alembic
    print()
    banner("Running Alembic Migrations")
    if not run_alembic_migrations():
        return 1

    # Done
    print()
    banner("Database Initialization Complete")
    ok("All migrations applied.")
    print(
        f"\n  {CYAN}Next step:{RESET} python scripts/start_backend.py\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
