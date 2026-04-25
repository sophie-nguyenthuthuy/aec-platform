"""Integration tests for POST /api/v1/codeguard/scan."""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


def _make_finding(**overrides):
    from schemas.codeguard import Finding, FindingStatus, RegulationCategory, Severity

    base = dict(
        status=FindingStatus.fail,
        severity=Severity.critical,
        category=RegulationCategory.fire_safety,
        title="Missing secondary evacuation exit",
        description="Floors above 28m must have two independent exits.",
        resolution="Add a protected secondary staircase.",
        citation=None,
    )
    base.update(overrides)
    return Finding(**base)


async def test_scan_returns_aggregated_counts(client, mock_llm):
    from schemas.codeguard import FindingStatus

    findings = [
        _make_finding(status=FindingStatus.fail),
        _make_finding(status=FindingStatus.warn, title="Narrow corridor"),
        _make_finding(status=FindingStatus.pass_, title="Compliant ramp slope"),
    ]
    reg_ids = [uuid4(), uuid4()]
    mock_llm.scan(findings=findings, regs=reg_ids)

    res = await client.post(
        "/api/v1/codeguard/scan",
        json={
            "project_id": str(uuid4()),
            "parameters": {
                "project_type": "mixed_use",
                "floors_above": 32,
                "max_height_m": 105.0,
            },
        },
    )

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["total"] == 3
    assert data["fail_count"] == 1
    assert data["warn_count"] == 1
    assert data["pass_count"] == 1
    assert data["status"] == "completed"
    assert len(data["findings"]) == 3


async def test_scan_persists_check_with_findings_and_refs(client, fake_db, mock_llm, fake_auth):
    from models.codeguard import ComplianceCheck as ComplianceCheckModel
    from schemas.codeguard import CheckStatus, CheckType

    reg_ids = [uuid4(), uuid4()]
    mock_llm.scan(findings=[_make_finding()], regs=reg_ids)

    res = await client.post(
        "/api/v1/codeguard/scan",
        json={
            "project_id": str(uuid4()),
            "parameters": {"project_type": "residential", "floors_above": 10},
        },
    )
    assert res.status_code == 200

    checks = [c for c in fake_db.added if isinstance(c, ComplianceCheckModel)]
    assert len(checks) == 1
    check = checks[0]
    assert check.organization_id == fake_auth.organization_id
    assert check.check_type == CheckType.auto_scan.value
    assert check.status == CheckStatus.completed.value
    assert check.regulations_referenced == reg_ids
    assert len(check.findings) == 1


async def test_scan_marks_check_failed_on_pipeline_error(client, fake_db, mock_llm):
    from models.codeguard import ComplianceCheck as ComplianceCheckModel
    from schemas.codeguard import CheckStatus

    mock = mock_llm.scan(findings=[], regs=[])
    mock.side_effect = RuntimeError("Retriever unavailable")

    res = await client.post(
        "/api/v1/codeguard/scan",
        json={
            "project_id": str(uuid4()),
            "parameters": {"project_type": "residential"},
        },
    )
    assert res.status_code == 502

    checks = [c for c in fake_db.added if isinstance(c, ComplianceCheckModel)]
    assert len(checks) == 1
    assert checks[0].status == CheckStatus.failed.value
