"""Unit tests for the price-scraper framework.

Covers the pure-logic parts — normaliser rules, MOC/Hanoi HTML parsing,
registry wiring, and `run_scraper` orchestration — without hitting the
live DOC sites or the DB.

The DB-touching `write_prices` step is tested in
`test_price_scrapers_writer.py` under the same `COSTPULSE_RLS_DB_URL`
guard as the other integration tests.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.price_scrapers import (
    GENERIC_SLUGS,
    SCRAPERS,
    all_slugs,
    get_scraper,
    run_scraper,
)
from services.price_scrapers.base import ScrapedPrice
from services.price_scrapers.generic_province import (
    PENDING_URL,
    GenericProvinceScraper,
    ProvinceConfig,
    _find_first_matching_link,
)
from services.price_scrapers.hanoi import HanoiScraper, _find_latest_hanoi_bulletin_url
from services.price_scrapers.ministry import (
    MinistryOfConstructionScraper,
    _extract_effective_date,
    _find_latest_bulletin_url,
    _parse_bulletin_html,
    _parse_vnd,
)
from services.price_scrapers.normalizer import normalise


# ---------- _parse_vnd ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234.567", Decimal("1234567")),
        ("1,234,567", Decimal("1234567")),
        ("2 000 000 đ", Decimal("2000000")),
        ("12.500 VND", Decimal("12500")),
    ],
)
def test_parse_vnd_handles_common_formats(raw, expected):
    assert _parse_vnd(raw) == expected


def test_parse_vnd_rejects_empty():
    from decimal import InvalidOperation

    with pytest.raises(InvalidOperation):
        _parse_vnd("---")


# ---------- MOC parsers ----------


def test_parse_bulletin_extracts_rows():
    html = """
    <html><body>
    <h1>Thông báo giá tháng 03/2026</h1>
    <table>
      <tr><td>Bê tông thương phẩm C30</td><td>m3</td><td>2.000.000</td></tr>
      <tr><td>Thép cuộn CB500</td><td>kg</td><td>20.500</td></tr>
      <tr><td>Gạch đỏ Tuynel</td><td>viên</td><td>1.200</td></tr>
      <tr><td>Lao động phổ thông</td><td>công</td><td>350.000</td></tr>
    </table>
    </body></html>
    """
    rows = _parse_bulletin_html(html, source_url="https://moc.gov.vn/x.html")
    assert len(rows) == 4
    assert rows[0].raw_name == "Bê tông thương phẩm C30"
    assert rows[0].raw_unit == "m3"
    assert rows[0].price_vnd == Decimal("2000000")
    assert rows[0].effective_date == date(2026, 3, 1)
    assert rows[0].province == "Vietnam"
    assert rows[0].source_url == "https://moc.gov.vn/x.html"


def test_parse_bulletin_skips_zero_and_unparseable_prices():
    html = """
    <table>
      <tr><td>Valid</td><td>kg</td><td>100</td></tr>
      <tr><td>Garbage</td><td>kg</td><td>N/A</td></tr>
      <tr><td>Zero</td><td>kg</td><td>0</td></tr>
      <tr><td></td><td>kg</td><td>500</td></tr>
    </table>
    """
    rows = _parse_bulletin_html(html, source_url="x")
    assert len(rows) == 1
    assert rows[0].raw_name == "Valid"


def test_extract_effective_date_prefers_in_body_month_year():
    assert _extract_effective_date("Thông báo giá tháng 11/2025") == date(2025, 11, 1)
    assert _extract_effective_date("Quý 1-2026") == date(2026, 1, 1)
    assert _extract_effective_date("no date here") is None
    # Out-of-range months/years fall through to None.
    assert _extract_effective_date("tháng 13/2026") is None
    assert _extract_effective_date("tháng 05/1999") is None


def test_find_latest_bulletin_url_rewrites_relative_links():
    html = '<a href="/vn/thong-bao-gia-2026-03.html">Mar</a>'
    assert _find_latest_bulletin_url(html) == "https://moc.gov.vn/vn/thong-bao-gia-2026-03.html"

    html_abs = '<a href="https://other.gov.vn/thong-bao-gia-x.html">link</a>'
    assert _find_latest_bulletin_url(html_abs) == "https://other.gov.vn/thong-bao-gia-x.html"

    assert _find_latest_bulletin_url("<p>no links</p>") is None


def test_find_latest_hanoi_bulletin_url_handles_relative_and_bare_paths():
    assert _find_latest_hanoi_bulletin_url(
        '<a href="/thong-bao-gia/2026-03">Mar</a>'
    ) == "https://soxaydung.hanoi.gov.vn/thong-bao-gia/2026-03"
    assert _find_latest_hanoi_bulletin_url(
        '<a href="thong-bao-gia-x">x</a>'
    ) == "https://soxaydung.hanoi.gov.vn/thong-bao-gia-x"


# ---------- Normaliser ----------


def test_normalise_maps_vietnamese_descriptions_to_material_codes():
    rows = [
        ScrapedPrice("Bê tông thương phẩm C30", "m3", Decimal("2000000"),
                     date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Thép CB500 phi 16", "kg", Decimal("20500"),
                     date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Gạch đỏ tuynel 2 lỗ", "viên", Decimal("1200"),
                     date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Sơn ngoại thất cao cấp", "lít", Decimal("180000"),
                     date(2026, 3, 1), "Hanoi"),
    ]
    matched, unmatched = normalise(rows)
    assert unmatched == []
    codes = {r.material_code for r in matched}
    assert codes == {"CONC_C30", "REBAR_CB500", "BRICK_RED", "PAINT_EXTERIOR"}

    # Category + canonical name are attached from the rule.
    concrete = next(r for r in matched if r.material_code == "CONC_C30")
    assert concrete.category == "concrete"
    assert concrete.name == "Concrete C30"
    assert concrete.unit == "m3"


def test_normalise_flags_unmatched_rows():
    rows = [
        ScrapedPrice("Lao động phổ thông", "công", Decimal("350000"),
                     date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Gạch đỏ tuynel", "viên", Decimal("1200"),
                     date(2026, 3, 1), "Hanoi"),
    ]
    matched, unmatched = normalise(rows)
    assert len(matched) == 1
    assert matched[0].material_code == "BRICK_RED"
    assert len(unmatched) == 1
    assert unmatched[0].raw_name == "Lao động phổ thông"


def test_normalise_concrete_grade_specificity():
    """C40 must not accidentally match C30/C25 and vice versa."""
    rows = [
        ScrapedPrice("Bê tông M400", "m3", Decimal("2500000"), date.today(), "Hanoi"),
        ScrapedPrice("Bê tông M250", "m3", Decimal("1800000"), date.today(), "Hanoi"),
    ]
    matched, _ = normalise(rows)
    codes = [r.material_code for r in matched]
    assert codes == ["CONC_C40", "CONC_C25"]


# ---------- Registry ----------


def test_registry_contains_moc_hanoi_hcmc():
    assert "moc" in SCRAPERS
    assert "hanoi" in SCRAPERS
    assert "hcmc" in SCRAPERS


def test_get_scraper_returns_instance_of_right_class():
    assert isinstance(get_scraper("moc"), MinistryOfConstructionScraper)
    assert isinstance(get_scraper("hanoi"), HanoiScraper)


def test_get_scraper_generic_province_returns_configured_instance():
    """Generic provinces share one class but get a distinct config per slug."""
    scraper = get_scraper("da-nang")
    assert isinstance(scraper, GenericProvinceScraper)
    assert scraper.slug == "da-nang"
    assert scraper.province == "Da Nang"


def test_get_scraper_unknown_slug_raises():
    with pytest.raises(KeyError):
        get_scraper("atlantis")


def test_registry_has_all_63_provinces():
    """MOC + Hanoi + HCMC (bespoke) + 61 generic = 64 total, covering every province."""
    slugs = set(all_slugs())
    assert slugs >= {"moc", "hanoi", "hcmc"}, "bespoke scrapers must be registered"
    assert len(GENERIC_SLUGS) == 61, (
        f"expected 61 generic-province configs, got {len(GENERIC_SLUGS)}"
    )
    assert len(slugs) == 64


# ---------- GenericProvinceScraper ----------


@pytest.mark.asyncio
async def test_generic_province_scraper_skips_pending_urls():
    """Provinces whose listing URL isn't verified must skip cleanly, not fail."""
    config = ProvinceConfig("test-province", "Test", PENDING_URL)
    scraper = GenericProvinceScraper(config)
    assert await scraper.scrape() == []


