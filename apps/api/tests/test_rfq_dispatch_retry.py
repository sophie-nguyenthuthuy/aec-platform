"""Unit tests for the inline retry + idempotency in `services.rfq_dispatch`.

Covers two scopes:

  1. `_send_with_retry` — pure transport-retry primitive. Tests
     exercise every branch (success first try, transient retry succeeds,
     all attempts fail, smtp-not-configured short-circuit).
  2. Idempotent `dispatch_rfq` re-call — when a slot is already
     `dispatched` or `responded`, a re-enqueue must not re-email
     that supplier.

The hourly `retry_bounced_rfqs_cron` is tested in `test_scraper_queue.py`
alongside the other arq cron jobs (its DB query + enqueue plumbing).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.asyncio


# ---------- _send_with_retry primitive ----------


def _delivery(*, delivered: bool, reason: str | None = None, to: str = "x@y") -> dict:
    return {
        "to": to,
        "subject": "RFQ test",
        "delivered": delivered,
        "reason": reason,
        "dispatched_at": datetime.now(UTC).isoformat(),
    }


async def test_send_with_retry_returns_first_success_no_backoff(monkeypatch):
    from services import rfq_dispatch

    calls = []

    async def _fake_send(*, to, subject, text_body, html_body=None):
        calls.append(to)
        return _delivery(delivered=True, to=to)

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)
    sleep_calls: list[float] = []
    monkeypatch.setattr(rfq_dispatch.asyncio, "sleep", AsyncMock(side_effect=lambda d: sleep_calls.append(d)))

    delivery, attempts = await rfq_dispatch._send_with_retry(to="x@y", subject="s", text_body="b")
    assert delivery["delivered"] is True
    assert attempts == 1
    assert len(calls) == 1
    # No backoff on a single-success path.
    assert sleep_calls == []


async def test_send_with_retry_succeeds_on_second_attempt(monkeypatch):
    """First attempt fails with a transport error; second succeeds.

    Exercises the retry-after-backoff branch and confirms the slot
    gets `attempts=2`.
    """
    from services import rfq_dispatch

    deliveries = iter(
        [
            _delivery(delivered=False, reason="smtp_error:TimeoutError"),
            _delivery(delivered=True),
        ]
    )

    async def _fake_send(**_kwargs):
        return next(deliveries)

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        rfq_dispatch.asyncio,
        "sleep",
        AsyncMock(side_effect=lambda d: sleep_calls.append(d)),
    )

    delivery, attempts = await rfq_dispatch._send_with_retry(to="x@y", subject="s", text_body="b")
    assert delivery["delivered"] is True
    assert attempts == 2
    # One backoff sleep before attempt 2 (1 second per `_BACKOFF_BASE_SECONDS`).
    assert sleep_calls == [1.0]


async def test_send_with_retry_exhausts_attempts_and_returns_last_failure(monkeypatch):
    """Three transport errors → final delivery is the third failure, attempts=3."""
    from services import rfq_dispatch

    deliveries = iter(
        [
            _delivery(delivered=False, reason="smtp_error:TimeoutError"),
            _delivery(delivered=False, reason="smtp_error:ConnectionResetError"),
            _delivery(delivered=False, reason="smtp_error:OSError"),
        ]
    )

    async def _fake_send(**_kwargs):
        return next(deliveries)

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)
    monkeypatch.setattr(rfq_dispatch.asyncio, "sleep", AsyncMock())

    delivery, attempts = await rfq_dispatch._send_with_retry(to="x@y", subject="s", text_body="b")
    assert delivery["delivered"] is False
    assert delivery["reason"] == "smtp_error:OSError"  # the LAST failure
    assert attempts == 3


async def test_send_with_retry_short_circuits_on_smtp_unconfigured(monkeypatch, caplog):
    """`smtp_not_configured` is a config issue — retry can't help. Stop after 1."""
    import logging

    from services import rfq_dispatch

    async def _fake_send(**_kwargs):
        return _delivery(delivered=False, reason="smtp_not_configured")

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        rfq_dispatch.asyncio,
        "sleep",
        AsyncMock(side_effect=lambda d: sleep_calls.append(d)),
    )

    with caplog.at_level(logging.INFO, logger="services.rfq_dispatch"):
        delivery, attempts = await rfq_dispatch._send_with_retry(to="x@y", subject="s", text_body="b")

    assert delivery["delivered"] is False
    assert delivery["reason"] == "smtp_not_configured"
    assert attempts == 1
    assert sleep_calls == []
    assert any("no_retry" in r.getMessage() for r in caplog.records)


# ---------- Idempotent dispatch re-call ----------


@pytest.fixture
def org_id() -> UUID:
    return UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def rfq_id() -> UUID:
    return UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def supplier_id() -> UUID:
    return UUID("33333333-3333-3333-3333-333333333333")


