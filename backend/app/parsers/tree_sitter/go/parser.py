"""Go tree-sitter parser implementation.

Parses Go source files and extracts:
- Structs, interfaces, type declarations
- Functions and methods (with receiver types)
- Import declarations (single and grouped)
- Call expressions
- HTTP routes for Gin and Echo frameworks
- Go doc comments
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

_LANG = get_language("go")
_PARSER = get_parser("go")

_GIN_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "Any"}
_ECHO_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}
_HTTP_HANDLE_FUNCS = {"HandleFunc", "Handle", "HandleFuncWithOptions"}


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


def _go_visibility(name: str) -> Visibility:
    """Go exported names start with uppercase."""
    if name and name[0].isupper():
        return Visibility.PUBLIC
    return Visibility.INTERNAL


def _strip_go_doc(raw: str) -> str:
    """Strip // or /* */ from Go doc comments."""
    lines = raw.strip().splitlines()
    result: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("//"):
            result.append(stripped[2:].strip())
        elif stripped.startswith("/*"):
            result.append(stripped[2:].strip("*/ "))
        else:
            result.append(stripped)
    return "\n".join(ln for ln in result if ln).strip()


class GoParser(CodeParser):
    """Tree-sitter based parser for Go source files.

    Handles Go module syntax, struct types, interfaces, goroutines,
    and Gin/Echo/standard-library HTTP route detection.
    """

    language = "Go"
    extensions = ["go"]

    # ── extract_symbols ───────────────────────────────────────────────────────

    def extract_symbols(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[Symbol]:
        """Extract all named symbols from Go source.

        Args:
            source: Go source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`Symbol` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        symbols: list[Symbol] = []

        for node in _find_nodes(tree.root_node, "type_declaration"):
            for spec in _find_nodes(node, "type_spec"):
                name_node = spec.child_by_field_name("name")
                type_node = spec.child_by_field_name("type")
                if not name_node:
                    continue
                name = _text(name_node, src)
                if type_node and type_node.type == "struct_type":
                    stype = SymbolType.STRUCT
                elif type_node and type_node.type == "interface_type":
                    stype = SymbolType.INTERFACE
                else:
                    stype = SymbolType.CLASS
                symbols.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=name,
                    symbol_type=stype,
                    visibility=_go_visibility(name),
                    start_line=_line(spec), end_line=_end_line(spec),
                    language=self.language,
                ))

        for node in _find_nodes(tree.root_node, "function_declaration", "method_declaration"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)
            receiver = self._receiver_type(node, src)
            qname = f"({receiver}).{name}" if receiver else name
            stype = SymbolType.METHOD if receiver else SymbolType.FUNCTION
            symbols.append(Symbol(
                repository_id=repository_id, file_id=file_id,
                symbol_name=name, qualified_name=qname,
                symbol_type=stype,
                visibility=_go_visibility(name),
                start_line=_line(node), end_line=_end_line(node),
                language=self.language,
                parent_symbol=receiver,
            ))

        for node in _find_nodes(tree.root_node, "var_declaration", "const_declaration"):
            stype = SymbolType.CONSTANT if node.type == "const_declaration" else SymbolType.VARIABLE
            for spec in _find_nodes(node, "var_spec", "const_spec"):
                for child in spec.children:
                    if child.type == "identifier":
                        name = _text(child, src)
                        symbols.append(Symbol(
                            repository_id=repository_id, file_id=file_id,
                            symbol_name=name, qualified_name=name,
                            symbol_type=stype,
                            visibility=_go_visibility(name),
                            start_line=_line(spec), end_line=_end_line(spec),
                            language=self.language,
                        ))
                        break

        return symbols

    def _receiver_type(self, node, src: bytes) -> str | None:
        """Extract receiver type name from a method declaration."""
        receiver_node = node.child_by_field_name("receiver")
        if not receiver_node:
            return None
        for child in _find_nodes(receiver_node, "parameter_declaration"):
            type_node = child.child_by_field_name("type")
            if type_node:
                t = _text(type_node, src).lstrip("*")
                return t
        return None

    # ── extract_imports ───────────────────────────────────────────────────────

    def extract_imports(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ImportStatement]:
        """Extract import declarations including grouped imports.

        Args:
            source: Go source code.
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
            for spec in _find_nodes(node, "import_spec"):
                path_node = spec.child_by_field_name("path")
                if not path_node:
                    continue
                module_path = _text(path_node, src).strip("'\" ")
                name_node = spec.child_by_field_name("name")
                alias = _text(name_node, src) if name_node else None
                imports.append(ImportStatement(
                    repository_id=repository_id, file_id=file_id,
                    module_path=module_path, alias=alias,
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
        """Extract call expressions from Go source.

        Args:
            source: Go source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`CallReference` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        calls: list[CallReference] = []
        seen: set[tuple] = set()

        for node in _find_nodes(tree.root_node, "call_expression"):
            fn_node = node.child_by_field_name("function")
            if not fn_node:
                continue
            line = _line(node)

            if fn_node.type == "selector_expression":
                obj = fn_node.child_by_field_name("operand")
                field = fn_node.child_by_field_name("field")
                callee = _text(field, src) if field else ""
                obj_name = _text(obj, src) if obj else None
            elif fn_node.type == "identifier":
                callee = _text(fn_node, src)
                obj_name = None
            else:
                continue

            caller = self._enclosing_func(node, src) or "<package>"
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

    def _enclosing_func(self, node, src: bytes) -> str | None:
        cur = node.parent
        while cur:
            if cur.type in ("function_declaration", "method_declaration"):
                n = cur.child_by_field_name("name")
                if n:
                    if cur.type == "method_declaration":
                        receiver = self._receiver_type(cur, src)
                        method = _text(n, src)
                        return f"({receiver}).{method}" if receiver else method
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
        """Extract struct and interface type declarations.

        Args:
            source: Go source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ClassDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        classes: list[ClassDefinition] = []

        for node in _find_nodes(tree.root_node, "type_declaration"):
            for spec in _find_nodes(node, "type_spec"):
                name_node = spec.child_by_field_name("name")
                type_node = spec.child_by_field_name("type")
                if not name_node or not type_node:
                    continue
                if type_node.type not in ("struct_type", "interface_type"):
                    continue
                name = _text(name_node, src)

                # Embedded types (base classes in Go)
                bases: list[str] = []
                if type_node.type == "struct_type":
                    for field in _find_nodes(type_node, "field_declaration"):
                        # Embedded fields have no tag and no explicit name
                        type_child = field.child_by_field_name("type")
                        name_children = [
                            c for c in field.children
                            if c.type == "field_identifier"
                        ]
                        if type_child and not name_children:
                            bases.append(_text(type_child, src).lstrip("*"))

                doc = self._preceding_doc_comment(node, src)
                classes.append(ClassDefinition(
                    repository_id=repository_id, file_id=file_id,
                    class_name=name, qualified_name=name,
                    base_classes=bases, interfaces=[],
                    visibility=_go_visibility(name),
                    start_line=_line(spec), end_line=_end_line(spec),
                    language=self.language, documentation=doc,
                ))

        return classes

    def _preceding_doc_comment(self, node, src: bytes) -> str | None:
        """Return Go doc comment immediately preceding a declaration node."""
        parent = node.parent
        if not parent:
            return None
        try:
            idx = parent.children.index(node)
        except ValueError:
            return None
        doc_lines: list[str] = []
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "comment":
                raw = _text(sib, src)
                doc_lines.insert(0, raw.lstrip("/ ").strip())
            else:
                break
        return "\n".join(doc_lines).strip() if doc_lines else None

    # ── extract_functions ─────────────────────────────────────────────────────

    def extract_functions(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[FunctionDefinition]:
        """Extract function and method declarations with full metadata.

        Args:
            source: Go source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`FunctionDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        functions: list[FunctionDefinition] = []

        for node in _find_nodes(
            tree.root_node, "function_declaration", "method_declaration"
        ):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)
            receiver = self._receiver_type(node, src)
            is_method = receiver is not None
            qname = f"({receiver}).{name}" if receiver else name

            # Parameters
            params_node = node.child_by_field_name("parameters")
            params: list[str] = []
            if params_node:
                for child in params_node.children:
                    if child.type in ("parameter_declaration", "variadic_parameter_declaration"):
                        params.append(_text(child, src))

            # Return type
            result_node = node.child_by_field_name("result")
            ret_type = _text(result_node, src) if result_node else None

            doc = self._preceding_doc_comment(node, src)
            sig = f"func {'(' + receiver + ') ' if receiver else ''}{name}({', '.join(params)})"
            if ret_type:
                sig += f" {ret_type}"

            functions.append(FunctionDefinition(
                repository_id=repository_id, file_id=file_id,
                function_name=name, qualified_name=qname,
                is_method=is_method,
                visibility=_go_visibility(name),
                parameters=params, return_type=ret_type,
                start_line=_line(node), end_line=_end_line(node),
                language=self.language, documentation=doc,
                signature=sig,
            ))

        return functions

    # ── extract_comments ──────────────────────────────────────────────────────

    def extract_comments(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CommentBlock]:
        """Extract Go doc comments and inline comments.

        Args:
            source: Go source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`CommentBlock` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        comments: list[CommentBlock] = []

        for node in _find_nodes(tree.root_node, "comment"):
            raw = _text(node, src)
            if raw.startswith("/*"):
                ctype, text = "block", raw[2:-2].strip()
            else:
                ctype, text = "line", raw.lstrip("/ ").strip()

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
        """Detect Gin, Echo, and net/http route registrations.

        Patterns:
        - ``r.GET("/path", handler)``       (Gin)
        - ``e.GET("/path", handler)``       (Echo)
        - ``http.HandleFunc("/path", ...)`` (net/http)
        - ``mux.Handle("/path", ...)``      (net/http ServeMux)

        Args:
            source: Go source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`RouteDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        routes: list[RouteDefinition] = []

        for node in _find_nodes(tree.root_node, "call_expression"):
            fn_node = node.child_by_field_name("function")
            if not fn_node:
                continue

            if fn_node.type == "selector_expression":
                field = fn_node.child_by_field_name("field")
                if not field:
                    continue
                method_name = _text(field, src)
                http_method = method_name.upper()

                if http_method in _GIN_METHODS or http_method in _ECHO_METHODS:
                    args_node = node.child_by_field_name("arguments")
                    if not args_node:
                        # Go uses "argument_list" field name
                        args_node = node.child_by_field_name("argument_list")
                    if not args_node:
                        continue
                    arg_children = [
                        c for c in args_node.children
                        if c.type not in (",", "(", ")")
                    ]
                    if not arg_children:
                        continue
                    first = arg_children[0]
                    if first.type not in ("interpreted_string_literal", "raw_string_literal"):
                        continue
                    path = _text(first, src).strip('"`')
                    handler = ""
                    if len(arg_children) > 1:
                        handler = _text(arg_children[-1], src)

                    obj = fn_node.child_by_field_name("operand")
                    obj_name = _text(obj, src) if obj else ""
                    # Differentiate Gin vs Echo by common variable names
                    framework = "gin" if obj_name.lower() in ("r", "router", "group") else "echo"

                    routes.append(RouteDefinition(
                        repository_id=repository_id, file_id=file_id,
                        http_method=http_method, path=path,
                        handler_name=handler, framework=framework,
                        start_line=_line(node), language=self.language,
                    ))

                elif method_name in _HTTP_HANDLE_FUNCS:
                    # net/http style
                    args_node = node.child_by_field_name("arguments")
                    if not args_node:
                        args_node = node.child_by_field_name("argument_list")
                    if not args_node:
                        continue
                    arg_children = [
                        c for c in args_node.children
                        if c.type not in (",", "(", ")")
                    ]
                    if not arg_children:
                        continue
                    path = _text(arg_children[0], src).strip('"`')
                    handler = _text(arg_children[1], src) if len(arg_children) > 1 else ""
                    routes.append(RouteDefinition(
                        repository_id=repository_id, file_id=file_id,
                        http_method="GET", path=path,
                        handler_name=handler, framework="net/http",
                        start_line=_line(node), language=self.language,
                    ))

        return routes
