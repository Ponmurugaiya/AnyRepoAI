# Architecture Decision Records

## ADR-001: Clean Architecture layers

**Decision:** Enforce strict layer separation — API handlers call services, services call repositories, repositories call the database/infra clients.

**Rationale:** Keeps business logic testable in isolation without spinning up HTTP or database infrastructure.

---

## ADR-002: Unified APIResponse envelope

**Decision:** All endpoints return `{ success, data, message, errors }`.

**Rationale:** Clients can always unwrap the same shape without per-endpoint error handling logic.

---

## ADR-003: pydantic-settings for configuration

**Decision:** Nest settings into domain-specific sub-models (AppSettings, DatabaseSettings, etc.) instead of a flat namespace.

**Rationale:** Reduces collision between env var prefixes and makes auto-complete ergonomic.

---

## ADR-004: Structlog with JSON output

**Decision:** Use structlog's `ProcessorFormatter` over a custom logging handler.

**Rationale:** Structlog's context variable binding (`bind_contextvars`) makes request_id propagation automatic without thread-local hacks.

---

## ADR-005: ULID for request IDs

**Decision:** Generate ULIDs rather than UUID4 for request identifiers.

**Rationale:** ULIDs are lexicographically sortable, making log correlation in time-ordered streams much easier.
