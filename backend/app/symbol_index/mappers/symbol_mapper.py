"""Translation layer between parser domain models and Symbol Index entries.

The :class:`SymbolMapper` converts :class:`~backend.app.parsers.models.symbols.FileSummary`
output into :class:`~backend.app.symbol_index.models.index.SymbolIndexEntry` ORM dicts
ready for bulk insertion.

This is the only place where parser-domain knowledge (e.g. what fields a
:class:`~backend.app.parsers.models.symbols.FunctionDefinition` carries) is
translated into the canonical index schema. Keeping this in one mapper class
means future parser changes require changes only here, not in the service layer.

Supported symbol sources:
    - :class:`~backend.app.parsers.models.symbols.Symbol` (generic symbol)
    - :class:`~backend.app.parsers.models.symbols.ClassDefinition`
    - :class:`~backend.app.parsers.models.symbols.FunctionDefinition`
    - :class:`~backend.app.parsers.models.symbols.RouteDefinition`
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.app.core.logging import get_logger
from backend.app.parsers.models.symbols import (
    ClassDefinition,
    FileSummary,
    FunctionDefinition,
    RouteDefinition,
    Symbol,
    SymbolType,
    Visibility,
)
from backend.app.symbol_index.validators.qualified_name import QualifiedNameValidator

logger = get_logger(__name__)

# Symbol types that carry route semantics
_ROUTE_SYMBOL_TYPES: frozenset[str] = frozenset(
    {SymbolType.ROUTE.value, "route", "api_route"}
)

# Deprecation indicators found in documentation strings
_DEPRECATION_MARKERS: tuple[str, ...] = (
    "@deprecated",
    "deprecated",
    "@Deprecated",
    ".. deprecated::",
    "DEPRECATED",
)


class SymbolMapper:
    """Converts parser domain objects to Symbol Index entry dicts.

    All methods return plain ``dict`` objects (column-name → value) rather
    than ORM instances so they can be passed directly to SQLAlchemy's bulk
    ``insert()`` without the overhead of model instantiation.

    The mapper is stateless and safe for concurrent use.

    Example::

        mapper = SymbolMapper()
        entries = mapper.map_file_summary(summary)
        # entries is a list[dict] ready for bulk insert
    """

    # ── Public entry point ─────────────────────────────────────────────────────

    def map_file_summary(
        self,
        summary: FileSummary,
        *,
        parent_id_map: dict[str, uuid.UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """Convert a :class:`FileSummary` to a list of index entry dicts.

        The function processes all symbol sources in the summary, assigning
        UUIDs and resolving parent IDs. The caller is responsible for
        deduplication before bulk-insert.

        Args:
            summary: Parse output for a single source file.
            parent_id_map: Optional mapping of ``qualified_name → UUID`` for
                symbols already in the database (used to resolve
                ``parent_symbol_id`` references to existing records).

        Returns:
            list[dict]: Column dicts ready for bulk insert into
            ``symbol_index_entries``.
        """
        parent_ids: dict[str, uuid.UUID] = dict(parent_id_map or {})
        entries: list[dict[str, Any]] = []

        # Process in order: classes first so parent IDs are available for methods
        entries.extend(
            self._map_classes(summary, parent_ids)
        )
        entries.extend(
            self._map_functions(summary, parent_ids)
        )
        entries.extend(
            self._map_routes(summary, parent_ids)
        )
        entries.extend(
            self._map_generic_symbols(summary, parent_ids, already_mapped=entries)
        )

        return entries

    # ── Class mapping ──────────────────────────────────────────────────────────

    def _map_classes(
        self,
        summary: FileSummary,
        parent_ids: dict[str, uuid.UUID],
    ) -> list[dict[str, Any]]:
        """Map :class:`ClassDefinition` objects from the summary.

        Args:
            summary: Source file parse summary.
            parent_ids: Mutable parent-ID map updated with new class UUIDs.

        Returns:
            list[dict]: Column dicts for class symbols.
        """
        entries: list[dict[str, Any]] = []
        for cls in summary.classes:
            entry_id = uuid.uuid4()
            qname = self._ensure_qualified_name(
                cls.qualified_name,
                summary.relative_path,
                summary.language,
                cls.class_name,
            )
            parent_id = self._resolve_parent_id(cls.qualified_name, parent_ids)
            doc = cls.documentation
            entry: dict[str, Any] = {
                "id": entry_id,
                "repository_id": summary.repository_id,
                "file_id": summary.file_id,
                "language": summary.language,
                "symbol_type": SymbolType.CLASS.value,
                "name": cls.class_name,
                "qualified_name": qname,
                "display_name": self._display_name(qname, cls.class_name),
                "parent_symbol_id": parent_id,
                "module_name": QualifiedNameValidator.extract_module(qname, cls.class_name),
                "namespace": None,
                "signature": f"class {cls.class_name}",
                "return_type": None,
                "visibility": cls.visibility.value,
                "is_static": False,
                "is_async": False,
                "is_exported": self._is_exported(cls.visibility),
                "is_deprecated": self._is_deprecated(doc),
                "documentation": doc,
                "start_line": cls.start_line,
                "end_line": cls.end_line,
                "start_column": 0,
                "end_column": 0,
            }
            entries.append(entry)
            # Register so child symbols can reference this as their parent
            parent_ids[qname] = entry_id

        return entries

    # ── Function / method mapping ──────────────────────────────────────────────

    def _map_functions(
        self,
        summary: FileSummary,
        parent_ids: dict[str, uuid.UUID],
    ) -> list[dict[str, Any]]:
        """Map :class:`FunctionDefinition` objects from the summary.

        Args:
            summary: Source file parse summary.
            parent_ids: Parent-ID map (read and updated).

        Returns:
            list[dict]: Column dicts for function and method symbols.
        """
        entries: list[dict[str, Any]] = []
        for fn in summary.functions:
            entry_id = uuid.uuid4()
            qname = self._ensure_qualified_name(
                fn.qualified_name,
                summary.relative_path,
                summary.language,
                fn.function_name,
            )
            parent_id = self._resolve_parent_id(fn.qualified_name, parent_ids)
            doc = fn.documentation

            if fn.is_constructor:
                sym_type = SymbolType.CONSTRUCTOR.value
            elif fn.is_method:
                sym_type = SymbolType.METHOD.value
            else:
                sym_type = SymbolType.FUNCTION.value

            entry: dict[str, Any] = {
                "id": entry_id,
                "repository_id": summary.repository_id,
                "file_id": summary.file_id,
                "language": summary.language,
                "symbol_type": sym_type,
                "name": fn.function_name,
                "qualified_name": qname,
                "display_name": self._display_name(qname, fn.function_name),
                "parent_symbol_id": parent_id,
                "module_name": QualifiedNameValidator.extract_module(qname, fn.function_name),
                "namespace": None,
                "signature": fn.signature,
                "return_type": fn.return_type,
                "visibility": fn.visibility.value,
                "is_static": fn.is_static,
                "is_async": fn.is_async,
                "is_exported": self._is_exported(fn.visibility),
                "is_deprecated": self._is_deprecated(doc),
                "documentation": doc,
                "start_line": fn.start_line,
                "end_line": fn.end_line,
                "start_column": 0,
                "end_column": 0,
            }
            entries.append(entry)
            parent_ids[qname] = entry_id

        return entries

    # ── Route mapping ──────────────────────────────────────────────────────────

    def _map_routes(
        self,
        summary: FileSummary,
        parent_ids: dict[str, uuid.UUID],
    ) -> list[dict[str, Any]]:
        """Map :class:`RouteDefinition` objects from the summary.

        Routes are surfaced as ``route`` symbols whose ``qualified_name``
        encodes the HTTP method and path so routes can be found by
        qualified-name search.

        Example qualified name:
            ``src/api/users.GET./users/{id}``

        Args:
            summary: Source file parse summary.
            parent_ids: Parent-ID map (read-only for routes).

        Returns:
            list[dict]: Column dicts for route symbols.
        """
        entries: list[dict[str, Any]] = []
        seen_qnames: set[str] = set()

        for route in summary.routes:
            # Build a stable qualified name that encodes method + path
            route_qname = (
                f"{route.handler_name}.{route.http_method}.{route.path}"
            )
            # Normalise slashes in the path segment
            route_qname = route_qname.replace("/", "|")

            if route_qname in seen_qnames:
                continue
            seen_qnames.add(route_qname)

            parent_id = parent_ids.get(route.handler_name)
            entry: dict[str, Any] = {
                "id": uuid.uuid4(),
                "repository_id": summary.repository_id,
                "file_id": summary.file_id,
                "language": summary.language,
                "symbol_type": SymbolType.ROUTE.value,
                "name": f"{route.http_method} {route.path}",
                "qualified_name": route_qname,
                "display_name": f"{route.http_method} {route.path}",
                "parent_symbol_id": parent_id,
                "module_name": None,
                "namespace": route.framework,
                "signature": f"{route.http_method} {route.path} → {route.handler_name}",
                "return_type": None,
                "visibility": Visibility.PUBLIC.value,
                "is_static": False,
                "is_async": False,
                "is_exported": True,
                "is_deprecated": False,
                "documentation": None,
                "start_line": route.start_line,
                "end_line": route.start_line,
                "start_column": 0,
                "end_column": 0,
            }
            entries.append(entry)

        return entries

    # ── Generic symbol mapping ─────────────────────────────────────────────────

    def _map_generic_symbols(
        self,
        summary: FileSummary,
        parent_ids: dict[str, uuid.UUID],
        already_mapped: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Map :class:`Symbol` objects not already covered by specialised mappers.

        Symbols whose ``qualified_name`` already appears in ``already_mapped``
        are skipped to avoid duplicates.

        Args:
            summary: Source file parse summary.
            parent_ids: Parent-ID map (read and updated).
            already_mapped: Entries produced by specialised mappers; their
                qualified names are excluded from generic processing.

        Returns:
            list[dict]: Column dicts for remaining symbols.
        """
        covered: set[str] = {e["qualified_name"] for e in already_mapped}
        entries: list[dict[str, Any]] = []

        for sym in summary.symbols:
            qname = self._ensure_qualified_name(
                sym.qualified_name,
                summary.relative_path,
                summary.language,
                sym.symbol_name,
            )
            if qname in covered:
                continue

            entry_id = uuid.uuid4()
            parent_id = self._resolve_parent_id(sym.qualified_name, parent_ids)
            doc = sym.documentation

            entry: dict[str, Any] = {
                "id": entry_id,
                "repository_id": summary.repository_id,
                "file_id": summary.file_id,
                "language": summary.language,
                "symbol_type": sym.symbol_type.value,
                "name": sym.symbol_name,
                "qualified_name": qname,
                "display_name": self._display_name(qname, sym.symbol_name),
                "parent_symbol_id": parent_id,
                "module_name": QualifiedNameValidator.extract_module(qname, sym.symbol_name),
                "namespace": None,
                "signature": sym.signature,
                "return_type": None,
                "visibility": sym.visibility.value,
                "is_static": False,
                "is_async": False,
                "is_exported": self._is_exported(sym.visibility),
                "is_deprecated": self._is_deprecated(doc),
                "documentation": doc,
                "start_line": sym.start_line,
                "end_line": sym.end_line,
                "start_column": 0,
                "end_column": 0,
            }
            entries.append(entry)
            covered.add(qname)
            parent_ids[qname] = entry_id

        return entries

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _ensure_qualified_name(
        existing: str,
        relative_path: str,
        language: str,
        name: str,
    ) -> str:
        """Return ``existing`` if non-empty, otherwise build one from path + name.

        Args:
            existing: The qualified name already computed by the parser.
            relative_path: Relative file path.
            language: Source language.
            name: Short symbol name.

        Returns:
            A non-empty qualified name string.
        """
        if existing and existing.strip():
            return QualifiedNameValidator.normalise(existing)
        return QualifiedNameValidator.build(relative_path, language, name)

    @staticmethod
    def _display_name(qualified_name: str, short_name: str) -> str:
        """Compute a concise display name for UI rendering.

        Uses the last two segments of the qualified name when there are
        multiple segments (e.g. ``"AuthService.login"``), otherwise uses
        the short name.

        Args:
            qualified_name: Fully-qualified name.
            short_name: Unqualified symbol name.

        Returns:
            Display name string.
        """
        parts = qualified_name.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return short_name

    @staticmethod
    def _resolve_parent_id(
        qualified_name: str,
        parent_ids: dict[str, uuid.UUID],
    ) -> uuid.UUID | None:
        """Find the parent symbol UUID by removing the last name segment.

        For a qualified name ``"pkg.MyClass.myMethod"``, the parent is
        ``"pkg.MyClass"``.

        Args:
            qualified_name: Fully-qualified name of the symbol.
            parent_ids: Map of known qualified_name → UUID.

        Returns:
            Parent UUID if found, otherwise ``None``.
        """
        if not qualified_name:
            return None
        parts = qualified_name.split(".")
        if len(parts) <= 1:
            return None
        parent_qname = ".".join(parts[:-1])
        return parent_ids.get(parent_qname)

    @staticmethod
    def _is_exported(visibility: Visibility) -> bool:
        """Return True when the visibility level implies the symbol is exported.

        Args:
            visibility: Parser-domain visibility value.

        Returns:
            bool: True for public visibility.
        """
        return visibility == Visibility.PUBLIC

    @staticmethod
    def _is_deprecated(documentation: str | None) -> bool:
        """Return True when the documentation contains a deprecation marker.

        Args:
            documentation: Extracted docstring text or ``None``.

        Returns:
            bool: True when a deprecation marker is found.
        """
        if not documentation:
            return False
        return any(marker in documentation for marker in _DEPRECATION_MARKERS)
