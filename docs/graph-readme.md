# Dependency & Knowledge Graph Builder

The Knowledge Graph Builder transforms the Symbol Index into a complete Code Knowledge Graph stored in Neo4j. Every important relationship between code entities is modelled as a directed graph that powers impact analysis, architecture exploration, code navigation, and graph-based retrieval.

---

## Architecture

The builder follows Clean Architecture with strict layer separation. It reads **exclusively** from the Symbol Index (PostgreSQL) and writes to Neo4j. Source files are never re-read.

```
app/graph/
├── api/
│   └── router.py          # REST endpoints (12 routes)
├── models/
│   └── nodes.py           # NodeType enum + GraphNode + GraphEdge Pydantic models
├── repositories/
│   └── graph_repository.py # All Cypher operations (merge, delete, query, analysis)
├── builders/
│   ├── node_builder.py    # Symbol Index entry → GraphNode translation
│   └── edge_builder.py    # Relational data → GraphEdge translation
├── services/
│   └── graph_build_service.py # Full pipeline orchestration
├── traversals/
│   └── algorithms.py      # BFS, DFS, shortest path, k-hop, dependency expansion
├── validators/
│   └── graph_validator.py # Node/edge filtering + cycle detection
├── workers/
│   └── graph_tasks.py     # Celery task: build_repository
└── schemas/
    └── graph.py           # Pydantic request/response models
```

**Data flow:**

```
POST /repositories/{id}/graph/build
        │
        ▼
  Celery Task / BackgroundTask
        │
        ▼
  GraphBuildService.build_graph()
        │
        ├─► RepositoryRepository     (validate repo)
        ├─► FileRepository           (load all files)
        ├─► SymbolIndexRepository    (load symbol entries in batches)
        ├─► NodeBuilder              (entries → GraphNode objects)
        ├─► EdgeBuilder              (imports/calls/classes → GraphEdge objects)
        ├─► GraphValidator           (filter bad nodes/edges, detect cycles)
        └─► GraphRepository          (MERGE nodes + relationships into Neo4j)
```

---

## Node Model

Every node in the graph carries the ``_GraphNode`` meta-label plus one primary label matching its type.

| Label | Source | Description |
|---|---|---|
| `Repository` | Repository ORM | Root node for the entire repository |
| `Directory` | File paths | Source directory structure |
| `File` | RepositoryFile | Individual source files |
| `Module` | Symbol Index (module) | Python/TypeScript modules |
| `Package` | Symbol Index (package) | Java packages, Go packages |
| `Namespace` | Symbol Index (namespace) | C++/TypeScript namespaces |
| `Class` | Symbol Index (class) | Class declarations |
| `Interface` | Symbol Index (interface) | Interface/protocol declarations |
| `Struct` | Symbol Index (struct) | Struct declarations (Go, Java records) |
| `Enum` | Symbol Index (enum) | Enumeration types |
| `Function` | Symbol Index (function) | Module-level functions |
| `Method` | Symbol Index (method) | Class methods |
| `Constructor` | Symbol Index (constructor) | Class constructors |
| `Variable` | Symbol Index (variable) | Mutable bindings |
| `Constant` | Symbol Index (constant) | Immutable bindings |
| `Property` | Symbol Index (decorator/annotation) | Decorators and annotations |
| `ApiRoute` | RouteRecord | HTTP route/endpoint |
| `ExternalLibrary` | ImportRecord | Third-party library dependency |
| `Database` | (future) | Database connection nodes |
| `EnvVariable` | (future) | Environment variable references |

### Node properties (all nodes)

| Property | Type | Description |
|---|---|---|
| `id` | string | Stable UUID (from Symbol Index entry) |
| `repository_id` | string | Owning repository UUID |
| `name` | string | Short display name |
| `qualified_name` | string | Fully-qualified name |
| `language` | string | Source programming language |
| `file_path` | string | Relative source file path |
| `updated_at` | timestamp | Last merge timestamp (Neo4j) |

Symbol nodes carry additional properties: `symbol_type`, `visibility`, `is_static`, `is_async`, `is_exported`, `is_deprecated`, `start_line`, `end_line`, `signature`, `return_type`, `documentation`, `module_name`.

---

## Edge Model

All relationships are directed. The source and direction encode the semantic meaning.

