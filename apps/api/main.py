from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.envelope import http_exception_handler, unhandled_exception_handler
from core.observability import setup_observability

# Register every ORM model up-front so SQLAlchemy can sort FK deps at flush time.
# Today this is also achieved indirectly because `routers/projects.py` imports
# from every module's models — but we don't want that to be load-bearing. If
# someone refactors `projects.py` and drops a model import, the next handler
# that flushes a row whose FK target wasn't loaded will blow up with
# `NoReferencedTableError` (the exact bug that hit `workers/queue.py`).
from models import register_all as _register_all_models  # noqa: E402

_register_all_models()

from routers import (  # noqa: E402
    activity,
    admin,
    assistant,
    audit,
    bidradar,
    billing,
    bondline,
    cashflow,
    changeorder,
    codeguard,
    costpulse,
    dailylog,
    drawbridge,
    einvoice,
    equipment_rental,
    files,
    greenmark,
    handover,
    inbox,
    invitations,
    material_price_index,
    me,
    my_work,
    nghiemthu,
    notifications,
    onboarding,
    org,
    orgs,
    pccc,
    permitflow,
    projects,
    public_rfq,
    pulse,
    punchlist,
    safety_toolbox,
    schedulepilot,
    search,
    siteeye,
    subcontractor_portal,
    submittals,
    thanhtoan,
    warranty_tracker,
    webhooks,
    winwork,
    workforce,
)
from routers import api_keys as api_keys_router  # noqa: E402
from routers import design_context as design_context_router  # noqa: E402
from routers import exports as exports_router  # noqa: E402
from routers import imports as imports_router  # noqa: E402


# Module-level boot time — captured once when the process starts.
# Powers the /_meta/version uptime field. Doing this at import time
# (vs first request) means the first health probe reports a
# trustworthy value: any subsequent restart is visible as an
# uptime reset, which is what ops actually want to know.
from datetime import UTC, datetime  # noqa: E402

_BOOT_TIME = datetime.now(UTC)


