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
│   └── app/
│       ├── main.py               # FastAPI app factory + lifespan
│       ├── api/
│       │   ├── router.py         # Aggregates all v1 routes
│       │   ├── exception_handlers.py
│       │   └── v1/
│       │       ├── health.py     # GET /health, GET /version
│       │       └── repositories.py  # POST/GET/DELETE /repositories
│       ├── core/
│       │   ├── config.py         # pydantic-settings (+ RepositorySettings)
│       │   ├── exceptions.py     # Domain exceptions (+ repo-specific)
│       │   └── logging.py        # structlog JSON logging setup
│       ├── db/
│       │   ├── base.py           # DeclarativeBase + AuditMixin
│       │   ├── session.py        # Async engine + session factory
│       │   └── health.py         # PostgreSQL health probe
│       ├── dependencies/
│       │   ├── database.py       # get_db() FastAPI dependency
│       │   └── infrastructure.py # Redis/Qdrant/Neo4j dependencies
│       ├── infrastructure/
│       │   ├── redis_client.py   # Redis connection + health
│       │   ├── qdrant_client.py  # Qdrant connection + health
│       │   ├── neo4j_client.py   # Neo4j connection + health
│       │   ├── github_client.py  # GitHub REST API client
│       │   └── git_client.py     # GitPython clone wrapper
│       ├── middleware/
│       │   └── request_id.py     # Request ID + access logging
│       ├── models/
│       │   └── repository.py     # Repository ORM model + RepositoryStatus enum
│       ├── repositories/
│       │   └── repository.py     # RepositoryRepository (data access)
│       ├── schemas/
│       │   ├── base.py           # APIResponse envelope
│       │   └── repository.py     # Request/response schemas
│       ├── services/
│       │   └── repository_service.py  # RepositoryService (business logic)
│       └── workers/
│           └── celery_app.py     # Celery app + clone_repository_task
├── tests/
│   ├── conftest.py               # Shared fixtures, test DB, mocks
│   ├── unit/
│   │   ├── test_repository_schemas.py   # URL validation tests
│   │   ├── test_repository_service.py   # Service layer unit tests
│   │   └── test_github_client.py        # GitHub client unit tests
│   └── integration/
│       └── test_repository_api.py       # Full API cycle tests
├── frontend/ ...
├── docker/
│   ├── backend.Dockerfile
│   └── frontend.Dockerfile
├── scripts/ ...
├── docker-compose.yml            # Includes Celery worker + repo_storage volume
├── pyproject.toml                # Python deps (+ gitpython, celery, flower)
└── .env.example                  # Environment variable template
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
| Container      | Docker + Docker Compose             |

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

On failure:

```json
{
  "success": false,
  "data": null,
  "message": "Validation failed.",
  "errors": [
    { "field": "url", "message": "Invalid GitHub URL", "code": "INVALID_URL" }
  ]
}
```

---

## Running Locally

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) ≥ 4.x
- Docker Compose ≥ v2

### 1. Clone and configure

```bash
git clone <repo-url>
cd codebase-intelligence-platform

# Create your .env from the template
cp .env.example .env
# Edit .env — change passwords for any non-local deployment
```

### 2. Start all services

```bash
# First run (or after Dockerfile changes)
docker compose up --build

# Subsequent runs
docker compose up
```

All services start in dependency order. The backend waits for PostgreSQL, Redis, Neo4j, and Qdrant to be healthy before accepting requests.

### 3. Verify

| Service   | URL                                    |
|-----------|----------------------------------------|
| Backend   | http://localhost:8000/api/v1/health    |
| API Docs  | http://localhost:8000/api/docs         |
| Frontend  | http://localhost:3000                  |
| Neo4j UI  | http://localhost:7474                  |
| Qdrant UI | http://localhost:6333/dashboard        |

### 4. Run database migrations

```bash
# Inside the container
docker compose exec backend python -m alembic upgrade head

# Or using the helper script (local Python env)
./scripts/migrate.sh upgrade head
```

### 5. Local backend development (without Docker)