@pytest.mark.asyncio
async def test_generic_province_scraper_follows_listing_then_bulletin():
    config = ProvinceConfig(
        slug="da-nang",
        province="Da Nang",
        listing_url="https://soxaydung.danang.gov.vn/thong-bao-gia",
    )

    listing_html = '<a href="/thong-bao-gia/2026-thang-03">March 2026</a>'
    bulletin_html = """
    <h1>Thông báo giá tháng 03/2026</h1>
    <table>
      <tr><td>Bê tông C30</td><td>m3</td><td>2.050.000</td></tr>
    </table>
    """
    client = _fake_client({
        "https://soxaydung.danang.gov.vn/thong-bao-gia": _fake_response(listing_html),
        "https://soxaydung.danang.gov.vn/thong-bao-gia/2026-thang-03":
            _fake_response(bulletin_html),
    })

    rows = await GenericProvinceScraper(config, http_client=client).scrape()
    assert len(rows) == 1
    assert rows[0].province == "Da Nang"
    assert rows[0].price_vnd == Decimal("2050000")


@pytest.mark.asyncio
async def test_generic_province_scraper_skips_binary_bulletins():
    config = ProvinceConfig(
        slug="binh-duong",
        province="Binh Duong",
        listing_url="https://sxd.binhduong.gov.vn/thong-bao-gia",
    )
    listing_html = '<a href="/files/thong-bao-gia-2026-03.docx">Mar</a>'
    client = _fake_client({
        "https://sxd.binhduong.gov.vn/thong-bao-gia": _fake_response(listing_html),
    })

    rows = await GenericProvinceScraper(config, http_client=client).scrape()
    # DOCX bulletins get skipped with a log — no rows, no exception.
    assert rows == []


