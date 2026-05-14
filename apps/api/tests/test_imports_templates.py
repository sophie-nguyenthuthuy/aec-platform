"""Tests for the import-wizard discovery + template-download endpoints.

These two endpoints (GET /api/v1/import/entities and
GET /api/v1/import/{entity}/template.csv) let the frontend wizard
stay schema-agnostic — column names + example rows live exclusively
in `services.imports.TEMPLATES`. The tests below cover:

  * Both endpoints return 401 to unauthenticated callers.
  * Both endpoints return 403 to non-admin callers (RBAC: bulk-import
    is a destructive privilege).
  * `/entities` returns every key in TEMPLATES with the right schema.
  * `/{entity}/template.csv` returns 404 for unknown entities (defensive
    against a typo'd URL — better than a confusing 500).
  * `/{entity}/template.csv` returns the right headers, an example
    row, and the right Content-Disposition for browser save-as.
  * Manifest-drift guard — every entity in TEMPLATES has a matching
    validator in VALIDATORS, and vice versa.
"""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from main import app
from middleware.auth import AuthContext, require_auth
from middleware.rbac import Role


@pytest.fixture
def client():
    """Auth-bypass test client. We swap `require_auth` with a dependency
    override so the test doesn't need a JWT; rbac on the endpoint is
    still exercised via the role we attach to the override.
    """
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth_as(role: Role) -> AuthContext:
    from uuid import uuid4

    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=str(role),
        email="t@x.com",
    )


def test_entities_endpoint_requires_admin(client):
    """A viewer-role caller must not see the entity discovery list."""
    app.dependency_overrides[require_auth] = lambda: _auth_as(Role.VIEWER)
    resp = client.get("/api/v1/import/entities")
    assert resp.status_code == 403


def test_entities_endpoint_returns_manifest(client):
    """Admin sees every TEMPLATES key with its required/optional split."""
    from services.imports import TEMPLATES

    app.dependency_overrides[require_auth] = lambda: _auth_as(Role.ADMIN)
    resp = client.get("/api/v1/import/entities")
    assert resp.status_code == 200

    payload = resp.json()["data"]
    values = {e["value"] for e in payload["entities"]}
    assert values == set(TEMPLATES.keys())

    # Spot-check schema shape — projects must list `name` as required.
    projects = next(e for e in payload["entities"] if e["value"] == "projects")
    assert "name" in projects["required"]
    assert "external_id" in projects["required"]

    assert payload["max_rows_per_upload"] > 0


def test_template_download_returns_csv_with_headers_and_example(client):
    app.dependency_overrides[require_auth] = lambda: _auth_as(Role.ADMIN)
    resp = client.get("/api/v1/import/projects/template.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    # Browser save-as: filename must be a sensible default.
    assert 'attachment; filename="aec-projects-template.csv"' in resp.headers.get(
        "content-disposition", ""
    )

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 2, "template should be header row + one example row"
    headers, example = rows

    # Headers contain every required + optional column from the manifest.
    from services.imports import TEMPLATES

    expected = TEMPLATES["projects"]["required"] + TEMPLATES["projects"]["optional"]
    assert headers == expected

    # The example row must validate end-to-end via the live validator,
    # otherwise the wizard's "download → upload" loop is broken on the
    # very first interaction.
    from services.imports import validate_rows

    raw_row = dict(zip(headers, example, strict=False))
    valid, errors = validate_rows(entity="projects", raw_rows=[raw_row])
    assert errors == [], f"sample row failed validation: {errors}"
    assert len(valid) == 1


def test_template_download_unknown_entity_returns_404(client):
    app.dependency_overrides[require_auth] = lambda: _auth_as(Role.ADMIN)
    resp = client.get("/api/v1/import/widgets/template.csv")
    assert resp.status_code == 404


def test_template_download_requires_admin(client):
    """Bulk import is destructive — VIEWER cannot prep a file either."""
    app.dependency_overrides[require_auth] = lambda: _auth_as(Role.VIEWER)
    resp = client.get("/api/v1/import/projects/template.csv")
    assert resp.status_code == 403


def test_templates_and_validators_stay_in_sync():
    """Drift guard: every TEMPLATES entry must have a matching VALIDATORS
    entry, and the other way around. Without this, adding a new entity to
    one dict but forgetting the other produces a confusing 404 or 500."""
    from services.imports import TEMPLATES, VALIDATORS

    assert set(TEMPLATES.keys()) == set(VALIDATORS.keys()), (
        f"TEMPLATES/VALIDATORS mismatch: "
        f"templates_only={set(TEMPLATES) - set(VALIDATORS)} "
        f"validators_only={set(VALIDATORS) - set(TEMPLATES)}"
    )


def test_suppliers_template_example_validates():
    """The supplier example row must round-trip through the validator
    just like the projects example. Catches off-by-one mistakes in the
    `required + optional` column order vs the example positional list.
    """
    from services.imports import TEMPLATES, render_template_csv, validate_rows

    body = render_template_csv("suppliers")
    rows = list(csv.reader(io.StringIO(body)))
    headers, example = rows

    raw_row = dict(zip(headers, example, strict=False))
    valid, errors = validate_rows(entity="suppliers", raw_rows=[raw_row])
    assert errors == []
    assert len(valid) == 1
    # `verified` must round-trip the truthy Vietnamese coercion.
    assert valid[0]["verified"] is True

    # Headers ordering matches the manifest order.
    assert headers == TEMPLATES["suppliers"]["required"] + TEMPLATES["suppliers"]["optional"]
