"""Webhook outbox + dispatcher.

Two halves of the same workflow:

  * `enqueue_event(...)` — called from inside a request handler in the
    SAME transaction as the source write (audit insert, project
    creation, etc.). It looks up matching subscriptions and inserts
    `webhook_deliveries` rows in `pending` status. If the surrounding
    transaction rolls back, the delivery rows roll back too — we
    never notify a customer about a write that didn't actually
    commit. Classic transactional outbox.

  * `drain_pending()` — called by the arq cron every minute. Picks up
    `pending` / due-for-retry rows, signs the payload with HMAC-SHA256,
    POSTs to the subscriber's URL, and marks the delivery `delivered`
    or schedules a retry with exponential backoff (1m → 5m → 30m → 2h
    → 12h → permanent fail at attempt 6).

Signature scheme:

    X-AEC-Signature: sha256=<hex_digest>
    X-AEC-Event-Type: <event_type>
    X-AEC-Delivery-ID: <uuid>
    X-AEC-Timestamp: <unix_seconds>

The receiver verifies via:

    expected = hmac.new(secret.encode(), body, sha256).hexdigest()
    hmac.compare_digest(f"sha256={expected}", header_value)

The timestamp lets the receiver reject replays older than N minutes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Closed registry of event types webhooks can subscribe to. Sources:
#   * Every value of `services/audit.AuditAction` is auto-mirrored here.
#   * Plus a few high-value events that don't carry an audit row (e.g.
#     defect-reported, safety-incident-detected — those are creations,
#     not authenticated approvals).
#
# Anything outside this set is considered a programmer error at the
# call site (`enqueue_event(unknown_type, ...)` raises). We don't
# *gate* subscribers on it — they can register for any string they
# want, and the dispatcher just won't fire on unknown types.
_KNOWN_EVENT_TYPES: set[str] = {
    # Audit-mirrored — keep in sync with `services/audit.AuditAction`
    "costpulse.estimate.approve",
    "costpulse.boq.import",
    "costpulse.suppliers.import",
    "costpulse.rfq.slots_expired",
    "pulse.change_order.approve",
    "pulse.change_order.reject",
    "org.member.role_change",
    "org.member.remove",
    "org.invitation.create",
    "org.invitation.revoke",
    "org.invitation.accept",
    "notifications.preference.update",
    "handover.package.deliver",
    "punchlist.list.sign_off",
    "submittals.review.approve",
    "submittals.review.approve_as_noted",
    "submittals.review.revise_resubmit",
    "submittals.review.reject",
    "admin.normalizer_rule.create",
    "admin.normalizer_rule.update",
    "admin.normalizer_rule.delete",
    "webhooks.subscription.rotate_secret",
    "admin.cron.run_now",
    "admin.cron.dedup_clear",
    # Non-audit creations (not gated by RBAC; carry no actor
    # before/after diff, so they're awkward to log to audit but
    # high-value to webhook)
    "project.created",
    "siteeye.safety_incident.detected",
    "handover.defect.reported",
    # Test-fire from the `/webhooks/{id}/test` endpoint. Same payload
    # shape as a real event so receivers can't distinguish (and thus
    # can't be tricked into trusting a spoofed flag).
    "webhook.test",
}


# Per-event-type metadata for the partner-facing catalog page at
# /docs/webhooks/events. Drives the frontend table without forcing
# the partner to read source code to figure out what each event
# means.
#
# The keys MUST be a strict subset of `_KNOWN_EVENT_TYPES` —
# `tests/test_integrator_surface_snapshot.py::test_webhook_event_catalog_in_sync`
# pins this so a new event added to the registry without a catalog
# entry fails CI before a partner discovers it documented as
# "(no description)".
#
# `payload_sample` is illustrative — the actual payload is whatever
# `enqueue_event(payload=...)` was called with. Listing every field
# would over-promise stability; we list only the fields receivers
# can confidently key off, with a comment about other fields being
# best-effort.
EVENT_CATALOG: dict[str, dict[str, str | dict[str, Any]]] = {
    # --- Audit-mirrored events (carry the full audit before/after diff) ---
    "costpulse.estimate.approve": {
        "description": "An estimate's status flipped to 'approved'. Receiver should refresh anything keyed off the estimate's lifecycle (proposal generation, approved-cost rollups).",
        "payload_sample": {"estimate_id": "<uuid>", "approved_by": "<user_uuid>"},
    },
    "costpulse.boq.import": {
        "description": "A BOQ Excel import landed. Useful for syncing BoqItem rows into a partner's costing system.",
        "payload_sample": {"estimate_id": "<uuid>", "row_count": 47},
    },
    "costpulse.suppliers.import": {
        "description": "Bulk supplier import via CSV completed.",
        "payload_sample": {"created": 12, "updated": 3, "errors": 0},
    },
    "costpulse.rfq.slots_expired": {
        "description": "An RFQ's response deadline passed without all suppliers replying. Cron-driven (no human actor). Fires once per RFQ at expiry.",
        "payload_sample": {"rfq_id": "<uuid>", "deadline": "<iso8601>"},
    },
    "pulse.change_order.approve": {
        "description": "Change order moved to 'approved' — costs and schedule impact are now committed.",
        "payload_sample": {"change_order_id": "<uuid>", "project_id": "<uuid>"},
    },
    "pulse.change_order.reject": {
        "description": "Change order moved to 'rejected'. Mirrors the audit-event so partner's CRM can close the corresponding ticket.",
        "payload_sample": {"change_order_id": "<uuid>", "reason": "<string>"},
    },
    "org.member.role_change": {
        "description": "An organisation member's role was changed (member ↔ admin ↔ owner). Useful for syncing access control with a partner SSO.",
        "payload_sample": {"user_id": "<uuid>", "new_role": "admin", "old_role": "member"},
    },
    "org.member.remove": {
        "description": "Member removed from the org. Receiver should revoke any partner-side access tied to this user_id.",
        "payload_sample": {"user_id": "<uuid>"},
    },
    "org.invitation.create": {
        "description": "Admin issued an invitation. Partners building HR provisioning use this to pre-stage accounts.",
        "payload_sample": {"invitation_id": "<uuid>", "email": "<masked>"},
    },
    "org.invitation.revoke": {
        "description": "Pending invitation cancelled before acceptance.",
        "payload_sample": {"invitation_id": "<uuid>"},
    },
    "org.invitation.accept": {
        "description": "Invitee completed sign-up — the new user_id is in the payload. This is the authoritative 'user joined the org' signal.",
        "payload_sample": {"invitation_id": "<uuid>", "user_id": "<uuid>"},
    },
    "notifications.preference.update": {
        "description": "A user adjusted their email/Slack notification preferences. Lower-signal — most partners don't subscribe.",
        "payload_sample": {"user_id": "<uuid>", "channel": "email"},
    },
    "handover.package.deliver": {
        "description": "A handover package marked delivered to the client. Triggers the partner's contract-closure workflow.",
        "payload_sample": {"package_id": "<uuid>", "project_id": "<uuid>"},
    },
    "punchlist.list.sign_off": {
        "description": "Punch list signed off — every item verified as resolved.",
        "payload_sample": {"punch_list_id": "<uuid>", "project_id": "<uuid>"},
    },
    "submittals.review.approve": {
        "description": "Submittal approved as-is. Materials/samples can proceed.",
        "payload_sample": {"submittal_id": "<uuid>", "project_id": "<uuid>"},
    },
    "submittals.review.approve_as_noted": {
        "description": "Submittal approved with required revisions noted. Receiver should surface the notes to the contractor.",
        "payload_sample": {"submittal_id": "<uuid>", "notes_count": 2},
    },
    "submittals.review.revise_resubmit": {
        "description": "Submittal needs revision and re-submission. Distinct from outright rejection.",
        "payload_sample": {"submittal_id": "<uuid>"},
    },
    "submittals.review.reject": {
        "description": "Submittal rejected outright. Contractor restarts.",
        "payload_sample": {"submittal_id": "<uuid>"},
    },
    "admin.normalizer_rule.create": {
        "description": "Ops added a new material-name normaliser rule. Platform-level event (no organization_id).",
        "payload_sample": {"rule_id": "<uuid>", "pattern": "<regex>"},
    },
    "admin.normalizer_rule.update": {
        "description": "Existing normaliser rule edited.",
        "payload_sample": {"rule_id": "<uuid>"},
    },
    "admin.normalizer_rule.delete": {
        "description": "Normaliser rule removed (or soft-disabled).",
        "payload_sample": {"rule_id": "<uuid>"},
    },
    "webhooks.subscription.rotate_secret": {
        "description": "A webhook subscription's signing secret was rotated by an admin. Receivers should re-fetch the secret out-of-band; deliveries signed with the previous secret will start failing verification at rotation time.",
        "payload_sample": {"webhook_id": "<uuid>", "rotated_by": "<user_uuid>"},
    },
    "admin.cron.run_now": {
        "description": "An admin manually triggered a cron job out-of-schedule. Useful for ops dashboards that distinguish operator interventions from scheduled runs.",
        "payload_sample": {"cron_name": "<string>", "triggered_by": "<user_uuid>"},
    },
    "admin.cron.dedup_clear": {
        "description": "An admin cleared the dedup state for a cron alert, silencing a stuck-cron notification. The alert will re-fire if the underlying cron remains stuck.",
        "payload_sample": {"cron_name": "<string>", "kind": "cron_stuck", "cleared_by": "<user_uuid>"},
    },
    # --- Non-audit events (creations + cron + test fire) ---
    "project.created": {
        "description": "A new project was created. The earliest hook for partner systems to provision a corresponding record.",
        "payload_sample": {"project_id": "<uuid>", "name": "<string>"},
    },
    "siteeye.safety_incident.detected": {
        "description": "AI camera analytics detected a PPE / safety violation. Real-time signal — fires within seconds of the camera frame.",
        "payload_sample": {"incident_id": "<uuid>", "project_id": "<uuid>", "severity": "high"},
    },
    "handover.defect.reported": {
        "description": "A new defect was logged during a handover walkthrough.",
        "payload_sample": {"defect_id": "<uuid>", "project_id": "<uuid>"},
    },
    "webhook.test": {
        "description": "Synthetic test event fired by `POST /webhooks/{id}/test`. Same envelope shape as a real event so receivers can't be tricked into trusting a spoofed `is_test` flag.",
        "payload_sample": {"message": "This is a test event from AEC Platform."},
    },
}


# Retry schedule: minutes from creation to each attempt. After 6
# attempts the delivery is marked `failed` permanently.
_BACKOFF_MINUTES: list[int] = [0, 1, 5, 30, 120, 720]
# Auto-disable a subscription after N consecutive failures so we don't
# hammer a dead endpoint forever. Counter resets on success.
_DISABLE_AFTER_FAILURES = 20
# Per-attempt HTTP timeout. Must be tighter than the cron interval
# (60s) so a stuck delivery doesn't pile up alongside its retries.
_HTTP_TIMEOUT_SEC = 10.0
# Cap stored response bodies so a chatty receiver can't bloat the table.
_MAX_RESPONSE_SNIPPET = 500


# ---------- Secret + signature helpers ----------


def generate_secret() -> str:
    """64-char hex (32 random bytes). Used by `webhook_subscriptions.secret`
    and never re-shown after creation."""
    return secrets.token_hex(32)


# Default grace window for `rotate_secret` — the previous secret keeps
# verifying for this long after rotation. 24h matches a typical
# customer's "deploy receiver with new secret, smoke-test, retire old"
# CI cycle. The constant is module-level so the test can pin it
# without recomputing the timedelta arithmetic.
DEFAULT_ROTATION_GRACE_SECONDS = 24 * 60 * 60


async def rotate_secret(
    session: AsyncSession,
    *,
    subscription_id: UUID,
    organization_id: UUID,
    grace_seconds: int = DEFAULT_ROTATION_GRACE_SECONDS,
) -> str | None:
    """Issue a new HMAC secret for a webhook subscription, retaining
    the previous secret as `secret_previous` for `grace_seconds`.

    Returns the NEW secret string (the only time the customer sees it
    on rotation) or None if the subscription doesn't exist / belongs
    to a different org. `organization_id` is checked here so the
    router doesn't have to re-load the row — a single UPDATE …
    RETURNING does the auth + mutation in one round trip.

    The previous secret is preserved so the dispatcher can sign every
    delivery with BOTH secrets for the grace window. Receivers that
    haven't yet rolled to the new secret keep verifying via the
    `X-AEC-Signature-Previous` header — see `_deliver_one`.

    Idempotency stance: rotating a subscription that's already in the
    middle of a grace window OVERWRITES the existing previous secret
    with the just-rotated-from one. The old `secret_previous` is
    discarded — receivers running on it should already have rolled
    forward by now (their grace started earlier). Two rapid rotations
    in quick succession are unusual but not blocked; a partner that
    actually wants two-deep history can request it later.

    Why a single UPDATE … RETURNING vs SELECT-then-UPDATE:
      * The org-scope check + the swap need to be atomic. A
        SELECT-then-UPDATE leaves a window where another rotation
        could land between the read and the write — the old secret
        would be lost without ever being preserved as
        `secret_previous`.
      * The RETURNING clause confirms a row was actually mutated; if
        the WHERE matched zero rows (wrong org or unknown id) we
        return None and the router 404s.
    """
    new_secret = generate_secret()
    # Transaction MUST commit before the new secret is returned to the
    # caller — otherwise a crash between RETURNING and the response
    # would leave the customer's receiver with a secret that doesn't
    # match the DB, and every delivery would 401 until manual repair.
    result = await session.execute(
        text(
            """
            UPDATE webhook_subscriptions
            SET secret_previous = secret,
                secret_previous_expires_at = NOW()
                    + make_interval(secs => :grace_seconds),
                secret = :new_secret
            WHERE id = :id
              AND organization_id = :org_id
            RETURNING id
            """
        ),
        {
            "id": str(subscription_id),
            "org_id": str(organization_id),
            "new_secret": new_secret,
            "grace_seconds": int(grace_seconds),
        },
    )
    matched = result.first()
    if matched is None:
        # Don't commit — the UPDATE matched nothing, so there's no
        # state to flush, but explicit is cheap defensiveness.
        return None
    await session.commit()
    return new_secret


def _previous_secret_active(
    secret_previous: str | None,
    secret_previous_expires_at: datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Pure helper: should the dispatcher emit
    `X-AEC-Signature-Previous` for this subscription right now?

    True iff both columns are populated AND the expiry is still in
    the future. Pulled out as a function so the unit tests can pin
    the boundary without round-tripping through the dispatcher.
    """
    if not secret_previous or secret_previous_expires_at is None:
        return False
    when = now or datetime.now(UTC)
    return secret_previous_expires_at > when


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 of the raw POST body, hex-encoded.

    The receiver computes the same and `hmac.compare_digest`s it
    against the `X-AEC-Signature` header (without the `sha256=` prefix
    or with — we accept both for ergonomics)."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def sign_payload_with_timestamp(secret: str, body: bytes, ts: int) -> str:
    """Replay-resistant variant of `sign_payload`.

    Mixes a unix-seconds timestamp into the signed material via a
    `b"<ts>."` prefix. The `.` separator matters: without it, an
    attacker who controlled either the timestamp or the body could
    shift the boundary between the two and produce a different
    signature for "the same" pair of inputs (length-extension shape).
    The dot is not in the digit alphabet, so no body byte can swallow
    it.

    Sender layout (header on the wire):
        X-AEC-Timestamp: <ts>
        X-AEC-Signature: sha256=<sign_payload_with_timestamp(...)>

    The legacy `sign_payload` is left unchanged — existing customer
    receivers depend on that exact output; this helper is strictly
    additive.
    """
    msg = f"{ts}.".encode() + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_payload_with_trace(
    secret: str,
    body: bytes,
    ts: int,
    signature: str,
    *,
    now: int,
    max_skew_seconds: int = 300,
) -> dict:
    """Structured-diagnosis variant of `verify_payload` (cycle Q2).

    Returns a dict with:
      * `verified` — bool, the same answer `verify_payload` returns.
      * `expected_signature` — the hex digest the receiver SHOULD
        have computed under the supplied secret + body + ts.
      * `provided_signature` — the supplied signature with any
        `sha256=` prefix stripped, mirroring what the verifier
        compared against.
      * `skew_seconds` — `now - ts` (signed). Surfaces "your clock
        is ahead by 7 seconds" vs. "your clock is behind by 7
        seconds" — different diagnostic stories.
      * `reason` — None on success; one of the closed reason codes
        on failure: `timestamp_skew_exceeded` |
        `signature_mismatch` | `invalid_signature_format`.

    Powers the partner-facing webhook signature verification
    playground at `/docs/webhooks/verify`. The structured shape lets
    the UI render a focused diagnosis ("clock skew 720s — re-sync
    your receiver's clock") instead of just "didn't match" — closes
    the most common partner support inquiry.

    The legacy boolean `verify_payload` (below) is preserved
    unchanged — receivers in production verify with that and a
    behaviour change there would be a wire breaking change.
    """
    skew = now - ts
    if abs(skew) > max_skew_seconds:
        # We still compute the expected signature so the partner can
        # eyeball it — useful when both clock skew AND signature
        # mismatch happen at once (otherwise the partner fixes the
        # clock and discovers a separate signature bug after).
        expected = sign_payload_with_timestamp(secret, body, ts)
        return {
            "verified": False,
            "expected_signature": expected,
            "provided_signature": _strip_prefix(signature),
            "skew_seconds": skew,
            "reason": "timestamp_skew_exceeded",
        }

    expected = sign_payload_with_timestamp(secret, body, ts)
    provided = _strip_prefix(signature)
    try:
        match = hmac.compare_digest(expected, provided)
    except (TypeError, ValueError):
        return {
            "verified": False,
            "expected_signature": expected,
            "provided_signature": provided,
            "skew_seconds": skew,
            "reason": "invalid_signature_format",
        }

    return {
        "verified": match,
        "expected_signature": expected,
        "provided_signature": provided,
        "skew_seconds": skew,
        "reason": None if match else "signature_mismatch",
    }


