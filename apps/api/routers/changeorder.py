"""ChangeOrder router — CRUD on the existing change_orders table + extension
tables (sources, line items, approvals) + AI candidate extraction & impact
analysis.

The base `change_orders` table was created in 0002_pulse and lives in
`models.pulse.ChangeOrder`. This router owns its CRUD because the AI
features (extract candidates, analyze impact) need a dedicated surface
that the Pulse module shouldn't carry.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.changeorder import (
    AcceptCandidateRequest,
    AnalyzeImpactRequest,
    Approval,
    ApprovalCreate,
    Candidate,
    ChangeOrder,
    ChangeOrderCreate,
    ChangeOrderDetail,
    ChangeOrderUpdate,
    CoStatus,
    ExtractCandidatesRequest,
    LineItem,
    LineItemCreate,
    LineItemUpdate,
    RejectCandidateRequest,
    Source,
    SourceCreate,
)

router = APIRouter(prefix="/api/v1/changeorder", tags=["changeorder"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


# ---------- ChangeOrder CRUD ----------


@router.post("/cos", status_code=status.HTTP_201_CREATED)
async def create_change_order(
    payload: ChangeOrderCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        number = payload.number or await _next_co_number(session, payload.project_id)
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO change_orders
                  (organization_id, project_id, number, title, description,
                   initiator, cost_impact_vnd, schedule_impact_days, status)
                VALUES
                  (:org, :pid, :num, :title, :desc, :init, :cost, :days, 'draft')
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "pid": str(payload.project_id),
                    "num": number,
                    "title": payload.title,
                    "desc": payload.description,
                    "init": payload.initiator,
                    "cost": payload.cost_impact_vnd,
                    "days": payload.schedule_impact_days,
                },
            )
        ).one()
        # Seed an initial approval row so the audit trail starts at draft.
        await session.execute(
            text(
                """
            INSERT INTO change_order_approvals
              (organization_id, change_order_id, from_status, to_status, actor_id, notes)
            VALUES (:org, :coid, NULL, 'draft', :actor, 'CO created')
            """
            ),
            {
                "org": str(auth.organization_id),
                "coid": str(_row_to_dict(row)["id"]),
                "actor": str(auth.user_id),
            },
        )
        await session.commit()
    return ok(ChangeOrder.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.get("/cos")
async def list_change_orders(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    status_filter: CoStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    where = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(auth.organization_id)}
    if project_id:
        where.append("project_id = :pid")
        params["pid"] = str(project_id)
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter.value
    where_sql = " AND ".join(where)

    async with TenantAwareSession(auth.organization_id) as session:
        total = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM change_orders WHERE {where_sql}"),
                params,
            )
        ).scalar_one()
        rows = (
            await session.execute(
                text(
                    f"""
                SELECT * FROM change_orders WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).all()

    items = [ChangeOrder.model_validate(_row_to_dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=int(total or 0))


@router.get("/cos/{co_id}")
async def get_change_order(
    co_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        co = (
            await session.execute(
                text("SELECT * FROM change_orders WHERE id = :id"),
                {"id": str(co_id)},
            )
        ).one_or_none()
        if co is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Change order not found")
        sources = (
            await session.execute(
                text("SELECT * FROM change_order_sources WHERE change_order_id = :id"),
                {"id": str(co_id)},
            )
        ).all()
        line_items = (
            await session.execute(
                text(
                    """
                SELECT * FROM change_order_line_items
                WHERE change_order_id = :id
                ORDER BY sort_order, created_at
                """
                ),
                {"id": str(co_id)},
            )
        ).all()
        approvals = (
            await session.execute(
                text(
                    """
                SELECT * FROM change_order_approvals
                WHERE change_order_id = :id
                ORDER BY created_at ASC
                """
                ),
                {"id": str(co_id)},
            )
        ).all()

    detail = ChangeOrderDetail(
        change_order=ChangeOrder.model_validate(_row_to_dict(co)),
        sources=[Source.model_validate(_row_to_dict(s)) for s in sources],
        line_items=[LineItem.model_validate(_row_to_dict(li)) for li in line_items],
        approvals=[Approval.model_validate(_row_to_dict(a)) for a in approvals],
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/cos/{co_id}")
async def update_change_order(
    co_id: UUID,
    payload: ChangeOrderUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    if "status" in fields and hasattr(fields["status"], "value"):
        fields["status"] = fields["status"].value
    set_sql = ", ".join(f"{k} = :{k}" for k in fields)

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(f"UPDATE change_orders SET {set_sql} WHERE id = :id RETURNING *"),
                {**fields, "id": str(co_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Change order not found")
        await session.commit()
    return ok(ChangeOrder.model_validate(_row_to_dict(row)).model_dump(mode="json"))


# ---------- Sources ----------


@router.post("/cos/{co_id}/sources", status_code=status.HTTP_201_CREATED)
async def add_source(
    co_id: UUID,
    payload: SourceCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    """
                INSERT INTO change_order_sources
                  (organization_id, change_order_id, source_kind, rfi_id,
                   observation_id, payload, notes)
                VALUES
                  (:org, :coid, :sk, :rfi, :obs, CAST(:payload AS jsonb), :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "coid": str(co_id),
                    "sk": payload.source_kind.value,
                    "rfi": str(payload.rfi_id) if payload.rfi_id else None,
                    "obs": (str(payload.observation_id) if payload.observation_id else None),
                    "payload": json.dumps(payload.payload),
                    "notes": payload.notes,
                },
            )
        ).one()
        await session.commit()
    return ok(Source.model_validate(_row_to_dict(row)).model_dump(mode="json"))


# ---------- Line items ----------


@router.post("/cos/{co_id}/line-items", status_code=status.HTTP_201_CREATED)
async def add_line_item(
    co_id: UUID,
    payload: LineItemCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        # cost_vnd auto-derives from quantity*unit_cost_vnd if both supplied
        # and cost_vnd wasn't.
        cost = payload.cost_vnd
        if cost is None and payload.quantity is not None and payload.unit_cost_vnd is not None:
            cost = int(round(payload.quantity * payload.unit_cost_vnd))

        row = (
            await session.execute(
                text(
                    """
                INSERT INTO change_order_line_items
                  (organization_id, change_order_id, description, line_kind,
                   spec_section, quantity, unit, unit_cost_vnd, cost_vnd,
                   schedule_impact_days, schedule_activity_id, sort_order, notes)
                VALUES
                  (:org, :coid, :desc, :kind, :spec, :qty, :unit, :uc, :cost,
                   :days, :sched_act, :sort_order, :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "coid": str(co_id),
                    "desc": payload.description,
                    "kind": payload.line_kind.value,
                    "spec": payload.spec_section,
                    "qty": payload.quantity,
                    "unit": payload.unit,
                    "uc": payload.unit_cost_vnd,
                    "cost": cost,
                    "days": payload.schedule_impact_days,
                    "sched_act": (str(payload.schedule_activity_id) if payload.schedule_activity_id else None),
                    "sort_order": payload.sort_order,
                    "notes": payload.notes,
                },
            )
        ).one()
        await session.commit()
    return ok(LineItem.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.patch("/line-items/{li_id}")
async def update_line_item(
    li_id: UUID,
    payload: LineItemUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    if "line_kind" in fields and hasattr(fields["line_kind"], "value"):
        fields["line_kind"] = fields["line_kind"].value
    if "schedule_activity_id" in fields and fields["schedule_activity_id"] is not None:
        fields["schedule_activity_id"] = str(fields["schedule_activity_id"])
    set_sql = ", ".join(f"{k} = :{k}" for k in fields)

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(f"UPDATE change_order_line_items SET {set_sql} WHERE id = :id RETURNING *"),
                {**fields, "id": str(li_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Line item not found")
        await session.commit()
    return ok(LineItem.model_validate(_row_to_dict(row)).model_dump(mode="json"))


# ---------- Approvals (state transitions) ----------


@router.post("/cos/{co_id}/approvals", status_code=status.HTTP_201_CREATED)
async def record_approval(
    co_id: UUID,
    payload: ApprovalCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Move a CO to a new state and append to the approval audit log."""
    async with TenantAwareSession(auth.organization_id) as session:
        co = (
            await session.execute(
                text("SELECT status FROM change_orders WHERE id = :id"),
                {"id": str(co_id)},
            )
        ).one_or_none()
        if co is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Change order not found")
        from_status = _row_to_dict(co)["status"]
        new_status = payload.to_status.value

        approval = (
            await session.execute(
                text(
                    """
                INSERT INTO change_order_approvals
                  (organization_id, change_order_id, from_status, to_status,
                   actor_id, notes)
                VALUES (:org, :coid, :from_s, :to_s, :actor, :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "coid": str(co_id),
                    "from_s": from_status,
                    "to_s": new_status,
                    "actor": str(auth.user_id),
                    "notes": payload.notes,
                },
            )
        ).one()
        # Stamp the timestamps + status atomically.
        extra_set = ""
        if new_status == "submitted":
            extra_set = ", submitted_at = COALESCE(submitted_at, NOW())"
        elif new_status == "approved":
            extra_set = ", approved_at = NOW(), approved_by = :approver"
        params: dict[str, Any] = {"status": new_status, "id": str(co_id)}
        if new_status == "approved":
            params["approver"] = str(auth.user_id)
        await session.execute(
            text(f"UPDATE change_orders SET status = :status{extra_set} WHERE id = :id"),
            params,
        )
        # Cross-module rollup: when the CO becomes executed, push every
        # line item with a schedule_activity_id onto its activity. Best-effort
        # (a failure must not block the approval audit row from committing).
        if new_status == "executed":
            try:
                from services.changeorder_schedule_rollup import (
                    apply_change_order_to_schedule,
                )

                await apply_change_order_to_schedule(
                    session,
                    organization_id=auth.organization_id,
                    change_order_id=co_id,
                    actor_id=auth.user_id,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort
                import logging

                logging.getLogger(__name__).warning(
                    "changeorder.executed_rollup: co_id=%s rollup failed: %s",
                    co_id,
                    exc,
                )
        await session.commit()
    return ok(Approval.model_validate(_row_to_dict(approval)).model_dump(mode="json"))


# ---------- AI extract & analyze ----------


@router.post("/extract", status_code=status.HTTP_201_CREATED)
async def extract_candidates_endpoint(
    payload: ExtractCandidatesRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Propose CO candidates from an RFI or pasted text."""
    from ml.pipelines.changeorder import extract_candidates

    if not payload.rfi_id and not payload.text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Either rfi_id or text must be provided",
        )

    async with TenantAwareSession(auth.organization_id) as session:
        text_blob = payload.text
        if payload.rfi_id:
            rfi = (
                await session.execute(
                    text("SELECT subject, description FROM rfis WHERE id = :id"),
                    {"id": str(payload.rfi_id)},
                )
            ).one_or_none()
            if rfi is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "RFI not found")
            rfi_d = _row_to_dict(rfi)
            text_blob = ((rfi_d.get("subject") or "") + "\n\n" + (rfi_d.get("description") or "")).strip()

        proposals = await extract_candidates(text=text_blob or "", source_kind=payload.source_kind.value)
        from ml.pipelines.changeorder import _EXTRACT_MODEL_VERSION as model_version

        rows = []
        for p in proposals:
            row = (
                await session.execute(
                    text(
                        """
                    INSERT INTO change_order_candidates
                      (organization_id, project_id, source_kind, source_rfi_id,
                       source_text_snippet, proposal, model_version, actor_id)
                    VALUES
                      (:org, :pid, :sk, :rfi, :snip, CAST(:proposal AS jsonb),
                       :mv, :actor)
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "pid": str(payload.project_id),
                        "sk": payload.source_kind.value,
                        "rfi": str(payload.rfi_id) if payload.rfi_id else None,
                        "snip": (text_blob or "")[:480],
                        "proposal": json.dumps(p),
                        "mv": model_version,
                        "actor": str(auth.user_id),
                    },
                )
            ).one()
            rows.append(_row_to_dict(row))
        await session.commit()
    return ok([Candidate.model_validate(r).model_dump(mode="json") for r in rows])


@router.post("/candidates/{cand_id}/accept")
async def accept_candidate(
    cand_id: UUID,
    payload: AcceptCandidateRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Promote a candidate into a real CO + line items.

    Idempotent: if `accepted_co_id` is already set, returns the existing CO
    without creating a duplicate.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        cand = (
            await session.execute(
                text("SELECT * FROM change_order_candidates WHERE id = :id"),
                {"id": str(cand_id)},
            )
        ).one_or_none()
        if cand is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
        cand_d = _row_to_dict(cand)
        if cand_d.get("rejected_at"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Candidate has already been rejected",
            )
        if cand_d.get("accepted_co_id"):
            existing = (
                await session.execute(
                    text("SELECT * FROM change_orders WHERE id = :id"),
                    {"id": str(cand_d["accepted_co_id"])},
                )
            ).one_or_none()
            if existing is not None:
                return ok(ChangeOrder.model_validate(_row_to_dict(existing)).model_dump(mode="json"))

        proposal = cand_d.get("proposal") or {}
        title = payload.title_override or proposal.get("title") or "Đề xuất thay đổi"
        description = payload.description_override or proposal.get("description")
        cost = proposal.get("cost_impact_vnd_estimate")
        days = proposal.get("schedule_impact_days_estimate")
        number = await _next_co_number(session, cand_d["project_id"])

        co = (
            await session.execute(
                text(
                    """
                INSERT INTO change_orders
                  (organization_id, project_id, number, title, description,
                   cost_impact_vnd, schedule_impact_days, status)
                VALUES
                  (:org, :pid, :num, :title, :desc, :cost, :days, 'draft')
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "pid": str(cand_d["project_id"]),
                    "num": number,
                    "title": title,
                    "desc": description,
                    "cost": cost,
                    "days": days,
                },
            )
        ).one()
        co_id = _row_to_dict(co)["id"]

        for li in proposal.get("line_items") or []:
            await session.execute(
                text(
                    """
                INSERT INTO change_order_line_items
                  (organization_id, change_order_id, description, line_kind,
                   spec_section, quantity, unit, unit_cost_vnd, cost_vnd,
                   schedule_impact_days)
                VALUES
                  (:org, :coid, :desc, :kind, :spec, :qty, :unit, :uc, :cost, :days)
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "coid": str(co_id),
                    "desc": li.get("description") or "",
                    "kind": li.get("line_kind") or "add",
                    "spec": li.get("spec_section"),
                    "qty": li.get("quantity"),
                    "unit": li.get("unit"),
                    "uc": li.get("unit_cost_vnd"),
                    "cost": li.get("cost_vnd"),
                    "days": li.get("schedule_impact_days"),
                },
            )

        # Backlink the CO source so it shows up in /cos/{id} sources list.
        await session.execute(
            text(
                """
            INSERT INTO change_order_sources
              (organization_id, change_order_id, source_kind, rfi_id, payload, notes)
            VALUES (:org, :coid, :sk, :rfi, CAST(:payload AS jsonb), :notes)
            """
            ),
            {
                "org": str(auth.organization_id),
                "coid": str(co_id),
                "sk": cand_d["source_kind"],
                "rfi": (str(cand_d["source_rfi_id"]) if cand_d.get("source_rfi_id") else None),
                "payload": json.dumps({"candidate_id": str(cand_id), "snippet": cand_d.get("source_text_snippet")}),
                "notes": "Promoted from AI candidate",
            },
        )

        await session.execute(
            text(
                """
            UPDATE change_order_candidates
            SET accepted_co_id = :coid, accepted_at = NOW(), actor_id = :actor
            WHERE id = :id
            """
            ),
            {
                "coid": str(co_id),
                "actor": str(auth.user_id),
                "id": str(cand_id),
            },
        )
        await session.commit()
    return ok(ChangeOrder.model_validate(_row_to_dict(co)).model_dump(mode="json"))


@router.post("/candidates/{cand_id}/reject")
async def reject_candidate(
    cand_id: UUID,
    payload: RejectCandidateRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    """
                UPDATE change_order_candidates
                SET rejected_at = NOW(), rejected_reason = :reason, actor_id = :actor
                WHERE id = :id AND accepted_co_id IS NULL
                RETURNING *
                """
                ),
                {
                    "reason": payload.reason,
                    "actor": str(auth.user_id),
                    "id": str(cand_id),
                },
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Candidate not found or already accepted",
            )
        await session.commit()
    return ok(Candidate.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.post("/cos/{co_id}/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_impact_endpoint(
    co_id: UUID,
    payload: AnalyzeImpactRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Re-estimate the parent CO's cost & schedule impact from line items."""
    from ml.pipelines.changeorder import analyze_impact

    async with TenantAwareSession(auth.organization_id) as session:
        co = (
            await session.execute(
                text(
                    """
                SELECT title, description, cost_impact_vnd, schedule_impact_days,
                       ai_analysis
                FROM change_orders WHERE id = :id
                """
                ),
                {"id": str(co_id)},
            )
        ).one_or_none()
        if co is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Change order not found")
        co_d = _row_to_dict(co)
        if co_d.get("ai_analysis") and not payload.force:
            return ok(co_d["ai_analysis"])

        line_items = [
            _row_to_dict(r)
            for r in (
                await session.execute(
                    text(
                        """
                    SELECT description, line_kind, spec_section, quantity, unit,
                           unit_cost_vnd, cost_vnd, schedule_impact_days
                    FROM change_order_line_items WHERE change_order_id = :id
                    ORDER BY sort_order
                    """
                    ),
                    {"id": str(co_id)},
                )
            ).all()
        ]

        analysis = await analyze_impact(
            title=co_d.get("title") or "",
            description=co_d.get("description"),
            line_items=line_items,
            current_cost_vnd=co_d.get("cost_impact_vnd"),
            current_schedule_days=co_d.get("schedule_impact_days"),
        )
        await session.execute(
            text(
                """
            UPDATE change_orders SET
              cost_impact_vnd = :cost,
              schedule_impact_days = :days,
              ai_analysis = CAST(:analysis AS jsonb)
            WHERE id = :id
            """
            ),
            {
                "cost": analysis.get("cost_impact_vnd"),
                "days": analysis.get("schedule_impact_days"),
                "analysis": json.dumps(analysis),
                "id": str(co_id),
            },
        )
        await session.commit()
    return ok(analysis)


# ---------- Helpers ----------


async def _next_co_number(session: Any, project_id: UUID) -> str:
    """Auto-assign CO-001, CO-002, …. Race-safe via project-scoped uniqueness
    on `change_orders.number` (the existing model's index)."""
    n = (
        await session.execute(
            text(
                """
            SELECT COALESCE(
              MAX(NULLIF(REGEXP_REPLACE(number, '\\D', '', 'g'), '')::int), 0
            ) + 1
            FROM change_orders WHERE project_id = :pid
            """
            ),
            {"pid": str(project_id)},
        )
    ).scalar_one()
    return f"CO-{int(n):03d}"
