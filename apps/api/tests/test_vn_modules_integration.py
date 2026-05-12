"""Real-DB round-trip integration for the 8 VN modules.

Each test inserts a row (or two) through `TenantAwareSession` (RLS-on,
the same code path request handlers use) and reads it back. Catches:

  * Migration / model mismatch (column missing, type wrong, default off).
  * CHECK constraint typos (status values not matching enum).
  * RLS wiring (the GUC must be applied for inserts to succeed).
  * FK + unique-constraint surprises (e.g. a wrong column referenced).

Gated by `--integration` like the rest of the live-DB suite; needs
`COSTPULSE_RLS_DB_URL` *or* the default compose URL.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DB_URL = os.environ.get("COSTPULSE_RLS_DB_URL") or os.environ.get("DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not _DB_URL,
        reason="VN-modules integration needs DATABASE_URL or COSTPULSE_RLS_DB_URL at migration head.",
    ),
]


# Admin engine for bypass-RLS seeding (orgs + project rows the per-module
# inserts depend on).
def _admin_url() -> str:
    # The COSTPULSE_RLS_DB_URL convention points at the migration role;
    # fall back to DATABASE_URL_ADMIN if it's set explicitly.
    return os.environ.get("DATABASE_URL_ADMIN") or _DB_URL  # type: ignore[return-value]


@pytest.fixture
async def admin_session():
    eng = create_async_engine(_admin_url(), pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        yield s
    await eng.dispose()


@pytest.fixture
async def seeded_org(admin_session: AsyncSession) -> dict:
    """Create a throwaway org + user + project so each test has tenants
    to attach to. Cleans up at teardown via CASCADE on org delete."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    slug = f"vnit-{org_id.hex[:8]}"

    await admin_session.execute(
        text(
            """
            INSERT INTO users (id, email, full_name, preferred_language, created_at)
            VALUES (:id, :email, 'VN Integration', 'vi', NOW())
            """
        ),
        {"id": str(user_id), "email": f"{slug}@test.local"},
    )
    await admin_session.execute(
        text(
            """
            INSERT INTO organizations (id, name, slug, plan, modules, settings, country_code, created_at)
            VALUES (:id, 'VN IT', :slug, 'starter', '[]'::jsonb, '{}'::jsonb, 'VN', NOW())
            """
        ),
        {"id": str(org_id), "slug": slug},
    )
    await admin_session.execute(
        text(
            """
            INSERT INTO projects (id, organization_id, name, type, status, created_at)
            VALUES (:id, :org, 'Toà A', 'building', 'active', NOW())
            """
        ),
        {"id": str(project_id), "org": str(org_id)},
    )
    await admin_session.commit()
    yield {"org_id": org_id, "user_id": user_id, "project_id": project_id}
    # CASCADE deletes everything created under this org.
    await admin_session.execute(
        text("DELETE FROM organizations WHERE id = :id"),
        {"id": str(org_id)},
    )
    await admin_session.commit()


@pytest.fixture
async def tenant_session(seeded_org):
    """Open a TenantAwareSession scoped to the seeded org. Mirrors what
    request handlers do — RLS policies apply."""
    from db.session import TenantAwareSession

    async with TenantAwareSession(seeded_org["org_id"]) as session:
        yield session


# ---------- Module 1: PermitFlow ----------


async def test_permitflow_dossier_roundtrip(seeded_org, tenant_session):
    dossier_id = uuid.uuid4()
    await tenant_session.execute(
        text(
            """
            INSERT INTO permit_dossiers
              (id, organization_id, project_id, name, classification,
               investment_type, status, location)
            VALUES (:id, :org, :pid, 'Test', 'cap_ii', 'domestic',
                    'planning', '{}'::jsonb)
            """
        ),
        {
            "id": str(dossier_id),
            "org": str(seeded_org["org_id"]),
            "pid": str(seeded_org["project_id"]),
        },
    )
    row = (
        await tenant_session.execute(
            text("SELECT classification, status FROM permit_dossiers WHERE id = :id"),
            {"id": str(dossier_id)},
        )
    ).one()
    assert row[0] == "cap_ii"
    assert row[1] == "planning"


