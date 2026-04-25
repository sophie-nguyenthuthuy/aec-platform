"""Shared file-upload endpoint used by all modules.

Uploads the raw bytes to S3 under a tenant-scoped key, records a row in `files`,
and for images optionally produces a compressed thumbnail so the mobile PWA
doesn't have to render a 5 MB JPEG over cellular.
"""

from __future__ import annotations

import io
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from core.config import get_settings
from core.envelope import ok
from db.session import TenantAwareSession
from middleware.auth import AuthContext, require_auth

router = APIRouter(prefix="/api/v1/files", tags=["files"])

_MAX_BYTES = 25 * 1024 * 1024
_THUMB_EDGE = 480
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(
    auth: Annotated[AuthContext, Depends(require_auth)],
    file: UploadFile,
    source_module: Annotated[str, Form()],
    project_id: Annotated[UUID | None, Form()] = None,
):
    settings = get_settings()
    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        raise HTTPException(413, "file_too_large")
    if not raw:
        raise HTTPException(400, "empty_file")

    file_id = uuid.uuid4()
    ext = _extension_for(file.content_type, file.filename)
    storage_key = f"{auth.organization_id}/{source_module}/{file_id}{ext}"

    await _s3_put(settings, storage_key, raw, content_type=file.content_type or "application/octet-stream")

    thumbnail_url: str | None = None
    if file.content_type in _IMAGE_MIMES:
        thumbnail_url = await _make_thumbnail(settings, storage_key, raw)

    from sqlalchemy import text

    async with TenantAwareSession(auth.organization_id) as session:
        await session.execute(
            text(
                """
                INSERT INTO files
                  (id, organization_id, project_id, name, storage_key,
                   mime_type, size_bytes, source_module, created_by)
                VALUES
                  (:id, :org, :project_id, :name, :storage_key,
                   :mime, :size, :source_module, :created_by)
                """
            ),
            {
                "id": str(file_id),
                "org": str(auth.organization_id),
                "project_id": str(project_id) if project_id else None,
                "name": file.filename or "unnamed",
                "storage_key": storage_key,
                "mime": file.content_type,
                "size": len(raw),
                "source_module": source_module,
                "created_by": str(auth.user_id),
            },
        )

    return ok(
        {
            "file_id": str(file_id),
            "storage_key": storage_key,
            "thumbnail_url": thumbnail_url,
            "mime_type": file.content_type,
            "size_bytes": len(raw),
        }
    )


async def _make_thumbnail(settings, base_key: str, raw: bytes) -> str | None:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        img.thumbnail((_THUMB_EDGE, _THUMB_EDGE))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
    except Exception:  # noqa: BLE001 — thumbnail is best-effort
        return None

    thumb_key = f"{base_key}.thumb.jpg"
    await _s3_put(settings, thumb_key, buf.getvalue(), content_type="image/jpeg")
    return f"https://{settings.s3_bucket}.s3.{settings.aws_region}.amazonaws.com/{thumb_key}"


async def _s3_put(settings, key: str, body: bytes, *, content_type: str) -> None:
    import aioboto3

    session = aioboto3.Session(region_name=settings.aws_region)
    async with session.client("s3") as client:
        await client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )


def _extension_for(mime: str | None, filename: str | None) -> str:
    if filename and "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime or "", "")
