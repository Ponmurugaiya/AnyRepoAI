"""SQLAlchemy ORM models.

Import all model modules here so Alembic's autogenerate can detect them.
"""

from backend.app.models.file import FileStatus, ProgrammingLanguage, RepositoryFile
from backend.app.models.repository import Repository, RepositoryStatus
from backend.app.models.symbol import (
    CallRecord,
    ClassRecord,
    FileParseJob,
    FunctionRecord,
    ImportRecord,
    ParseStatus,
    RouteRecord,
    Symbol,
    SymbolType,
    Visibility,
)
from backend.app.symbol_index.models.index import IndexStatus, SymbolIndex, SymbolIndexEntry

__all__ = [
    "Repository",
    "RepositoryStatus",
    "RepositoryFile",
    "FileStatus",
    "ProgrammingLanguage",
    "FileParseJob",
    "ParseStatus",
    "Symbol",
    "SymbolType",
    "Visibility",
    "ImportRecord",
    "CallRecord",
    "RouteRecord",
    "ClassRecord",
    "FunctionRecord",
    "SymbolIndex",
    "SymbolIndexEntry",
    "IndexStatus",
]
