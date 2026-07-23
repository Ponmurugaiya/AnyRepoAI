# Codebase Intelligence Platform

A production-grade AI platform for querying GitHub repositories through natural language. This repository contains the **infrastructure foundation** — RAG, embeddings, and LLM features will be layered on in subsequent milestones.

---

## Architecture

The system follows **Clean Architecture** with feature-based modules. Dependencies always point inward: HTTP handlers → services → repositories → DB/infra clients.

```
┌─────────────────────────────────────────────────────┐
│                      Frontend                        │
│           Next.js 14 · TypeScript · Tailwind         │
└───────────────────────┬─────────────────────────────┘
                        │ HTTP / REST
┌───────────────────────▼─────────────────────────────┐
│                 FastAPI Backend                       │
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │  API    │  │ Services │  │   Repositories     │  │
│  │ (HTTP)  │→ │(Business)│→ │ (Data Access)      │  │
│  └─────────┘  └──────────┘  └────────┬───────────┘  │
│                                       │              │
│  ┌────────────────────────────────────▼───────────┐  │
│  │          Infrastructure Clients                │  │
│  │  PostgreSQL  │  Redis  │  Neo4j  │  Qdrant     │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer          | Technology                          |
|----------------|-------------------------------------|
| Backend        | FastAPI 0.111, Python 3.12          |
| ORM            | SQLAlchemy 2.x (async)              |
| Migrations     | Alembic                             |
| Validation     | Pydantic v2 + pydantic-settings     |
| Logging        | structlog (JSON output)             |
| Relational DB  | PostgreSQL 16                       |
| Cache          | Redis 7                             |
| Graph DB       | Neo4j 5                             |
| Vector DB      | Qdrant 1.10                         |
| Frontend       | Next.js 14, TypeScript, Tailwind v3 |
| Runtime        | Python venv + npm (no Docker)       |

---

## Project Structure

```
.
├── backend/
│   ├── alembic/                  # Database migration scripts
│   │   ├── versions/
│   │   │   └── 001_create_repositories_table.py
│   │   ├── env.py                # Alembic runtime config
│   │   └── script.py.mako        # Migration file template
│   ├── alembic.ini               # Alembic configuration
│   ├── .env.example              # Backend environment variable template
│   └── app/
│       ├── main.py               # FastAPI app factory + lifespan
│       ├── api/
│       │   ├── router.py         # Aggregates all v1 routes
│       │   ├── exception_handlers.py
│       │   └── v1/
│       │       ├── health.py     # GET /health, GET /version
│       │       └── repositories.py
│       ├── core/
│       │   ├── config.py         # pydantic-settings configuration
│       │   ├── exceptions.py     # Domain exceptions
│       │   └── logging.py        # structlog JSON logging setup
│       ├── db/
│       │   ├── base.py           # DeclarativeBase + AuditMixin
│       │   ├── session.py        # Async engine + session factory
│       │   └── health.py         # PostgreSQL health probe
│       ├── infrastructure/       # Redis / Qdrant / Neo4j / GitHub clients
│       └── workers/
│           └── celery_app.py     # Celery app + clone_repository_task
├── frontend/
│   ├── .env.example              # Frontend environment variable template
│   └── src/
├── scripts/
│   ├── init_db.py                # Verify Postgres + run Alembic migrations
│   ├── start_backend.py          # Pre-flight checks + uvicorn launcher
│   ├── dev.py                    # One-command dev startup banner + launcher
│   └── migrate.sh                # Thin Alembic wrapper (bash)
├── tests/
├── pyproject.toml                # Python dependencies
└── .env.example                  # Root environment variable template
```

---

## Running Locally

### Prerequisites

Install the following on your machine before proceeding:

| Tool            | Minimum Version | Download |
|-----------------|-----------------|----------|
| Python          | 3.12            | https://python.org/downloads |
| Node.js         | 20 LTS          | https://nodejs.org |
| PostgreSQL      | 16              | https://www.postgresql.org/download |
| Redis           | 7               | https://redis.io/docs/getting-started |
| Neo4j Community | 5.x             | https://neo4j.com/download |
| Qdrant          | 1.10            | https://qdrant.tech/documentation/quick-start |

> **Windows users**: Redis is available via [Memurai](https://www.memurai.com/) or WSL2. Neo4j and Qdrant ship Windows installers.

---

### 1. Clone the repository

```bash
git clone <repo-url>
cd codebase-intelligence-platform
```

---

### 2. Configure environment variables

```bash
# Backend
cp backend/.env.example backend/.env

# Frontend
cp frontend/.env.example frontend/.env.local
```

Open `backend/.env` and update at minimum:

```dotenv
POSTGRES_PASSWORD=your_postgres_password
NEO4J_PASSWORD=your_neo4j_password
REPO_GITHUB_TOKEN=ghp_...   # Optional — raises GitHub API rate limits
```

---

### 3. Create Python virtual environment

```bash
# Create venv
python -m venv .venv

# Activate — Linux / macOS
source .venv/bin/activate

# Activate — Windows PowerShell
.venv\Scripts\Activate.ps1
```

---

### 4. Install Python dependencies

```bash
# Install all dependencies (including dev tools)
pip install -e ".[dev]"
```

---

### 5. Start infrastructure services

Start each service using its native installer or package manager. All services must be reachable on `localhost`.

**PostgreSQL** — default port `5432`
```bash
# macOS (Homebrew)
brew services start postgresql@16

# Linux (systemd)
sudo systemctl start postgresql

# Windows
# Use pgAdmin or the PostgreSQL Windows service manager
```

**Redis** — default port `6379`
```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis

# Windows (Memurai or WSL2)
redis-server
```

**Neo4j** — Bolt port `7687`, Browser UI `7474`
```bash
# macOS / Linux
neo4j start

