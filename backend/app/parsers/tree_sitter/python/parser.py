"""Python tree-sitter parser implementation.

Parses Python source files using tree-sitter-languages and extracts:
- Classes (with inheritance, decorators, docstrings)
- Functions and methods (with args, return types, async, decorators)
- Imports (regular and from-imports, relative imports)
- Call references
- HTTP routes (FastAPI, Flask, Django)
- Documentation strings
"""

from __future__ import annotations

import re
import uuid
from typing import Generator

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

_LANG = get_language("python")
_PARSER = get_parser("python")

# HTTP method names recognized as route decorators
_FASTAPI_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
_FLASK_METHODS = {"route", "get", "post", "put", "delete", "patch"}


def _iter_children(node, kind: str | None = None) -> Generator:
    """Yield direct children, optionally filtered by node type."""
    for child in node.children:
        if kind is None or child.type == kind:
            yield child


def _find_nodes(node, *types: str) -> Generator:
    """Recursively yield all descendant nodes matching any of the given types."""
    if node.type in types:
        yield node
    for child in node.children:
        yield from _find_nodes(child, *types)


def _text(node, src: bytes) -> str:
    """Decode node bytes from source."""
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string literal."""
    s = s.strip()
    if (s.startswith('"""') and s.endswith('"""')) or (
        s.startswith("'''") and s.endswith("'''")
    ):
        return s[3:-3].strip()
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    return s


def _visibility_from_name(name: str) -> Visibility:
    """Infer Python visibility from naming convention."""
    if name.startswith("__") and not name.endswith("__"):
        return Visibility.PRIVATE
    if name.startswith("_"):
        return Visibility.PROTECTED
    return Visibility.PUBLIC


class PythonParser(CodeParser):
    """Tree-sitter based parser for Python source files.

    Supports Python 2 and Python 3 syntax. Extracts all symbols,
    imports, calls, classes, functions, routes, and docstrings.
    """

    language = "Python"
    extensions = ["py", "pyw", "pyi"]

    # ── extract_symbols ───────────────────────────────────────────────────────

    def extract_symbols(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[Symbol]:
        """Extract all named symbols (classes, functions, variables, constants).

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`Symbol` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        symbols: list[Symbol] = []
        self._collect_symbols(tree.root_node, src, file_id, repository_id, symbols, parent=None)
        return symbols

    def _collect_symbols(
        self,
        node,
        src: bytes,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
        out: list[Symbol],
        parent: str | None,
    ) -> None:
        """Recursively collect symbols from AST nodes."""
        if node.type == "class_definition":
            name = _text(node.child_by_field_name("name"), src)
            qname = f"{parent}.{name}" if parent else name
            out.append(Symbol(
                repository_id=repository_id, file_id=file_id,
                symbol_name=name, qualified_name=qname,
                symbol_type=SymbolType.CLASS,
                visibility=_visibility_from_name(name),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language=self.language, parent_symbol=parent,
                signature=f"class {name}",
            ))
            body = node.child_by_field_name("body")
            if body:
                self._collect_symbols(body, src, file_id, repository_id, out, qname)
            return

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if not name_node:
                for child in node.children:
                    self._collect_symbols(child, src, file_id, repository_id, out, parent)
                return
            name = _text(name_node, src)
            qname = f"{parent}.{name}" if parent else name
            is_dunder = name.startswith("__") and name.endswith("__")
            stype = SymbolType.CONSTRUCTOR if name == "__init__" else (
                SymbolType.METHOD if parent else SymbolType.FUNCTION
            )
            params_node = node.child_by_field_name("parameters")
            sig = f"def {name}{_text(params_node, src) if params_node else '()'}"
            ret = node.child_by_field_name("return_type")
            if ret:
                sig += f" -> {_text(ret, src)}"
            out.append(Symbol(
                repository_id=repository_id, file_id=file_id,
                symbol_name=name, qualified_name=qname,
                symbol_type=stype,
                visibility=_visibility_from_name(name),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language=self.language, parent_symbol=parent,
                signature=sig,
            ))
            body = node.child_by_field_name("body")
            if body:
                self._collect_symbols(body, src, file_id, repository_id, out, qname)
            return

        # Top-level assignment: detect constants (ALL_CAPS) and variables
        if node.type == "expression_statement" and parent is None:
            for child in node.children:
                if child.type == "assignment":
                    lhs = child.child_by_field_name("left")
                    if lhs and lhs.type == "identifier":
                        name = _text(lhs, src)
                        stype = SymbolType.CONSTANT if name.isupper() else SymbolType.VARIABLE
                        out.append(Symbol(
                            repository_id=repository_id, file_id=file_id,
                            symbol_name=name, qualified_name=name,
                            symbol_type=stype,
                            visibility=_visibility_from_name(name),
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            language=self.language, parent_symbol=parent,
                        ))

        for child in node.children:
            self._collect_symbols(child, src, file_id, repository_id, out, parent)

    # ── extract_imports ───────────────────────────────────────────────────────

    def extract_imports(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ImportStatement]:
        """Extract all import and from-import statements.

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ImportStatement` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        imports: list[ImportStatement] = []

        for node in _find_nodes(tree.root_node, "import_statement", "import_from_statement"):
            line = node.start_point[0] + 1

            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.append(ImportStatement(
                            repository_id=repository_id, file_id=file_id,
                            module_path=_text(child, src),
                            start_line=line, language=self.language,
                        ))
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        if name_node:
                            imports.append(ImportStatement(
                                repository_id=repository_id, file_id=file_id,
                                module_path=_text(name_node, src),
                                alias=_text(alias_node, src) if alias_node else None,
                                start_line=line, language=self.language,
                            ))

            elif node.type == "import_from_statement":
                # Count leading dots for relative import detection
                dots = sum(1 for c in node.children if c.type == ".")
                is_relative = dots > 0
                module_node = node.child_by_field_name("module_name")
                module_path = _text(module_node, src) if module_node else ""
                if is_relative:
                    module_path = "." * dots + module_path

                names: list[str] = []
                alias: str | None = None
                for child in node.children:
                    if child.type == "dotted_name" and child != module_node:
                        names.append(_text(child, src))
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        alias_node = child.child_by_field_name("alias")
                        if name_node:
                            names.append(_text(name_node, src))
                        if alias_node:
                            alias = _text(alias_node, src)
                    elif child.type == "wildcard_import":
                        names.append("*")

                imports.append(ImportStatement(
                    repository_id=repository_id, file_id=file_id,
                    module_path=module_path, imported_names=names,
                    alias=alias, is_relative=is_relative,
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
        """Extract function and method call expressions.

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`CallReference` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        calls: list[CallReference] = []

        for call_node in _find_nodes(tree.root_node, "call"):
            fn_node = call_node.child_by_field_name("function")
            if not fn_node:
                continue
            line = call_node.start_point[0] + 1

            if fn_node.type == "attribute":
                obj_node = fn_node.child_by_field_name("object")
                attr_node = fn_node.child_by_field_name("attribute")
                callee_name = _text(attr_node, src) if attr_node else ""
                callee_obj = _text(obj_node, src) if obj_node else None
            elif fn_node.type == "identifier":
                callee_name = _text(fn_node, src)
                callee_obj = None
            else:
                continue

            caller = self._enclosing_function(call_node, src) or "<module>"
            calls.append(CallReference(
                repository_id=repository_id, file_id=file_id,
                caller_name=caller, callee_name=callee_name,
                callee_object=callee_obj, start_line=line,
                language=self.language,
            ))

        return calls

    def _enclosing_function(self, node, src: bytes) -> str | None:
        """Walk up the AST to find the nearest enclosing function name."""
        current = node.parent
        parts: list[str] = []
        while current:
            if current.type == "function_definition":
                n = current.child_by_field_name("name")
                if n:
                    parts.append(_text(n, src))
            elif current.type == "class_definition":
                n = current.child_by_field_name("name")
                if n:
                    parts.append(_text(n, src))
            current = current.parent
        if parts:
            return ".".join(reversed(parts))
        return None

    # ── extract_classes ───────────────────────────────────────────────────────

    def extract_classes(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[ClassDefinition]:
        """Extract class definitions with inheritance and decorator info.

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`ClassDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        classes: list[ClassDefinition] = []

        for node in _find_nodes(tree.root_node, "class_definition"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)

            # Base classes
            bases: list[str] = []
            args_node = node.child_by_field_name("superclasses")
            if args_node:
                for child in args_node.children:
                    if child.type in ("identifier", "dotted_name", "attribute"):
                        bases.append(_text(child, src))

            # Decorators
            decorators = self._extract_decorator_names(node, src)
            is_abstract = "ABC" in bases or "ABCMeta" in bases or "abc.ABC" in bases

            # Docstring
            doc = self._extract_docstring(node.child_by_field_name("body"), src)

            # Determine parent class context
            parent_ctx = self._parent_class_name(node, src)
            qname = f"{parent_ctx}.{name}" if parent_ctx else name

            classes.append(ClassDefinition(
                repository_id=repository_id, file_id=file_id,
                class_name=name, qualified_name=qname,
                base_classes=bases, interfaces=[],
                visibility=_visibility_from_name(name),
                is_abstract=is_abstract,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language=self.language,
                documentation=doc, decorators=decorators,
            ))

        return classes

    def _extract_decorator_names(self, node, src: bytes) -> list[str]:
        """Extract decorator names from a function or class node."""
        names: list[str] = []
        parent = node.parent
        if not parent:
            return names
        idx = parent.children.index(node)
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "decorator":
                for child in sib.children:
                    if child.type in ("identifier", "attribute", "call"):
                        names.insert(0, _text(child, src).split("(")[0])
                        break
            else:
                break
        return names

    def _parent_class_name(self, node, src: bytes) -> str | None:
        """Return the nearest enclosing class name, or None."""
        current = node.parent
        while current:
            if current.type == "class_definition":
                n = current.child_by_field_name("name")
                if n:
                    return _text(n, src)
            current = current.parent
        return None

    # ── extract_functions ─────────────────────────────────────────────────────

    def extract_functions(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[FunctionDefinition]:
        """Extract function and method definitions with full metadata.

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`FunctionDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        functions: list[FunctionDefinition] = []

        for node in _find_nodes(tree.root_node, "function_definition"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            name = _text(name_node, src)
            is_async = any(c.type == "async" for c in node.children)

            # Parameters
            params_node = node.child_by_field_name("parameters")
            params: list[str] = []
            if params_node:
                for p in params_node.children:
                    if p.type in (
                        "identifier", "typed_parameter", "default_parameter",
                        "typed_default_parameter", "list_splat_pattern",
                        "dictionary_splat_pattern",
                    ):
                        params.append(_text(p, src))

            # Return type
            ret_node = node.child_by_field_name("return_type")
            ret_type = _text(ret_node, src).lstrip("->").strip() if ret_node else None

            # Signature
            sig_params = ", ".join(params)
            sig = f"{'async ' if is_async else ''}def {name}({sig_params})"
            if ret_type:
                sig += f" -> {ret_type}"

            # Context
            parent_class = self._parent_class_name(node, src)
            is_method = parent_class is not None
            is_ctor = name == "__init__"
            qname = f"{parent_class}.{name}" if parent_class else name

            # Static / classmethod from decorators
            decorators = self._extract_decorator_names(node, src)
            is_static = "staticmethod" in decorators
            is_cm = "classmethod" in decorators

            # Docstring
            doc = self._extract_docstring(node.child_by_field_name("body"), src)

            # Visibility
            vis = _visibility_from_name(name)

            functions.append(FunctionDefinition(
                repository_id=repository_id, file_id=file_id,
                function_name=name, qualified_name=qname,
                is_method=is_method, is_constructor=is_ctor,
                is_async=is_async, is_static=is_static,
                is_class_method=is_cm, visibility=vis,
                parameters=params, return_type=ret_type,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language=self.language, documentation=doc,
                decorators=decorators, signature=sig,
            ))

        return functions

    # ── extract_comments ──────────────────────────────────────────────────────

    def extract_comments(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[CommentBlock]:
        """Extract docstrings and inline comments.

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`CommentBlock` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        comments: list[CommentBlock] = []

        # Docstrings: expression_statement containing a string as first stmt in body
        for node in _find_nodes(
            tree.root_node,
            "function_definition",
            "class_definition", "module",
        ):
            body = node.child_by_field_name("body") if node.type != "module" else node
            if not body:
                continue
            for child in body.children:
                if child.type == "expression_statement":
                    for subchild in child.children:
                        if subchild.type == "string":
                            raw = _text(subchild, src)
                            text = _strip_quotes(raw)
                            comments.append(CommentBlock(
                                repository_id=repository_id, file_id=file_id,
                                comment_text=text, comment_type="docstring",
                                start_line=subchild.start_point[0] + 1,
                                end_line=subchild.end_point[0] + 1,
                                language=self.language,
                            ))
                    break

        # Inline comments
        for node in _find_nodes(tree.root_node, "comment"):
            raw = _text(node, src).lstrip("#").strip()
            comments.append(CommentBlock(
                repository_id=repository_id, file_id=file_id,
                comment_text=raw, comment_type="line",
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language=self.language,
            ))

        return comments

    def _extract_docstring(self, body_node, src: bytes) -> str | None:
        """Extract the first string literal from a function/class body."""
        if not body_node:
            return None
        for child in body_node.children:
            if child.type == "expression_statement":
                for subchild in child.children:
                    if subchild.type == "string":
                        return _strip_quotes(_text(subchild, src))
            elif child.type not in ("comment",):
                break
        return None

    # ── extract_routes ────────────────────────────────────────────────────────

    def extract_routes(
        self,
        source: str,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> list[RouteDefinition]:
        """Detect HTTP route decorators for FastAPI, Flask, and Django.

        Recognises:
        - ``@app.get("/path")``, ``@router.post("/path")``  (FastAPI)
        - ``@app.route("/path", methods=["GET"])``           (Flask)
        - ``path("url", view)``                              (Django urls.py)

        Args:
            source: Python source code.
            file_id: File UUID.
            repository_id: Repository UUID.

        Returns:
            List of :class:`RouteDefinition` instances.
        """
        src = source.encode("utf-8")
        tree = _PARSER.parse(src)
        routes: list[RouteDefinition] = []

        for fn_node in _find_nodes(
            tree.root_node, "function_definition"
        ):
            name_node = fn_node.child_by_field_name("name")
            if not name_node:
                continue
            fn_name = _text(name_node, src)
            parent_class = self._parent_class_name(fn_node, src)
            qname = f"{parent_class}.{fn_name}" if parent_class else fn_name

            decorators = self._get_decorator_nodes(fn_node, src)
            for dec_text in decorators:
                route = self._parse_route_decorator(
                    dec_text, qname, fn_node.start_point[0] + 1,
                    file_id, repository_id,
                )
                if route:
                    routes.append(route)

        # Django-style: path(...) / re_path(...) / url(...) at module level
        for call_node in _find_nodes(tree.root_node, "call"):
            fn_node = call_node.child_by_field_name("function")
            if fn_node and fn_node.type == "identifier":
                fn_name = _text(fn_node, src)
                if fn_name in ("path", "re_path", "url"):
                    args = call_node.child_by_field_name("arguments")
                    if args:
                        arg_children = [c for c in args.children if c.type != ","]
                        if arg_children:
                            path_str = _strip_quotes(_text(arg_children[0], src))
                            handler = ""
                            if len(arg_children) > 1:
                                handler = _text(arg_children[1], src)
                            routes.append(RouteDefinition(
                                repository_id=repository_id, file_id=file_id,
                                http_method="GET",
                                path=path_str, handler_name=handler,
                                framework="django",
                                start_line=call_node.start_point[0] + 1,
                                language=self.language,
                            ))
        return routes

    def _get_decorator_nodes(self, fn_node, src: bytes) -> list[str]:
        """Return text of all decorators preceding a function node."""
        result: list[str] = []
        parent = fn_node.parent
        if not parent:
            return result
        idx = parent.children.index(fn_node)
        for i in range(idx - 1, -1, -1):
            sib = parent.children[i]
            if sib.type == "decorator":
                result.insert(0, _text(sib, src))
            else:
                break
        return result

    def _parse_route_decorator(
        self,
        decorator_text: str,
        handler_name: str,
        line: int,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
    ) -> RouteDefinition | None:
        """Parse a decorator text into a RouteDefinition, or None."""
        # FastAPI / APIRouter: @router.get("/path") or @app.post("/path")
        m = re.search(
            r'\.(\w+)\s*\(\s*["\']([^"\']+)["\']',
            decorator_text,
        )
        if m:
            method = m.group(1).upper()
            path = m.group(2)
            if method.lower() in _FASTAPI_METHODS:
                framework = "fastapi" if "router" in decorator_text.lower() or "app" in decorator_text.lower() else "flask"
                return RouteDefinition(
                    repository_id=repository_id, file_id=file_id,
                    http_method=method, path=path,
                    handler_name=handler_name, framework=framework,
                    start_line=line, language=self.language,
                )

        # Flask: @app.route("/path", methods=["GET", "POST"])
        m2 = re.search(r'route\s*\(\s*["\']([^"\']+)["\']', decorator_text)
        if m2:
            path = m2.group(1)
            methods_match = re.search(r'methods\s*=\s*\[([^\]]+)\]', decorator_text)
            if methods_match:
                raw = methods_match.group(1)
                http_methods = [x.strip().strip("'\"").upper() for x in raw.split(",")]
            else:
                http_methods = ["GET"]
            for http_method in http_methods:
                return RouteDefinition(
                    repository_id=repository_id, file_id=file_id,
                    http_method=http_method, path=path,
                    handler_name=handler_name, framework="flask",
                    start_line=line, language=self.language,
                )
        return None
