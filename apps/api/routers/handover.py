"""HANDOVER FastAPI router — project closeout & as-built intelligence endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.handover import (
    AsBuiltDrawing,
    AsBuiltRegister,
    CloseoutItem,
    CloseoutItemCreate,
    CloseoutItemUpdate,
    Defect,
    DefectCreate,
    DefectListFilters,
    DefectPriority,
    DefectStatus,
    DefectUpdate,
    HandoverPackage,
    HandoverPackageCreate,
    HandoverPackageUpdate,
    OmManual,
    OmManualGenerateRequest,
    OmManualStatus,
    PackageDetail,
    PackageListFilters,
    PackageStatus,
    PackageSummary,
    PromotedDrawingSummary,
    PromoteDrawingsRequest,
    PromoteDrawingsResponse,
    WarrantyExtractRequest,
    WarrantyExtractResponse,
    WarrantyItem,
    WarrantyItemCreate,
    WarrantyItemUpdate,
    WarrantyListFilters,
    WarrantyStatus,
)

router = APIRouter(prefix="/api/v1/handover", tags=["handover"])


# ---------- Packages ----------


@router.post("/packages", status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: HandoverPackageCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    from ml.pipelines.handover import seed_closeout_items

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO handover_packages
                      (organization_id, project_id, name, scope_summary, created_by)
                    VALUES
                      (:org, :project_id, :name, CAST(:scope AS jsonb), :created_by)
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "name": payload.name,
                        "scope": _json(payload.scope_summary),
                        "created_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )

        if payload.auto_populate:
            await seed_closeout_items(
                db=session,
                organization_id=auth.organization_id,
                package_id=row["id"],
                scope_summary=payload.scope_summary,
            )

    return ok(HandoverPackage.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/packages")
async def list_packages(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    package_status: PackageStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    filters = PackageListFilters(project_id=project_id, status=package_status, limit=limit, offset=offset)
    where, params = _package_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT
                      p.*,
                      COALESCE(ci.total, 0)::int AS closeout_total,
                      COALESCE(ci.done, 0)::int AS closeout_done,
                      COALESCE(w.expiring, 0)::int AS warranty_expiring,
                      COALESCE(d.open_count, 0)::int AS open_defects
                    FROM handover_packages p
                    LEFT JOIN (
                      SELECT package_id,
                             COUNT(*) AS total,
                             COUNT(*) FILTER (WHERE status = 'done') AS done
                      FROM closeout_items GROUP BY package_id
                    ) ci ON ci.package_id = p.id
                    LEFT JOIN (
                      SELECT package_id, COUNT(*) AS expiring
                      FROM warranty_items
                      WHERE status IN ('expiring', 'active')
                        AND expiry_date IS NOT NULL
                        AND expiry_date <= (CURRENT_DATE + INTERVAL '60 days')
                      GROUP BY package_id
                    ) w ON w.package_id = p.id
                    LEFT JOIN (
                      SELECT package_id, COUNT(*) AS open_count
                      FROM defects
                      WHERE status IN ('open', 'assigned', 'in_progress')
                      GROUP BY package_id
                    ) d ON d.package_id = p.id
                    WHERE {where}
                    ORDER BY p.created_at DESC
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
            await session.execute(text(f"SELECT COUNT(*) FROM handover_packages p WHERE {where}"), params)
        ).scalar_one()

    items = [PackageSummary.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.get("/packages/{package_id}")
async def get_package(
    package_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        pkg_row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM handover_packages
                    WHERE id = :id AND organization_id = :org
                    """
                    ),
                    {"id": str(package_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if pkg_row is None:
            raise HTTPException(status_code=404, detail="package_not_found")

        item_rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM closeout_items
                    WHERE package_id = :id
                    ORDER BY sort_order ASC, created_at ASC
                    """
                    ),
                    {"id": str(package_id)},
                )
            )
            .mappings()
            .all()
        )

    detail = PackageDetail.model_validate(
        {
            **dict(pkg_row),
            "closeout_items": [CloseoutItem.model_validate(dict(r)) for r in item_rows],
        }
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/packages/{package_id}")
async def update_package(
    package_id: UUID,
    payload: HandoverPackageUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = []
    params: dict[str, Any] = {"id": str(package_id), "org": str(auth.organization_id)}
    if payload.name is not None:
        assigns.append("name = :name")
        params["name"] = payload.name
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
        if payload.status == PackageStatus.delivered:
            assigns.append("delivered_at = :delivered_at")
            params["delivered_at"] = datetime.now(UTC)
    if payload.scope_summary is not None:
        assigns.append("scope_summary = CAST(:scope AS jsonb)")
        params["scope"] = _json(payload.scope_summary)
    if not assigns:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE handover_packages SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="package_not_found")
    return ok(HandoverPackage.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Closeout items ----------


@router.post("/packages/{package_id}/closeout-items", status_code=status.HTTP_201_CREATED)
async def add_closeout_item(
    package_id: UUID,
    payload: CloseoutItemCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        pkg = (
            await session.execute(
                text("SELECT id FROM handover_packages WHERE id = :id AND organization_id = :org"),
                {"id": str(package_id), "org": str(auth.organization_id)},
            )
        ).scalar_one_or_none()
        if pkg is None:
            raise HTTPException(status_code=404, detail="package_not_found")

        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO closeout_items
                      (organization_id, package_id, category, title, description,
                       required, sort_order, updated_at)
                    VALUES
                      (:org, :package_id, :category, :title, :description,
                       :required, :sort_order, NOW())
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "package_id": str(package_id),
                        "category": payload.category.value,
                        "title": payload.title,
                        "description": payload.description,
                        "required": payload.required,
                        "sort_order": payload.sort_order,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(CloseoutItem.model_validate(dict(row)).model_dump(mode="json"))


@router.patch("/closeout-items/{item_id}")
async def update_closeout_item(
    item_id: UUID,
    payload: CloseoutItemUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = ["updated_at = NOW()"]
    params: dict[str, Any] = {"id": str(item_id), "org": str(auth.organization_id)}
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
    if payload.assignee_id is not None:
        assigns.append("assignee_id = :assignee_id")
        params["assignee_id"] = str(payload.assignee_id)
    if payload.notes is not None:
        assigns.append("notes = :notes")
        params["notes"] = payload.notes
    if payload.file_ids is not None:
        assigns.append("file_ids = CAST(:file_ids AS uuid[])")
        params["file_ids"] = [str(f) for f in payload.file_ids]

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE closeout_items SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="closeout_item_not_found")
    return ok(CloseoutItem.model_validate(dict(row)).model_dump(mode="json"))


# ---------- As-built drawings ----------


@router.post("/as-builts", status_code=status.HTTP_201_CREATED)
async def register_as_built(
    payload: AsBuiltRegister,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    now = datetime.now(UTC)
    async with TenantAwareSession(auth.organization_id) as session:
        existing = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM as_built_drawings
                    WHERE project_id = :project_id AND drawing_code = :code
                      AND organization_id = :org
                    """
                    ),
                    {
                        "project_id": str(payload.project_id),
                        "code": payload.drawing_code,
                        "org": str(auth.organization_id),
                    },
                )
            )
            .mappings()
            .first()
        )

        if existing is None:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        INSERT INTO as_built_drawings
                          (organization_id, project_id, package_id, drawing_code,
                           discipline, title, current_version, current_file_id,
                           superseded_file_ids, changelog, last_updated_at)
                        VALUES
                          (:org, :project_id, :package_id, :code,
                           :discipline, :title, 1, :file_id,
                           ARRAY[]::uuid[], CAST(:changelog AS jsonb), :now)
                        RETURNING *
                        """
                        ),
                        {
                            "org": str(auth.organization_id),
                            "project_id": str(payload.project_id),
                            "package_id": str(payload.package_id) if payload.package_id else None,
                            "code": payload.drawing_code,
                            "discipline": payload.discipline.value,
                            "title": payload.title,
                            "file_id": str(payload.file_id),
                            "changelog": _json(
                                [
                                    {
                                        "version": 1,
                                        "file_id": str(payload.file_id),
                                        "change_note": payload.change_note,
                                        "recorded_at": now.isoformat(),
                                    }
                                ]
                            ),
                            "now": now,
                        },
                    )
                )
                .mappings()
                .one()
            )
        else:
            new_version = (existing["current_version"] or 0) + 1
            superseded = list(existing["superseded_file_ids"] or [])
            if existing["current_file_id"]:
                superseded.append(existing["current_file_id"])
            changelog = list(existing["changelog"] or [])
            changelog.append(
                {
                    "version": new_version,
                    "file_id": str(payload.file_id),
                    "change_note": payload.change_note,
                    "recorded_at": now.isoformat(),
                }
            )
            row = (
                (
                    await session.execute(
                        text(
                            """
                        UPDATE as_built_drawings
                        SET current_version = :version,
                            current_file_id = :file_id,
                            superseded_file_ids = CAST(:superseded AS uuid[]),
                            changelog = CAST(:changelog AS jsonb),
                            title = :title,
                            discipline = :discipline,
                            package_id = COALESCE(:package_id, package_id),
                            last_updated_at = :now
                        WHERE id = :id
                        RETURNING *
                        """
                        ),
                        {
                            "version": new_version,
                            "file_id": str(payload.file_id),
                            "superseded": [str(s) for s in superseded],
                            "changelog": _json(changelog),
                            "title": payload.title,
                            "discipline": payload.discipline.value,
                            "package_id": str(payload.package_id) if payload.package_id else None,
                            "now": now,
                            "id": existing["id"],
                        },
                    )
                )
                .mappings()
                .one()
            )
    return ok(AsBuiltDrawing.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/projects/{project_id}/as-builts")
async def list_as_builts(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    discipline: str | None = None,
):
    params: dict[str, Any] = {
        "org": str(auth.organization_id),
        "project_id": str(project_id),
    }
    where = "organization_id = :org AND project_id = :project_id"
    if discipline:
        where += " AND discipline = :discipline"
        params["discipline"] = discipline
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT * FROM as_built_drawings
                    WHERE {where}
                    ORDER BY discipline, drawing_code
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    items = [AsBuiltDrawing.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return ok(items)


@router.post("/packages/{package_id}/promote-drawings")
async def promote_drawings_from_drawbridge(
    package_id: UUID,
    payload: PromoteDrawingsRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """DRAWBRIDGE → HANDOVER handoff: sweep the package's project for the
    latest-revision drawing per drawing_number and register each as an
    as-built. Skips documents with missing file_id or drawing_number.

    Idempotent — re-running with the same set of drawings is a no-op because
    the upsert keys on (project_id, drawing_code) and bumps version only
    when the file_id differs.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        package = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, project_id FROM handover_packages
                    WHERE id = :pkg AND organization_id = :org
                    """
                    ),
                    {"pkg": str(package_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .first()
        )
        if package is None:
            raise HTTPException(status_code=404, detail="package_not_found")

        project_id = package["project_id"]

        # Pull candidate drawbridge documents. ORDER BY (drawing_number, created_at DESC)
        # then dedupe in Python so we get the newest Document per drawing_number
        # without relying on Postgres DISTINCT ON quirks.
        where = [
            "d.organization_id = :org",
            "d.project_id = :project_id",
            "d.drawing_number IS NOT NULL",
            "d.file_id IS NOT NULL",
        ]
        params: dict[str, Any] = {
            "org": str(auth.organization_id),
            "project_id": str(project_id),
        }
        if payload.discipline:
            where.append("d.discipline = :discipline")
            params["discipline"] = payload.discipline.value
        if payload.drawing_number_like:
            where.append("d.drawing_number ILIKE :dn_like")
            params["dn_like"] = payload.drawing_number_like

        docs = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT d.id, d.drawing_number, d.title, d.revision, d.discipline,
                           d.file_id, d.created_at
                    FROM documents d
                    WHERE {" AND ".join(where)}
                    ORDER BY d.drawing_number ASC, d.created_at DESC
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

        # Keep only the latest per drawing_number (first one in the sort above).
        latest_per_number: dict[str, dict[str, Any]] = {}
        for d in docs:
            dn = d["drawing_number"]
            if dn and dn not in latest_per_number:
                latest_per_number[dn] = dict(d)

        summaries: list[PromotedDrawingSummary] = []
        now = datetime.now(UTC)

        for drawing_code, doc in latest_per_number.items():
            title = (doc["title"] or drawing_code)[:200]
            discipline = (doc["discipline"] or "architecture").lower()

            existing = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT id, current_version, current_file_id,
                               superseded_file_ids, changelog
                        FROM as_built_drawings
                        WHERE organization_id = :org
                          AND project_id = :project_id
                          AND drawing_code = :code
                        """
                        ),
                        {
                            "org": str(auth.organization_id),
                            "project_id": str(project_id),
                            "code": drawing_code,
                        },
                    )
                )
                .mappings()
                .first()
            )

            change_note = f"Promoted from DRAWBRIDGE document {doc['id']}" + (
                f" (rev {doc['revision']})" if doc["revision"] else ""
            )

            if existing is None:
                await session.execute(
                    text(
                        """
                        INSERT INTO as_built_drawings
                          (organization_id, project_id, package_id, drawing_code,
                           discipline, title, current_version, current_file_id,
                           superseded_file_ids, changelog, last_updated_at)
                        VALUES
                          (:org, :project_id, :package_id, :code,
                           :discipline, :title, 1, :file_id,
                           ARRAY[]::uuid[], CAST(:changelog AS jsonb), :now)
                        """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "project_id": str(project_id),
                        "package_id": str(package_id),
                        "code": drawing_code,
                        "discipline": discipline,
                        "title": title,
                        "file_id": str(doc["file_id"]),
                        "changelog": _json(
                            [
                                {
                                    "version": 1,
                                    "file_id": str(doc["file_id"]),
                                    "change_note": change_note,
                                    "recorded_at": now.isoformat(),
                                }
                            ]
                        ),
                        "now": now,
                    },
                )
                summaries.append(
                    PromotedDrawingSummary(
                        drawing_code=drawing_code,
                        action="created",
                        current_version=1,
                    )
                )
            elif str(existing["current_file_id"]) == str(doc["file_id"]):
                # Same file already registered → no-op
                summaries.append(
                    PromotedDrawingSummary(
                        drawing_code=drawing_code,
                        action="skipped",
                        current_version=existing["current_version"],
                        reason="already_current",
                    )
                )
            else:
                new_version = (existing["current_version"] or 0) + 1
                superseded = list(existing["superseded_file_ids"] or [])
                if existing["current_file_id"]:
                    superseded.append(existing["current_file_id"])
                changelog = list(existing["changelog"] or [])
                changelog.append(
                    {
                        "version": new_version,
                        "file_id": str(doc["file_id"]),
                        "change_note": change_note,
                        "recorded_at": now.isoformat(),
                    }
                )
                await session.execute(
                    text(
                        """
                        UPDATE as_built_drawings
                        SET current_version = :version,
                            current_file_id = :file_id,
                            superseded_file_ids = CAST(:superseded AS uuid[]),
                            changelog = CAST(:changelog AS jsonb),
                            title = :title,
                            discipline = :discipline,
                            package_id = COALESCE(package_id, :package_id),
                            last_updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "version": new_version,
                        "file_id": str(doc["file_id"]),
                        "superseded": [str(s) for s in superseded],
                        "changelog": _json(changelog),
                        "title": title,
                        "discipline": discipline,
                        "package_id": str(package_id),
                        "now": now,
                        "id": existing["id"],
                    },
                )
                summaries.append(
                    PromotedDrawingSummary(
                        drawing_code=drawing_code,
                        action="versioned",
                        current_version=new_version,
                    )
                )

    return ok(
        PromoteDrawingsResponse(
            package_id=package_id,
            project_id=project_id,
            documents_considered=len(docs),
            promoted=summaries,
        ).model_dump(mode="json")
    )


# ---------- O&M manual ----------


@router.post("/om-manuals/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_om_manual(
    payload: OmManualGenerateRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    from ml.pipelines.handover import generate_om_manual as run_pipeline

    manual_id = uuid4()
    job_id = uuid4()
    now = datetime.now(UTC)
    title = payload.title or f"O&M Manual — {payload.discipline.value}"

    async with TenantAwareSession(auth.organization_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO ai_jobs (id, organization_id, module, job_type, status, input, started_at)
                VALUES (:id, :org, 'handover', 'om_manual', 'running',
                        CAST(:input AS jsonb), :now)
                """
            ),
            {
                "id": str(job_id),
                "org": str(auth.organization_id),
                "input": _json(payload.model_dump(mode="json")),
                "now": now,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO om_manuals
                  (id, organization_id, project_id, package_id, title, discipline,
                   status, source_file_ids, ai_job_id, generated_at, created_by)
                VALUES
                  (:id, :org, :project_id, :package_id, :title, :discipline,
                   'generating', CAST(:source_ids AS uuid[]), :job_id, :now, :created_by)
                """
            ),
            {
                "id": str(manual_id),
                "org": str(auth.organization_id),
                "project_id": str(payload.project_id),
                "package_id": str(payload.package_id) if payload.package_id else None,
                "title": title,
                "discipline": payload.discipline.value,
                "source_ids": [str(f) for f in payload.source_file_ids],
                "job_id": str(job_id),
                "now": now,
                "created_by": str(auth.user_id),
            },
        )

    # Run pipeline in the same request for simplicity; offload to a worker for
    # long documents (> 30 s) — the 202 status signals async intent either way.
    try:
        async with TenantAwareSession(auth.organization_id) as session:
            equipment, schedule = await run_pipeline(
                db=session,
                project_id=payload.project_id,
                discipline=payload.discipline,
                source_file_ids=payload.source_file_ids,
            )
    except Exception as exc:
        async with TenantAwareSession(auth.organization_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE om_manuals SET status = 'failed' WHERE id = :id;
                    UPDATE ai_jobs SET status = 'failed', error = :err, completed_at = NOW()
                    WHERE id = :job_id
                    """
                ),
                {"id": str(manual_id), "err": str(exc)[:500], "job_id": str(job_id)},
            )
        raise HTTPException(status_code=502, detail=f"om_manual_pipeline_failed: {exc}") from exc

    new_status = OmManualStatus.ready if equipment else OmManualStatus.failed
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    UPDATE om_manuals SET
                      status = :status,
                      equipment = CAST(:equipment AS jsonb),
                      maintenance_schedule = CAST(:schedule AS jsonb)
                    WHERE id = :id
                    RETURNING *
                    """
                    ),
                    {
                        "status": new_status.value,
                        "equipment": _json([e.model_dump(mode="json") for e in equipment]),
                        "schedule": _json([t.model_dump(mode="json") for t in schedule]),
                        "id": str(manual_id),
                    },
                )
            )
            .mappings()
            .one()
        )
        await session.execute(
            text("UPDATE ai_jobs SET status = 'completed', completed_at = NOW() WHERE id = :job_id"),
            {"job_id": str(job_id)},
        )

    return ok(OmManual.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/packages/{package_id}/om-manuals")
async def list_om_manuals(
    package_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT * FROM om_manuals
                    WHERE package_id = :id AND organization_id = :org
                    ORDER BY generated_at DESC
                    """
                    ),
                    {"id": str(package_id), "org": str(auth.organization_id)},
                )
            )
            .mappings()
            .all()
        )
    items = [OmManual.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return ok(items)


# ---------- Warranties ----------


@router.post("/warranties/extract", status_code=status.HTTP_201_CREATED)
async def extract_warranty(
    payload: WarrantyExtractRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    from ml.pipelines.handover import extract_warranty_items

    async with TenantAwareSession(auth.organization_id) as session:
        try:
            items = await extract_warranty_items(
                db=session,
                project_id=payload.project_id,
                package_id=payload.package_id,
                contract_file_ids=payload.contract_file_ids,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"warranty_extraction_failed: {exc}") from exc

        created: list[dict] = []
        for item in items:
            row = (
                (
                    await session.execute(
                        text(
                            """
                        INSERT INTO warranty_items
                          (organization_id, project_id, package_id, item_name, category,
                           vendor, contract_file_id, warranty_period_months,
                           start_date, expiry_date, coverage, claim_contact)
                        VALUES
                          (:org, :project_id, :package_id, :item_name, :category,
                           :vendor, :contract_file_id, :period,
                           :start_date, :expiry_date, :coverage, CAST(:contact AS jsonb))
                        RETURNING *
                        """
                        ),
                        {
                            "org": str(auth.organization_id),
                            "project_id": str(item.project_id),
                            "package_id": str(item.package_id) if item.package_id else None,
                            "item_name": item.item_name,
                            "category": item.category,
                            "vendor": item.vendor,
                            "contract_file_id": str(item.contract_file_id) if item.contract_file_id else None,
                            "period": item.warranty_period_months,
                            "start_date": item.start_date,
                            "expiry_date": item.expiry_date,
                            "coverage": item.coverage,
                            "contact": _json(item.claim_contact),
                        },
                    )
                )
                .mappings()
                .one()
            )
            created.append(dict(row))

    response = WarrantyExtractResponse(
        contract_file_ids=payload.contract_file_ids,
        extracted_count=len(created),
        items=[_to_warranty_schema(r) for r in created],
    )
    return ok(response.model_dump(mode="json"))


@router.post("/warranties", status_code=status.HTTP_201_CREATED)
async def create_warranty(
    payload: WarrantyItemCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO warranty_items
                      (organization_id, project_id, package_id, item_name, category,
                       vendor, contract_file_id, warranty_period_months,
                       start_date, expiry_date, coverage, claim_contact, notes)
                    VALUES
                      (:org, :project_id, :package_id, :item_name, :category,
                       :vendor, :contract_file_id, :period,
                       :start_date, :expiry_date, :coverage, CAST(:contact AS jsonb), :notes)
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "package_id": str(payload.package_id) if payload.package_id else None,
                        "item_name": payload.item_name,
                        "category": payload.category,
                        "vendor": payload.vendor,
                        "contract_file_id": str(payload.contract_file_id) if payload.contract_file_id else None,
                        "period": payload.warranty_period_months,
                        "start_date": payload.start_date,
                        "expiry_date": payload.expiry_date,
                        "coverage": payload.coverage,
                        "contact": _json(payload.claim_contact),
                        "notes": payload.notes,
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(_to_warranty_schema(dict(row)).model_dump(mode="json"))


@router.get("/warranties")
async def list_warranties(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    package_id: UUID | None = None,
    warranty_status: WarrantyStatus | None = Query(None, alias="status"),
    expiring_within_days: int | None = Query(None, ge=0, le=3650),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = WarrantyListFilters(
        project_id=project_id,
        package_id=package_id,
        status=warranty_status,
        expiring_within_days=expiring_within_days,
        limit=limit,
        offset=offset,
    )
    where, params = _warranty_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT * FROM warranty_items
                    WHERE {where}
                    ORDER BY expiry_date ASC NULLS LAST, created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (await session.execute(text(f"SELECT COUNT(*) FROM warranty_items WHERE {where}"), params)).scalar_one()

    items = [_to_warranty_schema(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.patch("/warranties/{warranty_id}")
async def update_warranty(
    warranty_id: UUID,
    payload: WarrantyItemUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = []
    params: dict[str, Any] = {"id": str(warranty_id), "org": str(auth.organization_id)}
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
    if payload.notes is not None:
        assigns.append("notes = :notes")
        params["notes"] = payload.notes
    if payload.claim_contact is not None:
        assigns.append("claim_contact = CAST(:contact AS jsonb)")
        params["contact"] = _json(payload.claim_contact)
    if not assigns:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE warranty_items SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="warranty_not_found")
    return ok(_to_warranty_schema(dict(row)).model_dump(mode="json"))


# ---------- Defects ----------


@router.post("/defects", status_code=status.HTTP_201_CREATED)
async def create_defect(
    payload: DefectCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO defects
                      (organization_id, project_id, package_id, title, description,
                       location, photo_file_ids, priority, assignee_id, reported_by)
                    VALUES
                      (:org, :project_id, :package_id, :title, :description,
                       CAST(:location AS jsonb), CAST(:photos AS uuid[]),
                       :priority, :assignee_id, :reported_by)
                    RETURNING *
                    """
                    ),
                    {
                        "org": str(auth.organization_id),
                        "project_id": str(payload.project_id),
                        "package_id": str(payload.package_id) if payload.package_id else None,
                        "title": payload.title,
                        "description": payload.description,
                        "location": _json(payload.location) if payload.location is not None else None,
                        "photos": [str(p) for p in payload.photo_file_ids],
                        "priority": payload.priority.value,
                        "assignee_id": str(payload.assignee_id) if payload.assignee_id else None,
                        "reported_by": str(auth.user_id),
                    },
                )
            )
            .mappings()
            .one()
        )
    return ok(Defect.model_validate(dict(row)).model_dump(mode="json"))


@router.get("/defects")
async def list_defects(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    package_id: UUID | None = None,
    defect_status: DefectStatus | None = Query(None, alias="status"),
    priority: DefectPriority | None = None,
    assignee_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = DefectListFilters(
        project_id=project_id,
        package_id=package_id,
        status=defect_status,
        priority=priority,
        assignee_id=assignee_id,
        limit=limit,
        offset=offset,
    )
    where, params = _defect_where(filters, auth.organization_id)
    async with TenantAwareSession(auth.organization_id) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT * FROM defects
                    WHERE {where}
                    ORDER BY
                      CASE status
                        WHEN 'open' THEN 0 WHEN 'assigned' THEN 1 WHEN 'in_progress' THEN 2
                        WHEN 'resolved' THEN 3 WHEN 'rejected' THEN 4
                      END,
                      CASE priority
                        WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3
                      END,
                      reported_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                    ),
                    {**params, "limit": limit, "offset": offset},
                )
            )
            .mappings()
            .all()
        )
        total = (await session.execute(text(f"SELECT COUNT(*) FROM defects WHERE {where}"), params)).scalar_one()

    items = [Defect.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=total)


@router.patch("/defects/{defect_id}")
async def update_defect(
    defect_id: UUID,
    payload: DefectUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    assigns: list[str] = []
    params: dict[str, Any] = {"id": str(defect_id), "org": str(auth.organization_id)}
    if payload.status is not None:
        assigns.append("status = :status")
        params["status"] = payload.status.value
        if payload.status == DefectStatus.resolved:
            assigns.append("resolved_at = :resolved_at")
            params["resolved_at"] = datetime.now(UTC)
    if payload.priority is not None:
        assigns.append("priority = :priority")
        params["priority"] = payload.priority.value
    if payload.assignee_id is not None:
        assigns.append("assignee_id = :assignee_id")
        params["assignee_id"] = str(payload.assignee_id)
    if payload.description is not None:
        assigns.append("description = :description")
        params["description"] = payload.description
    if payload.location is not None:
        assigns.append("location = CAST(:location AS jsonb)")
        params["location"] = _json(payload.location)
    if payload.photo_file_ids is not None:
        assigns.append("photo_file_ids = CAST(:photos AS uuid[])")
        params["photos"] = [str(p) for p in payload.photo_file_ids]
    if payload.resolution_notes is not None:
        assigns.append("resolution_notes = :resolution_notes")
        params["resolution_notes"] = payload.resolution_notes
    if not assigns:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    UPDATE defects SET {", ".join(assigns)}
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
        raise HTTPException(status_code=404, detail="defect_not_found")
    return ok(Defect.model_validate(dict(row)).model_dump(mode="json"))


# ---------- Helpers ----------


def _json(value: Any) -> str | None:
    import json as _std_json

    if value is None:
        return None
    return _std_json.dumps(value, default=_default_serializer, ensure_ascii=False)


def _default_serializer(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"not serializable: {type(value)}")


def _to_warranty_schema(row: dict) -> WarrantyItem:
    data = dict(row)
    expiry = data.get("expiry_date")
    if expiry:
        data["days_to_expiry"] = (expiry - date.today()).days
    return WarrantyItem.model_validate(data)


def _package_where(f: PackageListFilters, org_id: UUID) -> tuple[str, dict]:
    clauses = ["p.organization_id = :org"]
    params: dict = {"org": str(org_id)}
    if f.project_id:
        clauses.append("p.project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.status:
        clauses.append("p.status = :status")
        params["status"] = f.status.value
    return " AND ".join(clauses), params


def _warranty_where(f: WarrantyListFilters, org_id: UUID) -> tuple[str, dict]:
    clauses = ["organization_id = :org"]
    params: dict = {"org": str(org_id)}
    if f.project_id:
        clauses.append("project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.package_id:
        clauses.append("package_id = :package_id")
        params["package_id"] = str(f.package_id)
    if f.status:
        clauses.append("status = :status")
        params["status"] = f.status.value
    if f.expiring_within_days is not None:
        clauses.append("expiry_date IS NOT NULL AND expiry_date <= :cutoff")
        params["cutoff"] = date.today() + timedelta(days=f.expiring_within_days)
    return " AND ".join(clauses), params


def _defect_where(f: DefectListFilters, org_id: UUID) -> tuple[str, dict]:
    clauses = ["organization_id = :org"]
    params: dict = {"org": str(org_id)}
    if f.project_id:
        clauses.append("project_id = :project_id")
        params["project_id"] = str(f.project_id)
    if f.package_id:
        clauses.append("package_id = :package_id")
        params["package_id"] = str(f.package_id)
    if f.status:
        clauses.append("status = :status")
        params["status"] = f.status.value
    if f.priority:
        clauses.append("priority = :priority")
        params["priority"] = f.priority.value
    if f.assignee_id:
        clauses.append("assignee_id = :assignee_id")
        params["assignee_id"] = str(f.assignee_id)
    return " AND ".join(clauses), params
