"""Seed CODEGUARD reference + audit data for the demo organization.

Run locally with:
    python -m scripts.seed_codeguard

What this populates:
  * `regulations` — 6 QCVN/TCVN entries spanning every category
    (fire_safety, accessibility, structure × 2, zoning, energy).
  * `regulation_chunks` — every section of every fixture, parsed via
    the production splitter (`pipelines.codeguard_ingest.
    split_into_sections`). Embeddings are LEFT NULL — the retrieval
    pipeline degrades to "no candidates → abstain" rather than
    poisoning Q&A with random vectors. To get real semantic recall,
    run `make seed-codeguard-all` instead (calls the ingest CLI with
    OpenAI embeddings).
  * `compliance_checks` — 8 audit rows on the demo project: a mix of
    manual_query, auto_scan, and permit_checklist with realistic
    findings JSONB shapes (FAIL/WARN/PASS, citations referencing the
    seeded regulations).
  * `permit_checklists` — 3 jurisdiction-specific checklists with
    items at varying statuses (pending / in_progress / done).
  * `codeguard_org_quotas` — demo org pinned at 5M input / 1M output
    tokens per month.
  * `codeguard_org_usage` — current month + two prior months of
    realistic usage so the /codeguard/quota page renders a trend.
  * `codeguard_quota_audit_log` — 4 events (initial set, raise,
    reset, second raise) so the audit page has a paper trail.
  * `codeguard_quota_threshold_notifications` — 80% events from the
    prior month so the dedupe table is non-empty.
  * `codeguard_user_usage_by_route` — every ROUTE_WEIGHTS key for
    the demo user so the /quota/top-users breakdown is populated.

Idempotent: every row is keyed on a stable natural key (code_name
for regulations, `(org, section_ref)` for chunks, etc.) — re-running
upserts in place rather than duplicating.

Requires:
  * DATABASE_URL pointing at a migrated DB (alembic head).
  * The demo org/user from `seed_demo.py`. If those rows are
    missing this script bootstraps them so it can run standalone.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Make the ml package importable so we can reuse the production
# splitter rather than reimplementing it here. Keeps the parsed
# chunks identical to what `make seed-codeguard` would produce.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT / "apps" / "ml") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "apps" / "ml"))

from pipelines.codeguard_ingest import (  # noqa: E402
    chunk_section,
    split_into_sections,
)

from db.session import SessionFactory  # noqa: E402

# Reuse the demo identifiers from seed_demo.py so a tenant seeded by
# either script lands on the same org/project/user — operators can
# run them in either order.
DEMO_ORG_SLUG = "demo-co"
DEMO_USER_EMAIL = "demo@aec-platform.vn"
DEMO_PROJECT_NAME = "Demo — Tower A"

FIXTURE_DIR = _REPO_ROOT / "apps" / "ml" / "fixtures" / "codeguard"


# ---------- Regulation catalogue ----------
#
# (code_name, fixture_filename, category, jurisdiction, effective_date,
#  expiry_date, source_url, language).
# code_name is the natural key — keeps the upsert path deterministic.
REGULATIONS: list[tuple[str, str, str, str, date, date | None, str | None, str]] = [
    (
        "QCVN 06:2022/BXD",
        "qcvn_06_2022_excerpt.md",
        "fire_safety",
        "national",
        date(2022, 10, 25),
        None,
        "https://chinhphu.vn/qcvn-06-2022-bxd",
        "vi",
    ),
    (
        "QCVN 10:2014/BXD",
        "qcvn_10_2014_accessibility_excerpt.md",
        "accessibility",
        "national",
        date(2014, 7, 1),
        None,
        "https://chinhphu.vn/qcvn-10-2014-bxd",
        "vi",
    ),
    (
        "TCVN 5574:2018",
        "tcvn_5574_2018_concrete_structure_excerpt.md",
        "structure",
        "national",
        date(2018, 6, 30),
        None,
        "https://tcvn.gov.vn/tcvn-5574-2018",
        "vi",
    ),
    (
        "QCVN 01:2021/BXD",
        "qcvn_01_2021_planning_zoning_excerpt.md",
        "zoning",
        "national",
        date(2021, 7, 5),
        None,
        "https://chinhphu.vn/qcvn-01-2021-bxd",
        "vi",
    ),
    (
        "QCVN 09:2017/BXD",
        "qcvn_09_2017_building_energy_excerpt.md",
        "energy",
        "national",
        date(2017, 12, 1),
        None,
        "https://chinhphu.vn/qcvn-09-2017-bxd",
        "vi",
    ),
    (
        "TCVN 2737:2023",
        "tcvn_2737_2023_loads_excerpt.md",
        "structure",
        "national",
        date(2023, 12, 31),
        None,
        "https://tcvn.gov.vn/tcvn-2737-2023",
        "vi",
    ),
]


async def main() -> None:
    async with SessionFactory() as session:
        org_id = await _ensure_org(session)
        user_id = await _ensure_user(session)
        await _ensure_membership(session, org_id=org_id, user_id=user_id)
        project_id = await _ensure_project(session, org_id=org_id)
        await session.commit()

        # Regulations + chunks are global reference data — no org_id.
        # Seed them via the bootstrap session before switching to the
        # tenant-scoped flow below.
        reg_ids = await _seed_regulations(session)
        await session.commit()

        # Tenant-scoped seeds. We stay on `session` (bootstrap session)
        # because the codeguard quota + audit tables are deliberately
        # NOT under RLS — they're managed by the route layer using the
        # superuser session. See alembic migration 0023's docstring.
        await _seed_compliance_checks(
            session, org_id=org_id, project_id=project_id, user_id=user_id, reg_ids=reg_ids
        )
        await _seed_permit_checklists(
            session, org_id=org_id, project_id=project_id, user_id=user_id
        )
        await _seed_quotas(session, org_id=org_id)
        await _seed_usage(session, org_id=org_id)
        await _seed_quota_audit_log(session, org_id=org_id)
        await _seed_quota_threshold_notifications(session, org_id=org_id)
        await _seed_user_usage_by_route(session, org_id=org_id, user_id=user_id)
        await session.commit()

    print("--- CODEGUARD seed complete ---")
    print(f"Organization: {org_id}")
    print(f"Project:      {project_id}")
    print(f"User:         {user_id}")
    print(f"Regulations:  {len(reg_ids)}")
    print(
        "Embedding column is NULL on the seeded chunks — run "
        "`make seed-codeguard-all` with OPENAI_API_KEY exported "
        "for semantic retrieval to return hits."
    )


# ---------- Demo org / user / project bootstrap ----------
#
# Mirrors seed_demo.py's helpers but trimmed to just the CodeGuard
# prerequisites. Safe to call when seed_demo.py has already run —
# every helper is an upsert on the natural key.


async def _ensure_org(session: AsyncSession) -> UUID:
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


async def _ensure_user(session: AsyncSession) -> UUID:
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


async def _ensure_membership(session: AsyncSession, *, org_id: UUID, user_id: UUID) -> None:
    await session.execute(
        text(
            """
            INSERT INTO org_members (organization_id, user_id, role)
            VALUES (:org, :user, 'owner')
            ON CONFLICT (organization_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """
        ),
        {"org": str(org_id), "user": str(user_id)},
    )


async def _ensure_project(session: AsyncSession, *, org_id: UUID) -> UUID:
    existing = (
        await session.execute(
            text(
                "SELECT id FROM projects "
                "WHERE organization_id = :org AND name = :name"
            ),
            {"org": str(org_id), "name": DEMO_PROJECT_NAME},
        )
    ).scalar_one_or_none()
    if existing is not None:
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


# ---------- Regulations + chunks ----------


async def _seed_regulations(session: AsyncSession) -> dict[str, UUID]:
    """Upsert every fixture regulation + re-parse + re-insert chunks.

    Returns a `code_name -> regulation_id` map so downstream seeds can
    cite real UUIDs in their findings/regulations_referenced arrays.
    """
    reg_ids: dict[str, UUID] = {}

    for code_name, filename, category, jurisdiction, effective, expiry, url, language in REGULATIONS:
        fixture_path = FIXTURE_DIR / filename
        if not fixture_path.exists():
            print(f"WARNING: fixture not found, skipping: {fixture_path}", file=sys.stderr)
            continue
        raw_text = fixture_path.read_text(encoding="utf-8")
        sections = split_into_sections(raw_text)

        # Build the JSONB `content` payload mirroring RegulationDetail's
        # `sections` array so /regulations/{id} can render directly off
        # the row without a separate join into regulation_chunks.
        content_payload = {
            "sections": [
                {
                    "section_ref": s.section_ref,
                    "title": s.title,
                    "content": s.content,
                }
                for s in sections
            ]
        }

        existing = (
            await session.execute(
                text("SELECT id FROM regulations WHERE code_name = :code"),
                {"code": code_name},
            )
        ).scalar_one_or_none()

        if existing is not None:
            reg_id = UUID(str(existing))
            await session.execute(
                text(
                    """
                    UPDATE regulations
                    SET country_code=:cc, jurisdiction=:j, category=:cat,
                        effective_date=:eff, expiry_date=:exp,
                        source_url=:url, raw_text=:raw, content=CAST(:content AS jsonb),
                        language=:lang
                    WHERE id=:id
                    """
                ),
                {
                    "id": str(reg_id),
                    "cc": "VN",
                    "j": jurisdiction,
                    "cat": category,
                    "eff": effective,
                    "exp": expiry,
                    "url": url,
                    "raw": raw_text,
                    "content": json.dumps(content_payload, ensure_ascii=False),
                    "lang": language,
                },
            )
            # Re-ingest = wipe old chunks, write fresh ones. Mirrors
            # the production upsert path in codeguard_ingest._upsert_regulation.
            await session.execute(
                text("DELETE FROM regulation_chunks WHERE regulation_id = :id"),
                {"id": str(reg_id)},
            )
        else:
            reg_id = uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO regulations
                      (id, country_code, jurisdiction, code_name, category,
                       effective_date, expiry_date, source_url, raw_text,
                       content, language)
                    VALUES
                      (:id, 'VN', :j, :code, :cat, :eff, :exp, :url, :raw,
                       CAST(:content AS jsonb), :lang)
                    """
                ),
                {
                    "id": str(reg_id),
                    "j": jurisdiction,
                    "code": code_name,
                    "cat": category,
                    "eff": effective,
                    "exp": expiry,
                    "url": url,
                    "raw": raw_text,
                    "content": json.dumps(content_payload, ensure_ascii=False),
                    "lang": language,
                },
            )

        # Embedding is left NULL — see module docstring. The chunk row
        # still surfaces in /regulations/{id} (which reads JSONB
        # content), the regulation count on dashboards, and the audit
        # trail for grounding. Real retrieval needs vectors.
        chunks_written = 0
        for sec in sections:
            for piece in chunk_section(sec):
                await session.execute(
                    text(
                        """
                        INSERT INTO regulation_chunks
                          (id, regulation_id, section_ref, content)
                        VALUES
                          (gen_random_uuid(), :rid, :ref, :content)
                        """
                    ),
                    {
                        "rid": str(reg_id),
                        "ref": sec.section_ref,
                        "content": piece,
                    },
                )
                chunks_written += 1

        reg_ids[code_name] = reg_id
        print(f"  · {code_name}: {len(sections)} sections, {chunks_written} chunks")

    return reg_ids