def create_app() -> FastAPI:
    settings = get_settings()

    # Fail fast if a prod deploy ever boots with dev defaults — these would
    # otherwise let any caller mint a valid JWT against the well-known dev
    # secret. Restricted to AEC_ENV=production so local/staging keep booting.
    if settings.environment == "production" and settings.supabase_jwt_secret == "dev-secret-change-me":
        raise RuntimeError("AEC_ENV=production but SUPABASE_JWT_SECRET is the dev default — refusing to start")

    from core.version import get_version

    app = FastAPI(title="AEC Platform API", version=get_version())

    # CORS: explicit allow-list from env PLUS a regex covering every
    # `aec-platform-*.vercel.app` preview/alias domain. Vercel mints
    # alias subdomains per branch (e.g. `aec-platform-web-five`,
    # `aec-platform-web-git-main-…`, `aec-platform-havjmjkqh-…`); pinning
    # only `cors_origins` means each new alias 400s the preflight until
    # ops manually adds it. The regex covers all current + future
    # aliases on the same project. Other origins still go through
    # the explicit allow-list so non-Vercel domains can opt in.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https://aec-platform-[a-z0-9-]+\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Structured logging, request-ID middleware, slow-query detection,
    # optional Sentry init. Done before routers so middleware sees every
    # inbound request, including ones that 404 before hitting a handler.
    setup_observability(app, settings)

    app.include_router(me.router)
    app.include_router(my_work.router)
    app.include_router(inbox.router)
    app.include_router(org.router)
    app.include_router(orgs.router)
    app.include_router(invitations.router)
    app.include_router(projects.router)
    app.include_router(activity.router)
    app.include_router(notifications.router)
    app.include_router(assistant.router)
    app.include_router(audit.router)
    app.include_router(billing.router)
    app.include_router(cashflow.router)
    app.include_router(search.router)
    app.include_router(webhooks.router)
    app.include_router(onboarding.router)
    app.include_router(imports_router.router)
    app.include_router(exports_router.router)
    app.include_router(api_keys_router.router)
    app.include_router(winwork.router)
    app.include_router(pulse.router)
    app.include_router(bidradar.router)
    app.include_router(codeguard.router)
    app.include_router(costpulse.router)
    app.include_router(siteeye.router)
    app.include_router(handover.router)
    app.include_router(warranty_tracker.router)
    app.include_router(drawbridge.router)
    app.include_router(schedulepilot.router)
    app.include_router(submittals.router)
    app.include_router(dailylog.router)
    app.include_router(changeorder.router)
    app.include_router(punchlist.router)
    app.include_router(safety_toolbox.router)
    # Subcontractor portal: TWO routers, one admin (auth required),
    # one public (token in ?t= query). main mounts both.
    app.include_router(subcontractor_portal.admin_router)
    app.include_router(subcontractor_portal.public_router)
    app.include_router(permitflow.router)
    app.include_router(nghiemthu.router)
    app.include_router(thanhtoan.router)
    app.include_router(pccc.router)
    app.include_router(einvoice.router)
    app.include_router(equipment_rental.router)
    app.include_router(material_price_index.router)
    app.include_router(greenmark.router)
    app.include_router(bondline.router)
    app.include_router(workforce.router)
    app.include_router(files.router)
    app.include_router(design_context_router.router)
    # Cross-module admin / ops endpoints (gated by `admin` role).
    app.include_router(admin.router)
    # Public (no-auth) routers — token in the request *is* the auth.
    # Mounted last so any global middleware that runs `require_auth`
    # by default can be selectively bypassed by path prefix.
    app.include_router(public_rfq.router)

    @app.get("/health")
    async def health() -> dict:
        """Liveness probe — process is up. Cheap, never touches DB/Redis."""
        return {"data": {"status": "ok"}, "meta": None, "errors": None}

    @app.get("/_meta/version")
    async def meta_version() -> dict:
        """Deployed version + git SHA + boot time.

        Used by `make verify-deploy` to confirm the live API matches the
        commit you just pushed. Safe to expose unauth: nothing sensitive
        — version is committed to git + git SHA is a public attribute
        of any commit on `main`.
        """
        import os
        from datetime import UTC, datetime

        from core.version import get_git_sha, get_version

        return {
            "data": {
                "version": get_version(),
                "git_sha": get_git_sha(),
                "environment": os.environ.get("AEC_ENV", "development"),
                "boot_time_utc": _BOOT_TIME.isoformat(),
                "uptime_seconds": int(
                    (datetime.now(UTC) - _BOOT_TIME).total_seconds()
                ),
            },
            "meta": None,
            "errors": None,
        }

    @app.get("/metrics")
    async def metrics():
        """Prometheus exposition. Public endpoint by convention —
        scrapers run without auth and require network-level allowlisting
        at the LB. The arq queue-depth gauge is sampled lazily on each
        scrape so the value reflects the moment of read, not a stale
        cron snapshot."""
        from fastapi.responses import PlainTextResponse

        from core.metrics import _sample_queue_depth, render

        await _sample_queue_depth()
        return PlainTextResponse(
            render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/health/ready")
    async def health_ready():
        """Readiness probe.

        Only `db` + `redis` gate the HTTP status (503 vs 200) — those
        are what determine whether the API can serve requests at all.
        The other probes (`storage`, `migration`, `codeguard_regulations`)
        are informational: a deploy with unconfigured S3 or unseeded
        regulations is degraded-but-serving, not down. The
        load-balancer should keep routing to it; the verify-deploy
        script can still surface the gap.
        """
        from fastapi.responses import JSONResponse

        checks = await _readiness_checks()
        critical_keys = ("db", "redis")
        critical_ok = all(checks[k]["ok"] for k in critical_keys)
        # `status` flips to "degraded" if ANY check fails, even non-
        # critical ones — operator visibility.
        any_failed = any(not c["ok"] for c in checks.values())
        body = {
            "data": {
                "status": "ok" if not any_failed else "degraded",
                "checks": checks,
            },
            "meta": None,
            "errors": None,
        }
        return JSONResponse(body, status_code=200 if critical_ok else 503)

    return app


async def _readiness_checks() -> dict[str, dict]:
    """Run each dependency probe with a 1s budget. Reports per-dep
    so an operator can tell at a glance which one is blocking traffic.

    Probes run in parallel. Each returns `{ok: bool, error?: str}` plus
    optionally `count: int` / `head: str` for the seed-state probes
    (codeguard regulations, alembic migration head). None of these
    leak PII or secret material — they're safe to expose unauth so
    the verify-deploy script can run without a token.
    """
    import asyncio

    from sqlalchemy import text

    from db.session import engine

    async def _db_check() -> dict:
        try:
            async with engine.connect() as conn:
                await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=1.0)
            return {"ok": True}
        except TimeoutError:
            return {"ok": False, "error": "timeout (>1s)"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def _redis_check() -> dict:
        # 2s budget — Upstash Singapore connection setup can spike when
        # connections are cold (TLS handshake + idle-shutdown reconnect).
        # 1s was triggering false-degraded warnings; 2s catches genuine
        # outages without flapping.
        try:
            from arq.connections import RedisSettings, create_pool

            settings = get_settings()
            pool = await asyncio.wait_for(
                create_pool(RedisSettings.from_dsn(settings.redis_url)),
                timeout=2.0,
            )
            try:
                await asyncio.wait_for(pool.ping(), timeout=2.0)
                return {"ok": True}
            finally:
                closer = getattr(pool, "aclose", None) or pool.close
                await closer()
        except TimeoutError:
            return {"ok": False, "error": "timeout (>2s)"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def _storage_check() -> dict:
        """S3 / MinIO reachability — head_bucket is the cheapest probe.
        Skips when storage isn't configured (dev / API-only deploys).

        3s budget: head_bucket goes over the wire to S3 (50-200ms typical
        from Singapore Railway to AWS Singapore S3) but DNS + TLS
        handshake can add up. 3s is comfortable headroom while still
        keeping the readiness probe under 5s overall.
        """
        settings = get_settings()
        if not settings.s3_bucket:
            return {"ok": True, "configured": False}
        try:
            from core.storage import head_bucket

            await asyncio.wait_for(head_bucket(settings), timeout=3.0)
            return {"ok": True, "configured": True, "bucket": settings.s3_bucket}
        except TimeoutError:
            return {"ok": False, "configured": True, "error": "timeout (>3s)"}
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "configured": True,
                "error": f"{type(e).__name__}: {str(e)[:120]}",
            }

    async def _migration_head_check() -> dict:
        """Alembic current revision. Surfaces (a) does alembic run? and
        (b) is the head expected? Operator pins the expected head in
        the verify-deploy script."""
        try:
            from sqlalchemy import text as _text

            async with engine.connect() as conn:
                result = await asyncio.wait_for(
                    conn.execute(
                        _text("SELECT version_num FROM alembic_version LIMIT 1")
                    ),
                    timeout=1.0,
                )
                head = result.scalar_one_or_none()
            if not head:
                return {"ok": False, "error": "alembic_version table empty"}
            return {"ok": True, "head": head}
        except TimeoutError:
            return {"ok": False, "error": "timeout (>1s)"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def _codeguard_regs_check() -> dict:
        """Count of regulations seeded — answers "did the worker
        bootstrap run?" without exposing the regulation list itself.
        The numerical count alone is non-sensitive."""
        try:
            from sqlalchemy import text as _text

            async with engine.connect() as conn:
                result = await asyncio.wait_for(
                    conn.execute(_text("SELECT COUNT(*) FROM regulations")),
                    timeout=1.0,
                )
                count = result.scalar_one()
            return {
                "ok": int(count) > 0,
                "count": int(count),
                "error": None if int(count) > 0 else "regulations table empty",
            }
        except TimeoutError:
            return {"ok": False, "error": "timeout (>1s)"}
        except Exception as e:  # noqa: BLE001
            # If the table doesn't exist (early in migrations), report
            # not-ok with a clear message instead of crashing the probe.
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}

    db_status, redis_status, storage_status, mig_status, regs_status = await asyncio.gather(
        _db_check(),
        _redis_check(),
        _storage_check(),
        _migration_head_check(),
        _codeguard_regs_check(),
    )
    return {
        "db": db_status,
        "redis": redis_status,
        "storage": storage_status,
        "migration": mig_status,
        "codeguard_regulations": regs_status,
    }


app = create_app()
