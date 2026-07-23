"""Domain models for the Code Intelligence Engine.

These Pydantic models represent the parsed output from source files.
They are pure data containers with no database coupling — persistence
models live in ``app/models/``.

All line numbers are 1-indexed to match editor conventions.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pydantic import BaseModel, Field


class SymbolType(str, enum.Enum):
    """Enumeration of all symbol types recognized by the parser system.

    Variants:
        CLASS: A class declaration.
        FUNCTION: A module-level or standalone function.
        METHOD: A function defined inside a class body.
        CONSTRUCTOR: A class constructor (``__init__``, constructor, etc.).
        VARIABLE: A mutable variable binding.
        CONSTANT: An immutable constant binding.
        ENUM: An enumeration type.
        INTERFACE: An interface or protocol declaration.
        STRUCT: A struct declaration (Go).
        MODULE: A module or namespace.
        PACKAGE: A package declaration (Go, Java).
        ROUTE: An HTTP route/endpoint.
        DECORATOR: A decorator or annotation marker.
        ANNOTATION: A Java/TypeScript annotation.
    """

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    VARIABLE = "variable"
    CONSTANT = "constant"
    ENUM = "enum"
    INTERFACE = "interface"
    STRUCT = "struct"
    MODULE = "module"
    PACKAGE = "package"
    ROUTE = "route"
    DECORATOR = "decorator"
    ANNOTATION = "annotation"


class Visibility(str, enum.Enum):
    """Symbol visibility / access modifier.

    Variants:
        PUBLIC: Accessible from any context.
        PRIVATE: Accessible only within the defining class/module.
        PROTECTED: Accessible within defining class and subclasses.
        INTERNAL: Package-level access (Go, Java package-private).
        UNKNOWN: Visibility cannot be determined.
    """

    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class Symbol(BaseModel):
    """A named code symbol extracted from a source file.

    Attributes:
        id: Stable UUID for this symbol instance.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID (references ``repository_files.id``).
        symbol_name: Short, unqualified name (e.g. ``parse_file``).
        qualified_name: Fully qualified name including class/module context
            (e.g. ``MyClass.parse_file``).
        symbol_type: Classification of the symbol.
        visibility: Access modifier / visibility level.
        start_line: 1-indexed line where the symbol begins.
        end_line: 1-indexed line where the symbol ends.
        language: Programming language of the source file.
        parent_symbol: Qualified name of the enclosing symbol, or ``None``
            for top-level symbols.
        documentation: Docstring / JavaDoc / JSDoc text, stripped of markers.
        signature: Human-readable signature string (e.g. ``def foo(x: int) -> str``).
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Stable symbol UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    symbol_name: str = Field(description="Short unqualified name")
    qualified_name: str = Field(description="Fully qualified symbol name")
    symbol_type: SymbolType = Field(description="Symbol classification")
    visibility: Visibility = Field(
        default=Visibility.UNKNOWN, description="Access modifier"
    )
    start_line: int = Field(ge=1, description="Start line (1-indexed)")
    end_line: int = Field(ge=1, description="End line (1-indexed)")
    language: str = Field(description="Programming language")
    parent_symbol: str | None = Field(
        default=None, description="Qualified name of enclosing symbol"
    )
    documentation: str | None = Field(
        default=None, description="Extracted documentation string"
    )
    signature: str | None = Field(
        default=None, description="Human-readable signature"
    )


