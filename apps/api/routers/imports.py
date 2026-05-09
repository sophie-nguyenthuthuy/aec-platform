"""CSV/XLSX bulk-import endpoints.

Two-phase pipeline (see `services/imports.py` for the rationale):

  * `POST /api/v1/import/{entity}/preview` — multipart upload. Parses
    the file, validates each row, and writes a `previewed` row to
    `import_jobs`. Returns the row count, valid count, and the per-row
    error list so the frontend can render a preview table.

  * `GET  /api/v1/import/jobs/{job_id}` — re-fetch a previewed job.
    Useful when the user navigates away mid-flow.

  * `POST /api/v1/import/jobs/{job_id}/commit` — replay the validated
    rows against the target table. Idempotent — re-running it on the
    same job is a no-op (status check).

Admin-gated: bulk import is a destructive privilege (it can over-write
existing rows via the upsert), so we require Role.ADMIN at every
endpoint. The `entity` path param is whitelisted to match the SQL
helper's allowed list — defense in depth against a router refactor
that forgets to validate.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import text

from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext
from middleware.rbac import Role, require_min_role
from services.imports import (
    MAX_ROWS,
    VALIDATORS,
    commit_job,
    parse_upload,
    validate_rows,
)

router = APIRouter(prefix="/api/v1/import", tags=["import"])


# Whitelist mirrors `services.imports.VALIDATORS`. Repeat it as a
# Literal so FastAPI rejects junk before we reach the validator dict
# lookup — saves a 500/400 round-trip and gives clean OpenAPI docs.
EntityName = Literal["projects", "suppliers"]


# Cap upload bytes so a malicious 1GB upload can't OOM the worker.
# 5MB lets a 1000-row spreadsheet with rich content through with room
# to spare; openpyxl streams XLSX so the in-memory cost stays bounded.
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/{entity}/preview", status_code=201)
async def preview_import(
    entity: EntityName,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
    file: UploadFile,
):
    """Parse + validate a CSV/XLSX upload. Persists the result to a
    new `import_jobs` row in `previewed` state and returns the
    summary + the validation errors for the preview table."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file_too_large: max {_MAX_UPLOAD_BYTES} bytes",
        )

    try:
        raw_rows = parse_upload(content=raw, filename=file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    valid, errors = validate_rows(entity=entity, raw_rows=raw_rows)

    # Persist the previewed payload. We store both `rows` (validated)
    # and `errors` (per-row failures) so the commit step doesn't
    # re-parse the file — the upload bytes can be GC'd immediately.
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                """
                INSERT INTO import_jobs (
                    id, organization_id, user_id, entity, filename,
                    status, row_count, valid_count, error_count,
                    rows, errors
                ) VALUES (
                    gen_random_uuid(), :org_id, :user_id, :entity, :filename,
                    'previewed', :row_count, :valid_count, :error_count,
                    CAST(:rows AS JSONB), CAST(:errors AS JSONB)
                )
                RETURNING id, created_at
                """
            ),
            {
                "org_id": str(auth.organization_id),
                "user_id": str(auth.user_id),
                "entity": entity,
                "filename": file.filename or "upload",
                "row_count": len(raw_rows),
                "valid_count": len(valid),
                "error_count": len(errors),
                "rows": _to_json(valid),
                "errors": _to_json(errors),
            },
        )
        row = result.mappings().one()
        await session.commit()

    return ok(
        {
            "id": str(row["id"]),
            "entity": entity,
            "filename": file.filename or "upload",
            "status": "previewed",
            "row_count": len(raw_rows),
            "valid_count": len(valid),
            "error_count": len(errors),
            "errors": errors,
            "created_at": row["created_at"].isoformat(),
        }
    )


@router.get("/jobs/{job_id}")
async def get_import_job(
    job_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Re-fetch a previewed/committed job. RLS keeps the lookup
    tenant-scoped — a forged ID from another org returns 404."""
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                """
                SELECT id, entity, filename, status, row_count, valid_count,
                       error_count, errors, committed_count, created_at,
                       committed_at
                FROM import_jobs
                WHERE id = :id
                """
            ),
            {"id": str(job_id)},
        )
        row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="import_job_not_found")
    return ok(
        {
            "id": str(row["id"]),
            "entity": row["entity"],
            "filename": row["filename"],
            "status": row["status"],
            "row_count": row["row_count"],
            "valid_count": row["valid_count"],
            "error_count": row["error_count"],
            "errors": row["errors"],
            "committed_count": row["committed_count"],
            "created_at": row["created_at"].isoformat(),
            "committed_at": row["committed_at"].isoformat() if row["committed_at"] else None,
        }
    )


@router.post("/jobs/{job_id}/commit")
async def commit_import_job(
    job_id: UUID,
    auth: Annotated[AuthContext, Depends(require_min_role(Role.ADMIN))],
):
    """Run the upsert for a previewed job. Returns the count of rows
    written. Idempotent: re-calling on a job that's already been
    committed returns the prior committed_count instead of re-running
    the SQL — the partial unique index would let a second run be a
    no-op anyway, but skipping the DB round-trip is friendlier.

    A job whose preview produced 100% errors (`error_count > 0` and
    `valid_count == 0`) is rejected with 400 — there's nothing to
    commit, and surfacing the contradiction explicitly is clearer than
    a silent zero-row commit.
    """
    async with TenantAwareSession(auth.organization_id) as session:
        result = await session.execute(
            text(
                """
                SELECT id, entity, status, valid_count, error_count, rows,
                       committed_count
                FROM import_jobs
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": str(job_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="import_job_not_found")
        if row["status"] == "committed":
            # Idempotent: already done, just echo the count.
            return ok(
                {
                    "id": str(row["id"]),
                    "status": "committed",
                    "committed_count": row["committed_count"] or 0,
                }
            )
        if row["status"] != "previewed":
            raise HTTPException(
                status_code=400,
                detail=f"job in {row['status']!r} state cannot be committed",
            )
        if row["valid_count"] == 0:
            raise HTTPException(
                status_code=400,
                detail="no valid rows to commit (fix the validation errors and re-upload)",
            )

        try:
            written = await commit_job(
                session=session,
                organization_id=auth.organization_id,
                entity=row["entity"],
                rows=row["rows"],
            )
        except Exception as exc:
            # Mark the job failed so the UI can show a retryable state.
            await session.execute(
                text("UPDATE import_jobs SET status = 'failed' WHERE id = :id"),
                {"id": str(job_id)},
            )
            await session.commit()
            raise HTTPException(status_code=500, detail=f"commit_failed: {exc}") from exc

        await session.execute(
            text(
                """
                UPDATE import_jobs
                SET status = 'committed',
                    committed_count = :written,
                    committed_at = NOW()
                WHERE id = :id
                """
            ),
            {"written": written, "id": str(job_id)},
        )
        await session.commit()

    return ok(
        {
            "id": str(job_id),
            "status": "committed",
            "committed_count": written,
        }
    )


def _to_json(v: object) -> str:
    """Serialise a Python object to a JSON string for `CAST(:x AS
    JSONB)`. Done explicitly so dict/list payloads round-trip cleanly
    through asyncpg's plain-text bind path."""
    import json

    return json.dumps(v, default=str)


# Schemas surface the validator allowlist for the frontend so a
# "Tải file mẫu" button can render the right placeholder columns.
__all__ = ["router", "MAX_ROWS", "VALIDATORS"]
