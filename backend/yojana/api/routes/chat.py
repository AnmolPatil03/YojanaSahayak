"""Streaming chat endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from yojana.agent.orchestrator import ChatRequest
from yojana.api.sse import sse_response

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """Answer one message as a stream of server-sent events."""
    orchestrator = request.app.state.services.orchestrator
    return sse_response(orchestrator.run(body))
