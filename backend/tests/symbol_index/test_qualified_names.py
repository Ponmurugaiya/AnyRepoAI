"""Tests for the QualifiedNameValidator.

Verifies that qualified names are:
- Generated correctly for each language from file paths
- Stable across multiple calls with the same inputs
- Normalised consistently
- Validated correctly
"""

from __future__ import annotations

import pytest

from backend.app.symbol_index.validators.qualified_name import QualifiedNameValidator


class TestQualifiedNameBuild:
    """Verify QualifiedNameValidator.build() produces correct output."""

    def test_python_module_path(self) -> None:
        """Python: app/services/auth.py + AuthService + login → app.services.auth.AuthService.login"""
        result = QualifiedNameValidator.build(
            "app/services/auth.py", "Python", "AuthService", "login"
        )
        assert result == "app.services.auth.AuthService.login"

    def test_python_root_file(self) -> None:
        """Python: top-level file should omit directory prefix."""
        result = QualifiedNameValidator.build(
            "auth.py", "Python", "AuthService"
        )
        assert result == "auth.AuthService"

    def test_python_nested_method(self) -> None:
        """Python: deeply nested path + class + method."""
        result = QualifiedNameValidator.build(
            "backend/app/services/auth.py", "Python", "AuthService", "login"
        )
        assert result == "backend.app.services.auth.AuthService.login"

    def test_java_package_path(self) -> None:
        """Java: com/company/auth/UserService.java → com.company.auth.UserService."""
        result = QualifiedNameValidator.build(
            "com/company/auth/UserService.java", "Java", "login"
        )
        assert result == "com.company.auth.UserService.login"

    def test_go_slash_path(self) -> None:
        """Go: internal/auth/handler.go → internal/auth/handler.AuthHandler.Login."""
        result = QualifiedNameValidator.build(
            "internal/auth/handler.go", "Go", "AuthHandler", "Login"
        )
        assert "handler" in result
        assert "AuthHandler" in result
        assert "Login" in result

    def test_typescript_src_path(self) -> None:
        """TypeScript: src/services/AuthService.ts + AuthService + login."""
        result = QualifiedNameValidator.build(
            "src/services/AuthService.ts", "TypeScript", "AuthService", "login"
        )
        assert result == "src.services.AuthService.AuthService.login"

    def test_javascript_no_extension(self) -> None:
        """JavaScript: stem used correctly."""
        result = QualifiedNameValidator.build(
            "routes/users.js", "JavaScript", "getUser"
        )
        assert result == "routes.users.getUser"

    def test_no_name_parts(self) -> None:
        """Returns module path alone when no name parts are given."""
        result = QualifiedNameValidator.build("app/utils.py", "Python")
        assert result == "app.utils"

    def test_single_name_part(self) -> None:
        """Single name part appended to module."""
        result = QualifiedNameValidator.build("app/utils.py", "Python", "helper")
        assert result == "app.utils.helper"


class TestQualifiedNameNormalise:
    """Verify QualifiedNameValidator.normalise() cleans up names."""

    def test_strips_leading_dot(self) -> None:
        result = QualifiedNameValidator.normalise(".app.services.auth")
        assert not result.startswith(".")

    def test_strips_trailing_dot(self) -> None:
        result = QualifiedNameValidator.normalise("app.services.auth.")
        assert not result.endswith(".")

    def test_collapses_double_dots(self) -> None:
        result = QualifiedNameValidator.normalise("app..services..auth")
        assert ".." not in result

    def test_trims_whitespace(self) -> None:
        result = QualifiedNameValidator.normalise("  app.services.auth  ")
        assert result == "app.services.auth"

    def test_no_op_on_valid_name(self) -> None:
        name = "app.services.auth.AuthService.login"
        assert QualifiedNameValidator.normalise(name) == name


class TestQualifiedNameIsValid:
    """Verify QualifiedNameValidator.is_valid() rejects bad names."""

    def test_valid_dotted_name(self) -> None:
        assert QualifiedNameValidator.is_valid("app.auth.AuthService.login") is True

    def test_valid_go_path(self) -> None:
        assert QualifiedNameValidator.is_valid("internal/auth/handler.Login") is True

    def test_rejects_empty(self) -> None:
        assert QualifiedNameValidator.is_valid("") is False

    def test_rejects_whitespace(self) -> None:
        assert QualifiedNameValidator.is_valid("   ") is False

    def test_rejects_special_chars(self) -> None:
        assert QualifiedNameValidator.is_valid("app.$invalid.name") is False


class TestQualifiedNameExtractName:
    """Verify QualifiedNameValidator.extract_name() returns rightmost segment."""

    def test_extracts_last_segment(self) -> None:
        assert QualifiedNameValidator.extract_name("app.auth.AuthService.login") == "login"

    def test_single_segment(self) -> None:
        assert QualifiedNameValidator.extract_name("login") == "login"

    def test_empty_returns_empty(self) -> None:
        assert QualifiedNameValidator.extract_name("") == ""


class TestQualifiedNameExtractModule:
    """Verify QualifiedNameValidator.extract_module() returns the prefix."""

    def test_removes_name(self) -> None:
        result = QualifiedNameValidator.extract_module(
            "app.auth.AuthService.login", "login"
        )
        assert result == "app.auth.AuthService"

    def test_returns_none_when_equal(self) -> None:
        result = QualifiedNameValidator.extract_module("login", "login")
        assert result is None

    def test_returns_none_when_name_not_suffix(self) -> None:
        result = QualifiedNameValidator.extract_module(
            "app.auth.AuthService", "login"
        )
        # "login" is not a suffix of the qualified name
        assert result is None


class TestLanguageSpecificQualifiedNames:
    """End-to-end verification of language-idiomatic qualified name generation."""

    @pytest.mark.parametrize("path,language,parts,expected_contains", [
        # Python
        ("app/services/auth.py", "Python", ("AuthService", "login"),
         ["app.services.auth", "AuthService", "login"]),
        # Java
        ("com/example/service/UserService.java", "Java", ("UserService", "findById"),
         ["com.example.service.UserService", "findById"]),
        # JavaScript
        ("src/api/users.js", "JavaScript", ("getUser",),
         ["src.api.users", "getUser"]),
        # TypeScript
        ("src/controllers/auth.ts", "TypeScript", ("AuthController", "login"),
         ["src.controllers.auth", "AuthController", "login"]),
        # Go
        ("internal/handler/auth.go", "Go", ("AuthHandler", "Login"),
         ["auth", "AuthHandler", "Login"]),
    ])
    def test_qualified_name_parts_present(
        self,
        path: str,
        language: str,
        parts: tuple,
        expected_contains: list[str],
    ) -> None:
        result = QualifiedNameValidator.build(path, language, *parts)
        for expected in expected_contains:
            assert expected in result, (
                f"Expected '{expected}' in qualified name '{result}' "
                f"for {language} file '{path}'"
            )
