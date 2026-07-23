"""Tests for the NodeBuilder.

Verifies that every node type is produced correctly from Symbol Index data.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.app.graph.builders.node_builder import NodeBuilder, _normalise_library_name
from backend.app.graph.models.nodes import NodeType
from backend.app.symbol_index.models.index import SymbolIndexEntry

REPO_ID = str(uuid.uuid4())
FILE_ID = str(uuid.uuid4())


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_entry(
    symbol_type: str = "function",
    name: str = "my_func",
    qualified_name: str = "app.my_func",
    language: str = "Python",
    visibility: str = "public",
    is_static: bool = False,
    is_async: bool = False,
    is_exported: bool = True,
    is_deprecated: bool = False,
    start_line: int = 10,
    end_line: int = 20,
    signature: str | None = "def my_func() -> None",
    return_type: str | None = "None",
    documentation: str | None = "Does a thing.",
    module_name: str | None = "app",
    namespace: str | None = None,
    parent_symbol_id: uuid.UUID | None = None,
) -> SymbolIndexEntry:
    entry = MagicMock(spec=SymbolIndexEntry)
    entry.id = uuid.uuid4()
    entry.repository_id = uuid.UUID(REPO_ID)
    entry.file_id = uuid.UUID(FILE_ID)
    entry.symbol_type = symbol_type
    entry.name = name
    entry.qualified_name = qualified_name
    entry.language = language
    entry.visibility = visibility
    entry.is_static = is_static
    entry.is_async = is_async
    entry.is_exported = is_exported
    entry.is_deprecated = is_deprecated
    entry.start_line = start_line
    entry.end_line = end_line
    entry.signature = signature
    entry.return_type = return_type
    entry.documentation = documentation
    entry.module_name = module_name
    entry.namespace = namespace
    entry.parent_symbol_id = parent_symbol_id
    return entry


class TestRepositoryNode:
    def test_node_id_prefixed_with_repo(self) -> None:
        node = NodeBuilder.build_repository_node(REPO_ID, "owner/repo")
        assert node.node_id == f"repo:{REPO_ID}"

    def test_node_type_is_repository(self) -> None:
        node = NodeBuilder.build_repository_node(REPO_ID, "owner/repo")
        assert node.node_type == NodeType.REPOSITORY

    def test_name_is_repo_part(self) -> None:
        node = NodeBuilder.build_repository_node(REPO_ID, "owner/my-service")
        assert node.name == "my-service"

    def test_qualified_name_is_full_name(self) -> None:
        node = NodeBuilder.build_repository_node(REPO_ID, "owner/repo")
        assert node.qualified_name == "owner/repo"

    def test_properties_contain_description(self) -> None:
        node = NodeBuilder.build_repository_node(
            REPO_ID, "owner/repo", description="A service"
        )
        assert node.properties["description"] == "A service"


class TestDirectoryNode:
    def test_node_type_is_directory(self) -> None:
        node = NodeBuilder.build_directory_node(REPO_ID, "src/services")
        assert node.node_type == NodeType.DIRECTORY

    def test_name_is_last_segment(self) -> None:
        node = NodeBuilder.build_directory_node(REPO_ID, "src/services")
        assert node.name == "services"

    def test_node_id_is_stable(self) -> None:
        n1 = NodeBuilder.build_directory_node(REPO_ID, "src/services")
        n2 = NodeBuilder.build_directory_node(REPO_ID, "src/services")
        assert n1.node_id == n2.node_id


class TestFileNode:
    def test_node_type_is_file(self) -> None:
        node = NodeBuilder.build_file_node(REPO_ID, FILE_ID, "src/auth.py", "Python")
        assert node.node_type == NodeType.FILE

    def test_name_is_filename(self) -> None:
        node = NodeBuilder.build_file_node(REPO_ID, FILE_ID, "src/auth.py", "Python")
        assert node.name == "auth.py"

    def test_language_stored(self) -> None:
        node = NodeBuilder.build_file_node(REPO_ID, FILE_ID, "src/auth.ts", "TypeScript")
        assert node.language == "TypeScript"

    def test_extension_in_properties(self) -> None:
        node = NodeBuilder.build_file_node(REPO_ID, FILE_ID, "src/auth.py", "Python")
        assert node.properties["extension"] == "py"


class TestExternalLibraryNode:
    def test_node_type_is_external_library(self) -> None:
        node = NodeBuilder.build_external_library_node(REPO_ID, "redis")
        assert node.node_type == NodeType.EXTERNAL_LIBRARY

    def test_name_normalised(self) -> None:
        node = NodeBuilder.build_external_library_node(REPO_ID, "sqlalchemy.orm")
        assert node.name == "sqlalchemy"

    def test_go_library_name(self) -> None:
        node = NodeBuilder.build_external_library_node(
            REPO_ID, "github.com/gin-gonic/gin"
        )
        assert node.name == "gin"


class TestSymbolNode:
    def test_function_type(self) -> None:
        entry = _make_entry(symbol_type="function")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.FUNCTION

    def test_method_type(self) -> None:
        entry = _make_entry(symbol_type="method")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.METHOD

    def test_constructor_type(self) -> None:
        entry = _make_entry(symbol_type="constructor")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.CONSTRUCTOR

    def test_class_type(self) -> None:
        entry = _make_entry(symbol_type="class")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.CLASS

    def test_interface_type(self) -> None:
        entry = _make_entry(symbol_type="interface")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.INTERFACE

    def test_enum_type(self) -> None:
        entry = _make_entry(symbol_type="enum")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.ENUM

    def test_struct_type(self) -> None:
        entry = _make_entry(symbol_type="struct")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.STRUCT

    def test_route_type(self) -> None:
        entry = _make_entry(symbol_type="route")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_type == NodeType.API_ROUTE

    def test_node_id_is_entry_id_string(self) -> None:
        entry = _make_entry()
        node = NodeBuilder.build_symbol_node(entry)
        assert node.node_id == str(entry.id)

    def test_qualified_name_preserved(self) -> None:
        entry = _make_entry(qualified_name="app.auth.AuthService.login")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.qualified_name == "app.auth.AuthService.login"

    def test_signature_in_properties(self) -> None:
        entry = _make_entry(signature="def login(self) -> Token")
        node = NodeBuilder.build_symbol_node(entry)
        assert node.properties["signature"] == "def login(self) -> Token"

    def test_documentation_truncated_at_500(self) -> None:
        long_doc = "x" * 600
        entry = _make_entry(documentation=long_doc)
        node = NodeBuilder.build_symbol_node(entry)
        assert len(node.properties["documentation"]) <= 500

    def test_async_flag_in_properties(self) -> None:
        entry = _make_entry(is_async=True)
        node = NodeBuilder.build_symbol_node(entry)
        assert node.properties["is_async"] is True

    def test_with_path_sets_file_path(self) -> None:
        entry = _make_entry()
        node = NodeBuilder.build_symbol_node_with_path(entry, "src/auth.py")
        assert node.file_path == "src/auth.py"

    @pytest.mark.parametrize("language", ["Python", "JavaScript", "TypeScript", "Java", "Go"])
    def test_language_propagated(self, language: str) -> None:
        entry = _make_entry(language=language)
        node = NodeBuilder.build_symbol_node(entry)
        assert node.language == language


class TestNormaliseLibraryName:
    def test_python_dotted(self) -> None:
        assert _normalise_library_name("sqlalchemy.orm") == "sqlalchemy"

    def test_go_module_path(self) -> None:
        assert _normalise_library_name("github.com/gin-gonic/gin") == "gin"

    def test_simple_name(self) -> None:
        assert _normalise_library_name("redis") == "redis"

    def test_nested_python(self) -> None:
        assert _normalise_library_name("fastapi.routing") == "fastapi"
