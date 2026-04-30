"""FastAPI router for CODEGUARD endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.envelope import Envelope, ok, paginated
from db.deps import get_db
from middleware.auth import AuthContext, require_auth
from models.codeguard import (
    ComplianceCheck as ComplianceCheckModel,
)
from models.codeguard import (
    PermitChecklist as PermitChecklistModel,
)
from models.codeguard import (
    Regulation as RegulationModel,
)
from models.codeguard import (
    RegulationChunk as RegulationChunkModel,
)
from schemas.codeguard import (
    ChecklistItemStatus,
    CheckStatus,
    CheckType,
    ComplianceCheck,
    MarkItemRequest,
    PermitChecklist,
    PermitChecklistRequest,
    QueryRequest,
    QueryResponse,
    RegulationCategory,
    RegulationDetail,
    RegulationSection,
    RegulationSummary,
    ScanRequest,
    ScanResponse,
)

router = APIRouter(prefix="/api/v1/codeguard", tags=["codeguard"])


# ---------- Health -------------------------------------------------------


# Dep status names. Kept as plain strings (not an enum) so consumers can
# treat the JSON response loosely without importing API types — health
# probes are typically scraped by ops tooling, not other Python code.
_DEP_OK = "ok"
_DEP_DOWN = "down"
_DEP_UNAVAILABLE = "unavailable"  # optional dep that's intentionally not configured


async def _check_postgres(db: AsyncSession) -> dict:
    """Verify Postgres is reachable AND migration 0009 is applied.

    The presence of `regulation_chunks.embedding_half` is the cheapest
    proof that the codeguard schema is at the expected revision —
    cheaper than parsing alembic state. If this column is missing,
    `_dense_search` will raise on every call, so a `down` status here
    is a real "service is broken" signal worth paging on.
    """
    import time as _time

    start = _time.monotonic()
    try:
        from sqlalchemy import text as sa_text

        result = await db.execute(
            sa_text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='regulation_chunks' "
                "AND column_name='embedding_half'"
            )
        )
        has_halfvec = result.scalar_one_or_none() is not None
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        if not has_halfvec:
            return {
                "name": "postgres",
                "status": _DEP_DOWN,
                "latency_ms": elapsed_ms,
                "message": ("regulation_chunks.embedding_half missing — migration 0009_codeguard_hnsw not applied"),
            }
        return {
            "name": "postgres",
            "status": _DEP_OK,
            "latency_ms": elapsed_ms,
            "message": "halfvec column present",
        }
    except Exception as exc:
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        return {
            "name": "postgres",
            "status": _DEP_DOWN,
            "latency_ms": elapsed_ms,
            "message": str(exc),
        }


def _check_api_key_env(name: str, env_var: str) -> dict:
    """Light env-var presence check for an LLM/embedding provider key.

    Deliberately NOT a live ping — pinging on every health probe would
    burn ~1¢ × probe_frequency × pod_count, which adds up fast in
    production and creates a positive-feedback loop where a noisy probe
    is itself a cost incident. Env-presence is sufficient for "is this
    deployment configured" — invalid-key failures surface in the LLM
    call telemetry instead.
    """
    import os as _os

    value = _os.environ.get(env_var)
    if not value:
        return {
            "name": name,
            "status": _DEP_DOWN,
            "latency_ms": 0,
            "message": f"{env_var} not set",
        }
    return {
        "name": name,
        "status": _DEP_OK,
        "latency_ms": 0,
        "message": f"{env_var} configured",
    }


async def _check_elasticsearch() -> dict:
    """Optional dep — sparse retrieval still works without it (the
    pipeline degrades to dense-only via `_hybrid_search`'s graceful
    fallback). Returns `unavailable` if the package or env var isn't
    configured, distinct from `down` (configured but unreachable)."""
    import os as _os
    import time as _time

    es_url = _os.environ.get("ELASTICSEARCH_URL")
    if not es_url:
        return {
            "name": "elasticsearch",
            "status": _DEP_UNAVAILABLE,
            "latency_ms": 0,
            "message": "ELASTICSEARCH_URL not configured (dense-only mode)",
        }
    try:
        from elasticsearch import AsyncElasticsearch  # type: ignore[import-not-found]
    except ImportError:
        return {
            "name": "elasticsearch",
            "status": _DEP_UNAVAILABLE,
            "latency_ms": 0,
            "message": "elasticsearch package not installed",
        }

    start = _time.monotonic()
    es = AsyncElasticsearch(es_url)
    try:
        await es.ping()
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        return {
            "name": "elasticsearch",
            "status": _DEP_OK,
            "latency_ms": elapsed_ms,
            "message": "ping succeeded",
        }
    except Exception as exc:
        elapsed_ms = int((_time.monotonic() - start) * 1000)
        return {
            "name": "elasticsearch",
            "status": _DEP_DOWN,
            "latency_ms": elapsed_ms,
            "message": str(exc),
        }
    finally:
        await es.close()


def _aggregate_status(deps: list[dict]) -> str:
    """Roll dep statuses into a single overall verdict.

    `ok`        — every required dep is `ok`. Optional deps may be
                  `unavailable` (intentionally off) without changing this.
    `degraded`  — required deps are `ok`, but at least one configured
                  optional dep is `down`. Service still answers, just
                  with reduced capability.
    `down`      — at least one required dep is `down`. Service should
                  not answer queries; load balancers should pull this
                  pod out of rotation.

    Required = postgres, openai_key, anthropic_key. Everything else is
    optional from the codeguard point of view.
    """
    required_names = {"postgres", "openai_key", "anthropic_key"}
    has_required_down = any(d["name"] in required_names and d["status"] == _DEP_DOWN for d in deps)
    if has_required_down:
        return "down"
    has_optional_down = any(d["name"] not in required_names and d["status"] == _DEP_DOWN for d in deps)
    return "degraded" if has_optional_down else "ok"


@router.get("/health")
async def codeguard_health(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Dependency-state probe for ops tooling.

    Checks every dependency the codeguard module needs and returns a
    structured status envelope. Designed for:
      * Kubernetes readiness probes — pull the pod out of rotation
        when overall status is `down`.
      * Ops dashboards — surface per-dep latency/message for triage
        ("Anthropic key missing" vs "Postgres unreachable" demand
        very different responses).
      * CI smoke tests — a clean health probe is the cheapest way
        to assert "deployment X has every required env var set."

    Crucially does NOT call any LLM (no token spend on probes) and
    does NOT require auth — the route is intentionally outside the
    `require_auth` dependency so external probes don't need a JWT.
    """
    import asyncio as _asyncio

    pg, openai_key, anthropic_key, es = await _asyncio.gather(
        _check_postgres(db),
        _asyncio.to_thread(_check_api_key_env, "openai_key", "OPENAI_API_KEY"),
        _asyncio.to_thread(_check_api_key_env, "anthropic_key", "ANTHROPIC_API_KEY"),
        _check_elasticsearch(),
    )
    deps = [pg, openai_key, anthropic_key, es]
    return {
        "data": {
            "status": _aggregate_status(deps),
            "deps": deps,
        },
        "meta": None,
        "errors": None,
    }


