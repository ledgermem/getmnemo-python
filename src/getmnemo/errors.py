"""Typed exceptions raised by the Mnemo SDK."""

from __future__ import annotations

from typing import Any


class MnemoError(Exception):
    """Base class for all SDK errors."""


class MnemoHTTPError(MnemoError):
    """Raised when the API returns a non-2xx response.

    The original response body is preserved on `body` for debugging.
    """

    def __init__(self, message: str, status: int, body: Any = None) -> None:
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.body = body
