"""Dependency & Knowledge Graph Builder.

Transforms the Symbol Index into a full Code Knowledge Graph in Neo4j.

The graph models every important relationship between code entities:
imports, calls, inheritance, interface implementation, containment,
and framework-specific connections (API routes → handlers → services).

This package exposes the public surface consumed by downstream modules
(Graph Retrieval, AI Reasoning, Impact Analysis).

Modules:
    models:      Pydantic domain models for nodes and edges.
    repositories: Neo4j GraphRepository for all Cypher operations.
    builders:    Translators that convert Symbol Index data into graph
                 write operations (node builders + edge builders).
    services:    Orchestration — GraphBuildService controls the full
                 build pipeline and incremental updates.
    traversals:  BFS, DFS, shortest-path, k-hop, dependency expansion.
    validators:  Circular-reference detection and relationship validation.
    workers:     Celery background task for async graph construction.
    api:         REST endpoints for build, query, and analysis.
    schemas:     Pydantic request/response models for the API layer.
"""
