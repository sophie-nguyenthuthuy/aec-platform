"""S3-compatible object storage client.

Single place where the platform talks to its object store. Supports
both AWS S3 (production cloud option) and MinIO (self-hosted option for
on-prem deploys — required for Vietnamese SOE customers who can't ship
PII / drawings to a US-region AWS account).

Settings:
  * `s3_endpoint_url` — set this to MinIO's URL (e.g.
    `https://minio.aec-platform.vn`) to use MinIO. Leave None to use AWS.
  * `s3_bucket` — bucket / MinIO bucket name (default: `aec-platform-files`)
  * `aws_region` — AWS region OR MinIO region label (default:
    `ap-southeast-1`)
  * `s3_access_key_id` / `s3_secret_access_key` — credentials. On AWS
    these can be left None to fall through to the default provider
    chain (IAM role, ~/.aws/credentials). On MinIO they're required.
  * `s3_force_path_style` — MinIO requires path-style URLs
    (`{endpoint}/{bucket}/{key}`); AWS supports both but newer regions
    require virtual-hosted style. Defaults to True when
    `s3_endpoint_url` is set, False otherwise.
  * `s3_public_base_url` — if MinIO is fronted by a CDN / reverse proxy
    serving the bucket publicly, use this as the read URL base.
    Otherwise we generate presigned GET URLs at fetch time.

Two surfaces:
  * `put_bytes(key, body, content_type)` — synchronous write via aioboto3.
  * `presigned_get(key, expires_seconds)` — short-lived read URL.
  * `public_url(key)` — non-expiring URL if `s3_public_base_url` is set,
    falls back to AWS-style virtual-host URL otherwise.

Tests stub `aioboto3` directly (see `tests/test_retention.py`); this
module just orchestrates.
"""

from __future__ import annotations

from typing import Any


def _client_kwargs(settings: Any) -> dict[str, Any]:
    """Build the boto3/aioboto3 client kwargs from settings.

    Returns a dict suitable for `Session.client("s3", **kwargs)`. Includes
    `endpoint_url` only when set, so AWS default routing keeps working.
    """
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if getattr(settings, "s3_endpoint_url", None):
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    if getattr(settings, "s3_access_key_id", None):
        kwargs["aws_access_key_id"] = settings.s3_access_key_id
    if getattr(settings, "s3_secret_access_key", None):
        kwargs["aws_secret_access_key"] = settings.s3_secret_access_key
    # Path-style addressing — MinIO requires it; AWS tolerates it.
    if getattr(settings, "s3_force_path_style", None) or getattr(
        settings, "s3_endpoint_url", None
    ):
        from botocore.config import Config

        kwargs["config"] = Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
        )
    return kwargs


async def put_bytes(
    settings: Any, key: str, body: bytes, *, content_type: str
) -> None:
    """Upload bytes to the configured bucket under `key`.

    Lazy-imports `aioboto3` so cold-start of routes that never touch S3
    (most of the API surface) stays fast.
    """
    import aioboto3

    session = aioboto3.Session()
    async with session.client("s3", **_client_kwargs(settings)) as client:
        await client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )


async def presigned_get(
    settings: Any, key: str, *, expires_seconds: int = 3600
) -> str:
    """Return a short-lived presigned GET URL for `key`.

    Use for sensitive content (drawings, photos) where you don't want
    to expose the file publicly. Default 1-hour TTL — the front-end
    re-fetches the URL when the cached one nears expiry.
    """
    import aioboto3

    session = aioboto3.Session()
    async with session.client("s3", **_client_kwargs(settings)) as client:
        return await client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )


def public_url(settings: Any, key: str) -> str:
    """Return a non-expiring public URL for `key`.

    Resolution order:
      1. `s3_public_base_url` — set this to your CDN / reverse-proxy if
         you're serving the bucket publicly (e.g. behind Cloudflare).
      2. `s3_endpoint_url` — MinIO direct, path-style.
      3. AWS virtual-host style.

    For MinIO without a public proxy, use `presigned_get` instead —
    raw MinIO URLs require auth.
    """
    base = getattr(settings, "s3_public_base_url", None)
    if base:
        return f"{base.rstrip('/')}/{key}"
    endpoint = getattr(settings, "s3_endpoint_url", None)
    if endpoint:
        return f"{endpoint.rstrip('/')}/{settings.s3_bucket}/{key}"
    return (
        f"https://{settings.s3_bucket}.s3.{settings.aws_region}"
        f".amazonaws.com/{key}"
    )
