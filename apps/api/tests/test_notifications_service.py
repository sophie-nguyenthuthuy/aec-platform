"""Service tests for `services.notifications.digest_for_user`.

We focus on the *render* contract — given queue of programmable rows
representing a user's last-24h activity, the function must:
  * return None when there are no events (empty digests don't get sent)
  * group events by project in the rendered bodies
  * include each project's name and event count
  * not crash on UTF-8 / HTML-special characters
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


ORG_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class FakeAsyncSession:
    """Minimal session whose execute() returns one programmed result."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    async def execute(self, *_a: Any, **_kw: Any) -> Any:
        r = MagicMock()
        r.mappings.return_value.all.return_value = self._rows
        return r


def _row(**overrides: Any) -> dict:
    base = {
        "id": uuid4(),
        "project_id": uuid4(),
        "module": "pulse",
        "title": "CO #CO-001 — Slab",
        "timestamp": datetime(2026, 4, 26, 9, 30, tzinfo=UTC),
    }
    base.update(overrides)
    return base


# ---------- Empty-window short-circuit ----------


async def test_digest_returns_none_when_no_events():
    """No events in the window → caller must skip emailing."""
    from services.notifications import digest_for_user

    project_id = uuid4()
    session = FakeAsyncSession(rows=[])

    result = await digest_for_user(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        user_id=USER_ID,
        user_email="pm@example.com",
        project_ids_to_names={project_id: "Tower A"},
    )
    assert result is None


async def test_digest_returns_none_when_no_watched_projects():
    """A user with zero watches has nothing to digest — skip the query."""
    from services.notifications import digest_for_user

    session = FakeAsyncSession(rows=[])
    result = await digest_for_user(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        user_id=USER_ID,
        user_email="pm@example.com",
        project_ids_to_names={},
    )
    assert result is None


# ---------- Render contract ----------


async def test_digest_groups_events_by_project_and_counts_them():
    from services.notifications import digest_for_user

    project_a = uuid4()
    project_b = uuid4()
    rows = [
        _row(project_id=project_a, module="pulse", title="CO #1 — A"),
        _row(project_id=project_a, module="siteeye", title="Safety incident: no_ppe"),
        _row(project_id=project_b, module="handover", title="Defect: leak"),
    ]
    session = FakeAsyncSession(rows=rows)

    result = await digest_for_user(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        user_id=USER_ID,
        user_email="pm@example.com",
        project_ids_to_names={project_a: "Tower A", project_b: "Villa B"},
    )

    assert result is not None
    assert result["event_count"] == 3
    # Both project sections must show up in the body.
    assert "Tower A" in result["text_body"]
    assert "Villa B" in result["text_body"]
    assert "Tower A" in result["html_body"]
    assert "Villa B" in result["html_body"]
    # Subject mentions the count so the inbox preview is informative.
    assert "3" in result["subject"]
    # Grouped events for caller inspection.
    assert len(result["events_by_project"][str(project_a)]) == 2
    assert len(result["events_by_project"][str(project_b)]) == 1


async def test_digest_html_escapes_special_characters():
    """HTML body must escape <, >, &, " in event titles to prevent
    accidental tag injection from user-supplied data."""
    from services.notifications import digest_for_user

    project_id = uuid4()
    rows = [_row(project_id=project_id, title='<script>alert("xss")</script>')]
    session = FakeAsyncSession(rows=rows)

    result = await digest_for_user(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        user_id=USER_ID,
        user_email="pm@example.com",
        project_ids_to_names={project_id: "Project & Co"},
    )

    assert result is not None
    html = result["html_body"]
    assert "<script>" not in html, "raw <script> in HTML body — escape failed"
    assert "&lt;script&gt;" in html
    assert "Project &amp; Co" in html


async def test_digest_uses_module_label_in_text_body():
    """`pulse` shouldn't render as the bare slug — display the full label."""
    from services.notifications import digest_for_user

    project_id = uuid4()
    rows = [_row(project_id=project_id, module="pulse", title="Anything")]
    session = FakeAsyncSession(rows=rows)

    result = await digest_for_user(
        session,  # type: ignore[arg-type]
        organization_id=ORG_ID,
        user_id=USER_ID,
        user_email="pm@example.com",
        project_ids_to_names={project_id: "Tower A"},
    )

    assert result is not None
    assert "ProjectPulse" in result["text_body"]