# ---------- Quota helper ----------


async def _check_quota_or_raise(db: AsyncSession, organization_id: UUID) -> None:
    """Pre-flight quota check shared by every LLM-invoking route.

    Raises a structured 429 if the org is over their monthly cap. The
    message names the binding dimension (input vs output) so debugging a
    block doesn't require cross-referencing two dashboards. Numbers are
    comma-formatted for readability in error logs.

    Putting this in a single helper rather than copying the inline check
    into six routes means a future tweak (caching, soft-warn band, etc.)
    lands in one place. Tests can monkeypatch
    `services.codeguard_quotas.check_org_quota` to control behaviour
    without having to know which routes wire the gate.
    """
    from services import codeguard_quotas as _q

    quota = await _q.check_org_quota(db, organization_id)
    if quota.over_limit:
        used_fmt = f"{quota.used:,}"
        limit_fmt = f"{quota.limit:,}" if quota.limit is not None else "?"
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Monthly {quota.limit_kind}-token quota exceeded "
            f"({used_fmt} / {limit_fmt}). Contact admin to raise the cap.",
        )


import contextlib as _contextlib  # noqa: E402  — local alias to avoid clobbering


@_contextlib.asynccontextmanager
async def _with_usage_recording(db: AsyncSession, organization_id: UUID):
    """Bind a per-request `TelemetryAccumulator`, drain it on exit.

    Yields the accumulator so handlers can inspect token counts mid-
    flight if needed. On exit, persists the accumulated totals to
    `codeguard_org_usage` via `services.codeguard_quotas.record_org_usage`
    — the increment that lets the *next* request's `check_org_quota`
    see real spend.

    Without this drain the cap-enforcement story is purely defensive:
    `check_org_quota` reads from a usage table that nothing populates,
    so `over_limit` is never True except for orgs whose admin manually
    pre-populated rows. The pre-flight check would never trip in real
    traffic. This helper closes that gap.

    Best-effort write: a transient DB error during `record_org_usage`
    is logged at WARNING and swallowed. Without the swallow a flaky
    bookkeeping write would 502 a request whose LLM work already
    succeeded; the user-visible response was already returned (or
    streamed), and refusing to commit it because the counter write
    failed is the wrong tradeoff. Worst case: under-counted spend
    by at most one request's worth.

    Token-less calls (HyDE cache hits, embedding-only paths) leave
    the accumulator at (0, 0); `record_org_usage` short-circuits on
    both-zero, so we don't pay a write for free requests.

    Why not a FastAPI dependency: streaming routes return a
    StreamingResponse whose generator runs *after* the dependency's
    `yield` resumes. The drain has to happen after the generator
    finishes, which means the route owns the wrap. A `dependencies=
    [Depends(...)]` would drain too early — before any LLM call has
    happened.
    """
    from ml.pipelines.codeguard import (
        TelemetryAccumulator,
        clear_telemetry_accumulator,
        set_telemetry_accumulator,
    )

    from services import codeguard_quotas as _q

    acc = TelemetryAccumulator()
    token = set_telemetry_accumulator(acc)
    try:
        yield acc
    finally:
        clear_telemetry_accumulator(token)
        if acc.input_tokens or acc.output_tokens:
            try:
                await _q.record_org_usage(
                    db,
                    organization_id,
                    input_tokens=acc.input_tokens,
                    output_tokens=acc.output_tokens,
                )
            except Exception:
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "codeguard_quotas.record_org_usage failed for org=%s (in=%d, out=%d) — request already served",
                    organization_id,
                    acc.input_tokens,
                    acc.output_tokens,
                )