# ---------- Compliance checks ----------


async def _seed_compliance_checks(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    user_id: UUID,
    reg_ids: dict[str, UUID],
) -> None:
    """Seed 8 audit rows across check_type values.

    Idempotency key: a synthetic `input.seed_key` field. We look up
    by `(org, project, seed_key)` and skip if found — keeps re-runs
    from stacking duplicate rows on every dev rebuild.
    """
    fire_reg = reg_ids.get("QCVN 06:2022/BXD")
    access_reg = reg_ids.get("QCVN 10:2014/BXD")
    energy_reg = reg_ids.get("QCVN 09:2017/BXD")
    zoning_reg = reg_ids.get("QCVN 01:2021/BXD")
    structure_reg = reg_ids.get("TCVN 5574:2018")

    samples: list[dict] = [
        {
            "seed_key": "query-fire-stair-width",
            "check_type": "manual_query",
            "status": "completed",
            "days_ago": 14,
            "input": {
                "seed_key": "query-fire-stair-width",
                "question": "Chiều rộng thông thủy tối thiểu của thang bộ thoát nạn nhà chung cư cao tầng là bao nhiêu?",
                "language": "vi",
            },
            "findings": [
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "fire_safety",
                    "title": "Trả lời câu hỏi",
                    "description": (
                        "Theo QCVN 06:2022/BXD §3.2.2, chiều rộng thông thủy bản thang bộ "
                        "thoát nạn của nhà chung cư cao tầng không nhỏ hơn 1,05 m [1]."
                    ),
                    "citation": {
                        "regulation_id": str(fire_reg),
                        "regulation": "QCVN 06:2022/BXD",
                        "section": "3.2.2",
                        "excerpt": "Chiều rộng thông thủy của bản thang bộ thoát nạn không được nhỏ hơn 1,05 m",
                        "source_url": "https://chinhphu.vn/qcvn-06-2022-bxd",
                    },
                }
            ],
            "regulations_referenced": [fire_reg],
        },
        {
            "seed_key": "query-accessibility-ramp",
            "check_type": "manual_query",
            "status": "completed",
            "days_ago": 9,
            "input": {
                "seed_key": "query-accessibility-ramp",
                "question": "Độ dốc tối đa của đường dốc tiếp cận xe lăn là bao nhiêu?",
                "language": "vi",
            },
            "findings": [
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "accessibility",
                    "title": "Trả lời câu hỏi",
                    "description": (
                        "QCVN 10:2014/BXD §2.1.1 quy định độ dốc đường dốc xe lăn không quá 1/12 "
                        "(8,33%); cho phép 1/10 trên đoạn ≤ 3 m khi cải tạo [1]."
                    ),
                    "citation": {
                        "regulation_id": str(access_reg),
                        "regulation": "QCVN 10:2014/BXD",
                        "section": "2.1.1",
                        "excerpt": "Độ dốc của đường dốc dành cho người khuyết tật sử dụng xe lăn không được lớn hơn 1/12",
                        "source_url": "https://chinhphu.vn/qcvn-10-2014-bxd",
                    },
                }
            ],
            "regulations_referenced": [access_reg],
        },
        {
            "seed_key": "query-energy-window-shgc",
            "check_type": "manual_query",
            "status": "completed",
            "days_ago": 5,
            "input": {
                "seed_key": "query-energy-window-shgc",
                "question": "Giá trị SHGC tối đa của kính trên tường ngoài hướng đông tây là bao nhiêu?",
                "language": "vi",
            },
            "findings": [
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "energy",
                    "title": "Trả lời câu hỏi",
                    "description": (
                        "QCVN 09:2017/BXD §2.1.2 quy định SHGC tối đa 0,4 cho hướng đông và tây [1]."
                    ),
                    "citation": {
                        "regulation_id": str(energy_reg),
                        "regulation": "QCVN 09:2017/BXD",
                        "section": "2.1.2",
                        "excerpt": "hệ số hấp thụ năng lượng mặt trời SHGC không vượt quá 0,4 với hướng đông tây",
                        "source_url": "https://chinhphu.vn/qcvn-09-2017-bxd",
                    },
                }
            ],
            "regulations_referenced": [energy_reg],
        },
        {
            "seed_key": "scan-tower-a-2026-04",
            "check_type": "auto_scan",
            "status": "completed",
            "days_ago": 21,
            "input": {
                "seed_key": "scan-tower-a-2026-04",
                "parameters": {
                    "project_type": "commercial",
                    "total_area_m2": 4800,
                    "floors_above": 12,
                    "max_height_m": 47.0,
                    "occupancy": 1200,
                },
                "categories": ["fire_safety", "accessibility", "structure", "energy"],
            },
            "findings": [
                {
                    "status": "FAIL",
                    "severity": "critical",
                    "category": "fire_safety",
                    "title": "Thiếu hệ thống sprinkler tự động",
                    "description": (
                        "Công trình cao 47 m nhưng hồ sơ thiết kế chưa có hệ thống chữa cháy "
                        "tự động bằng nước cho toàn bộ diện tích sàn [1]."
                    ),
                    "resolution": (
                        "Bổ sung hệ thống sprinkler tự động ướt phủ toàn bộ diện tích sàn theo "
                        "QCVN 06:2022/BXD §4.2; lập bản vẽ MEP-FP-AUTO."
                    ),
                    "citation": {
                        "regulation_id": str(fire_reg),
                        "regulation": "QCVN 06:2022/BXD",
                        "section": "4.2",
                        "excerpt": "Nhà chung cư cao tầng có chiều cao PCCC trên 50 m phải được trang bị hệ thống chữa cháy tự động sprinkler",
                        "source_url": "https://chinhphu.vn/qcvn-06-2022-bxd",
                    },
                },
                {
                    "status": "WARN",
                    "severity": "major",
                    "category": "accessibility",
                    "title": "Cabin thang máy chưa đạt kích thước tiếp cận",
                    "description": (
                        "Cabin thang máy hành khách đo được 1,1 m x 1,35 m, nhỏ hơn yêu cầu "
                        "tối thiểu 1,1 m x 1,4 m theo QCVN 10:2014/BXD §4.2.1 [1]."
                    ),
                    "resolution": "Thay shop drawing thang máy sang model có cabin ≥ 1,1 m x 1,4 m.",
                    "citation": {
                        "regulation_id": str(access_reg),
                        "regulation": "QCVN 10:2014/BXD",
                        "section": "4.2.1",
                        "excerpt": "Kích thước cabin thang máy tiếp cận tối thiểu là 1,1 m x 1,4 m",
                        "source_url": "https://chinhphu.vn/qcvn-10-2014-bxd",
                    },
                },
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "structure",
                    "title": "Lớp bảo vệ cốt thép",
                    "description": (
                        "Lớp bảo vệ cốt thép dầm cột thiết kế 30 mm, đáp ứng yêu cầu tối "
                        "thiểu 25 mm theo TCVN 5574:2018."
                    ),
                    "citation": None,
                },
                {
                    "status": "WARN",
                    "severity": "minor",
                    "category": "energy",
                    "title": "Mật độ công suất chiếu sáng khu văn phòng",
                    "description": (
                        "Mật độ công suất chiếu sáng khu văn phòng tầng 5–8 thiết kế "
                        "12,5 W/m², vượt ngưỡng 11 W/m² của QCVN 09:2017/BXD §3.1.1 [1]."
                    ),
                    "resolution": (
                        "Đổi sang đèn LED panel hiệu suất ≥ 110 lm/W để hạ mật độ về dưới 11 W/m²."
                    ),
                    "citation": {
                        "regulation_id": str(energy_reg),
                        "regulation": "QCVN 09:2017/BXD",
                        "section": "3.1.1",
                        "excerpt": "Mật độ công suất chiếu sáng lắp đặt trong khu văn phòng không được vượt quá 11 W/m²",
                        "source_url": "https://chinhphu.vn/qcvn-09-2017-bxd",
                    },
                },
            ],
            "regulations_referenced": [fire_reg, access_reg, energy_reg],
        },
        {
            "seed_key": "scan-tower-a-2026-05",
            "check_type": "auto_scan",
            "status": "completed",
            "days_ago": 3,
            "input": {
                "seed_key": "scan-tower-a-2026-05",
                "parameters": {
                    "project_type": "commercial",
                    "total_area_m2": 4800,
                    "floors_above": 12,
                    "max_height_m": 47.0,
                    "occupancy": 1200,
                },
                "categories": ["fire_safety", "zoning", "structure"],
            },
            "findings": [
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "fire_safety",
                    "title": "Hệ thống sprinkler tự động đã được thiết kế",
                    "description": (
                        "Sau cập nhật MEP-FP-AUTO-R02, hệ thống sprinkler đã phủ 100% diện "
                        "tích sàn — đáp ứng QCVN 06:2022/BXD §4.2 [1]."
                    ),
                    "citation": {
                        "regulation_id": str(fire_reg),
                        "regulation": "QCVN 06:2022/BXD",
                        "section": "4.2",
                        "excerpt": "phải được trang bị hệ thống chữa cháy tự động sprinkler cho toàn bộ diện tích sàn",
                        "source_url": "https://chinhphu.vn/qcvn-06-2022-bxd",
                    },
                },
                {
                    "status": "WARN",
                    "severity": "major",
                    "category": "zoning",
                    "title": "Mật độ xây dựng tiệm cận giới hạn",
                    "description": (
                        "Mật độ xây dựng thuần đạt 39,2% trên lô 2,8 ha — sát ngưỡng 40% "
                        "của lô đất < 3000 m² (lô gần tới hạn) theo QCVN 01:2021/BXD §2.1.1 [1]."
                    ),
                    "resolution": "Xác nhận diện tích lô trong sổ đỏ; lập tổng mặt bằng có ghi rõ mật độ.",
                    "citation": {
                        "regulation_id": str(zoning_reg),
                        "regulation": "QCVN 01:2021/BXD",
                        "section": "2.1.1",
                        "excerpt": "Mật độ xây dựng thuần của lô đất xây dựng nhà chung cư hỗn hợp không được vượt quá 40 phần trăm",
                        "source_url": "https://chinhphu.vn/qcvn-01-2021-bxd",
                    },
                },
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "structure",
                    "title": "Tổ hợp tải trọng cơ bản hợp lệ",
                    "description": (
                        "Tổ hợp tải trọng SAP2000 (DEAD + LIVE + WIND) sử dụng hệ số tải "
                        "đúng quy định TCVN 2737:2023."
                    ),
                    "citation": None,
                },
            ],
            "regulations_referenced": [fire_reg, zoning_reg, structure_reg],
        },
        {
            "seed_key": "checklist-hcm-residential-mixed",
            "check_type": "permit_checklist",
            "status": "completed",
            "days_ago": 10,
            "input": {
                "seed_key": "checklist-hcm-residential-mixed",
                "jurisdiction": "Ho Chi Minh City",
                "project_type": "mixed_use",
            },
            "findings": None,
            "regulations_referenced": [fire_reg, zoning_reg, access_reg],
        },
        {
            "seed_key": "query-zoning-setback",
            "check_type": "manual_query",
            "status": "completed",
            "days_ago": 1,
            "input": {
                "seed_key": "query-zoning-setback",
                "question": "Khoảng lùi tối thiểu của công trình cao tầng so với chỉ giới đường đỏ là bao nhiêu?",
                "language": "vi",
            },
            "findings": [
                {
                    "status": "PASS",
                    "severity": "minor",
                    "category": "zoning",
                    "title": "Trả lời câu hỏi",
                    "description": (
                        "Theo QCVN 01:2021/BXD §3.2, công trình cao trên 28 m trên đường rộng "
                        "< 19 m phải lùi tối thiểu 6 m so với chỉ giới đường đỏ [1]."
                    ),
                    "citation": {
                        "regulation_id": str(zoning_reg),
                        "regulation": "QCVN 01:2021/BXD",
                        "section": "3.2",
                        "excerpt": "công trình có chiều cao trên 28 m phải lùi tối thiểu 6 m so với chỉ giới đường đỏ",
                        "source_url": "https://chinhphu.vn/qcvn-01-2021-bxd",
                    },
                }
            ],
            "regulations_referenced": [zoning_reg],
        },
        {
            "seed_key": "scan-failed-llm-timeout",
            "check_type": "auto_scan",
            "status": "failed",
            "days_ago": 7,
            "input": {
                "seed_key": "scan-failed-llm-timeout",
                "parameters": {
                    "project_type": "commercial",
                    "total_area_m2": 4800,
                    "floors_above": 12,
                },
                "categories": ["fire_safety", "energy"],
                "error": "Anthropic API timed out after 60s on fire_safety category.",
            },
            "findings": [],
            "regulations_referenced": [],
        },
    ]

    for sample in samples:
        # Look up the existing row via the seed_key embedded in input JSONB.
        existing = (
            await session.execute(
                text(
                    """
                    SELECT id FROM compliance_checks
                    WHERE organization_id = :org
                      AND project_id = :project_id
                      AND (input ->> 'seed_key') = :seed_key
                    """
                ),
                {
                    "org": str(org_id),
                    "project_id": str(project_id),
                    "seed_key": sample["seed_key"],
                },
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        created_at = datetime.now(UTC) - timedelta(days=sample["days_ago"])
        await session.execute(
            text(
                """
                INSERT INTO compliance_checks
                  (organization_id, project_id, check_type, status, input,
                   findings, regulations_referenced, created_by, created_at)
                VALUES
                  (:org, :project_id, :check_type, :status,
                   CAST(:input AS jsonb), CAST(:findings AS jsonb),
                   CAST(:reg_refs AS uuid[]), :user, :created_at)
                """
            ),
            {
                "org": str(org_id),
                "project_id": str(project_id),
                "check_type": sample["check_type"],
                "status": sample["status"],
                "input": json.dumps(sample["input"], ensure_ascii=False),
                "findings": (
                    json.dumps(sample["findings"], ensure_ascii=False)
                    if sample["findings"] is not None
                    else None
                ),
                "reg_refs": (
                    "{" + ",".join(str(r) for r in sample["regulations_referenced"] if r) + "}"
                    if sample["regulations_referenced"]
                    else "{}"
                ),
                "user": str(user_id),
                "created_at": created_at,
            },
        )


# ---------- Permit checklists ----------


async def _seed_permit_checklists(
    session: AsyncSession,
    *,
    org_id: UUID,
    project_id: UUID,
    user_id: UUID,
) -> None:
    """Three checklists across jurisdictions; items at varying statuses.

    Idempotency key: `(org, project, jurisdiction, project_type)`. The
    checklist table has no unique constraint on these — we do a
    SELECT-then-INSERT.
    """
    now = datetime.now(UTC)
    samples = [
        {
            "jurisdiction": "Ho Chi Minh City",
            "project_type": "mixed_use",
            "generated_days_ago": 10,
            "completed": False,
            "items": [
                {
                    "id": "loc-permit",
                    "title": "Giấy chứng nhận quyền sử dụng đất hoặc hợp đồng thuê đất",
                    "description": "Bản sao công chứng giấy chứng nhận quyền sử dụng đất hoặc hợp đồng thuê đất hợp lệ.",
                    "regulation_ref": "Luật Xây dựng 2014, Điều 95",
                    "required": True,
                    "status": "done",
                },
                {
                    "id": "loc-plan-approval",
                    "title": "Quy hoạch chi tiết tỷ lệ 1/500 được duyệt",
                    "description": "Bản đồ quy hoạch 1/500 và quyết định phê duyệt của UBND quận/huyện.",
                    "regulation_ref": "QCVN 01:2021/BXD §2.1",
                    "required": True,
                    "status": "done",
                },
                {
                    "id": "fire-safety-design-approval",
                    "title": "Văn bản thẩm duyệt thiết kế PCCC",
                    "description": "Hồ sơ thiết kế PCCC được thẩm duyệt bởi Cảnh sát PCCC TP.HCM.",
                    "regulation_ref": "QCVN 06:2022/BXD",
                    "required": True,
                    "status": "in_progress",
                    "notes": "Đã nộp ngày 12/04; chờ phản hồi từ PCC07.",
                },
                {
                    "id": "accessibility-statement",
                    "title": "Bản cam kết tiếp cận người khuyết tật",
                    "description": "Văn bản cam kết tuân thủ QCVN 10:2014/BXD trong thiết kế và thi công.",
                    "regulation_ref": "QCVN 10:2014/BXD",
                    "required": True,
                    "status": "pending",
                },
                {
                    "id": "env-impact-screening",
                    "title": "Báo cáo đánh giá tác động môi trường ĐTM",
                    "description": "Quyết định phê duyệt ĐTM hoặc kế hoạch bảo vệ môi trường tùy quy mô.",
                    "regulation_ref": "Luật BVMT 2020",
                    "required": False,
                    "status": "not_applicable",
                    "notes": "Quy mô dưới ngưỡng yêu cầu ĐTM theo Phụ lục II Nghị định 08/2022.",
                },
                {
                    "id": "structural-design",
                    "title": "Hồ sơ thiết kế kết cấu được thẩm tra",
                    "description": "Hồ sơ thiết kế kết cấu kèm báo cáo thẩm tra từ đơn vị độc lập có chứng chỉ hạng I.",
                    "regulation_ref": "TCVN 5574:2018",
                    "required": True,
                    "status": "pending",
                },
            ],
        },
        {
            "jurisdiction": "Hanoi",
            "project_type": "office",
            "generated_days_ago": 30,
            "completed": True,
            "items": [
                {
                    "id": "hn-land-use",
                    "title": "Giấy chứng nhận quyền sử dụng đất",
                    "regulation_ref": "Luật Đất đai 2024",
                    "required": True,
                    "status": "done",
                },
                {
                    "id": "hn-zoning-conformance",
                    "title": "Văn bản chấp thuận quy hoạch 1/500",
                    "regulation_ref": "QCVN 01:2021/BXD",
                    "required": True,
                    "status": "done",
                },
                {
                    "id": "hn-fire-design",
                    "title": "Văn bản thẩm duyệt thiết kế PCCC",
                    "regulation_ref": "QCVN 06:2022/BXD",
                    "required": True,
                    "status": "done",
                },
                {
                    "id": "hn-energy-statement",
                    "title": "Báo cáo tuân thủ QCVN 09:2017/BXD",
                    "description": "Áp dụng cho công trình ≥ 2500 m² sàn.",
                    "regulation_ref": "QCVN 09:2017/BXD §1.1",
                    "required": True,
                    "status": "done",
                },
            ],
        },
        {
            "jurisdiction": "Da Nang",
            "project_type": "retail",
            "generated_days_ago": 2,
            "completed": False,
            "items": [
                {
                    "id": "dn-land-cert",
                    "title": "Giấy chứng nhận quyền sử dụng đất",
                    "regulation_ref": "Luật Đất đai 2024",
                    "required": True,
                    "status": "pending",
                },
                {
                    "id": "dn-coastal-setback",
                    "title": "Hồ sơ kiểm tra khoảng lùi ven biển",
                    "description": "Giấy phép môi trường ven biển — yêu cầu cho khu thương mại trong 50 m từ bờ biển.",
                    "regulation_ref": "QCVN 01:2021/BXD §6.2",
                    "required": True,
                    "status": "pending",
                },
                {
                    "id": "dn-fire-design",
                    "title": "Văn bản thẩm duyệt thiết kế PCCC",
                    "regulation_ref": "QCVN 06:2022/BXD",
                    "required": True,
                    "status": "pending",
                },
                {
                    "id": "dn-parking-plan",
                    "title": "Phương án bố trí bãi đỗ xe",
                    "regulation_ref": "QCVN 01:2021/BXD §4.3",
                    "required": True,
                    "status": "in_progress",
                },
            ],
        },
    ]

    for sample in samples:
        existing = (
            await session.execute(
                text(
                    """
                    SELECT id FROM permit_checklists
                    WHERE organization_id = :org
                      AND project_id = :project_id
                      AND jurisdiction = :j
                      AND project_type = :pt
                    """
                ),
                {
                    "org": str(org_id),
                    "project_id": str(project_id),
                    "j": sample["jurisdiction"],
                    "pt": sample["project_type"],
                },
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue

        generated_at = datetime.now(UTC) - timedelta(days=sample["generated_days_ago"])
        # Items get an `updated_at` ts that's between generation and now
        # so the UI's "edited X days ago" badge isn't all zeros.
        items_with_ts = []
        for it in sample["items"]:
            it_copy = {**it}
            if it.get("status") != "pending":
                it_copy["updated_at"] = (generated_at + timedelta(days=1)).isoformat()
            items_with_ts.append(it_copy)

        completed_at = (
            datetime.now(UTC) - timedelta(days=max(0, sample["generated_days_ago"] - 5))
            if sample["completed"]
            else None
        )
        await session.execute(
            text(
                """
                INSERT INTO permit_checklists
                  (organization_id, project_id, jurisdiction, project_type,
                   items, generated_at, completed_at)
                VALUES
                  (:org, :project_id, :j, :pt, CAST(:items AS jsonb),
                   :generated_at, :completed_at)
                """
            ),
            {
                "org": str(org_id),
                "project_id": str(project_id),
                "j": sample["jurisdiction"],
                "pt": sample["project_type"],
                "items": json.dumps(items_with_ts, ensure_ascii=False),
                "generated_at": generated_at,
                "completed_at": completed_at,
            },
        )
        _ = now  # appease linter for unused local while keeping the var for clarity above


# ---------- Quotas ----------


async def _seed_quotas(session: AsyncSession, *, org_id: UUID) -> None:
    """Pin the demo org at 5,000,000 input / 1,000,000 output tokens/mo.

    Asymmetric on purpose — Anthropic prices output ~5× input, so most
    real-world orgs hit the output limit first. Seeding the same shape
    gives the /codeguard/quota page a realistic dashboard view.
    """
    await session.execute(
        text(
            """
            INSERT INTO codeguard_org_quotas
              (organization_id, monthly_input_token_limit,
               monthly_output_token_limit)
            VALUES (:org, 5000000, 1000000)
            ON CONFLICT (organization_id) DO UPDATE
              SET monthly_input_token_limit = EXCLUDED.monthly_input_token_limit,
                  monthly_output_token_limit = EXCLUDED.monthly_output_token_limit,
                  updated_at = NOW()
            """
        ),
        {"org": str(org_id)},
    )


# ---------- Usage (current + prior months) ----------


async def _seed_usage(session: AsyncSession, *, org_id: UUID) -> None:
    """Three months of usage so the quota trend chart isn't flat."""
    today = date.today()
    this_month = today.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    prior_month = (last_month - timedelta(days=1)).replace(day=1)

    rows = [
        # period_start, input_tokens, output_tokens
        (prior_month, 1_240_000, 240_000),  # quiet month
        (last_month, 3_180_000, 820_000),   # crossed 80% (820k/1M output)
        (this_month, 1_950_000, 410_000),   # mid-month, ~41% output
    ]
    for period_start, in_tok, out_tok in rows:
        await session.execute(
            text(
                """
                INSERT INTO codeguard_org_usage
                  (organization_id, period_start, input_tokens, output_tokens)
                VALUES (:org, :p, :in_tok, :out_tok)
                ON CONFLICT (organization_id, period_start) DO UPDATE
                  SET input_tokens = EXCLUDED.input_tokens,
                      output_tokens = EXCLUDED.output_tokens,
                      updated_at = NOW()
                """
            ),
            {
                "org": str(org_id),
                "p": period_start,
                "in_tok": in_tok,
                "out_tok": out_tok,
            },
        )


# ---------- Quota audit log ----------


async def _seed_quota_audit_log(session: AsyncSession, *, org_id: UUID) -> None:
    """Four audit events so the audit page has a paper trail.

    Idempotency key: synthetic `actor` prefix `seed:` — re-runs check
    for any row with that actor on this org and skip the whole block.
    """
    existing = (
        await session.execute(
            text(
                """
                SELECT id FROM codeguard_quota_audit_log
                WHERE organization_id = :org AND actor LIKE 'seed:%'
                LIMIT 1
                """
            ),
            {"org": str(org_id)},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    now = datetime.now(UTC)
    events = [
        {
            "action": "quota_set",
            "before": None,
            "after": {"monthly_input_token_limit": 2000000, "monthly_output_token_limit": 400000},
            "actor": "seed:ops-initial",
            "occurred_at": now - timedelta(days=92),
        },
        {
            "action": "quota_set",
            "before": {"monthly_input_token_limit": 2000000, "monthly_output_token_limit": 400000},
            "after": {"monthly_input_token_limit": 3000000, "monthly_output_token_limit": 600000},
            "actor": "seed:ops-raise-1",
            "occurred_at": now - timedelta(days=45),
        },
        {
            "action": "quota_reset",
            "before": {"input_tokens": 2_900_000, "output_tokens": 590_000},
            "after": {"input_tokens": 0, "output_tokens": 0},
            "actor": "seed:ops-billing-dispute-T1248",
            "occurred_at": now - timedelta(days=22),
        },
        {
            "action": "quota_set",
            "before": {"monthly_input_token_limit": 3000000, "monthly_output_token_limit": 600000},
            "after": {"monthly_input_token_limit": 5000000, "monthly_output_token_limit": 1000000},
            "actor": "seed:ops-raise-2",
            "occurred_at": now - timedelta(days=14),
        },
    ]
    for ev in events:
        await session.execute(
            text(
                """
                INSERT INTO codeguard_quota_audit_log
                  (organization_id, action, before, after, actor, occurred_at)
                VALUES
                  (:org, :action, CAST(:before AS jsonb), CAST(:after AS jsonb),
                   :actor, :occurred_at)
                """
            ),
            {
                "org": str(org_id),
                "action": ev["action"],
                "before": (
                    json.dumps(ev["before"]) if ev["before"] is not None else None
                ),
                "after": json.dumps(ev["after"]) if ev["after"] is not None else None,
                "actor": ev["actor"],
                "occurred_at": ev["occurred_at"],
            },
        )


# ---------- Threshold notification dedupe rows ----------


async def _seed_quota_threshold_notifications(session: AsyncSession, *, org_id: UUID) -> None:
    """Backfill the dedupe table with last month's 80% / 95% events.

    Real production rows are written by the notification path on threshold
    crossings — seeding them here keeps the operational state realistic
    (no flapping on the seeded prior-month usage row).
    """
    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    rows = [
        # (dimension, threshold)
        ("output", 80),
        # Note: NOT 95 — last_month's seeded output was 820k/1M = 82%,
        # below the critical line. Reflecting reality, not just flooding
        # rows for the sake of "more data".
    ]
    for dimension, threshold in rows:
        await session.execute(
            text(
                """
                INSERT INTO codeguard_quota_threshold_notifications
                  (organization_id, dimension, threshold, period_start, sent_at)
                VALUES (:org, :dim, :th, :p, NOW() - INTERVAL '20 days')
                ON CONFLICT
                  ON CONSTRAINT pk_codeguard_quota_threshold_notifications
                  DO NOTHING
                """
            ),
            {
                "org": str(org_id),
                "dim": dimension,
                "th": threshold,
                "p": last_month,
            },
        )


# ---------- Per-route per-user usage attribution ----------


async def _seed_user_usage_by_route(
    session: AsyncSession, *, org_id: UUID, user_id: UUID
) -> None:
    """One row per ROUTE_WEIGHTS key, for the current month.

    Numbers are chosen so the /quota/top-users breakdown ranks scan >
    query > permit-checklist — matches the dominant cost story for
    Vietnamese AEC tenants (multi-category scans dominate spend).
    """
    this_month = date.today().replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    rows = [
        # (period_start, route_key, input_tokens, output_tokens)
        (this_month, "scan", 1_400_000, 280_000),
        (this_month, "query", 480_000, 110_000),
        (this_month, "permit-checklist", 70_000, 20_000),
        (last_month, "scan", 2_200_000, 580_000),
        (last_month, "query", 820_000, 190_000),
        (last_month, "permit-checklist", 160_000, 50_000),
    ]
    for period_start, route_key, in_tok, out_tok in rows:
        await session.execute(
            text(
                """
                INSERT INTO codeguard_user_usage_by_route
                  (organization_id, user_id, period_start, route_key,
                   input_tokens, output_tokens)
                VALUES (:org, :user, :p, :rk, :in_tok, :out_tok)
                ON CONFLICT
                  ON CONSTRAINT pk_codeguard_user_usage_by_route
                  DO UPDATE SET
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    updated_at = NOW()
                """
            ),
            {
                "org": str(org_id),
                "user": str(user_id),
                "p": period_start,
                "rk": route_key,
                "in_tok": in_tok,
                "out_tok": out_tok,
            },
        )


if __name__ == "__main__":
    asyncio.run(main())
