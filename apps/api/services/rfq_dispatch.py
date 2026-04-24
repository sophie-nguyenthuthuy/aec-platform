"""Dispatch an RFQ to its selected suppliers.

Loads the RFQ inside a TenantAwareSession, renders a per-supplier email with
a short BOQ digest from the linked estimate, and delegates transport to
`services.mailer`. Records each attempt back on `rfqs.responses` so the UI can
show dispatch state before any supplier has quoted.

Responses shape (per-supplier entry):
    {
      "supplier_id": "<uuid>",
      "status": "dispatched" | "bounced" | "skipped",
      "dispatched_at": "<iso8601>",
      "delivery": {"to": "...", "subject": "...", "delivered": bool, "reason": str|None},
      "quote": null
    }
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from db.session import TenantAwareSession
from models.costpulse import BoqItem, Estimate, Rfq, Supplier
from services.mailer import send_mail

logger = logging.getLogger(__name__)

_MAX_BOQ_LINES = 15


async def dispatch_rfq(*, organization_id: UUID, rfq_id: UUID) -> dict:
    """Best-effort dispatch. Never raises: returns a summary for the worker to log."""
    async with TenantAwareSession(organization_id) as session:
        rfq = (
            await session.execute(select(Rfq).where(Rfq.id == rfq_id))
        ).scalar_one_or_none()
        if rfq is None:
            logger.warning("rfq_dispatch.missing rfq_id=%s", rfq_id)
            return {"rfq_id": str(rfq_id), "dispatched": 0, "skipped": 0, "reason": "not_found"}

        estimate = None
        boq_digest = ""
        if rfq.estimate_id:
            estimate = (
                await session.execute(select(Estimate).where(Estimate.id == rfq.estimate_id))
            ).scalar_one_or_none()
            if estimate is not None:
                lines = (
                    (await session.execute(
                        select(BoqItem)
                        .where(BoqItem.estimate_id == estimate.id)
                        .order_by(BoqItem.sort_order)
                        .limit(_MAX_BOQ_LINES)
                    )).scalars().all()
                )
                boq_digest = _format_boq_digest(lines)

        supplier_ids = list(rfq.sent_to or [])
        suppliers = (
            (await session.execute(
                select(Supplier).where(Supplier.id.in_(supplier_ids))
            )).scalars().all()
            if supplier_ids else []
        )
        by_id: dict[UUID, Supplier] = {s.id: s for s in suppliers}

        existing: list[dict] = list(rfq.responses or [])
        existing_by_supplier = {
            str(e.get("supplier_id")): e for e in existing if isinstance(e, dict)
        }

        dispatched = 0
        skipped = 0
        for sid in supplier_ids:
            supplier = by_id.get(sid)
            entry = existing_by_supplier.get(str(sid), {
                "supplier_id": str(sid), "quote": None,
            })

            if supplier is None:
                entry.update({
                    "status": "skipped",
                    "delivery": {"delivered": False, "reason": "supplier_not_visible"},
                })
                existing_by_supplier[str(sid)] = entry
                skipped += 1
                continue

            email = (supplier.contact or {}).get("email")
            if not email:
                entry.update({
                    "status": "skipped",
                    "delivery": {"delivered": False, "reason": "no_email_on_file"},
                })
                existing_by_supplier[str(sid)] = entry
                skipped += 1
                continue

            subject, body = _render(rfq=rfq, estimate=estimate, supplier=supplier,
                                    boq_digest=boq_digest)
            delivery = await send_mail(to=email, subject=subject, text_body=body)
            entry.update({
                "status": "dispatched" if delivery["delivered"] else "bounced",
                "dispatched_at": delivery["dispatched_at"],
                "delivery": {
                    "to": delivery["to"],
                    "subject": delivery["subject"],
                    "delivered": delivery["delivered"],
                    "reason": delivery["reason"],
                },
            })
            existing_by_supplier[str(sid)] = entry
            if delivery["delivered"]:
                dispatched += 1
            else:
                skipped += 1

        rfq.responses = list(existing_by_supplier.values())
        # Flag SQLAlchemy that the mutable JSONB list changed.
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(rfq, "responses")
        rfq.status = "sent" if dispatched else (rfq.status or "draft")

    logger.info(
        "rfq_dispatch.done rfq_id=%s dispatched=%d skipped=%d",
        rfq_id, dispatched, skipped,
    )
    return {
        "rfq_id": str(rfq_id),
        "dispatched": dispatched,
        "skipped": skipped,
    }


def _format_boq_digest(items: list[BoqItem]) -> str:
    if not items:
        return "(estimate had no BOQ items)"
    lines = []
    for i in items:
        qty = f"{i.quantity}" if i.quantity is not None else "?"
        unit = i.unit or ""
        code = f"[{i.material_code}] " if i.material_code else ""
        lines.append(f"  - {code}{i.description} — {qty} {unit}".rstrip())
    return "\n".join(lines)


def _render(*, rfq: Rfq, estimate: Estimate | None, supplier: Supplier,
            boq_digest: str) -> tuple[str, str]:
    deadline = rfq.deadline.isoformat() if rfq.deadline else "at your earliest convenience"
    estimate_name = estimate.name if estimate else "(no linked estimate)"
    subject = f"RFQ — {estimate_name} (deadline {deadline})"
    body = (
        f"Xin chào {supplier.name},\n\n"
        f"We would like to request a quotation for the following project scope:\n\n"
        f"Estimate: {estimate_name}\n"
        f"RFQ ID:   {rfq.id}\n"
        f"Deadline: {deadline}\n\n"
        f"Indicative scope:\n{boq_digest}\n\n"
        f"Please reply to this email with your unit prices and lead times. "
        f"Full BOQ is available on request.\n\n"
        f"Thank you,\nAEC Platform — RFQ Bot\n"
    )
    return subject, body