# ---------- Q&A ----------


@router.post("/query", response_model=Envelope[QueryResponse])
async def codeguard_query(
    payload: QueryRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.codeguard import answer_regulation_query

    await _check_quota_or_raise(db, auth.organization_id)

    # Bind the accumulator BEFORE invoking the pipeline so token counts
    # captured at every `_record_llm_call` site (HyDE, generate, etc.)
    # land on `acc`. The helper's exit calls `record_org_usage` with
    # the correct kwarg names — replacing the previous broken call
    # that always passed `(0, 0)` because `result.input_tokens` doesn't
    # exist on the `QueryResponse` schema.
    async with _with_usage_recording(db, auth.organization_id):
        try:
            result = await answer_regulation_query(
                db=db,
                question=payload.question,
                language=payload.language,
                jurisdiction=payload.jurisdiction,
                categories=payload.categories,
                top_k=payload.top_k,
                as_of_date=payload.as_of_date,
            )
        except HTTPException:
            # Don't wrap our own quota 429 (or any other deliberate raise) into
            # a 502 — those are intentional, not pipeline failures.
            raise
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Q&A pipeline failed: {exc}") from exc

    check = ComplianceCheckModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        check_type=CheckType.manual_query.value,
        status=CheckStatus.completed.value,
        input=payload.model_dump(mode="json"),
        findings=result.model_dump(mode="json"),
        regulations_referenced=[c.regulation_id for c in result.citations],
        created_by=auth.user_id,
        created_at=datetime.now(UTC),
    )
    db.add(check)
    await db.flush()
    await db.refresh(check)

    result.check_id = check.id
    return ok(result)


