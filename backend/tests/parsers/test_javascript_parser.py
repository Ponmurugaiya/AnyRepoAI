"""Unit tests for the JavaScript tree-sitter parser.

Verifies class, function, arrow function, require/import,
Express routes, JSDoc, and call extraction.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.parsers.tree_sitter.javascript.parser import JavaScriptParser

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_JS = FIXTURE_DIR / "sample_javascript.js"

FILE_ID = uuid.uuid4()
REPO_ID = uuid.uuid4()


@pytest.fixture(scope="module")
def parser() -> JavaScriptParser:
    return JavaScriptParser()


@pytest.fixture(scope="module")
def js_source() -> str:
    return SAMPLE_JS.read_text(encoding="utf-8")


class TestJavaScriptParserMetadata:
    def test_language(self, parser):
        assert parser.language == "JavaScript"

    def test_extensions(self, parser):
        assert "js" in parser.extensions
        assert "jsx" in parser.extensions


class TestJavaScriptSymbols:
    def test_extracts_classes(self, parser, js_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(js_source, FILE_ID, REPO_ID)
        classes = [s for s in symbols if s.symbol_type == SymbolType.CLASS]
        names = [s.symbol_name for s in classes]
        assert "BaseHandler" in names
        assert "UserHandler" in names

    def test_extracts_const_function(self, parser, js_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(js_source, FILE_ID, REPO_ID)
        fns = [s for s in symbols if s.symbol_type in (SymbolType.FUNCTION, SymbolType.CONSTANT)]
        names = [s.symbol_name for s in fns]
        assert "validateEmail" in names

    def test_extracts_constant(self, parser, js_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(js_source, FILE_ID, REPO_ID)
        consts = [s for s in symbols if s.symbol_type == SymbolType.CONSTANT]
        names = [s.symbol_name for s in consts]
        assert "MAX_CONNECTIONS" in names

    def test_line_numbers_positive(self, parser, js_source):
        symbols = parser.extract_symbols(js_source, FILE_ID, REPO_ID)
        for s in symbols:
            assert s.start_line >= 1


class TestJavaScriptImports:
    def test_require_import(self, parser, js_source):
        imports = parser.extract_imports(js_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert "express" in paths

    def test_es6_import(self, parser, js_source):
        imports = parser.extract_imports(js_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert "axios" in paths

    def test_named_import(self, parser, js_source):
        imports = parser.extract_imports(js_source, FILE_ID, REPO_ID)
        named = [i for i in imports if i.imported_names]
        names_flat = [n for i in named for n in i.imported_names]
        assert "readFileSync" in names_flat

    def test_import_language(self, parser, js_source):
        imports = parser.extract_imports(js_source, FILE_ID, REPO_ID)
        for imp in imports:
            assert imp.language == "JavaScript"


class TestJavaScriptClasses:
    def test_class_with_heritage(self, parser, js_source):
        classes = parser.extract_classes(js_source, FILE_ID, REPO_ID)
        user_handler = next(
            (c for c in classes if c.class_name == "UserHandler"), None
        )
        assert user_handler is not None
        assert "BaseHandler" in user_handler.base_classes

    def test_jsdoc_on_class(self, parser, js_source):
        classes = parser.extract_classes(js_source, FILE_ID, REPO_ID)
        base = next((c for c in classes if c.class_name == "BaseHandler"), None)
        assert base is not None
        assert base.documentation is not None


class TestJavaScriptFunctions:
    def test_async_function(self, parser, js_source):
        functions = parser.extract_functions(js_source, FILE_ID, REPO_ID)
        fetch = next((f for f in functions if f.function_name == "fetchUserData"), None)
        assert fetch is not None
        assert fetch.is_async is True

    def test_arrow_function_detected(self, parser, js_source):
        functions = parser.extract_functions(js_source, FILE_ID, REPO_ID)
        names = [f.function_name for f in functions]
        assert "validateEmail" in names

    def test_method_in_class(self, parser, js_source):
        functions = parser.extract_functions(js_source, FILE_ID, REPO_ID)
        methods = [f for f in functions if f.is_method]
        assert len(methods) >= 1


class TestJavaScriptRoutes:
    def test_express_get_route(self, parser, js_source):
        routes = parser.extract_routes(js_source, FILE_ID, REPO_ID)
        get_routes = [r for r in routes if r.http_method == "GET"]
        assert len(get_routes) >= 2

    def test_express_post_route(self, parser, js_source):
        routes = parser.extract_routes(js_source, FILE_ID, REPO_ID)
        post_routes = [r for r in routes if r.http_method == "POST"]
        assert len(post_routes) >= 1

    def test_framework_express(self, parser, js_source):
        routes = parser.extract_routes(js_source, FILE_ID, REPO_ID)
        express = [r for r in routes if r.framework == "express"]
        assert len(express) >= 1

    def test_route_paths(self, parser, js_source):
        routes = parser.extract_routes(js_source, FILE_ID, REPO_ID)
        paths = [r.path for r in routes]
        assert "/health" in paths or "/users" in paths


class TestJavaScriptComments:
    def test_jsdoc_extracted(self, parser, js_source):
        comments = parser.extract_comments(js_source, FILE_ID, REPO_ID)
        jsdoc = [c for c in comments if c.comment_type == "jsdoc"]
        assert len(jsdoc) >= 2

    def test_comment_text_not_empty(self, parser, js_source):
        comments = parser.extract_comments(js_source, FILE_ID, REPO_ID)
        for c in comments:
            assert c.comment_text.strip() != ""


class TestJavaScriptParseFile:
    def test_parse_file_complete(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="fixtures/sample_javascript.js",
            absolute_path=str(SAMPLE_JS),
        )
        assert summary.language == "JavaScript"
        assert len(summary.symbols) > 0
        assert len(summary.imports) > 0
        assert len(summary.functions) > 0
        assert len(summary.classes) > 0
        assert len(summary.routes) > 0
