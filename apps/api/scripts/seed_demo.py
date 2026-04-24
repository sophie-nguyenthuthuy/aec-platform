"""Seed a demo organization, project, and SiteEye fixtures.

Run locally with:
    python -m scripts.seed_demo

Idempotent: re-running updates existing rows rather than duplicating them.
Prints credentials for the demo user at the end.
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from db.session import SessionFactory, TenantAwareSession

DEMO_ORG_SLUG = "demo-co"
DEMO_USER_EMAIL = "demo@aec-platform.vn"
DEMO_PROJECT_NAME = "Demo — Tower A"

PHASES = ["site_prep", "foundation", "structure", "envelope", "mep"]
INCIDENT_TYPES = [
    ("no_ppe", "high", "Worker without hard hat detected on ground floor"),
    ("unsafe_scaffold", "high", "Scaffold missing top rail on east face"),
    ("open_trench", "medium", "Unprotected trench near utilities staging"),
]


async def main() -> None:
    async with SessionFactory() as bootstrap:
        org_id = await _upsert_org(bootstrap)
        user_id = await _upsert_user(bootstrap)
        await _upsert_membership(bootstrap, org_id=org_id, user_id=user_id, role="owner")
        await bootstrap.commit()

    async with TenantAwareSession(org_id) as session:
        project_id = await _upsert_project(session, org_id=org_id)
        visit_ids = await _seed_visits(session, org_id=org_id, project_id=project_id, user_id=user_id)
        photo_ids = await _seed_photos(session, org_id=org_id, project_id=project_id, visit_ids=visit_ids)
        await _seed_progress(session, org_id=org_id, project_id=project_id, photo_ids=photo_ids)
        await _seed_incidents(session, org_id=org_id, project_id=project_id, photo_ids=photo_ids)

    token = _mint_dev_jwt(user_id)
    print("\n--- Demo credentials ---")
    print(f"Organization ID: {org_id}")
    print(f"User ID:         {user_id}")
    print(f"Project ID:      {project_id}")
    print(f"JWT token:       {token}")
    print("Use with:  Authorization: Bearer <token>   X-Org-ID: <org_id>")


async def _upsert_org(session: AsyncSession) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO organizations (name, slug, plan, modules, country_code)
                VALUES (:name, :slug, 'pro', CAST(:modules AS jsonb), 'VN')
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            ),
            {
                "name": "Demo Construction Co.",
                "slug": DEMO_ORG_SLUG,
                "modules": json.dumps(["siteeye", "codeguard", "costpulse"]),
            },
        )
    ).scalar_one()
    return UUID(str(row))


async def _upsert_user(session: AsyncSession) -> UUID:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO users (email, full_name, preferred_language)
                VALUES (:email, :name, 'vi')
                ON CONFLICT (email) DO UPDATE SET full_name = EXCLUDED.full_name
                RETURNING id
                """
            ),
            {"email": DEMO_USER_EMAIL, "name": "Demo User"},
        )
    ).scalar_one()
    return UUID(str(row))


async def _upsert_membership(
    session: AsyncSession, *, org_id: UUID, user_id: UUID, role: str
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO org_members (organization_id, user_id, role)
            VALUES (:org, :user, :role)
            ON CONFLICT (organization_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """
        ),
        {"org": str(org_id), "user": str(user_id), "role": role},
    )


async def _upsert_project(session: AsyncSession, *, org_id: UUID) -> UUID:
    existing = (
        await session.execute(
            text(
                "SELECT id FROM projects WHERE organization_id = :org AND name = :name"
            ),
            {"org": str(org_id), "name": DEMO_PROJECT_NAME},
        )
    ).scalar_one_or_none()
    if existing:
        return UUID(str(existing))

    start = date.today() - timedelta(days=60)
    end = date.today() + timedelta(days=240)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO projects
                  (organization_id, name, type, status, address, area_sqm,
                   floors, budget_vnd, start_date, end_date)
                VALUES
                  (:org, :name, 'commercial', 'active',
                   CAST(:addr AS jsonb), 4800, 12, 125000000000, :start, :end)
                RETURNING id
                """
            ),
            {
                "org": str(org_id),
                "name": DEMO_PROJECT_NAME,
                "addr": json.dumps({"street": "123 Nguyen Van Cu", "city": "Ho Chi Minh"}),
                "start": start,
                "end": end,
            },
        )
    ).scalar_one()
    return UUID(str(row))


