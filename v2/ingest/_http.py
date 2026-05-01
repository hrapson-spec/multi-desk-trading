"""Small HTTP helper for v2 public-data ingesters.

Wraps ``httpx.Client`` with:
- 30s timeout, follow redirects.
- Exponential-backoff retry (3 attempts) on 5xx and connect errors.
- Conditional-GET via ``If-Modified-Since`` / ``If-None-Match``.
- A test-mode kill switch via env var ``V2_INGEST_OFFLINE=1`` so unit tests
  cannot accidentally make a network call.

The dataclass return ``HTTPResponse`` carries enough provenance
(``retrieved_at_utc``, ``etag``, ``last_modified``) for downstream PIT writes.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

# Module-level kill switch. Tests should set V2_INGEST_OFFLINE=1.
OFFLINE_MODE: bool = os.environ.get("V2_INGEST_OFFLINE") == "1"


class HTTPClientError(Exception):
    """Base exception for v2 ingest HTTP layer."""


class OfflineModeError(HTTPClientError):
    """Raised when a network call is attempted while OFFLINE_MODE is set."""


class RetryExhaustedError(HTTPClientError):
    """Raised when retry budget is exhausted on a 5xx or connect error."""


@dataclass
class HTTPResponse:
    """Minimal provenance-carrying HTTP response."""

    status_code: int
    content: bytes
    headers: dict[str, str]
    etag: str | None
    last_modified: str | None
    retrieved_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))


class HTTPClient:
    """Thin httpx wrapper with retry, conditional-GET and offline mode."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        follow_redirects: bool = True,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        self._timeout = timeout
        self._follow_redirects = follow_redirects
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HTTPClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        if_modified_since: str | None = None,
        if_none_match: str | None = None,
    ) -> HTTPResponse:
        """Perform a GET with retry-on-5xx and conditional headers.

        Raises
        ------
        OfflineModeError
            If module-level OFFLINE_MODE is set (test kill switch).
        RetryExhaustedError
            If 5xx or connect errors persist past ``max_retries``.
        """
        if OFFLINE_MODE:
            raise OfflineModeError(
                f"V2_INGEST_OFFLINE=1 blocked outbound GET to {url!r}"
            )

        request_headers: dict[str, str] = dict(headers or {})
        if if_modified_since is not None:
            request_headers["If-Modified-Since"] = if_modified_since
        if if_none_match is not None:
            request_headers["If-None-Match"] = if_none_match

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.get(url, headers=request_headers, params=params)
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    raise RetryExhaustedError(
                        f"connect/read errors on GET {url!r}: {exc!r}"
                    ) from exc
                time.sleep(self._backoff_base * (2**attempt))
                continue

            if 500 <= resp.status_code < 600 and attempt < self._max_retries:
                time.sleep(self._backoff_base * (2**attempt))
                continue

            return HTTPResponse(
                status_code=resp.status_code,
                content=resp.content,
                headers=dict(resp.headers),
                etag=resp.headers.get("ETag"),
                last_modified=resp.headers.get("Last-Modified"),
            )

        # Unreachable in normal flow: loop returns or raises above.
        raise RetryExhaustedError(
            f"retry budget exhausted on GET {url!r}; last error: {last_exc!r}"
        )
