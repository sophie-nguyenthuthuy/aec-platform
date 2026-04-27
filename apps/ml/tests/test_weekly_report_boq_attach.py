"""Unit tests for `_maybe_render_boq_attachment` in the SiteEye pipeline.

Covers four shapes:

  * Approved estimate exists with BOQ rows — returns ReportAttachment
    pointing at the uploaded PDF; render+upload helpers are called.
  * No approved estimate — returns None, no upload, no exception.
  * Approved estimate has zero BOQ rows — returns None, no upload.
  * `services.boq_io` import fails (e.g. reportlab missing in a
    degraded deploy) — returns None, logs, no exception.

The pipeline-level happy path (entire `generate_weekly_report` end-to-
end) lives elsewhere; this module pins the attach-or-skip contract.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


PROJECT_ID = UUID("33333333-3333-3333-3333-333333333333")


# ---------- Fake session ----------


class _FakeSession:
    """Pops `_results` for each `execute()` call. Mirrors the pattern in
    other ML-side tests; chosen over a SQLAlchemy mock because we just
    need to drive `.scalar_one_or_none` and `.scalars().all()` returns."""

    def __init__(self) -> None:
        self._results: list = []

    def push(self, value) -> None:
        self._results.append(value)

    async def execute(self, *_a, **_k):
        result = MagicMock()
        next_value = self._results.pop(0) if self._results else None
        result.scalar_one_or_none.return_value = next_value
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = next_value if isinstance(next_value, list) else []
        result.scalars.return_value = scalars_mock
        # If we pop a list, the caller expects `.scalars().all()` not
        # `.scalar_one_or_none()` — return None for the latter so the
        # router branches correctly.
        if isinstance(next_value, list):
            result.scalar_one_or_none.return_value = None
        return result


def _estimate(**overrides):
    base = dict(
        id=uuid4(),
        project_id=PROJECT_ID,
        name="Tower X — Schematic v1",
        status="approved",
        created_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _boq_item(description: str, qty: float = 100, price: float = 1000) -> SimpleNamespace:
    return SimpleNamespace(
        description=description,
        code="1.1",
        unit="m3",
        quantity=Decimal(str(qty)),
        unit_price_vnd=Decimal(str(price)),
        total_price_vnd=Decimal(str(qty * price)),
        material_code=None,
        sort_order=0,
    )


# ---------- Tests ----------


async def test_returns_attachment_when_approved_estimate_with_items_exists(monkeypatch):
    """Happy path: approved estimate + 2 BOQ items → uploaded PDF + ReportAttachment."""
    from ml.pipelines import siteeye

    session = _FakeSession()
    estimate = _estimate(name="Tower X — schematic v1")
    session.push(estimate)
    session.push([_boq_item("Bê tông C30"), _boq_item("Thép CB500")])

    # Capture the upload — we don't want a real S3 call.
    uploads: list[dict] = []

    async def _capture_put(key, body, *, content_type):
        uploads.append({"key": key, "body": body, "content_type": content_type})

    monkeypatch.setattr(siteeye, "_s3_put", _capture_put)
    # Stub the renderer so the test doesn't pull reportlab.
    monkeypatch.setattr(
        "services.boq_io.render_boq_pdf",
        lambda name, rows: f"%PDF-1.4 stub for {name} ({len(rows)} rows)".encode(),
    )

    result = await siteeye._maybe_render_boq_attachment(
        session, project_id=PROJECT_ID, week_start=date(2026, 4, 27)
    )

    assert result is not None
    assert result.kind == "boq_pdf"
    assert "Tower X" in result.label
    assert result.url.startswith("s3://")
    assert result.url.endswith("-boq.pdf")
    # Date stamp is in the key so reruns overwrite the same week's snapshot.
    assert "2026-04-27-boq.pdf" in result.url

    assert len(uploads) == 1
    assert uploads[0]["content_type"] == "application/pdf"
    assert uploads[0]["body"].startswith(b"%PDF-")


async def test_returns_none_when_no_approved_estimate(monkeypatch, caplog):
    """No approved estimate → None + INFO log; no S3 call."""
    import logging

    from ml.pipelines import siteeye

    session = _FakeSession()
    session.push(None)  # estimate query returns nothing

    s3_calls = []
    monkeypatch.setattr(
        siteeye, "_s3_put", AsyncMock(side_effect=lambda *a, **k: s3_calls.append(a))
    )

    with caplog.at_level(logging.INFO, logger="ml.pipelines.siteeye"):
        result = await siteeye._maybe_render_boq_attachment(
            session, project_id=PROJECT_ID, week_start=date(2026, 4, 27)
        )

    assert result is None
    assert s3_calls == []
    assert any("no approved estimate" in r.getMessage() for r in caplog.records)


async def test_returns_none_when_estimate_has_no_boq_items(monkeypatch, caplog):
    """Approved estimate exists but BOQ is empty (corrupt / mid-import) → None."""
    import logging

    from ml.pipelines import siteeye

    session = _FakeSession()
    session.push(_estimate())
    session.push([])  # zero items

    monkeypatch.setattr(siteeye, "_s3_put", AsyncMock())

    with caplog.at_level(logging.INFO, logger="ml.pipelines.siteeye"):
        result = await siteeye._maybe_render_boq_attachment(
            session, project_id=PROJECT_ID, week_start=date(2026, 4, 27)
        )

    assert result is None
    assert any("no BOQ items" in r.getMessage() for r in caplog.records)


async def test_returns_none_when_boq_io_import_fails(monkeypatch, caplog):
    """Missing services.boq_io must degrade gracefully — log + return None."""
    import logging
    import sys

    from ml.pipelines import siteeye

    session = _FakeSession()
    session.push(_estimate())
    session.push([_boq_item("x")])

    # Force the local `from services.boq_io import …` to raise.
    monkeypatch.setitem(sys.modules, "services.boq_io", None)

    with caplog.at_level(logging.WARNING, logger="ml.pipelines.siteeye"):
        result = await siteeye._maybe_render_boq_attachment(
            session, project_id=PROJECT_ID, week_start=date(2026, 4, 27)
        )

    assert result is None
    assert any("services.boq_io missing" in r.getMessage() for r in caplog.records)