def test_find_first_matching_link_respects_per_province_regex():
    html = (
        '<a href="/tin-tuc">news</a>'
        '<a href="/cong-bo-gia/2026-q1">bulletin</a>'
        '<a href="/thong-bao-gia/2026-03">older</a>'
    )
    # Default regex matches 'cong-bo-gia' — picks the first occurrence.
    url = _find_first_matching_link(
        html,
        link_re=r"(?:thong-bao-gia|cong-bo-gia)",
        base_url="https://x.gov.vn",
    )
    assert url == "https://x.gov.vn/cong-bo-gia/2026-q1"


def test_find_first_matching_link_returns_none_when_nothing_matches():
    assert _find_first_matching_link(
        '<a href="/unrelated">x</a>',
        link_re="thong-bao-gia",
        base_url="https://x.gov.vn",
    ) is None


# ---------- End-to-end MOC scraper with mocked HTTP ----------


@pytest.mark.asyncio
async def test_moc_scraper_follows_listing_then_bulletin(monkeypatch):
    listing_html = '<a href="/vn/thong-bao-gia-2026-03.html">Mar 2026</a>'
    bulletin_html = """
    <h1>Thông báo giá tháng 03/2026</h1>
    <table>
      <tr><td>Bê tông C30</td><td>m3</td><td>2.000.000</td></tr>
      <tr><td>Thép CB500</td><td>kg</td><td>20.000</td></tr>
    </table>
    """
    responses = {
        "https://moc.gov.vn/vn/thong-bao-gia-vat-lieu-xay-dung.html":
            _fake_response(listing_html),
        "https://moc.gov.vn/vn/thong-bao-gia-2026-03.html":
            _fake_response(bulletin_html),
    }

    client = _fake_client(responses)
    scraper = MinistryOfConstructionScraper(http_client=client)

    rows = await scraper.scrape()

    assert len(rows) == 2
    assert {r.raw_name for r in rows} == {"Bê tông C30", "Thép CB500"}
    assert all(r.province == "Vietnam" for r in rows)
    assert all(r.effective_date == date(2026, 3, 1) for r in rows)


