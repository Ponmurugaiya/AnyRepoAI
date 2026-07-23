"""Abstract base class for all language parsers.

Every language parser must inherit from ``CodeParser`` and implement
all abstract methods. The parser registry uses this interface to
dispatch parsing by language without knowing concrete implementations.

Design principles:
    - Parsers are stateless — each ``parse_file()`` call is independent.
    - Parsers never read from or write to the database.
    - Parsers never raise on parse errors; they log and continue.
    - All line numbers are 1-indexed.
"""

from __future__ import annotations

import abc
import uuid
from typing import final

from backend.app.parsers.models.symbols import (
    CallReference,
    ClassDefinition,
    CommentBlock,
    FileSummary,
    FunctionDefinition,
    ImportStatement,
    RouteDefinition,
    Symbol,
)


class CodeParser(abc.ABC):
    """Abstract base parser that every language parser must implement.

    Subclasses must override all abstract methods. The concrete parsing
    logic is language-specific, but the public contract is identical
    across all implementations, enabling the registry to dispatch
    transparently.

    Attributes:
        language: Human-readable name of the supported language
            (matches ``ProgrammingLanguage`` enum values, e.g. "Python").
        extensions: File extensions handled by this parser, without dots
            and lowercase (e.g. ``["py", "pyw", "pyi"]``).
    """

    language: str = ""
    extensions: list[str] = []

    # ── High-level entry point ────────────────────────────────────────────────

    @final
    def parse_file(
        self,
        *,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
        relative_path: str,
        absolute_path: str,
    ) -> FileSummary:
        """Parse a source file and return a complete :class:`FileSummary`.

        This is the single public entry point for all parsing work.
        It orchestrates calls to all extraction methods, builds the
        summary, and guarantees that exceptions in any sub-step do NOT
        propagate — they are captured in ``FileSummary.parse_errors``.

        Args:
            file_id: UUID of the ``repository_files`` record.
            repository_id: UUID of the owning repository.
            relative_path: POSIX path relative to the repository root.
            absolute_path: Absolute filesystem path for reading content.

        Returns:
            :class:`~backend.app.parsers.models.symbols.FileSummary`
            with all extracted information and any parse errors.
        """
        import time

        t0 = time.perf_counter()
        errors: list[str] = []

        try:
            source = self._read_source(absolute_path)
        except OSError as exc:
            return FileSummary(
                file_id=file_id,
                repository_id=repository_id,
                relative_path=relative_path,
                language=self.language,
                parse_errors=[f"Cannot read file: {exc}"],
                parse_duration_ms=0.0,
            )

        symbols: list[Symbol] = []
        imports: list[ImportStatement] = []
        calls: list[CallReference] = []
        classes: list[ClassDefinition] = []
        functions: list[FunctionDefinition] = []
        routes: list[RouteDefinition] = []
        comments: list[CommentBlock] = []

        # Each extraction step is isolated so one failure does not
        # prevent other steps from running.
        _steps = [
            ("extract_symbols", lambda: self.extract_symbols(source, file_id, repository_id)),
            ("extract_imports", lambda: self.extract_imports(source, file_id, repository_id)),
            ("extract_calls", lambda: self.extract_calls(source, file_id, repository_id)),
            ("extract_classes", lambda: self.extract_classes(source, file_id, repository_id)),
            ("extract_functions", lambda: self.extract_functions(source, file_id, repository_id)),
            ("extract_routes", lambda: self.extract_routes(source, file_id, repository_id)),
            ("extract_comments", lambda: self.extract_comments(source, file_id, repository_id)),
        ]

        results = [symbols, imports, calls, classes, functions, routes, comments]

        for (step_name, step_fn), container in zip(_steps, results):
            try:
                container.extend(step_fn())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{step_name}: {type(exc).__name__}: {exc}")

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return FileSummary(
            file_id=file_id,
            repository_id=repository_id,
            relative_path=relative_path,
            language=self.language,
            symbols=symbols,
            imports=imports,
            calls=calls,
            classes=classes,
            functions=functions,
            routes=routes,
            comments=comments,
            parse_errors=errors,
            parse_duration_ms=round(elapsed_ms, 3),
        )

    # ── Abstract extraction methods ───────────────────────────────────────────

    @abc.abstractmethod
    def extract_symbols(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[Symbol]:
        """Extract all named symbols from the source code.

        Args:
            source: Full source code content as a string.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.Symbol` instances.
        """

    @abc.abstractmethod
    def extract_imports(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ImportStatement]:
        """Extract all import/require/use statements from the source code.

        Args:
            source: Full source code content.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.ImportStatement` instances.
        """

    @abc.abstractmethod
    def extract_calls(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CallReference]:
        """Extract all function and method calls from the source code.

        Args:
            source: Full source code content.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.CallReference` instances.
        """

    @abc.abstractmethod
    def extract_classes(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ClassDefinition]:
        """Extract all class definitions from the source code.

        Args:
            source: Full source code content.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.ClassDefinition` instances.
        """

    @abc.abstractmethod
    def extract_functions(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[FunctionDefinition]:
        """Extract all function and method definitions from the source code.

        Args:
            source: Full source code content.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.FunctionDefinition` instances.
        """

    @abc.abstractmethod
    def extract_comments(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CommentBlock]:
        """Extract all documentation comments from the source code.

        Args:
            source: Full source code content.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.CommentBlock` instances.
        """

    @abc.abstractmethod
    def extract_routes(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[RouteDefinition]:
        """Detect HTTP route/endpoint declarations in the source code.

        Args:
            source: Full source code content.
            file_id: UUID of the file being parsed.
            repository_id: UUID of the owning repository.

        Returns:
            List of :class:`~backend.app.parsers.models.symbols.RouteDefinition` instances.
        """

    # ── Utility helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _read_source(absolute_path: str) -> str:
        """Read a source file, attempting UTF-8 then latin-1 fallback.

        Args:
            absolute_path: Absolute path to the source file.

        Returns:
            Full source content as a string.

        Raises:
            OSError: If the file cannot be opened or read.
        """
        try:
            with open(absolute_path, encoding="utf-8") as fh:
                return fh.read()
        except UnicodeDecodeError:
            with open(absolute_path, encoding="latin-1") as fh:
                return fh.read()

    @staticmethod
    def _safe_node_text(node: "tree_sitter.Node", source: bytes) -> str:  # type: ignore[name-defined]
        """Extract the UTF-8 text of a tree-sitter node.

        Args:
            node: A tree-sitter ``Node``.
            source: The full source bytes the tree was parsed from.

        Returns:
            Decoded text string.
        """
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _node_line(node: "tree_sitter.Node") -> int:  # type: ignore[name-defined]
        """Return the 1-indexed start line of a tree-sitter node.

        Args:
            node: A tree-sitter ``Node``.

        Returns:
            1-indexed line number.
        """
        return node.start_point[0] + 1

    @staticmethod
    def _node_end_line(node: "tree_sitter.Node") -> int:  # type: ignore[name-defined]
        """Return the 1-indexed end line of a tree-sitter node.

        Args:
            node: A tree-sitter ``Node``.

        Returns:
            1-indexed line number.
        """
        return node.end_point[0] + 1