# ---------- Module 2: NghieThu ----------


async def test_nghiemthu_record_roundtrip(seeded_org, tenant_session):
    record_id = uuid.uuid4()
    await tenant_session.execute(
        text(
            """
            INSERT INTO acceptance_records
              (id, organization_id, project_id, reference_no, acceptance_level,
               title, status, acceptance_date, work_item_codes, quantities, basis)
            VALUES (:id, :org, :pid, 'BBNT-IT-001', 'cong_viec', 'Test',
                    'draft', CURRENT_DATE, ARRAY[]::text[], '[]'::jsonb, '{}'::jsonb)
            """
        ),
        {
            "id": str(record_id),
            "org": str(seeded_org["org_id"]),
            "pid": str(seeded_org["project_id"]),
        },
    )
    status = (
        await tenant_session.execute(
            text("SELECT status FROM acceptance_records WHERE id = :id"),
            {"id": str(record_id)},
        )
    ).scalar_one()
    assert status == "draft"


# ---------- Module 3: ThanhToan ----------


async def test_thanhtoan_claim_check_constraint_blocks_inverted_period(seeded_org, tenant_session):
    """The CHECK constraint on (period_end >= period_start) should reject."""
    with pytest.raises(Exception) as exc:
        await tenant_session.execute(
            text(
                """
                INSERT INTO payment_claims
                  (id, organization_id, project_id, claim_no, sequence,
                   period_start, period_end, status)
                VALUES (:id, :org, :pid, 'PT-IT-001', 1,
                        DATE '2026-04-30', DATE '2026-04-01', 'draft')
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(seeded_org["org_id"]),
                "pid": str(seeded_org["project_id"]),
            },
        )
    assert "ck_payment_claims_period" in str(exc.value) or "check" in str(exc.value).lower()


async def test_thanhtoan_claim_roundtrip(seeded_org, tenant_session):
    claim_id = uuid.uuid4()
    await tenant_session.execute(
        text(
            """
            INSERT INTO payment_claims
              (id, organization_id, project_id, claim_no, sequence,
               period_start, period_end, status, vat_pct, retention_pct, tndn_pct)
            VALUES (:id, :org, :pid, 'PT-IT-002', 1,
                    DATE '2026-04-01', DATE '2026-04-30', 'draft',
                    0.0800, 0.0500, 0.0100)
            """
        ),
        {
            "id": str(claim_id),
            "org": str(seeded_org["org_id"]),
            "pid": str(seeded_org["project_id"]),
        },
    )
    row = (
        await tenant_session.execute(
            text("SELECT vat_pct, retention_pct, tndn_pct FROM payment_claims WHERE id = :id"),
            {"id": str(claim_id)},
        )
    ).one()
    assert Decimal(row[0]) == Decimal("0.0800")
    assert Decimal(row[1]) == Decimal("0.0500")
    assert Decimal(row[2]) == Decimal("0.0100")


# ---------- Module 4: PCCC ----------


async def test_pccc_cert_hazard_check(seeded_org, tenant_session):
    """A bogus hazard category should fail the CHECK constraint."""
    with pytest.raises(Exception) as exc:
        await tenant_session.execute(
            text(
                """
                INSERT INTO fire_certs
                  (id, organization_id, project_id, cert_type, reference_no,
                   hazard_category, building_class, pc07_unit, status, legal_basis)
                VALUES (:id, :org, :pid, 'acceptance', 'PCCC-IT-001',
                        'Z', 'CO1', 'PC07-IT', 'planning', ARRAY[]::text[])
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(seeded_org["org_id"]),
                "pid": str(seeded_org["project_id"]),
            },
        )
    assert "ck_fire_certs_hazard" in str(exc.value) or "check" in str(exc.value).lower()


# ---------- Module 5: InvoiceVN ----------


