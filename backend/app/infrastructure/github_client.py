"""GitHub REST API client for repository metadata extraction.

Provides a thin async wrapper around the GitHub v3 REST API.
All network I/O is performed via ``httpx.AsyncClient`` with retry
logic powered by ``tenacity``.

Only the metadata fields needed by the Repository Management module
are fetched — no code content is downloaded here.
"""

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.app.core.config import get_settings
from backend.app.core.exceptions import ExternalServiceError, RepositoryAccessError
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class GitHubRepoMetadata:
    """Value object holding metadata returned by the GitHub API.

    Attributes:
        name: Repository name.
        owner: Repository owner login.
        full_name: ``owner/name``.
        description: Repository description (may be ``None``).
        default_branch: Primary branch name (e.g. ``main``).
        visibility: ``"public"`` or ``"private"``.
        language: Primary programming language (may be ``None``).
        stars: Stargazer count.
        forks: Fork count.
        private: Whether the repository is private.
        clone_url: HTTPS clone URL.
    """

    __slots__ = (
        "name",
        "owner",
        "full_name",
        "description",
        "default_branch",
        "visibility",
        "language",
        "stars",
        "forks",
        "private",
        "clone_url",
    )

    def __init__(
        self,
        *,
        name: str,
        owner: str,
        full_name: str,
        description: str | None,
        default_branch: str,
        visibility: str,
        language: str | None,
        stars: int,
        forks: int,
        private: bool,
        clone_url: str,
    ) -> None:
        self.name = name
        self.owner = owner
        self.full_name = full_name
        self.description = description
        self.default_branch = default_branch
        self.visibility = visibility
        self.language = language
        self.stars = stars
        self.forks = forks
        self.private = private
        self.clone_url = clone_url


class GitHubClient:
    """Async GitHub REST API client.

    Args:
        base_url: GitHub API base URL (defaults to ``https://api.github.com``).
        token: Optional Personal Access Token for authentication.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.repository.github_api_base_url).rstrip("/")
        self._token = token or settings.repository.github_token
        self._timeout = timeout

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def get_repository(self, owner: str, name: str) -> GitHubRepoMetadata:
        """Fetch repository metadata from the GitHub REST API.

        Args:
            owner: Repository owner login.
            name: Repository name.

        Returns:
            :class:`GitHubRepoMetadata` populated from the API response.

        Raises:
            RepositoryAccessError: When the repo is private / 404 / 403.
            ExternalServiceError: For unexpected API failures or timeouts.
        """
        url = f"/repos/{owner}/{name}"
        logger.info(
            "Fetching GitHub repository metadata",
            owner=owner,
            name=name,
            url=url,
        )

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            logger.warning(
                "GitHub API request timed out",
                owner=owner,
                name=name,
                error=str(exc),
            )
            raise ExternalServiceError(
                "GitHub API", f"Request timed out after {self._timeout}s"
            ) from exc
        except httpx.TransportError as exc:
            logger.warning(
                "GitHub API transport error",
                owner=owner,
                name=name,
                error=str(exc),
            )
            raise ExternalServiceError("GitHub API", str(exc)) from exc

        if response.status_code in (401, 403, 404):
            logger.warning(
                "GitHub API access denied or not found",
                owner=owner,
                name=name,
                status_code=response.status_code,
            )
            raise RepositoryAccessError(f"https://github.com/{owner}/{name}")

        if response.status_code != 200:
            logger.error(
                "GitHub API returned unexpected status",
                owner=owner,
                name=name,
                status_code=response.status_code,
                body=response.text[:256],
            )
            raise ExternalServiceError(
                "GitHub API",
                f"Unexpected status code {response.status_code}",
            )

        data: dict = response.json()

        logger.info(
            "GitHub metadata extracted",
            owner=owner,
            name=name,
            stars=data.get("stargazers_count", 0),
            language=data.get("language"),
            default_branch=data.get("default_branch", "main"),
        )

        return GitHubRepoMetadata(
            name=data["name"],
            owner=data["owner"]["login"],
            full_name=data["full_name"],
            description=data.get("description"),
            default_branch=data.get("default_branch", "main"),
            visibility=data.get("visibility", "public"),
            language=data.get("language"),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            private=data.get("private", False),
            clone_url=data.get("clone_url", f"https://github.com/{owner}/{name}.git"),
        )


# ── Module-level singleton ─────────────────────────────────────────────────────
# Created lazily on first call so tests can override get_settings() first.

_github_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    """Return (or lazily create) the shared :class:`GitHubClient` instance.

    Returns:
        GitHubClient: The shared client singleton.
    """
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client


async def close_github_client() -> None:
    """Close and reset the shared client. Called at application shutdown."""
    global _github_client
    if _github_client is not None:
        await _github_client.close()
        _github_client = None