| Type | Source → Target | Description |
|---|---|---|
| `CONTAINS` | File → Symbol | File contains a symbol |
| `BELONGS_TO` | Symbol → File | Inverse of CONTAINS (navigation) |
| `DEFINES` | Parent Symbol → Child Symbol | Class defines a method |
| `IMPORTS` | File → Module | Internal module import |
| `USES_LIBRARY` | File → ExternalLibrary | Third-party library usage |
| `INHERITS` | Class → Parent Class | Class inheritance |
| `IMPLEMENTS` | Class → Interface | Interface implementation |
| `CALLS` | Function/Method → Function/Method | Function call reference |
| `EXPOSES_ROUTE` | File → ApiRoute | File exposes an HTTP route |
| `DEPENDS_ON` | Module → Module | Derived dependency between modules |
| `USES` | Symbol → Symbol | Generic usage relationship |
| `RETURNS` | Function → Type | Return type reference |
| `PARAMETER` | Function → Type | Parameter type reference |
| `REFERENCES` | Symbol → Symbol | Code reference |
| `CONNECTS_DATABASE` | Service → Database | Database connection |
| `USES_ENV` | Code → EnvVariable | Environment variable access |

### Edge properties

All edges carry `repository_id` and `updated_at`. Additional type-specific properties:
- `CALLS`: `line` (source line number), `language`
- `IMPORTS` / `USES_LIBRARY`: `module_path`
- `INHERITS`: `base_class`
- `IMPLEMENTS`: `interface`
- `EXPOSES_ROUTE`: `http_method`, `path`, `framework`

---

## Graph Construction Pipeline

The build pipeline runs in 11 sequential steps:

```
Step 1:  Create Repository node
Step 2:  Load all source files from PostgreSQL
Step 3:  Create Directory nodes (deduplicated from file paths)
Step 4:  Create File nodes + Directory→File CONTAINS edges
Step 5:  Load Symbol Index entries in paginated batches (1000/batch)
Step 6:  Build and merge Symbol nodes (File→Symbol CONTAINS + BELONGS_TO + DEFINES)
Step 7:  Build ExternalLibrary nodes + IMPORTS / USES_LIBRARY edges
Step 8:  Build INHERITS + IMPLEMENTS edges from ClassRecord data
Step 9:  Build CALLS edges from CallRecord data
Step 10: Build ApiRoute nodes + EXPOSES_ROUTE + CALLS (handler) edges
Step 11: Cycle detection (warning only; does not abort build)
```

Nodes are always flushed to Neo4j before edges so ``MERGE`` on edge endpoints always finds existing nodes.

---

## Qualified Name Stability

All graph nodes use a stable `id` property derived from the Symbol Index entry UUID. This means:
- Re-running a build always produces the same node IDs.
- Incremental updates can target exactly the changed file's nodes.
- External tools can store node IDs as stable references.

---

## Import Graph

Internal imports become `IMPORTS` edges between File nodes and internal Module/Class nodes. External imports become `USES_LIBRARY` edges to ExternalLibrary nodes.

**Examples:**

```
AuthService.py -[IMPORTS]→ jwt (ExternalLibrary)
AuthService.py -[IMPORTS]→ app.database (internal Module)
UserController.py -[IMPORTS]→ AuthService (internal Class)
```

Detection rules:
- Relative imports (`from . import ...`) → always internal
- Module path matches a Symbol Index qualified name → internal IMPORTS edge
- Otherwise → USES_LIBRARY edge to ExternalLibrary node

---

## Call Graph

`CALLS` edges are built from `CallRecord` rows. The resolver tries:
1. Exact qualified name match (`caller_name` / `callee_name`)
2. Object + method match (`callee_object.callee_name`)

```
AuthController.login -[CALLS]→ AuthService.authenticate
AuthService.authenticate -[CALLS]→ JWTService.generate
JWTService.generate -[CALLS]→ UserRepository.find_user
```

---

## Inheritance Graph

`INHERITS` edges are built from `ClassRecord.base_classes` (JSON array).

```
AdminUser -[INHERITS]→ BaseUser
BaseUser  -[INHERITS]→ AbstractUser
```

`IMPLEMENTS` edges are built from `ClassRecord.interfaces`.

```
UserService -[IMPLEMENTS]→ IUserService
```

---

## API Route Graph

HTTP routes become `ApiRoute` nodes. Two edges are created per route:

```
auth.py -[EXPOSES_ROUTE]→ POST /login
POST /login -[CALLS]→ AuthController.login
```

This captures the full request-to-handler chain without re-parsing source.

---

## REST API

### Start Graph Build

```
POST /api/v1/repositories/{id}/graph/build
```

Returns `202 ACCEPTED` immediately. Dispatches a Celery task (falls back to FastAPI BackgroundTasks).

**Response:**
```json
{
  "success": true,
  "data": {"repository_id": "...", "status": "QUEUED", "message": "..."}
}
```

---

### Check Progress

```
GET /api/v1/repositories/{id}/graph/progress
```

Returns current Neo4j node and edge counts.

---

### Get Node by ID

```
GET /api/v1/repositories/{id}/graph/node/{node_id}
```

---

### Get Node by Qualified Name

```
GET /api/v1/repositories/{id}/graph/node/by-name?qname=app.auth.AuthService.login
```

---

### Get Neighbors

