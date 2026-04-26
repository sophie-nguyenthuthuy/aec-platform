"""AI assistant: project-scoped chat backed by every module's roll-up."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import ok
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from schemas.assistant import AskRequest, AssistantResponse
from services.assistant import ask as assistant_ask

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


@router.post("/projects/{project_id}/ask")
async def ask_about_project(
    project_id: UUID,
    payload: AskRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Answer a natural-language question about one of the caller's projects.

    The assistant builds context from every module's roll-up (tasks,
    change orders, RFIs, defects, safety incidents, recent activity) and
    sends it to Claude. The client owns conversation history and replays
    it on each turn — keeps the API stateless.

    A 404 is returned for cross-tenant project IDs (or unknown ones) so
    the caller doesn't leak whether a project exists in another org.
    """
    response: AssistantResponse = await assistant_ask(
        db,
        organization_id=auth.organization_id,
        project_id=project_id,
        request=payload,
    )

    if response.answer == "Project not found.":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    return ok(response.model_dump(mode="json"))