def _strip_prefix(signature: str) -> str:
    """Helper: drop the `sha256=` prefix the wire format includes.

    Pulled out as a function so the legacy `verify_payload` AND the
    new `verify_payload_with_trace` use the same parse rule. A
    receiver that includes the prefix and one that doesn't both
    work via this helper."""
    if signature.startswith("sha256="):
        return signature[len("sha256=") :]
    return signature


def verify_payload(
    secret: str,
    body: bytes,
    ts: int,
    signature: str,
    *,
    now: int,
    max_skew_seconds: int = 300,
) -> bool:
    """Verify a `sign_payload_with_timestamp` signature.

    Two independent checks, both must pass:

      1. **Freshness.** `abs(now - ts) <= max_skew_seconds`.
         Symmetric on purpose — a future-dated timestamp from an
         attacker (`ts = year 9999`) must reject just like a stale
         one. A naive `now > ts` check would let the future-dated
         case through.

      2. **HMAC.** The provided signature equals
         `sign_payload_with_timestamp(secret, body, ts)`. Compared
         via `hmac.compare_digest` so we don't side-channel-leak
         signature bytes through timing.

    The signature parameter accepts either the raw hex digest or the
    `sha256=<hex>` wire form for receiver ergonomics.

    Returns False (never raises) on any malformed input — wrong-
    length signature, non-hex characters, empty string. Receivers
    pass header values verbatim; an exception backtrace at this
    boundary would be a DoS vector.
    """
    if abs(now - ts) > max_skew_seconds:
        return False
    if signature.startswith("sha256="):
        signature = signature[len("sha256=") :]
    expected = sign_payload_with_timestamp(secret, body, ts)
    try:
        return hmac.compare_digest(expected, signature)
    except (TypeError, ValueError):
        return False


