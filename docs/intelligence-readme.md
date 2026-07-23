# Code Intelligence Engine

## Overview

The Code Intelligence Engine is a **production-grade Multi-Language AST Parser**
that transforms a scanned repository into a complete, queryable **symbol database**.
It understands software structure — classes, functions, imports, call graphs, and
HTTP routes — rather than treating code as plain text.

**Explicit out-of-scope:** This module does NOT perform embeddings, vector search,
retrieval, RAG, LLM inference, or Neo4j graph persistence. Those belong to downstream
modules that consume the symbol database produced here.

---

## Architecture

```
POST /repositories/{id}/parse
         │
         ▼
 RepositoryParserService
         │  reads repository_files (SCANNED, non-binary, supported language)
         │  deletes previous intelligence records
         │  marks files as QUEUED
         │
         ▼
  ProcessPoolExecutor  ──►  _parse_file_worker (subprocess)
         │                         │
         │                         ▼
         │                  ParserRegistry.get_parser_for_language()
         │                         │
         │                         ▼
         │                  CodeParser.parse_file()
         │                         │
         │                   FileSummary (JSON-serialisable)
         │
         ▼
  SymbolRepository.bulk_insert_summary()
         │
         ▼
  PostgreSQL: symbols, imports, calls, classes, functions, routes, file_parse_jobs
```

### Clean Architecture Layers

| Layer | Location | Responsibility |
|-------|----------|---------------|
| API | `app/api/v1/parser.py` | HTTP endpoints, response shaping |
| Service | `app/services/parser_service.py` | Orchestration, parallel dispatch |
| Repository | `app/repositories/symbol_repository.py` | DB reads/writes only |
| Models | `app/models/symbol.py` | SQLAlchemy ORM |
| Parsers | `app/parsers/` | AST extraction, zero DB coupling |
| Domain Models | `app/parsers/models/symbols.py` | Pydantic data contracts |

---

## Parser Registry

The `ParserRegistry` maps language names and file extensions to concrete
`CodeParser` implementations. It is built once per process via `@lru_cache`
and populated in `registry/registry.py`.

```python
from backend.app.parsers.registry import get_parser_registry

registry = get_parser_registry()

# Look up by language name (case-insensitive)
parser = registry.get_parser_for_language("Python")

# Look up by extension
parser = registry.get_parser_for_extension("ts")

# Inspect what's registered
print(registry.supported_languages())
# ['Go', 'Java', 'JavaScript', 'Python', 'TypeScript']
```

**Adding a new language** requires zero changes to existing code:

1. Create `app/parsers/tree_sitter/<language>/parser.py`
2. Subclass `CodeParser`, set `language` and `extensions` class attributes
3. Implement all seven abstract methods
4. Import and register in `registry/registry.py`'s `_build_registry()`

---

## Tree-sitter

