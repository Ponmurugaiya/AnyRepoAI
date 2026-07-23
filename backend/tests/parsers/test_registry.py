"""Unit tests for the parser registry.

Verifies registration, language/extension lookup, and
that all five required parsers are registered correctly.
"""

from __future__ import annotations

import pytest

from backend.app.parsers.registry.registry import ParserRegistry, get_parser_registry


class TestParserRegistry:
    """Tests for registry build and lookup."""

    def test_registry_has_five_parsers(self):
        registry = get_parser_registry()
        assert len(registry) == 5

    def test_all_required_languages_registered(self):
        registry = get_parser_registry()
        for lang in ["Python", "JavaScript", "TypeScript", "Java", "Go"]:
            assert registry.is_supported(lang), f"Missing parser for {lang}"

    def test_python_lookup_by_language(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_language("Python")
        assert parser is not None
        assert parser.language == "Python"

    def test_case_insensitive_language_lookup(self):
        registry = get_parser_registry()
        assert registry.get_parser_for_language("python") is not None
        assert registry.get_parser_for_language("PYTHON") is not None
        assert registry.get_parser_for_language("Python") is not None

    def test_extension_lookup_py(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_extension("py")
        assert parser is not None
        assert parser.language == "Python"

    def test_extension_lookup_ts(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_extension("ts")
        assert parser is not None
        assert parser.language == "TypeScript"

    def test_extension_lookup_tsx(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_extension("tsx")
        assert parser is not None
        assert parser.language == "TypeScript"

    def test_extension_lookup_js(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_extension("js")
        assert parser is not None
        assert parser.language == "JavaScript"

    def test_extension_lookup_java(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_extension("java")
        assert parser is not None
        assert parser.language == "Java"

    def test_extension_lookup_go(self):
        registry = get_parser_registry()
        parser = registry.get_parser_for_extension("go")
        assert parser is not None
        assert parser.language == "Go"

    def test_unknown_language_returns_none(self):
        registry = get_parser_registry()
        assert registry.get_parser_for_language("COBOL") is None

    def test_unknown_extension_returns_none(self):
        registry = get_parser_registry()
        assert registry.get_parser_for_extension("xyz") is None

    def test_supported_languages_list(self):
        registry = get_parser_registry()
        langs = registry.supported_languages()
        assert "Python" in langs
        assert "TypeScript" in langs
        assert "JavaScript" in langs
        assert "Java" in langs
        assert "Go" in langs

    def test_supported_extensions_list(self):
        registry = get_parser_registry()
        exts = registry.supported_extensions()
        for ext in ["py", "ts", "tsx", "js", "java", "go"]:
            assert ext in exts

    def test_registry_is_singleton(self):
        r1 = get_parser_registry()
        r2 = get_parser_registry()
        assert r1 is r2

    def test_custom_registry_register(self):
        """Verify manual registration on a fresh registry instance."""
        from backend.app.parsers.tree_sitter.python.parser import PythonParser
        reg = ParserRegistry()
        reg.register(PythonParser())
        assert len(reg) == 1
        assert reg.is_supported("Python")

    def test_register_parser_without_language_raises(self):
        from backend.app.parsers.base.parser import CodeParser
        import uuid

        class BrokenParser(CodeParser):
            language = ""
            extensions = []

            def extract_symbols(self, s, f, r): return []
            def extract_imports(self, s, f, r): return []
            def extract_calls(self, s, f, r): return []
            def extract_classes(self, s, f, r): return []
            def extract_functions(self, s, f, r): return []
            def extract_comments(self, s, f, r): return []
            def extract_routes(self, s, f, r): return []

        reg = ParserRegistry()
        with pytest.raises(ValueError, match="language"):
            reg.register(BrokenParser())