class ImportStatement(BaseModel):
    """An import/require/use statement extracted from a source file.

    Attributes:
        id: Stable UUID for this import instance.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID.
        module_path: The imported module or package path.
        imported_names: Specific names imported from the module
            (empty list means the whole module was imported).
        alias: Optional ``as`` alias.
        is_relative: ``True`` for relative imports (Python ``from . import``).
        start_line: Source line of this import statement.
        language: Programming language.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Import UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    module_path: str = Field(description="Imported module or package path")
    imported_names: list[str] = Field(
        default_factory=list, description="Specific names imported from module"
    )
    alias: str | None = Field(default=None, description="Import alias (as X)")
    is_relative: bool = Field(default=False, description="True for relative imports")
    start_line: int = Field(ge=1, description="Source line of import statement")
    language: str = Field(description="Programming language")


class CallReference(BaseModel):
    """A function or method call extracted from a source file.

    Attributes:
        id: Stable UUID for this call instance.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID.
        caller_name: Qualified name of the symbol that makes the call.
        callee_name: Name of the function/method being called.
        callee_object: Object or module the call is made on (e.g. ``self``,
            ``os.path``). ``None`` for bare function calls.
        start_line: Line number of the call.
        language: Programming language.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Call UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    caller_name: str = Field(description="Qualified name of the calling symbol")
    callee_name: str = Field(description="Name of the called function/method")
    callee_object: str | None = Field(
        default=None, description="Object or module the call targets"
    )
    start_line: int = Field(ge=1, description="Line number of the call expression")
    language: str = Field(description="Programming language")


class ClassDefinition(BaseModel):
    """A class definition with inheritance and member information.

    Attributes:
        id: Stable UUID for this class instance.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID.
        class_name: Simple class name.
        qualified_name: Fully qualified class name.
        base_classes: List of base class names.
        interfaces: List of implemented interface names.
        visibility: Access modifier.
        is_abstract: ``True`` if the class is abstract.
        start_line: 1-indexed start line.
        end_line: 1-indexed end line.
        language: Programming language.
        documentation: Class-level docstring.
        decorators: List of decorator names applied to this class.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Class UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    class_name: str = Field(description="Simple class name")
    qualified_name: str = Field(description="Fully qualified class name")
    base_classes: list[str] = Field(
        default_factory=list, description="List of base class names"
    )
    interfaces: list[str] = Field(
        default_factory=list, description="List of implemented interface names"
    )
    visibility: Visibility = Field(
        default=Visibility.PUBLIC, description="Access modifier"
    )
    is_abstract: bool = Field(default=False, description="Abstract class flag")
    start_line: int = Field(ge=1, description="Start line (1-indexed)")
    end_line: int = Field(ge=1, description="End line (1-indexed)")
    language: str = Field(description="Programming language")
    documentation: str | None = Field(
        default=None, description="Class-level documentation string"
    )
    decorators: list[str] = Field(
        default_factory=list, description="Decorator/annotation names applied"
    )


class FunctionDefinition(BaseModel):
    """A function or method definition with full signature details.

    Attributes:
        id: Stable UUID for this function instance.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID.
        function_name: Simple function name.
        qualified_name: Fully qualified name.
        is_method: ``True`` if this function is a class method.
        is_constructor: ``True`` if this is a constructor.
        is_async: ``True`` for async/coroutine functions.
        is_static: ``True`` for static methods.
        is_class_method: ``True`` for class methods.
        visibility: Access modifier.
        parameters: List of parameter descriptors as strings.
        return_type: Return type annotation string, or ``None``.
        start_line: 1-indexed start line.
        end_line: 1-indexed end line.
        language: Programming language.
        documentation: Extracted docstring / JSDoc / JavaDoc.
        decorators: List of decorator names.
        signature: Full human-readable signature.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Function UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    function_name: str = Field(description="Simple function name")
    qualified_name: str = Field(description="Fully qualified function name")
    is_method: bool = Field(default=False, description="True if defined inside a class")
    is_constructor: bool = Field(default=False, description="True if this is a constructor")
    is_async: bool = Field(default=False, description="True for async/coroutine functions")
    is_static: bool = Field(default=False, description="True for static methods")
    is_class_method: bool = Field(default=False, description="True for class methods")
    visibility: Visibility = Field(
        default=Visibility.PUBLIC, description="Access modifier"
    )
    parameters: list[str] = Field(
        default_factory=list,
        description="List of parameter descriptors (name:type or just name)",
    )
    return_type: str | None = Field(
        default=None, description="Return type annotation string"
    )
    start_line: int = Field(ge=1, description="Start line (1-indexed)")
    end_line: int = Field(ge=1, description="End line (1-indexed)")
    language: str = Field(description="Programming language")
    documentation: str | None = Field(
        default=None, description="Extracted docstring"
    )
    decorators: list[str] = Field(
        default_factory=list, description="Decorator names applied"
    )
    signature: str | None = Field(
        default=None, description="Full human-readable signature"
    )


