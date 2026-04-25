"""Seed platform-wide CostPulse reference data: material_prices and suppliers.

Run locally with:
    python -m scripts.seed_costpulse

Idempotent. Uses SessionFactory (not TenantAwareSession) because material_prices
has no organization_id (global reference) and suppliers seeded here are platform-wide
(organization_id = NULL, visible to all tenants via the suppliers RLS policy).

Prices reflect indicative April 2026 VN government-published rates for Hanoi and
Ho Chi Minh. Material codes match those emitted by apps/ml/pipelines/costpulse.py.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import SessionFactory

EFFECTIVE = date(2026, 4, 1)
PROVINCES = ("Hanoi", "Ho Chi Minh")

# (material_code, name, category, unit, base_price_vnd_hanoi, hcm_multiplier)
# Categories align with the MaterialCategory enum in schemas/costpulse.py.
MATERIALS: list[tuple[str, str, str, str, int, float]] = [
    ("CONC_C25", "Bê tông thương phẩm M250 (C25)", "concrete", "m3", 1_450_000, 1.03),
    ("CONC_C30", "Bê tông thương phẩm M300 (C30)", "concrete", "m3", 1_580_000, 1.03),
    ("CONC_C40", "Bê tông thương phẩm M400 (C40)", "concrete", "m3", 1_820_000, 1.03),
    ("REBAR_CB300", "Thép thanh CB300-V (ϕ10–ϕ14)", "steel", "kg", 17_800, 1.01),
    ("REBAR_CB500", "Thép thanh CB500-V (ϕ16–ϕ32)", "steel", "kg", 18_400, 1.01),
    ("STEEL_STRUCT", "Thép hình kết cấu (H/I-beam, SS400)", "steel", "kg", 22_500, 1.02),
    ("BRICK_RED", "Gạch đất sét nung tuy-nen 80×80×180", "masonry", "viên", 1_450, 1.05),
    ("BRICK_AAC", "Gạch bê tông khí chưng áp AAC 600×200×100", "masonry", "viên", 18_500, 1.04),
    ("CEMENT_PCB40", "Xi măng PCB40 (bao 50kg)", "cement", "bao", 95_000, 1.02),
    ("SAND_FINE", "Cát xây tô mịn (đã sàng)", "aggregate", "m3", 340_000, 1.08),
    ("GRAVEL_1x2", "Đá dăm 1×2 cm", "aggregate", "m3", 410_000, 1.06),
    ("TILE_CERAMIC", "Gạch ốp lát ceramic 600×600", "finishing", "m2", 185_000, 1.02),
    ("PAINT_EMULSION", "Sơn nội thất gốc nước (kinh tế)", "finishing", "L", 78_000, 1.00),
    ("PAINT_EXTERIOR", "Sơn ngoại thất chống thấm", "finishing", "L", 135_000, 1.00),
    ("PLASTER", "Vữa trát tường mác 75 (đã trộn sẵn)", "finishing", "m2", 82_000, 1.04),
    ("WATERPROOF_MEMBRANE", "Màng chống thấm bitum 3mm", "finishing", "m2", 165_000, 1.02),
    ("ELECTRICAL_ALLOWANCE", "Khoán hệ thống điện (dân dụng)", "mep", "m2", 480_000, 1.05),
    ("PLUMBING_ALLOWANCE", "Khoán hệ thống cấp thoát nước", "mep", "m2", 360_000, 1.05),
    ("HVAC_ALLOWANCE", "Khoán hệ thống HVAC (điều hòa + thông gió)", "mep", "m2", 720_000, 1.03),
]

# (name, categories, provinces, contact_phone, contact_email)
SUPPLIERS: list[tuple[str, list[str], list[str], str, str]] = [
    (
        "Hòa Phát Group (thép xây dựng)",
        ["steel"],
        ["Hanoi", "Ho Chi Minh", "Hai Phong", "Da Nang"],
        "028-3822-1234",
        "sales@hoaphat.example.vn",
    ),
    (
        "Vicem Bút Sơn (xi măng PCB40)",
        ["cement"],
        ["Hanoi", "Ha Nam", "Ninh Binh"],
        "024-3550-2345",
        "kinhdoanh@vicembutson.example.vn",
    ),
    (
        "Holcim Vietnam (bê tông + xi măng)",
        ["concrete", "cement"],
        ["Ho Chi Minh", "Dong Nai", "Binh Duong"],
        "028-3827-3456",
        "order@holcim.example.vn",
    ),
    (
        "Viglacera (gạch ốp lát + gạch xây)",
        ["finishing", "masonry"],
        ["Hanoi", "Ho Chi Minh", "Bac Ninh"],
        "024-3553-4567",
        "order@viglacera.example.vn",
    ),
    (
        "Prime Group (gạch ceramic)",
        ["finishing"],
        ["Vinh Phuc", "Hanoi", "Ho Chi Minh"],
        "0211-386-5678",
        "sales@primegroup.example.vn",
    ),
    (
        "KOVA Paint (sơn nội/ngoại thất)",
        ["finishing"],
        ["Ho Chi Minh", "Hanoi", "Da Nang"],
        "028-3875-6789",
        "kinhdoanh@kova.example.vn",
    ),
    (
        "Sika Vietnam (chống thấm + phụ gia)",
        ["finishing"],
        ["Ho Chi Minh", "Hanoi"],
        "028-3930-7890",
        "vietnam.info@sika.example.vn",
    ),
    (
        "Panasonic Vietnam (thiết bị điện)",
        ["mep"],
        ["Ho Chi Minh", "Hanoi", "Binh Duong"],
        "028-3910-8901",
        "b2b@panasonic.example.vn",
    ),
    (
        "Daikin Vietnam (HVAC thương mại)",
        ["mep"],
        ["Ho Chi Minh", "Hanoi"],
        "028-3821-9012",
        "projects@daikin.example.vn",
    ),
    (
        "Xuân Trường Minerals (đá + cát)",
        ["aggregate"],
        ["Ninh Binh", "Hanoi", "Hai Phong"],
        "0229-386-0123",
        "kd@xuantruong.example.vn",
    ),
]


async def main() -> None:
    async with SessionFactory() as session:
        price_count = await _seed_material_prices(session)
        supplier_count = await _seed_suppliers(session)
        await session.commit()

    print("\n--- CostPulse reference data seeded ---")
    print(f"material_prices rows upserted: {price_count}  ({len(MATERIALS)} codes × {len(PROVINCES)} provinces)")
    print(f"suppliers rows upserted:       {supplier_count}  (platform-wide, organization_id = NULL)")
    print(f"effective_date:                {EFFECTIVE.isoformat()}")


async def _seed_material_prices(session: AsyncSession) -> int:
    count = 0
    for code, name, category, unit, base_price, hcm_mul in MATERIALS:
        for province in PROVINCES:
            price = base_price if province == "Hanoi" else int(round(base_price * hcm_mul))
            await session.execute(
                text(
                    """
                    INSERT INTO material_prices
                      (material_code, name, category, unit, price_vnd,
                       province, source, effective_date)
                    VALUES
                      (:code, :name, :category, :unit, :price,
                       :province, 'government', :effective)
                    ON CONFLICT (material_code, province, effective_date) DO UPDATE SET
                      name = EXCLUDED.name,
                      category = EXCLUDED.category,
                      unit = EXCLUDED.unit,
                      price_vnd = EXCLUDED.price_vnd,
                      source = EXCLUDED.source
                    """
                ),
                {
                    "code": code,
                    "name": name,
                    "category": category,
                    "unit": unit,
                    "price": Decimal(price),
                    "province": province,
                    "effective": EFFECTIVE,
                },
            )
            count += 1
    return count


async def _seed_suppliers(session: AsyncSession) -> int:
    count = 0
    for name, categories, provinces, phone, email in SUPPLIERS:
        # No natural unique constraint on suppliers; key on (name, organization_id IS NULL).
        existing = (
            await session.execute(
                text("SELECT id FROM suppliers WHERE name = :name AND organization_id IS NULL"),
                {"name": name},
            )
        ).scalar_one_or_none()

        contact = json.dumps({"phone": phone, "email": email})

        if existing:
            await session.execute(
                text(
                    """
                    UPDATE suppliers SET
                      categories = :categories,
                      provinces = :provinces,
                      contact = CAST(:contact AS jsonb),
                      verified = true,
                      rating = 4.5
                    WHERE id = :id
                    """
                ),
                {
                    "id": str(existing),
                    "categories": categories,
                    "provinces": provinces,
                    "contact": contact,
                },
            )
        else:
            await session.execute(
                text(
                    """
                    INSERT INTO suppliers
                      (organization_id, name, categories, provinces, contact,
                       verified, rating)
                    VALUES
                      (NULL, :name, :categories, :provinces, CAST(:contact AS jsonb),
                       true, 4.5)
                    """
                ),
                {
                    "name": name,
                    "categories": categories,
                    "provinces": provinces,
                    "contact": contact,
                },
            )
        count += 1
    return count


if __name__ == "__main__":
    asyncio.run(main())
