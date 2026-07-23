"""Sample Python code used by parser tests.

This file is intentionally a real Python source file — it is both
the test fixture and a parseable Python file, validating that the
Python parser can handle its own fixture files.
"""

from __future__ import annotations

import os
from typing import Optional

# A module-level constant
MAX_RETRIES: int = 3

# A module-level variable
default_timeout = 30


class BaseHandler:
    """Base HTTP handler.

    Provides common utilities for request handling.
    """

    status_code: int = 200

    def __init__(self, name: str, timeout: int = 30) -> None:
        """Initialise the handler.

        Args:
            name: Handler name.
            timeout: Request timeout in seconds.
        """
        self.name = name
        self.timeout = timeout

    def handle(self, request: dict) -> dict:
        """Process a request.

        Args:
            request: Incoming request dict.

        Returns:
            Response dict.
        """
        return {"status": self.status_code, "handler": self.name}

    @staticmethod
    def validate(data: dict) -> bool:
        """Validate request data.

        Args:
            data: Data to validate.

        Returns:
            True if valid.
        """
        return bool(data)

    @classmethod
    def from_env(cls) -> "BaseHandler":
        """Create handler from environment variables.

        Returns:
            New BaseHandler instance.
        """
        return cls(name=os.getenv("HANDLER_NAME", "default"))


class AuthHandler(BaseHandler):
    """Authenticated request handler extending BaseHandler."""

    def __init__(self, name: str, token: str) -> None:
        super().__init__(name)
        self.token = token

    def handle(self, request: dict) -> dict:
        if not self.token:
            return {"status": 401, "error": "Unauthorized"}
        return super().handle(request)


async def fetch_data(url: str, timeout: Optional[int] = None) -> dict:
    """Fetch data from a URL asynchronously.

    Args:
        url: Target URL.
        timeout: Optional timeout override.

    Returns:
        Parsed response data.
    """
    effective_timeout = timeout or default_timeout
    return {"url": url, "timeout": effective_timeout}


def _internal_helper(value: str) -> str:
    """Private helper function.

    Args:
        value: Input value.

    Returns:
        Processed value.
    """
    return value.strip().lower()
