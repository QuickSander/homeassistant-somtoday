"""Exception hierarchy for the SomToday integration.

The hierarchy mirrors the error mapping described in
``docs/architecture.md`` section 5.1. Keeping it in a dedicated module avoids
circular imports between the authentication and transport layers.
"""

from __future__ import annotations


class SomTodayError(Exception):
    """Base class for all SomToday errors."""


class SomTodayConnectionError(SomTodayError):
    """Raised when SomToday cannot be reached or times out."""


class SomTodayAuthError(SomTodayError):
    """Raised when authentication or token refresh fails."""


class SomtodayInvalidAuth(SomTodayAuthError):
    """Raised on a definitive OAuth2 rejection (``invalid_grant``/state).

    Only an HTTP 400 with ``error=invalid_grant`` or a ``state`` mismatch is
    definitive: reusing the same code or state can never succeed, so the user
    must restart the browser login instead of retrying the exchange.
    """


class SomTodayApiError(SomTodayError):
    """Raised for unexpected API responses or malformed payloads."""


class SomTodayRateLimitError(SomTodayApiError):
    """Raised when SomToday returns HTTP 429 (rate limit)."""
