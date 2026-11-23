"""HTTP client for the MeSquareMLEngine service.

The ML Engine is a *separate* running service (not something this backend spins
up). This client is the only place that knows how to talk to it: it posts the
twin-state payload and wraps transport failures in typed errors that the service
layer can translate into clean HTTP responses.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class MLEngineError(Exception):
    """Base error for any failure talking to the ML Engine."""


class MLEngineTimeout(MLEngineError):
    """The ML Engine did not respond within the configured timeout."""


class MLEngineUnavailable(MLEngineError):
    """The ML Engine could not be reached (connection refused, DNS, etc.)."""


class MLEngineResponseError(MLEngineError):
    """The ML Engine responded with a non-2xx status.

    Attributes:
        status_code: The HTTP status returned by the ML Engine.
        detail: The response body text, when available.
    """

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"ML Engine returned HTTP {status_code}: {detail}")


class MLEngineClient:
    """Thin async client over the ML Engine's HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ml_engine_url).rstrip("/")
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.ml_engine_timeout_seconds
        )

    async def get_health(self) -> dict[str, Any]:
        """Return the ML Engine's health payload.

        Raises:
            MLEngineTimeout: The request timed out.
            MLEngineUnavailable: The engine could not be reached.
            MLEngineResponseError: The engine returned a non-2xx status.
        """
        return await self._request("GET", "/health")

    async def post_twin_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a twin-state request and return the parsed JSON response.

        Args:
            payload: The body for ``POST /v1/twin/state`` -- user_id, profile,
                records and as_of, already translated by the adapter.

        Raises:
            MLEngineTimeout: The request timed out.
            MLEngineUnavailable: The engine could not be reached.
            MLEngineResponseError: The engine returned a non-2xx status (e.g. a
                422 validation error or a 503 when the model is not loaded).
        """
        return await self._request("POST", "/v1/twin/state", json=payload)

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, json=json)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise MLEngineTimeout(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text
            except Exception:  # pragma: no cover - body read is best-effort
                pass
            raise MLEngineResponseError(exc.response.status_code, body) from exc
        except httpx.RequestError as exc:
            raise MLEngineUnavailable(str(exc)) from exc
