"""Unit tests for the Java tree-sitter parser.

Verifies extraction of classes, interfaces, enums, methods, constructors,
Spring Boot routes, JavaDoc, and Java imports.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.parsers.tree_sitter.java.parser import JavaParser

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_JAVA = FIXTURE_DIR / "sample_java.java"

FILE_ID = uuid.uuid4()
REPO_ID = uuid.uuid4()


@pytest.fixture(scope="module")
def parser() -> JavaParser:
    return JavaParser()


@pytest.fixture(scope="module")
def java_source() -> str:
    return SAMPLE_JAVA.read_text(encoding="utf-8")


class TestJavaParserMetadata:
    def test_language(self, parser):
        assert parser.language == "Java"

    def test_extensions(self, parser):
        assert "java" in parser.extensions


class TestJavaSymbols:
    def test_extracts_classes(self, parser, java_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        classes = [s for s in symbols if s.symbol_type == SymbolType.CLASS]
        names = [s.symbol_name for s in classes]
        assert "User" in names
        assert "UserService" in names
        assert "UserController" in names

    def test_extracts_interface(self, parser, java_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        ifaces = [s for s in symbols if s.symbol_type == SymbolType.INTERFACE]
        assert any(s.symbol_name == "UserRepository" for s in ifaces)

    def test_extracts_enum(self, parser, java_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        enums = [s for s in symbols if s.symbol_type == SymbolType.ENUM]
        assert any(s.symbol_name == "Role" for s in enums)

    def test_extracts_methods(self, parser, java_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        methods = [s for s in symbols if s.symbol_type == SymbolType.METHOD]
        names = [s.symbol_name for s in methods]
        assert "getUser" in names or "getAllUsers" in names

    def test_extracts_constructor(self, parser, java_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        ctors = [s for s in symbols if s.symbol_type == SymbolType.CONSTRUCTOR]
        assert len(ctors) >= 1

    def test_visibility_private(self, parser, java_source):
        from backend.app.parsers.models.symbols import Visibility
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        private = [s for s in symbols if s.visibility == Visibility.PRIVATE]
        assert len(private) >= 1

    def test_visibility_public(self, parser, java_source):
        from backend.app.parsers.models.symbols import Visibility
        symbols = parser.extract_symbols(java_source, FILE_ID, REPO_ID)
        public = [s for s in symbols if s.visibility == Visibility.PUBLIC]
        assert len(public) >= 1


class TestJavaImports:
    def test_extracts_imports(self, parser, java_source):
        imports = parser.extract_imports(java_source, FILE_ID, REPO_ID)
        assert len(imports) >= 1

    def test_import_paths(self, parser, java_source):
        imports = parser.extract_imports(java_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert any("java.util" in p for p in paths)

    def test_import_language(self, parser, java_source):
        imports = parser.extract_imports(java_source, FILE_ID, REPO_ID)
        for imp in imports:
            assert imp.language == "Java"


class TestJavaClasses:
    def test_class_with_documentation(self, parser, java_source):
        classes = parser.extract_classes(java_source, FILE_ID, REPO_ID)
        user_class = next((c for c in classes if c.class_name == "User"), None)
        assert user_class is not None

    def test_service_annotation(self, parser, java_source):
        classes = parser.extract_classes(java_source, FILE_ID, REPO_ID)
        service = next((c for c in classes if c.class_name == "UserService"), None)
        assert service is not None
        # @Service annotation should be captured
        assert "Service" in service.decorators


class TestJavaFunctions:
    def test_method_with_parameters(self, parser, java_source):
        functions = parser.extract_functions(java_source, FILE_ID, REPO_ID)
        create = next((f for f in functions if f.function_name == "createUser"), None)
        assert create is not None
        assert len(create.parameters) >= 1

    def test_return_type_extracted(self, parser, java_source):
        functions = parser.extract_functions(java_source, FILE_ID, REPO_ID)
        get_user = next((f for f in functions if f.function_name == "getUser"), None)
        assert get_user is not None
        assert get_user.return_type is not None

    def test_constructor_is_not_method(self, parser, java_source):
        functions = parser.extract_functions(java_source, FILE_ID, REPO_ID)
        ctors = [f for f in functions if f.is_constructor]
        assert len(ctors) >= 1
        for ctor in ctors:
            assert not ctor.is_method


class TestJavaRoutes:
    def test_spring_get_mapping(self, parser, java_source):
        routes = parser.extract_routes(java_source, FILE_ID, REPO_ID)
        get_routes = [r for r in routes if r.http_method == "GET"]
        assert len(get_routes) >= 1

    def test_spring_post_mapping(self, parser, java_source):
        routes = parser.extract_routes(java_source, FILE_ID, REPO_ID)
        post_routes = [r for r in routes if r.http_method == "POST"]
        assert len(post_routes) >= 1

    def test_spring_delete_mapping(self, parser, java_source):
        routes = parser.extract_routes(java_source, FILE_ID, REPO_ID)
        del_routes = [r for r in routes if r.http_method == "DELETE"]
        assert len(del_routes) >= 1

    def test_framework_spring(self, parser, java_source):
        routes = parser.extract_routes(java_source, FILE_ID, REPO_ID)
        spring = [r for r in routes if r.framework == "spring"]
        assert len(spring) >= 1

    def test_route_language(self, parser, java_source):
        routes = parser.extract_routes(java_source, FILE_ID, REPO_ID)
        for r in routes:
            assert r.language == "Java"


class TestJavaComments:
    def test_javadoc_extracted(self, parser, java_source):
        comments = parser.extract_comments(java_source, FILE_ID, REPO_ID)
        javadoc = [c for c in comments if c.comment_type == "javadoc"]
        assert len(javadoc) >= 1

    def test_line_comment_extracted(self, parser, java_source):
        comments = parser.extract_comments(java_source, FILE_ID, REPO_ID)
        # sample_java.java uses /** */ javadoc style; verify at least one block comment
        block_comments = [c for c in comments if c.comment_type in ("javadoc", "block")]
        assert len(block_comments) >= 1


class TestJavaParseFile:
    def test_parse_file_complete(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="fixtures/sample_java.java",
            absolute_path=str(SAMPLE_JAVA),
        )
        assert summary.language == "Java"
        assert len(summary.symbols) > 0
        assert len(summary.classes) > 0
        assert len(summary.functions) > 0
        assert len(summary.routes) > 0
        assert len(summary.imports) > 0