# ---------- Wildcard helpers ----------


def _wildcard_candidates(event_type: str) -> list[str]:
    """Return wildcard patterns that would match `event_type`.

    Walks segment prefixes from most-specific to least:
      "costpulse.estimate.approve" → ["costpulse.estimate.*", "costpulse.*"]
      "webhook.test"               → ["webhook.*"]
      "unstructured"               → []
    """
    parts = event_type.split(".")
    if len(parts) < 2:
        return []
    candidates = []
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        candidates.append(f"{prefix}.*")
    return candidates


# ---------- Outbox enqueue ----------


async def enqueue_event(
    session: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """Insert one `webhook_deliveries` row per matching subscription.

    Returns the number of delivery rows inserted (0 if no subscription
    matched). Idempotency is the *caller's* responsibility — fire from
    inside the same transaction as the source write so the outbox row
    rolls back with it.

    Matching rule: a subscription with empty `event_types[]` matches
    everything. Otherwise the event_type must be in the array.
    """
    if event_type not in _KNOWN_EVENT_TYPES:
        # Soft warning, not a raise — keeps a typo at the call site
        # from breaking the request, but the log line tells us about
        # it. Subscriptions only fire on known events anyway.
        logger.warning("webhooks.enqueue_event: unknown type %r", event_type)

    wildcards = _wildcard_candidates(event_type)
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id FROM webhook_subscriptions
                    WHERE organization_id = :org
                      AND enabled = true
                      AND (
                        cardinality(event_types) = 0
                        OR :event_type = ANY(event_types)
                        OR event_types && CAST(:wildcards AS text[])
                      )
                    """
                ),
                {
                    "org": str(organization_id),
                    "event_type": event_type,
                    "wildcards": wildcards,
                },
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    # Bulk insert — one round trip regardless of subscription count.
    # `next_retry_at = NOW()` so the next cron tick picks this up.
    payload_json = json.dumps(payload, default=str)
    for sub_id in rows:
        await session.execute(
            text(
                """
                INSERT INTO webhook_deliveries
                  (id, subscription_id, organization_id, event_type, payload,
                   status, attempt_count, next_retry_at)
                VALUES
                  (:id, :sub, :org, :event_type, CAST(:payload AS jsonb),
                   'pending', 0, NOW())
                """
            ),
            {
                "id": str(uuid4()),
                "sub": str(sub_id),
                "org": str(organization_id),
                "event_type": event_type,
                "payload": payload_json,
            },
        )
    return len(rows)


# ---------- Cron drain ----------


async def drain_pending(session: AsyncSession, *, batch: int = 100) -> dict[str, int]:
    """Pick up due deliveries, ship them, mark + retry.

    Cross-tenant by design — caller passes an `AdminSessionFactory`
    session because the discovery query needs to see every org's
    pending deliveries. Tenant scoping happens *inside* each delivery's
    payload via `organization_id`, not via session GUC.

    Atomicity / locking: we `SELECT … FOR UPDATE SKIP LOCKED` so two
    workers running concurrently each pick a disjoint batch instead
    of contending on the same row.
    """
    # Pull due rows + the parent subscription's URL/secret/state in
    # one go. JOIN keeps the per-row dispatch loop decoupled from the
    # subscription state.
    due_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT
                        d.id, d.subscription_id, d.organization_id,
                        d.event_type, d.payload, d.attempt_count,
                        s.url, s.secret, s.failure_count,
                        -- Rotation grace columns (migration 0043).
                        -- The dispatcher emits a second signature
                        -- header when both are populated AND the
                        -- expiry is in the future.
                        s.secret_previous,
                        s.secret_previous_expires_at
                    FROM webhook_deliveries d
                    JOIN webhook_subscriptions s ON s.id = d.subscription_id
                    WHERE d.status IN ('pending', 'in_flight')
                      AND d.next_retry_at <= NOW()
                      AND s.enabled = true
                    ORDER BY d.next_retry_at
                    LIMIT :batch
                    FOR UPDATE OF d SKIP LOCKED
                    """
                ),
                {"batch": batch},
            )
        )
        .mappings()
        .all()
    )
    if not due_rows:
        return {"picked": 0, "delivered": 0, "failed": 0, "retried": 0}

    # Mark all picked rows as in_flight under the same SELECT lock so
    # a misconfigured second cron tick can't double-deliver.
    await session.execute(
        text("UPDATE webhook_deliveries SET status = 'in_flight' WHERE id = ANY(:ids)"),
        {"ids": [str(r["id"]) for r in due_rows]},
    )
    await session.commit()

    delivered = 0
    failed = 0
    retried = 0

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SEC) as http:
        for row in due_rows:
            attempt = int(row["attempt_count"]) + 1
            ok, status, snippet, err = await _deliver_one(
                http,
                url=row["url"],
                secret=row["secret"],
                # Pass the previous secret + expiry through; helper
                # decides whether to actually emit the second header.
                secret_previous=row["secret_previous"],
                secret_previous_expires_at=row["secret_previous_expires_at"],
                event_type=row["event_type"],
                delivery_id=row["id"],
                payload=row["payload"],
            )
            if ok:
                await _mark_delivered(
                    session,
                    delivery_id=row["id"],
                    subscription_id=row["subscription_id"],
                    response_status=status,
                    snippet=snippet,
                    attempt=attempt,
                )
                delivered += 1
            elif attempt >= len(_BACKOFF_MINUTES):
                await _mark_failed_permanently(
                    session,
                    delivery_id=row["id"],
                    subscription_id=row["subscription_id"],
                    response_status=status,
                    snippet=snippet,
                    error=err,
                    attempt=attempt,
                    failure_count=int(row["failure_count"]),
                )
                failed += 1
            else:
                await _schedule_retry(
                    session,
                    delivery_id=row["id"],
                    subscription_id=row["subscription_id"],
                    response_status=status,
                    snippet=snippet,
                    error=err,
                    attempt=attempt,
                    failure_count=int(row["failure_count"]),
                )
                retried += 1
        await session.commit()

    return {
        "picked": len(due_rows),
        "delivered": delivered,
        "failed": failed,
        "retried": retried,
    }


