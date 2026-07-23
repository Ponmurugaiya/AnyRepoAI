"""Parser registry — automatic language-to-parser dispatch.

The ``ParserRegistry`` maintains a mapping from language names and file
extensions to concrete ``CodeParser`` implementations. Parsers register
themselves at module load time; callers look up parsers without knowing
which class handles a given language.

This design follows the Registry pattern and satisfies the Open/Closed
Principle: adding a new language parser requires zero changes to existing
code — simply implement ``CodeParser`` and call ``registry.register()``.

Usage::

    registry = get_parser_registry()
    parser = registry.get_parser_for_language("Python")
    summary = parser.parse_file(
        file_id=..., repository_id=...,
        relative_path="src/api.py", absolute_path="/storage/repos/.../src/api.py"
    )
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from backend.app.core.logging import get_logger

if TYPE_CHECKING:
    from backend.app.parsers.base.parser import CodeParser

logger = get_logger(__name__)


class ParserRegistry:
    """Thread-safe registry mapping languages and extensions to parsers.

    Parsers are registered by language name (case-insensitive) and
    automatically indexed by their declared file extensions.

    Example::

        registry = ParserRegistry()
        registry.register(PythonParser())
        parser = registry.get_parser_for_language("python")
        parser = registry.get_parser_for_extension("py")
    """

    def __init__(self) -> None:
        # Maps lowercase language name → parser instance
        self._by_language: dict[str, "CodeParser"] = {}
        # Maps lowercase file extension → parser instance
        self._by_extension: dict[str, "CodeParser"] = {}

    def register(self, parser: "CodeParser") -> None:
        """Register a parser instance.

        The parser's ``language`` attribute and all entries in its
        ``extensions`` list are indexed automatically.

        Args:
            parser: A :class:`~backend.app.parsers.base.parser.CodeParser`
                subclass instance. Must have non-empty ``language`` and
                ``extensions`` attributes.

        Raises:
            ValueError: If ``parser.language`` is empty.
        """
        if not parser.language:
            raise ValueError(
                f"Parser {type(parser).__name__} has no language set."
            )

        lang_key = parser.language.lower()

        if lang_key in self._by_language:
            logger.warning(
                "Parser override: replacing existing parser for language",
                language=parser.language,
                previous=type(self._by_language[lang_key]).__name__,
                new=type(parser).__name__,
            )

        self._by_language[lang_key] = parser
        logger.debug(
            "Parser registered",
            language=parser.language,
            parser=type(parser).__name__,
            extensions=parser.extensions,
        )

        for ext in parser.extensions:
            ext_key = ext.lower().lstrip(".")
            self._by_extension[ext_key] = parser
            logger.debug(
                "Extension mapped to parser",
                extension=ext_key,
                parser=type(parser).__name__,
            )

    def get_parser_for_language(self, language: str) -> "CodeParser | None":
        """Return the parser registered for a language name.

        Args:
            language: Language name as stored in ``ProgrammingLanguage``
                enum values (e.g. ``"Python"``, ``"TypeScript"``).
                Case-insensitive.

        Returns:
            The registered :class:`~backend.app.parsers.base.parser.CodeParser`,
            or ``None`` if no parser handles the language.
        """
        return self._by_language.get(language.lower())

    def get_parser_for_extension(self, extension: str) -> "CodeParser | None":
        """Return the parser registered for a file extension.

        Args:
            extension: File extension without leading dot, lowercase
                (e.g. ``"py"``, ``"ts"``).

        Returns:
            The registered parser, or ``None`` if no parser handles
            the extension.
        """
        return self._by_extension.get(extension.lower().lstrip("."))

    def supported_languages(self) -> list[str]:
        """Return all registered language names.

        Returns:
            Sorted list of language names as registered (original casing).
        """
        return sorted(
            {p.language for p in self._by_language.values()},
            key=str.lower,
        )

    def supported_extensions(self) -> list[str]:
        """Return all registered file extensions.

        Returns:
            Sorted list of extension strings (lowercase, no leading dot).
        """
        return sorted(self._by_extension.keys())

    def is_supported(self, language: str) -> bool:
        """Check whether a language has a registered parser.

        Args:
            language: Language name (case-insensitive).

        Returns:
            ``True`` if a parser is registered for the language.
        """
        return language.lower() in self._by_language

    def __len__(self) -> int:
        """Return the number of registered parsers."""
        return len(self._by_language)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ParserRegistry languages={self.supported_languages()} "
            f"extensions={self.supported_extensions()}>"
        )


def _build_registry() -> ParserRegistry:
    """Instantiate and populate the global parser registry.

    All concrete parser implementations are imported here and registered
    in one place. To add a new language: implement ``CodeParser``, import
    it below, and call ``registry.register(YourParser())``.

    Returns:
        Fully populated :class:`ParserRegistry`.
    """
    from backend.app.parsers.tree_sitter.python.parser import PythonParser
    from backend.app.parsers.tree_sitter.javascript.parser import JavaScriptParser
    from backend.app.parsers.tree_sitter.typescript.parser import TypeScriptParser
    from backend.app.parsers.tree_sitter.java.parser import JavaParser
    from backend.app.parsers.tree_sitter.go.parser import GoParser

    registry = ParserRegistry()

    parsers = [
        PythonParser(),
        JavaScriptParser(),
        TypeScriptParser(),
        JavaParser(),
        GoParser(),
    ]

    for parser in parsers:
        try:
            registry.register(parser)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to register parser",
                parser=type(parser).__name__,
                error=str(exc),
            )

    logger.info(
        "Parser registry built",
        languages=registry.supported_languages(),
        total=len(registry),
    )
    return registry


@lru_cache(maxsize=1)
def get_parser_registry() -> ParserRegistry:
    """Return the application-wide parser registry singleton.

    Uses ``lru_cache`` so the registry is built exactly once per process.
    To force a rebuild in tests, call ``get_parser_registry.cache_clear()``.

    Returns:
        The populated :class:`ParserRegistry`.
    """
    return _build_registry()
