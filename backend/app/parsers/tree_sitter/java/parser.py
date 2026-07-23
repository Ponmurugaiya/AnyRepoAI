"""Java tree-sitter parser implementation.

Parses Java source files and extracts:
- Classes, abstract classes, interfaces, enums, annotations
- Methods and constructors with full access modifier resolution
- Import statements (single-type and on-demand)
- Call expressions
- Spring Boot @RequestMapping, @GetMapping, @PostMapping routes
- JavaDoc comment blocks
"""

from __future__ import annotations

import re
import uuid

from tree_sitter_languages import get_language, get_parser

from backend.app.core.logging import get_logger
from backend.app.parsers.base.parser import CodeParser
from backend.app.parsers.models.symbols import (
    CallReference,
    ClassDefinition,
    CommentBlock,
    FunctionDefinition,
    ImportStatement,
    RouteDefinition,
    Symbol,
    SymbolType,
    Visibility,
)

logger = get_logger(__name__)

_LANG = get_language("java")
_PARSER = get_parser("java")

_SPRING_ROUTE_ANNOTATIONS = {
    "RequestMapping", "GetMapping", "PostMapping",
    "PutMapping", "DeleteMapping", "PatchMapping",
}
_SPRING_METHOD_MAP = {
    "GetMapping": "GET", "PostMapping": "POST",
    "PutMapping": "PUT", "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH", "RequestMapping": "GET",
}
_ACCESS_MODS = {"public", "private", "protected"}


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _line(node) -> int:
    return node.start_point[0] + 1


def _end_line(node) -> int:
    return node.end_point[0] + 1


def _find_nodes(node, *types):
    if node.type in types:
        yield node
    for child in node.children:
        yield from _find_nodes(child, *types)


def _collect_modifiers(node, src: bytes) -> list[str]:
    mods: list[str] = []
    for child in node.children:
        if child.type in ("modifiers",):
            for sub in child.children:
                if sub.type in (
                    "public", "private", "protected",
                    "static", "final", "abstract",
                    "synchronized", "native", "transient",
                    "volatile", "strictfp",
                ):
                    mods.append(_text(sub, src))
    return mods


def _java_visibility(modifiers: list[str]) -> Visibility:
    for m in modifiers:
        if m == "private":
            return Visibility.PRIVATE
        if m == "protected":
            return Visibility.PROTECTED
        if m == "public":
            return Visibility.PUBLIC
    return Visibility.INTERNAL  # package-private


