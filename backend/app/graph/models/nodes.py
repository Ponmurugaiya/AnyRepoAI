"""Domain models for the Code Knowledge Graph.

These Pydantic models represent graph nodes and edges as pure data
containers, fully decoupled from Neo4j driver internals.  The
:class:`GraphRepository` translates them into Cypher write operations.

Node labels and edge types use the exact strings that will appear as
Neo4j node labels and relationship types so there is a 1-to-1 mapping
with no additional translation layer.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, Field


# ── Node labels ────────────────────────────────────────────────────────────────


class NodeType(str, enum.Enum):
    """Labels for all graph node types.

    Every label maps to a distinct Neo4j node label. A node may carry
    multiple labels (e.g., both ``Method`` and ``Function``) but here we
    use a single primary label per node for simplicity and query performance.
    """

    REPOSITORY = "Repository"
    BRANCH = "Branch"
    COMMIT = "Commit"
    DIRECTORY = "Directory"
    FILE = "File"
    MODULE = "Module"
    PACKAGE = "Package"
    NAMESPACE = "Namespace"
    CLASS = "Class"
    INTERFACE = "Interface"
    STRUCT = "Struct"
    ENUM = "Enum"
    FUNCTION = "Function"
    METHOD = "Method"
    CONSTRUCTOR = "Constructor"
    VARIABLE = "Variable"
    CONSTANT = "Constant"
    PROPERTY = "Property"
    API_ROUTE = "ApiRoute"
    EXTERNAL_LIBRARY = "ExternalLibrary"
    DATABASE = "Database"
    ENV_VARIABLE = "EnvVariable"


# ── Edge / relationship types ──────────────────────────────────────────────────


class EdgeType(str, enum.Enum):
    """Types for all directed graph relationships.

    Each value is the exact Neo4j relationship type string that will be
    used in Cypher ``MERGE`` and ``MATCH`` statements.
    """

    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    DEFINES = "DEFINES"
    DECLARES = "DECLARES"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    OVERRIDES = "OVERRIDES"
    USES = "USES"
    RETURNS = "RETURNS"
    PARAMETER = "PARAMETER"
    CONTAINS = "CONTAINS"
    REFERENCES = "REFERENCES"
    DEPENDS_ON = "DEPENDS_ON"
    EXPOSES_ROUTE = "EXPOSES_ROUTE"
    CONNECTS_DATABASE = "CONNECTS_DATABASE"
    USES_ENV = "USES_ENV"
    USES_LIBRARY = "USES_LIBRARY"
    BELONGS_TO = "BELONGS_TO"


# ── Node model ─────────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    """A single node in the Code Knowledge Graph.

    The ``node_id`` is the stable identifier used to merge nodes in Neo4j.
    It is derived from the Symbol Index entry UUID so nodes can be
    deterministically refreshed on incremental updates.

    Attributes:
        node_id: Stable UUID string used as the ``id`` property in Neo4j.
        node_type: Primary Neo4j label for this node.
        repository_id: UUID of the owning repository (denormalised for
            efficient per-repository subgraph queries).
        name: Short display name (e.g. ``"login"``).
        qualified_name: Fully-qualified name (e.g. ``"app.auth.AuthService.login"``).
        language: Source programming language, or empty string for
            non-code nodes (directories, external libraries).
        file_path: Relative source file path, or empty string.
        properties: Additional node-specific properties stored as a flat
            dict of JSON-serialisable primitives.
    """

    node_id: str = Field(description="Stable node identifier (UUID string)")
    node_type: NodeType = Field(description="Primary Neo4j label")
    repository_id: str = Field(description="Owning repository UUID string")
    name: str = Field(description="Short display name")
    qualified_name: str = Field(description="Fully-qualified name")
    language: str = Field(default="", description="Source language")
    file_path: str = Field(default="", description="Relative source file path")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional node-specific properties",
    )


# ── Edge model ─────────────────────────────────────────────────────────────────


class GraphEdge(BaseModel):
    """A directed relationship between two nodes in the Knowledge Graph.

    Attributes:
        source_id: ``node_id`` of the source (origin) node.
        target_id: ``node_id`` of the target (destination) node.
        edge_type: Neo4j relationship type.
        repository_id: Owning repository UUID string (denormalised).
        properties: Additional relationship properties, e.g.
            ``{"line": 42, "language": "Python"}``.
    """

    source_id: str = Field(description="Source node ID")
    target_id: str = Field(description="Target node ID")
    edge_type: EdgeType = Field(description="Relationship type")
    repository_id: str = Field(description="Owning repository UUID string")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Relationship properties",
    )