All parsers use [tree-sitter](https://tree-sitter.github.io/tree-sitter/) via
the `tree-sitter-languages` package, which ships pre-compiled grammars for
all supported languages. No system-level grammar installation is required.

```python
from tree_sitter_languages import get_language, get_parser

_LANG = get_language("python")   # grammar object
_PARSER = get_parser("python")   # parser object (thread-safe, reusable)
```

The parser objects are **module-level singletons** in each language module,
loaded once per process and shared across all parse calls. This avoids the
overhead of re-initialising the grammar for every file.

---

## Parser Interface

Every language parser inherits from `CodeParser` and must implement:

```python
class CodeParser(abc.ABC):
    language: str           # e.g. "Python"
    extensions: list[str]   # e.g. ["py", "pyw", "pyi"]

    def parse_file(self, *, file_id, repository_id,
                   relative_path, absolute_path) -> FileSummary: ...
    # (final — do not override)

    def extract_symbols(self, source, file_id, repository_id) -> list[Symbol]: ...
    def extract_imports(self, source, file_id, repository_id) -> list[ImportStatement]: ...
    def extract_calls(self, source, file_id, repository_id) -> list[CallReference]: ...
    def extract_classes(self, source, file_id, repository_id) -> list[ClassDefinition]: ...
    def extract_functions(self, source, file_id, repository_id) -> list[FunctionDefinition]: ...
    def extract_comments(self, source, file_id, repository_id) -> list[CommentBlock]: ...
    def extract_routes(self, source, file_id, repository_id) -> list[RouteDefinition]: ...
```

`parse_file()` is `@final` — it orchestrates all seven extraction methods,
isolates failures per step (so one bad step does not abort others),
and returns a `FileSummary`.

---

## Supported Languages

| Language | Parser | Extensions | Frameworks Detected |
|----------|--------|-----------|---------------------|
| Python | `PythonParser` | `.py`, `.pyw`, `.pyi` | FastAPI, Flask, Django |
| JavaScript | `JavaScriptParser` | `.js`, `.jsx`, `.mjs`, `.cjs` | Express.js |
| TypeScript | `TypeScriptParser` | `.ts`, `.tsx`, `.d.ts` | NestJS, Express |
| Java | `JavaParser` | `.java` | Spring Boot |
| Go | `GoParser` | `.go` | Gin, Echo, net/http |

---

## Symbol Types

`SymbolType` enum values persisted to the `symbols` table:

| Value | Description |
|-------|-------------|
| `class` | Class declaration |
| `function` | Module-level function |
| `method` | Function inside a class |
| `constructor` | `__init__`, `constructor`, Java constructors |
| `variable` | Mutable binding |
| `constant` | Immutable constant (ALL_CAPS, `const`, `static final`) |
| `enum` | Enumeration type |
| `interface` | Interface or protocol |
| `struct` | Go struct type |
| `module` | Module/namespace |
| `package` | Package declaration |
| `route` | HTTP route symbol |
| `decorator` | Python decorator |
| `annotation` | Java/TypeScript annotation |

---

## Database Schema

### `file_parse_jobs`
Tracks per-file parse lifecycle. One record per `repository_files` entry.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | PK |
| `file_id` | UUID | FK → `repository_files.id` (unique) |
| `repository_id` | UUID | FK → `repositories.id` |
| `parse_status` | `parse_status` | QUEUED / PARSING / COMPLETED / FAILED |
| `language` | VARCHAR | Parser language |
| `error_message` | TEXT | Last failure reason |
| `parse_duration_ms` | FLOAT | Wall-clock parse time |
| `symbol_count` | INTEGER | Total symbols extracted |
| `import_count` | INTEGER | Total imports |
| `call_count` | INTEGER | Total calls |
| `function_count` | INTEGER | Total functions |
| `class_count` | INTEGER | Total classes |
| `route_count` | INTEGER | Total routes |

### `symbols`
All named code symbols.

| Column | Type | Description |
|--------|------|-------------|
| `symbol_name` | VARCHAR(512) | Short unqualified name |
| `qualified_name` | VARCHAR(1024) | Full dotted name |
| `symbol_type` | `symbol_type` | See Symbol Types above |
| `visibility` | `visibility` | public / private / protected / internal / unknown |
| `start_line` | INTEGER | 1-indexed start line |
| `end_line` | INTEGER | 1-indexed end line |
| `language` | VARCHAR(64) | Source language |
| `parent_symbol` | VARCHAR(1024) | Enclosing symbol qualified name |
| `documentation` | TEXT | Docstring / JavaDoc / JSDoc |
| `signature` | TEXT | Human-readable signature |

### `imports`
Import / require / use statements.

### `calls`
Caller → callee references.

### `routes`
HTTP route definitions with method, path, handler, framework.

### `classes`
Class definitions with inheritance, interfaces, decorators.

### `functions`
Function/method definitions with full signature metadata.

---

## API Endpoints

All responses use the `{ success, data, message, errors }` envelope.

### `POST /api/v1/repositories/{id}/parse`
Enqueue asynchronous parsing. Returns immediately with `status=QUEUED`.

```json
{
  "success": true,
  "data": {
    "repository_id": "…",
    "status": "QUEUED",
    "message": "Parse enqueued. Poll /parse/progress to track completion."
  }
}
```

### `GET /api/v1/repositories/{id}/parse/progress`
Poll parse progress.

```json
{
  "data": {
    "status": "COMPLETED",
    "total_files": 142,
    "queued": 0,
    "parsing": 0,
    "completed": 138,
    "failed": 4
  }
}
```

### `GET /api/v1/repositories/{id}/symbols`
Query parameters: `symbol_type`, `language`, `limit` (max 2000), `offset`.

### `GET /api/v1/repositories/{id}/classes`
Query parameters: `language`, `limit`, `offset`.

### `GET /api/v1/repositories/{id}/functions`
Query parameters: `language`, `is_method`, `limit`, `offset`.

### `GET /api/v1/repositories/{id}/routes`
Query parameters: `http_method`, `framework`, `limit`, `offset`.

---

## Background Processing

Parse jobs run asynchronously via Celery workers. The state machine is:

```
QUEUED → PARSING → COMPLETED
                ↘ FAILED
```

**Celery task:** `parser.parse_repository`

```python
from backend.app.workers.parser_tasks import parse_repository_task

parse_repository_task.delay(str(repository_id))
```

**Retry policy:** max 3 retries, 30s initial delay, exponential backoff with
jitter, max 120s — identical to the scanner task policy.

**Fallback:** If Celery is unavailable, the POST endpoint falls back to
FastAPI `BackgroundTasks` so local development works without a Celery worker.

---

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PARSER_PARSE_BATCH_SIZE` | `20` | Files per process-pool batch |
| `PARSER_PARSE_MAX_WORKERS` | `4` | Max parallel worker processes |
| `PARSER_PARSE_TIMEOUT_SECONDS` | `60` | Per-file parse timeout |
| `PARSER_MAX_FILE_SIZE_BYTES` | `5242880` (5 MB) | File size cap |

---

## Performance

- **Incremental:** Files processed in configurable batches (default 20).
  Memory usage is bounded regardless of repository size.
- **Parallel:** CPU-bound parsing runs in a `ProcessPoolExecutor`, leaving
  the async event loop free for I/O.
- **Fault isolation:** A parse failure on one file is caught, recorded as
  `FAILED`, and does not abort remaining files.
- **Idempotent:** Re-parsing wipes previous results atomically before
  inserting new ones. Safe to re-run at any time.
- **Serialisable worker protocol:** Workers communicate via JSON-serialised
  `FileSummary` models, enabling subprocess isolation without shared memory.

---

## Adding a New Language

1. **Create the parser module:**
   ```
   backend/app/parsers/tree_sitter/<language>/
       __init__.py
       parser.py        ← implement CodeParser subclass
   ```

2. **Implement all abstract methods** in `parser.py`.
   The parser must set:
   ```python
   language = "YourLanguage"   # must match ProgrammingLanguage enum value
   extensions = ["ext1", "ext2"]
   ```

3. **Register in `registry/registry.py`:**
   ```python
   from backend.app.parsers.tree_sitter.yourlang.parser import YourParser
   # inside _build_registry():
   registry.register(YourParser())
   ```

4. **Add language to `ProgrammingLanguage` enum** in `app/models/file.py`
   (already done for the 5 supported languages).

5. **Add the extension** to `EXTENSION_LANGUAGE_MAP` in `scanner_config.py`.

6. **Write tests** in `backend/tests/parsers/test_<language>_parser.py`.

---

## Testing

```bash
# Run all parser tests
pytest backend/tests/parsers/ -v

# Run a specific language
pytest backend/tests/parsers/test_python_parser.py -v

# Run with coverage
pytest backend/tests/parsers/ --cov=backend/app/parsers --cov-report=term-missing
```

### Test Structure

| Test File | Coverage |
|-----------|---------|
| `test_python_parser.py` | Symbols, imports, classes, functions, routes, comments, parse_file |
| `test_typescript_parser.py` | Interfaces, enums, NestJS routes, access modifiers, JSDoc |
| `test_java_parser.py` | Classes, interfaces, enums, Spring Boot routes, JavaDoc |
| `test_go_parser.py` | Structs, interfaces, Gin routes, visibility, go doc |
| `test_javascript_parser.py` | Classes, require/import, Express routes, JSDoc |
| `test_registry.py` | Registration, language/extension lookup, singleton |

---

## Migration

**File:** `backend/alembic/versions/003_create_intelligence_tables.py`

```bash
alembic upgrade head
```

Creates: `file_parse_jobs`, `symbols`, `imports`, `calls`, `routes`,
`classes`, `functions`, and three PostgreSQL enum types:
`parse_status`, `symbol_type`, `visibility`.

---

## Usage Example

```python
from backend.app.services.parser_service import RepositoryParserService
from backend.app.db.session import get_session_context
import uuid

repository_id = uuid.UUID("01234567-89ab-cdef-0123-456789abcdef")

async with get_session_context() as session:
    service = RepositoryParserService(session=session)

    # Parse all supported source files
    stats = await service.parse_repository(repository_id)
    print(f"Parsed {stats.completed_files}/{stats.total_files} files")
    print(f"Extracted {stats.total_symbols} symbols, {stats.total_routes} routes")

    # Check progress
    progress = await service.get_parse_progress(repository_id)
    print(f"Status: {progress.status}")
```

---

## What Is NOT Implemented (By Design)

| Feature | Owner |
|---------|-------|
| Code embeddings | Future: Embeddings module |
| Vector similarity search | Future: Vector Search module |
| RAG / LLM integration | Future: RAG module |
| Neo4j graph persistence | Future: Graph module |
| Cross-file call resolution | Future: Graph module |
| Type inference | Future: Deep Analysis module |

The Intelligence Engine is the **structural foundation** that all downstream
modules build upon. It provides precise symbol locations, signatures, and
relationships — without doing anything beyond AST analysis.
