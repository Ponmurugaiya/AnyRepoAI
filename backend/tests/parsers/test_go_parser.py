"""Unit tests for the Go tree-sitter parser.

Verifies struct, interface, function, method, import, Gin route,
visibility, and doc comment extraction from Go source.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.parsers.tree_sitter.go.parser import GoParser

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GO = FIXTURE_DIR / "sample_go.go"

FILE_ID = uuid.uuid4()
REPO_ID = uuid.uuid4()


@pytest.fixture(scope="module")
def parser() -> GoParser:
    return GoParser()


@pytest.fixture(scope="module")
def go_source() -> str:
    return SAMPLE_GO.read_text(encoding="utf-8")


class TestGoParserMetadata:
    def test_language(self, parser):
        assert parser.language == "Go"

    def test_extensions(self, parser):
        assert "go" in parser.extensions


class TestGoSymbols:
    def test_extracts_structs(self, parser, go_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        structs = [s for s in symbols if s.symbol_type == SymbolType.STRUCT]
        names = [s.symbol_name for s in structs]
        assert "User" in names
        assert "UserService" in names
        assert "UserHandler" in names

    def test_extracts_interface(self, parser, go_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        ifaces = [s for s in symbols if s.symbol_type == SymbolType.INTERFACE]
        assert any(s.symbol_name == "UserRepository" for s in ifaces)

    def test_extracts_functions(self, parser, go_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        fns = [s for s in symbols if s.symbol_type == SymbolType.FUNCTION]
        names = [s.symbol_name for s in fns]
        assert "NewUserService" in names
        assert "NewUserHandler" in names

    def test_extracts_methods(self, parser, go_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        methods = [s for s in symbols if s.symbol_type == SymbolType.METHOD]
        names = [s.symbol_name for s in methods]
        assert "GetUser" in names
        assert "CreateUser" in names

    def test_extracts_constant(self, parser, go_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        consts = [s for s in symbols if s.symbol_type == SymbolType.CONSTANT]
        assert any(s.symbol_name == "MaxPageSize" for s in consts)

    def test_go_exported_visibility_public(self, parser, go_source):
        from backend.app.parsers.models.symbols import Visibility
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        public = [s for s in symbols if s.visibility == Visibility.PUBLIC]
        assert len(public) >= 1

    def test_go_unexported_visibility_internal(self, parser, go_source):
        from backend.app.parsers.models.symbols import Visibility
        symbols = parser.extract_symbols(go_source, FILE_ID, REPO_ID)
        internal = [s for s in symbols if s.visibility == Visibility.INTERNAL]
        names = [s.symbol_name for s in internal]
        assert "validateEmail" in names or "contains" in names


class TestGoImports:
    def test_extracts_imports(self, parser, go_source):
        imports = parser.extract_imports(go_source, FILE_ID, REPO_ID)
        assert len(imports) >= 3

    def test_stdlib_import(self, parser, go_source):
        imports = parser.extract_imports(go_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert "fmt" in paths
        assert "net/http" in paths

    def test_third_party_import(self, parser, go_source):
        imports = parser.extract_imports(go_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert any("gin-gonic" in p for p in paths)

    def test_import_language(self, parser, go_source):
        imports = parser.extract_imports(go_source, FILE_ID, REPO_ID)
        for imp in imports:
            assert imp.language == "Go"


class TestGoClasses:
    def test_struct_extracted(self, parser, go_source):
        classes = parser.extract_classes(go_source, FILE_ID, REPO_ID)
        user = next((c for c in classes if c.class_name == "User"), None)
        assert user is not None

    def test_interface_extracted(self, parser, go_source):
        classes = parser.extract_classes(go_source, FILE_ID, REPO_ID)
        iface = next((c for c in classes if c.class_name == "UserRepository"), None)
        assert iface is not None

    def test_struct_with_embedded_types(self, parser, go_source):
        classes = parser.extract_classes(go_source, FILE_ID, REPO_ID)
        service = next((c for c in classes if c.class_name == "UserService"), None)
        assert service is not None


class TestGoFunctions:
    def test_method_with_receiver(self, parser, go_source):
        functions = parser.extract_functions(go_source, FILE_ID, REPO_ID)
        get_user = next((f for f in functions if f.function_name == "GetUser"), None)
        assert get_user is not None
        assert get_user.is_method is True

    def test_top_level_function(self, parser, go_source):
        functions = parser.extract_functions(go_source, FILE_ID, REPO_ID)
        new_svc = next((f for f in functions if f.function_name == "NewUserService"), None)
        assert new_svc is not None
        assert new_svc.is_method is False

    def test_return_type_extracted(self, parser, go_source):
        functions = parser.extract_functions(go_source, FILE_ID, REPO_ID)
        new_svc = next((f for f in functions if f.function_name == "NewUserService"), None)
        assert new_svc is not None
        assert new_svc.return_type is not None

    def test_function_signature(self, parser, go_source):
        functions = parser.extract_functions(go_source, FILE_ID, REPO_ID)
        for fn in functions:
            assert fn.signature is not None
            assert fn.function_name in fn.signature


class TestGoRoutes:
    def test_gin_get_route(self, parser, go_source):
        routes = parser.extract_routes(go_source, FILE_ID, REPO_ID)
        get_routes = [r for r in routes if r.http_method == "GET"]
        assert len(get_routes) >= 2

    def test_gin_post_route(self, parser, go_source):
        routes = parser.extract_routes(go_source, FILE_ID, REPO_ID)
        post_routes = [r for r in routes if r.http_method == "POST"]
        assert len(post_routes) >= 1

    def test_route_paths(self, parser, go_source):
        routes = parser.extract_routes(go_source, FILE_ID, REPO_ID)
        paths = [r.path for r in routes]
        assert "/api/users" in paths

    def test_route_language(self, parser, go_source):
        routes = parser.extract_routes(go_source, FILE_ID, REPO_ID)
        for r in routes:
            assert r.language == "Go"


class TestGoComments:
    def test_line_comments(self, parser, go_source):
        comments = parser.extract_comments(go_source, FILE_ID, REPO_ID)
        line_comments = [c for c in comments if c.comment_type == "line"]
        assert len(line_comments) >= 3

    def test_comment_text_stripped(self, parser, go_source):
        comments = parser.extract_comments(go_source, FILE_ID, REPO_ID)
        for c in comments:
            assert not c.comment_text.startswith("//")
            assert not c.comment_text.startswith("/*")


class TestGoParseFile:
    def test_parse_file_complete(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="fixtures/sample_go.go",
            absolute_path=str(SAMPLE_GO),
        )
        assert summary.language == "Go"
        assert len(summary.symbols) > 0
        assert len(summary.imports) > 0
        assert len(summary.functions) > 0
        assert len(summary.classes) > 0
        assert len(summary.routes) > 0
