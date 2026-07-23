"""Duplicate qualified-name detection for the Symbol Index.

When multiple parser outputs produce symbols with the same qualified name
(e.g. method overloads in Java, or repeated symbols from multiple parse
passes), the :class:`DuplicateDetector` decides which entry wins and logs
the collision.

Deduplication strategy:
    - Within a single file batch: the first occurrence wins; subsequent
      occurrences with the same ``qualified_name`` are dropped and counted.
    - Across repository re-indexes: the upsert layer handles collisions via
      ``ON CONFLICT DO UPDATE`` on ``(repository_id, qualified_name)``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from backend.app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DuplicateStats:
    """Statistics produced by one deduplication pass.

    Attributes:
        total_input: Number of entries before deduplication.
        unique_entries: Number of unique entries after deduplication.
        duplicate_count: Number of duplicate entries dropped.
        collisions: Mapping of qualified_name → collision count.
    """

    total_input: int = 0
    unique_entries: int = 0
    duplicate_count: int = 0
    collisions: dict[str, int] = field(default_factory=dict)


class DuplicateDetector:
    """Detects and removes duplicate symbols within a batch.

    This class is stateless between calls; each :meth:`deduplicate` call
    is independent and safe for concurrent use.

    Example::

        detector = DuplicateDetector()
        unique, stats = detector.deduplicate(entries, key_fn=lambda e: e.qualified_name)
    """

    @staticmethod
    def deduplicate(
        entries: list,
        *,
        key_fn: "callable[[object], str]",
        context: str = "",
    ) -> "tuple[list, DuplicateStats]":
        """Remove duplicate entries, keeping the first occurrence of each key.

        Args:
            entries: A list of objects to deduplicate.
            key_fn: A callable that returns the deduplication key string
                for an entry (typically its ``qualified_name``).
            context: Optional context label for log messages
                (e.g. a file path or repository ID).

        Returns:
            A tuple of ``(unique_entries, stats)`` where:
            - ``unique_entries`` is the deduplicated list (preserving insertion order).
            - ``stats`` is a :class:`DuplicateStats` summary.
        """
        seen: dict[str, int] = {}  # key → first-seen index
        unique: list = []
        collision_counts: dict[str, int] = defaultdict(int)

        for entry in entries:
            key = key_fn(entry)
            if key not in seen:
                seen[key] = len(unique)
                unique.append(entry)
            else:
                collision_counts[key] += 1

        total_duplicates = sum(collision_counts.values())

        if total_duplicates > 0:
            logger.warning(
                "Duplicate qualified names detected",
                context=context,
                duplicate_count=total_duplicates,
                affected_names=len(collision_counts),
            )
            for qname, count in list(collision_counts.items())[:10]:  # log first 10
                logger.debug(
                    "Duplicate symbol",
                    qualified_name=qname,
                    collision_count=count,
                    context=context,
                )

        stats = DuplicateStats(
            total_input=len(entries),
            unique_entries=len(unique),
            duplicate_count=total_duplicates,
            collisions=dict(collision_counts),
        )

        return unique, stats
