"""Unit tests for language detection and scanner configuration constants.

Validates the extension → language mapping table, MIME type table,
ignore directory set, and ignore extension set without requiring any
database or filesystem infrastructure.
"""

import pytest

from backend.app.core.scanner_config import (
    BINARY_EXTENSIONS,
    EXTENSION_LANGUAGE_MAP,
    EXTENSION_MIME_MAP,
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
)
from backend.app.models.file import ProgrammingLanguage
from backend.app.services.scanner_service import RepositoryScannerService


# ── Extension → Language mapping ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "extension,expected_language",
    [
        ("py", ProgrammingLanguage.PYTHON),
        ("pyw", ProgrammingLanguage.PYTHON),
        ("pyi", ProgrammingLanguage.PYTHON),
        ("java", ProgrammingLanguage.JAVA),
        ("js", ProgrammingLanguage.JAVASCRIPT),
        ("jsx", ProgrammingLanguage.JAVASCRIPT),
        ("mjs", ProgrammingLanguage.JAVASCRIPT),
        ("ts", ProgrammingLanguage.TYPESCRIPT),
        ("tsx", ProgrammingLanguage.TYPESCRIPT),
        ("go", ProgrammingLanguage.GO),
        ("c", ProgrammingLanguage.C),
        ("h", ProgrammingLanguage.C),
        ("cpp", ProgrammingLanguage.CPP),
        ("cc", ProgrammingLanguage.CPP),
        ("hpp", ProgrammingLanguage.CPP),
        ("rs", ProgrammingLanguage.RUST),
        ("kt", ProgrammingLanguage.KOTLIN),
        ("kts", ProgrammingLanguage.KOTLIN),
        ("swift", ProgrammingLanguage.SWIFT),
        ("php", ProgrammingLanguage.PHP),
        ("rb", ProgrammingLanguage.RUBY),
        ("md", ProgrammingLanguage.MARKDOWN),
        ("mdx", ProgrammingLanguage.MARKDOWN),
        ("json", ProgrammingLanguage.JSON),
        ("yaml", ProgrammingLanguage.YAML),
        ("yml", ProgrammingLanguage.YAML),
        ("tf", ProgrammingLanguage.TERRAFORM),
        ("tfvars", ProgrammingLanguage.TERRAFORM),
        ("sh", ProgrammingLanguage.SHELL),
        ("bash", ProgrammingLanguage.SHELL),
        ("html", ProgrammingLanguage.HTML),
        ("htm", ProgrammingLanguage.HTML),
        ("css", ProgrammingLanguage.CSS),
        ("scss", ProgrammingLanguage.CSS),
        ("sql", ProgrammingLanguage.SQL),
    ],
)
def test_extension_maps_to_correct_language(
    extension: str,
    expected_language: ProgrammingLanguage,
) -> None:
    """Each supported extension should map to the expected language."""
    assert EXTENSION_LANGUAGE_MAP.get(extension) == expected_language


def test_unknown_extension_returns_unknown() -> None:
    """An extension absent from the map should return UNKNOWN via detect_language."""
    lang = RepositoryScannerService.detect_language("file.xyz", "xyz")
    assert lang == ProgrammingLanguage.UNKNOWN


def test_dockerfile_exact_match() -> None:
    """Dockerfile (no extension, exact name) maps to DOCKERFILE."""
    lang = RepositoryScannerService.detect_language("Dockerfile", "")
    assert lang == ProgrammingLanguage.DOCKERFILE


def test_dockerfile_variant_match() -> None:
    """Dockerfile.prod (with suffix) maps to DOCKERFILE."""
    lang = RepositoryScannerService.detect_language("Dockerfile.prod", "prod")
    assert lang == ProgrammingLanguage.DOCKERFILE


def test_case_insensitive_dockerfile() -> None:
    """dockerfile (lowercase) maps to DOCKERFILE."""
    lang = RepositoryScannerService.detect_language("dockerfile", "")
    assert lang == ProgrammingLanguage.DOCKERFILE


# ── Compound extension ─────────────────────────────────────────────────────────


def test_compound_extension_d_ts() -> None:
    """File index.d.ts should detect as TypeScript via compound extension."""
    ext = RepositoryScannerService._extract_extension("index.d.ts")
    assert ext == "d.ts"
    lang = RepositoryScannerService.detect_language("index.d.ts", ext)
    assert lang == ProgrammingLanguage.TYPESCRIPT


# ── Ignored directories ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dir_name",
    [
        ".git",
        ".github",
        ".gitlab",
        ".idea",
        ".vscode",
        "node_modules",
        "venv",
        ".venv",
        "dist",
        "build",
        "coverage",
        ".cache",
        ".next",
        "target",
        "__pycache__",
        "bin",
        "obj",
        "vendor",
    ],
)
def test_ignored_directories_present(dir_name: str) -> None:
    """All specified ignore directories must be in the IGNORED_DIRECTORIES set."""
    assert dir_name in IGNORED_DIRECTORIES


# ── Ignored extensions ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "extension",
    [
        "pyc",
        "class",
        "exe",
        "dll",
        "so",
        "o",
        "a",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "ico",
        "zip",
        "tar",
        "gz",
        "7z",
    ],
)
def test_ignored_extensions_present(extension: str) -> None:
    """All specified ignore extensions must be in the IGNORED_EXTENSIONS set."""
    assert extension in IGNORED_EXTENSIONS


# ── Binary extension detection ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "extension",
    ["exe", "dll", "so", "o", "a", "jar", "zip", "tar", "gz", "pyc", "class"],
)
def test_binary_extensions_present(extension: str) -> None:
    """Binary extensions must be in the BINARY_EXTENSIONS set."""
    assert extension in BINARY_EXTENSIONS


# ── MIME types ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "extension,expected_mime",
    [
        ("py", "text/x-python"),
        ("js", "application/javascript"),
        ("ts", "application/typescript"),
        ("html", "text/html"),
        ("css", "text/css"),
        ("json", "application/json"),
        ("yaml", "application/x-yaml"),
        ("md", "text/markdown"),
        ("sql", "application/sql"),
        ("sh", "application/x-sh"),
    ],
)
def test_mime_type_map(extension: str, expected_mime: str) -> None:
    """Extension should map to the expected MIME type."""
    assert EXTENSION_MIME_MAP.get(extension) == expected_mime
