"""Best-effort persistence of Slack delivery attempts.

Lives in its OWN file rather than inlined into `services/slack.py` —
three prior attempts to add a `_record_delivery` helper to
`services/slack.py` were reverted upstream within seconds. The
migration (`0037_slack_deliveries.py`) and the ORM model
(`models/slack_delivery.py`) survive; only the wiring in
`services/slack.py` keeps getting un-applied. By isolating the
persistence helper here, callers (`services.ops_alerts._maybe_send_slack`,
future RFQ-deadline / weekly-digest callers) can opt in with a
single import without touching the slack delivery primitive.

Design contract:

  * **Opt-in.** `send_slack` itself does NOT call this — the caller
    decides whether the delivery is worth logging. The drift-alert
    path opts in (ops needs trend data); a future "user typed
    /slack-test" path probably wouldn't.

  * **Best-effort.** A DB outage MUST NOT propagate or re-raise.
    Failure mode is "we lost one row of telemetry" — never "the
    Slack alert that DID land also poisoned the originating job."

  * **No PII.** `text_preview` is capped at 200 chars and is the
    rendered Slack `text` fallback (drift alert subject, basically).
    Block payloads aren't persisted.

  * **`AdminSessionFactory`.** Cross-tenant by design — a Slack
    delivery isn't bound to an org. Same factory the drift-recipient
    resolver uses (see `services.ops_alerts._resolve_drift_recipients`).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# Cap on the persisted preview. Slack's `text` field can be a few KB
# (long block-kit fallbacks); persisting the full payload would bloat
# the table without giving ops more diagnostic value than the first
# line. Tune up only if a real ops-debugging session shows the cap
# truncates the useful signal.
_TEXT_PREVIEW_CAP = 200


async def record_delivery_attempt(
    *,
    kind: str,
    text: str,
    result: dict[str, Any],
) -> None:
    """Persist one row in `slack_deliveries` describing the attempt.

    `result` is the dict returned by `services.slack.send_slack` —
    `{delivered, reason, status}`. We mirror those into discrete
    columns for query-ability (`WHERE delivered = false` for the
    failures dashboard).

    `kind` is the caller-supplied label that groups attempts in the
    admin dashboard. Examples:
      * `"scraper_drift"` — drift-alert pipeline
      * (future) `"rfq_deadline"`, `"weekly_digest"`

    Never raises. A DB / import failure logs at WARNING and returns
    cleanly — the caller treats persistence as fire-and-forget.
    """
    delivered = bool(result.get("delivered"))
    reason = result.get("reason")
    status = result.get("status")

    # Guard against an int-ish status from a non-conforming caller.
    status_code: int | None
    if isinstance(status, int):
        status_code = status
    elif status is None:
        status_code = None
    else:
        # Defensive — surfaces a contract drift in the caller without
        # crashing the persistence path.
        logger.warning(
            "slack_telemetry: non-int status %r (%s) — coercing to None",
            status,
            type(status).__name__,
        )
        status_code = None

    text_preview = (text or "")[:_TEXT_PREVIEW_CAP]

    try:
        # Lazy imports keep this module's import graph free of
        # SQLAlchemy when the caller is in a unit-test that mocks
        # the function out wholesale.
        from db.session import AdminSessionFactory
        from models.slack_delivery import SlackDelivery

        async with AdminSessionFactory() as session:
            session.add(
                SlackDelivery(
                    id=uuid.uuid4(),
                    kind=kind,
                    delivered=delivered,
                    reason=reason if isinstance(reason, str) else None,
                    status_code=status_code,
                    text_preview=text_preview,
                )
            )
            await session.commit()
    except Exception as exc:  # pragma: no cover — defensive
        # The caller's Slack message already landed (or already failed
        # for its own reason); losing the telemetry row is a "we'll
        # see less data in the dashboard" event, not a job failure.
        logger.warning(
            "slack_telemetry.record_delivery_attempt: persist failed (%s): %s",
            kind,
            exc,
        )