# ---------- Per-row delivery ----------


async def _deliver_one(
    http: httpx.AsyncClient,
    *,
    url: str,
    secret: str,
    secret_previous: str | None = None,
    secret_previous_expires_at: datetime | None = None,
    event_type: str,
    delivery_id: UUID,
    payload: dict,
) -> tuple[bool, int | None, str | None, str | None]:
    """POST a single delivery. Returns `(ok, status, body_snippet, error)`.

    `ok` is True on any 2xx — receivers signal "got it" with a 200
    typically, but some prefer 204. Anything else (incl. 5xx, network
    error, timeout) is treated as a retryable failure.

    Dual-secret rotation: when `secret_previous` is non-null AND
    `secret_previous_expires_at` is in the future, an additional
    `X-AEC-Signature-Previous` header is emitted alongside the
    primary `X-AEC-Signature`. Receivers verify EITHER signature
    matches, letting them roll forward to the new secret without a
    flag-day deploy. Outside the grace window the helper sends only
    the primary signature — same shape as the pre-rotation behaviour.
    """
    body = json.dumps(payload, default=str).encode("utf-8")
    signature = sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-AEC-Signature": f"sha256={signature}",
        "X-AEC-Event-Type": event_type,
        "X-AEC-Delivery-ID": str(delivery_id),
        "X-AEC-Timestamp": str(int(time.time())),
        # Receivers can redirect to https; but we don't auto-follow
        # redirects because a 3xx to a different host is suspicious
        # in this context.
        "User-Agent": "AEC-Platform-Webhook/1.0",
    }
    # Emit the second signature only inside the grace window. After
    # expiry we don't even send the header — quiet retirement of the
    # old secret matches the dispatcher's pre-rotation contract.
    if _previous_secret_active(secret_previous, secret_previous_expires_at):
        # Inside this branch `secret_previous` is non-None per the
        # helper's contract; the `or ""` keeps mypy quiet without
        # affecting runtime (the helper already returned False if
        # the value were falsy).
        prev_sig = sign_payload(secret_previous or "", body)
        headers["X-AEC-Signature-Previous"] = f"sha256={prev_sig}"
    try:
        res = await http.post(url, content=body, headers=headers)
    except httpx.TimeoutException:
        return (False, None, None, "timeout")
    except httpx.RequestError as exc:
        return (False, None, None, f"network: {type(exc).__name__}: {exc}")

    snippet = (res.text or "")[:_MAX_RESPONSE_SNIPPET] or None
    if 200 <= res.status_code < 300:
        return (True, res.status_code, snippet, None)
    return (
        False,
        res.status_code,
        snippet,
        f"non-2xx status: {res.status_code}",
    )


