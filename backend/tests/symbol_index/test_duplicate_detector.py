"""Tests for the DuplicateDetector.

Verifies that deduplication keeps first occurrence, counts collisions,
and returns correct statistics.
"""

from __future__ import annotations

import pytest

from backend.app.symbol_index.validators.duplicates import DuplicateDetector, DuplicateStats


class _Entry:
    """Minimal stub for a symbol entry used in tests."""

    def __init__(self, qualified_name: str, value: str = "") -> None:
        self.qualified_name = qualified_name
        self.value = value


def _key(entry: _Entry) -> str:
    return entry.qualified_name


class TestDuplicateDetectorNoDuplicates:
    """Verify behaviour when all entries are unique."""

    def test_all_entries_preserved(self) -> None:
        entries = [
            _Entry("app.auth.AuthService.login"),
            _Entry("app.auth.AuthService.logout"),
            _Entry("app.users.UserService.get"),
        ]
        unique, stats = DuplicateDetector.deduplicate(entries, key_fn=_key)
        assert len(unique) == 3
        assert stats.duplicate_count == 0
        assert stats.total_input == 3
        assert stats.unique_entries == 3

    def test_empty_list(self) -> None:
        unique, stats = DuplicateDetector.deduplicate([], key_fn=_key)
        assert unique == []
        assert stats.total_input == 0
        assert stats.unique_entries == 0
        assert stats.duplicate_count == 0


class TestDuplicateDetectorWithDuplicates:
    """Verify deduplication keeps first occurrence."""

    def test_first_occurrence_kept(self) -> None:
        first = _Entry("app.auth.login", value="first")
        second = _Entry("app.auth.login", value="second")
        unique, stats = DuplicateDetector.deduplicate([first, second], key_fn=_key)
        assert len(unique) == 1
        assert unique[0].value == "first"

    def test_duplicate_count_correct(self) -> None:
        entries = [
            _Entry("app.auth.login"),
            _Entry("app.auth.login"),   # dup 1
            _Entry("app.auth.login"),   # dup 2
            _Entry("app.auth.logout"),
        ]
        unique, stats = DuplicateDetector.deduplicate(entries, key_fn=_key)
        assert len(unique) == 2
        assert stats.duplicate_count == 2
        assert stats.total_input == 4
        assert stats.unique_entries == 2

    def test_collisions_dict_populated(self) -> None:
        entries = [
            _Entry("app.A"),
            _Entry("app.A"),
            _Entry("app.B"),
            _Entry("app.B"),
            _Entry("app.B"),
        ]
        _, stats = DuplicateDetector.deduplicate(entries, key_fn=_key)
        assert stats.collisions["app.A"] == 1
        assert stats.collisions["app.B"] == 2

    def test_order_preserved(self) -> None:
        entries = [_Entry(f"app.symbol_{i}") for i in range(5)]
        unique, _ = DuplicateDetector.deduplicate(entries, key_fn=_key)
        names = [e.qualified_name for e in unique]
        assert names == [f"app.symbol_{i}" for i in range(5)]

    def test_context_label_accepted(self) -> None:
        """Context string must not cause any exception."""
        entries = [_Entry("app.A"), _Entry("app.A")]
        unique, stats = DuplicateDetector.deduplicate(
            entries, key_fn=_key, context="test/file.py"
        )
        assert stats.duplicate_count == 1


class TestDuplicateStatsDefaults:
    """Verify DuplicateStats dataclass defaults."""

    def test_default_values(self) -> None:
        stats = DuplicateStats()
        assert stats.total_input == 0
        assert stats.unique_entries == 0
        assert stats.duplicate_count == 0
        assert stats.collisions == {}
