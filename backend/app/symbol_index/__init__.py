"""Symbol Intelligence Engine.

Transforms parsed ASTs into a canonical Symbol Index — the single source
of truth for all code entities in a repository.

This package exposes the public API surface consumed by downstream modules
(Dependency Graph, Embedding Pipeline, AI Chat).

Modules:
    api:          REST API endpoints for indexing, querying, and searching symbols.
    models:       SQLAlchemy ORM model for the canonical symbol index table.
    repositories: Data-access layer for the symbol index.
    services:     Indexing orchestration, qualified-name generation, and search.
    schemas:      Pydantic request/response models for the API layer.
    workers:      Celery background task for asynchronous indexing.
    mappers:      Translation layer between parser domain models and index entries.
    validators:   Duplicate detection and qualified-name validation.
"""
