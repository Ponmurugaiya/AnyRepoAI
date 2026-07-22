"""Scanner configuration constants and language detection tables.

Centralises all static lookup tables used by the Repository Scanner:
  - Extension → ProgrammingLanguage mapping
  - Extension → MIME type mapping
  - Set of ignored directory names
  - Set of ignored file extensions (binary / compiled artefacts)

These constants are intentionally module-level so they are computed once
at import time and shared across scanner instances without re-allocation.
"""

from backend.app.models.file import ProgrammingLanguage

# ── Language detection table ───────────────────────────────────────────────────
# Maps lowercased file extensions (without leading dot) → ProgrammingLanguage.
# Special-case filenames (e.g. "Dockerfile") are handled separately in the
# language detector because they have no extension.

EXTENSION_LANGUAGE_MAP: dict[str, ProgrammingLanguage] = {
    # Python
    "py": ProgrammingLanguage.PYTHON,
    "pyw": ProgrammingLanguage.PYTHON,
    "pyi": ProgrammingLanguage.PYTHON,
    # Java
    "java": ProgrammingLanguage.JAVA,
    # JavaScript
    "js": ProgrammingLanguage.JAVASCRIPT,
    "jsx": ProgrammingLanguage.JAVASCRIPT,
    "mjs": ProgrammingLanguage.JAVASCRIPT,
    "cjs": ProgrammingLanguage.JAVASCRIPT,
    # TypeScript
    "ts": ProgrammingLanguage.TYPESCRIPT,
    "tsx": ProgrammingLanguage.TYPESCRIPT,
    "d.ts": ProgrammingLanguage.TYPESCRIPT,
    # Go
    "go": ProgrammingLanguage.GO,
    # C
    "c": ProgrammingLanguage.C,
    "h": ProgrammingLanguage.C,
    # C++
    "cpp": ProgrammingLanguage.CPP,
    "cc": ProgrammingLanguage.CPP,
    "cxx": ProgrammingLanguage.CPP,
    "c++": ProgrammingLanguage.CPP,
    "hpp": ProgrammingLanguage.CPP,
    "hh": ProgrammingLanguage.CPP,
    "hxx": ProgrammingLanguage.CPP,
    # Rust
    "rs": ProgrammingLanguage.RUST,
    # Kotlin
    "kt": ProgrammingLanguage.KOTLIN,
    "kts": ProgrammingLanguage.KOTLIN,
    # Swift
    "swift": ProgrammingLanguage.SWIFT,
    # PHP
    "php": ProgrammingLanguage.PHP,
    "phtml": ProgrammingLanguage.PHP,
    # Ruby
    "rb": ProgrammingLanguage.RUBY,
    "rake": ProgrammingLanguage.RUBY,
    "gemspec": ProgrammingLanguage.RUBY,
    # Markdown
    "md": ProgrammingLanguage.MARKDOWN,
    "mdx": ProgrammingLanguage.MARKDOWN,
    "markdown": ProgrammingLanguage.MARKDOWN,
    # JSON
    "json": ProgrammingLanguage.JSON,
    "jsonc": ProgrammingLanguage.JSON,
    "json5": ProgrammingLanguage.JSON,
    # YAML
    "yaml": ProgrammingLanguage.YAML,
    "yml": ProgrammingLanguage.YAML,
    # Terraform
    "tf": ProgrammingLanguage.TERRAFORM,
    "tfvars": ProgrammingLanguage.TERRAFORM,
    # Shell
    "sh": ProgrammingLanguage.SHELL,
    "bash": ProgrammingLanguage.SHELL,
    "zsh": ProgrammingLanguage.SHELL,
    "fish": ProgrammingLanguage.SHELL,
    "ksh": ProgrammingLanguage.SHELL,
    # HTML
    "html": ProgrammingLanguage.HTML,
    "htm": ProgrammingLanguage.HTML,
    "xhtml": ProgrammingLanguage.HTML,
    # CSS
    "css": ProgrammingLanguage.CSS,
    "scss": ProgrammingLanguage.CSS,
    "sass": ProgrammingLanguage.CSS,
    "less": ProgrammingLanguage.CSS,
    # SQL
    "sql": ProgrammingLanguage.SQL,
    "ddl": ProgrammingLanguage.SQL,
    "dml": ProgrammingLanguage.SQL,
}

