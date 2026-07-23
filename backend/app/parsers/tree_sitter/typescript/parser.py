"""TypeScript tree-sitter parser implementation.

Extends JavaScript parsing with TypeScript-specific constructs:
- Interface declarations
- Type aliases and enums
- Access modifiers (public/private/protected/readonly)
- Return type annotations
- NestJS decorator-based HTTP routes (@Get, @Post, etc.)
- Generic type parameters
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

_LANG = get_language("typescript")
_PARSER = get_parser("typescript")

_NEST_HTTP_DECORATORS = {
    "get", "post", "put", "delete", "patch", "options", "head", "all",
    "Get", "Post", "Put", "Delete", "Patch", "Options", "Head", "All",
}
_EXPRESS_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "all", "use"}


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
    text = raw.strip()
    if text.startswith("/**"):
        text = text[3:]
    if text.endswith("*/"):
        text = text[:-2]
    lines = [ln.lstrip().lstrip("*").strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _ts_visibility(name: str, modifiers: list[str]) -> Visibility:
    """Determine visibility from TS access modifiers or naming convention."""
    for m in modifiers:
        if m == "private":
            return Visibility.PRIVATE
        if m == "protected":
            return Visibility.PROTECTED
        if m == "public":
            return Visibility.PUBLIC
    if name.startswith("_"):
        return Visibility.PRIVATE
    return Visibility.PUBLIC


def _collect_modifiers(node, src: bytes) -> list[str]:
    """Collect TypeScript access modifier keywords from a node."""
    mods: list[str] = []
    for child in node.children:
        if child.type in (
            "public", "private", "protected", "readonly",
            "static", "abstract", "override", "async",
            "accessibility_modifier",
        ):
            mods.append(_text(child, src))
    return mods


class TypeScriptParser(CodeParser):
    """Tree-sitter based parser for TypeScript source files.

    Inherits JavaScript logic and extends with TypeScript-specific
    constructs including interfaces, enums, access modifiers, and
    NestJS decorator route detection.
    """

    language = "TypeScript"
    extensions = ["ts", "tsx", "d.ts"]

    # ── extract_symbols ───────────────────────────────────────────────────────

    def extract_symbols(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[Symbol]:
        """Extract all named symbols including TS-specific constructs.

        Args:
            source: TypeScript source code.
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

        if t in ("class_declaration", "abstract_class_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.CLASS,
                    visibility=_ts_visibility(name, _collect_modifiers(node, src)),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                    signature=f"class {name}",
                ))
                body = node.child_by_field_name("body")
                if body:
                    self._collect(body, src, file_id, repository_id, out, qname)
                return

        if t == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.INTERFACE,
                    visibility=Visibility.PUBLIC,
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                    signature=f"interface {name}",
                ))
            return

        if t == "enum_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=SymbolType.ENUM,
                    visibility=Visibility.PUBLIC,
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                ))
            return

        if t in ("function_declaration", "method_definition", "method_signature"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _text(name_node, src)
                qname = f"{parent}.{name}" if parent else name
                mods = _collect_modifiers(node, src)
                stype = SymbolType.CONSTRUCTOR if name == "constructor" else (
                    SymbolType.METHOD if parent else SymbolType.FUNCTION
                )
                out.append(Symbol(
                    repository_id=repository_id, file_id=file_id,
                    symbol_name=name, qualified_name=qname,
                    symbol_type=stype,
                    visibility=_ts_visibility(name, mods),
                    start_line=_line(node), end_line=_end_line(node),
                    language=self.language, parent_symbol=parent,
                ))

        if t in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node and name_node.type == "identifier":
                        name = _text(name_node, src)
                        is_const = any(c.type == "const" for c in node.children)
                        qname = f"{parent}.{name}" if parent else name
                        out.append(Symbol(
                            repository_id=repository_id, file_id=file_id,
                            symbol_name=name, qualified_name=qname,
                            symbol_type=SymbolType.CONSTANT if is_const else SymbolType.VARIABLE,
                            visibility=_ts_visibility(name, []),
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
        """Extract ES6/TS import statements.

        Args:
            source: TypeScript source code.
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

        return imports

    # ── extract_calls ─────────────────────────────────────────────────────────

    def extract_calls(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CallReference]:
        """Extract call expressions from TypeScript source.

        Args:
            source: TypeScript source code.
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
        """Extract class and abstract class declarations.

        Args:
            source: TypeScript source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ClassDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        classes: list[ClassDefinition] = []

        for node in _find_nodes(
            tree.root_node, "class_declaration", "abstract_class_declaration"
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
                if child.type == "class_heritage":
                    for sub in child.children:
                        if sub.type == "extends_clause":
                            for item in sub.children:
                                if item.type in ("identifier", "member_expression", "type_identifier"):
                                    bases.append(_text(item, src))
                        elif sub.type == "implements_clause":
                            for item in sub.children:
                                if item.type in ("identifier", "member_expression", "type_identifier", "type_reference"):
                                    ifaces.append(_text(item, src))

            doc = self._preceding_jsdoc(node, src)
            # Decorators may be siblings inside export_statement or direct siblings
            decorators = self._preceding_decorators_for_class(node, src)

            classes.append(ClassDefinition(
                repository_id=repository_id, file_id=file_id,
                class_name=name, qualified_name=name,
                base_classes=bases, interfaces=ifaces,
                visibility=_ts_visibility(name, mods),
                is_abstract=is_abstract,
                start_line=_line(node), end_line=_end_line(node),
                language=self.language, documentation=doc,
                decorators=decorators,
            ))

        return classes

    def _preceding_jsdoc(self, node, src: bytes) -> str | None:
        parent = node.parent
        if not parent:
            return None
        try:
            idx = parent.children.index(node)
        except ValueError:
            return None
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "comment":
                raw = _text(sib, src)
                if raw.startswith("/**"):
                    return _strip_jsdoc(raw)
            else:
                break
        return None

    def _preceding_decorators_for_class(self, node, src: bytes) -> list[str]:
        """Collect @Decorator names preceding a class node.

        Handles two layouts:
        1. Decorator is a sibling of the class_declaration in program scope.
        2. Decorator is a child of export_statement alongside the class.
        """
        parent = node.parent
        if not parent:
            return []

        names: list[str] = []

        # Layout 2: class is inside export_statement
        # Structure: export_statement → [decorator, export, class_declaration]
        if parent.type == "export_statement":
            try:
                idx = parent.children.index(node)
            except ValueError:
                return []
            for i in range(idx - 1, -1, -1):
                sib = parent.children[i]
                if sib.type == "decorator":
                    raw = _text(sib, src).lstrip("@").split("(")[0].strip()
                    names.insert(0, raw)
                elif sib.type not in ("comment", "export"):
                    break
            # Also check siblings of the export_statement itself in the program
            outer_parent = parent.parent
            if outer_parent:
                try:
                    export_idx = outer_parent.children.index(parent)
                    for i in range(export_idx - 1, -1, -1):
                        sib = outer_parent.children[i]
                        if sib.type == "decorator":
                            raw = _text(sib, src).lstrip("@").split("(")[0].strip()
                            names.insert(0, raw)
                        elif sib.type not in ("comment",):
                            break
                except ValueError:
                    pass
            return names

        # Layout 1: class is a direct child of program/class_body
        try:
            idx = parent.children.index(node)
        except ValueError:
            return []
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "decorator":
                raw = _text(sib, src).lstrip("@").split("(")[0].strip()
                names.insert(0, raw)
            elif sib.type not in ("comment",):
                break
        return names

    def _preceding_decorators(self, node, src: bytes) -> list[str]:
        """Collect @Decorator names preceding a non-class node (methods, functions)."""
        parent = node.parent
        if not parent:
            return []
        try:
            idx = parent.children.index(node)
        except ValueError:
            return []
        names: list[str] = []
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "decorator":
                raw = _text(sib, src).lstrip("@").split("(")[0].strip()
                names.insert(0, raw)
            elif sib.type not in ("comment",):
                break
        return names

    # ── extract_functions ─────────────────────────────────────────────────────

    def extract_functions(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[FunctionDefinition]:
        """Extract function definitions with TypeScript type annotations.

        Args:
            source: TypeScript source code.
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
            "function_declaration", "method_definition",
            "arrow_function", "function_expression",
        ):
            name = self._function_name(node, src)
            if not name:
                continue

            mods = _collect_modifiers(node, src)
            is_async = "async" in mods or any(c.type == "async" for c in node.children)
            is_static = "static" in mods
            is_method = node.type == "method_definition"
            is_ctor = name == "constructor"
            params = self._extract_params(node, src)
            ret_type = self._extract_return_type(node, src)
            sig = f"{'async ' if is_async else ''}{name}({', '.join(params)})"
            if ret_type:
                sig += f": {ret_type}"
            parent_class = self._parent_class(node, src)
            qname = f"{parent_class}.{name}" if parent_class else name
            doc = self._preceding_jsdoc(node, src)
            decorators = self._preceding_decorators(node, src)

            functions.append(FunctionDefinition(
                repository_id=repository_id, file_id=file_id,
                function_name=name, qualified_name=qname,
                is_method=is_method, is_constructor=is_ctor,
                is_async=is_async, is_static=is_static,
                visibility=_ts_visibility(name, mods),
                parameters=params, return_type=ret_type,
                start_line=_line(node), end_line=_end_line(node),
                language=self.language, documentation=doc,
                decorators=decorators, signature=sig,
            ))

        return functions

    def _function_name(self, node, src: bytes) -> str | None:
        n = node.child_by_field_name("name")
        if n:
            return _text(n, src)
        parent = node.parent
        if parent and parent.type == "variable_declarator":
            n2 = parent.child_by_field_name("name")
            if n2:
                return _text(n2, src)
        return None

    def _extract_params(self, node, src: bytes) -> list[str]:
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            return []
        result: list[str] = []
        for child in params_node.children:
            if child.type in (
                "required_parameter", "optional_parameter",
                "rest_parameter", "identifier",
            ):
                result.append(_text(child, src))
        return result

    def _extract_return_type(self, node, src: bytes) -> str | None:
        rt = node.child_by_field_name("return_type")
        if rt:
            return _text(rt, src).lstrip(":").strip()
        return None

    def _parent_class(self, node, src: bytes) -> str | None:
        cur = node.parent
        while cur:
            if cur.type in ("class_declaration", "abstract_class_declaration", "class"):
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
        """Extract JSDoc and inline comments from TypeScript source.

        Args:
            source: TypeScript source code.
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
                ctype, text = "jsdoc", _strip_jsdoc(raw)
            elif raw.startswith("/*"):
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
        """Detect NestJS decorator routes and Express.js route registrations.

        NestJS patterns: ``@Get('/path')``, ``@Post('/path')`` on methods.
        Express patterns: ``app.get('/path', handler)``.

        Args:
            source: TypeScript source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`RouteDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        routes: list[RouteDefinition] = []

        # NestJS: @Get('/path') on method_definition
        for node in _find_nodes(tree.root_node, "method_definition"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            handler = _text(name_node, src)
            parent_class = self._parent_class(node, src)
            qname = f"{parent_class}.{handler}" if parent_class else handler
            decorators = self._preceding_decorators(node, src)

            for dec_name in decorators:
                http_method = dec_name.upper()
                if dec_name.lower() in _NEST_HTTP_DECORATORS or http_method in _NEST_HTTP_DECORATORS:
                    # Try to extract path from decorator args
                    path = self._extract_decorator_path(node, dec_name, src)
                    routes.append(RouteDefinition(
                        repository_id=repository_id, file_id=file_id,
                        http_method=http_method,
                        path=path or "/", handler_name=qname,
                        framework="nestjs",
                        start_line=_line(node), language=self.language,
                    ))

        # Express: app.get('/path', ...) / router.post('/path', ...)
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
            arg_children = [c for c in args.children if c.type != ","]
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
                http_method=method_name.upper(), path=path,
                handler_name=handler, framework="express",
                start_line=_line(node), language=self.language,
            ))

        return routes

    def _extract_decorator_path(self, method_node, dec_name: str, src: bytes) -> str | None:
        """Find the path argument of a @Decorator('path') preceding a method."""
        parent = method_node.parent
        if not parent:
            return None
        try:
            idx = parent.children.index(method_node)
        except ValueError:
            return None
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "decorator":
                raw = _text(sib, src)
                m = re.search(r"""['"]([^'"]+)['"]""", raw)
                if m:
                    return m.group(1)
            else:
                break
        return None
