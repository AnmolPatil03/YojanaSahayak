"""Server-sent events helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


def format_sse(event: str, data: Any) -> bytes:
    """Encode one SSE frame. Data is JSON on a single line."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode()


async def encode_events(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[bytes]:
    """Turn orchestrator events into SSE bytes; unexpected errors become an error event."""
    try:
        async for item in events:
            yield format_sse(item["event"], item["data"])
    except Exception:
        logger.exception("Chat stream failed")
        yield format_sse(
            "error",
            {"code": "internal_error", "message": "Something went wrong while answering."},
        )
        yield format_sse("done", {"error": True})


def sse_response(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    return StreamingResponse(
        encode_events(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
