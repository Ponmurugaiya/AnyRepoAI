#!/usr/bin/env python3
"""
scripts/start_backend.py
────────────────────────
Native backend startup script for the Codebase Intelligence Platform.

Responsibilities:
  1. Load environment variables from .env / backend/.env
  2. Run pre-flight connectivity checks against all four infrastructure services:
       PostgreSQL · Redis · Neo4j · Qdrant
  3. Launch the FastAPI server via uvicorn with hot-reload enabled

Usage:
    # From the project root
    python scripts/start_backend.py

    # Skip infrastructure checks (fast start, useful if services known-good)
    python scripts/start_backend.py --no-checks

    # Production mode (no reload)
    python scripts/start_backend.py --prod
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ── Resolve project root ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env before importing anything that reads env vars ──────────────────
try:
    from dotenv import load_dotenv  # type: ignore[import]

    for _f in [PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"]:
        if _f.exists():
            load_dotenv(_f, override=False)
except ImportError:
    pass


# ── Console helpers ───────────────────────────────────────────────────────────

RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"


def ok(label: str, msg: str = "") -> None:
    suffix = f"  {DIM}{msg}{RESET}" if msg else ""
    print(f"  {GREEN}✔{RESET}  {BOLD}{label}{RESET}{suffix}")


def fail(label: str, msg: str = "") -> None:
    suffix = f"  {DIM}{msg}{RESET}" if msg else ""
    print(f"  {RED}✘{RESET}  {BOLD}{label}{RESET}{suffix}")


def info(msg: str) -> None:
    print(f"  {CYAN}→{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def banner(title: str) -> None:
    width = 60
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}\n")


def print_service_urls() -> None:
    print(f"\n{BOLD}  Service URLs{RESET}")
    print(f"  {GREEN}Backend API{RESET}   →  http://localhost:8000/api/v1/health")
    print(f"  {GREEN}API Docs{RESET}      →  http://localhost:8000/api/docs")
    print(f"  {GREEN}Frontend{RESET}      →  http://localhost:3000")
    print(f"  {GREEN}Neo4j UI{RESET}      →  http://localhost:7474")
    print(f"  {GREEN}Qdrant UI{RESET}     →  http://localhost:6333/dashboard\n")


# ── Pre-flight checks ─────────────────────────────────────────────────────────

def check_postgres() -> bool:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    dbname = os.getenv("POSTGRES_DB", "codebase_intel")
    try:
        import psycopg2  # type: ignore[import]
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password,
            dbname=dbname, connect_timeout=5,
        )
        conn.close()
        ok("PostgreSQL", f"{host}:{port}/{dbname}")
        return True
    except Exception as exc:
        fail("PostgreSQL", str(exc))
        return False


def check_redis() -> bool:
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    password = os.getenv("REDIS_PASSWORD") or None
    try:
        import redis as redis_lib  # type: ignore[import]
        client = redis_lib.Redis(
            host=host, port=port, password=password,
            socket_connect_timeout=5, socket_timeout=5,
        )
        client.ping()
        client.close()
        ok("Redis", f"{host}:{port}")
        return True
    except Exception as exc:
        fail("Redis", str(exc))
        return False


def check_neo4j() -> bool:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j_password")
    try:
        from neo4j import GraphDatabase  # type: ignore[import]
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        driver.close()
        ok("Neo4j", uri)
        return True
    except Exception as exc:
        fail("Neo4j", str(exc))
        return False


def check_qdrant() -> bool:
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    api_key = os.getenv("QDRANT_API_KEY") or None
    try:
        from qdrant_client import QdrantClient  # type: ignore[import]
        client = QdrantClient(host=host, port=port, api_key=api_key, timeout=5)
        client.get_collections()
        ok("Qdrant", f"{host}:{port}")
        return True
    except Exception as exc:
        fail("Qdrant", str(exc))
        return False


def run_preflight_checks() -> bool:
    """Run all four service checks. Returns True if all pass."""
    banner("Pre-flight Service Checks")
    results = [
        check_postgres(),
        check_redis(),
        check_neo4j(),
        check_qdrant(),
    ]
    all_ok = all(results)
    print()
    if all_ok:
        ok("All services reachable", "starting backend…")
    else:
        failed_count = results.count(False)
        warn(
            f"{failed_count} service(s) unreachable. "
            "Fix connectivity issues or start missing services before retrying."
        )
    return all_ok


# ── Uvicorn launcher ──────────────────────────────────────────────────────────

def start_uvicorn(reload: bool = True) -> None:
    """Start uvicorn directly (same process — replaces the current process)."""
    banner("Starting FastAPI Backend")
    print_service_urls()
    time.sleep(0.5)

    import uvicorn  # type: ignore[import]

    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
        reload_dirs=[str(PROJECT_ROOT / "backend")] if reload else None,
        log_level=os.getenv("APP_LOG_LEVEL", "info").lower(),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the Codebase Intelligence Platform backend"
    )
    parser.add_argument(
        "--no-checks",
        action="store_true",
        help="Skip pre-flight infrastructure checks and start immediately",
    )
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Production mode — disables hot-reload",
    )
    args = parser.parse_args()

    banner("Codebase Intelligence Platform — Backend Startup")

    if not args.no_checks:
        all_ok = run_preflight_checks()
        if not all_ok:
            print(
                f"  {RED}Aborting. Ensure all services are running and retry.{RESET}\n"
            )
            print(
                f"  {CYAN}Tip:{RESET} use --no-checks to skip this gate.\n"
            )
            return 1

    start_uvicorn(reload=not args.prod)
    return 0


if __name__ == "__main__":
    sys.exit(main())
