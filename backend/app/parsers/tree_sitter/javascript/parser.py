"""JavaScript tree-sitter parser implementation.

Parses JavaScript (ES6+, JSX) source files and extracts:
- Classes, functions, arrow functions, methods
- Import/export/require statements
- Call references
- HTTP routes (Express.js, NestJS decorators)
- JSDoc comment blocks
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

_LANG = get_language("javascript")
_PARSER = get_parser("javascript")

_EXPRESS_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "all", "use"}
_NEST_HTTP = {"Get", "Post", "Put", "Delete", "Patch", "Options", "Head"}


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


def _strip_jsdoc(raw: str) -> str:
    """Strip /** ... */ markers and leading * from JSDoc."""
    text = raw.strip()
    if text.startswith("/**"):
        text = text[3:]
    if text.endswith("*/"):
        text = text[:-2]
    lines = [ln.lstrip().lstrip("*").strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()

def _js_visibility(name: str) -> Visibility:
    """Infer visibility from JS/TS naming conventions."""
    if name.startswith("_"):
        return Visibility.PRIVATE
    return Visibility.PUBLIC


class JavaScriptParser(CodeParser):
    """Tree-sitter based parser for JavaScript source files.

    Handles ES6 modules, CommonJS require(), class syntax,
    arrow functions, and Express/NestJS route detection.
    """

    language = "JavaScript"
    extensions = ["js", "jsx", "mjs", "cjs"]

    # ── extract_symbols ───────────────────────────────────────────────────────

    def extract_symbols(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[Symbol]:
        """Extract all named symbols from JavaScript source.

        Args:
            source: JavaScript source code.
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
        """Recursively collect symbols from AST."""
        t = node.type

        if t == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.CLASS,
                    visibility=_js_visibility(name),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                    signature=f"class {name}",
                ))
                body = node.child_by_field_name("body")
                if body:
                    self._collect(body, src, file_id, repository_id, out, qname)
                return

        if t == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                stype = SymbolType.CONSTRUCTOR if name == "constructor" else SymbolType.METHOD
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=stype, visibility=_js_visibility(name),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                ))

        if t == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.FUNCTION,
                    visibility=_js_visibility(name),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                ))

        if t == "lexical_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    val_node = child.child_by_field_name("value")
                    if name_node:
                        name = _text(name_node, src)
                        is_fn = val_node and val_node.type in (
                            "arrow_function", "function_expression"
                        )
                        stype = SymbolType.FUNCTION if is_fn else (
                            SymbolType.CONSTANT if any(
                                c.type == "const" for c in node.children
                            ) else SymbolType.VARIABLE
                        )
                        qname = f"{parent}.{name}" if parent else name
                        out.append(Symbol(
                            repository_id=repository_id, file_id=file_id,
                            symbol_name=name, qualified_name=qname,
                            symbol_type=stype, visibility=_js_visibility(name),
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
        """Extract ES6 imports and CommonJS require() calls.

        Args:
            source: JavaScript source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ImportStatement` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        imports: list[ImportStatement] = []

        for node in _find_nodes(tree.root_node, "import_statement"):
            line = _line(node)
            module_node = node.child_by_field_name("source")
            if not module_node:
                continue
            module_path = _text(module_node, src).strip("'\"")
            names: list[str] = []
            for child in node.children:
                if child.type == "import_clause":
                    for sub in child.children:
                        if sub.type == "identifier":
                            names.append(_text(sub, src))
                        elif sub.type == "named_imports":
                            for item in sub.children:
                                if item.type == "import_specifier":
                                    n = item.child_by_field_name("name")
                                    if n:
                                        names.append(_text(n, src))
                        elif sub.type == "namespace_import":
                            for item in sub.children:
                                if item.type == "identifier":
                                    names.append(f"* as {_text(item, src)}")
            imports.append(ImportStatement(
                repository_id=repository_id, file_id=file_id,
                module_path=module_path, imported_names=names,
                start_line=line, language=self.language,
            ))

        # CommonJS: const x = require("module")
        for node in _find_nodes(tree.root_node, "call_expression"):
            fn = node.child_by_field_name("function")
            if fn and _text(fn, src) == "require":
                args = node.child_by_field_name("arguments")
                if args:
                    for child in args.children:
                        if child.type == "string":
                            module_path = _text(child, src).strip("'\"")
                            imports.append(ImportStatement(
                                repository_id=repository_id, file_id=file_id,
                                module_path=module_path,
                                start_line=_line(node),
                                language=self.language,
                            ))
                            break

        return imports

    # ── extract_calls ─────────────────────────────────────────────────────────

    def extract_calls(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CallReference]:
        """Extract call expressions from JavaScript source.

        Args:
            source: JavaScript source code.
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
            fn = node.child_by_field_name("function")
            if not fn:
                continue
            line = _line(node)

            if fn.type == "member_expression":
                obj = fn.child_by_field_name("object")
                prop = fn.child_by_field_name("property")
                callee = _text(prop, src) if prop else ""
                obj_name = _text(obj, src) if obj else None
            elif fn.type == "identifier":
                callee = _text(fn, src)
                obj_name = None
            else:
                continue

            caller = self._enclosing_fn(node, src) or "<module>"
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

    def _enclosing_fn(self, node, src: bytes) -> str | None:
        """Walk AST upward to find enclosing function/method name."""
        cur = node.parent
        while cur:
            if cur.type in (
                "function_declaration", "function_expression",
                "arrow_function", "method_definition",
            ):
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
        """Extract class declarations with inheritance metadata.

        Args:
            source: JavaScript source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ClassDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        classes: list[ClassDefinition] = []

        for node in _find_nodes(tree.root_node, "class_declaration", "class"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)

            bases: list[str] = []
            for child in node.children:
                if child.type == "class_heritage":
                    for sub in child.children:
                        if sub.type in ("identifier", "member_expression"):
                            bases.append(_text(sub, src))

            doc = self._preceding_jsdoc(node, src)
            classes.append(ClassDefinition(
                repository_id=repository_id, file_id=file_id,
                class_name=name, qualified_name=name,
                base_classes=bases, interfaces=[],
                visibility=_js_visibility(name),
                start_line=_line(node), end_line=_end_line(node),
                language=self.language, documentation=doc,
            ))

        return classes

    def _preceding_jsdoc(self, node, src: bytes) -> str | None:
        """Look for a /** ... */ comment immediately before a node."""
        parent = node.parent
        if not parent:
            return None
        idx = parent.children.index(node)
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "comment":
                raw = _text(sib, src)
                if raw.startswith("/**"):
                    return _strip_jsdoc(raw)
            elif sib.type not in ("comment",):
                break
        return None

    # ── extract_functions ─────────────────────────────────────────────────────

    def extract_functions(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[FunctionDefinition]:
        """Extract function declarations, expressions, and arrow functions.

        Args:
            source: JavaScript source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`FunctionDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        functions: list[FunctionDefinition] = []

        for node in _find_nodes(
            tree.root_node,
            "function_declaration", "function_expression",
            "arrow_function", "method_definition",
        ):
            name = self._function_name(node, src)
            if not name:
                continue

            is_async = any(c.type == "async" for c in node.children)
            is_method = node.type == "method_definition"
            is_ctor = name == "constructor"
            params = self._extract_params(node, src)
            sig = f"{'async ' if is_async else ''}function {name}({', '.join(params)})"
            doc = self._preceding_jsdoc(node, src)
            parent_class = self._parent_class(node, src)
            qname = f"{parent_class}.{name}" if parent_class else name

            functions.append(FunctionDefinition(
                repository_id=repository_id, file_id=file_id,
                function_name=name, qualified_name=qname,
                is_method=is_method, is_constructor=is_ctor,
                is_async=is_async, visibility=_js_visibility(name),
                parameters=params, start_line=_line(node),
                end_line=_end_line(node), language=self.language,
                documentation=doc, signature=sig,
            ))

        return functions

    def _function_name(self, node, src: bytes) -> str | None:
        """Extract function name from various function node types."""
        name_node = node.child_by_field_name("name")
        if name_node:
            return _text(name_node, src)
        # Arrow functions assigned to variables: const foo = () => {}
        parent = node.parent
        if parent and parent.type == "variable_declarator":
            n = parent.child_by_field_name("name")
            if n:
                return _text(n, src)
        return None

    def _extract_params(self, node, src: bytes) -> list[str]:
        """Extract parameter names from a function node."""
        params_node = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
        if not params_node:
            return []
        return [
            _text(c, src)
            for c in params_node.children
            if c.type in (
                "identifier", "assignment_pattern", "rest_pattern",
                "object_pattern", "array_pattern",
            )
        ]

    def _parent_class(self, node, src: bytes) -> str | None:
        """Return the name of the nearest enclosing class."""
        cur = node.parent
        while cur:
            if cur.type in ("class_declaration", "class"):
                n = cur.child_by_field_name("name")
                if n:
                    return _text(n, src)
            cur = cur.parent
        return None

    # ── extract_comments ──────────────────────────────────────────────────────

    def extract_comments(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CommentBlock]:
        """Extract JSDoc and inline comments.

        Args:
            source: JavaScript source code.
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
            if raw.startswith("/**"):
                ctype = "jsdoc"
                text = _strip_jsdoc(raw)
            elif raw.startswith("/*"):
                ctype = "block"
                text = raw[2:-2].strip()
            else:
                ctype = "line"
                text = raw.lstrip("/").strip()

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
        """Detect Express.js route registrations.

        Recognises patterns like:
        - ``app.get('/path', handler)``
        - ``router.post('/path', handler)``
        - ``app.use('/path', router)``

        Args:
            source: JavaScript source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`RouteDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        routes: list[RouteDefinition] = []

        for node in _find_nodes(tree.root_node, "call_expression"):
            fn = node.child_by_field_name("function")
            if not fn or fn.type != "member_expression":
                continue

            prop = fn.child_by_field_name("property")
            if not prop:
                continue
            method_name = _text(prop, src).lower()
            if method_name not in _EXPRESS_METHODS:
                continue

            args = node.child_by_field_name("arguments")
            if not args:
                continue

            arg_children = [
                c for c in args.children
                if c.type not in (",", "(", ")")
            ]
            if not arg_children:
                continue

            first = arg_children[0]
            if first.type not in ("string", "template_string"):
                continue
            path = _text(first, src).strip("'\"` ")

            handler = ""
            if len(arg_children) > 1:
                handler = _text(arg_children[-1], src).split("(")[0].strip()

            routes.append(RouteDefinition(
                repository_id=repository_id, file_id=file_id,
                http_method=method_name.upper(),
                path=path, handler_name=handler,
                framework="express",
                start_line=_line(node), language=self.language,
            ))

        return routes
