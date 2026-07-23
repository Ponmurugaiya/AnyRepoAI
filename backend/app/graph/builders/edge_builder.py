"""Edge builder: translates Symbol Index data into GraphEdge objects.

The :class:`EdgeBuilder` is responsible for all relationship inference.
It reads Symbol Index tables (imports, calls, classes, functions, routes)
and produces :class:`~backend.app.graph.models.nodes.GraphEdge` objects.

Relationship rules
------------------
CONTAINS       File → Symbol (every symbol belongs to its file)
INHERITS       Class → Parent class
IMPLEMENTS     Class → Interface
IMPORTS        File → ExternalLibrary (from import records)
CALLS          Function/Method → Function/Method (from call records)
EXPOSES_ROUTE  File → ApiRoute (from route records)
BELONGS_TO     Symbol → File (inverse of CONTAINS, for navigation)
DEFINES        Module/File → Class/Function/etc.
DEPENDS_ON     Module → Module (derived from imports between internal modules)
"""

from __future__ import annotations

import json
from typing import Any

from backend.app.core.logging import get_logger
from backend.app.graph.builders.node_builder import (
    NodeBuilder,
    _normalise_library_name,
)
from backend.app.graph.models.nodes import EdgeType, GraphEdge, GraphNode, NodeType
from backend.app.models.symbol import CallRecord, ClassRecord, ImportRecord, RouteRecord
from backend.app.symbol_index.models.index import SymbolIndexEntry

logger = get_logger(__name__)

# Set of module prefixes considered internal (not external libraries).
# An import is internal when its module_path starts with one of these
# prefixes OR when the module resolves to a known Symbol Index entry.
_RELATIVE_IMPORT_MARKERS: tuple[str, ...] = (".", "/")


