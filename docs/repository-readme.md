# Repository Management Module

## Overview

The Repository Management module is the **entry point** of the Codebase Intelligence Platform.
It accepts a GitHub repository URL, validates it, clones the repository to local storage,
fetches metadata from the GitHub REST API, and tracks the repository lifecycle through a
well-defined set of statuses.

**Explicit out-of-scope:** This module does NOT perform file scanning, AST parsing,
embeddings, vector search, graph construction, or any AI features. Those belong to
downstream modules that consume the cloned repository produced here.

---

## Architecture

```
POST /api/v1/repositories
         │
         ▼
  RepositoryService.create_repository()
         │  validates URL format
         │  checks for duplicate (github_url unique constraint)
         │  creates PENDING record in PostgreSQL
         │
         ▼
  _enqueue_clone()
         │  tries Celery first → falls back to FastAPI BackgroundTasks
         │
         ▼
  clone_repository_task  (Celery worker)
         │
         ▼
  RepositoryService.run_clone_pipeline()
         │  status → CLONING
         │
         ├──► GitHubClient.get_repository()   (GitHub REST API)
         │         extracts: name, owner, branch, stars, language…
         │
         ├──► clone_repository()              (GitPython, depth=1)
         │         writes to /storage/repos/{uuid}/
         │
         ├──► RepositoryRepository.update_clone_metadata()
         ├──► RepositoryRepository.update_github_metadata()
         │
         ▼
  status → READY  (or FAILED on any error)
```

### Clean Architecture Layers

| Layer | Location | Responsibility |
|-------|----------|----------------|
| API | `app/api/v1/repositories.py` | HTTP endpoints, response shaping |
| Service | `app/services/repository_service.py` | Orchestration, status transitions |
| Repository | `app/repositories/repository.py` | DB reads / writes only |
| Model | `app/models/repository.py` | SQLAlchemy ORM + `RepositoryStatus` enum |
| Schemas | `app/schemas/repository.py` | Pydantic request / response models |
| Infrastructure | `app/infrastructure/github_client.py` | GitHub REST API client |
| Infrastructure | `app/infrastructure/git_client.py` | GitPython shallow clone wrapper |
| Worker | `app/workers/celery_app.py` | Celery app + `clone_repository_task` |

---

## Folder Structure

```
backend/
├── alembic/
│   └── versions/
│       └── 001_create_repositories_table.py   ← DB migration
└── app/
    ├── api/
    │   └── v1/
    │       └── repositories.py                ← POST / GET / DELETE endpoints
    ├── core/
    │   ├── config.py                          ← RepositorySettings sub-model
    │   └── exceptions.py                      ← Repository-specific exceptions
    ├── infrastructure/
    │   ├── github_client.py                   ← GitHub REST API client (httpx + tenacity)
    │   └── git_client.py                      ← GitPython clone / remove helpers
    ├── models/
    │   └── repository.py                      ← Repository ORM model + RepositoryStatus enum
    ├── repositories/
    │   └── repository.py                      ← RepositoryRepository (data access)
    ├── schemas/
    │   └── repository.py                      ← Request / response Pydantic schemas
    ├── services/
    │   └── repository_service.py              ← RepositoryService (business logic)
    └── workers/
        └── celery_app.py                      ← Celery app + clone_repository_task

tests/
├── unit/
│   ├── test_repository_schemas.py             ← URL validation tests
│   ├── test_repository_service.py             ← Service layer unit tests
│   └── test_github_client.py                  ← GitHub client error handling tests
└── integration/
    └── test_repository_api.py                 ← Full API cycle tests (real DB, mocked I/O)
```

---

## Database Schema

### `repositories` Table

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | UUID | NO | Primary key (`gen_random_uuid()`) |
| `owner` | VARCHAR(255) | NO | GitHub owner login (user or organisation) |
| `name` | VARCHAR(255) | NO | Repository name without owner prefix |
| `full_name` | VARCHAR(512) | NO | Canonical `owner/name` — **unique** |
| `github_url` | VARCHAR(512) | NO | Normalised HTTPS URL (no `.git`) — **unique** |
| `default_branch` | VARCHAR(255) | YES | Primary branch name (e.g. `main`) |
| `local_path` | VARCHAR(1024) | YES | Absolute path to local clone |
| `current_commit` | VARCHAR(40) | YES | HEAD commit SHA |
| `clone_status` | `repository_status` | NO | Lifecycle status (default `PENDING`) |
| `description` | TEXT | YES | GitHub repository description |
| `visibility` | VARCHAR(16) | YES | `public` or `private` |
| `language` | VARCHAR(100) | YES | Primary programming language |
| `stars` | INTEGER | NO | Stargazer count at last sync (default `0`) |
| `forks` | INTEGER | NO | Fork count at last sync (default `0`) |
| `created_at` | TIMESTAMPTZ | NO | Record creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | Last update timestamp |
| `last_synced_at` | TIMESTAMPTZ | YES | Timestamp of last GitHub metadata sync |