def _build_rfq(rfq_id: UUID, org_id: UUID, supplier_id: UUID, *, response_status: str | None = None):
    """SimpleNamespace stand-in for an Rfq ORM row."""
    responses: list[dict[str, Any]] = []
    if response_status is not None:
        responses.append(
            {
                "supplier_id": str(supplier_id),
                "status": response_status,
                "dispatched_at": "2026-04-25T10:00:00+00:00",
                "attempts": 1,
                "delivery": {
                    "to": "x@y",
                    "subject": "s",
                    "delivered": response_status == "dispatched",
                    "reason": None,
                },
                "quote": None,
            }
        )
    return SimpleNamespace(
        id=rfq_id,
        organization_id=org_id,
        sent_to=[supplier_id],
        responses=responses,
        estimate_id=None,
        deadline=date(2026, 6, 1),
        status="sent",
    )


def _build_supplier(supplier_id: UUID, email: str = "supplier@example.com"):
    return SimpleNamespace(
        id=supplier_id,
        name="Test Supplier",
        contact={"email": email},
    )


class _FakeSession:
    """Pops execute results in order. Tracks `flag_modified` calls
    not at all — the tenant session API isn't relevant here."""

    def __init__(self, results: list[Any]):
        self._results = list(results)

    async def execute(self, *_a, **_k):
        next_value = self._results.pop(0) if self._results else None
        result = MagicMock()
        result.scalar_one_or_none.return_value = next_value
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = next_value if isinstance(next_value, list) else []
        result.scalars.return_value = scalars_mock
        if isinstance(next_value, list):
            result.scalar_one_or_none.return_value = None
        return result


@pytest.fixture
def install_tenant_session(monkeypatch):
    """Replace `TenantAwareSession` with a context manager that yields
    a `_FakeSession` driven by the test's queued results."""

    def _install(results):
        session = _FakeSession(results)

        class _CM:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        from services import rfq_dispatch

        def _factory(_org_id):
            return _CM()

        monkeypatch.setattr(rfq_dispatch, "TenantAwareSession", _factory)
        # `flag_modified` requires a real ORM instance; neuter for the
        # SimpleNamespace stand-in.
        monkeypatch.setattr("sqlalchemy.orm.attributes.flag_modified", lambda *a, **k: None)
        return session

    return _install


async def test_dispatch_skips_already_dispatched_slot(install_tenant_session, monkeypatch, org_id, rfq_id, supplier_id):
    """Re-enqueueing dispatch for an RFQ where the supplier slot is
    already `dispatched` must NOT re-email — idempotency."""
    from services import rfq_dispatch

    rfq = _build_rfq(rfq_id, org_id, supplier_id, response_status="dispatched")
    supplier = _build_supplier(supplier_id)

    # Execute order in dispatch_rfq:
    #   1. SELECT Rfq           → rfq
    #   2. SELECT Supplier ...  → [supplier] (BOQ digest skipped because no estimate_id)
    install_tenant_session([rfq, [supplier]])

    sends: list[str] = []

    async def _fake_send(**kwargs):
        sends.append(kwargs["to"])
        return _delivery(delivered=True)

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)

    summary = await rfq_dispatch.dispatch_rfq(organization_id=org_id, rfq_id=rfq_id)

    # Mailer NOT called — that's the idempotency assertion.
    assert sends == []
    # Slot stays `dispatched` (not regressed to `bounced`).
    assert rfq.responses[0]["status"] == "dispatched"
    # Counters reflect the no-op: nothing newly dispatched, nothing skipped
    # (skipped counts the supplier-not-visible / no-email branches, not idempotent skips).
    assert summary["dispatched"] == 0
    assert summary["skipped"] == 0


async def test_dispatch_skips_already_responded_slot(install_tenant_session, monkeypatch, org_id, rfq_id, supplier_id):
    """A supplier who already submitted a quote must not be re-emailed
    even on a retry pass that picks up bounced sibling slots."""
    from services import rfq_dispatch

    rfq = _build_rfq(rfq_id, org_id, supplier_id, response_status="responded")
    supplier = _build_supplier(supplier_id)
    install_tenant_session([rfq, [supplier]])

    sends: list[str] = []

    async def _fake_send(**kwargs):
        sends.append(kwargs["to"])
        return _delivery(delivered=True)

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)
    await rfq_dispatch.dispatch_rfq(organization_id=org_id, rfq_id=rfq_id)
    assert sends == []
    assert rfq.responses[0]["status"] == "responded"


async def test_dispatch_retries_bounced_slot_and_carries_attempts_forward(
    install_tenant_session, monkeypatch, org_id, rfq_id, supplier_id
):
    """A `bounced` slot SHOULD re-attempt, and the running `attempts`
    counter must include the prior pass + the new attempts."""
    from services import rfq_dispatch

    rfq = _build_rfq(rfq_id, org_id, supplier_id, response_status="bounced")
    # Prior retry pass got `attempts=1`. We'll deliver successfully on
    # the new pass's first try → final attempts = 1 prior + 1 new = 2.
    rfq.responses[0]["attempts"] = 1
    supplier = _build_supplier(supplier_id)
    install_tenant_session([rfq, [supplier]])

    async def _fake_send(**_kwargs):
        return _delivery(delivered=True)

    monkeypatch.setattr(rfq_dispatch, "send_mail", _fake_send)

    summary = await rfq_dispatch.dispatch_rfq(organization_id=org_id, rfq_id=rfq_id)
    assert summary["dispatched"] == 1
    slot = rfq.responses[0]
    assert slot["status"] == "dispatched"
    assert slot["attempts"] == 2  # carried forward