@router.post("/query/stream")
async def codeguard_query_stream(
    payload: QueryRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE-streamed Q&A.

    Wire format (matches the standard `text/event-stream` SSE shape):

        event: token
        data: {"delta": "<incremental text>"}

        event: done
        data: {"answer": "...", "confidence": 0.88, "citations": [...],
               "related_questions": [...], "check_id": "<uuid>"}

        event: error
        data: {"message": "..."}

    The frontend should treat `done` as terminal — the `check_id` is
    only available there because it's set after the ComplianceCheck row
    is persisted, which can't happen until the LLM has emitted the full
    grounded response. `error` is also terminal; it does NOT preempt
    `done` — once an error fires, no further events follow.

    The non-streaming `/query` endpoint stays in place for clients that
    don't want SSE complexity (and for the existing router-level mock
    tests). Both code paths share `_hyde_expand`, `_hybrid_search`,
    `_rerank`, `_ground_citations`, and `_abstain_response` — anything
    you change in those flows for free into both surfaces.
    """
    from ml.pipelines.codeguard import answer_regulation_query_stream

    # Pre-flight quota check before constructing the StreamingResponse.
    # Putting it here means an over-quota org gets a clean HTTP 429
    # rather than an SSE `error` event mid-stream — the former is what
    # ops dashboards filter on, and the latter would hand the client a
    # 200-with-trailing-error-frame that's awkward to handle.
    await _check_quota_or_raise(db, auth.organization_id)

    async def sse_stream():
        # `_with_usage_recording` binds an accumulator that captures token
        # counts at every `_record_llm_call` site reached during the
        # generator's execution (HyDE expansion + token-streaming
        # generation). The drain in its finally fires when the
        # generator exits — including on the early `return` when an
        # `error` event is emitted. Without this wrap, the per-org
        # usage table never gets the streaming-route increment and the
        # cap can never trip for streaming clients.
        async with _with_usage_recording(db, auth.organization_id):
            try:
                response: QueryResponse | None = None
                async for event_name, event_payload in answer_regulation_query_stream(
                    db=db,
                    question=payload.question,
                    language=payload.language,
                    jurisdiction=payload.jurisdiction,
                    categories=payload.categories,
                    top_k=payload.top_k,
                    as_of_date=payload.as_of_date,
                ):
                    if event_name == "token":
                        # `delta` is plain text; json.dumps escapes any
                        # newlines or quotes that would otherwise break the
                        # SSE framing (which is line-delimited).
                        yield f"event: token\ndata: {json.dumps({'delta': event_payload})}\n\n"
                    elif event_name == "done":
                        response = event_payload
                    elif event_name == "error":
                        yield (f"event: error\ndata: {json.dumps({'message': str(event_payload)})}\n\n")
                        return

                if response is None:
                    # Helper exited without emitting `done` or `error` —
                    # shouldn't happen, but defend rather than leaving the
                    # client hanging waiting for a terminal event.
                    yield ('event: error\ndata: {"message": "pipeline produced no terminal event"}\n\n')
                    return

                # Persist the ComplianceCheck row before the terminal `done`
                # event so the check_id we surface is committed audit state,
                # not a hypothetical UUID. Same shape as the non-streaming
                # /query endpoint — the audit trail is identical.
                check = ComplianceCheckModel(
                    id=uuid4(),
                    organization_id=auth.organization_id,
                    project_id=payload.project_id,
                    check_type=CheckType.manual_query.value,
                    status=CheckStatus.completed.value,
                    input=payload.model_dump(mode="json"),
                    findings=response.model_dump(mode="json"),
                    regulations_referenced=[c.regulation_id for c in response.citations],
                    created_by=auth.user_id,
                    created_at=datetime.now(UTC),
                )
                db.add(check)
                await db.flush()
                await db.refresh(check)
                response.check_id = check.id

                yield f"event: done\ndata: {response.model_dump_json()}\n\n"
            except Exception as exc:  # pragma: no cover — defensive catch
                yield (f"event: error\ndata: {json.dumps({'message': f'Q&A pipeline failed: {exc}'})}\n\n")

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={
            # Prevent intermediate proxies from buffering the stream —
            # nginx in particular needs `X-Accel-Buffering: no` to flush
            # each chunk immediately. Without it the client gets the
            # whole response in one go and the streaming UX collapses.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- Auto-scan ----------


@router.post("/scan", response_model=Envelope[ScanResponse])
async def codeguard_scan(
    payload: ScanRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.codeguard import auto_scan_project

    # Pre-flight quota check — scan is the costliest LLM surface (one
    # generate call per category, up to 5), so 429ing before we start
    # spares an org from blasting through their cap on a single call
    # they wouldn't have been allowed to make anyway.
    await _check_quota_or_raise(db, auth.organization_id)

    check = ComplianceCheckModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        check_type=CheckType.auto_scan.value,
        status=CheckStatus.running.value,
        input=payload.model_dump(mode="json"),
        created_by=auth.user_id,
        created_at=datetime.now(UTC),
    )
    db.add(check)
    await db.flush()

    # Wrap the (potentially many) LLM calls — scan can fire one
    # generation per category — so the accumulator captures the full
    # spend for this request, not just one category.
    async with _with_usage_recording(db, auth.organization_id):
        try:
            findings, reg_ids = await auto_scan_project(
                db=db,
                parameters=payload.parameters,
                categories=payload.categories,
                as_of_date=payload.as_of_date,
            )
        except Exception as exc:
            check.status = CheckStatus.failed.value
            await db.flush()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Auto-scan failed: {exc}") from exc

    pass_count = sum(1 for f in findings if f.status == "PASS")
    warn_count = sum(1 for f in findings if f.status == "WARN")
    fail_count = sum(1 for f in findings if f.status == "FAIL")

    check.status = CheckStatus.completed.value
    check.findings = [f.model_dump(mode="json") for f in findings]
    check.regulations_referenced = reg_ids
    await db.flush()
    await db.refresh(check)

    response = ScanResponse(
        check_id=check.id,
        status=CheckStatus.completed,
        total=len(findings),
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        findings=findings,
    )
    return ok(response)


@router.post("/scan/stream")
async def codeguard_scan_stream(
    payload: ScanRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE-streamed compliance scan.

    Wire format:

        event: category_start
        data: {"category": "fire_safety"}

        event: category_done
        data: {"category": "fire_safety",
               "findings": [{status, severity, ..., citation}, ...]}

        event: done
        data: {"check_id": "<uuid>", "total": N,
               "pass_count": ..., "warn_count": ..., "fail_count": ...}

        event: error
        data: {"message": "..."}

    Per-category events let the frontend render findings as each
    category finishes — for the slowest endpoint in the module
    (5 sequential LLM calls), that's the difference between "stare at
    a spinner for 30s" and "watch findings populate live."

    `done` is terminal and only fires on success. `error` is also
    terminal. `reg_ids` is rolled into the persisted ComplianceCheck
    row but NOT echoed in `done` (the frontend doesn't need it).
    """
    from ml.pipelines.codeguard import auto_scan_project_stream

    # Pre-flight quota check — same shape as /query/stream. Lands as a
    # 429 before any SSE framing, not as a mid-stream error event.
    await _check_quota_or_raise(db, auth.organization_id)

    async def sse_stream():
        # Same accumulator wrap as /query/stream. Scan is the costliest
        # surface (one LLM call per category), so the per-month usage
        # increment from a streaming scan is the largest single
        # contributor to the cap calculation.
        async with _with_usage_recording(db, auth.organization_id):
            try:
                all_findings: list = []
                all_reg_ids: list = []

                async for event_name, event_payload in auto_scan_project_stream(
                    db=db,
                    parameters=payload.parameters,
                    categories=payload.categories,
                    as_of_date=payload.as_of_date,
                ):
                    if event_name == "category_start":
                        yield (f"event: category_start\ndata: {json.dumps({'category': event_payload.value})}\n\n")
                    elif event_name == "category_done":
                        cat = event_payload["category"]
                        findings = event_payload["findings"]
                        all_findings.extend(findings)
                        all_reg_ids.extend(event_payload["reg_ids"])
                        body = {
                            "category": cat.value,
                            "findings": [f.model_dump(mode="json") for f in findings],
                        }
                        yield f"event: category_done\ndata: {json.dumps(body)}\n\n"
                    elif event_name == "error":
                        yield (f"event: error\ndata: {json.dumps({'message': str(event_payload)})}\n\n")
                        return

                # All categories done — persist the ComplianceCheck row
                # before emitting the terminal `done`. Mirrors the
                # non-streaming /scan persistence shape exactly so audit
                # consumers (history page, /checks endpoint) treat both
                # paths identically.
                pass_count = sum(1 for f in all_findings if f.status == "PASS")
                warn_count = sum(1 for f in all_findings if f.status == "WARN")
                fail_count = sum(1 for f in all_findings if f.status == "FAIL")

                check = ComplianceCheckModel(
                    id=uuid4(),
                    organization_id=auth.organization_id,
                    project_id=payload.project_id,
                    check_type=CheckType.auto_scan.value,
                    status=CheckStatus.completed.value,
                    input=payload.model_dump(mode="json"),
                    findings=[f.model_dump(mode="json") for f in all_findings],
                    regulations_referenced=list({rid for rid in all_reg_ids}),
                    created_by=auth.user_id,
                    created_at=datetime.now(UTC),
                )
                db.add(check)
                await db.flush()
                await db.refresh(check)

                done_body = {
                    "check_id": str(check.id),
                    "total": len(all_findings),
                    "pass_count": pass_count,
                    "warn_count": warn_count,
                    "fail_count": fail_count,
                }
                yield f"event: done\ndata: {json.dumps(done_body)}\n\n"
            except Exception as exc:  # pragma: no cover — defensive
                yield (f"event: error\ndata: {json.dumps({'message': f'Auto-scan failed: {exc}'})}\n\n")

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Permit checklist ----------


