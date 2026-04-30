"""RFI/Submittals router — submittal CRUD + AI features over existing RFIs.

Two surfaces under the same prefix:

  * /api/v1/submittals/*           — submittal workflow (CRUD + revisions)
  * /api/v1/submittals/rfis/{id}/* — AI features applied to existing
                                     drawbridge RFIs (similar search,
                                     grounded auto-draft, accept-draft)

Auth via require_auth + tenant via TenantAwareSession (RLS-enforced).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text

from core.envelope import ok, paginated
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth
from schemas.submittals import (
    AcceptDraftRequest,
    BallInCourt,
    RfiDraftRequest,
    RfiResponseDraft,
    RfiSimilarRequest,
    RfiSimilarResponse,
    SimilarRfi,
    Submittal,
    SubmittalCreate,
    SubmittalDetail,
    SubmittalRevision,
    SubmittalRevisionCreate,
    SubmittalRevisionReview,
    SubmittalStatus,
    SubmittalUpdate,
)

router = APIRouter(prefix="/api/v1/submittals", tags=["submittals"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


# ---------- Submittals ----------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_submittal(
    payload: SubmittalCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Create a submittal package + its first revision.

    If `package_number` is omitted, auto-assign the next sequential number
    in the project (S-001, S-002, …). The first SubmittalRevision is
    created automatically so the workflow starts in a usable state.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        if payload.package_number:
            number = payload.package_number
        else:
            number = await _next_submittal_number(session, payload.project_id)

        sub = (
            await session.execute(
                text(
                    """
                INSERT INTO submittals
                  (organization_id, project_id, package_number, title, description,
                   submittal_type, spec_section, csi_division, contractor_id,
                   submitted_by, due_date, notes)
                VALUES
                  (:org, :pid, :num, :title, :desc, :type, :spec, :csi,
                   :contractor, :submitted_by, :due, :notes)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "pid": str(payload.project_id),
                    "num": number,
                    "title": payload.title,
                    "desc": payload.description,
                    "type": payload.submittal_type.value,
                    "spec": payload.spec_section,
                    "csi": payload.csi_division,
                    "contractor": (str(payload.contractor_id) if payload.contractor_id else None),
                    "submitted_by": str(auth.user_id),
                    "due": payload.due_date,
                    "notes": payload.notes,
                },
            )
        ).one()
        sub_d = _row_to_dict(sub)

        await session.execute(
            text(
                """
            INSERT INTO submittal_revisions
              (organization_id, submittal_id, revision_number, file_id)
            VALUES
              (:org, :sid, 1, :file_id)
            """
            ),
            {
                "org": str(auth.organization_id),
                "sid": str(sub_d["id"]),
                "file_id": str(payload.file_id) if payload.file_id else None,
            },
        )
        await session.commit()

    return ok(Submittal.model_validate(sub_d).model_dump(mode="json"))