# Windows
# Start via Neo4j Desktop or the Windows service
```

**Qdrant** — HTTP port `6333`
```bash
# Using the Qdrant binary
./qdrant

# Or via cargo
cargo run --release
```

---

### 6. Initialize the database

Verifies PostgreSQL connectivity, creates the database if needed, and applies all Alembic migrations.

```bash
python scripts/init_db.py
```

Expected output:
```
──────────────────────────────────────────────────────────────
  Codebase Intelligence Platform — Database Init
──────────────────────────────────────────────────────────────

  →  Connecting to PostgreSQL: postgres@localhost:5432 / db=codebase_intel
  ✔  PostgreSQL reachable at localhost:5432
  ✔  Database 'codebase_intel' already exists

──────────────────────────────────────────────────────────────
  Running Alembic Migrations
──────────────────────────────────────────────────────────────
  ✔  Alembic migrations applied successfully
```

---

### 7. Start the backend

```bash
# Full startup with pre-flight checks (recommended)
python scripts/dev.py

# Or just the backend launcher
python scripts/start_backend.py

# Skip service checks (if services are known-good)
python scripts/start_backend.py --no-checks
```

The script checks all four services before launching uvicorn:

```
  ✔  PostgreSQL    localhost:5432/codebase_intel
  ✔  Redis         localhost:6379
  ✔  Neo4j         bolt://localhost:7687
  ✔  Qdrant        localhost:6333
```

Then starts uvicorn with hot-reload on **http://localhost:8000**.

> **Manual alternative** (if you prefer raw uvicorn):
> ```bash
> uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
> ```

---

### 8. Start the frontend

In a **separate terminal**:

```bash
cd frontend
npm install          # First run only
npm run dev          # http://localhost:3000
```

The frontend proxies all `/api/*` requests to `http://localhost:8000` automatically.

---

### 9. Verify everything is running

| Service      | URL                                    |
|--------------|----------------------------------------|
| Backend API  | http://localhost:8000/api/v1/health    |
| API Docs     | http://localhost:8000/api/docs         |
| Frontend     | http://localhost:3000                  |
| Neo4j UI     | http://localhost:7474                  |
| Qdrant UI    | http://localhost:6333/dashboard        |

A healthy response from the health endpoint:

```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "version": "0.1.0",
    "dependencies": {
      "postgres": { "status": "healthy" },
      "redis":    { "status": "healthy" },
      "neo4j":    { "status": "healthy" },
      "qdrant":   { "status": "healthy" }
    }
  }
}
```

---

## Database Migrations

```bash
# Apply all pending migrations
python scripts/init_db.py

# Or run Alembic directly (from backend/ directory)
cd backend
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Generate a new migration (after model changes)
alembic revision --autogenerate -m "describe your change"

# Using the bash wrapper
./scripts/migrate.sh upgrade head
```

---

## Running Tests

```bash
# Unit tests (no infrastructure required)
pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
pytest tests/integration/ -v

# All tests with coverage
pytest tests/ --cov=backend --cov-report=term-missing
```

---

## Environment Variables

See `backend/.env.example` for the full list. Key variables:

| Variable              | Default               | Description                          |
|-----------------------|-----------------------|--------------------------------------|
| `APP_ENVIRONMENT`     | `development`         | `development`, `staging`, `production` |
| `APP_DEBUG`           | `true`                | Enable API docs + verbose errors     |
| `POSTGRES_PASSWORD`   | `change_me_in_production` | **Change before any non-local use** |
| `NEO4J_PASSWORD`      | `change_me_in_production` | **Change before any non-local use** |
| `REPO_CLONE_ROOT`     | `./storage/repos`     | Where cloned repos are stored        |
| `REPO_GITHUB_TOKEN`   | *(empty)*             | Optional PAT for higher rate limits  |
| `OPENAI_API_KEY`      | *(empty)*             | For future LLM / embedding features  |

---

## API Response Envelope

Every endpoint returns the same JSON shape:

```json
{
  "success": true,
  "data": { "...": "payload" },
  "message": "Human-readable summary",
  "errors": []
}
```

---

## Logging

All log records are emitted as JSON to stdout:

```json
{
  "timestamp": "2026-07-22T10:30:00Z",
  "level": "info",
  "message": "HTTP request processed",
  "request_id": "01J...",
  "method": "GET",
  "path": "/api/v1/health",
  "status_code": 200,
  "latency_ms": 12.4,
  "app": "Codebase Intelligence Platform",
  "environment": "development"
}
```

---

## Repository Management

### API Endpoints

| Method   | Path                        | Status | Description                              |
|----------|-----------------------------|--------|------------------------------------------|
| `POST`   | `/api/v1/repositories`      | 202    | Register a GitHub repo and enqueue clone |
| `GET`    | `/api/v1/repositories`      | 200    | List all registered repositories         |
| `GET`    | `/api/v1/repositories/{id}` | 200    | Get full detail for a single repository  |
| `DELETE` | `/api/v1/repositories/{id}` | 200    | Delete record and local clone            |

### Repository Status Lifecycle

```
PENDING → CLONING → READY
                  ↘ FAILED
READY   → SYNCING → READY
                  ↘ FAILED
```

### Clone Storage Layout

```
./storage/repos/
└── {repository_uuid}/
    ├── .git/
    ├── README.md
    └── ...
```

---

## Next Milestones

- [x] Repository ingestion API (`POST /repositories`)
- [x] Git clone worker (Celery + BackgroundTasks fallback)
- [x] GitHub metadata extraction
- [ ] AST parsing pipeline
- [ ] Dependency graph construction (Neo4j)
- [ ] Embedding generation (Qdrant)
- [ ] Hybrid + graph retrieval
- [ ] AI chat over repositories
