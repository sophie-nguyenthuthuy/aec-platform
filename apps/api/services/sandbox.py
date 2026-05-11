"""Synthetic-data layer for test-mode API keys.

A request authenticated with a `mode='test'` key gets routed here
instead of hitting real org data. Lets a partner build their
integration end-to-end (parse responses, handle pagination, retry
errors) without any production rows existing.

V1 scope:
  * Read-only fixtures for projects / defects / RFIs / suppliers.
  * Mutations (POST/PATCH/DELETE) accept the request and return a
    202 with `{"status": "accepted_test_mode"}` — no DB write. Lets
    the partner exercise their write path without polluting real
    data.

Design choices:
  * **In-process Python fixtures.** Not stored in DB. Restartable,
    deterministic across deploys, no migration when fixture data
    changes. The downside (every replica has the same data) is
    irrelevant for what is essentially a documentation surface.
  * **Stable IDs.** All UUIDs are pinned literals so a partner can
    write `assert response.id == "00000000-…"` in their integration
    test and it'll keep passing across our deploys.
  * **Mode-aware routing lives in handlers, not here.** A handler
    that wants test-mode support imports `is_test_mode(auth)` and
    branches. Most handlers don't need it (test traffic for those
    endpoints just gets the live response, which is fine because
    test orgs are real orgs with real RLS — the synthetic data is
    additive).

Why no DB write for mutations:
  * The partner's mental model is "test mode = ephemeral". A POST
    that persists would be confusing — does it survive restart?
    appear in `GET /projects`? collide with another partner?
  * Telemetry is unaffected: api_key_calls still fires, so
    /admin/api-usage shows test traffic. Operators can tell test
    activity apart by joining api_keys.mode.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from middleware.auth import AuthContext

# Pinned UUIDs — partners can hardcode these in their integration
# tests. Format chosen to be obviously synthetic at a glance.
SAMPLE_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000001")
SAMPLE_DEFECT_ID = UUID("00000000-0000-0000-0000-000000000010")
SAMPLE_RFI_ID = UUID("00000000-0000-0000-0000-000000000020")
SAMPLE_SUPPLIER_ID = UUID("00000000-0000-0000-0000-000000000030")


# Frozen "now" for deterministic responses. Partners' integration
# tests can pin against this exact timestamp.
SAMPLE_TIMESTAMP = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def is_test_mode(auth: AuthContext) -> bool:
    """True iff the caller is an api-key in test mode.

    The `mode` flows from `api_keys.mode` (migration 0033) into
    `AuthContext.api_key_mode` via `_api_key_auth`. User-JWT callers
    always read "live" by default — there's no UI affordance to
    "browse test data" as a logged-in user.
    """
    if auth.role != "api_key":
        return False
    return auth.api_key_mode == "test"


# ---------- Fixture content ----------


def sample_projects() -> list[dict[str, Any]]:
    """Three projects spanning the lifecycle stages partners are
    most likely to filter on (planning, construction, completed) so
    a `?status=construction` filter test returns at least one row."""
    return [
        {
            "id": str(SAMPLE_PROJECT_ID),
            "external_id": "TEST-P-001",
            "name": "Sample Tower A (test)",
            "type": "office",
            "status": "construction",
            "address": {"city": "Hà Nội", "district": "Cầu Giấy"},
            "area_sqm": 1200.0,
            "budget_vnd": 5_000_000_000,
            "floors": 12,
            "start_date": "2026-01-01",
            "end_date": None,
            "created_at": SAMPLE_TIMESTAMP.isoformat(),
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "external_id": "TEST-P-002",
            "name": "Sample Villa (test)",
            "type": "residential",
            "status": "planning",
            "address": {"city": "TP. Hồ Chí Minh", "district": "Quận 7"},
            "area_sqm": 320.0,
            "budget_vnd": 800_000_000,
            "floors": 3,
            "start_date": None,
            "end_date": None,
            "created_at": SAMPLE_TIMESTAMP.isoformat(),
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "external_id": "TEST-P-003",
            "name": "Sample Warehouse (test)",
            "type": "industrial",
            "status": "completed",
            "address": {"city": "Bình Dương", "district": "Thuận An"},
            "area_sqm": 4500.0,
            "budget_vnd": 12_000_000_000,
            "floors": 1,
            "start_date": "2025-03-01",
            "end_date": "2025-12-15",
            "created_at": SAMPLE_TIMESTAMP.isoformat(),
        },
    ]


def sample_defects() -> list[dict[str, Any]]:
    """Two defects on the construction-stage project. One open, one
    resolved — covers the typical UI partial filters."""
    return [
        {
            "id": str(SAMPLE_DEFECT_ID),
            "project_id": str(SAMPLE_PROJECT_ID),
            "title": "Sample defect — leak in basement (test)",
            "description": "Water ingress at corner B-3.",
            "priority": "high",
            "status": "open",
            "reported_at": SAMPLE_TIMESTAMP.isoformat(),
            "resolved_at": None,
        },
        {
            "id": "00000000-0000-0000-0000-000000000011",
            "project_id": str(SAMPLE_PROJECT_ID),
            "title": "Sample defect — paint peeling (test)",
            "description": "South facade, levels 3-5.",
            "priority": "low",
            "status": "resolved",
            "reported_at": SAMPLE_TIMESTAMP.isoformat(),
            "resolved_at": SAMPLE_TIMESTAMP.isoformat(),
        },
    ]


def sample_rfis() -> list[dict[str, Any]]:
    return [
        {
            "id": str(SAMPLE_RFI_ID),
            "project_id": str(SAMPLE_PROJECT_ID),
            "number": "RFI-001",
            "subject": "Sample RFI — door schedule clarification (test)",
            "description": "Need exterior door fire rating spec for B-1.",
            "status": "open",
            "priority": "normal",
            "created_at": SAMPLE_TIMESTAMP.isoformat(),
        },
    ]


def sample_suppliers() -> list[dict[str, Any]]:
    return [
        {
            "id": str(SAMPLE_SUPPLIER_ID),
            "external_id": "TEST-S-001",
            "name": "Acme Cement (test)",
            "categories": ["cement", "concrete"],
            "provinces": ["HN", "HP"],
            "verified": True,
            "rating": "4.5",
            "created_at": SAMPLE_TIMESTAMP.isoformat(),
        },
    ]


def stub_mutation_response(*, action: str) -> dict[str, Any]:
    """Generic 202-shaped response for write paths in test mode. The
    partner exercises their POST/PATCH/DELETE code without polluting
    real data."""
    return {
        "status": "accepted_test_mode",
        "action": action,
        "note": (
            "Test-mode keys do not persist mutations. Switch to a live "
            "key (or POST against a sandbox org) to observe DB writes."
        ),
    }
