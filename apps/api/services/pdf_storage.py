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

    If you later switch to signed URLs (e.g. for non-public buckets), this is
    the single place to change — the route calls it, tests stub it.
    """
    return f"https://{settings.s3_bucket}.s3.{settings.aws_region}.amazonaws.com/{storage_key}"


async def upload_report_pdf(
    settings: Settings,
    *,
    organization_id: UUID,
    report_id: UUID,
    pdf_bytes: bytes,
) -> str:
    """Upload `pdf_bytes` to S3 and return the public URL.

    Returns the URL on success. Callers should catch exceptions and decide
    whether to fail the whole request or persist the report with `pdf_url=None`
    — generating a client report is valuable even if the CDN hiccups.
    """
    import aioboto3  # lazy: not every API workload needs S3 at import time

    key = report_storage_key(organization_id, report_id)
    session = aioboto3.Session(region_name=settings.aws_region)
    async with session.client("s3") as client:
        await client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )

    logger.info(
        "uploaded report pdf org=%s report=%s size=%d key=%s",
        organization_id,
        report_id,
        len(pdf_bytes),
        key,
    )
    return report_public_url(settings, key)
