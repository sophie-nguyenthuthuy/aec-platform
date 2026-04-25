"""Integration tests for POST /api/v1/codeguard/query.

The LLM/RAG pipeline is mocked via the `mock_llm` fixture so these tests
verify the HTTP + persistence wiring, not the model output.
"""

from __future__ import annotations

from uuid import UUID

import pytest

pytestmark = pytest.mark.asyncio


async def test_query_returns_envelope_with_answer_and_citations(client, fake_db, mock_llm, make_query_response):
    mock_llm.query(returns=make_query_response())

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Chiều rộng hành lang thoát nạn tối thiểu?"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["errors"] is None
    assert body["data"]["answer"].startswith("Hành lang")
    assert body["data"]["confidence"] == pytest.approx(0.82)
    assert len(body["data"]["citations"]) == 1
    assert body["data"]["citations"][0]["regulation"] == "QCVN 06:2022/BXD"
    # The route should attach the newly-created check_id.
    assert body["data"]["check_id"] is not None
    UUID(body["data"]["check_id"])


async def test_query_persists_compliance_check(client, fake_db, mock_llm, make_query_response, fake_auth):
    from models.codeguard import ComplianceCheck as ComplianceCheckModel
    from schemas.codeguard import CheckType

    mock_llm.query(returns=make_query_response())

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Requirement for emergency lighting in apartments?"},
    )
    assert res.status_code == 200

    checks = [c for c in fake_db.added if isinstance(c, ComplianceCheckModel)]
    assert len(checks) == 1
    check = checks[0]
    assert check.organization_id == fake_auth.organization_id
    assert check.created_by == fake_auth.user_id
    assert check.check_type == CheckType.manual_query.value
    assert check.input["question"].startswith("Requirement")
    assert check.findings["answer"] == "Hành lang thoát nạn phải có chiều rộng tối thiểu 1.4m."
    # regulations_referenced should be populated from citations.
    assert len(check.regulations_referenced) == 1


async def test_query_forwards_filters_to_pipeline(client, mock_llm, make_query_response):
    mock = mock_llm.query(returns=make_query_response())

    await client.post(
        "/api/v1/codeguard/query",
        json={
            "question": "Yêu cầu tiếp cận cho người khuyết tật?",
            "language": "vi",
            "jurisdiction": "Hồ Chí Minh",
            "categories": ["accessibility"],
            "top_k": 5,
        },
    )

    mock.assert_awaited_once()
    kwargs = mock.await_args.kwargs
    assert kwargs["language"] == "vi"
    assert kwargs["jurisdiction"] == "Hồ Chí Minh"
    assert kwargs["top_k"] == 5
    assert [c.value for c in kwargs["categories"]] == ["accessibility"]


async def test_query_rejects_short_question(client):
    res = await client.post("/api/v1/codeguard/query", json={"question": "hi"})
    assert res.status_code == 422


async def test_query_surfaces_pipeline_failure_as_502(client, mock_llm):
    mock = mock_llm.query(returns=None)
    mock.side_effect = RuntimeError("LLM provider timed out")

    res = await client.post(
        "/api/v1/codeguard/query",
        json={"question": "Question that will trigger a failure"},
    )
    assert res.status_code == 502
    body = res.json()
    assert body["errors"][0]["message"].startswith("Q&A pipeline failed")