**Indexes:**
- Unique: `full_name`, `github_url`
- Single: `owner`, `name`, `full_name`, `github_url`, `clone_status`

### `repository_status` Enum

| Value | Description |
|-------|-------------|
| `PENDING` | Record created; clone not yet started |
| `CLONING` | Clone in progress |
| `READY` | Clone complete; metadata extracted |
| `FAILED` | Clone or metadata extraction failed |
| `SYNCING` | Re-sync of metadata in progress |

**Status transitions:**
```
PENDING → CLONING → READY
                  ↘ FAILED
READY   → SYNCING → READY
                  ↘ FAILED
```

---

## API Endpoints

All responses use the unified `{ success, data, message, errors }` envelope.

---

### `POST /api/v1/repositories`

Register a GitHub repository and enqueue an asynchronous clone.
Returns immediately — poll `GET /repositories/{id}` to track progress.

**Request body:**
```json
{
  "github_url": "https://github.com/owner/repo",
  "reclone": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `github_url` | string | yes | GitHub HTTPS URL (see Accepted URL Formats) |
| `reclone` | boolean | no | `true` to force re-clone of an existing repository |

**Response: `202 Accepted`**
```json
{
  "success": true,
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "PENDING"
  },
  "message": "Repository accepted. Cloning has been enqueued.",
  "errors": []
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `409 Conflict` | URL already registered and `reclone=false` |
| `422 Unprocessable Entity` | Invalid GitHub URL format |
| `403 Forbidden` | Repository is private or requires authentication |

---

### `GET /api/v1/repositories`

List all registered repositories ordered by creation time (newest first).