class RouteDefinition(BaseModel):
    """An HTTP route/endpoint detected in source code.

    Covers FastAPI, Flask, Django, Express, NestJS, Spring Boot, Gin, Echo.

    Attributes:
        id: Stable UUID for this route instance.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID.
        http_method: HTTP verb (GET, POST, PUT, DELETE, PATCH, etc.).
        path: URL path pattern (e.g. ``/users/{id}``).
        handler_name: Qualified name of the handler function.
        framework: Detected framework (fastapi, flask, django, express, etc.).
        start_line: Line where the route is defined.
        language: Programming language.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Route UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    http_method: str = Field(description="HTTP verb (GET, POST, PUT, DELETE, PATCH, …)")
    path: str = Field(description="URL path pattern")
    handler_name: str = Field(description="Qualified handler function name")
    framework: str = Field(description="Detected framework name")
    start_line: int = Field(ge=1, description="Line of the route definition")
    language: str = Field(description="Programming language")


class CommentBlock(BaseModel):
    """A documentation comment or comment block extracted from source.

    Attributes:
        id: Stable UUID for this comment.
        repository_id: Owning repository UUID.
        file_id: Owning file UUID.
        comment_text: The raw comment text with markers stripped.
        comment_type: Classification: ``docstring``, ``javadoc``,
            ``jsdoc``, ``block``, or ``line``.
        start_line: First line of the comment.
        end_line: Last line of the comment.
        language: Programming language.
        attached_symbol: Qualified name of the immediately following symbol,
            if any.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, description="Comment UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Owning file UUID")
    comment_text: str = Field(description="Comment text with delimiters stripped")
    comment_type: str = Field(
        description="Classification: docstring, javadoc, jsdoc, block, or line"
    )
    start_line: int = Field(ge=1, description="First line of the comment")
    end_line: int = Field(ge=1, description="Last line of the comment")
    language: str = Field(description="Programming language")
    attached_symbol: str | None = Field(
        default=None, description="Qualified name of the symbol this comment documents"
    )


class FileSummary(BaseModel):
    """Complete parse output for a single source file.

    This is the primary output of a language parser's ``parse_file()``
    call and the payload that the parser service persists to the database.

    Attributes:
        file_id: UUID of the ``repository_files`` record.
        repository_id: UUID of the owning repository.
        relative_path: POSIX path relative to repository root.
        language: Programming language.
        symbols: All symbols extracted from the file.
        imports: All import statements.
        calls: All call references.
        classes: All class definitions.
        functions: All function definitions.
        routes: All HTTP route definitions.
        comments: All documentation blocks.
        parse_errors: Non-fatal parse errors encountered.
        parse_duration_ms: Wall-clock parse time in milliseconds.
    """

    file_id: uuid.UUID = Field(description="Source file UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    relative_path: str = Field(description="POSIX path relative to repository root")
    language: str = Field(description="Programming language")
    symbols: list[Symbol] = Field(
        default_factory=list, description="All extracted symbols"
    )
    imports: list[ImportStatement] = Field(
        default_factory=list, description="All import statements"
    )
    calls: list[CallReference] = Field(
        default_factory=list, description="All call references"
    )
    classes: list[ClassDefinition] = Field(
        default_factory=list, description="All class definitions"
    )
    functions: list[FunctionDefinition] = Field(
        default_factory=list, description="All function definitions"
    )
    routes: list[RouteDefinition] = Field(
        default_factory=list, description="All HTTP route definitions"
    )
    comments: list[CommentBlock] = Field(
        default_factory=list, description="All documentation blocks"
    )
    parse_errors: list[str] = Field(
        default_factory=list, description="Non-fatal parse errors"
    )
    parse_duration_ms: float = Field(
        default=0.0, description="Wall-clock parse time in milliseconds"
    )