@router.get("")
async def list_submittals(
    auth: Annotated[AuthContext, Depends(require_auth)],
    project_id: UUID | None = None,
    status_filter: SubmittalStatus | None = Query(default=None, alias="status"),
    ball_in_court: BallInCourt | None = None,
    csi_division: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    where = ["organization_id = :org"]
    params: dict[str, Any] = {"org": str(auth.organization_id)}
    if project_id:
        where.append("project_id = :project_id")
        params["project_id"] = str(project_id)
    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter.value
    if ball_in_court:
        where.append("ball_in_court = :bic")
        params["bic"] = ball_in_court.value
    if csi_division:
        where.append("csi_division = :csi")
        params["csi"] = csi_division
    where_sql = " AND ".join(where)

    async with TenantAwareSession(auth.organization_id) as session:
        total = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM submittals WHERE {where_sql}"),
                params,
            )
        ).scalar_one()
        rows = (
            await session.execute(
                text(
                    f"""
                SELECT * FROM submittals
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
                ),
                {**params, "limit": limit, "offset": offset},
            )
        ).all()

    items = [Submittal.model_validate(_row_to_dict(r)).model_dump(mode="json") for r in rows]
    return paginated(items, page=offset // limit + 1, per_page=limit, total=int(total or 0))


@router.get("/{submittal_id}")
async def get_submittal(
    submittal_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    async with TenantAwareSession(auth.organization_id) as session:
        sub = (
            await session.execute(
                text("SELECT * FROM submittals WHERE id = :id"),
                {"id": str(submittal_id)},
            )
        ).one_or_none()
        if sub is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Submittal not found")
        revs = (
            await session.execute(
                text(
                    """
                SELECT * FROM submittal_revisions
                WHERE submittal_id = :id
                ORDER BY revision_number ASC
                """
                ),
                {"id": str(submittal_id)},
            )
        ).all()

    detail = SubmittalDetail(
        submittal=Submittal.model_validate(_row_to_dict(sub)),
        revisions=[SubmittalRevision.model_validate(_row_to_dict(r)) for r in revs],
    )
    return ok(detail.model_dump(mode="json"))


@router.patch("/{submittal_id}")
async def update_submittal(
    submittal_id: UUID,
    payload: SubmittalUpdate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")
    for k in ("submittal_type", "status", "ball_in_court"):
        if k in fields and hasattr(fields[k], "value"):
            fields[k] = fields[k].value
    if "contractor_id" in fields and fields["contractor_id"] is not None:
        fields["contractor_id"] = str(fields["contractor_id"])

    set_sql = ", ".join(f"{k} = :{k}" for k in fields)
    async with TenantAwareSession(auth.organization_id) as session:
        row = (
            await session.execute(
                text(
                    f"""
                UPDATE submittals SET {set_sql}, updated_at = NOW()
                WHERE id = :id
                RETURNING *
                """
                ),
                {**fields, "id": str(submittal_id)},
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Submittal not found")
        await session.commit()
    return ok(Submittal.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.post("/{submittal_id}/revisions", status_code=status.HTTP_201_CREATED)
async def create_revision(
    submittal_id: UUID,
    payload: SubmittalRevisionCreate,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Add a new revision (e.g. after a "revise & resubmit" cycle).

    Bumps `submittals.current_revision`, resets status to pending_review,
    and flips ball_in_court back to designer.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        next_n = (
            await session.execute(
                text(
                    """
                SELECT COALESCE(MAX(revision_number), 0) + 1
                FROM submittal_revisions WHERE submittal_id = :id
                """
                ),
                {"id": str(submittal_id)},
            )
        ).scalar_one()

        rev = (
            await session.execute(
                text(
                    """
                INSERT INTO submittal_revisions
                  (organization_id, submittal_id, revision_number, file_id, annotations)
                VALUES
                  (:org, :sid, :n, :file_id, CAST(:annotations AS jsonb))
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "sid": str(submittal_id),
                    "n": next_n,
                    "file_id": (str(payload.file_id) if payload.file_id else None),
                    "annotations": json.dumps(payload.annotations),
                },
            )
        ).one()

        await session.execute(
            text(
                """
            UPDATE submittals SET
              current_revision = :n,
              status = 'pending_review',
              ball_in_court = 'designer',
              updated_at = NOW()
            WHERE id = :id
            """
            ),
            {"n": int(next_n), "id": str(submittal_id)},
        )
        await session.commit()

    return ok(SubmittalRevision.model_validate(_row_to_dict(rev)).model_dump(mode="json"))


