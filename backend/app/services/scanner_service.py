"""Repository Scanner service.

Walks a cloned repository on disk, builds complete file metadata, and
persists the results to the ``repository_files`` table.

The scanner intentionally does NOT parse source code — it only produces
file-level metadata (path, language, hash, size, binary flag, etc.).
AST parsing is the responsibility of the next downstream module.

Public interface
----------------
- :meth:`RepositoryScannerService.scan_repository` — top-level entry point
- :meth:`RepositoryScannerService.generate_manifest` — assemble final manifest

Design decisions
----------------
- ``os.scandir()`` is used throughout (O(1) per entry vs recursive glob).
- Files are never read into memory in full; SHA-256 is streamed in chunks.
- Binary detection uses extension lookup first, then byte-sniffing.
- The directory walk is iterative (stack-based) to avoid recursion limits.
- Database writes use bulk-upsert in configurable batches to bound memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.exceptions import (
    RepositoryNotFoundError,
    RepositoryNotReadyError,
    ScannerError,
)
from backend.app.core.logging import get_logger
from backend.app.core.scanner_config import (
    BINARY_EXTENSIONS,
    BINARY_SNIFF_BYTES,
    EXTENSION_LANGUAGE_MAP,
    EXTENSION_MIME_MAP,
    FILENAME_PREFIX_LANGUAGE_MAP,
    IGNORED_DIRECTORIES,
    IGNORED_EXTENSIONS,
    DEFAULT_MIME_TYPE,
    DEFAULT_TEXT_MIME_TYPE,
)
from backend.app.models.file import FileStatus, ProgrammingLanguage, RepositoryFile
from backend.app.models.repository import Repository, RepositoryStatus
from backend.app.repositories.file_repository import FileRepository
from backend.app.repositories.repository import RepositoryRepository
from backend.app.schemas.scanner import (
    DirectoryNode,
    LanguageStats,
    RepositoryManifest,
    ScanInitiatedResponse,
    ScanStatistics,
)

logger = get_logger(__name__)


class RepositoryScannerService:
    """Orchestrates all repository scanning operations.

    Args:
        session: Injected SQLAlchemy async session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo_repo = RepositoryRepository(session)
        self._file_repo = FileRepository(session)
        self._settings = get_settings()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def scan_repository(self, repository_id: uuid.UUID) -> ScanStatistics:
        """Scan a repository and persist all file metadata.

        This method is designed to be called from a Celery task or
        FastAPI BackgroundTask. All status transitions and error handling
        are managed internally.

        Steps:
            1. Load repository record; validate status=READY.
            2. Delete any existing file records (clean slate).
            3. Walk directory tree, build file metadata.
            4. Bulk-insert file records in batches.
            5. Return aggregate statistics.

        Args:
            repository_id: UUID of the repository to scan.

        Returns:
            :class:`~backend.app.schemas.scanner.ScanStatistics` summarising the scan.

        Raises:
            RepositoryNotFoundError: Repository record not found.
            RepositoryNotReadyError: Repository status is not READY.
            ScannerError: Filesystem or database error during scan.
        """
        start_time = time.perf_counter()

        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))

        if repo.clone_status != RepositoryStatus.READY:
            raise RepositoryNotReadyError(
                str(repository_id),
                repo.clone_status.value,
            )

        if not repo.local_path or not Path(repo.local_path).exists():
            logger.error(
                "Repository local_path missing or does not exist",
                repository_id=str(repository_id),
                local_path=repo.local_path,
            )
            raise ScannerError(
                f"Repository {repository_id} has no valid local_path. Re-clone first."
            )

        logger.info(
            "Repository scan started",
            repository_id=str(repository_id),
            local_path=repo.local_path,
        )

        # Delete existing file records to ensure clean state
        await self._file_repo.delete_by_repository(repository_id)

        stats = ScanStatistics()
        batch: list[dict] = []
        batch_size = self._settings.scanner.db_batch_size

        root_path = Path(repo.local_path)

        async def _flush_batch() -> None:
            if batch:
                await self._file_repo.bulk_upsert(batch)
                batch.clear()

        try:
            for file_dict in self._walk_repository(root_path, repository_id):
                status = file_dict.get("scan_status")

                stats.total_files += 1
                if status == FileStatus.SCANNED:
                    stats.scanned_files += 1
                    stats.total_bytes += file_dict.get("size_bytes", 0)
                    if file_dict.get("is_binary"):
                        stats.binary_files += 1
                    if file_dict.get("is_hidden"):
                        stats.hidden_files += 1
                    lang = file_dict.get("language")
                    if lang and lang != ProgrammingLanguage.UNKNOWN:
                        stats.source_files += 1
                    if lang == ProgrammingLanguage.MARKDOWN:
                        stats.documentation_files += 1
                elif status == FileStatus.IGNORED:
                    stats.ignored_files += 1
                elif status == FileStatus.FAILED:
                    stats.failed_files += 1

                batch.append(file_dict)

                if len(batch) >= batch_size:
                    await _flush_batch()

            # Flush remaining records
            await _flush_batch()

        except Exception as exc:
            logger.error(
                "Repository scan failed",
                repository_id=str(repository_id),
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            raise ScannerError(f"Scan failed for repository {repository_id}: {exc}") from exc

        elapsed = time.perf_counter() - start_time
        stats.scan_duration_seconds = round(elapsed, 3)

        # Populate languages_found
        lang_stats = await self._file_repo.get_language_stats(repository_id)
        stats.languages_found = [
            row[0].value for row in lang_stats
            if row[0] != ProgrammingLanguage.UNKNOWN
        ]

        logger.info(
            "Repository scan completed",
            repository_id=str(repository_id),
            total_files=stats.total_files,
            scanned_files=stats.scanned_files,
            ignored_files=stats.ignored_files,
            failed_files=stats.failed_files,
            total_bytes=stats.total_bytes,
            duration_seconds=stats.scan_duration_seconds,
        )

        return stats

    async def generate_manifest(
        self,
        repository_id: uuid.UUID,
    ) -> RepositoryManifest:
        """Generate a complete repository manifest after a scan.

        Assembles:
          - Aggregate statistics
          - Per-language breakdown with byte totals
          - Hierarchical directory tree

        Args:
            repository_id: UUID of the repository to manifest.

        Returns:
            :class:`~backend.app.schemas.scanner.RepositoryManifest`

        Raises:
            RepositoryNotFoundError: Repository does not exist.
        """
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))

        # Build statistics
        total_files = await self._file_repo.count_by_repository(repository_id)
        scanned = await self._file_repo.count_by_status(repository_id, FileStatus.SCANNED)
        ignored = await self._file_repo.count_by_status(repository_id, FileStatus.IGNORED)
        failed = await self._file_repo.count_by_status(repository_id, FileStatus.FAILED)

        files = await self._file_repo.get_by_repository_id(repository_id)
        total_bytes = sum(f.size_bytes for f in files if f.scan_status == FileStatus.SCANNED)
        binary_count = sum(1 for f in files if f.is_binary and f.scan_status == FileStatus.SCANNED)
        hidden_count = sum(1 for f in files if f.is_hidden and f.scan_status == FileStatus.SCANNED)
        source_count = sum(
            1 for f in files
            if f.scan_status == FileStatus.SCANNED
            and f.language != ProgrammingLanguage.UNKNOWN
        )
        doc_count = sum(
            1 for f in files
            if f.scan_status == FileStatus.SCANNED
            and f.language == ProgrammingLanguage.MARKDOWN
        )

        stats = ScanStatistics(
            total_files=total_files,
            scanned_files=scanned,
            ignored_files=ignored,
            failed_files=failed,
            binary_files=binary_count,
            hidden_files=hidden_count,
            total_bytes=total_bytes,
            source_files=source_count,
            documentation_files=doc_count,
            languages_found=[],
            scan_duration_seconds=0.0,
        )

        # Language breakdown
        lang_rows = await self._file_repo.get_language_stats(repository_id)
        languages = []
        for lang, count, bytes_total in lang_rows:
            if lang != ProgrammingLanguage.UNKNOWN:
                stats.languages_found.append(lang.value)
            pct = (count / scanned * 100.0) if scanned > 0 else 0.0
            languages.append(
                LanguageStats(
                    language=lang.value,
                    file_count=count,
                    total_bytes=bytes_total,
                    percentage=round(pct, 2),
                )
            )

        # Directory tree
        tree = self._build_directory_tree(files)

        return RepositoryManifest(
            repository_id=repository_id,
            scan_status="COMPLETED",
            statistics=stats,
            languages=languages,
            directory_tree=tree,
            scanned_at=datetime.now(timezone.utc),
        )

    # ── Directory walking ─────────────────────────────────────────────────────

    def _walk_repository(
        self,
        root: Path,
        repository_id: uuid.UUID,
    ) -> Iterator[dict]:
        """Iteratively walk the repository directory tree using a stack.

        Uses ``os.scandir()`` for efficient directory traversal without
        loading entire directory listings into memory.

        Yields one ``dict`` per file (matching RepositoryFile column names).
        Directories in ``IGNORED_DIRECTORIES`` are never descended into.
        The ``.git`` directory is always excluded.

        Args:
            root: Absolute path to the repository root.
            repository_id: UUID used to populate the ``repository_id`` column.

        Yields:
            dict: Column-name keyed dictionary ready for bulk upsert.
        """
        max_depth = self._settings.scanner.max_scan_depth

        # Stack entries: (dir_path, depth, parent_hidden)
        stack: list[tuple[Path, int, bool]] = [(root, 0, False)]

        while stack:
            current_dir, depth, parent_hidden = stack.pop()

            if depth > max_depth:
                logger.warning(
                    "Maximum scan depth exceeded, skipping directory",
                    directory=str(current_dir),
                    depth=depth,
                    max_depth=max_depth,
                )
                continue

            logger.debug(
                "Directory entered",
                directory=str(current_dir),
                depth=depth,
            )

            try:
                with os.scandir(current_dir) as entries:
                    subdirs: list[tuple[Path, int, bool]] = []

                    for entry in entries:
                        entry_path = Path(entry.path)
                        entry_name = entry.name

                        if entry.is_dir(follow_symlinks=False):
                            if entry_name in IGNORED_DIRECTORIES:
                                logger.debug(
                                    "Ignored directory skipped",
                                    directory=entry_name,
                                )
                                continue
                            is_hidden = parent_hidden or entry_name.startswith(".")
                            subdirs.append((entry_path, depth + 1, is_hidden))
                            continue

                        if entry.is_file(follow_symlinks=False):
                            file_dict = self._scan_file(
                                entry=entry,
                                entry_path=entry_path,
                                root=root,
                                repository_id=repository_id,
                                parent_hidden=parent_hidden,
                            )
                            yield file_dict

                    # Push subdirectories in reverse so alphabetical order is preserved
                    stack.extend(reversed(subdirs))

            except PermissionError as exc:
                logger.warning(
                    "Permission denied reading directory",
                    directory=str(current_dir),
                    error=str(exc),
                )
            except OSError as exc:
                logger.warning(
                    "OS error reading directory",
                    directory=str(current_dir),
                    error=str(exc),
                )

    def _scan_file(
        self,
        entry: os.DirEntry,
        entry_path: Path,
        root: Path,
        repository_id: uuid.UUID,
        parent_hidden: bool,
    ) -> dict:
        """Build a complete metadata dictionary for a single file.

        Args:
            entry: ``os.DirEntry`` for the file.
            entry_path: Resolved :class:`~pathlib.Path` for the file.
            root: Repository root path (used to compute relative_path).
            repository_id: UUID of the owning repository.
            parent_hidden: Whether any ancestor directory is hidden.

        Returns:
            dict: Column-name keyed dictionary suitable for bulk upsert.
        """
        file_name = entry.name
        extension = self._extract_extension(file_name)
        is_hidden = parent_hidden or file_name.startswith(".")

        # Compute POSIX relative path
        try:
            relative_path = entry_path.relative_to(root).as_posix()
        except ValueError:
            relative_path = entry_path.as_posix()

        # --- Check ignore rules ---
        if extension.lower() in IGNORED_EXTENSIONS:
            logger.debug(
                "File ignored (extension)",
                file=relative_path,
                extension=extension,
            )
            return self._build_record(
                repository_id=repository_id,
                file_name=file_name,
                extension=extension,
                relative_path=relative_path,
                absolute_path=str(entry_path),
                is_hidden=is_hidden,
                status=FileStatus.IGNORED,
                size_bytes=0,
            )

        # --- Stat the file ---
        try:
            stat = entry.stat(follow_symlinks=False)
            size_bytes = stat.st_size
            last_modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except OSError as exc:
            logger.warning(
                "File stat failed",
                file=relative_path,
                error=str(exc),
            )
            return self._build_record(
                repository_id=repository_id,
                file_name=file_name,
                extension=extension,
                relative_path=relative_path,
                absolute_path=str(entry_path),
                is_hidden=is_hidden,
                status=FileStatus.FAILED,
                size_bytes=0,
            )

        # --- Size guard ---
        max_bytes = self._settings.scanner.max_file_size_bytes
        if size_bytes > max_bytes:
            logger.debug(
                "File ignored (exceeds max size)",
                file=relative_path,
                size_bytes=size_bytes,
                max_bytes=max_bytes,
            )
            return self._build_record(
                repository_id=repository_id,
                file_name=file_name,
                extension=extension,
                relative_path=relative_path,
                absolute_path=str(entry_path),
                is_hidden=is_hidden,
                status=FileStatus.IGNORED,
                size_bytes=size_bytes,
                last_modified=last_modified,
            )

        # --- Language and binary detection ---
        is_binary = self.detect_binary(file_name, extension, str(entry_path))
        language = self.detect_language(file_name, extension)
        mime_type = EXTENSION_MIME_MAP.get(extension.lower(), DEFAULT_MIME_TYPE)

        # --- Hash (text files only) ---
        sha256: str | None = None
        if not is_binary and size_bytes > 0:
            try:
                sha256 = self.compute_hash(str(entry_path))
                logger.debug("Hash computed", file=relative_path, sha256=sha256[:8])
            except OSError as exc:
                logger.warning(
                    "Hash computation failed",
                    file=relative_path,
                    error=str(exc),
                )
                return self._build_record(
                    repository_id=repository_id,
                    file_name=file_name,
                    extension=extension,
                    relative_path=relative_path,
                    absolute_path=str(entry_path),
                    is_hidden=is_hidden,
                    status=FileStatus.FAILED,
                    size_bytes=size_bytes,
                    last_modified=last_modified,
                )

        logger.debug(
            "File scanned",
            file=relative_path,
            language=language.value,
            size_bytes=size_bytes,
            is_binary=is_binary,
        )

        return self._build_record(
            repository_id=repository_id,
            file_name=file_name,
            extension=extension,
            relative_path=relative_path,
            absolute_path=str(entry_path),
            is_hidden=is_hidden,
            status=FileStatus.SCANNED,
            size_bytes=size_bytes,
            sha256=sha256,
            is_binary=is_binary,
            language=language,
            mime_type=mime_type,
            last_modified=last_modified,
        )

    # ── Core detection methods ────────────────────────────────────────────────

    @staticmethod
    def detect_language(file_name: str, extension: str) -> ProgrammingLanguage:
        """Map a file to a :class:`~backend.app.models.file.ProgrammingLanguage`.

        Resolution order:
          1. Exact filename match (lowercased) against ``FILENAME_PREFIX_LANGUAGE_MAP``
             — handles ``Dockerfile``, ``Dockerfile.dev``, etc.
          2. Extension lookup in ``EXTENSION_LANGUAGE_MAP``.
          3. Fall through to ``UNKNOWN``.

        Args:
            file_name: Base name of the file (e.g. ``api.py``).
            extension: Extension without leading dot (e.g. ``py``).

        Returns:
            :class:`~backend.app.models.file.ProgrammingLanguage`
        """
        # Step 1: Prefix/exact filename check (case-insensitive)
        lower_name = file_name.lower()
        for prefix, lang in FILENAME_PREFIX_LANGUAGE_MAP.items():
            if lower_name == prefix or lower_name.startswith(prefix + "."):
                return lang

        # Step 2: Extension lookup
        if extension:
            return EXTENSION_LANGUAGE_MAP.get(extension.lower(), ProgrammingLanguage.UNKNOWN)

        return ProgrammingLanguage.UNKNOWN

    @staticmethod
    def detect_binary(file_name: str, extension: str, absolute_path: str) -> bool:
        """Determine whether a file should be treated as binary.

        Binary files are never read into memory for hashing.

        Resolution order:
          1. Extension membership in ``BINARY_EXTENSIONS``.
          2. Byte-sniff: read the first ``BINARY_SNIFF_BYTES`` bytes and look
             for null bytes (the classic heuristic used by git).

        Args:
            file_name: Base name of the file.
            extension: Extension without leading dot (e.g. ``exe``).
            absolute_path: Absolute filesystem path (used for byte sniffing).

        Returns:
            ``True`` when the file is considered binary.
        """
        if extension.lower() in BINARY_EXTENSIONS:
            return True

        # Byte-sniff fallback
        try:
            with open(absolute_path, "rb") as fh:
                chunk = fh.read(BINARY_SNIFF_BYTES)
            return b"\x00" in chunk
        except OSError:
            # If we cannot read the file, assume binary to be safe
            return True

    @staticmethod
    def compute_hash(absolute_path: str) -> str:
        """Compute the SHA-256 hex digest of a file by streaming its contents.

        The file is never fully loaded into memory; it is read in fixed-size
        chunks to support arbitrarily large files within the size limit.

        Args:
            absolute_path: Absolute path to the file.

        Returns:
            64-character lowercase hex string (SHA-256 digest).

        Raises:
            OSError: If the file cannot be read.
        """
        settings = get_settings()
        chunk_size = settings.scanner.hash_chunk_size
        digest = hashlib.sha256()
        with open(absolute_path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_extension(file_name: str) -> str:
        """Extract the lowercase extension from a file name.

        Handles compound extensions (e.g. ``.d.ts`` → ``d.ts``) by
        returning the portion after the *first* dot for files whose
        name contains more than one dot component and where the compound
        extension exists in ``EXTENSION_LANGUAGE_MAP``.

        For all other files the standard suffix after the last dot is used.

        Args:
            file_name: Base name of the file.

        Returns:
            Lowercase extension string without leading dot; empty string
            when the file has no extension.
        """
        if "." not in file_name or file_name.startswith("."):
            return ""

        # Check compound extension (e.g. d.ts)
        parts = file_name.split(".")
        if len(parts) >= 3:
            compound = ".".join(parts[-2:]).lower()
            if compound in EXTENSION_LANGUAGE_MAP:
                return compound

        return parts[-1].lower()

    @staticmethod
    def _build_record(
        *,
        repository_id: uuid.UUID,
        file_name: str,
        extension: str,
        relative_path: str,
        absolute_path: str,
        is_hidden: bool,
        status: FileStatus,
        size_bytes: int = 0,
        sha256: str | None = None,
        is_binary: bool = False,
        language: ProgrammingLanguage = ProgrammingLanguage.UNKNOWN,
        mime_type: str = DEFAULT_MIME_TYPE,
        last_modified: datetime | None = None,
    ) -> dict:
        """Assemble a column-name keyed dict for bulk upsert.

        Args:
            repository_id: Owning repository UUID.
            file_name: Base name of the file.
            extension: Lowercase extension without dot.
            relative_path: POSIX-style path relative to repository root.
            absolute_path: Absolute filesystem path.
            is_hidden: Hidden flag.
            status: :class:`~backend.app.models.file.FileStatus`.
            size_bytes: File size in bytes.
            sha256: Optional SHA-256 hex digest.
            is_binary: Binary flag.
            language: Detected :class:`~backend.app.models.file.ProgrammingLanguage`.
            mime_type: MIME type string.
            last_modified: Filesystem last-modification time.

        Returns:
            dict: Ready for ``FileRepository.bulk_upsert``.
        """
        now = datetime.now(timezone.utc)
        return {
            "id": uuid.uuid4(),
            "repository_id": repository_id,
            "relative_path": relative_path,
            "absolute_path": absolute_path,
            "file_name": file_name,
            "extension": extension,
            "language": language,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "is_binary": is_binary,
            "is_hidden": is_hidden,
            "last_modified": last_modified,
            "scan_status": status,
            "created_at": now,
            "updated_at": now,
        }

    # ── Manifest tree builder ─────────────────────────────────────────────────

    @staticmethod
    def _build_directory_tree(
        files: list[RepositoryFile],
    ) -> list[DirectoryNode]:
        """Build a hierarchical directory tree from a flat list of file records.

        Only SCANNED files are included in the tree.

        Args:
            files: All :class:`~backend.app.models.file.RepositoryFile` records
                   for a repository.

        Returns:
            A list of root-level :class:`~backend.app.schemas.scanner.DirectoryNode`
            objects with nested ``children`` forming the full tree.
        """
        # Build a nested dict tree first
        root: dict = {"__files__": [], "__dirs__": {}}

        scanned = [f for f in files if f.scan_status == FileStatus.SCANNED]

        for file in scanned:
            parts = file.relative_path.split("/")
            node = root
            for part in parts[:-1]:  # Navigate/create intermediate directories
                if part not in node["__dirs__"]:
                    node["__dirs__"][part] = {"__files__": [], "__dirs__": {}}
                node = node["__dirs__"][part]
            node["__files__"].append(file)

        def _to_node_list(tree: dict, prefix: str) -> list[DirectoryNode]:
            """Recursively convert dict tree to DirectoryNode list.

            Args:
                tree: Internal dict representation of the tree level.
                prefix: Path prefix for the current level.

            Returns:
                Sorted list of :class:`~backend.app.schemas.scanner.DirectoryNode`.
            """
            nodes: list[DirectoryNode] = []

            # Directory nodes
            for dir_name, subtree in sorted(tree["__dirs__"].items()):
                dir_path = f"{prefix}/{dir_name}" if prefix else dir_name
                children = _to_node_list(subtree, dir_path)
                nodes.append(
                    DirectoryNode(
                        name=dir_name,
                        path=dir_path,
                        is_file=False,
                        children=children,
                    )
                )

            # File nodes
            for file in sorted(tree["__files__"], key=lambda f: f.file_name):
                nodes.append(
                    DirectoryNode(
                        name=file.file_name,
                        path=file.relative_path,
                        is_file=True,
                        language=file.language.value,
                        size_bytes=file.size_bytes,
                        children=[],
                    )
                )

            return nodes

        return _to_node_list(root, "")