class EdgeBuilder:
    """Constructs :class:`GraphEdge` objects from Symbol Index relational data.

    All methods are pure functions; they accept plain data and return
    edge lists without any I/O.

    Example::

        builder = EdgeBuilder()
        contain_edges = builder.build_containment_edges(
            file_node_id="file:repo:src/auth.py",
            symbol_entries=entries,
            repository_id="abc-123",
        )
    """

    # ── Containment ────────────────────────────────────────────────────────────

    @staticmethod
    def build_containment_edges(
        file_node_id: str,
        symbol_nodes: list[GraphNode],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create CONTAINS edges from a File node to all its symbol nodes.

        Also creates inverse BELONGS_TO edges for bidirectional navigation.

        Args:
            file_node_id: The stable ID of the File node.
            symbol_nodes: All symbol nodes belonging to this file.
            repository_id: Repository UUID string.

        Returns:
            List of ``CONTAINS`` and ``BELONGS_TO`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []
        for node in symbol_nodes:
            edges.append(GraphEdge(
                source_id=file_node_id,
                target_id=node.node_id,
                edge_type=EdgeType.CONTAINS,
                repository_id=repository_id,
            ))
            edges.append(GraphEdge(
                source_id=node.node_id,
                target_id=file_node_id,
                edge_type=EdgeType.BELONGS_TO,
                repository_id=repository_id,
            ))
        return edges

    # ── Parent-child (DEFINES) ─────────────────────────────────────────────────

    @staticmethod
    def build_defines_edges(
        entries: list[SymbolIndexEntry],
        node_id_map: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create DEFINES edges from parent symbols to their children.

        Uses ``parent_symbol_id`` from the Symbol Index entries.

        Args:
            entries: Symbol Index entries for one repository.
            node_id_map: Mapping of ``str(entry.id)`` → ``node_id`` in the graph.
            repository_id: Repository UUID string.

        Returns:
            List of ``DEFINES`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []
        for entry in entries:
            if entry.parent_symbol_id is None:
                continue
            parent_node_id = node_id_map.get(str(entry.parent_symbol_id))
            child_node_id = node_id_map.get(str(entry.id))
            if parent_node_id and child_node_id:
                edges.append(GraphEdge(
                    source_id=parent_node_id,
                    target_id=child_node_id,
                    edge_type=EdgeType.DEFINES,
                    repository_id=repository_id,
                ))
        return edges

    # ── Inheritance ────────────────────────────────────────────────────────────

    @staticmethod
    def build_inheritance_edges(
        classes: list[ClassRecord],
        qname_to_node_id: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create INHERITS edges for class inheritance relationships.

        Args:
            classes: Class records with ``base_classes`` JSON arrays.
            qname_to_node_id: Mapping of qualified_name → graph node_id.
            repository_id: Repository UUID string.

        Returns:
            List of ``INHERITS`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []
        for cls in classes:
            if not cls.base_classes:
                continue
            try:
                bases: list[str] = json.loads(cls.base_classes)
            except (ValueError, TypeError):
                continue

            child_id = qname_to_node_id.get(cls.qualified_name)
            if not child_id:
                continue

            for base in bases:
                # Try exact qualified name, then just the base name
                parent_id = (
                    qname_to_node_id.get(base)
                    or qname_to_node_id.get(f"{cls.qualified_name}.{base}")
                )
                if parent_id:
                    edges.append(GraphEdge(
                        source_id=child_id,
                        target_id=parent_id,
                        edge_type=EdgeType.INHERITS,
                        repository_id=repository_id,
                        properties={"base_class": base},
                    ))

        return edges

    # ── Interface implementation ───────────────────────────────────────────────

    @staticmethod
    def build_implements_edges(
        classes: list[ClassRecord],
        qname_to_node_id: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create IMPLEMENTS edges for interface implementation.

        Args:
            classes: Class records with ``interfaces`` JSON arrays.
            qname_to_node_id: Mapping of qualified_name → graph node_id.
            repository_id: Repository UUID string.

        Returns:
            List of ``IMPLEMENTS`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []
        for cls in classes:
            if not cls.interfaces:
                continue
            try:
                ifaces: list[str] = json.loads(cls.interfaces)
            except (ValueError, TypeError):
                continue

            class_id = qname_to_node_id.get(cls.qualified_name)
            if not class_id:
                continue

            for iface in ifaces:
                iface_id = qname_to_node_id.get(iface)
                if iface_id:
                    edges.append(GraphEdge(
                        source_id=class_id,
                        target_id=iface_id,
                        edge_type=EdgeType.IMPLEMENTS,
                        repository_id=repository_id,
                        properties={"interface": iface},
                    ))

        return edges

    # ── Import graph ───────────────────────────────────────────────────────────

    @staticmethod
    def build_import_edges(
        imports: list[ImportRecord],
        file_node_id_map: dict[str, str],
        lib_node_id_map: dict[str, str],
        qname_to_node_id: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create IMPORTS and USES_LIBRARY edges from import records.

        Internal imports (where the target module exists in the Symbol Index)
        become ``IMPORTS`` edges.  External library imports become
        ``USES_LIBRARY`` edges pointing to ExternalLibrary nodes.

        Args:
            imports: Import records for the repository.
            file_node_id_map: Mapping of ``str(file_id)`` → file graph node_id.
            lib_node_id_map: Mapping of normalised library name → library node_id.
            qname_to_node_id: Mapping of qualified_name → symbol node_id.
            repository_id: Repository UUID string.

        Returns:
            List of ``IMPORTS`` / ``USES_LIBRARY`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []

        for imp in imports:
            source_file_id = file_node_id_map.get(str(imp.file_id))
            if not source_file_id:
                continue

            module = imp.module_path.strip()

            # Relative imports are always internal
            is_relative = imp.is_relative or module.startswith(_RELATIVE_IMPORT_MARKERS)

            if is_relative:
                # Try to find the target module in the graph by qualified name
                target_id = qname_to_node_id.get(module.lstrip("."))
                if target_id:
                    edges.append(GraphEdge(
                        source_id=source_file_id,
                        target_id=target_id,
                        edge_type=EdgeType.IMPORTS,
                        repository_id=repository_id,
                        properties={"module_path": module},
                    ))
                continue

            # Check if this is an internal module (exists in Symbol Index)
            internal_id = qname_to_node_id.get(module)
            if internal_id:
                edges.append(GraphEdge(
                    source_id=source_file_id,
                    target_id=internal_id,
                    edge_type=EdgeType.IMPORTS,
                    repository_id=repository_id,
                    properties={"module_path": module},
                ))
                continue

            # External library
            lib_name = _normalise_library_name(module)
            lib_id = lib_node_id_map.get(lib_name)
            if lib_id:
                edges.append(GraphEdge(
                    source_id=source_file_id,
                    target_id=lib_id,
                    edge_type=EdgeType.USES_LIBRARY,
                    repository_id=repository_id,
                    properties={"module_path": module},
                ))

        return edges

    # ── Call graph ─────────────────────────────────────────────────────────────

    @staticmethod
    def build_call_edges(
        calls: list[CallRecord],
        qname_to_node_id: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create CALLS edges from call records.

        Args:
            calls: Call records for the repository.
            qname_to_node_id: Mapping of qualified_name → symbol node_id.
            repository_id: Repository UUID string.

        Returns:
            List of ``CALLS`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []
        for call in calls:
            caller_id = qname_to_node_id.get(call.caller_name)
            if not caller_id:
                continue

            # Try to find callee in the graph
            callee_id = (
                qname_to_node_id.get(call.callee_name)
                or (
                    qname_to_node_id.get(
                        f"{call.callee_object}.{call.callee_name}"
                    )
                    if call.callee_object
                    else None
                )
            )
            if callee_id:
                edges.append(GraphEdge(
                    source_id=caller_id,
                    target_id=callee_id,
                    edge_type=EdgeType.CALLS,
                    repository_id=repository_id,
                    properties={
                        "line": call.start_line,
                        "language": call.language,
                    },
                ))

        return edges

    # ── Route graph ────────────────────────────────────────────────────────────

    @staticmethod
    def build_route_edges(
        routes: list[RouteRecord],
        route_node_id_map: dict[str, str],
        qname_to_node_id: dict[str, str],
        file_node_id_map: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create EXPOSES_ROUTE and CALLS edges for HTTP routes.

        Each API route is connected to:
        - Its handler function via ``CALLS``
        - Its source file via ``EXPOSES_ROUTE``

        Args:
            routes: Route records for the repository.
            route_node_id_map: Mapping of route key → route node_id in graph.
            qname_to_node_id: Qualified name → symbol node_id.
            file_node_id_map: str(file_id) → file graph node_id.
            repository_id: Repository UUID string.

        Returns:
            List of ``EXPOSES_ROUTE`` and ``CALLS`` :class:`GraphEdge` objects.
        """
        edges: list[GraphEdge] = []
        for route in routes:
            route_key = _route_key(route)
            route_node_id = route_node_id_map.get(route_key)
            if not route_node_id:
                continue

            # File EXPOSES_ROUTE → ApiRoute
            source_file_id = file_node_id_map.get(str(route.file_id))
            if source_file_id:
                edges.append(GraphEdge(
                    source_id=source_file_id,
                    target_id=route_node_id,
                    edge_type=EdgeType.EXPOSES_ROUTE,
                    repository_id=repository_id,
                    properties={
                        "framework": route.framework,
                        "http_method": route.http_method,
                        "path": route.path,
                    },
                ))

            # ApiRoute CALLS → handler function
            handler_id = qname_to_node_id.get(route.handler_name)
            if handler_id:
                edges.append(GraphEdge(
                    source_id=route_node_id,
                    target_id=handler_id,
                    edge_type=EdgeType.CALLS,
                    repository_id=repository_id,
                    properties={"role": "handler"},
                ))

        return edges

    # ── Directory containment ──────────────────────────────────────────────────

    @staticmethod
    def build_directory_contains_file_edges(
        repo_node_id: str,
        file_nodes: list[GraphNode],
        dir_node_id_map: dict[str, str],
        repository_id: str,
    ) -> list[GraphEdge]:
        """Create CONTAINS edges from Repository/Directory nodes to File nodes.

        Args:
            repo_node_id: Repository graph node ID.
            file_nodes: All File nodes in the repository.
            dir_node_id_map: directory_path → directory node_id map.
            repository_id: Repository UUID string.

        Returns:
            List of ``CONTAINS`` :class:`GraphEdge` objects.
        """
        from pathlib import PurePosixPath

        edges: list[GraphEdge] = []
        for file_node in file_nodes:
            file_path = file_node.qualified_name  # relative_path stored here
            parent_dir = str(PurePosixPath(file_path).parent)

            if parent_dir == ".":
                # Root file — contained directly by the repository
                source_id = repo_node_id
            else:
                source_id = dir_node_id_map.get(parent_dir, repo_node_id)

            edges.append(GraphEdge(
                source_id=source_id,
                target_id=file_node.node_id,
                edge_type=EdgeType.CONTAINS,
                repository_id=repository_id,
            ))

        return edges


def _route_key(route: RouteRecord) -> str:
    """Derive the stable node_id key for a RouteRecord.

    Must match the logic in :class:`~backend.app.graph.services.graph_build_service.GraphBuildService`
    that creates the ApiRoute node.

    Args:
        route: A :class:`RouteRecord` ORM instance.

    Returns:
        Stable string key.
    """
    path_part = route.path.replace("/", "|")
    return f"route:{route.repository_id}:{route.http_method}.{path_part}"
