"""Unit tests for the repository Pydantic schemas.

Validates URL parsing, normalisation, and rejection of invalid inputs.
No database or network connections are required.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.repository import RepositoryCreateRequest


class TestRepositoryCreateRequest:
    """Tests for RepositoryCreateRequest URL validation."""

    # ── Valid URLs ─────────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "url, expected_normalised",
        [
            (
                "https://github.com/octocat/Hello-World",
                "https://github.com/octocat/Hello-World",
            ),
            (
                "https://github.com/octocat/Hello-World.git",
                "https://github.com/octocat/Hello-World",
            ),
            (
                "https://github.com/my-org/my.repo",
                "https://github.com/my-org/my.repo",
            ),
            (
                "https://github.com/owner_123/repo-name_456",
                "https://github.com/owner_123/repo-name_456",
            ),
        ],
    )
    def test_valid_url_accepted_and_normalised(self, url: str, expected_normalised: str) -> None:
        """Valid GitHub URLs should be accepted and normalised (no trailing .git)."""
        req = RepositoryCreateRequest(github_url=url)
        assert req.github_url == expected_normalised

    def test_dot_git_suffix_stripped(self) -> None:
        """Trailing .git suffix must be removed during normalisation."""
        req = RepositoryCreateRequest(github_url="https://github.com/org/repo.git")
        assert not req.github_url.endswith(".git")

    # ── Owner / name extraction ───────────────────────────────────────────────

    def test_parsed_owner(self) -> None:
        req = RepositoryCreateRequest(github_url="https://github.com/octocat/hello")
        assert req.parsed_owner == "octocat"

    def test_parsed_name(self) -> None:
        req = RepositoryCreateRequest(github_url="https://github.com/octocat/hello-world.git")
        assert req.parsed_name == "hello-world"

    # ── Invalid URLs ──────────────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "bad_url",
        [
            "http://github.com/owner/repo",          # HTTP not HTTPS
            "https://gitlab.com/owner/repo",          # wrong host
            "https://github.com/owner",               # missing repo name
            "https://github.com/",                    # missing owner and name
            "github.com/owner/repo",                  # no scheme
            "https://github.com/owner/repo/extra",    # too many path segments
            "not_a_url",
            "",
        ],
    )
    def test_invalid_url_rejected(self, bad_url: str) -> None:
        """URLs that don't match the accepted pattern must raise ValidationError."""
        with pytest.raises(ValidationError):
            RepositoryCreateRequest(github_url=bad_url)

    # ── reclone flag ──────────────────────────────────────────────────────────

    def test_reclone_defaults_to_false(self) -> None:
        req = RepositoryCreateRequest(github_url="https://github.com/a/b")
        assert req.reclone is False

    def test_reclone_can_be_set_true(self) -> None:
        req = RepositoryCreateRequest(github_url="https://github.com/a/b", reclone=True)
        assert req.reclone is True
