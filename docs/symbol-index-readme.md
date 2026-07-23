# Symbol Intelligence Engine

The Symbol Intelligence Engine transforms parsed ASTs into a **canonical Symbol Index** — the single source of truth for all code entities in a repository. Future modules (Dependency Graph, Embedding Pipeline, AI Chat) consume this index instead of reparsing source files.

---

## Architecture

The engine follows Clean Architecture with strict layer separation:

```
app/symbol_index/
├── api/
│   └── router.py          # FastAPI REST endpoints
├── models/
│   └── index.py           # SQLAlchemy ORM (SymbolIndex + SymbolIndexEntry)
├── repositories/
│   └── index_repository.py # Data-access layer
├── services/
│   └── index_service.py   # Orchestration and business logic
├── schemas/
│   └── index.py           # Pydantic request/response models
├── workers/
│   └── index_tasks.py     # Celery background task
├── mappers/
│   └── symbol_mapper.py   # Parser domain → Index entry translation
└── validators/
    ├── qualified_name.py  # Qualified-name generation and validation
    └── duplicates.py      # Duplicate-symbol detection
```

**Data flow:**

```
POST /repositories/{id}/symbols/index
        │
        ▼
  Celery Task / BackgroundTask
        │
        ▼
  SymbolIndexService.index_repository()
        │
        ├─► RepositoryRepository  (validate repo exists + READY)
        ├─► FileRepository        (load SCANNED files)
        ├─► ParserRegistry        (parse files via language parsers)
        ├─► SymbolMapper          (FileSummary → index entry dicts)
        ├─► DuplicateDetector     (remove qualified-name collisions)
        └─► SymbolIndexRepository (bulk upsert to DB)
```

---

## Canonical Symbol Index

The `symbol_index_entries` table is the canonical store. Every meaningful code symbol across all supported languages is normalised into a single schema.

### Why a dedicated index?

The existing `symbols`, `classes`, and `functions` tables (from migration `003`) store raw parser output per-file. The Symbol Index adds:

- **Globally unique qualified names** per repository
- **Parent-child UUID links** (`parent_symbol_id`) for tree traversal
- **Stable display names** for UI rendering
- **Computed flags** (`is_exported`, `is_deprecated`)
- **Normalised signatures** cleaned of raw source noise
- **Module and namespace metadata** for qualified-name reconstruction

---

## Qualified Name Generation

Qualified names are stable identifiers that survive re-indexing. They follow language conventions.

### Python

File: `app/services/auth.py`

```
app.services.auth.AuthService.login
```

### Java

File: `com/company/auth/UserService.java`

```
com.company.auth.UserService.login
```

### Go

File: `internal/auth/handler.go`

```
internal/auth/handler.AuthHandler.Login
```

### TypeScript

File: `src/services/AuthService.ts`

```
src.services.AuthService.AuthService.login
```

### JavaScript

File: `routes/users.js`

```
routes.users.getUser
```

### HTTP Routes

Routes use an encoding that captures the HTTP method and path:

```
handler_name.GET.|users|{id}
```

Slashes in paths are replaced with `|` to avoid breaking the dot-separated naming scheme.

---

## Database Schema

### `symbol_index_jobs`

Tracks the lifecycle of one indexing run per repository.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `repository_id` | UUID FK | Unique per repository |
| `status` | enum | QUEUED / INDEXING / COMPLETED / FAILED |
| `total_files` | int | Files eligible for indexing |
| `indexed_files` | int | Files successfully indexed |
| `failed_files` | int | Files with errors |
| `total_symbols` | int | Symbols written to the index |
| `duplicate_symbols` | int | Symbols skipped (QN collision) |
| `error_message` | text | Last failure detail |
| `index_duration_seconds` | float | Wall-clock time |

### `symbol_index_entries`

One row per canonical code symbol.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `repository_id` | UUID FK → `repositories.id` | |
| `file_id` | UUID FK → `repository_files.id` | |
| `language` | varchar(64) | Source language |
| `symbol_type` | varchar(32) | class / function / method / … |
| `name` | varchar(512) | Short unqualified name |
| `qualified_name` | varchar(1024) | Fully-qualified name (**unique per repo**) |
| `display_name` | varchar(512) | Human-readable label (last 2 segments) |
| `parent_symbol_id` | UUID FK (self) | Enclosing symbol UUID |
| `module_name` | varchar(1024) | Module/package path |
| `namespace` | varchar(512) | Language namespace / framework name |
| `signature` | text | Normalised signature |
| `return_type` | varchar(512) | Return type annotation |
| `visibility` | varchar(16) | public / private / protected / internal / unknown |
| `is_static` | bool | |
| `is_async` | bool | |
| `is_exported` | bool | |
| `is_deprecated` | bool | |
| `documentation` | text | Docstring / JavaDoc / JSDoc |
| `start_line` | int | 1-indexed |
| `end_line` | int | 1-indexed |
| `start_column` | int | 0-indexed |
| `end_column` | int | 0-indexed |

**Unique constraint:** `(repository_id, qualified_name)`

**Indexes:** repository_id, file_id, language, symbol_type, name, qualified_name, parent_symbol_id, and composite variants.

---

## Symbol Types

| Type | Description | Languages |
|---|---|---|
| `class` | Class declaration | All |
| `function` | Module-level function | All |
| `method` | Class method | All |
| `constructor` | Class constructor | All |
| `interface` | Interface / protocol | TypeScript, Java, Go |
| `enum` | Enumeration | Python, TypeScript, Java |
| `struct` | Struct declaration | Go, Java (records) |
| `variable` | Mutable binding | All |
| `constant` | Immutable binding | All |
| `decorator` | Decorator / annotation | Python, TypeScript, Java |
| `annotation` | Java annotation type | Java |
| `module` | Module / namespace | Python, TypeScript |
| `package` | Package declaration | Java, Go |
| `route` | HTTP route/endpoint | Python, TypeScript, Java, Go, JavaScript |

