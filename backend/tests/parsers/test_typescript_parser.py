"""Unit tests for the TypeScript tree-sitter parser.

Verifies extraction of interfaces, enums, classes, NestJS routes,
access modifiers, JSDoc, and TypeScript-specific syntax.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.parsers.tree_sitter.typescript.parser import TypeScriptParser

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_TS = FIXTURE_DIR / "sample_typescript.ts"

FILE_ID = uuid.uuid4()
REPO_ID = uuid.uuid4()


@pytest.fixture(scope="module")
def parser() -> TypeScriptParser:
    return TypeScriptParser()


@pytest.fixture(scope="module")
def ts_source() -> str:
    return SAMPLE_TS.read_text(encoding="utf-8")


class TestTypeScriptParserMetadata:
    def test_language(self, parser):
        assert parser.language == "TypeScript"

    def test_extensions(self, parser):
        assert "ts" in parser.extensions
        assert "tsx" in parser.extensions


class TestTypeScriptSymbols:
    def test_extracts_enum(self, parser, ts_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(ts_source, FILE_ID, REPO_ID)
        enums = [s for s in symbols if s.symbol_type == SymbolType.ENUM]
        assert any(s.symbol_name == "UserRole" for s in enums)

    def test_extracts_interface(self, parser, ts_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(ts_source, FILE_ID, REPO_ID)
        ifaces = [s for s in symbols if s.symbol_type == SymbolType.INTERFACE]
        assert any(s.symbol_name == "UserDto" for s in ifaces)

    def test_extracts_classes(self, parser, ts_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(ts_source, FILE_ID, REPO_ID)
        classes = [s for s in symbols if s.symbol_type == SymbolType.CLASS]
        names = [s.symbol_name for s in classes]
        assert "UserService" in names
        assert "UserController" in names

    def test_extracts_constant(self, parser, ts_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(ts_source, FILE_ID, REPO_ID)
        consts = [s for s in symbols if s.symbol_type == SymbolType.CONSTANT]
        assert any(s.symbol_name == "MAX_USERS" for s in consts)

    def test_line_numbers(self, parser, ts_source):
        symbols = parser.extract_symbols(ts_source, FILE_ID, REPO_ID)
        for s in symbols:
            assert s.start_line >= 1


class TestTypeScriptImports:
    def test_extracts_named_imports(self, parser, ts_source):
        imports = parser.extract_imports(ts_source, FILE_ID, REPO_ID)
        names_found = []
        for imp in imports:
            names_found.extend(imp.imported_names)
        assert "Injectable" in names_found

    def test_extracts_default_import(self, parser, ts_source):
        imports = parser.extract_imports(ts_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert "axios" in paths

    def test_import_language(self, parser, ts_source):
        imports = parser.extract_imports(ts_source, FILE_ID, REPO_ID)
        for imp in imports:
            assert imp.language == "TypeScript"


class TestTypeScriptClasses:
    def test_base_class_extracted(self, parser, ts_source):
        classes = parser.extract_classes(ts_source, FILE_ID, REPO_ID)
        service = next((c for c in classes if c.class_name == "UserService"), None)
        assert service is not None
        assert "BaseService" in service.base_classes

    def test_abstract_class(self, parser, ts_source):
        classes = parser.extract_classes(ts_source, FILE_ID, REPO_ID)
        base = next((c for c in classes if c.class_name == "BaseService"), None)
        assert base is not None
        assert base.is_abstract is True

    def test_decorator_extracted(self, parser, ts_source):
        classes = parser.extract_classes(ts_source, FILE_ID, REPO_ID)
        service = next((c for c in classes if c.class_name == "UserService"), None)
        assert service is not None
        assert "Injectable" in service.decorators


class TestTypeScriptFunctions:
    def test_async_method(self, parser, ts_source):
        functions = parser.extract_functions(ts_source, FILE_ID, REPO_ID)
        create = next(
            (f for f in functions if f.function_name == "createUser"), None
        )
        assert create is not None
        assert create.is_async is True

    def test_private_method_visibility(self, parser, ts_source):
        from backend.app.parsers.models.symbols import Visibility
        functions = parser.extract_functions(ts_source, FILE_ID, REPO_ID)
        validate = next(
            (f for f in functions if f.function_name == "validateEmail"), None
        )
        assert validate is not None
        assert validate.visibility == Visibility.PRIVATE

    def test_constructor_extracted(self, parser, ts_source):
        functions = parser.extract_functions(ts_source, FILE_ID, REPO_ID)
        ctors = [f for f in functions if f.is_constructor]
        assert len(ctors) >= 1


class TestTypeScriptRoutes:
    def test_nestjs_get_route(self, parser, ts_source):
        routes = parser.extract_routes(ts_source, FILE_ID, REPO_ID)
        get_routes = [r for r in routes if r.http_method == "GET"]
        assert len(get_routes) >= 1

    def test_nestjs_post_route(self, parser, ts_source):
        routes = parser.extract_routes(ts_source, FILE_ID, REPO_ID)
        post_routes = [r for r in routes if r.http_method == "POST"]
        assert len(post_routes) >= 1

    def test_framework_nestjs(self, parser, ts_source):
        routes = parser.extract_routes(ts_source, FILE_ID, REPO_ID)
        nestjs = [r for r in routes if r.framework == "nestjs"]
        assert len(nestjs) >= 1

    def test_route_language(self, parser, ts_source):
        routes = parser.extract_routes(ts_source, FILE_ID, REPO_ID)
        for r in routes:
            assert r.language == "TypeScript"


class TestTypeScriptComments:
    def test_jsdoc_extracted(self, parser, ts_source):
        comments = parser.extract_comments(ts_source, FILE_ID, REPO_ID)
        jsdoc = [c for c in comments if c.comment_type == "jsdoc"]
        assert len(jsdoc) >= 1


class TestTypeScriptParseFile:
    def test_parse_file_complete(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="fixtures/sample_typescript.ts",
            absolute_path=str(SAMPLE_TS),
        )
        assert summary.language == "TypeScript"
        assert len(summary.symbols) > 0
        assert len(summary.classes) > 0
        assert len(summary.functions) > 0
        assert len(summary.routes) > 0
