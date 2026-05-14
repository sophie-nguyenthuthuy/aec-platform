"""Self-bootstrap CODEGUARD regulations on first worker startup.

Why a startup hook rather than a Makefile target:
  * Production deploys (Railway) can't run `make seed-codeguard-all`
    — there's no shell, no make, no fixtures path muscle memory.
  * Manually copying the GOOGLE_API_KEY around so an operator can run
    the ingest locally against the prod Supabase URL is a security
    smell — the key is already on the worker service, leave it there.
  * Idempotency: the function checks `regulations` for any existing
    rows and exits fast if the table's already populated. Subsequent
    restarts pay a single COUNT query (~5ms) and skip the ~30s embed
    cycle.

If bootstrap fails (Gemini down, DB slow, etc.) we log + swallow the
exception so the worker still boots and processes jobs. The
`/api/v1/codeguard/scan` endpoint will return empty results until the
next restart succeeds — degraded, not broken.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


# Each entry mirrors one line of `seed-codeguard-all` in the repo Makefile.
# Keep these in sync if a new QCVN/TCVN excerpt is committed under
# apps/ml/fixtures/codeguard/.
_FIXTURES: list[dict[str, Any]] = [
    {
        "source": "qcvn_06_2022_excerpt.md",
        "code_name": "QCVN 06:2022/BXD",
        "category": "fire_safety",
        "effective_date": date(2022, 10, 25),
    },
    {
        "source": "qcvn_10_2014_accessibility_excerpt.md",
        "code_name": "QCVN 10:2014/BXD",
        "category": "accessibility",
        "effective_date": date(2014, 7, 1),
    },
    {
        "source": "tcvn_5574_2018_concrete_structure_excerpt.md",
        "code_name": "TCVN 5574:2018",
        "category": "structure",
        "effective_date": date(2018, 6, 30),
    },
    {
        "source": "qcvn_01_2021_planning_zoning_excerpt.md",
        "code_name": "QCVN 01:2021/BXD",
        "category": "zoning",
        "effective_date": date(2021, 7, 5),
    },
    {
        "source": "qcvn_09_2017_building_energy_excerpt.md",
        "code_name": "QCVN 09:2017/BXD",
        "category": "energy",
        "effective_date": date(2017, 12, 1),
    },
    {
        "source": "tcvn_2737_2023_loads_excerpt.md",
        "code_name": "TCVN 2737:2023",
        "category": "structure",
        "effective_date": date(2023, 12, 31),
    },
]


def _fixture_dir() -> Path:
    """Locate `apps/ml/fixtures/codeguard/` relative to this file.

    Layout invariant inside the worker image (see worker.arq.Dockerfile):
        /app/apps/api/workers/codeguard_bootstrap.py  ← __file__
        /app/apps/ml/fixtures/codeguard/*.md
    """
    here = Path(__file__).resolve()
    # …/apps/api/workers → …/apps/api → …/apps → …/apps/ml/fixtures/codeguard
    repo_apps = here.parent.parent.parent
    return repo_apps / "ml" / "fixtures" / "codeguard"


async def _table_is_empty() -> bool:
    """Return True iff the regulations table has zero rows.

    Uses AdminSessionFactory so RLS isn't in the way — bootstrap is a
    cross-tenant operation (regulations are global, not per-org).
    """
    from db.session import AdminSessionFactory

    async with AdminSessionFactory() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM regulations"))
        count = result.scalar_one()
    return count == 0


async def bootstrap_codeguard_if_empty(ctx: dict[str, Any] | None = None) -> None:
    """Ingest the 6 QCVN/TCVN fixtures if `regulations` is empty.

    Wired into `WorkerSettings.on_startup`, so this runs once per worker
    process boot. Safe to run repeatedly — early-exits when populated.

    Set env var `CODEGUARD_BOOTSTRAP_DISABLED=1` to skip entirely (useful
    when running the worker locally with no GOOGLE_API_KEY).
    """
    if os.getenv("CODEGUARD_BOOTSTRAP_DISABLED"):
        logger.info("codeguard_bootstrap: disabled via env var, skipping")
        return

    try:
        if not await _table_is_empty():
            logger.info("codeguard_bootstrap: regulations table populated, skipping")
            return
    except Exception as exc:
        # DB might not be migrated yet on the very first deploy; let the
        # worker boot and we'll bootstrap on the next restart.
        logger.warning("codeguard_bootstrap: empty-check failed (%s) — skipping", exc)
        return

    if not os.getenv("GOOGLE_API_KEY"):
        logger.warning(
            "codeguard_bootstrap: regulations empty but GOOGLE_API_KEY not set — skipping"
        )
        return

    fixture_dir = _fixture_dir()
    if not fixture_dir.exists():
        logger.warning("codeguard_bootstrap: fixture dir not found at %s", fixture_dir)
        return

    # Lazy imports — pipelines.codeguard_ingest pulls in google-generativeai
    # and other ML deps. We only want to pay that cost when we actually
    # need to bootstrap.
    from db.session import AdminSessionFactory
    from pipelines.codeguard_ingest import ingest_regulation  # type: ignore[import-not-found]

    logger.info(
        "codeguard_bootstrap: regulations empty, ingesting %d fixtures from %s",
        len(_FIXTURES),
        fixture_dir,
    )

    for entry in _FIXTURES:
        source = fixture_dir / entry["source"]
        if not source.exists():
            logger.warning("codeguard_bootstrap: fixture missing, skipping: %s", source)
            continue

        try:
            async with AdminSessionFactory() as session:
                result = await ingest_regulation(
                    session,
                    source=source,
                    code_name=entry["code_name"],
                    country_code="VN",
                    jurisdiction="national",
                    category=entry["category"],
                    effective_date=entry["effective_date"],
                    source_url=None,
                    language="vi",
                )
            logger.info(
                "codeguard_bootstrap: ingested %s — %d sections, %d chunks",
                entry["code_name"],
                result.sections_written,
                result.chunks_written,
            )
        except Exception as exc:
            # One bad fixture shouldn't block the others; surface and continue.
            logger.exception(
                "codeguard_bootstrap: failed to ingest %s: %s", entry["code_name"], exc
            )

    logger.info("codeguard_bootstrap: complete")
