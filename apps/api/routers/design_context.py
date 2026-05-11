"""Design Context Generator router.

POST /api/v1/design/context/stream
  SSE stream for one turn of the architectural brief conversation.

Wire format:
  event: token     → {"delta": "..."}
  event: questions → {"questions": [...]}
  event: svg       → {"svg": "..."}
  event: done      → DesignContextDone JSON
  event: error     → {"message": "..."}
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from middleware.auth import AuthContext, require_auth
from schemas.design_context import DesignContextRequest
from services.design_context import generate_design_context_stream

router = APIRouter(prefix="/api/v1/design", tags=["design"])


@router.post("/context/stream")
async def design_context_stream(
    payload: DesignContextRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Stream a design-context conversation turn as SSE.

    The client sends the latest user message plus the full conversation
    history. The server streams back:
      1. Text tokens (the AI's prose response)
      2. Follow-up question chips (when still gathering info)
      3. SVG site context diagram (when ready to generate)
      4. A terminal `done` event with the structured design brief
    """
    _ = auth  # authenticated; no per-org cost gate for now

    generator = generate_design_context_stream(payload)
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
