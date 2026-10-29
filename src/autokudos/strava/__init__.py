"""Klient wewnętrznych endpointów web Stravy."""

from __future__ import annotations

from autokudos.strava.client import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    StravaClient,
    StravaError,
    StravaHTTPError,
    StravaNetworkError,
    StravaParseError,
)

__all__ = [
    "AuthError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "StravaClient",
    "StravaError",
    "StravaHTTPError",
    "StravaNetworkError",
    "StravaParseError",
]
