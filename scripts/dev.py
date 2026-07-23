#!/usr/bin/env python3
"""
scripts/dev.py
──────────────
One-command development launcher for the Codebase Intelligence Platform.

This script:
  1. Prints a startup banner with environment info
  2. Runs pre-flight checks for all four infrastructure services
  3. Launches the FastAPI backend with uvicorn hot-reload

The frontend must be started separately:
    cd frontend && npm run dev

Usage:
    # From the project root
    python scripts/dev.py

    # Skip infrastructure checks
    python scripts/dev.py --no-checks
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── Resolve project root ───────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env ─────────────────────────────────────────────────────────────────
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
MAGENTA = "\033[95m"


def print_welcome_banner() -> None:
    env = os.getenv("APP_ENVIRONMENT", "development")
    version = "0.1.0"
    env_color = GREEN if env == "development" else YELLOW

    lines = [
        "",
        f"{BOLD}{CYAN}╔══════════════════════════════════════════════════════════╗{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {BOLD}Codebase Intelligence Platform{RESET}  {DIM}v{version}{RESET}               {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}║{RESET}  Environment: {env_color}{env}{RESET}                                    {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}╠══════════════════════════════════════════════════════════╣{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {GREEN}Backend API{RESET}   →  http://localhost:8000/api/v1/health   {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {GREEN}API Docs{RESET}      →  http://localhost:8000/api/docs        {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {GREEN}Frontend{RESET}      →  http://localhost:3000                 {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {MAGENTA}Neo4j UI{RESET}      →  http://localhost:7474                 {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {MAGENTA}Qdrant UI{RESET}     →  http://localhost:6333/dashboard       {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}╠══════════════════════════════════════════════════════════╣{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {DIM}Frontend: cd frontend && npm run dev{RESET}                  {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}║{RESET}  {DIM}Stop:     Ctrl+C{RESET}                                      {BOLD}{CYAN}║{RESET}",
        f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════╝{RESET}",
        "",
    ]
    for line in lines:
        print(line)


def check_env_file() -> None:
    """Warn if no .env file is found."""
    has_env = (PROJECT_ROOT / ".env").exists() or (PROJECT_ROOT / "backend" / ".env").exists()
    if not has_env:
        print(
            f"  {YELLOW}⚠{RESET}  No .env file found. "
            f"Copy backend/.env.example → backend/.env and fill in your values.\n"
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the Codebase Intelligence Platform in development mode"
    )
    parser.add_argument(
        "--no-checks",
        action="store_true",
        help="Skip pre-flight infrastructure checks",
    )
    args = parser.parse_args()

    print_welcome_banner()
    check_env_file()

    # Delegate to start_backend which handles checks + uvicorn
    from scripts.start_backend import run_preflight_checks, start_uvicorn  # type: ignore[import]

    if not args.no_checks:
        all_ok = run_preflight_checks()
        if not all_ok:
            print(
                f"\n  {RED}One or more services are unreachable.{RESET}\n"
                f"  Start the missing services then re-run: {CYAN}python scripts/dev.py{RESET}\n"
                f"  Or skip checks with: {CYAN}python scripts/dev.py --no-checks{RESET}\n"
            )
            return 1

    start_uvicorn(reload=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
