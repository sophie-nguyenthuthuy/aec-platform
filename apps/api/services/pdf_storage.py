"""Tenant-scoped PDF storage for generated client reports.

Keeps storage keys consistent across modules: `{org_id}/{module}/reports/{id}.pdf`.
Uploads via the same aioboto3 session pattern used by `routers/files.py`.
"""

from __future__ import annotations

import logging
from uuid import UUID

from core.config import Settings

logger = logging.getLogger(__name__)


def report_storage_key(organization_id: UUID, report_id: UUID) -> str:
    """Deterministic S3 key for a client report's PDF artefact."""
    return f"{organization_id}/pulse/reports/{report_id}.pdf"


def report_public_url(settings: Settings, storage_key: str) -> str:
    """Canonical HTTPS URL for the PDF in the configured bucket.

    Delegates to `core.storage.public_url`, which produces the right
    URL shape for AWS S3 (virtual-host), MinIO (path-style via
    endpoint_url), and CDN-fronted setups (`S3_PUBLIC_BASE_URL`).
    """
    from core.storage import public_url

    return public_url(settings, storage_key)


async def upload_report_pdf(
    settings: Settings,
    *,
    organization_id: UUID,
    report_id: UUID,
    pdf_bytes: bytes,
) -> str:
    """Upload `pdf_bytes` to S3-compatible storage and return the URL.

    Returns the URL on success. Callers should catch exceptions and decide
    whether to fail the whole request or persist the report with `pdf_url=None`
    — generating a client report is valuable even if storage hiccups.
    """
    from core.storage import put_bytes

    key = report_storage_key(organization_id, report_id)
    await put_bytes(settings, key, pdf_bytes, content_type="application/pdf")

    logger.info(
        "uploaded report pdf org=%s report=%s size=%d key=%s",
        organization_id,
        report_id,
        len(pdf_bytes),
        key,
    )
    return report_public_url(settings, key)
