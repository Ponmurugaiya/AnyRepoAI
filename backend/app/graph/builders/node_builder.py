"""Node builder: translates Symbol Index entries into GraphNode objects.

The :class:`NodeBuilder` is the translation layer between the flat
relational Symbol Index and the graph node model.  It understands the
``symbol_type`` vocabulary from the Symbol Index and maps each value to
the correct :class:`~backend.app.graph.models.nodes.NodeType` label.

Design:
    - Stateless — safe for concurrent use.
    - Never queries the database.
    - Returns plain :class:`GraphNode` instances; the caller handles persistence.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Any

from backend.app.core.logging import get_logger
from backend.app.graph.models.nodes import GraphNode, NodeType
from backend.app.symbol_index.models.index import SymbolIndexEntry

logger = get_logger(__name__)

# Mapping from Symbol Index symbol_type strings to graph NodeType labels.
_SYMBOL_TYPE_TO_NODE_TYPE: dict[str, NodeType] = {
    "class":       NodeType.CLASS,
    "function":    NodeType.FUNCTION,
    "method":      NodeType.METHOD,
    "constructor": NodeType.CONSTRUCTOR,
    "variable":    NodeType.VARIABLE,
    "constant":    NodeType.CONSTANT,
    "enum":        NodeType.ENUM,
    "interface":   NodeType.INTERFACE,
    "struct":      NodeType.STRUCT,
    "module":      NodeType.MODULE,
    "package":     NodeType.PACKAGE,
    "route":       NodeType.API_ROUTE,
    "decorator":   NodeType.PROPERTY,
    "annotation":  NodeType.PROPERTY,
}


class NodeBuilder:
    """Converts :class:`SymbolIndexEntry` ORM rows into :class:`GraphNode` objects.

    Example::

        builder = NodeBuilder()
        repo_node = builder.build_repository_node(repo_id, "owner/name")
        file_node = builder.build_file_node(repo_id, file_id, "src/auth.py", "Python")
        symbol_node = builder.build_symbol_node(entry)
    """

    # ── Repository / structural nodes ──────────────────────────────────────────

    @staticmethod
    def build_repository_node(
        repository_id: str,
        full_name: str,
        *,
        language: str = "",
        description: str = "",
    ) -> GraphNode:
        """Build a Repository node.

        Args:
            repository_id: UUID string of the repository.
            full_name: Canonical ``owner/name`` string.
            language: Primary language (from GitHub metadata).
            description: Repository description.

        Returns:
            :class:`GraphNode` with ``node_type=NodeType.REPOSITORY``.
        """
        return GraphNode(
            node_id=f"repo:{repository_id}",
            node_type=NodeType.REPOSITORY,
            repository_id=repository_id,
            name=full_name.split("/")[-1] if "/" in full_name else full_name,
            qualified_name=full_name,
            language=language,
            file_path="",
            properties={
                "full_name": full_name,
                "description": description,
            },
        )

    @staticmethod
    def build_directory_node(
        repository_id: str,
        directory_path: str,
    ) -> GraphNode:
        """Build a Directory node for a source directory.

        Args:
            repository_id: Repository UUID string.
            directory_path: POSIX path relative to the repository root.

        Returns:
            :class:`GraphNode` with ``node_type=NodeType.DIRECTORY``.
        """
        name = PurePosixPath(directory_path).name or directory_path
        return GraphNode(
            node_id=f"dir:{repository_id}:{directory_path}",
            node_type=NodeType.DIRECTORY,
            repository_id=repository_id,
            name=name,
            qualified_name=directory_path,
            file_path=directory_path,
            properties={"path": directory_path},
        )

    @staticmethod
    def build_file_node(
        repository_id: str,
        file_id: str,
        relative_path: str,
        language: str,
    ) -> GraphNode:
        """Build a File node for a source file.

        Args:
            repository_id: Repository UUID string.
            file_id: UUID string of the ``repository_files`` record.
            relative_path: POSIX path relative to the repository root.
            language: Detected programming language.

        Returns:
            :class:`GraphNode` with ``node_type=NodeType.FILE``.
        """
        name = PurePosixPath(relative_path).name
        return GraphNode(
            node_id=f"file:{repository_id}:{relative_path}",
            node_type=NodeType.FILE,
            repository_id=repository_id,
            name=name,
            qualified_name=relative_path,
            language=language,
            file_path=relative_path,
            properties={
                "file_id": file_id,
                "extension": PurePosixPath(relative_path).suffix.lstrip("."),
            },
        )

    @staticmethod
    def build_external_library_node(
        repository_id: str,
        library_name: str,
    ) -> GraphNode:
        """Build an ExternalLibrary node.

        Args:
            repository_id: Repository UUID string.
            library_name: Normalised library / package name.

        Returns:
            :class:`GraphNode` with ``node_type=NodeType.EXTERNAL_LIBRARY``.
        """
        # Normalise: strip version specifiers and paths
        clean_name = _normalise_library_name(library_name)
        return GraphNode(
            node_id=f"lib:{repository_id}:{clean_name}",
            node_type=NodeType.EXTERNAL_LIBRARY,
            repository_id=repository_id,
            name=clean_name,
            qualified_name=clean_name,
            file_path="",
            properties={"original_import": library_name},
        )

    # ── Symbol nodes ───────────────────────────────────────────────────────────

    @staticmethod
    def build_symbol_node(entry: SymbolIndexEntry) -> GraphNode:
        """Build a graph node from a :class:`SymbolIndexEntry`.

        Args:
            entry: A Symbol Index ORM record.

        Returns:
            :class:`GraphNode` whose ``node_type`` is derived from
            ``entry.symbol_type``.
        """
        node_type = _SYMBOL_TYPE_TO_NODE_TYPE.get(
            entry.symbol_type, NodeType.VARIABLE
        )
        properties: dict[str, Any] = {
            "symbol_type": entry.symbol_type,
            "visibility": entry.visibility,
            "is_static": entry.is_static,
            "is_async": entry.is_async,
            "is_exported": entry.is_exported,
            "is_deprecated": entry.is_deprecated,
            "start_line": entry.start_line,
            "end_line": entry.end_line,
        }
        if entry.signature:
            properties["signature"] = entry.signature
        if entry.return_type:
            properties["return_type"] = entry.return_type
        if entry.documentation:
            # Truncate very long docstrings to keep graph storage lean
            properties["documentation"] = entry.documentation[:500]
        if entry.module_name:
            properties["module_name"] = entry.module_name
        if entry.namespace:
            properties["namespace"] = entry.namespace

        return GraphNode(
            node_id=str(entry.id),
            node_type=node_type,
            repository_id=str(entry.repository_id),
            name=entry.name,
            qualified_name=entry.qualified_name,
            language=entry.language,
            file_path=str(entry.file_id),  # file_id UUID as path key
            properties=properties,
        )

    @staticmethod
    def build_symbol_node_with_path(
        entry: SymbolIndexEntry,
        relative_path: str,
    ) -> GraphNode:
        """Build a graph node from a Symbol Index entry, enriched with file path.

        Args:
            entry: A Symbol Index ORM record.
            relative_path: Relative source file path resolved from file_id.

        Returns:
            :class:`GraphNode` with ``file_path`` set to the relative path.
        """
        node = NodeBuilder.build_symbol_node(entry)
        node.file_path = relative_path
        return node


def _normalise_library_name(import_path: str) -> str:
    """Extract the top-level package name from an import path.

    Examples::

        "from sqlalchemy.orm import Session" → "sqlalchemy"
        "import redis.asyncio as aioredis"   → "redis"
        "github.com/gin-gonic/gin"           → "gin"

    Args:
        import_path: Raw import module path.

    Returns:
        Normalised top-level library name.
    """
    # Handle Go module paths (e.g. "github.com/gin-gonic/gin")
    if "/" in import_path and "." in import_path:
        parts = import_path.rstrip("/").split("/")
        return parts[-1]  # last segment is the package name

    # Python/JS/TS: first dot-separated segment
    return import_path.split(".")[0].split("/")[0]