def _strip_javadoc(raw: str) -> str:
    text = raw.strip()
    if text.startswith("/**"):
        text = text[3:]
    elif text.startswith("/*"):
        text = text[2:]
    if text.endswith("*/"):
        text = text[:-2]
    lines = [ln.lstrip().lstrip("*").strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


class JavaParser(CodeParser):
    """Tree-sitter based parser for Java source files.

    Handles Java 8-21 syntax including records, sealed classes,
    and annotation declarations.
    """

    language = "Java"
    extensions = ["java"]

    # ── extract_symbols ───────────────────────────────────────────────────────

    def extract_symbols(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[Symbol]:
        """Extract all named symbols from Java source.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`Symbol` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        symbols: list[Symbol] = []
        self._collect(tree.root_node, src, file_id, repository_id, symbols, None)
        return symbols

    def _collect(self, node, src, file_id, repository_id, out, parent):
        t = node.type

        if t in (
            "class_declaration", "interface_declaration",
            "enum_declaration", "annotation_type_declaration",
            "record_declaration",
        ):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                mods = _collect_modifiers(node, src)
                type_map = {
                    "class_declaration": SymbolType.CLASS,
                    "interface_declaration": SymbolType.INTERFACE,
                    "enum_declaration": SymbolType.ENUM,
                    "annotation_type_declaration": SymbolType.ANNOTATION,
                    "record_declaration": SymbolType.STRUCT,
                }
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=type_map.get(t, SymbolType.CLASS),
                    visibility=_java_visibility(mods),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                    signature=f"class {name}",
                ))
                body = node.child_by_field_name("body")
                if body:
                    self._collect(body, src, file_id, repository_id, out, qname)
                return

        if t == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                mods = _collect_modifiers(node, src)
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.METHOD,
                    visibility=_java_visibility(mods),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                ))

        if t == "constructor_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                mods = _collect_modifiers(node, src)
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.CONSTRUCTOR,
                    visibility=_java_visibility(mods),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                ))

        if t == "field_declaration":
            mods = _collect_modifiers(node, src)
            is_const = "final" in mods and "static" in mods
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        name = _text(name_node, src)
                        qname = f"{parent}.{name}" if parent else name
                        out.append(Symbol(
                            repository_id=repository_id, file_id=file_id,
                            symbol_name=name, qualified_name=qname,
                            symbol_type=SymbolType.CONSTANT if is_const else SymbolType.VARIABLE,
                            visibility=_java_visibility(mods),
                            start_line=_line(node), end_line=_end_line(node),
                            language=self.language, parent_symbol=parent,
                        ))

        for child in node.children:
            self._collect(child, src, file_id, repository_id, out, parent)

    # ── extract_imports ───────────────────────────────────────────────────────

    def extract_imports(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ImportStatement]:
        """Extract Java import declarations.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ImportStatement` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        imports: list[ImportStatement] = []

        for node in _find_nodes(tree.root_node, "import_declaration"):
            line = _line(node)
            # Collect all identifier/scoped parts
            parts: list[str] = []
            is_wildcard = False
            for child in node.children:
                if child.type == "scoped_identifier":
                    parts.append(_text(child, src))
                elif child.type == "identifier":
                    parts.append(_text(child, src))
                elif child.type == "asterisk":
                    is_wildcard = True

            module_path = ".".join(parts)
            names = ["*"] if is_wildcard else []

            imports.append(ImportStatement(
                repository_id=repository_id, file_id=file_id,
                module_path=module_path, imported_names=names,
                start_line=line, language=self.language,
            ))

        return imports

    # ── extract_calls ─────────────────────────────────────────────────────────

    def extract_calls(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CallReference]:
        """Extract method invocation expressions from Java source.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`CallReference` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        calls: list[CallReference] = []
        seen: set[tuple] = set()

        for node in _find_nodes(tree.root_node, "method_invocation"):
            line = _line(node)
            name_node = node.child_by_field_name("name")
            obj_node = node.child_by_field_name("object")
            if not name_node:
                continue

            callee = _text(name_node, src)
            obj_name = _text(obj_node, src) if obj_node else None
            caller = self._enclosing_method(node, src) or "<class>"
            key = (caller, callee, line)
            if key in seen:
                continue
            seen.add(key)

            calls.append(CallReference(
                repository_id=repository_id, file_id=file_id,
                caller_name=caller, callee_name=callee,
                callee_object=obj_name, start_line=line,
                language=self.language,
            ))

        return calls

    def _enclosing_method(self, node, src: bytes) -> str | None:
        cur = node.parent
        while cur:
            if cur.type in ("method_declaration", "constructor_declaration"):
                n = cur.child_by_field_name("name")
                if n:
                    cls = self._enclosing_class(cur, src)
                    method = _text(n, src)
                    return f"{cls}.{method}" if cls else method
            cur = cur.parent
        return None

    def _enclosing_class(self, node, src: bytes) -> str | None:
        cur = node.parent
        while cur:
            if cur.type in ("class_declaration", "interface_declaration", "enum_declaration"):
                n = cur.child_by_field_name("name")
                if n:
                    return _text(n, src)
            cur = cur.parent
        return None

    # ── extract_classes ───────────────────────────────────────────────────────

    def extract_classes(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ClassDefinition]:
        """Extract class, interface, enum, and record declarations.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ClassDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        classes: list[ClassDefinition] = []

        for node in _find_nodes(
            tree.root_node,
            "class_declaration", "interface_declaration",
            "enum_declaration", "record_declaration",
        ):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)
            mods = _collect_modifiers(node, src)
            is_abstract = "abstract" in mods

            bases: list[str] = []
            ifaces: list[str] = []
            for child in node.children:
                if child.type == "superclass":
                    for sub in child.children:
                        if sub.type in ("type_identifier", "generic_type"):
                            bases.append(_text(sub, src))
                elif child.type == "super_interfaces":
                    for sub in _find_nodes(child, "type_identifier", "generic_type"):
                        ifaces.append(_text(sub, src))

            doc = self._preceding_javadoc(node, src)
            annotations = self._preceding_annotations(node, src)
            parent_name = self._enclosing_class(node, src)
            qname = f"{parent_name}.{name}" if parent_name else name

            classes.append(ClassDefinition(
                repository_id=repository_id, file_id=file_id,
                class_name=name, qualified_name=qname,
                base_classes=bases, interfaces=ifaces,
                visibility=_java_visibility(mods),
                is_abstract=is_abstract,
                start_line=_line(node), end_line=_end_line(node),
                language=self.language, documentation=doc,
                decorators=annotations,
            ))

        return classes

    def _preceding_javadoc(self, node, src: bytes) -> str | None:
        parent = node.parent
        if not parent:
            return None
        try:
            idx = parent.children.index(node)
        except ValueError:
            return None
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "block_comment":
                raw = _text(sib, src)
                if raw.startswith("/**"):
                    return _strip_javadoc(raw)
            elif sib.type not in ("line_comment", "block_comment", "modifiers"):
                break
        return None

    def _preceding_annotations(self, node, src: bytes) -> list[str]:
        names: list[str] = []
        for child in node.children:
            if child.type == "modifiers":
                for sub in child.children:
                    if sub.type == "marker_annotation" or sub.type == "annotation":
                        n = sub.child_by_field_name("name")
                        if n:
                            names.append(_text(n, src))
        return names

    # ── extract_functions ─────────────────────────────────────────────────────

    def extract_functions(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[FunctionDefinition]:
        """Extract method and constructor declarations with full metadata.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`FunctionDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        functions: list[FunctionDefinition] = []

        for node in _find_nodes(
            tree.root_node, "method_declaration", "constructor_declaration"
        ):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)
            mods = _collect_modifiers(node, src)
            is_ctor = node.type == "constructor_declaration"
            is_static = "static" in mods
            is_abstract = "abstract" in mods

            # Parameters
            params_node = node.child_by_field_name("parameters")
            params: list[str] = []
            if params_node:
                for child in params_node.children:
                    if child.type in (
                        "formal_parameter", "spread_parameter",
                        "receiver_parameter",
                    ):
                        params.append(_text(child, src))

            # Return type
            ret_node = node.child_by_field_name("type")
            ret_type = _text(ret_node, src) if ret_node else None

            parent_class = self._enclosing_class(node, src)
            qname = f"{parent_class}.{name}" if parent_class else name
            doc = self._preceding_javadoc(node, src)
            annotations = self._preceding_annotations(node, src)

            sig_parts = [
                " ".join(mods),
                ret_type or "",
                f"{name}({', '.join(params)})",
            ]
            sig = " ".join(p for p in sig_parts if p).strip()

            functions.append(FunctionDefinition(
                repository_id=repository_id, file_id=file_id,
                function_name=name, qualified_name=qname,
                is_method=not is_ctor, is_constructor=is_ctor,
                is_static=is_static,
                visibility=_java_visibility(mods),
                parameters=params, return_type=ret_type,
                start_line=_line(node), end_line=_end_line(node),
                language=self.language, documentation=doc,
                decorators=annotations, signature=sig,
            ))

        return functions

    # ── extract_comments ──────────────────────────────────────────────────────

    def extract_comments(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CommentBlock]:
        """Extract JavaDoc and inline comments.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`CommentBlock` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        comments: list[CommentBlock] = []

        for node in _find_nodes(tree.root_node, "block_comment", "line_comment"):
            raw = _text(node, src)
            if node.type == "block_comment":
                if raw.startswith("/**"):
                    ctype, text = "javadoc", _strip_javadoc(raw)
                else:
                    ctype, text = "block", raw[2:-2].strip()
            else:
                ctype, text = "line", raw.lstrip("/").strip()

            comments.append(CommentBlock(
                repository_id=repository_id, file_id=file_id,
                comment_text=text, comment_type=ctype,
                start_line=_line(node), end_line=_end_line(node),
                language=self.language,
            ))

        return comments

    # ── extract_routes ────────────────────────────────────────────────────────

    def extract_routes(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[RouteDefinition]:
        """Detect Spring Boot route annotations on methods and classes.

        Recognises: @GetMapping, @PostMapping, @PutMapping,
        @DeleteMapping, @PatchMapping, @RequestMapping.

        Args:
            source: Java source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`RouteDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        routes: list[RouteDefinition] = []

        for node in _find_nodes(tree.root_node, "method_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            method_name = _text(name_node, src)
            parent_class = self._enclosing_class(node, src)
            qname = f"{parent_class}.{method_name}" if parent_class else method_name

            annotations = self._get_annotation_nodes(node, src)
            for ann_name, ann_args in annotations:
                if ann_name in _SPRING_ROUTE_ANNOTATIONS:
                    http_method = _SPRING_METHOD_MAP.get(ann_name, "GET")
                    # Check for method attribute in @RequestMapping
                    method_attr = re.search(r'method\s*=\s*RequestMethod\.(\w+)', ann_args)
                    if method_attr:
                        http_method = method_attr.group(1).upper()
                    # Extract path
                    path_match = re.search(r'["\']([^"\']+)["\']', ann_args)
                    path = path_match.group(1) if path_match else "/"

                    routes.append(RouteDefinition(
                        repository_id=repository_id, file_id=file_id,
                        http_method=http_method, path=path,
                        handler_name=qname, framework="spring",
                        start_line=_line(node), language=self.language,
                    ))

        return routes

    def _get_annotation_nodes(self, node, src: bytes) -> list[tuple[str, str]]:
        """Return (annotation_name, annotation_args_text) tuples for a node."""
        result: list[tuple[str, str]] = []
        for child in node.children:
            if child.type == "modifiers":
                for sub in child.children:
                    if sub.type in ("marker_annotation", "annotation"):
                        n = sub.child_by_field_name("name")
                        args = sub.child_by_field_name("arguments")
                        if n:
                            result.append((
                                _text(n, src),
                                _text(args, src) if args else "",
                            ))
        return result