# ---------- Status transitions ----------


async def _mark_delivered(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    subscription_id: UUID,
    response_status: int | None,
    snippet: str | None,
    attempt: int,
) -> None:
    await session.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = 'delivered',
                response_status = :status,
                response_body_snippet = :snippet,
                attempt_count = :attempt,
                delivered_at = NOW(),
                next_retry_at = NULL,
                error_message = NULL
            WHERE id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": response_status,
            "snippet": snippet,
            "attempt": attempt,
        },
    )
    # Reset the subscription's rolling failure counter — a successful
    # delivery wipes the slate clean. last_delivery_at gets stamped
    # for ops dashboards.
    await session.execute(
        text(
            """
            UPDATE webhook_subscriptions
            SET failure_count = 0, last_delivery_at = NOW()
            WHERE id = :id
            """
        ),
        {"id": str(subscription_id)},
    )


async def _schedule_retry(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    subscription_id: UUID,
    response_status: int | None,
    snippet: str | None,
    error: str | None,
    attempt: int,
    failure_count: int,
) -> None:
    next_at = datetime.now(UTC) + timedelta(minutes=_BACKOFF_MINUTES[attempt])
    await session.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = 'pending',
                response_status = :status,
                response_body_snippet = :snippet,
                error_message = :error,
                attempt_count = :attempt,
                next_retry_at = :next_at
            WHERE id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": response_status,
            "snippet": snippet,
            "error": error,
            "attempt": attempt,
            "next_at": next_at,
        },
    )
    await _bump_subscription_failure_counter(session, subscription_id=subscription_id, failure_count=failure_count)