@pytest.mark.asyncio
async def test_moc_scraper_returns_empty_when_no_bulletin_link(monkeypatch):
    client = _fake_client({
        "https://moc.gov.vn/vn/thong-bao-gia-vat-lieu-xay-dung.html":
            _fake_response("<html><body>no links here</body></html>"),
    })
    scraper = MinistryOfConstructionScraper(http_client=client)
    assert await scraper.scrape() == []


@pytest.mark.asyncio
async def test_moc_scraper_wraps_http_failure_in_scrape_error():
    from services.price_scrapers.base import ScrapeError

    client = MagicMock()
    client.get = AsyncMock(side_effect=RuntimeError("boom"))
    scraper = MinistryOfConstructionScraper(http_client=client)

    with pytest.raises(ScrapeError) as exc:
        await scraper.scrape()
    assert "boom" in str(exc.value)


# ---------- Hanoi scraper forces province ----------


@pytest.mark.asyncio
async def test_hanoi_scraper_sets_province_to_hanoi():
    listing_html = '<a href="/thong-bao-gia-2026-03">x</a>'
    bulletin_html = """
    <h1>Thông báo giá tháng 03/2026</h1>
    <table>
      <tr><td>Bê tông C30</td><td>m3</td><td>2.100.000</td></tr>
    </table>
    """
    client = _fake_client({
        "https://soxaydung.hanoi.gov.vn/thong-bao-gia-vat-lieu-xd":
            _fake_response(listing_html),
        "https://soxaydung.hanoi.gov.vn/thong-bao-gia-2026-03":
            _fake_response(bulletin_html),
    })

    rows = await HanoiScraper(http_client=client).scrape()
    assert len(rows) == 1
    assert rows[0].province == "Hanoi"


# ---------- run_scraper orchestration ----------


@pytest.mark.asyncio
async def test_run_scraper_aggregates_summary_counts(monkeypatch):
    """run_scraper should scrape → normalise → (mocked) write and return counts."""
    from services.price_scrapers import base

    class _FakeScraper(base.BaseScraper):
        slug = "fake"
        province = "Fakeland"

        async def scrape(self):
            return [
                ScrapedPrice("Bê tông C30", "m3", Decimal("2000000"),
                             date(2026, 3, 1), "Fakeland"),
                ScrapedPrice("Lao động không xác định", "công", Decimal("350000"),
                             date(2026, 3, 1), "Fakeland"),
            ]

    # Stub out the DB write so this test stays unit-level.
    from services import price_scrapers

    async def _fake_write(rows):
        return {"inserted_or_updated": len(rows)}

    monkeypatch.setattr(price_scrapers, "write_prices", _fake_write)

    summary = await run_scraper(_FakeScraper())

    assert summary == {
        "slug": "fake",
        "ok": True,
        "scraped": 2,
        "matched": 1,
        "unmatched": 1,
        "written": 1,
    }


@pytest.mark.asyncio
async def test_run_scraper_catches_scrape_errors(monkeypatch):
    from services.price_scrapers import base

    class _BrokenScraper(base.BaseScraper):
        slug = "broken"
        province = "Nowhere"

        async def scrape(self):
            raise base.ScrapeError("upstream 500")

    summary = await run_scraper(_BrokenScraper())

    assert summary["ok"] is False
    assert summary["error"] == "upstream 500"
    assert summary["scraped"] == 0
    assert summary["written"] == 0


# ---------- helpers ----------


def _fake_response(text: str):
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _fake_client(url_to_response: dict):
    client = MagicMock()

    async def _get(url, *a, **k):
        if url in url_to_response:
            return url_to_response[url]
        raise AssertionError(f"unexpected GET {url}")

    client.get = AsyncMock(side_effect=_get)
    return client
