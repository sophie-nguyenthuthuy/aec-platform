"""Schemas for the Design Context (Bản vẽ context) generator."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"


class ChatTurn(BaseModel):
    role: ChatRole
    content: str


class DesignContextRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


class DesignBrief(BaseModel):
    project_type: str | None = None
    location: str | None = None
    site_area: str | None = None
    site_dimensions: str | None = None
    orientation: str | None = None
    floors: int | None = None
    style: str | None = None
    budget: str | None = None
    special_requirements: list[str] = []


class DesignContextDone(BaseModel):
    stage: str
    brief: DesignBrief | None = None
    follow_up_questions: list[str] = []
    svg_diagram: str | None = None