**Response: `200 OK`**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "owner": "octocat",
        "name": "Hello-World",
        "full_name": "octocat/Hello-World",
        "github_url": "https://github.com/octocat/Hello-World",
        "default_branch": "main",
        "local_path": "/storage/repos/550e8400-e29b-41d4-a716-446655440000",
        "current_commit": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
        "description": "My first repository on GitHub!",
        "visibility": "public",
        "language": "Python",
        "stars": 1500,
        "forks": 200,
        "clone_status": "READY",
        "created_at": "2026-07-22T10:00:00Z",
        "updated_at": "2026-07-22T10:01:30Z",
        "last_synced_at": "2026-07-22T10:01:30Z"
      }
    ],
    "total": 1
  },
  "message": "Retrieved 1 repositories.",
  "errors": []
}
```

---

### `GET /api/v1/repositories/{id}`

Retrieve full detail for a single repository by UUID.

**Path parameter:** `id` — Repository UUID

**Response: `200 OK`** — same shape as a single item from the list above.

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No repository with the given UUID |

---

### `DELETE /api/v1/repositories/{id}`

Delete the database record **and** the local clone directory.
This operation is irreversible.

**Path parameter:** `id` — Repository UUID

**Response: `200 OK`**
```json
{
  "success": true,
  "data": null,
  "message": "Repository deleted successfully.",
  "errors": []
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | No repository with the given UUID |

---

## Accepted GitHub URL Formats

Only these two formats are accepted:

```
https://github.com/owner/repository
https://github.com/owner/repository.git
```

The `.git` suffix is stripped during validation — both forms are normalised
to the same URL before the duplicate check and database insert.

**Rejected examples:**

| URL | Reason |
|-----|--------|
| `http://github.com/owner/repo` | HTTP not HTTPS |
| `https://gitlab.com/owner/repo` | Not GitHub |
| `https://github.com/owner` | Missing repository name |
| `git@github.com:owner/repo.git` | SSH format not supported |
| `https://github.com/owner/repo/tree/main` | Extra path segments |

---

## How Cloning Works

### Clone Pipeline

```
1. POST /repositories received
   │
   ├─ URL validated against regex
   ├─ Duplicate check (github_url unique constraint)
   ├─ PENDING record written to PostgreSQL
   └─ 202 returned immediately

2. Background task dispatched (Celery → BackgroundTasks fallback)
   │
   ├─ status → CLONING
   │
   ├─ GitHub REST API call
   │   GET https://api.github.com/repos/{owner}/{name}
   │   Extracts: name, owner, description, default_branch,
   │             visibility, language, stars, forks
   │
   ├─ git clone --depth=1 https://github.com/{owner}/{name}.git
   │   Target: /storage/repos/{repository_uuid}/
   │
   ├─ HEAD commit SHA extracted via GitPython
   ├─ clone_metadata written to DB (local_path, current_commit, default_branch)
   ├─ github_metadata written to DB (description, stars, language, …)
   │
   └─ status → READY

3. On any failure
   ├─ Partial clone directory removed from disk
   └─ status → FAILED
```

### Clone Storage Layout

Repositories are always cloned into a UUID-named directory:

```
/storage/repos/
└── {repository_uuid}/
    ├── .git/
    ├── README.md
    ├── src/
    └── ...
```

The UUID is the primary key of the `repositories` record, guaranteeing
a 1:1 mapping between database records and filesystem directories.
Temporary directories are never used.

### Shallow Clone

All clones use `depth=1` (single-commit history). This minimises:
- Bandwidth (only the latest tree is downloaded)
- Disk usage (no historical blobs)
- Clone time (especially for large repositories)

The full git history is not needed for the downstream scanner or parser modules.

### Celery / BackgroundTasks Fallback

The clone task is dispatched to Celery for production use (workers can be
scaled independently and survive API restarts). If Celery is unreachable at
dispatch time, the router automatically falls back to FastAPI `BackgroundTasks`,
which runs in-process. This ensures local development works without starting
a Celery worker.

---

## GitHub Metadata Extraction

The `GitHubClient` calls `GET https://api.github.com/repos/{owner}/{name}`
and maps the response to the following fields:

| GitHub API field | DB column | Description |
|-----------------|-----------|-------------|
| `name` | `name` | Repository name |
| `owner.login` | `owner` | Owner login |
| `full_name` | `full_name` | `owner/name` |
| `description` | `description` | Repository description |
| `default_branch` | `default_branch` | Primary branch |
| `visibility` | `visibility` | `public` or `private` |
| `language` | `language` | Primary language |
| `stargazers_count` | `stars` | Star count |
| `forks_count` | `forks` | Fork count |

Requests are retried up to 3 times with exponential backoff on transient
network errors (`httpx.TransportError`). Timeout is 15 seconds per request.

---

## Error Handling

| Exception | HTTP Status | `error_code` | Trigger |
|-----------|-------------|--------------|---------|
| `RepositoryAlreadyExistsError` | 409 | `CONFLICT` | Duplicate `github_url` without `reclone=true` |
| `RepositoryNotFoundError` | 404 | `NOT_FOUND` | Unknown UUID in GET / DELETE |
| `RepositoryAccessError` | 403 | `REPOSITORY_ACCESS_DENIED` | GitHub returns 401/403/404 |
| `RepositoryEmptyError` | 422 | `REPOSITORY_EMPTY` | Repository has no commits |
| `RepositoryCloneError` | 422 | `CLONE_FAILED` | `git clone` exits non-zero |
| `ExternalServiceError` | 502 | `EXTERNAL_SERVICE_ERROR` | GitHub API 5xx or timeout |
| `ValidationError` | 422 | `VALIDATION_ERROR` | Invalid request body (Pydantic) |

All errors are returned in the standard envelope:
```json
{
  "success": false,
  "data": null,
  "message": "Repository 'https://github.com/owner/repo' is already registered.",
  "errors": []
}
```

---

## Configuration

All settings are prefixed `REPO_` and read from environment variables or `.env`.

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_CLONE_ROOT` | `/storage/repos` | Root directory for all cloned repositories |
| `REPO_CLONE_TIMEOUT` | `300` | Maximum seconds to wait for `git clone` |
| `REPO_MAX_REPO_SIZE_MB` | `2048` | Maximum repository size in MB (reserved for future enforcement) |
| `REPO_GITHUB_API_BASE_URL` | `https://api.github.com` | GitHub REST API base URL (override for GitHub Enterprise) |
| `REPO_GITHUB_TOKEN` | *(empty)* | GitHub Personal Access Token — required for private repos; raises rate limit from 60 to 5000 req/hour |

Add to `.env`:
```dotenv
REPO_CLONE_ROOT=/storage/repos
REPO_CLONE_TIMEOUT=300
REPO_MAX_REPO_SIZE_MB=2048
REPO_GITHUB_API_BASE_URL=https://api.github.com
REPO_GITHUB_TOKEN=ghp_your_token_here
```

---

## Logging

Every stage of the pipeline emits a structured JSON log record via structlog.
The `request_id` field is automatically propagated from the HTTP middleware.

| Event | Level | Stage |
|-------|-------|-------|
| `Repository validation started` | INFO | URL received |
| `Duplicate repository rejected` | INFO | Duplicate check failed |
| `Repository record created, clone queued` | INFO | DB insert succeeded |
| `Repository accepted` | INFO | 202 returned to caller |
| `Repository cloning started` | INFO | Status → CLONING |
| `GitHub metadata fetched` | INFO | API call succeeded |
| `Git clone started` | INFO | `git clone` spawned |
| `Clone completed` | INFO | `git clone` finished |
| `Repository clone metadata persisted` | INFO | DB updated with path + SHA |
| `Repository GitHub metadata updated` | INFO | DB updated with stars, language… |
| `Database updated — repository READY` | INFO | Status → READY |
| `Repository pipeline failed` | ERROR | Any exception in pipeline |
| `Repository marked as FAILED` | ERROR | Status → FAILED |
| `Repository deleted` | INFO | DELETE completed |

---

## Background Processing

### Celery Task

**Task name:** `repository.clone`

```python
from backend.app.workers.celery_app import clone_repository_task

clone_repository_task.delay(str(repository_id))
```

**Retry policy:**
- Max retries: 3
- Initial delay: 30s
- Backoff: exponential with jitter
- Max backoff: 120s

**Broker / backend:** Redis (shares the existing Redis service)

### Starting the Celery Worker

```bash
# Docker (included in docker-compose.yml as celery_worker service)
docker compose up celery_worker

# Local development
celery -A backend.app.workers.celery_app.celery_app worker --loglevel=info --concurrency=2
```

---

## Testing

```bash
# Unit tests — no infrastructure required
pytest tests/unit/test_repository_schemas.py -v    # URL validation
pytest tests/unit/test_repository_service.py -v    # Service logic (all I/O mocked)
pytest tests/unit/test_github_client.py -v         # GitHub client error handling

# Integration tests — requires PostgreSQL
pytest tests/integration/test_repository_api.py -v

# All tests with coverage
pytest tests/ --cov=backend --cov-report=term-missing
```

### Test Coverage

| File | What is tested |
|------|----------------|
| `test_repository_schemas.py` | Valid/invalid URL patterns, `.git` normalisation, `reclone` default, owner/name extraction |
| `test_repository_service.py` | New registration, duplicate rejection, `reclone=true` reset, get by ID, delete with clone removal, list all |
| `test_github_client.py` | Successful metadata mapping, 401/403/404 → `RepositoryAccessError`, 5xx → `ExternalServiceError`, timeout handling |
| `test_repository_api.py` | POST 202, POST 422, POST 409, POST reclone, GET list, GET by ID, GET 404, DELETE 200, DELETE 404 |

---

## Migration

**File:** `backend/alembic/versions/001_create_repositories_table.py`

**Run:**
```bash
docker compose exec -w /app/backend backend python -m alembic upgrade head
```

**Creates:**
- PostgreSQL enum type: `repository_status`
- Table: `repositories` with all columns, constraints, and indexes

---

## Usage Example

```python
from backend.app.services.repository_service import RepositoryService
from backend.app.schemas.repository import RepositoryCreateRequest
from backend.app.db.session import get_session_context
import uuid

# Register a new repository
async with get_session_context() as session:
    service = RepositoryService(session=session)

    request = RepositoryCreateRequest(
        github_url="https://github.com/octocat/Hello-World"
    )
    result = await service.create_repository(request)
    print(f"Created: {result.id}, status: {result.status}")
    # Created: 550e8400-..., status: PENDING

# Run the clone pipeline (normally done by the Celery worker)
async with get_session_context() as session:
    service = RepositoryService(session=session)
    await service.run_clone_pipeline(result.id)

# Fetch the completed record
async with get_session_context() as session:
    service = RepositoryService(session=session)
    repo = await service.get_repository(result.id)
    print(f"Status: {repo.clone_status}")   # READY
    print(f"Branch: {repo.default_branch}") # main
    print(f"Commit: {repo.current_commit}") # abc123...
    print(f"Stars:  {repo.stars}")          # 1500
```

---

## What Is NOT Implemented (By Design)

| Feature | Owner |
|---------|-------|
| File scanning / language detection | Scanner module (`docs/scanner-readme.md`) |
| AST parsing / symbol extraction | Intelligence module (`docs/intelligence-readme.md`) |
| Code embeddings | Future: Embeddings module |
| Vector similarity search | Future: Vector Search module |
| Neo4j graph construction | Future: Graph module |
| RAG / LLM integration | Future: RAG module |

The Repository Management module is the **foundation** of the pipeline.
It produces a cloned repository on disk and a metadata record in PostgreSQL.
All downstream modules depend on a repository being in `READY` status.