@router.post("/revisions/{revision_id}/review")
async def review_revision(
    revision_id: UUID,
    payload: SubmittalRevisionReview,
    auth: Annotated[AuthContext, Depends(require_auth)],
    request: Request,
):
    """Designer files a review verdict on a specific revision.

    Side effect: the parent submittal's `status` and `ball_in_court` move
    in lockstep with the revision verdict (approved → contractor closes,
    revise_resubmit → contractor's turn, etc.).
    """
    fields: dict[str, Any] = {
        "review_status": payload.review_status.value,
        "reviewer_notes": payload.reviewer_notes,
    }
    if payload.annotations is not None:
        fields["annotations"] = json.dumps(payload.annotations)

    set_clauses = [
        "review_status = :review_status",
        "reviewer_notes = :reviewer_notes",
        "reviewer_id = :reviewer_id",
        "reviewed_at = NOW()",
    ]
    params: dict[str, Any] = {
        "id": str(revision_id),
        "review_status": fields["review_status"],
        "reviewer_notes": fields["reviewer_notes"],
        "reviewer_id": str(auth.user_id),
    }
    if "annotations" in fields:
        set_clauses.append("annotations = CAST(:annotations AS jsonb)")
        params["annotations"] = fields["annotations"]
    set_sql = ", ".join(set_clauses)

    async with TenantAwareSession(auth.organization_id) as session:
        rev = (
            await session.execute(
                text(f"UPDATE submittal_revisions SET {set_sql} WHERE id = :id RETURNING *"),
                params,
            )
        ).one_or_none()
        if rev is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
        rev_d = _row_to_dict(rev)

        new_sub_status, new_bic = _verdict_to_submittal_state(payload.review_status.value)
        await session.execute(
            text(
                """
            UPDATE submittals SET
              status = :status,
              ball_in_court = :bic,
              closed_at = CASE WHEN :status IN ('approved','approved_as_noted','rejected')
                                THEN NOW() ELSE closed_at END,
              updated_at = NOW()
            WHERE id = :sid
            """
            ),
            {
                "status": new_sub_status,
                "bic": new_bic,
                "sid": str(rev_d["submittal_id"]),
            },
        )

        # Audit: every reviewer verdict is governance-bearing — designers
        # are speaking on behalf of the design intent, contractors will
        # later cite these decisions in close-out. Resource is the
        # parent submittal (not the revision) so a /settings/audit
        # query for "what verdicts were filed against submittal X" is a
        # single resource_id lookup. Resubmittal is also tracked because
        # it's a binding "this version is a no-go" decision even though
        # the submittal stays open.
        from services import audit as _audit

        verdict_to_action: dict[str, str] = {
            "approved": "submittals.review.approve",
            "approved_as_noted": "submittals.review.approve_as_noted",
            "revise_resubmit": "submittals.review.revise_resubmit",
            "rejected": "submittals.review.reject",
        }
        verdict_action = verdict_to_action.get(payload.review_status.value)
        if verdict_action is not None:
            await _audit.record(
                session,
                organization_id=auth.organization_id,
                actor_user_id=auth.user_id,
                action=verdict_action,  # type: ignore[arg-type]
                resource_type="submittals",
                resource_id=rev_d["submittal_id"],
                before={"revision_id": str(revision_id)},
                after={
                    "review_status": payload.review_status.value,
                    "submittal_status": new_sub_status,
                    "ball_in_court": new_bic,
                    "reviewer_notes": payload.reviewer_notes,
                },
                request=request,
            )

        await session.commit()

    return ok(SubmittalRevision.model_validate(rev_d).model_dump(mode="json"))


def _verdict_to_submittal_state(verdict: str) -> tuple[str, str]:
    """Map a revision verdict → (parent submittal status, ball_in_court)."""
    return {
        "approved": ("approved", "contractor"),
        "approved_as_noted": ("approved_as_noted", "contractor"),
        "revise_resubmit": ("revise_resubmit", "contractor"),
        "rejected": ("rejected", "contractor"),
        "pending_review": ("pending_review", "designer"),
    }.get(verdict, ("under_review", "designer"))


# ---------- RFI AI ----------


@router.post("/rfis/{rfi_id}/similar")
async def find_similar_rfis_endpoint(
    rfi_id: UUID,
    payload: RfiSimilarRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Search for past RFIs whose embedding is close to this one.

    Lazy-imports the pipeline so test fixtures can stub `ml.pipelines.rfi`
    without pulling openai / langchain. If the source RFI has no embedding
    yet, a 422 is returned with a hint to call /embed first (the
    drawbridge RFI-create flow can be wired to call this in the future).
    """
    from ml.pipelines.rfi import find_similar_rfis

    async with TenantAwareSession(auth.organization_id) as session:
        # Confirm both the RFI and its embedding exist; surface a clean
        # error rather than letting the recursive query return nothing.
        rfi = (
            await session.execute(
                text("SELECT id, project_id FROM rfis WHERE id = :id"),
                {"id": str(rfi_id)},
            )
        ).one_or_none()
        if rfi is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "RFI not found")
        emb = (
            await session.execute(
                text("SELECT model_version FROM rfi_embeddings WHERE rfi_id = :id"),
                {"id": str(rfi_id)},
            )
        ).one_or_none()
        if emb is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "RFI is not yet embedded; call /api/v1/submittals/rfis/{id}/embed first",
            )

        results = await find_similar_rfis(
            session,
            rfi_id=rfi_id,
            limit=payload.limit,
            max_distance=payload.max_distance,
        )

    resp = RfiSimilarResponse(
        source_rfi_id=rfi_id,
        results=[SimilarRfi.model_validate(r) for r in results],
        embedding_model=_row_to_dict(emb)["model_version"],
    )
    return ok(resp.model_dump(mode="json"))


@router.post("/rfis/{rfi_id}/embed", status_code=status.HTTP_202_ACCEPTED)
async def embed_rfi_endpoint(
    rfi_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Compute and persist the embedding for an RFI.

    Idempotent — the underlying pipeline upserts on (rfi_id) so this is
    safe to call whenever the RFI is created or its subject/description
    changes.
    """
    from ml.pipelines.rfi import upsert_rfi_embedding

    async with TenantAwareSession(auth.organization_id) as session:
        rfi = (
            await session.execute(
                text("SELECT subject, description FROM rfis WHERE id = :id"),
                {"id": str(rfi_id)},
            )
        ).one_or_none()
        if rfi is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "RFI not found")
        rfi_d = _row_to_dict(rfi)
        model_version = await upsert_rfi_embedding(
            session,
            organization_id=auth.organization_id,
            rfi_id=rfi_id,
            subject=rfi_d["subject"],
            description=rfi_d.get("description"),
        )
        await session.commit()
    return ok({"rfi_id": str(rfi_id), "model_version": model_version})


