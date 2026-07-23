"""Tests for the EdgeBuilder.

Verifies that every edge type is produced correctly from Symbol Index data.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest

from backend.app.graph.builders.edge_builder import EdgeBuilder
from backend.app.graph.models.nodes import EdgeType, GraphNode, NodeType
from backend.app.models.symbol import CallRecord, ClassRecord, ImportRecord, RouteRecord

REPO_ID = str(uuid.uuid4())
FILE_ID_A = str(uuid.uuid4())
FILE_ID_B = str(uuid.uuid4())


# ── Helpers ────────────────────────────────────────────────────────────────────


def _node(node_id: str, node_type: NodeType = NodeType.FUNCTION, qname: str = "") -> GraphNode:
    return GraphNode(
        node_id=node_id,
        node_type=node_type,
        repository_id=REPO_ID,
        name=node_id,
        qualified_name=qname or node_id,
    )


def _import(
    file_id: str,
    module_path: str,
    is_relative: bool = False,
) -> ImportRecord:
    imp = MagicMock(spec=ImportRecord)
    imp.file_id = uuid.UUID(file_id)
    imp.module_path = module_path
    imp.is_relative = is_relative
    imp.start_line = 1
    imp.language = "Python"
    return imp


def _call(caller: str, callee: str, callee_object: str | None = None) -> CallRecord:
    call = MagicMock(spec=CallRecord)
    call.caller_name = caller
    call.callee_name = callee
    call.callee_object = callee_object
    call.start_line = 10
    call.language = "Python"
    return call


def _class(qualified_name: str, base_classes: list[str], interfaces: list[str]) -> ClassRecord:
    cls = MagicMock(spec=ClassRecord)
    cls.qualified_name = qualified_name
    cls.base_classes = json.dumps(base_classes)
    cls.interfaces = json.dumps(interfaces)
    return cls


def _route(
    file_id: str,
    http_method: str,
    path: str,
    handler_name: str,
    framework: str = "fastapi",
    language: str = "Python",
) -> RouteRecord:
    r = MagicMock(spec=RouteRecord)
    r.file_id = uuid.UUID(file_id)
    r.repository_id = uuid.UUID(REPO_ID)
    r.http_method = http_method
    r.path = path
    r.handler_name = handler_name
    r.framework = framework
    r.language = language
    r.start_line = 5
    return r


class TestContainmentEdges:
    """CONTAINS and BELONGS_TO edges between File and Symbol nodes."""

    def test_produces_contains_edge(self) -> None:
        sym = _node("sym-1")
        edges = EdgeBuilder.build_containment_edges("file-1", [sym], REPO_ID)
        contains = [e for e in edges if e.edge_type == EdgeType.CONTAINS]
        assert len(contains) == 1
        assert contains[0].source_id == "file-1"
        assert contains[0].target_id == "sym-1"

    def test_produces_belongs_to_edge(self) -> None:
        sym = _node("sym-1")
        edges = EdgeBuilder.build_containment_edges("file-1", [sym], REPO_ID)
        belongs = [e for e in edges if e.edge_type == EdgeType.BELONGS_TO]
        assert len(belongs) == 1
        assert belongs[0].source_id == "sym-1"
        assert belongs[0].target_id == "file-1"

    def test_two_edges_per_symbol(self) -> None:
        syms = [_node(f"sym-{i}") for i in range(3)]
        edges = EdgeBuilder.build_containment_edges("file-1", syms, REPO_ID)
        assert len(edges) == 6  # 2 per symbol

    def test_empty_symbols_returns_empty(self) -> None:
        edges = EdgeBuilder.build_containment_edges("file-1", [], REPO_ID)
        assert edges == []


class TestDefinesEdges:
    """DEFINES edges from parent symbols to children via parent_symbol_id."""

    def test_defines_edge_created(self) -> None:
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        entry = MagicMock()
        entry.id = uuid.UUID(child_id)
        entry.parent_symbol_id = uuid.UUID(parent_id)

        node_id_map = {parent_id: parent_id, child_id: child_id}
        edges = EdgeBuilder.build_defines_edges([entry], node_id_map, REPO_ID)
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.DEFINES
        assert edges[0].source_id == parent_id
        assert edges[0].target_id == child_id

    def test_no_edge_when_no_parent(self) -> None:
        entry = MagicMock()
        entry.id = uuid.uuid4()
        entry.parent_symbol_id = None
        edges = EdgeBuilder.build_defines_edges([entry], {}, REPO_ID)
        assert edges == []

    def test_no_edge_when_parent_not_in_map(self) -> None:
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        entry = MagicMock()
        entry.id = uuid.UUID(child_id)
        entry.parent_symbol_id = uuid.UUID(parent_id)
        # parent_id NOT in map
        edges = EdgeBuilder.build_defines_edges([entry], {child_id: child_id}, REPO_ID)
        assert edges == []


class TestInheritanceEdges:
    """INHERITS edges from subclass to parent class."""

    def test_inherits_edge_created(self) -> None:
        cls = _class("AuthService", ["BaseService"], [])
        qname_map = {
            "AuthService": "node-auth",
            "BaseService": "node-base",
        }
        edges = EdgeBuilder.build_inheritance_edges([cls], qname_map, REPO_ID)
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.INHERITS
        assert edges[0].source_id == "node-auth"
        assert edges[0].target_id == "node-base"

    def test_no_edge_when_base_unknown(self) -> None:
        cls = _class("AuthService", ["UnknownBase"], [])
        qname_map = {"AuthService": "node-auth"}
        edges = EdgeBuilder.build_inheritance_edges([cls], qname_map, REPO_ID)
        assert edges == []

    def test_no_edge_when_no_bases(self) -> None:
        cls = _class("AuthService", [], [])
        qname_map = {"AuthService": "node-auth"}
        edges = EdgeBuilder.build_inheritance_edges([cls], qname_map, REPO_ID)
        assert edges == []

    def test_multiple_bases(self) -> None:
        cls = _class("Multi", ["Base1", "Base2"], [])
        qname_map = {"Multi": "m", "Base1": "b1", "Base2": "b2"}
        edges = EdgeBuilder.build_inheritance_edges([cls], qname_map, REPO_ID)
        assert len(edges) == 2


class TestImplementsEdges:
    """IMPLEMENTS edges from class to interface."""

    def test_implements_edge_created(self) -> None:
        cls = _class("UserService", [], ["IUserService"])
        qname_map = {
            "UserService": "node-svc",
            "IUserService": "node-iface",
        }
        edges = EdgeBuilder.build_implements_edges([cls], qname_map, REPO_ID)
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.IMPLEMENTS

    def test_no_edge_when_interface_unknown(self) -> None:
        cls = _class("UserService", [], ["IUnknown"])
        qname_map = {"UserService": "node-svc"}
        edges = EdgeBuilder.build_implements_edges([cls], qname_map, REPO_ID)
        assert edges == []


class TestImportEdges:
    """IMPORTS and USES_LIBRARY edges from file imports."""

    def test_internal_import_produces_imports_edge(self) -> None:
        imp = _import(FILE_ID_A, "app.auth", is_relative=False)
        file_map = {FILE_ID_A: "file-a"}
        lib_map: dict[str, str] = {}
        qname_map = {"app.auth": "node-auth-module"}

        edges = EdgeBuilder.build_import_edges(
            [imp], file_map, lib_map, qname_map, REPO_ID
        )
        imports = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
        assert len(imports) == 1
        assert imports[0].source_id == "file-a"
        assert imports[0].target_id == "node-auth-module"

    def test_external_import_produces_uses_library_edge(self) -> None:
        imp = _import(FILE_ID_A, "redis", is_relative=False)
        file_map = {FILE_ID_A: "file-a"}
        lib_map = {"redis": "lib-redis"}
        qname_map: dict[str, str] = {}

        edges = EdgeBuilder.build_import_edges(
            [imp], file_map, lib_map, qname_map, REPO_ID
        )
        uses = [e for e in edges if e.edge_type == EdgeType.USES_LIBRARY]
        assert len(uses) == 1
        assert uses[0].target_id == "lib-redis"

    def test_relative_import_matched_internally(self) -> None:
        imp = _import(FILE_ID_A, ".auth", is_relative=True)
        file_map = {FILE_ID_A: "file-a"}
        lib_map: dict[str, str] = {}
        qname_map = {"auth": "node-auth"}

        edges = EdgeBuilder.build_import_edges(
            [imp], file_map, lib_map, qname_map, REPO_ID
        )
        # .auth stripped to "auth" then looked up
        imports = [e for e in edges if e.edge_type == EdgeType.IMPORTS]
        assert len(imports) == 1

    def test_no_edge_when_file_not_in_map(self) -> None:
        imp = _import(FILE_ID_B, "redis", is_relative=False)
        file_map = {FILE_ID_A: "file-a"}  # FILE_ID_B not in map
        lib_map = {"redis": "lib-redis"}
        edges = EdgeBuilder.build_import_edges([imp], file_map, lib_map, {}, REPO_ID)
        assert edges == []


class TestCallEdges:
    """CALLS edges from caller to callee."""

    def test_calls_edge_created(self) -> None:
        call = _call("AuthService.login", "JWTService.generate")
        qname_map = {
            "AuthService.login": "node-login",
            "JWTService.generate": "node-generate",
        }
        edges = EdgeBuilder.build_call_edges([call], qname_map, REPO_ID)
        assert len(edges) == 1
        assert edges[0].edge_type == EdgeType.CALLS
        assert edges[0].source_id == "node-login"
        assert edges[0].target_id == "node-generate"

    def test_no_edge_when_caller_unknown(self) -> None:
        call = _call("UnknownCaller", "JWTService.generate")
        qname_map = {"JWTService.generate": "node-generate"}
        edges = EdgeBuilder.build_call_edges([call], qname_map, REPO_ID)
        assert edges == []

    def test_no_edge_when_callee_unknown(self) -> None:
        call = _call("AuthService.login", "UnknownCallee")
        qname_map = {"AuthService.login": "node-login"}
        edges = EdgeBuilder.build_call_edges([call], qname_map, REPO_ID)
        assert edges == []

    def test_callee_resolved_via_object(self) -> None:
        call = _call("handler", "login", callee_object="AuthService")
        qname_map = {
            "handler": "node-handler",
            "AuthService.login": "node-login",
        }
        edges = EdgeBuilder.build_call_edges([call], qname_map, REPO_ID)
        assert len(edges) == 1
        assert edges[0].target_id == "node-login"

    def test_line_number_in_properties(self) -> None:
        call = _call("AuthService.login", "JWTService.generate")
        call.start_line = 42
        qname_map = {
            "AuthService.login": "node-login",
            "JWTService.generate": "node-generate",
        }
        edges = EdgeBuilder.build_call_edges([call], qname_map, REPO_ID)
        assert edges[0].properties["line"] == 42


class TestRouteEdges:
    """EXPOSES_ROUTE and CALLS (handler) edges for API routes."""

    def test_exposes_route_edge(self) -> None:
        route = _route(FILE_ID_A, "GET", "/users", "list_users")
        route_key = f"route:{REPO_ID}:GET.|users"
        route_map = {route_key: route_key}
        file_map = {FILE_ID_A: "file-a"}
        qname_map = {"list_users": "node-handler"}

        edges = EdgeBuilder.build_route_edges(
            [route], route_map, qname_map, file_map, REPO_ID
        )
        exposes = [e for e in edges if e.edge_type == EdgeType.EXPOSES_ROUTE]
        assert len(exposes) == 1
        assert exposes[0].source_id == "file-a"
        assert exposes[0].target_id == route_key

    def test_route_calls_handler(self) -> None:
        route = _route(FILE_ID_A, "POST", "/users", "create_user")
        route_key = f"route:{REPO_ID}:POST.|users"
        route_map = {route_key: route_key}
        file_map = {FILE_ID_A: "file-a"}
        qname_map = {"create_user": "node-create"}

        edges = EdgeBuilder.build_route_edges(
            [route], route_map, qname_map, file_map, REPO_ID
        )
        calls = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(calls) == 1
        assert calls[0].source_id == route_key
        assert calls[0].target_id == "node-create"

    def test_no_edge_when_route_not_in_map(self) -> None:
        route = _route(FILE_ID_A, "GET", "/unknown", "handler")
        edges = EdgeBuilder.build_route_edges([route], {}, {}, {}, REPO_ID)
        assert edges == []