---

## Search API

### Start Indexing

```
POST /api/v1/repositories/{id}/symbols/index
```

Enqueues asynchronous symbol indexing. Returns `202 ACCEPTED` immediately.

**Response:**
```json
{
  "success": true,
  "data": {
    "repository_id": "...",
    "status": "QUEUED",
    "message": "Symbol indexing enqueued."
  }
}
```

---

### Check Progress

```
GET /api/v1/repositories/{id}/symbols/index/progress
```

**Response:**
```json
{
  "success": true,
  "data": {
    "repository_id": "...",
    "status": "COMPLETED",
    "total_files": 150,
    "indexed_files": 148,
    "failed_files": 2,
    "total_symbols": 4821,
    "duplicate_symbols": 7,
    "index_duration_seconds": 12.4
  }
}
```

Status values: `NOT_STARTED`, `QUEUED`, `INDEXING`, `COMPLETED`, `FAILED`.

---

### List Symbols

```
GET /api/v1/repositories/{id}/symbols/index/entries
```

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `language` | string | Filter by language |
| `symbol_type` | string | Filter by type |
| `filename` | string | Filter by source filename (substring) |
| `limit` | int | Page size (1–2000, default 100) |
| `offset` | int | Row offset (default 0) |

---

### Get Symbol by ID

```
GET /api/v1/repositories/{id}/symbols/index/entries/{symbol_id}
```

Returns complete symbol information for a single entry.

---

### Search Symbols

```
GET /api/v1/repositories/{id}/symbols/index/search
```

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `q` | string | **Required.** Search query (1–512 chars) |
| `mode` | string | `prefix` (default), `exact`, or `qualified` |
| `language` | string | Filter by language |
| `symbol_type` | string | Filter by type |
| `limit` | int | Max results (1–500, default 50) |

**Search modes:**

- `prefix` — `name` starts with `q` (case-insensitive, fastest)
- `exact` — `name` exactly equals `q` (case-insensitive)
- `qualified` — `qualified_name` contains `q` (case-insensitive substring)

**Example:**

```
GET /api/v1/repositories/{id}/symbols/index/search?q=login&mode=prefix&language=Python
```

---

## Incremental Indexing

The Symbol Index is designed for efficient incremental updates. When a file changes, only its entries need to be regenerated.

### Incremental update flow

```
1. File changes on disk
2. Parser re-parses the file → new FileSummary
3. SymbolIndexService.index_file(repository_id, file_id) is called
4. DELETE FROM symbol_index_entries WHERE file_id = ?
5. Map + deduplicate new symbols
6. Bulk upsert new entries
```

This guarantees:
- No stale entries from the old file version remain
- Other files in the same repository are untouched
- The entire operation completes in milliseconds for typical file sizes

### Triggering incremental re-index

```python
from backend.app.symbol_index.services.index_service import SymbolIndexService

async with get_session_context() as session:
    service = SymbolIndexService(session=session)
    symbol_count = await service.index_file(repository_id, file_id)
```

---

## Performance

The engine is designed for repositories with 100,000+ symbols.

| Strategy | Implementation |
|---|---|
| Batch inserts | Entries upserted in 500-row batches via `pg_insert().on_conflict_do_update()` |
| File batching | Files processed in batches of 20; DB committed after each batch |
| Streaming | Files loaded lazily; no full-repository load into memory |
| No redundant parsing | Parser produces `FileSummary` once; mapper is pure-function translation |
| Duplicate filtering | In-memory set-based deduplication before any DB call |
| Connection pooling | AsyncPG connection pool shared across all requests |

### Indexing throughput (approximate)

| Repository size | Symbols | Estimated duration |
|---|---|---|
| Small (< 50 files) | < 5,000 | < 5 seconds |
| Medium (500 files) | ~50,000 | ~30 seconds |
| Large (5,000 files) | ~500,000 | ~5 minutes |

These figures depend on file size, CPU speed, and PostgreSQL write throughput.

---

## Framework Detection

The mapper preserves framework context in the `namespace` field for route symbols.

| Framework | Language | Namespace value |
|---|---|---|
| FastAPI | Python | `fastapi` |
| Flask | Python | `flask` |
| Django | Python | `django` |
| Express | JavaScript/TypeScript | `express` |
| NestJS | TypeScript | `nestjs` |
| Spring Boot | Java | `spring` |
| Gin | Go | `gin` |
| Echo | Go | `echo` |
| net/http | Go | `net/http` |

---

## Parent-Child Hierarchy

Every symbol that lives inside another symbol carries a `parent_symbol_id` UUID pointing to its enclosing symbol record. This enables efficient tree queries.

```
Repository
└── Module (app.services.auth)
    └── Class (AuthService)
        ├── Constructor (__init__)
        ├── Method (login)
        └── Method (logout)
```

The hierarchy is built during mapping: classes are processed first, so their IDs are available when methods are mapped.

To retrieve all methods of a class:

```python
children = await index_repo.get_children(parent_symbol_id=auth_service_entry.id)
```

---

## Running Tests

```bash
# All symbol index tests
pytest backend/tests/symbol_index/ -v

# Specific test class
pytest backend/tests/symbol_index/test_qualified_names.py -v
pytest backend/tests/symbol_index/test_symbol_mapper.py -v
pytest backend/tests/symbol_index/test_index_service.py -v
pytest backend/tests/symbol_index/test_api_endpoints.py -v
```

---

## Running the Migration

```bash
cd backend
alembic upgrade 004_create_symbol_index_tables
```

To run all migrations from scratch:

```bash
alembic upgrade head
```
