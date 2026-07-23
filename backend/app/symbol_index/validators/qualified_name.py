"""Qualified-name generation and validation for the Symbol Index.

Qualified names must be:
    1. Globally stable — the same symbol in the same file always produces the
       same qualified name regardless of how many times it is indexed.
    2. Human-readable — a developer reading a qualified name should immediately
       understand where the symbol lives.
    3. Language-idiomatic — follows the conventions of the source language.

Generation rules by language:

    Python   →  ``<module_path>.<ClassName>.<method_name>``
                e.g. ``app.services.auth.AuthService.login``

    Java     →  ``<package>.<ClassName>.<methodName>``
                e.g. ``com.company.auth.UserService.login``

    Go       →  ``<import_path>.<ReceiverType>.<MethodName>``
                e.g. ``internal/auth/AuthHandler.Login``

    TypeScript / JavaScript
             →  ``<file_path_stem>.<ClassName>.<methodName>``
                e.g. ``src/services/AuthService.login``
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath


# Characters illegal in a qualified-name segment
_ILLEGAL_CHARS_RE = re.compile(r"[^\w.\-/]")
# Collapse multiple dots or slashes
_MULTI_SEP_RE = re.compile(r"\.{2,}")


class QualifiedNameValidator:
    """Validates and normalises qualified symbol names.

    This class is stateless and all methods are pure functions suitable
    for use in parallel processing contexts.

    Example::

        validator = QualifiedNameValidator()
        qn = validator.build("app/auth.py", "Python", "AuthService", "login")
        # → "app.auth.AuthService.login"
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    @staticmethod
    def build(
        relative_path: str,
        language: str,
        *name_parts: str,
    ) -> str:
        """Build a stable qualified name from its constituent parts.

        Args:
            relative_path: POSIX path relative to repository root
                (e.g. ``"app/services/auth.py"``).
            language: Programming language (e.g. ``"Python"``).
            *name_parts: Ordered name segments from outermost to innermost
                (e.g. ``"AuthService"``, ``"login"``).

        Returns:
            Fully-qualified name string.

        Example::

            QualifiedNameValidator.build(
                "app/services/auth.py", "Python",
                "AuthService", "login",
            )
            # → "app.services.auth.AuthService.login"

            QualifiedNameValidator.build(
                "internal/auth/handler.go", "Go",
                "AuthHandler", "Login",
            )
            # → "internal/auth/handler.AuthHandler.Login"
        """
        module = QualifiedNameValidator._path_to_module(relative_path, language)
        parts = [p for p in name_parts if p]
        if module:
            segments = [module] + parts
        else:
            segments = parts
        return QualifiedNameValidator._join_segments(language, segments)

    @staticmethod
    def normalise(qualified_name: str) -> str:
        """Normalise an already-constructed qualified name.

        - Strips leading/trailing whitespace and separators.
        - Collapses consecutive dots.
        - Removes illegal characters from each segment.

        Args:
            qualified_name: Raw qualified name.

        Returns:
            Normalised qualified name string.
        """
        cleaned = qualified_name.strip().strip(".")
        cleaned = _MULTI_SEP_RE.sub(".", cleaned)
        return cleaned

    @staticmethod
    def is_valid(qualified_name: str) -> bool:
        """Return True if ``qualified_name`` is a well-formed identifier.

        Args:
            qualified_name: Name to validate.

        Returns:
            bool: True when valid.
        """
        if not qualified_name or not qualified_name.strip():
            return False
        # Allow dots, hyphens, slashes (Go paths), underscores, alphanumerics,
        # parens for Go receiver syntax e.g. "(Handler).Method"
        return bool(re.match(r"^[\w.\-/()*]+$", qualified_name.strip()))

    @staticmethod
    def extract_name(qualified_name: str) -> str:
        """Return the short (rightmost) segment of a qualified name.

        Args:
            qualified_name: A fully-qualified name.

        Returns:
            The last segment after the rightmost dot.

        Example::

            extract_name("app.auth.AuthService.login")
            # → "login"
        """
        if not qualified_name:
            return ""
        return qualified_name.split(".")[-1]

    @staticmethod
    def extract_module(qualified_name: str, name: str) -> str | None:
        """Return the module prefix by stripping the name from the qualified name.

        Args:
            qualified_name: Fully-qualified name.
            name: Short name to strip from the right.

        Returns:
            Module prefix, or ``None`` if ``qualified_name == name``.
        """
        if qualified_name == name:
            return None
        suffix = f".{name}"
        if qualified_name.endswith(suffix):
            return qualified_name[: -len(suffix)]
        return None

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _path_to_module(relative_path: str, language: str) -> str:
        """Convert a relative file path to a module identifier.

        The conversion strategy is language-specific:

        - Python: ``app/services/auth.py`` → ``app.services.auth``
        - Java: ``com/company/auth/UserService.java`` → ``com.company.auth.UserService``
        - Go: paths keep their slash-separated form (``internal/auth/handler``)
        - JS/TS: ``src/services/AuthService.ts`` → ``src/services/AuthService``

        Args:
            relative_path: POSIX-style path.
            language: Source language name.

        Returns:
            Module identifier string.
        """
        path = PurePosixPath(relative_path)
        stem = path.stem  # filename without extension

        lang_lower = language.lower()

        if lang_lower == "python":
            # Dot-joined path segments, drop extension
            parts = list(path.parent.parts) + [stem]
            # Remove leading dots or current-directory markers
            parts = [p for p in parts if p not in (".", "")]
            return ".".join(parts) if parts else stem

        if lang_lower == "java":
            # Java: package path mirrors directory structure; include class stem
            parts = list(path.parent.parts) + [stem]
            parts = [p for p in parts if p not in (".", "")]
            return ".".join(parts) if parts else stem

        if lang_lower == "go":
            # Go: keep slash-separated import path, drop filename
            parent = str(path.parent)
            if parent and parent != ".":
                return f"{parent}/{stem}"
            return stem

        # JavaScript / TypeScript / other: dot-separated without extension
        parts = list(path.parent.parts) + [stem]
        parts = [p for p in parts if p not in (".", "")]
        return ".".join(parts) if parts else stem

    @staticmethod
    def _join_segments(language: str, segments: list[str]) -> str:
        """Join qualified-name segments using the language's separator convention.

        Go uses ``/`` within the import path and ``.`` for the type separator.
        All other languages use ``.`` exclusively.

        Args:
            language: Source language.
            segments: Ordered name segments.

        Returns:
            Joined qualified name.
        """
        return ".".join(s for s in segments if s)