```
GET /api/v1/repositories/{id}/graph/neighbors/{node_id}
```

Query parameters:

| Parameter | Type | Description |
|---|---|---|
| `direction` | string | `outgoing`, `incoming`, or `both` (default) |
| `edge_types` | list[string] | Filter by relationship type (e.g. `CALLS`) |
| `limit` | int | Max neighbors (1–1000, default 100) |

---

### Find Shortest Path

```
GET /api/v1/repositories/{id}/graph/path?source={id}&target={id}&max_depth=10
```

---

### Dependency Graph

```
GET /api/v1/repositories/{id}/graph/dependencies
```

Returns all `IMPORTS` and `DEPENDS_ON` edges as a subgraph.

---

### Call Graph

```
GET /api/v1/repositories/{id}/graph/callgraph
```

Returns all `CALLS` edges as a subgraph.

---

### Analysis Endpoints

```
GET /api/v1/repositories/{id}/graph/analysis/unused-functions
GET /api/v1/repositories/{id}/graph/analysis/orphan-classes
GET /api/v1/repositories/{id}/graph/analysis/circular-dependencies
GET /api/v1/repositories/{id}/graph/analysis/longest-chain
```

---

## Traversal Algorithms

The `GraphTraversal` class provides in-memory traversal on edge lists returned from Neo4j queries, avoiding additional round-trips.

| Algorithm | Method | Description |
|---|---|---|
| BFS | `bfs(start, edges, max_depth)` | Breadth-first, returns visited IDs |
| DFS | `dfs(start, edges, max_depth)` | Depth-first, iterative |
| Shortest Path | `shortest_path(source, target, edges)` | BFS-based unweighted |
| k-Hop | `k_hop(start, edges, k, direction)` | All nodes within k hops |
| Dependency Expansion | `expand_dependencies(start, edges)` | Transitive IMPORTS + DEPENDS_ON closure |
| Subgraph Extraction | `extract_subgraph(node_ids, edges)` | Induced subgraph on a node set |

---

## Incremental Graph Updates

When a single file changes, only its nodes and edges are regenerated:

```python
await service.build_file_subgraph(repository_id, file_id)
```

Steps:
1. Delete all nodes where `file_path == relative_path` (DETACH DELETE).
2. Reload Symbol Index entries for the file.
3. Rebuild File node + Symbol nodes.
4. Rebuild CONTAINS, BELONGS_TO, and DEFINES edges.
5. Merge into Neo4j.

Other files in the repository are never touched.

---

## Performance

| Strategy | Implementation |
|---|---|
| Batch node writes | UNWIND + MERGE in 500-node batches |
| Batch edge writes | UNWIND + MATCH + MERGE in 500-edge batches |
| Label-grouped writes | Nodes batched by label to allow literal label Cypher |
| Edge-type-grouped writes | Edges batched by type to allow literal relationship Cypher |
| Paginated index loads | Symbol Index read 1,000 entries at a time |
| Idempotent MERGE | Re-running a build always converges to the same state |

**Scale target:** 100,000+ nodes, millions of edges.

---

## Neo4j Schema

Indexes and constraints are created automatically during each build:

```cypher
CREATE CONSTRAINT node_id_unique IF NOT EXISTS
    FOR (n:_GraphNode) REQUIRE n.id IS UNIQUE;

CREATE INDEX idx_repository_id IF NOT EXISTS FOR (n:_GraphNode) ON (n.repository_id);
CREATE INDEX idx_qualified_name IF NOT EXISTS FOR (n:_GraphNode) ON (n.qualified_name);
CREATE INDEX idx_node_language  IF NOT EXISTS FOR (n:_GraphNode) ON (n.language);
CREATE INDEX idx_node_name      IF NOT EXISTS FOR (n:_GraphNode) ON (n.name);
```

---

## Running Tests

```bash
# All graph tests
pytest backend/tests/graph/ -v

# Individual test modules
pytest backend/tests/graph/test_node_builder.py -v
pytest backend/tests/graph/test_edge_builder.py -v
pytest backend/tests/graph/test_graph_validator.py -v
pytest backend/tests/graph/test_traversal.py -v
pytest backend/tests/graph/test_graph_service.py -v
pytest backend/tests/graph/test_graph_repository.py -v
pytest backend/tests/graph/test_graph_api.py -v
```

---

## Full Test Suite

```bash
pytest backend/tests/ -q
# 397 passed
```

---

## Typical Workflow

```
1. POST /repositories/{id}              → clone repository
2. POST /repositories/{id}/scan         → scan files
3. POST /repositories/{id}/parse        → AST parse
4. POST /repositories/{id}/symbols/index → build Symbol Index
5. POST /repositories/{id}/graph/build  → build Knowledge Graph
```

After step 5, the full graph is available for all query and analysis endpoints.
