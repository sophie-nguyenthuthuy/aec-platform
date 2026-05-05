"""Schemas for the cross-module search endpoint."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Provenance of a hybrid-search result. Set by `_rrf_fuse` based on
# which retrieval arm(s) produced the row:
#   * "keyword" — only the ILIKE arm hit
#   * "vector"  — only the pgvector arm hit
#   * "both"    — RRF fused contributions from both arms
#   * None      — keyword-only scope (defects, proposals) or no
#                  embedding key configured. Distinguishes "we tried
#                  vector and it didn't match" from "we never tried".
MatchedOn = Literal["keyword", "vector", "both"]


class SearchScope(StrEnum):
    """Modules the search can fan out across. Each maps to one backend
    function in `services/search.py`. Adding a scope is one entry here +
    one function there + one test."""

    documents = "documents"  # Drawbridge drawings + uploaded docs
    regulations = "regulations"  # CodeGuard reference catalogue
    defects = "defects"  # Handover snag-list
    rfis = "rfis"  # Drawbridge RFIs
    proposals = "proposals"  # WinWork proposals


class SearchRequest(BaseModel):
    """Cross-module search query.

    `scopes` is optional — omit to search every supported module.
    `project_id` narrows the result set to one project (only honored by
    scopes that have a project_id column; regulations are global).
    """

    query: str = Field(min_length=2, max_length=200)
    scopes: list[SearchScope] | None = Field(
        default=None,
        description="Modules to search. None = all.",
    )
    project_id: UUID | None = Field(
        default=None,
        description="Optional project filter. Ignored by global scopes (regulations).",
    )
    limit: int = Field(default=20, ge=1, le=100)


class SearchResult(BaseModel):
    """One match. The `route` field is the in-app deep link the
    frontend opens on click (e.g. `/handover?defect_id=<uuid>`)."""

    scope: SearchScope
    id: UUID
    title: str
    # Optional contextual line — defect description, RFI subject, etc.
    # Rendered as a single muted line under the title.
    snippet: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    # ILIKE matches don't produce a meaningful relevance score, so for
    # the keyword MVP we just rank by recency (`created_at DESC`). The
    # `score` field is a placeholder so the response shape is forward-
    # compatible with a hybrid (keyword + pgvector) ranker.
    score: float = 1.0
    # Which retrieval arm(s) produced this row. None when the scope
    # has no vector arm at all (defects/proposals) — distinguishes
    # "keyword-only scope" from "vector found nothing".
    matched_on: MatchedOn | None = None
    route: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResult]
