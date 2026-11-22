"""HTTP client for the MeSquareAssistantBot streaming (SSE) API."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Generous read timeout: the bot streams tokens as they are generated, so
# long gaps between events are possible while the model is thinking.
STREAM_TIMEOUT_SECONDS = 120.0


def _bot_headers() -> dict[str, str]:
    headers = {"Accept": "text/event-stream"}
    if settings.assistant_bot_api_key:
        headers["Authorization"] = f"Bearer {settings.assistant_bot_api_key}"
    return headers


def _parse_data(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


async def stream_assistant_bot(payload: dict[str, Any]) -> AsyncIterator[tuple[str, Any]]:
    """POST a ChatRequest to the assistant bot and yield (event, data) pairs.

    The bot replies with an SSE stream; each block carries an event name and
    a JSON data payload. This function normalizes the stream into parsed
    events so callers never deal with SSE framing. Raises httpx.HTTPError
    subclasses on connection failures or non-200 responses; the caller
    decides how to surface those to the client.
    """
    timeout = httpx.Timeout(STREAM_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", settings.assistant_bot_url, json=payload, headers=_bot_headers()
        ) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", errors="replace")
                logger.error(
                    "Assistant bot returned %s: %s",
                    response.status_code,
                    body[:500],
                )
                raise httpx.HTTPStatusError(
                    f"Assistant bot returned status {response.status_code}.",
                    request=response.request,
                    response=response,
                )

            current_event = "message"
            data_lines: list[str] = []

            def _flush() -> tuple[str, Any] | None:
                nonlocal current_event, data_lines
                if not data_lines and current_event == "message":
                    return None
                raw = "\n".join(data_lines).strip()
                event, data = current_event, (_parse_data(raw) if raw else None)
                current_event, data_lines = "message", []
                return event, data

            async for line in response.aiter_lines():
                if not line.strip():
                    pending = _flush()
                    if pending is not None:
                        yield pending
                    continue
                if line.startswith("event:"):
                    current_event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())

            # Some servers omit the trailing blank line after the last event.
            pending = _flush()
            if pending is not None:
                yield pending