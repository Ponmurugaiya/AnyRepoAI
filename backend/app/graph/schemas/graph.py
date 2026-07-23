"""Pydantic schemas for the Knowledge Graph API.

All request/response models for the graph endpoints live here, decoupled
from the Neo4j driver and ORM layers so the API surface evolves independently.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


# ── Build lifecycle ────────────────────────────────────────────────────────────


class GraphBuildResponse(BaseModel):
    """Returned immediately when a graph build job is enqueued.

    Attributes:
        repository_id: Repository being built.
        status: Always ``"QUEUED"`` on initial enqueue.
        message: Human-readable confirmation.
    """

    repository_id: uuid.UUID = Field(description="Repository being built")
    status: str = Field(description="Initial build status")
    message: str = Field(description="Human-readable confirmation")


class GraphBuildProgress(BaseModel):
    """Current graph build state for a repository.

    Attributes:
        repository_id: Repository UUID.
        total_nodes: Nodes currently in the graph.
        total_edges: Edges currently in the graph.
        status: One of NOT_STARTED, QUEUED, BUILDING, COMPLETED, FAILED.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    status: str = Field(default="COMPLETED", description="Build status")
    total_nodes: int = Field(default=0, description="Node count in Neo4j")
    total_edges: int = Field(default=0, description="Edge count in Neo4j")
    error_message: str | None = Field(default=None, description="Error if failed")


class GraphStatistics(BaseModel):
    """Aggregate statistics from a completed graph build.

    Attributes:
        repository_id: Repository UUID.
        total_nodes: Total nodes written.
        total_edges: Total relationships written.
        circular_dependency_count: Number of import/dependency cycles detected.
        build_duration_seconds: Wall-clock build time.
        error_message: Error detail when build partially failed.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    total_nodes: int = Field(default=0, description="Total nodes written")
    total_edges: int = Field(default=0, description="Total edges written")
    circular_dependency_count: int = Field(
        default=0, description="Number of circular dependency cycles"
    )
    build_duration_seconds: float = Field(
        default=0.0, description="Wall-clock build duration (seconds)"
    )
    error_message: str | None = Field(
        default=None, description="Error detail when build partially failed"
    )


# ── Node / edge responses ──────────────────────────────────────────────────────


class GraphNodeResponse(BaseModel):
    """A single graph node returned by the API.

    Attributes:
        node_id: Stable node UUID string.
        node_type: Primary Neo4j label.
        name: Short display name.
        qualified_name: Fully-qualified name.
        language: Source language.
        file_path: Relative source file path.
        properties: Additional node-specific properties.
        labels: All Neo4j labels on this node.
    """

    node_id: str = Field(description="Stable node identifier")
    node_type: str = Field(description="Primary node label")
    name: str = Field(default="", description="Short display name")
    qualified_name: str = Field(default="", description="Fully-qualified name")
    language: str = Field(default="", description="Source language")
    file_path: str = Field(default="", description="Relative source file path")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Additional properties"
    )
    labels: list[str] = Field(default_factory=list, description="All Neo4j labels")

    @classmethod
    def from_neo4j(cls, record: dict[str, Any]) -> "GraphNodeResponse":
        """Construct from a raw Neo4j record dict.

        Args:
            record: dict returned by :class:`GraphRepository` query methods.

        Returns:
            :class:`GraphNodeResponse` instance.
        """
        labels = record.pop("_labels", [])
        # Primary label is the one that is NOT ``_GraphNode``
        primary = next(
            (lb for lb in labels if lb != "_GraphNode"),
            labels[0] if labels else "Unknown",
        )
        return cls(
            node_id=record.get("id", ""),
            node_type=primary,
            name=record.get("name", ""),
            qualified_name=record.get("qualified_name", ""),
            language=record.get("language", ""),
            file_path=record.get("file_path", ""),
            properties={
                k: v for k, v in record.items()
                if k not in (
                    "id", "name", "qualified_name", "language",
                    "file_path", "repository_id", "updated_at",
                )
            },
            labels=labels,
        )


class GraphEdgeResponse(BaseModel):
    """A single relationship returned by the API.

    Attributes:
        source_id: Source node ID.
        target_id: Target node ID.
        edge_type: Relationship type string.
        properties: Additional relationship properties.
    """

    source_id: str = Field(description="Source node ID")
    target_id: str = Field(description="Target node ID")
    edge_type: str = Field(description="Relationship type")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Relationship properties"
    )


class GraphNeighborResponse(BaseModel):
    """A neighbor node with its connecting relationship.

    Attributes:
        node: The neighboring node.
        relationship: The connecting relationship.
    """

    node: GraphNodeResponse = Field(description="Neighboring node")
    relationship: dict[str, Any] = Field(description="Connecting relationship")


# ── Traversal responses ────────────────────────────────────────────────────────


class GraphPathResponse(BaseModel):
    """A path between two nodes.

    Attributes:
        source_id: Start node ID.
        target_id: End node ID.
        path: Ordered list of node property dicts on the path.
        length: Number of hops.
        found: Whether a path was found.
    """

    source_id: str = Field(description="Start node ID")
    target_id: str = Field(description="End node ID")
    path: list[dict[str, Any]] = Field(default_factory=list, description="Path nodes")
    length: int = Field(default=0, description="Number of hops")
    found: bool = Field(default=False, description="Whether a path exists")


class GraphSubgraphResponse(BaseModel):
    """A subgraph with nodes and edges.

    Attributes:
        nodes: All nodes in the subgraph.
        edges: All edges in the subgraph.
        node_count: Total node count.
        edge_count: Total edge count.
    """

    nodes: list[dict[str, Any]] = Field(
        default_factory=list, description="Subgraph nodes"
    )
    edges: list[dict[str, Any]] = Field(
        default_factory=list, description="Subgraph edges"
    )
    node_count: int = Field(default=0, description="Number of nodes")
    edge_count: int = Field(default=0, description="Number of edges")


# ── Analysis responses ─────────────────────────────────────────────────────────


class AnalysisResult(BaseModel):
    """Generic analysis query result.

    Attributes:
        analysis_type: Name of the analysis performed.
        repository_id: Repository UUID.
        items: Result items (nodes, paths, or cycle lists).
        total: Total count of items.
    """

    analysis_type: str = Field(description="Analysis type identifier")
    repository_id: uuid.UUID = Field(description="Repository UUID")
    items: list[Any] = Field(default_factory=list, description="Analysis result items")
    total: int = Field(default=0, description="Total result count")
