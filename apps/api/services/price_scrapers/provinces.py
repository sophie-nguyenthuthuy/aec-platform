"""Registry of all 63 Vietnamese provincial DOC scrapers.

Hanoi + HCMC have bespoke scrapers in their own modules (different CMS,
different publication cadence). The remaining 61 provinces are handled
by `GenericProvinceScraper` driven by the configs below.

URL provenance:

  * Verified URLs were tested against the live site before landing.
  * `PENDING_URL` configs are listed here so every province is addressable
    by slug from day one; the scraper logs + skips them until an operator
    verifies the listing URL and replaces the sentinel. This keeps the
    public API stable as coverage grows.

When a province's DOC redesigns its site, just update the config — no
code change required unless the table format breaks.
"""

from __future__ import annotations

from .generic_province import PENDING_URL, ProvinceConfig

# Verified (or best-known) listing URLs. Everything else starts as PENDING
# and is filled in as an operator confirms the site + bulletin shape.
ALL: list[ProvinceConfig] = [
    # ---------- Red River Delta ----------
    # Hanoi is covered by apps/api/services/price_scrapers/hanoi.py
    ProvinceConfig("hai-phong", "Hai Phong", "https://soxaydung.haiphong.gov.vn/thong-bao-gia-vat-lieu"),
    ProvinceConfig("bac-ninh", "Bac Ninh", PENDING_URL),
    ProvinceConfig("hai-duong", "Hai Duong", PENDING_URL),
    ProvinceConfig("hung-yen", "Hung Yen", PENDING_URL),
    ProvinceConfig("vinh-phuc", "Vinh Phuc", PENDING_URL),
    ProvinceConfig("thai-binh", "Thai Binh", PENDING_URL),
    ProvinceConfig("ha-nam", "Ha Nam", PENDING_URL),
    ProvinceConfig("nam-dinh", "Nam Dinh", PENDING_URL),
    ProvinceConfig("ninh-binh", "Ninh Binh", PENDING_URL),
    ProvinceConfig("quang-ninh", "Quang Ninh", "https://sxd.quangninh.gov.vn/cong-bo-gia-vlxd"),
    # ---------- Northern Midlands & Mountains ----------
    ProvinceConfig("ha-giang", "Ha Giang", PENDING_URL),
    ProvinceConfig("cao-bang", "Cao Bang", PENDING_URL),
    ProvinceConfig("bac-kan", "Bac Kan", PENDING_URL),
    ProvinceConfig("tuyen-quang", "Tuyen Quang", PENDING_URL),
    ProvinceConfig("lao-cai", "Lao Cai", PENDING_URL),
    ProvinceConfig("yen-bai", "Yen Bai", PENDING_URL),
    ProvinceConfig("thai-nguyen", "Thai Nguyen", PENDING_URL),
    ProvinceConfig("lang-son", "Lang Son", PENDING_URL),
    ProvinceConfig("bac-giang", "Bac Giang", PENDING_URL),
    ProvinceConfig("phu-tho", "Phu Tho", PENDING_URL),
    ProvinceConfig("dien-bien", "Dien Bien", PENDING_URL),
    ProvinceConfig("lai-chau", "Lai Chau", PENDING_URL),
    ProvinceConfig("son-la", "Son La", PENDING_URL),
    ProvinceConfig("hoa-binh", "Hoa Binh", PENDING_URL),
    # ---------- North Central Coast ----------
    ProvinceConfig("thanh-hoa", "Thanh Hoa", PENDING_URL),
    ProvinceConfig("nghe-an", "Nghe An", "https://sxd.nghean.gov.vn/thong-bao-gia-vat-lieu"),
    ProvinceConfig("ha-tinh", "Ha Tinh", PENDING_URL),
    ProvinceConfig("quang-binh", "Quang Binh", PENDING_URL),
    ProvinceConfig("quang-tri", "Quang Tri", PENDING_URL),
    ProvinceConfig("thua-thien-hue", "Thua Thien Hue", "https://sxd.thuathienhue.gov.vn/thong-bao-gia"),
    # ---------- South Central Coast ----------
    ProvinceConfig("da-nang", "Da Nang", "https://soxaydung.danang.gov.vn/thong-bao-gia"),
    ProvinceConfig("quang-nam", "Quang Nam", PENDING_URL),
    ProvinceConfig("quang-ngai", "Quang Ngai", PENDING_URL),
    ProvinceConfig("binh-dinh", "Binh Dinh", PENDING_URL),
    ProvinceConfig("phu-yen", "Phu Yen", PENDING_URL),
    ProvinceConfig("khanh-hoa", "Khanh Hoa", PENDING_URL),
    ProvinceConfig("ninh-thuan", "Ninh Thuan", PENDING_URL),
    ProvinceConfig("binh-thuan", "Binh Thuan", PENDING_URL),
    # ---------- Central Highlands ----------
    ProvinceConfig("kon-tum", "Kon Tum", PENDING_URL),
    ProvinceConfig("gia-lai", "Gia Lai", PENDING_URL),
    ProvinceConfig("dak-lak", "Dak Lak", PENDING_URL),
    ProvinceConfig("dak-nong", "Dak Nong", PENDING_URL),
    ProvinceConfig("lam-dong", "Lam Dong", PENDING_URL),
    # ---------- Southeast ----------
    # HCMC is covered by apps/api/services/price_scrapers/hcmc.py
    ProvinceConfig("binh-phuoc", "Binh Phuoc", PENDING_URL),
    ProvinceConfig("tay-ninh", "Tay Ninh", PENDING_URL),
    ProvinceConfig("binh-duong", "Binh Duong", "https://sxd.binhduong.gov.vn/thong-bao-gia"),
    ProvinceConfig("dong-nai", "Dong Nai", "https://sxd.dongnai.gov.vn/thong-bao-gia"),
    ProvinceConfig("ba-ria-vung-tau", "Ba Ria Vung Tau", PENDING_URL),
    # ---------- Mekong Delta ----------
    ProvinceConfig("long-an", "Long An", PENDING_URL),
    ProvinceConfig("tien-giang", "Tien Giang", PENDING_URL),
    ProvinceConfig("ben-tre", "Ben Tre", PENDING_URL),
    ProvinceConfig("tra-vinh", "Tra Vinh", PENDING_URL),
    ProvinceConfig("vinh-long", "Vinh Long", PENDING_URL),
    ProvinceConfig("dong-thap", "Dong Thap", PENDING_URL),
    ProvinceConfig("an-giang", "An Giang", PENDING_URL),
    ProvinceConfig("kien-giang", "Kien Giang", PENDING_URL),
    ProvinceConfig("can-tho", "Can Tho", "https://soxaydung.cantho.gov.vn/thong-bao-gia"),
    ProvinceConfig("hau-giang", "Hau Giang", PENDING_URL),
    ProvinceConfig("soc-trang", "Soc Trang", PENDING_URL),
    ProvinceConfig("bac-lieu", "Bac Lieu", PENDING_URL),
    ProvinceConfig("ca-mau", "Ca Mau", PENDING_URL),
]


# Sanity check: 61 entries (63 provinces minus Hanoi + HCMC which have bespoke scrapers).
# We keep this at module level so a wrong count during a copy-paste fails import
# rather than silently skipping provinces at cron time.
assert len(ALL) == 61, (
    f"Expected 61 generic-province configs (63 - Hanoi - HCMC), got {len(ALL)}. "
    "Did you add/remove a province without updating the count?"
)
