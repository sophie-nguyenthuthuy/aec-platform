"""Evaluate subscribed price alerts against the latest material_prices row.

Invoked by the nightly arq cron `price_alerts_evaluate_job`. For each alert,
look up the most-recent price for (material_code, province) and compare to
`last_price_vnd`. If the absolute percentage change exceeds `threshold_pct`,
email the subscribed user and update `last_price_vnd` so they aren't paged
again for the same movement.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from db.session import SessionFactory
from services.mailer import send_mail

logger = logging.getLogger(__name__)


async def evaluate_price_alerts() -> dict:
    # Cross-tenant read. RLS is disabled for the service role in prod; in dev the
    # alerts table already has tenant_isolation but this job bypasses it intentionally
    # by not setting app.current_org_id — the data we read is per-alert, not cross-org.
    async with SessionFactory() as session:
        rows = (await session.execute(
            text(
                """
                SELECT
                  pa.id               AS alert_id,
                  pa.organization_id  AS organization_id,
                  pa.user_id          AS user_id,
                  pa.material_code    AS material_code,
                  pa.province         AS province,
                  pa.threshold_pct    AS threshold_pct,
                  pa.last_price_vnd   AS last_price_vnd,
                  u.email             AS user_email,
                  mp.price_vnd        AS current_price_vnd,
                  mp.effective_date   AS current_effective_date,
                  mp.name             AS material_name
                FROM price_alerts pa
                JOIN users u ON u.id = pa.user_id
                LEFT JOIN LATERAL (
                  SELECT price_vnd, effective_date, name
                  FROM material_prices
                  WHERE material_code = pa.material_code
                    AND (pa.province IS NULL OR province = pa.province)
                  ORDER BY effective_date DESC
                  LIMIT 1
                ) mp ON true
                """
            )
        )).mappings().all()

        evaluated = len(rows)
        triggered = 0
        skipped_missing_price = 0
        skipped_no_baseline = 0

        for r in rows:
            if r["current_price_vnd"] is None:
                skipped_missing_price += 1
                continue

            current = Decimal(r["current_price_vnd"])
            threshold = Decimal(r["threshold_pct"] or 5)
            baseline = r["last_price_vnd"]

            if baseline is None:
                # First observation for this alert — seed the baseline, don't fire.
                await _update_baseline(session, r["alert_id"], current)
                skipped_no_baseline += 1
                continue

            baseline_dec = Decimal(baseline)
            if baseline_dec == 0:
                await _update_baseline(session, r["alert_id"], current)
                continue

            delta_pct = ((current - baseline_dec) / baseline_dec) * Decimal(100)
            if abs(delta_pct) < threshold:
                continue

            await _notify(
                user_email=r["user_email"],
                material_name=r["material_name"] or r["material_code"],
                material_code=r["material_code"],
                province=r["province"],
                baseline=baseline_dec,
                current=current,
                delta_pct=delta_pct,
                effective_date=r["current_effective_date"],
            )
            await _update_baseline(session, r["alert_id"], current)
            triggered += 1

        await session.commit()

    summary = {
        "evaluated": evaluated,
        "triggered": triggered,
        "skipped_missing_price": skipped_missing_price,
        "skipped_no_baseline": skipped_no_baseline,
    }
    logger.info("price_alerts.evaluate %s", summary)
    return summary


async def _update_baseline(session, alert_id: UUID, current: Decimal) -> None:
    await session.execute(
        text("UPDATE price_alerts SET last_price_vnd = :p WHERE id = :id"),
        {"p": current, "id": str(alert_id)},
    )


async def _notify(
    *,
    user_email: str,
    material_name: str,
    material_code: str,
    province: str | None,
    baseline: Decimal,
    current: Decimal,
    delta_pct: Decimal,
    effective_date,
) -> None:
    direction = "↑" if delta_pct > 0 else "↓"
    province_label = province or "nationwide"
    subject = (
        f"Price alert {direction} {abs(delta_pct):.1f}% — "
        f"{material_name} ({province_label})"
    )
    body = (
        f"Material: {material_name} [{material_code}]\n"
        f"Province: {province_label}\n"
        f"Previous: {int(baseline):,} VND\n"
        f"Current:  {int(current):,} VND  (effective {effective_date})\n"
        f"Change:   {direction} {abs(delta_pct):.2f}%\n\n"
        f"This alert has been reset — you'll be notified again the next time the "
        f"price moves by more than your threshold.\n"
    )
    await send_mail(to=user_email, subject=subject, text_body=body)