async def _mark_failed_permanently(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    subscription_id: UUID,
    response_status: int | None,
    snippet: str | None,
    error: str | None,
    attempt: int,
    failure_count: int,
) -> None:
    await session.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = 'failed',
                response_status = :status,
                response_body_snippet = :snippet,
                error_message = :error,
                attempt_count = :attempt,
                next_retry_at = NULL
            WHERE id = :id
            """
        ),
        {
            "id": str(delivery_id),
            "status": response_status,
            "snippet": snippet,
            "error": error,
            "attempt": attempt,
        },
    )
    await _bump_subscription_failure_counter(session, subscription_id=subscription_id, failure_count=failure_count)


async def _bump_subscription_failure_counter(
    session: AsyncSession,
    *,
    subscription_id: UUID,
    failure_count: int,
) -> None:
    """Increment, and auto-disable if we've crossed the dead-endpoint
    threshold. The auto-disable is reversible — an admin can edit the
    URL + flip `enabled = true` and the next event will fire again."""
    new_count = failure_count + 1
    if new_count >= _DISABLE_AFTER_FAILURES:
        logger.warning(
            "webhook subscription %s auto-disabled after %d consecutive failures",
            subscription_id,
            new_count,
        )
        await session.execute(
            text("UPDATE webhook_subscriptions SET failure_count = :n, enabled = false WHERE id = :id"),
            {"id": str(subscription_id), "n": new_count},
        )
    else:
        await session.execute(
            text("UPDATE webhook_subscriptions SET failure_count = :n WHERE id = :id"),
            {"id": str(subscription_id), "n": new_count},
        )