@router.post("/permit-checklist", response_model=Envelope[PermitChecklist])
async def create_permit_checklist(
    payload: PermitChecklistRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from ml.pipelines.codeguard import generate_permit_checklist

    # Pre-flight quota check — checklist generation is a single LLM call,
    # but a 429 still beats a 502 from the pipeline failing partway.
    await _check_quota_or_raise(db, auth.organization_id)

    async with _with_usage_recording(db, auth.organization_id):
        try:
            items = await generate_permit_checklist(
                db=db,
                jurisdiction=payload.jurisdiction,
                project_type=payload.project_type,
                parameters=payload.parameters,
            )
        except Exception as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Checklist generation failed: {exc}") from exc

    record = PermitChecklistModel(
        id=uuid4(),
        organization_id=auth.organization_id,
        project_id=payload.project_id,
        jurisdiction=payload.jurisdiction,
        project_type=payload.project_type,
        items=[i.model_dump(mode="json") for i in items],
        generated_at=datetime.now(UTC),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    return ok(PermitChecklist.model_validate(record))


@router.post("/permit-checklist/stream")
async def codeguard_permit_checklist_stream(
    payload: PermitChecklistRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE-streamed permit checklist.

    Wire format:

        event: item
        data: {id, title, description, regulation_ref, required, status}

        event: done
        data: {checklist_id, total, generated_at}

        event: error
        data: {"message": "..."}

    Items arrive as the LLM's JSON output progressively populates the
    `items` array (see `generate_permit_checklist_stream` for the
    look-ahead-by-one heuristic that prevents emitting partial items).
    The terminal `done` event carries the persisted checklist's id,
    which the frontend uses to enable the per-item mark-as-done
    interaction.

    The non-streaming `/permit-checklist` endpoint stays in place for
    server-side renders and clients that don't want SSE complexity —
    same persistence shape, same audit trail.
    """
    from ml.pipelines.codeguard import generate_permit_checklist_stream

    # Pre-flight quota check — same shape as the other /stream routes:
    # land a clean 429 before any SSE framing.
    await _check_quota_or_raise(db, auth.organization_id)

    async def sse_stream():
        # Same accumulator wrap as the other streaming routes.
        async with _with_usage_recording(db, auth.organization_id):
            try:
                items: list = []
                async for event_name, event_payload in generate_permit_checklist_stream(
                    db=db,
                    jurisdiction=payload.jurisdiction,
                    project_type=payload.project_type,
                    parameters=payload.parameters,
                ):
                    if event_name == "item_done":
                        body = event_payload.model_dump(mode="json")
                        yield f"event: item\ndata: {json.dumps(body)}\n\n"
                    elif event_name == "done":
                        items = event_payload
                    elif event_name == "error":
                        yield (f"event: error\ndata: {json.dumps({'message': str(event_payload)})}\n\n")
                        return

                # Persist the PermitChecklistModel after all items are in,
                # so the `done` event can carry a stable checklist_id that
                # the frontend's mark-item flow targets.
                now = datetime.now(UTC)
                record = PermitChecklistModel(
                    id=uuid4(),
                    organization_id=auth.organization_id,
                    project_id=payload.project_id,
                    jurisdiction=payload.jurisdiction,
                    project_type=payload.project_type,
                    items=[i.model_dump(mode="json") for i in items],
                    generated_at=now,
                )
                db.add(record)
                await db.flush()
                await db.refresh(record)

                done_body = {
                    "checklist_id": str(record.id),
                    "total": len(items),
                    "generated_at": record.generated_at.isoformat(),
                }
                yield f"event: done\ndata: {json.dumps(done_body)}\n\n"
            except Exception as exc:  # pragma: no cover — defensive
                yield (f"event: error\ndata: {json.dumps({'message': f'Checklist generation failed: {exc}'})}\n\n")

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/permit-checklist/{checklist_id}/pdf")
async def export_permit_checklist_pdf(
    checklist_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Render an org-owned PermitChecklist as a downloadable PDF.

    Uses 404 (not 403) for cross-org access so we don't leak that
    a checklist with that id exists in another tenant. Filename
    embeds the checklist id so multiple exports don't collide in
    a downloads folder.
    """
    from fastapi.responses import Response

    from services.codeguard_pdf import render_permit_checklist_pdf

    checklist = await db.get(PermitChecklistModel, checklist_id)
    if checklist is None or checklist.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist not found")

    pdf_bytes = render_permit_checklist_pdf(
        checklist_id=str(checklist.id),
        project_id=str(checklist.project_id) if checklist.project_id else None,
        jurisdiction=checklist.jurisdiction,
        project_type=checklist.project_type,
        items=list(checklist.items or []),
        generated_at=checklist.generated_at,
        completed_at=checklist.completed_at,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'attachment; filename="permit-checklist-{checklist.id}.pdf"'),
        },
    )


@router.post("/checks/{check_id}/mark-item", response_model=Envelope[PermitChecklist])
async def mark_checklist_item(
    check_id: UUID,
    payload: MarkItemRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    checklist = await db.get(PermitChecklistModel, check_id)
    if checklist is None or checklist.organization_id != auth.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist not found")

    items = list(checklist.items or [])
    now_iso = datetime.now(UTC).isoformat()
    updated = False
    for item in items:
        if item.get("id") == payload.item_id:
            item["status"] = payload.status.value
            if payload.notes is not None:
                item["notes"] = payload.notes
            if payload.assignee_id is not None:
                item["assignee_id"] = str(payload.assignee_id)
            item["updated_at"] = now_iso
            updated = True
            break

    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found")

    checklist.items = items
    if all(
        i.get("status") in (ChecklistItemStatus.done.value, ChecklistItemStatus.not_applicable.value) for i in items
    ):
        checklist.completed_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(checklist)
    return ok(PermitChecklist.model_validate(checklist))


# ---------- Regulations ----------


@router.get("/regulations", response_model=Envelope[list[RegulationSummary]])
async def list_regulations(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    country_code: str | None = Query(default=None, max_length=2),
    jurisdiction: str | None = None,
    category: RegulationCategory | None = None,
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    stmt = select(RegulationModel)
    if country_code:
        stmt = stmt.where(RegulationModel.country_code == country_code.upper())
    if jurisdiction:
        stmt = stmt.where(RegulationModel.jurisdiction == jurisdiction)
    if category:
        stmt = stmt.where(RegulationModel.category == category.value)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(RegulationModel.code_name.ilike(like), RegulationModel.raw_text.ilike(like)))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(RegulationModel.code_name).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    return paginated(
        [RegulationSummary.model_validate(r) for r in rows],
        page=offset // limit + 1,
        per_page=limit,
        total=int(total),
    )


@router.get("/regulations/{regulation_id}", response_model=Envelope[RegulationDetail])
async def get_regulation(
    regulation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    reg = await db.get(RegulationModel, regulation_id)
    if reg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regulation not found")

    chunks_stmt = (
        select(RegulationChunkModel)
        .where(RegulationChunkModel.regulation_id == regulation_id)
        .order_by(RegulationChunkModel.section_ref)
    )
    chunks = (await db.execute(chunks_stmt)).scalars().all()
    sections = [RegulationSection(section_ref=c.section_ref or "", content=c.content) for c in chunks]

    detail = RegulationDetail.model_validate(
        {
            "id": reg.id,
            "country_code": reg.country_code,
            "jurisdiction": reg.jurisdiction,
            "code_name": reg.code_name,
            "category": reg.category,
            "effective_date": reg.effective_date,
            "expiry_date": reg.expiry_date,
            "source_url": reg.source_url,
            "language": reg.language,
            "content": reg.content,
            "sections": sections,
        }
    )
    return ok(detail)


# ---------- Check history ----------


@router.get("/checks/{project_id}", response_model=Envelope[list[ComplianceCheck]])
async def list_project_checks(
    project_id: UUID,
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    check_type: CheckType | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    stmt = (
        select(ComplianceCheckModel)
        .where(
            and_(
                ComplianceCheckModel.project_id == project_id,
                ComplianceCheckModel.organization_id == auth.organization_id,
            )
        )
        .order_by(ComplianceCheckModel.created_at.desc())
        .limit(limit)
    )
    if check_type:
        stmt = stmt.where(ComplianceCheckModel.check_type == check_type.value)
    rows = (await db.execute(stmt)).scalars().all()
    return ok([ComplianceCheck.model_validate(r) for r in rows])


@router.get("/quota")
async def get_codeguard_quota(
    auth: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return the caller's org's quota + current-month usage with
    per-dimension percent-of-cap.

    The frontend's `<QuotaStatusBanner>` consumes this to render an
    in-line warning at 80%+ (yellow) and 95%+ (red), letting users see
    their cap approaching instead of finding out via a 429 in the
    middle of an answer. Unlimited orgs (no quota row, or NULL on a
    dimension) get `quota.percent_of_cap.<dim> = null` and the banner
    stays hidden.

    Read-only — no LLM calls, no DB writes. Reuses the same SQL shape
    as `services.codeguard_quotas.check_org_quota` but returns both
    dimensions' state rather than just the binding one (the banner
    needs both to render the per-dimension progress bar).
    """
    from sqlalchemy import text as sa_text

    row = (
        await db.execute(
            sa_text(
                """
                SELECT
                  q.monthly_input_token_limit  AS in_lim,
                  q.monthly_output_token_limit AS out_lim,
                  COALESCE(u.input_tokens, 0)  AS in_used,
                  COALESCE(u.output_tokens, 0) AS out_used,
                  u.period_start
                FROM codeguard_org_quotas q
                LEFT JOIN codeguard_org_usage u
                  ON u.organization_id = q.organization_id
                  AND u.period_start = date_trunc('month', NOW())::date
                WHERE q.organization_id = :org
                """
            ),
            {"org": str(auth.organization_id)},
        )
    ).first()

    if row is None:
        # No quota row → unlimited. Banner consumes this and renders
        # nothing; we still surface the org_id + the "unlimited"
        # marker so client-side analytics / debugging tools can tell
        # the difference between "haven't loaded yet" and "no cap
        # configured for this org."
        return ok(
            {
                "organization_id": str(auth.organization_id),
                "unlimited": True,
                "input": None,
                "output": None,
                "period_start": None,
            }
        )

    def _dim(used: int, lim: int | None) -> dict:
        if lim is None or lim <= 0:
            # Unlimited on this dimension → percent is null. Component
            # treats null-percent as "don't render this dimension's bar."
            return {"used": used, "limit": lim, "percent": None}
        return {
            "used": used,
            "limit": lim,
            "percent": round(100.0 * used / lim, 1),
        }

    return ok(
        {
            "organization_id": str(auth.organization_id),
            "unlimited": False,
            "input": _dim(row.in_used, row.in_lim),
            "output": _dim(row.out_used, row.out_lim),
            "period_start": row.period_start.isoformat() if row.period_start else None,
        }
    )