async def test_einvoice_vat_rate_check(seeded_org, tenant_session):
    """13% VAT (not in the allow-list) should hit the CHECK constraint."""
    invoice_id = uuid.uuid4()
    await tenant_session.execute(
        text(
            """
            INSERT INTO einvoices
              (id, organization_id, direction, invoice_no, template_no, serial_no,
               status, issuer_mst, issuer_name, buyer_name, issue_date)
            VALUES (:id, :org, 'issued', '0000123', '1/001', 'C25TAA',
                    'draft', '0312345678', 'Test', 'Buyer', DATE '2026-05-01')
            """
        ),
        {"id": str(invoice_id), "org": str(seeded_org["org_id"])},
    )
    with pytest.raises(Exception) as exc:
        await tenant_session.execute(
            text(
                """
                INSERT INTO einvoice_lines
                  (id, organization_id, invoice_id, sort_order, description,
                   unit, qty, unit_price, line_total, vat_rate, vat_amount)
                VALUES (:id, :org, :inv, 0, 'Bad rate',
                        'cái', 1, 1000, 1000, 0.13, 130)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(seeded_org["org_id"]),
                "inv": str(invoice_id),
            },
        )
    assert "vat_rate" in str(exc.value).lower() or "check" in str(exc.value).lower()


# ---------- Module 6: LotusEdge ----------


async def test_greenmark_cert_roundtrip(seeded_org, tenant_session):
    cert_id = uuid.uuid4()
    await tenant_session.execute(
        text(
            """
            INSERT INTO green_certifications
              (id, organization_id, project_id, system, target_level,
               status, achieved_points, max_points)
            VALUES (:id, :org, :pid, 'lotus_nr', 'gold',
                    'planning', 0, 0)
            """
        ),
        {
            "id": str(cert_id),
            "org": str(seeded_org["org_id"]),
            "pid": str(seeded_org["project_id"]),
        },
    )
    sys = (
        await tenant_session.execute(
            text("SELECT system FROM green_certifications WHERE id = :id"),
            {"id": str(cert_id)},
        )
    ).scalar_one()
    assert sys == "lotus_nr"


# ---------- Module 7: BondLine ----------


async def test_bondline_expiry_after_issue_constraint(seeded_org, tenant_session):
    """Bond expiry must be strictly after issue_date per CHECK constraint."""
    with pytest.raises(Exception) as exc:
        await tenant_session.execute(
            text(
                """
                INSERT INTO bonds
                  (id, organization_id, project_id, bond_type, bond_no,
                   issuing_bank, beneficiary_name, face_amount_vnd,
                   currency, issue_date, expiry_date, status)
                VALUES (:id, :org, :pid, 'performance', 'IT-001',
                        'VCB', 'Owner X', 1000000,
                        'VND', DATE '2026-05-01', DATE '2026-05-01', 'active')
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(seeded_org["org_id"]),
                "pid": str(seeded_org["project_id"]),
            },
        )
    assert (
        "ck_bonds_expiry_after_issue" in str(exc.value)
        or "check" in str(exc.value).lower()
    )


# ---------- Module 8: WorkforceVN ----------


async def test_workforce_id_no_format_check(seeded_org, tenant_session):
    """id_no must be 9 or 12 digits per regex CHECK."""
    with pytest.raises(Exception) as exc:
        await tenant_session.execute(
            text(
                """
                INSERT INTO workers
                  (id, organization_id, full_name, id_no, trade,
                   employment_type, nationality, status)
                VALUES (:id, :org, 'Nguyễn Văn A', '12345',
                        'mason', 'direct', 'VN', 'active')
                """
            ),
            {"id": str(uuid.uuid4()), "org": str(seeded_org["org_id"])},
        )
    assert (
        "ck_workers_id_no_format" in str(exc.value)
        or "check" in str(exc.value).lower()
    )


