"""Router-level tests for /api/v1/files.

The upload endpoint touches S3 (aioboto3), Pillow (for images), and Postgres
via `TenantAwareSession`. All three are mocked — we only verify HTTP wiring,
size limits, thumbnail branching, and that an INSERT is attempted with the
expected fields.
"""
from __future__ import annotations

import io
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(fake_auth) -> Iterator[FastAPI]:
    """Mount only the files router so a failure in another router doesn't
    block collection. No `get_db` override is needed — the router uses
    `TenantAwareSession` directly, which tests patch per-call.
    """
    from core.envelope import http_exception_handler, unhandled_exception_handler
    from middleware.auth import require_auth
    from routers import files as files_router

    test_app = FastAPI()
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)
    test_app.include_router(files_router.router)
    test_app.dependency_overrides[require_auth] = lambda: fake_auth
    try:
        yield test_app
    finally:
        test_app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class _RecordingSession:
    """Minimal async session that records every `execute()` call."""
    def __init__(self) -> None:
        self.executes: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        # Stringify the statement so tests can substring-match without
        # depending on SQLAlchemy's text-clause repr internals.
        self.executes.append((str(stmt), params or {}))
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result


@pytest.fixture
def patch_session(monkeypatch):
    """Replace `routers.files.TenantAwareSession` with a context manager that
    yields a recording fake session. Returns the recording session so tests
    can assert what SQL was attempted.
    """
    session = _RecordingSession()

    @asynccontextmanager
    async def _fake_session(org_id: Any):
        yield session

    class _FakeTenantAwareSession:
        def __init__(self, org_id: Any) -> None:
            self._cm = _fake_session(org_id)
        async def __aenter__(self):
            return await self._cm.__aenter__()
        async def __aexit__(self, exc_type, exc, tb):
            return await self._cm.__aexit__(exc_type, exc, tb)

    monkeypatch.setattr("routers.files.TenantAwareSession", _FakeTenantAwareSession)
    return session


@pytest.fixture
def patch_s3(monkeypatch):
    """Replace `routers.files._s3_put` with an AsyncMock that records puts."""
    put = AsyncMock(return_value=None)
    monkeypatch.setattr("routers.files._s3_put", put)
    return put


# ---------- Tests ----------

async def test_upload_rejects_empty_file(client, patch_session, patch_s3):
    r = await client.post(
        "/api/v1/files",
        data={"source_module": "drawbridge"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert r.status_code == 400
    assert "empty_file" in r.text
    # Nothing should have been written to S3 or DB
    patch_s3.assert_not_awaited()
    assert patch_session.executes == []


async def test_upload_rejects_too_large(client, patch_session, patch_s3):
    oversized = b"x" * (25 * 1024 * 1024 + 1)
    r = await client.post(
        "/api/v1/files",
        data={"source_module": "drawbridge"},
        files={"file": ("big.bin", oversized, "application/octet-stream")},
    )
    assert r.status_code == 413
    assert "file_too_large" in r.text
    patch_s3.assert_not_awaited()


async def test_upload_pdf_skips_thumbnail_and_records_row(
    client, patch_session, patch_s3, fake_auth
):
    body = b"%PDF-1.4\n%fake pdf bytes"
    r = await client.post(
        "/api/v1/files",
        data={"source_module": "drawbridge"},
        files={"file": ("spec.pdf", body, "application/pdf")},
    )

    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["mime_type"] == "application/pdf"
    assert data["size_bytes"] == len(body)
    assert data["thumbnail_url"] is None
    # Storage key is scoped to org + module and ends with the right extension
    assert data["storage_key"].startswith(f"{fake_auth.organization_id}/drawbridge/")
    assert data["storage_key"].endswith(".pdf")

    # S3 received exactly one put (original, no thumbnail)
    assert patch_s3.await_count == 1
    # And one INSERT into `files` was attempted
    assert len(patch_session.executes) == 1
    sql, params = patch_session.executes[0]
    assert "INSERT INTO files" in sql
    assert params["mime"] == "application/pdf"
    assert params["source_module"] == "drawbridge"
    assert params["size"] == len(body)
    assert params["org"] == str(fake_auth.organization_id)
    assert params["created_by"] == str(fake_auth.user_id)


async def test_upload_image_generates_thumbnail(
    client, patch_session, patch_s3, monkeypatch
):
    # Stub Pillow's Image.open → a MagicMock image. We don't need real bytes
    # since `_s3_put` is also mocked; we just want the thumbnail branch to run.
    fake_image = MagicMock()
    fake_image.thumbnail = MagicMock()
    fake_image.convert.return_value.save = MagicMock(
        side_effect=lambda buf, **kw: buf.write(b"\xff\xd8\xff\xd9")  # minimal JPEG-ish
    )

    import PIL.Image
    monkeypatch.setattr(PIL.Image, "open", lambda _: fake_image)

    r = await client.post(
        "/api/v1/files",
        data={"source_module": "siteeye"},
        files={"file": ("photo.jpg", b"fakejpegbytes", "image/jpeg")},
    )

    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["thumbnail_url"] is not None
    assert data["thumbnail_url"].endswith(".thumb.jpg")
    # S3 got two puts: original + thumb
    assert patch_s3.await_count == 2
    # Keys the handler put — check both the original and the thumbnail
    called_keys = [call.args[1] for call in patch_s3.await_args_list]
    original_key, thumb_key = called_keys
    assert original_key.endswith(".jpg")
    assert thumb_key == f"{original_key}.thumb.jpg"


async def test_upload_image_falls_back_when_pillow_fails(
    client, patch_session, patch_s3, monkeypatch
):
    """If Pillow raises while processing, the thumbnail is skipped (best-effort)
    but the upload still succeeds with `thumbnail_url=None`.
    """
    def _boom(_buf):
        raise RuntimeError("decode failed")

    import PIL.Image
    monkeypatch.setattr(PIL.Image, "open", _boom)

    r = await client.post(
        "/api/v1/files",
        data={"source_module": "siteeye"},
        files={"file": ("broken.png", b"not-a-png", "image/png")},
    )

    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["thumbnail_url"] is None
    # Only the original was uploaded
    assert patch_s3.await_count == 1


async def test_upload_infers_extension_from_filename(
    client, patch_session, patch_s3
):
    # Filename has .DWG — handler should lowercase and include it
    r = await client.post(
        "/api/v1/files",
        data={"source_module": "drawbridge"},
        files={"file": ("plan.DWG", b"AC1024...", "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["storage_key"].endswith(".dwg")


async def test_upload_with_project_id_forwards_it_to_insert(
    client, patch_session, patch_s3
):
    from uuid import uuid4
    project_id = uuid4()

    r = await client.post(
        "/api/v1/files",
        data={"source_module": "pulse", "project_id": str(project_id)},
        files={"file": ("note.pdf", b"%PDF-1.4 test", "application/pdf")},
    )

    assert r.status_code == 201, r.text
    _sql, params = patch_session.executes[0]
    assert params["project_id"] == str(project_id)