async def _seed_visits(
    session: AsyncSession, *, org_id: UUID, project_id: UUID, user_id: UUID
) -> list[UUID]:
    visit_ids: list[UUID] = []
    today = date.today()
    for i in range(5):
        d = today - timedelta(days=i * 3)
        row = (
            await session.execute(
                text(
                    """
                    INSERT INTO site_visits
                      (organization_id, project_id, visit_date, weather, workers_count,
                       notes, reported_by, ai_summary)
                    VALUES
                      (:org, :project_id, :d, :weather, :workers, :notes, :user,
                       :summary)
                    RETURNING id
                    """
                ),
                {
                    "org": str(org_id),
                    "project_id": str(project_id),
                    "d": d,
                    "weather": random.choice(["Sunny 32°C", "Cloudy 28°C", "Light rain 26°C"]),
                    "workers": random.randint(40, 90),
                    "notes": f"Walk-through day {i + 1}",
                    "user": str(user_id),
                    "summary": "Structure pour progressed; MEP rough-in started on L3.",
                },
            )
        ).scalar_one()
        visit_ids.append(UUID(str(row)))
    return visit_ids


async def _seed_photos(
    session: AsyncSession, *, org_id: UUID, project_id: UUID, visit_ids: list[UUID]
) -> list[UUID]:
    photo_ids: list[UUID] = []
    for visit_id in visit_ids:
        for _ in range(6):
            phase = random.choice(PHASES)
            safety = random.choices(
                ["clear", "warning", "critical"], weights=[80, 15, 5]
            )[0]
            ai = {
                "description": "Ongoing structural work visible on this elevation.",
                "detected_elements": [phase, random.choice(["rebar", "formwork", "crane"])],
                "safety_flags": [],
                "progress_indicators": {"elements": [], "completion_indicators": []},
                "phase": phase,
                "completion_hint": round(random.uniform(0.2, 0.9), 2),
            }
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO site_photos
                          (organization_id, project_id, site_visit_id, thumbnail_url,
                           taken_at, tags, ai_analysis, safety_status)
                        VALUES
                          (:org, :project_id, :visit, :thumb, :taken_at, :tags,
                           CAST(:ai AS jsonb), :safety)
                        RETURNING id
                        """
                    ),
                    {
                        "org": str(org_id),
                        "project_id": str(project_id),
                        "visit": str(visit_id),
                        "thumb": f"https://picsum.photos/seed/{uuid4()}/480/360",
                        "taken_at": datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 200)),
                        "tags": [phase],
                        "ai": json.dumps(ai),
                        "safety": safety,
                    },
                )
            ).scalar_one()
            photo_ids.append(UUID(str(row)))
    return photo_ids


async def _seed_progress(
    session: AsyncSession, *, org_id: UUID, project_id: UUID, photo_ids: list[UUID]
) -> None:
    today = date.today()
    base = 30.0
    for i in range(8, -1, -1):
        d = today - timedelta(days=i * 3)
        overall = round(base + (8 - i) * 2.4 + random.uniform(-0.5, 0.5), 1)
        phase_progress = {
            "site_prep": 100,
            "foundation": min(100, round(overall * 2.2, 1)),
            "structure": round(overall * 1.3, 1),
            "envelope": max(0, round(overall - 20, 1)),
            "mep": max(0, round(overall - 30, 1)),
        }
        await session.execute(
            text(
                """
                INSERT INTO progress_snapshots
                  (organization_id, project_id, snapshot_date, overall_progress_pct,
                   phase_progress, photo_ids)
                VALUES
                  (:org, :project_id, :d, :overall, CAST(:phases AS jsonb), :photos)
                ON CONFLICT (project_id, snapshot_date) DO UPDATE SET
                  overall_progress_pct = EXCLUDED.overall_progress_pct,
                  phase_progress = EXCLUDED.phase_progress,
                  photo_ids = EXCLUDED.photo_ids
                """
            ),
            {
                "org": str(org_id),
                "project_id": str(project_id),
                "d": d,
                "overall": overall,
                "phases": json.dumps(phase_progress),
                "photos": [str(p) for p in photo_ids[: min(10, len(photo_ids))]],
            },
        )


async def _seed_incidents(
    session: AsyncSession, *, org_id: UUID, project_id: UUID, photo_ids: list[UUID]
) -> None:
    for i, (incident_type, severity, description) in enumerate(INCIDENT_TYPES):
        await session.execute(
            text(
                """
                INSERT INTO safety_incidents
                  (organization_id, project_id, detected_at, incident_type, severity,
                   photo_id, ai_description, status)
                VALUES
                  (:org, :project_id, :detected, :type, :severity,
                   :photo, :desc, 'open')
                """
            ),
            {
                "org": str(org_id),
                "project_id": str(project_id),
                "detected": datetime.now(timezone.utc) - timedelta(hours=6 + i * 12),
                "type": incident_type,
                "severity": severity,
                "photo": str(photo_ids[i]) if i < len(photo_ids) else None,
                "desc": description,
            },
        )


def _mint_dev_jwt(user_id: UUID) -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": str(user_id), "email": DEMO_USER_EMAIL},
        settings.supabase_jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


if __name__ == "__main__":
    asyncio.run(main())
