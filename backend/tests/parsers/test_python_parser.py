"""Unit tests for the Python tree-sitter parser.

Verifies that the PythonParser correctly extracts symbols, imports,
calls, classes, functions, routes, and comments from real Python source.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.parsers.tree_sitter.python.parser import PythonParser

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PY = FIXTURE_DIR / "sample_python.py"
SAMPLE_FASTAPI = FIXTURE_DIR / "sample_fastapi.py"

FILE_ID = uuid.uuid4()
REPO_ID = uuid.uuid4()


@pytest.fixture(scope="module")
def parser() -> PythonParser:
    """Return a shared PythonParser instance."""
    return PythonParser()


@pytest.fixture(scope="module")
def python_source() -> str:
    return SAMPLE_PY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fastapi_source() -> str:
    return SAMPLE_FASTAPI.read_text(encoding="utf-8")


class TestPythonParserMetadata:
    """Verify parser registration attributes."""

    def test_language(self, parser):
        assert parser.language == "Python"

    def test_extensions(self, parser):
        assert "py" in parser.extensions
        assert "pyi" in parser.extensions


class TestPythonSymbols:
    """Verify symbol extraction from sample Python file."""

    def test_extracts_classes(self, parser, python_source):
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        names = [s.symbol_name for s in symbols]
        assert "BaseHandler" in names
        assert "AuthHandler" in names

    def test_class_symbol_type(self, parser, python_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        classes = [s for s in symbols if s.symbol_type == SymbolType.CLASS]
        assert len(classes) >= 2

    def test_extracts_functions(self, parser, python_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        fns = [s for s in symbols if s.symbol_type == SymbolType.FUNCTION]
        fn_names = [s.symbol_name for s in fns]
        assert "fetch_data" in fn_names

    def test_extracts_constructor(self, parser, python_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        ctors = [s for s in symbols if s.symbol_type == SymbolType.CONSTRUCTOR]
        assert len(ctors) >= 1

    def test_extracts_constant(self, parser, python_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        consts = [s for s in symbols if s.symbol_type == SymbolType.CONSTANT]
        assert any(s.symbol_name == "MAX_RETRIES" for s in consts)

    def test_extracts_variable(self, parser, python_source):
        from backend.app.parsers.models.symbols import SymbolType
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        vars_ = [s for s in symbols if s.symbol_type == SymbolType.VARIABLE]
        assert any(s.symbol_name == "default_timeout" for s in vars_)

    def test_visibility_private(self, parser, python_source):
        from backend.app.parsers.models.symbols import Visibility
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        # Single-underscore names are PROTECTED in Python convention
        protected = [s for s in symbols if s.visibility == Visibility.PROTECTED]
        names = [s.symbol_name for s in protected]
        assert "_internal_helper" in names

    def test_qualified_names(self, parser, python_source):
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        qnames = [s.qualified_name for s in symbols]
        assert "BaseHandler.handle" in qnames
        assert "BaseHandler.__init__" in qnames

    def test_line_numbers_positive(self, parser, python_source):
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        for s in symbols:
            assert s.start_line >= 1
            assert s.end_line >= s.start_line

    def test_repository_id_propagated(self, parser, python_source):
        symbols = parser.extract_symbols(python_source, FILE_ID, REPO_ID)
        for s in symbols:
            assert s.repository_id == REPO_ID
            assert s.file_id == FILE_ID


class TestPythonImports:
    """Verify import extraction from sample Python files."""

    def test_extracts_stdlib_imports(self, parser, python_source):
        imports = parser.extract_imports(python_source, FILE_ID, REPO_ID)
        paths = [i.module_path for i in imports]
        assert "os" in paths

    def test_extracts_from_imports(self, parser, python_source):
        imports = parser.extract_imports(python_source, FILE_ID, REPO_ID)
        from_imports = [i for i in imports if i.imported_names]
        assert any("Optional" in i.imported_names for i in from_imports)

    def test_import_line_numbers(self, parser, python_source):
        imports = parser.extract_imports(python_source, FILE_ID, REPO_ID)
        for imp in imports:
            assert imp.start_line >= 1

    def test_import_language(self, parser, python_source):
        imports = parser.extract_imports(python_source, FILE_ID, REPO_ID)
        for imp in imports:
            assert imp.language == "Python"


class TestPythonClasses:
    """Verify class definition extraction."""

    def test_base_class_inheritance(self, parser, python_source):
        classes = parser.extract_classes(python_source, FILE_ID, REPO_ID)
        auth = next((c for c in classes if c.class_name == "AuthHandler"), None)
        assert auth is not None
        assert "BaseHandler" in auth.base_classes

    def test_docstring_extracted(self, parser, python_source):
        classes = parser.extract_classes(python_source, FILE_ID, REPO_ID)
        base = next((c for c in classes if c.class_name == "BaseHandler"), None)
        assert base is not None
        assert base.documentation is not None
        assert "HTTP handler" in base.documentation

    def test_class_line_span(self, parser, python_source):
        classes = parser.extract_classes(python_source, FILE_ID, REPO_ID)
        for cls in classes:
            assert cls.end_line > cls.start_line


class TestPythonFunctions:
    """Verify function definition extraction."""

    def test_async_function_detected(self, parser, python_source):
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        fetch = next((f for f in functions if f.function_name == "fetch_data"), None)
        assert fetch is not None
        assert fetch.is_async is True

    def test_static_method_detected(self, parser, python_source):
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        validate = next((f for f in functions if f.function_name == "validate"), None)
        assert validate is not None
        assert validate.is_static is True

    def test_classmethod_detected(self, parser, python_source):
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        from_env = next((f for f in functions if f.function_name == "from_env"), None)
        assert from_env is not None
        assert from_env.is_class_method is True

    def test_return_type_extracted(self, parser, python_source):
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        fetch = next((f for f in functions if f.function_name == "fetch_data"), None)
        assert fetch is not None
        assert fetch.return_type is not None
        assert "dict" in fetch.return_type

    def test_parameters_extracted(self, parser, python_source):
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        # Find __init__ that has a "name" parameter (may be annotated as "name: str")
        init = next(
            (f for f in functions if f.function_name == "__init__"
             and any("name" in p for p in f.parameters)),
            None,
        )
        assert init is not None

    def test_docstring_extracted(self, parser, python_source):
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        fetch = next((f for f in functions if f.function_name == "fetch_data"), None)
        assert fetch is not None
        assert fetch.documentation is not None

    def test_private_function_visibility(self, parser, python_source):
        from backend.app.parsers.models.symbols import Visibility
        functions = parser.extract_functions(python_source, FILE_ID, REPO_ID)
        helper = next((f for f in functions if f.function_name == "_internal_helper"), None)
        assert helper is not None
        # Single-underscore → PROTECTED by Python convention
        assert helper.visibility == Visibility.PROTECTED


class TestPythonRoutes:
    """Verify FastAPI route detection."""

    def test_fastapi_get_route(self, parser, fastapi_source):
        routes = parser.extract_routes(fastapi_source, FILE_ID, REPO_ID)
        get_routes = [r for r in routes if r.http_method == "GET"]
        assert len(get_routes) >= 2

    def test_fastapi_post_route(self, parser, fastapi_source):
        routes = parser.extract_routes(fastapi_source, FILE_ID, REPO_ID)
        post_routes = [r for r in routes if r.http_method == "POST"]
        assert len(post_routes) >= 1

    def test_route_paths_extracted(self, parser, fastapi_source):
        routes = parser.extract_routes(fastapi_source, FILE_ID, REPO_ID)
        paths = [r.path for r in routes]
        assert "/health" in paths
        assert "/users" in paths

    def test_route_language(self, parser, fastapi_source):
        routes = parser.extract_routes(fastapi_source, FILE_ID, REPO_ID)
        for r in routes:
            assert r.language == "Python"


class TestPythonComments:
    """Verify docstring and comment extraction."""

    def test_module_docstring(self, parser, python_source):
        comments = parser.extract_comments(python_source, FILE_ID, REPO_ID)
        docstrings = [c for c in comments if c.comment_type == "docstring"]
        assert len(docstrings) >= 1

    def test_inline_comments(self, parser, python_source):
        comments = parser.extract_comments(python_source, FILE_ID, REPO_ID)
        line_comments = [c for c in comments if c.comment_type == "line"]
        assert len(line_comments) >= 1


class TestPythonParseFile:
    """Integration: parse_file() returns a complete FileSummary."""

    def test_parse_file_returns_summary(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="tests/fixtures/sample_python.py",
            absolute_path=str(SAMPLE_PY),
        )
        assert summary.file_id == FILE_ID
        assert summary.repository_id == REPO_ID
        assert summary.language == "Python"
        assert len(summary.symbols) > 0
        assert len(summary.imports) > 0
        assert len(summary.functions) > 0
        assert len(summary.classes) > 0

    def test_parse_file_no_fatal_errors(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="tests/fixtures/sample_python.py",
            absolute_path=str(SAMPLE_PY),
        )
        fatal = [e for e in summary.parse_errors if "Cannot read file" in e]
        assert not fatal

    def test_parse_duration_recorded(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="tests/fixtures/sample_python.py",
            absolute_path=str(SAMPLE_PY),
        )
        assert summary.parse_duration_ms > 0

    def test_parse_missing_file_returns_error(self, parser):
        summary = parser.parse_file(
            file_id=FILE_ID,
            repository_id=REPO_ID,
            relative_path="nonexistent.py",
            absolute_path="/nonexistent/path/file.py",
        )
        assert len(summary.parse_errors) > 0
        assert "Cannot read file" in summary.parse_errors[0]
