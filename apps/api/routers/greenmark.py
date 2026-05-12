"""GREENMARK router — VGBC LOTUS + IFC EDGE certification endpoints."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.greenmark import (
    LOTUS_LEVEL_THRESHOLDS,
    CertDetail,
    CertListFilters,
    CertStatus,
    CertSummary,
    CertSystem,
    GapToNextLevel,
    GreenCertification,
    GreenCertificationCreate,
    GreenCertificationUpdate,
    GreenCredit,
    GreenCreditCreate,
    GreenCreditUpdate,
    ScoreBreakdownRow,
    ScoreResult,
    SeedCreditsRequest,
    TargetLevel,
    lotus_level_for_points,
    score_for_credit,
)

router = APIRouter(prefix="/api/v1/greenmark", tags=["greenmark"])


# ---------- Seed catalogs ----------
#
# Minimal default catalogs per system. Real deployments ship much larger
# lists (LOTUS NR v3 has ~50 credits across 7 categories); we keep the
# in-code list short and treat it as a starting scaffold. Operators
# extend via the import pipeline or the add-credit endpoint.

_LOTUS_NR_SEED: list[dict[str, Any]] = [
    {"code": "LOTUS-EN-01", "category": "energy", "title": "Hiệu suất năng lượng tối thiểu", "max_points": "18"},
    {"code": "LOTUS-EN-02", "category": "energy", "title": "Năng lượng tái tạo", "max_points": "5"},
    {"code": "LOTUS-WT-01", "category": "water", "title": "Tiết kiệm nước trong nhà", "max_points": "8"},
    {"code": "LOTUS-WT-02", "category": "water", "title": "Quản lý nước mưa", "max_points": "3"},
    {"code": "LOTUS-MT-01", "category": "materials", "title": "Vật liệu tái chế", "max_points": "6"},
    {"code": "LOTUS-MT-02", "category": "materials", "title": "Vật liệu địa phương", "max_points": "4"},
    {"code": "LOTUS-IQ-01", "category": "ieq", "title": "Chất lượng không khí trong nhà", "max_points": "10"},
    {"code": "LOTUS-IQ-02", "category": "ieq", "title": "Ánh sáng tự nhiên", "max_points": "4"},
    {"code": "LOTUS-ST-01", "category": "site", "title": "Vị trí dự án", "max_points": "5"},
    {"code": "LOTUS-OP-01", "category": "operations", "title": "Quản lý vận hành", "max_points": "5"},
    {"code": "LOTUS-IN-01", "category": "innovation", "title": "Sáng kiến thiết kế", "max_points": "5"},
]

_LOTUS_HOMES_SEED: list[dict[str, Any]] = [
    {"code": "LH-EN-01", "category": "energy", "title": "Cách nhiệt vỏ công trình", "max_points": "12"},
    {"code": "LH-EN-02", "category": "energy", "title": "Thiết bị tiết kiệm điện", "max_points": "8"},
    {"code": "LH-WT-01", "category": "water", "title": "Thiết bị tiết kiệm nước", "max_points": "6"},
    {"code": "LH-MT-01", "category": "materials", "title": "Vật liệu thân thiện môi trường", "max_points": "5"},
    {"code": "LH-IQ-01", "category": "ieq", "title": "Thông gió tự nhiên", "max_points": "6"},
    {"code": "LH-IN-01", "category": "innovation", "title": "Sáng kiến", "max_points": "3"},
]

_EDGE_SEED: list[dict[str, Any]] = [
    {"code": "EDGE-EN-1", "category": "energy", "title": "Cải thiện cách nhiệt vỏ", "max_points": "20"},
    {"code": "EDGE-EN-2", "category": "energy", "title": "Thiết bị HVAC hiệu suất cao", "max_points": "20"},
    {"code": "EDGE-EN-3", "category": "energy", "title": "Chiếu sáng LED", "max_points": "10"},
    {"code": "EDGE-WT-1", "category": "water", "title": "Vòi/sen tiết kiệm nước", "max_points": "10"},
    {"code": "EDGE-WT-2", "category": "water", "title": "Tái sử dụng nước xám", "max_points": "10"},
    {"code": "EDGE-MT-1", "category": "materials", "title": "Bê-tông carbon thấp", "max_points": "10"},
    {"code": "EDGE-MT-2", "category": "materials", "title": "Khung cửa nhôm tái chế", "max_points": "10"},
    {"code": "EDGE-MT-3", "category": "materials", "title": "Gạch không nung", "max_points": "10"},
]


def _seed_for_system(system: CertSystem) -> list[dict[str, Any]]:
    if system == CertSystem.edge:
        return _EDGE_SEED
    if system == CertSystem.lotus_homes:
        return _LOTUS_HOMES_SEED
    # lotus_nr / lotus_bio / lotus_intl all share the NR seed by default —
    # operators tune per-system later via imports.
    return _LOTUS_NR_SEED


# ---------- Certifications ----------


@router.post("/certifications", status_code=status.HTTP_201_CREATED)
async def create_certification(
    payload: GreenCertificationCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    cert_id = uuid4()
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO green_certifications
                      (id, organization_id, project_id, system, target_level,
                       status, achieved_points, max_points, project_brief,
                       assessor_name, notes, created_by, created_at, updated_at)
                    VALUES
                      (:id, :org, :project_id, :system, :target_level,
                       'planning', 0, 0, CAST(:brief AS jsonb),
                       :assessor_name, :notes, :created_by, NOW(), NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(cert_id),
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "system": payload.system.value,
                        "target_level": payload.target_level.value,
                        "brief": _json(payload.project_brief),
                        "assessor_name": payload.assessor_name,
                        "notes": payload.notes,
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(GreenCertification.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/certifications")
async def list_certifications(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    system: CertSystem | None = None,
    cert_status: CertStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = CertListFilters(project_id=project_id, system=system, status=cert_status, limit=limit, offset=offset)
    where, params = _cert_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.*,
                      COALESCE(cr.total, 0)::int AS credit_total,
                      COALESCE(cr.verified, 0)::int AS credit_verified
                    FROM green_certifications c
                    LEFT JOIN (
                      SELECT certification_id,
                             COUNT(*) AS total,
                             COUNT(*) FILTER (WHERE status = 'verified') AS verified
                      FROM green_credits GROUP BY certification_id
                    ) cr ON cr.certification_id = c.id
                    WHERE {where}
                    ORDER BY c.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (
            await session.execute(text(f"SELECT COUNT(*) FROM green_certifications c WHERE {where}"), params)
        ).scalar_one()

    items = [CertSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/certifications/{cert_id}")
async def get_certification(
    cert_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM green_certifications
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cert is None:
            raise HTTPException(status_code=404, detail="certification_not_found")
        credits = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM green_credits
                    WHERE certification_id = :id
                    ORDER BY category, sort_order, code
                    """
                    ),
                    {"id": str(cert_id)},
                )
            )
            .mappings()
            .all()
        )
    detail = CertDetail.model_validate(
        {
            **dict(cert),
            "credits": [GreenCredit.model_validate(dict(c)) for c in credits],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/certifications/{cert_id}")
async def update_certification(
    cert_id: UUID,
    payload: GreenCertificationUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(cert_id), "org": str(auth.organization_id)}
    for col, val in (
        ("target_level", payload.target_level),
        ("status", payload.status),
        ("certification_no", payload.certification_no),
        ("awarded_at", payload.awarded_at),
        ("valid_until", payload.valid_until),
        ("assessor_name", payload.assessor_name),
        ("notes", payload.notes),
    ):
        if val is None:
            continue
        if hasattr(val, "value"):
            val = val.value
        assigns.append(f"{col} = :{col}")
        params[col] = val
    if payload.project_brief is not None:
        assigns.append("project_brief = CAST(:brief AS jsonb)")
        params["brief"] = _json(payload.project_brief)
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE green_certifications SET {", ".join(assigns)}
                    WHERE id = :id AND organization_id = :org
                    RETURNING *
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise HTTPException(status_code=404, detail="certification_not_found")
    return ok(GreenCertification.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Seed credits ----------


@router.post("/certifications/{cert_id}/seed-credits", status_code=status.HTTP_201_CREATED)
async def seed_credits(
    cert_id: UUID,
    payload: SeedCreditsRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Idempotent seed of the default credit catalog for the
    certification's system. Skips codes already present."""
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, system FROM green_certifications
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cert is None:
            raise HTTPException(status_code=404, detail="certification_not_found")

        existing = (
            (
                await session.execute(
                    text("SELECT code FROM green_credits WHERE certification_id = :id"),
                    {"id": str(cert_id)},
                )
            )
            .scalars()
            .all()
        )
        existing_set = set(existing)
        seed = _seed_for_system(CertSystem(cert["system"]))

        seeded = 0
        for idx, item in enumerate(seed):
            if item["code"] in existing_set:
                continue
            await session.execute(
                text(
                    """
                INSERT INTO green_credits
                  (id, organization_id, certification_id, code, category, title,
                   max_points, sort_order)
                VALUES
                  (:id, :org, :cert_id, :code, :category, :title,
                   :max_points, :sort_order)
                """
                ),
                {
                    "id": str(uuid4()),
                    "org": str(auth.organization_id),
                    "cert_id": str(cert_id),
                    "code": item["code"],
                    "category": item["category"],
                    "title": item["title"],
                    "max_points": Decimal(item["max_points"]),
                    "sort_order": idx,
                },
            )
            seeded += 1

        # Refresh header max_points so the list-card percent matches.
        await _do_recompute(session, cert_id)

    return ok(
        {
            "certification_id": str(cert_id),
            "template_version": payload.template_version,
            "seeded": seeded,
            "already_present": len(existing_set),
        }
    )


@router.post("/certifications/{cert_id}/credits", status_code=status.HTTP_201_CREATED)
async def add_credit(
    cert_id: UUID,
    payload: GreenCreditCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            await session.execute(
                text("SELECT id FROM green_certifications WHERE id = :id AND organization_id = :org"),
                {"id": str(cert_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if cert is None:
            raise HTTPException(status_code=404, detail="certification_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO green_credits
                      (id, organization_id, certification_id, code, category, title,
                       description, max_points, sort_order)
                    VALUES
                      (:id, :org, :cert_id, :code, :category, :title,
                       :description, :max_points, :sort_order)
                    RETURNING *
                    """
                    ),
                    {
                        "id": str(uuid4()),
                        "org": str(auth.organization_id),
                        "cert_id": str(cert_id),
                        "code": payload.code,
                        "category": payload.category.value,
                        "title": payload.title,
                        "description": payload.description,
                        "max_points": payload.max_points,
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )
        await _do_recompute(session, cert_id)
    return ok(GreenCredit.model_validate(dict(row)).model_dump(mode="json"))


@router.patch("/credits/{credit_id}")
async def update_credit(
    credit_id: UUID,
    payload: GreenCreditUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(credit_id), "org": str(auth.organization_id)}
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
        if payload.status.value in ("verified", "rejected"):
            assigns.append("reviewed_at = NOW()")
            assigns.append("reviewer_user_id = :reviewer_user_id")
            params["reviewer_user_id"] = str(auth.user_id)
    if payload.claimed_points is not None:
        assigns.append("claimed_points = :claimed_points")
        params["claimed_points"] = payload.claimed_points
    if payload.awarded_points is not None:
        assigns.append("awarded_points = :awarded_points")
        params["awarded_points"] = payload.awarded_points
    if payload.computed_metrics is not None:
        assigns.append("computed_metrics = CAST(:computed_metrics AS jsonb)")
        params["computed_metrics"] = _json(payload.computed_metrics)
    if payload.evidence_file_ids is not None:
        assigns.append("evidence_file_ids = CAST(:evidence AS uuid[])")
        params["evidence"] = [str(f) for f in payload.evidence_file_ids]
    if payload.reviewer_note is not None:
        assigns.append("reviewer_note = :reviewer_note")
        params["reviewer_note"] = payload.reviewer_note
    if len(assigns) == 1:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE green_credits SET {", ".join(assigns)}
                    WHERE id = :id AND organization_id = :org
                    RETURNING *
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="credit_not_found")
        # Bump header score so the list card stays current.
        await _do_recompute(session, row["certification_id"])

    return ok(GreenCredit.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Score + gap ----------


@router.post("/certifications/{cert_id}/score")
async def score_certification(
    cert_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Recompute the score + persist on the header.

    Returns a per-category breakdown so the UI can render a stacked-bar
    chart without a second round-trip.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, system FROM green_certifications
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cert is None:
            raise HTTPException(status_code=404, detail="certification_not_found")
        result = await _do_recompute_full(session, cert_id, CertSystem(cert["system"]))
    return ok(result.model_dump(mode="json"))


@router.get("/certifications/{cert_id}/gap")
async def gap_to_next_level(
    cert_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Surface the cheapest credits to push from current level → next.

    Only meaningful for LOTUS systems (point-based). EDGE returns an
    empty `candidate_credits` since its gap is savings-percentage
    based, not point-additive.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        cert = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, system, achieved_points FROM green_certifications
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(cert_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if cert is None:
            raise HTTPException(status_code=404, detail="certification_not_found")

        current = lotus_level_for_points(Decimal(cert["achieved_points"]))
        next_level = _next_lotus_level(current)
        if next_level is None or CertSystem(cert["system"]) == CertSystem.edge:
            return ok(
                GapToNextLevel(
                    certification_id=cert_id,
                    current_level=current,
                    next_level=None,
                    points_needed=Decimal("0"),
                    candidate_credits=[],
                ).model_dump(mode="json")
            )

        gap = Decimal(LOTUS_LEVEL_THRESHOLDS[next_level]) - Decimal(cert["achieved_points"])
        # Candidate credits = un-attempted ones with max_points > 0, ordered by points desc.
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM green_credits
                    WHERE certification_id = :id
                      AND status IN ('not_attempted', 'targeted')
                      AND max_points > 0
                    ORDER BY max_points DESC, code ASC
                    LIMIT 10
                    """
                    ),
                    {"id": str(cert_id)},
                )
            )
            .mappings()
            .all()
        )
    return ok(
        GapToNextLevel(
            certification_id=cert_id,
            current_level=current,
            next_level=next_level,
            points_needed=max(gap, Decimal("0")),
            candidate_credits=[GreenCredit.model_validate(dict(r)) for r in rows],
        ).model_dump(mode="json")
    )


# ---------- Internal helpers ----------


def _next_lotus_level(current: TargetLevel | None) -> TargetLevel | None:
    chain = [
        TargetLevel.certified,
        TargetLevel.silver,
        TargetLevel.gold,
        TargetLevel.platinum,
    ]
    if current is None:
        return TargetLevel.certified
    if current == TargetLevel.platinum:
        return None
    idx = chain.index(current)
    return chain[idx + 1]


async def _do_recompute(session, cert_id: UUID) -> None:
    """Lightweight: just sum the running totals onto the header."""
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT status, claimed_points, awarded_points, max_points
                FROM green_credits WHERE certification_id = :id
                """
                ),
                {"id": str(cert_id)},
            )
        )
        .mappings()
        .all()
    )
    achieved = Decimal("0")
    max_pts = Decimal("0")
    for r in rows:
        achieved += score_for_credit(dict(r))
        max_pts += Decimal(r["max_points"])
    await session.execute(
        text(
            """
        UPDATE green_certifications SET
          achieved_points = :achieved,
          max_points = :max_pts,
          achieved_level = :level,
          updated_at = NOW()
        WHERE id = :id
        """
        ),
        {
            "id": str(cert_id),
            "achieved": achieved,
            "max_pts": max_pts,
            "level": (lotus_level_for_points(achieved) or None) and lotus_level_for_points(achieved).value,  # type: ignore[union-attr]
        },
    )


async def _do_recompute_full(session, cert_id: UUID, system: CertSystem) -> ScoreResult:
    """Recompute + return the per-category breakdown."""
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT category, status, claimed_points, awarded_points, max_points
                FROM green_credits WHERE certification_id = :id
                """
                ),
                {"id": str(cert_id)},
            )
        )
        .mappings()
        .all()
    )
    by_cat: dict[str, dict[str, Decimal]] = {}
    achieved_total = Decimal("0")
    max_total = Decimal("0")
    for r in rows:
        cat = r["category"]
        bucket = by_cat.setdefault(cat, {"earned": Decimal("0"), "max": Decimal("0")})
        bucket["earned"] += score_for_credit(dict(r))
        bucket["max"] += Decimal(r["max_points"])
        achieved_total += score_for_credit(dict(r))
        max_total += Decimal(r["max_points"])

    breakdown = [
        ScoreBreakdownRow(category=cat, earned_points=v["earned"], max_points=v["max"])  # type: ignore[arg-type]
        for cat, v in sorted(by_cat.items())
    ]
    level = lotus_level_for_points(achieved_total) if system != CertSystem.edge else None

    await session.execute(
        text(
            """
        UPDATE green_certifications SET
          achieved_points = :achieved,
          max_points = :max_pts,
          achieved_level = :level,
          updated_at = NOW()
        WHERE id = :id
        """
        ),
        {
            "id": str(cert_id),
            "achieved": achieved_total,
            "max_pts": max_total,
            "level": level.value if level else None,
        },
    )

    return ScoreResult(
        certification_id=cert_id,
        system=system,
        achieved_points=achieved_total,
        max_points=max_total,
        achieved_level=level,
        breakdown=breakdown,
    )


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=_default_serializer, ensure_ascii=False)


def _default_serializer(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not serializable: {type(value)}")


def _cert_where(f: CertListFilters, org_id: UUID) -> tuple[str, dict[str, Any]]:
    clauses = ["c.organization_id = :org"]
    params: dict[str, Any] = {"org": str(org_id)}
    if f.project_id:
        clauses.append("c.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.system:
        clauses.append("c.system = :system")
        params["system"] = f.system.value
    if f.status:
        clauses.append("c.status = :status")
        params["status"] = f.status.value
    return " AND ".join(clauses), params


__all__ = ["router"]