@router.post("/rfis/{rfi_id}/draft", status_code=status.HTTP_201_CREATED)
async def draft_rfi_response_endpoint(
    rfi_id: UUID,
    payload: RfiDraftRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Generate a grounded draft response. Cached for `cache_minutes`."""
    from ml.pipelines.rfi import draft_rfi_response

    async with TenantAwareSession(auth.organization_id) as session:
        # Cache lookup
        if payload.cache_minutes > 0:
            cutoff = datetime.now(UTC) - timedelta(minutes=payload.cache_minutes)
            cached = (
                await session.execute(
                    text(
                        """
                    SELECT * FROM rfi_response_drafts
                    WHERE rfi_id = :id AND generated_at >= :cutoff
                    ORDER BY generated_at DESC LIMIT 1
                    """
                    ),
                    {"id": str(rfi_id), "cutoff": cutoff},
                )
            ).one_or_none()
            if cached:
                return ok(RfiResponseDraft.model_validate(_row_to_dict(cached)).model_dump(mode="json"))

        rfi = (
            await session.execute(
                text(
                    """
                SELECT id, project_id, subject, description, response
                FROM rfis WHERE id = :id
                """
                ),
                {"id": str(rfi_id)},
            )
        ).one_or_none()
        if rfi is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "RFI not found")
        rfi_d = _row_to_dict(rfi)

        result = await draft_rfi_response(session, rfi=rfi_d, retrieval_k=payload.retrieval_k)

        row = (
            await session.execute(
                text(
                    """
                INSERT INTO rfi_response_drafts
                  (organization_id, rfi_id, draft_text, citations, model_version)
                VALUES
                  (:org, :rfi_id, :draft, CAST(:cits AS jsonb), :mv)
                RETURNING *
                """
                ),
                {
                    "org": str(auth.organization_id),
                    "rfi_id": str(rfi_id),
                    "draft": result["draft_text"],
                    "cits": json.dumps(result["citations"]),
                    "mv": result["model_version"],
                },
            )
        ).one()
        await session.commit()

    return ok(RfiResponseDraft.model_validate(_row_to_dict(row)).model_dump(mode="json"))


@router.post("/drafts/{draft_id}/accept")
async def accept_draft(
    draft_id: UUID,
    payload: AcceptDraftRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
):
    """Promote a draft to the RFI's `response` column and stamp accepted_at."""
    async with TenantAwareSession(auth.organization_id) as session:
        draft = (
            await session.execute(
                text(
                    """
                UPDATE rfi_response_drafts SET
                  accepted_at = NOW(),
                  accepted_by = :user_id,
                  notes = :notes
                WHERE id = :id
                RETURNING *
                """
                ),
                {
                    "id": str(draft_id),
                    "user_id": str(auth.user_id),
                    "notes": payload.notes,
                },
            )
        ).one_or_none()
        if draft is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
        draft_d = _row_to_dict(draft)
        await session.execute(
            text(
                """
            UPDATE rfis SET response = :response, status = 'answered'
            WHERE id = :rfi_id
            """
            ),
            {"response": draft_d["draft_text"], "rfi_id": str(draft_d["rfi_id"])},
        )
        await session.commit()
    return ok(RfiResponseDraft.model_validate(draft_d).model_dump(mode="json"))


# ---------- Helpers ----------


async def _next_submittal_number(session: Any, project_id: UUID) -> str:
    """Auto-assign S-001 etc. Race-safe enough for typical traffic; if two
    concurrent creates collide on the unique constraint, the second will
    fail and the caller can retry."""
    n = (
        await session.execute(
            text(
                """
            SELECT COALESCE(
              MAX(NULLIF(REGEXP_REPLACE(package_number, '\\D', '', 'g'), '')::int),
              0
            ) + 1
            FROM submittals WHERE project_id = :pid
            """
            ),
            {"pid": str(project_id)},
        )
    ).scalar_one()
    return f"S-{int(n):03d}"