```bash
# Create a Python 3.12 virtual environment
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Start infrastructure only (skip backend + frontend containers)
docker compose up postgres redis neo4j qdrant -d

# Copy and edit env
cp .env.example .env

# Run the backend with hot reload
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Local frontend development

```bash
cd frontend
npm install
npm run dev         # http://localhost:3000
```

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable              | Default              | Description                        |
|-----------------------|----------------------|------------------------------------|
| `APP_ENVIRONMENT`     | `development`        | `development`, `staging`, `production` |
| `APP_DEBUG`           | `true`               | Enable API docs + verbose errors   |
| `POSTGRES_PASSWORD`   | `change_me`          | **Must change for staging/prod**   |
| `NEO4J_PASSWORD`      | `change_me`          | **Must change for staging/prod**   |

---

## Logging

All log records are emitted as JSON to stdout, structured for ingestion by Datadog, CloudWatch, or similar aggregators:

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

## Health Check

`GET /api/v1/health` probes all four dependency services concurrently and returns a 200 when all are healthy, or 503 when degraded:

```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "version": "0.1.0",
    "uptime_seconds": 142.3,
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

## Next Milestones

- [x] Repository ingestion API (`POST /repositories`)
- [x] Git clone worker (Celery + BackgroundTasks fallback)
- [x] GitHub metadata extraction
- [ ] AST parsing pipeline
- [ ] Dependency graph construction (Neo4j)
- [ ] Embedding generation (Qdrant)
- [ ] Hybrid + graph retrieval
- [ ] AI chat over repositories

---

## Repository Management Module

### API Endpoints

| Method   | Path                       | Status | Description                                  |
|----------|----------------------------|--------|----------------------------------------------|
| `POST`   | `/api/v1/repositories`     | 202    | Register a GitHub repo and enqueue clone     |
| `GET`    | `/api/v1/repositories`     | 200    | List all registered repositories             |
| `GET`    | `/api/v1/repositories/{id}`| 200    | Get full detail for a single repository      |
| `DELETE` | `/api/v1/repositories/{id}`| 200    | Delete record and local clone                |

### POST /repositories — Request & Response

```json
// Request
{ "github_url": "https://github.com/owner/repo", "reclone": false }

// Immediate response (202 Accepted)
{
  "success": true,
  "data": { "id": "550e8400-e29b-41d4-a716-446655440000", "status": "PENDING" },
  "message": "Repository accepted. Cloning has been enqueued."
}
```

Poll `GET /repositories/{id}` until `status` transitions to `READY` (or `FAILED`).

### Repository Status Lifecycle

```
PENDING → CLONING → READY
                  ↘ FAILED
READY   → SYNCING → READY
                  ↘ FAILED
```

### How Cloning Works

1. **POST** arrives → URL validated (must be `https://github.com/owner/repo[.git]`).
2. Duplicate check — 409 if already registered (pass `reclone=true` to override).
3. PENDING record written to PostgreSQL; API returns `202` immediately.
4. **Celery task** (`repository.clone`) is enqueued on Redis.
   - Falls back to FastAPI `BackgroundTasks` if Celery is unavailable.
5. Worker transitions status to `CLONING` and:
   - Fetches metadata from `api.github.com` (name, description, branch, stars, language…).
   - Runs `git clone --depth=1 <url> /storage/repos/{id}/`.
   - Persists clone path, HEAD SHA, default branch, and GitHub metadata.
   - Transitions status to `READY`.
6. On any failure, status → `FAILED`; partial clone directory is removed.

### Clone Storage Layout

```
/storage/repos/
└── {repository_uuid}/
    ├── .git/
    ├── README.md
    └── ...
```

Never uses temporary directories; the UUID-based path is permanent and matches the database record.

### Accepted GitHub URL Formats

```
https://github.com/owner/repository
https://github.com/owner/repository.git
```

All other schemes or hosts are rejected with 422.

### New Environment Variables

| Variable                    | Default                        | Description                                          |
|-----------------------------|--------------------------------|------------------------------------------------------|
| `REPO_CLONE_ROOT`           | `/storage/repos`               | Root directory for all cloned repositories           |
| `REPO_CLONE_TIMEOUT`        | `300`                          | Max seconds for a git clone                          |
| `REPO_MAX_REPO_SIZE_MB`     | `2048`                         | Max repository size in MB (reserved for future use)  |
| `REPO_GITHUB_API_BASE_URL`  | `https://api.github.com`       | GitHub REST API base URL                             |
| `REPO_GITHUB_TOKEN`         | *(empty)*                      | Optional PAT for private repos and higher rate limits|

### Running Tests

```bash
# Unit tests (no infrastructure required)
pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
pytest tests/integration/ -v

# All tests with coverage
pytest tests/ --cov=backend --cov-report=term-missing
```
