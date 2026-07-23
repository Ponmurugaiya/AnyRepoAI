"""Tests for the SymbolMapper.

Verifies that FileSummary objects from every supported language are
correctly translated into symbol index entry dicts, including:
- qualified names
- parent-child relationships
- visibility flags
- documentation extraction
- signature preservation
- deprecation detection
- route symbols
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.parsers.models.symbols import (
    ClassDefinition,
    FileSummary,
    FunctionDefinition,
    RouteDefinition,
    Symbol,
    SymbolType,
    Visibility,
)
from backend.app.symbol_index.mappers.symbol_mapper import SymbolMapper

FILE_ID = uuid.uuid4()
REPO_ID = uuid.uuid4()


def _make_summary(**kwargs) -> FileSummary:
    """Build a minimal FileSummary with sensible defaults."""
    defaults = dict(
        file_id=FILE_ID,
        repository_id=REPO_ID,
        relative_path="app/services/auth.py",
        language="Python",
        symbols=[],
        classes=[],
        functions=[],
        routes=[],
        imports=[],
        calls=[],
        comments=[],
        parse_errors=[],
    )
    defaults.update(kwargs)
    return FileSummary(**defaults)


@pytest.fixture
def mapper() -> SymbolMapper:
    return SymbolMapper()


class TestSymbolMapperClasses:
    """Verify class symbol mapping."""

    def test_class_entry_created(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="app.services.auth.AuthService",
                    base_classes=[],
                    interfaces=[],
                    visibility=Visibility.PUBLIC,
                    start_line=10,
                    end_line=50,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        class_entries = [e for e in entries if e["symbol_type"] == "class"]
        assert len(class_entries) == 1
        assert class_entries[0]["name"] == "AuthService"
        assert class_entries[0]["qualified_name"] == "app.services.auth.AuthService"

    def test_class_visibility_public(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="AuthService",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=10,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        e = entries[0]
        assert e["visibility"] == "public"
        assert e["is_exported"] is True

    def test_class_visibility_private(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="_Internal",
                    qualified_name="_Internal",
                    visibility=Visibility.PRIVATE,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        e = entries[0]
        assert e["visibility"] == "private"
        assert e["is_exported"] is False

    def test_class_documentation_extracted(self, mapper: SymbolMapper) -> None:
        doc = "Handles authentication."
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="AuthService",
                    documentation=doc,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=10,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["documentation"] == doc

    def test_class_deprecation_detected(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="OldService",
                    qualified_name="OldService",
                    documentation="@deprecated Use NewService instead.",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["is_deprecated"] is True

    def test_class_ids_generated(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="A",
                    qualified_name="A",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert isinstance(entries[0]["id"], uuid.UUID)

    def test_class_module_name_derived(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="app.services.auth.AuthService",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=10,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["module_name"] == "app.services.auth"


class TestSymbolMapperFunctions:
    """Verify function and method symbol mapping."""

    def test_function_entry_created(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="login",
                    qualified_name="AuthService.login",
                    is_method=True,
                    visibility=Visibility.PUBLIC,
                    parameters=["self", "username: str", "password: str"],
                    return_type="Token",
                    signature="def login(self, username: str, password: str) -> Token",
                    start_line=20,
                    end_line=35,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        fn_entries = [e for e in entries if e["symbol_type"] == "method"]
        assert len(fn_entries) == 1
        assert fn_entries[0]["name"] == "login"

    def test_method_type_assigned(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="process",
                    qualified_name="Handler.process",
                    is_method=True,
                    visibility=Visibility.PUBLIC,
                    start_line=5,
                    end_line=15,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["symbol_type"] == "method"

    def test_constructor_type_assigned(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="__init__",
                    qualified_name="AuthService.__init__",
                    is_method=True,
                    is_constructor=True,
                    visibility=Visibility.PUBLIC,
                    start_line=10,
                    end_line=20,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["symbol_type"] == "constructor"

    def test_async_function_flag(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="fetch",
                    qualified_name="fetch",
                    is_async=True,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["is_async"] is True

    def test_static_method_flag(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="validate",
                    qualified_name="AuthService.validate",
                    is_static=True,
                    is_method=True,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["is_static"] is True

    def test_signature_preserved(self, mapper: SymbolMapper) -> None:
        sig = "def login(username: str, password: str) -> Token"
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="login",
                    qualified_name="login",
                    signature=sig,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["signature"] == sig

    def test_return_type_preserved(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="login",
                    qualified_name="login",
                    return_type="Token",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["return_type"] == "Token"

    def test_documentation_extracted(self, mapper: SymbolMapper) -> None:
        doc = "Authenticate a user and return a session token."
        summary = _make_summary(
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="login",
                    qualified_name="login",
                    documentation=doc,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["documentation"] == doc


class TestSymbolMapperRoutes:
    """Verify HTTP route symbol mapping."""

    def test_route_entry_created(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            routes=[
                RouteDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    http_method="GET",
                    path="/users/{id}",
                    handler_name="get_user",
                    framework="fastapi",
                    start_line=15,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        route_entries = [e for e in entries if e["symbol_type"] == "route"]
        assert len(route_entries) == 1

    def test_route_qualified_name_encodes_method_and_path(
        self, mapper: SymbolMapper
    ) -> None:
        summary = _make_summary(
            routes=[
                RouteDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    http_method="POST",
                    path="/users",
                    handler_name="create_user",
                    framework="fastapi",
                    start_line=20,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        route = entries[0]
        assert "POST" in route["qualified_name"]
        assert "users" in route["qualified_name"]

    def test_route_is_exported(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            routes=[
                RouteDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    http_method="DELETE",
                    path="/users/{id}",
                    handler_name="delete_user",
                    framework="fastapi",
                    start_line=30,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["is_exported"] is True

    def test_route_framework_stored_as_namespace(
        self, mapper: SymbolMapper
    ) -> None:
        summary = _make_summary(
            routes=[
                RouteDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    http_method="GET",
                    path="/health",
                    handler_name="health_check",
                    framework="fastapi",
                    start_line=5,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["namespace"] == "fastapi"

    def test_duplicate_routes_deduplicated(self, mapper: SymbolMapper) -> None:
        route = RouteDefinition(
            repository_id=REPO_ID,
            file_id=FILE_ID,
            http_method="GET",
            path="/users",
            handler_name="list_users",
            framework="fastapi",
            start_line=10,
            language="Python",
        )
        summary = _make_summary(routes=[route, route])
        entries = mapper.map_file_summary(summary)
        route_entries = [e for e in entries if e["symbol_type"] == "route"]
        assert len(route_entries) == 1


class TestSymbolMapperParentChildHierarchy:
    """Verify parent_symbol_id is correctly resolved."""

    def test_method_parent_is_class(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="AuthService",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=50,
                    language="Python",
                )
            ],
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name="login",
                    qualified_name="AuthService.login",
                    is_method=True,
                    visibility=Visibility.PUBLIC,
                    start_line=10,
                    end_line=20,
                    language="Python",
                )
            ],
        )
        entries = mapper.map_file_summary(summary)
        class_entry = next(e for e in entries if e["name"] == "AuthService")
        method_entry = next(e for e in entries if e["name"] == "login")

        # Method's parent_symbol_id must reference the class entry's id
        assert method_entry["parent_symbol_id"] == class_entry["id"]

    def test_top_level_symbol_has_no_parent(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="AuthService",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=10,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert entries[0]["parent_symbol_id"] is None


class TestSymbolMapperGenericSymbols:
    """Verify fallback to generic symbol mapping."""

    def test_generic_symbol_mapped(self, mapper: SymbolMapper) -> None:
        summary = _make_summary(
            symbols=[
                Symbol(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    symbol_name="MAX_RETRIES",
                    qualified_name="MAX_RETRIES",
                    symbol_type=SymbolType.CONSTANT,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=1,
                    language="Python",
                )
            ]
        )
        entries = mapper.map_file_summary(summary)
        assert any(e["name"] == "MAX_RETRIES" for e in entries)

    def test_generic_symbol_not_duplicated_with_class(
        self, mapper: SymbolMapper
    ) -> None:
        """Symbol already emitted by class mapper must not be re-emitted."""
        summary = _make_summary(
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name="AuthService",
                    qualified_name="AuthService",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=50,
                    language="Python",
                )
            ],
            symbols=[
                Symbol(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    symbol_name="AuthService",
                    qualified_name="AuthService",
                    symbol_type=SymbolType.CLASS,
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=50,
                    language="Python",
                )
            ],
        )
        entries = mapper.map_file_summary(summary)
        service_entries = [e for e in entries if e["name"] == "AuthService"]
        assert len(service_entries) == 1


class TestSymbolMapperLanguageCoverage:
    """Verify mapping works for all supported languages."""

    @pytest.mark.parametrize("language,path,class_name,method_name", [
        ("Python", "app/auth.py", "AuthService", "login"),
        ("JavaScript", "src/auth.js", "AuthService", "login"),
        ("TypeScript", "src/auth.ts", "AuthService", "login"),
        ("Java", "com/example/AuthService.java", "AuthService", "login"),
        ("Go", "internal/auth/handler.go", "AuthHandler", "Login"),
    ])
    def test_language_produces_entries(
        self,
        mapper: SymbolMapper,
        language: str,
        path: str,
        class_name: str,
        method_name: str,
    ) -> None:
        summary = _make_summary(
            relative_path=path,
            language=language,
            classes=[
                ClassDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    class_name=class_name,
                    qualified_name=f"{class_name}",
                    visibility=Visibility.PUBLIC,
                    start_line=1,
                    end_line=50,
                    language=language,
                )
            ],
            functions=[
                FunctionDefinition(
                    repository_id=REPO_ID,
                    file_id=FILE_ID,
                    function_name=method_name,
                    qualified_name=f"{class_name}.{method_name}",
                    is_method=True,
                    visibility=Visibility.PUBLIC,
                    start_line=10,
                    end_line=20,
                    language=language,
                )
            ],
        )
        entries = mapper.map_file_summary(summary)
        assert any(e["name"] == class_name for e in entries)
        assert any(e["name"] == method_name for e in entries)
        for entry in entries:
            assert entry["language"] == language