# Exact filename → language map (for files with no extension).
FILENAME_LANGUAGE_MAP: dict[str, ProgrammingLanguage] = {
    "dockerfile": ProgrammingLanguage.DOCKERFILE,
    "makefile": ProgrammingLanguage.SHELL,
    "rakefile": ProgrammingLanguage.RUBY,
    "gemfile": ProgrammingLanguage.RUBY,
    "podfile": ProgrammingLanguage.RUBY,
    "vagrantfile": ProgrammingLanguage.RUBY,
    "jenkinsfile": ProgrammingLanguage.UNKNOWN,
}

# Simplified filename → language for files that may have suffixes in their name
# (e.g. Dockerfile.dev, dockerfile.prod).
FILENAME_PREFIX_LANGUAGE_MAP: dict[str, ProgrammingLanguage] = {
    "dockerfile": ProgrammingLanguage.DOCKERFILE,
}

# ── MIME type table ────────────────────────────────────────────────────────────

EXTENSION_MIME_MAP: dict[str, str] = {
    # Source code
    "py": "text/x-python",
    "pyw": "text/x-python",
    "pyi": "text/x-python",
    "java": "text/x-java-source",
    "js": "application/javascript",
    "jsx": "text/jsx",
    "mjs": "application/javascript",
    "cjs": "application/javascript",
    "ts": "application/typescript",
    "tsx": "text/tsx",
    "go": "text/x-go",
    "c": "text/x-csrc",
    "h": "text/x-chdr",
    "cpp": "text/x-c++src",
    "cc": "text/x-c++src",
    "cxx": "text/x-c++src",
    "hpp": "text/x-c++hdr",
    "hh": "text/x-c++hdr",
    "rs": "text/x-rustsrc",
    "kt": "text/x-kotlin",
    "kts": "text/x-kotlin",
    "swift": "text/x-swift",
    "php": "text/x-php",
    "rb": "text/x-ruby",
    "sh": "application/x-sh",
    "bash": "application/x-sh",
    "zsh": "application/x-sh",
    # Markup / data
    "html": "text/html",
    "htm": "text/html",
    "xhtml": "application/xhtml+xml",
    "css": "text/css",
    "scss": "text/x-scss",
    "sass": "text/x-sass",
    "less": "text/x-less",
    "md": "text/markdown",
    "mdx": "text/markdown",
    "markdown": "text/markdown",
    "json": "application/json",
    "jsonc": "application/json",
    "yaml": "application/x-yaml",
    "yml": "application/x-yaml",
    "xml": "application/xml",
    "sql": "application/sql",
    "tf": "text/x-terraform",
    "tfvars": "text/x-terraform",
    "toml": "application/toml",
    "ini": "text/plain",
    "cfg": "text/plain",
    "conf": "text/plain",
    "env": "text/plain",
    "txt": "text/plain",
    "rst": "text/x-rst",
    # Archives / binaries (these will be marked is_binary=True)
    "zip": "application/zip",
    "tar": "application/x-tar",
    "gz": "application/gzip",
    "7z": "application/x-7z-compressed",
    "exe": "application/vnd.microsoft.portable-executable",
    "dll": "application/vnd.microsoft.portable-executable",
    "so": "application/x-sharedlib",
    "a": "application/x-archive",
    "o": "application/x-object",
    "pyc": "application/octet-stream",
    "class": "application/java-vm",
    # Images
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "ico": "image/x-icon",
    "svg": "image/svg+xml",
    "webp": "image/webp",
}

# Default MIME type when the extension is not found in the map.
DEFAULT_MIME_TYPE: str = "application/octet-stream"
DEFAULT_TEXT_MIME_TYPE: str = "text/plain"

# ── Ignore sets ────────────────────────────────────────────────────────────────

#: Directory names that are never descended into during a scan.
IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
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
    }
)

#: File extensions (without leading dot, lowercased) that are silently ignored.
IGNORED_EXTENSIONS: frozenset[str] = frozenset(
    {
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
    }
)

#: Extensions that are always treated as binary even if they pass the ignore check.
BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pyc",
        "class",
        "exe",
        "dll",
        "so",
        "o",
        "a",
        "zip",
        "tar",
        "gz",
        "7z",
        "jar",
        "war",
        "ear",
        "whl",
        "egg",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "db",
        "sqlite",
        "sqlite3",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "ico",
        "bmp",
        "tiff",
        "webp",
        "mp3",
        "mp4",
        "avi",
        "mov",
        "mkv",
        "wav",
        "flac",
        "ogg",
        "woff",
        "woff2",
        "ttf",
        "otf",
        "eot",
    }
)

# Number of bytes read to perform binary sniffing on unknown file types.
BINARY_SNIFF_BYTES: int = 8192