async def test_workforce_roundtrip_full_chain(seeded_org, tenant_session):
    """Insert worker → training → insurance → assignment in one tenant session.

    Exercises the FK chain that the project-manifest query joins through.
    """
    worker_id = uuid.uuid4()
    await tenant_session.execute(
        text(
            """
            INSERT INTO workers
              (id, organization_id, full_name, id_no, trade,
               employment_type, nationality, status)
            VALUES (:id, :org, 'Nguyễn Văn B', '079090123456',
                    'mason', 'direct', 'VN', 'active')
            """
        ),
        {"id": str(worker_id), "org": str(seeded_org["org_id"])},
    )
    await tenant_session.execute(
        text(
            """
            INSERT INTO worker_safety_trainings
              (id, organization_id, worker_id, "group", training_org,
               training_date, valid_until, status)
            VALUES (:id, :org, :wid, '3', 'Trung tâm ATLĐ',
                    DATE '2026-05-01', DATE '2029-04-30', 'valid')
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "org": str(seeded_org["org_id"]),
            "wid": str(worker_id),
        },
    )
    await tenant_session.execute(
        text(
            """
            INSERT INTO worker_insurance_enrollments
              (id, organization_id, worker_id, basic_salary_vnd,
               bhxh_enrolled, bhyt_enrolled, bhtn_enrolled, status)
            VALUES (:id, :org, :wid, 10000000, true, true, true, 'enrolled')
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "org": str(seeded_org["org_id"]),
            "wid": str(worker_id),
        },
    )
    await tenant_session.execute(
        text(
            """
            INSERT INTO project_worker_assignments
              (id, organization_id, worker_id, project_id, start_date, status)
            VALUES (:id, :org, :wid, :pid, DATE '2026-05-01', 'active')
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "org": str(seeded_org["org_id"]),
            "wid": str(worker_id),
            "pid": str(seeded_org["project_id"]),
        },
    )

    # Manifest-style query that joins through every table.
    row = (
        await tenant_session.execute(
            text(
                """
                SELECT
                  w.full_name,
                  EXISTS(SELECT 1 FROM worker_safety_trainings t
                         WHERE t.worker_id = w.id AND t.status = 'valid') AS atld,
                  EXISTS(SELECT 1 FROM worker_insurance_enrollments i
                         WHERE i.worker_id = w.id AND i.status = 'enrolled') AS bhxh,
                  (SELECT COUNT(*) FROM project_worker_assignments a
                     WHERE a.worker_id = w.id AND a.status = 'active') AS active_pj
                FROM workers w WHERE w.id = :id
                """
            ),
            {"id": str(worker_id)},
        )
    ).one()
    assert row[0] == "Nguyễn Văn B"
    assert row[1] is True  # ATLD valid
    assert row[2] is True  # BHXH enrolled
    assert int(row[3]) == 1


# ---------- Cross-tenant RLS smoke ----------


async def test_rls_blocks_cross_tenant_read(seeded_org):
    """Org A inserts a permit dossier; Org B's session can't see it."""
    from db.session import TenantAwareSession

    org_a = seeded_org["org_id"]
    project_a = seeded_org["project_id"]

    # Seed a second org via admin to compare against.
    admin_url = _admin_url()
    eng = create_async_engine(admin_url, pool_pre_ping=True)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    org_b = uuid.uuid4()
    async with Session() as s:
        await s.execute(
            text(
                """
                INSERT INTO organizations (id, name, slug, plan, modules, settings, country_code, created_at)
                VALUES (:id, 'VN IT B', :slug, 'starter', '[]'::jsonb, '{}'::jsonb, 'VN', NOW())
                """
            ),
            {"id": str(org_b), "slug": f"vnit-b-{org_b.hex[:8]}"},
        )
        await s.commit()

    try:
        # Insert as Org A.
        dossier_id = uuid.uuid4()
        async with TenantAwareSession(org_a) as sa:
            await sa.execute(
                text(
                    """
                    INSERT INTO permit_dossiers
                      (id, organization_id, project_id, name, classification,
                       investment_type, status, location)
                    VALUES (:id, :org, :pid, 'A-only', 'cap_iii', 'domestic',
                            'planning', '{}'::jsonb)
                    """
                ),
                {"id": str(dossier_id), "org": str(org_a), "pid": str(project_a)},
            )
            await sa.commit()

        # Read as Org B — RLS should hide it.
        async with TenantAwareSession(org_b) as sb:
            seen = (
                await sb.execute(
                    text("SELECT COUNT(*) FROM permit_dossiers WHERE id = :id"),
                    {"id": str(dossier_id)},
                )
            ).scalar_one()
        assert seen == 0, "RLS leak: Org B saw Org A's permit dossier"
    finally:
        async with Session() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": str(org_b)})
            await s.commit()
        await eng.dispose()
