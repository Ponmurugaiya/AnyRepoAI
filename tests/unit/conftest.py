"""Local conftest for unit tests.

This file intentionally overrides the root conftest so that scanner
unit tests can run without any infrastructure dependencies (PostgreSQL,
Neo4j, Redis, Qdrant).  All I/O is mocked at the test level.
"""
