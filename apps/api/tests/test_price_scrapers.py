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
    assert (
        _find_latest_hanoi_bulletin_url('<a href="/thong-bao-gia/2026-03">Mar</a>')
        == "https://soxaydung.hanoi.gov.vn/thong-bao-gia/2026-03"
    )
    assert (
        _find_latest_hanoi_bulletin_url('<a href="thong-bao-gia-x">x</a>')
        == "https://soxaydung.hanoi.gov.vn/thong-bao-gia-x"
    )


# ---------- Normaliser ----------


def test_normalise_maps_vietnamese_descriptions_to_material_codes():
    rows = [
        ScrapedPrice("Bê tông thương phẩm C30", "m3", Decimal("2000000"), date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Thép CB500 phi 16", "kg", Decimal("20500"), date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Gạch đỏ tuynel 2 lỗ", "viên", Decimal("1200"), date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Sơn ngoại thất cao cấp", "lít", Decimal("180000"), date(2026, 3, 1), "Hanoi"),
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
        ScrapedPrice("Lao động phổ thông", "công", Decimal("350000"), date(2026, 3, 1), "Hanoi"),
        ScrapedPrice("Gạch đỏ tuynel", "viên", Decimal("1200"), date(2026, 3, 1), "Hanoi"),
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
    assert len(GENERIC_SLUGS) == 61, f"expected 61 generic-province configs, got {len(GENERIC_SLUGS)}"
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
    client = _fake_client(
        {
            "https://soxaydung.danang.gov.vn/thong-bao-gia": _fake_response(listing_html),
            "https://soxaydung.danang.gov.vn/thong-bao-gia/2026-thang-03": _fake_response(bulletin_html),
        }
    )

    rows = await GenericProvinceScraper(config, http_client=client).scrape()
    assert len(rows) == 1
    assert rows[0].province == "Da Nang"
    assert rows[0].price_vnd == Decimal("2050000")


@pytest.mark.asyncio
async def test_generic_province_scraper_skips_unhandled_binary_bulletins():
    """Legacy .doc / .xls / .xlsx still skip — we have no parser for those."""
    config = ProvinceConfig(
        slug="binh-duong",
        province="Binh Duong",
        listing_url="https://sxd.binhduong.gov.vn/thong-bao-gia",
    )
    listing_html = '<a href="/files/thong-bao-gia-2026-03.xls">Mar</a>'
    client = _fake_client(
        {
            "https://sxd.binhduong.gov.vn/thong-bao-gia": _fake_response(listing_html),
        }
    )

    rows = await GenericProvinceScraper(config, http_client=client).scrape()
    assert rows == []


@pytest.mark.asyncio
async def test_generic_province_scraper_dispatches_docx_to_parser(monkeypatch):
    """A .docx bulletin URL must fetch + call parse_docx_bulletin with the bytes."""
    from services.price_scrapers import generic_province as gp

    seen: dict = {}

    def _fake_docx(content, *, source_url, province):
        seen["content"] = content
        seen["source_url"] = source_url
        seen["province"] = province
        return [
            ScrapedPrice(
                "Bê tông C30",
                "m3",
                Decimal("2050000"),
                date(2026, 3, 1),
                province,
                source_url=source_url,
            )
        ]

    # Patch the dispatch table — replace the .docx parser with our fake.
    monkeypatch.setitem(gp._BINARY_PARSERS, ".docx", (_fake_docx, "docx"))

    config = ProvinceConfig(
        slug="binh-duong",
        province="Binh Duong",
        listing_url="https://sxd.binhduong.gov.vn/thong-bao-gia",
    )
    listing_html = '<a href="/files/thong-bao-gia-2026-03.docx">Mar</a>'
    bulletin_url = "https://sxd.binhduong.gov.vn/files/thong-bao-gia-2026-03.docx"
    docx_response = MagicMock()
    docx_response.content = b"FAKE_DOCX_BYTES"
    docx_response.raise_for_status = MagicMock()

    client = _fake_client(
        {
            "https://sxd.binhduong.gov.vn/thong-bao-gia": _fake_response(listing_html),
            bulletin_url: docx_response,
        }
    )

    rows = await GenericProvinceScraper(config, http_client=client).scrape()

    assert len(rows) == 1
    assert rows[0].province == "Binh Duong"
    assert seen == {
        "content": b"FAKE_DOCX_BYTES",
        "source_url": bulletin_url,
        "province": "Binh Duong",
    }


@pytest.mark.asyncio
async def test_generic_province_scraper_dispatches_pdf_to_parser(monkeypatch):
    """A .pdf bulletin URL (with query string) must dispatch to parse_pdf_bulletin."""
    from services.price_scrapers import generic_province as gp

    called = {"n": 0}

    def _fake_pdf(content, *, source_url, province):
        called["n"] += 1
        called["content"] = content
        return []

    monkeypatch.setitem(gp._BINARY_PARSERS, ".pdf", (_fake_pdf, "pdf"))

    config = ProvinceConfig(
        slug="quang-nam",
        province="Quang Nam",
        listing_url="https://sxd.quangnam.gov.vn/thong-bao-gia",
    )
    # Direct PDF link — most provinces serve attachments at /files/*.pdf.
    # PDFs behind /download.aspx?file=...&id=... query strings will need
    # Content-Type sniffing later (see B.1.1 follow-up).
    listing_html = '<a href="/files/cong-bo-gia-q1-2026.pdf?download=1">Q1</a>'
    bulletin_url = "https://sxd.quangnam.gov.vn/files/cong-bo-gia-q1-2026.pdf?download=1"
    pdf_response = MagicMock()
    pdf_response.content = b"%PDF-1.4 ..."
    pdf_response.raise_for_status = MagicMock()

    client = _fake_client(
        {
            "https://sxd.quangnam.gov.vn/thong-bao-gia": _fake_response(listing_html),
            bulletin_url: pdf_response,
        }
    )

    await GenericProvinceScraper(config, http_client=client).scrape()
    assert called["n"] == 1
    assert called["content"] == b"%PDF-1.4 ..."


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
    assert (
        _find_first_matching_link(
            '<a href="/unrelated">x</a>',
            link_re="thong-bao-gia",
            base_url="https://x.gov.vn",
        )
        is None
    )


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
        "https://moc.gov.vn/vn/thong-bao-gia-vat-lieu-xay-dung.html": _fake_response(listing_html),
        "https://moc.gov.vn/vn/thong-bao-gia-2026-03.html": _fake_response(bulletin_html),
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
    client = _fake_client(
        {
            "https://moc.gov.vn/vn/thong-bao-gia-vat-lieu-xay-dung.html": _fake_response(
                "<html><body>no links here</body></html>"
            ),
        }
    )
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
    client = _fake_client(
        {
            "https://soxaydung.hanoi.gov.vn/thong-bao-gia-vat-lieu-xd": _fake_response(listing_html),
            "https://soxaydung.hanoi.gov.vn/thong-bao-gia-2026-03": _fake_response(bulletin_html),
        }
    )

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
                ScrapedPrice("Bê tông C30", "m3", Decimal("2000000"), date(2026, 3, 1), "Fakeland"),
                ScrapedPrice("Lao động không xác định", "công", Decimal("350000"), date(2026, 3, 1), "Fakeland"),
            ]

    # Stub out the DB write so this test stays unit-level.
    from services import price_scrapers

    async def _fake_write(rows):
        return {"inserted_or_updated": len(rows)}

    monkeypatch.setattr(price_scrapers, "write_prices", _fake_write)

    summary = await run_scraper(_FakeScraper())

    # Core counts are the contract.
    assert summary["slug"] == "fake"
    assert summary["ok"] is True
    assert summary["scraped"] == 2
    assert summary["matched"] == 1
    assert summary["unmatched"] == 1
    assert summary["written"] == 1
    # Drift telemetry (B.2) is also part of the contract.
    assert summary["rule_hits"]["CONC_C30"] == 1
    assert summary["rule_hits"]["REBAR_CB500"] == 0
    assert summary["unmatched_sample"] == ["Lao động không xác định"]


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


# ---------- Drift monitoring (B.2) ----------


@pytest.mark.asyncio
async def test_run_scraper_logs_drift_warning_above_threshold(monkeypatch, caplog):
    """High unmatched ratio must surface a `scraper.drift[...]` WARN."""
    import logging

    from services import price_scrapers
    from services.price_scrapers import base

    class _DriftyScraper(base.BaseScraper):
        slug = "drifty-province"
        province = "Drifty"

        async def scrape(self):
            # 4 unparseable + 1 known = 80% unmatched, well over 30%.
            return [
                ScrapedPrice("Đèn LED Philips A19", "cái", Decimal("85000"), date(2026, 3, 1), "Drifty"),
                ScrapedPrice("Cửa nhôm Xingfa hệ 55", "m2", Decimal("950000"), date(2026, 3, 1), "Drifty"),
                ScrapedPrice("Lavabo TOTO LW210", "cái", Decimal("1200000"), date(2026, 3, 1), "Drifty"),
                ScrapedPrice("Đầu nối ống PPR D25", "cái", Decimal("8500"), date(2026, 3, 1), "Drifty"),
                ScrapedPrice("Bê tông C30", "m3", Decimal("2000000"), date(2026, 3, 1), "Drifty"),
            ]

    async def _fake_write(rows):
        return {"inserted_or_updated": len(rows)}

    monkeypatch.setattr(price_scrapers, "write_prices", _fake_write)

    with caplog.at_level(logging.WARNING, logger="services.price_scrapers"):
        summary = await run_scraper(_DriftyScraper())

    assert summary["matched"] == 1
    assert summary["unmatched"] == 4
    drift_records = [r for r in caplog.records if "scraper.drift[drifty-province]" in r.getMessage()]
    assert len(drift_records) == 1
    assert "4/5 (80%)" in drift_records[0].getMessage()


@pytest.mark.asyncio
async def test_run_scraper_does_not_log_drift_when_under_threshold(monkeypatch, caplog):
    """Below the 30% threshold, no `scraper.drift[...]` warning at all."""
    import logging

    from services import price_scrapers
    from services.price_scrapers import base

    class _CleanScraper(base.BaseScraper):
        slug = "clean-province"
        province = "Clean"

        async def scrape(self):
            return [
                ScrapedPrice("Bê tông C30", "m3", Decimal("2000000"), date(2026, 3, 1), "Clean"),
                ScrapedPrice("Bê tông C25", "m3", Decimal("1700000"), date(2026, 3, 1), "Clean"),
                ScrapedPrice("Thép CB500", "kg", Decimal("20500"), date(2026, 3, 1), "Clean"),
                ScrapedPrice("Gạch đỏ tuynel", "viên", Decimal("1200"), date(2026, 3, 1), "Clean"),
                ScrapedPrice("Some weird thing", "cái", Decimal("100"), date(2026, 3, 1), "Clean"),
            ]

    async def _fake_write(rows):
        return {"inserted_or_updated": len(rows)}

    monkeypatch.setattr(price_scrapers, "write_prices", _fake_write)

    with caplog.at_level(logging.WARNING, logger="services.price_scrapers"):
        await run_scraper(_CleanScraper())

    drift_records = [r for r in caplog.records if "scraper.drift[" in r.getMessage()]
    assert drift_records == []


@pytest.mark.asyncio
async def test_run_scraper_persists_telemetry_row_on_success(monkeypatch):
    """A successful run must add a ScraperRun row via AdminSessionFactory."""
    from services import price_scrapers
    from services.price_scrapers import base

    class _OkScraper(base.BaseScraper):
        slug = "telemetry-test"
        province = "Telemetryland"

        async def scrape(self):
            return [
                ScrapedPrice("Bê tông C30", "m3", Decimal("2000000"), date(2026, 3, 1), "Telemetryland"),
                ScrapedPrice("Lao động phổ thông", "công", Decimal("350000"), date(2026, 3, 1), "Telemetryland"),
            ]

    async def _fake_write(rows):
        return {"inserted_or_updated": len(rows)}

    monkeypatch.setattr(price_scrapers, "write_prices", _fake_write)

    captured = _install_admin_session_capture(monkeypatch)
    summary = await run_scraper(_OkScraper())
    assert summary["ok"] is True

    assert len(captured["added"]) == 1
    row = captured["added"][0]
    assert row.slug == "telemetry-test"
    assert row.ok is True
    assert row.error is None
    assert row.scraped == 2
    assert row.matched == 1
    assert row.unmatched == 1
    assert row.written == 1
    assert row.rule_hits["CONC_C30"] == 1
    assert row.unmatched_sample == ["Lao động phổ thông"]
    assert row.started_at is not None
    assert row.finished_at is not None
    assert row.finished_at >= row.started_at
    assert captured["committed"] is True


@pytest.mark.asyncio
async def test_run_scraper_persists_telemetry_row_on_scrape_error(monkeypatch):
    """A ScrapeError run must still write a row, with ok=False + error set."""
    from services.price_scrapers import base

    class _BrokenScraper(base.BaseScraper):
        slug = "telemetry-error"
        province = "Errorland"

        async def scrape(self):
            raise base.ScrapeError("upstream 500")

    captured = _install_admin_session_capture(monkeypatch)
    summary = await run_scraper(_BrokenScraper())
    assert summary["ok"] is False

    assert len(captured["added"]) == 1
    row = captured["added"][0]
    assert row.slug == "telemetry-error"
    assert row.ok is False
    assert row.error == "upstream 500"
    assert row.scraped == 0
    assert row.matched == 0


@pytest.mark.asyncio
async def test_run_scraper_swallows_telemetry_persist_failures(monkeypatch, caplog):
    """A DB failure during telemetry persist must not propagate."""
    import logging

    from services import price_scrapers
    from services.price_scrapers import base

    class _OkScraper(base.BaseScraper):
        slug = "telemetry-survives"
        province = "Survival"

        async def scrape(self):
            return [
                ScrapedPrice("Bê tông C30", "m3", Decimal("2000000"), date(2026, 3, 1), "Survival"),
            ]

    async def _fake_write(rows):
        return {"inserted_or_updated": len(rows)}

    monkeypatch.setattr(price_scrapers, "write_prices", _fake_write)

    import db.session as db_session

    class _BoomSession:
        def add(self, *a, **k):
            pass

        async def commit(self):
            raise RuntimeError("simulated DB outage")

    class _BoomFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _BoomSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(db_session, "AdminSessionFactory", _BoomFactory())

    with caplog.at_level(logging.WARNING, logger="services.price_scrapers"):
        summary = await run_scraper(_OkScraper())

    assert summary["ok"] is True  # scrape succeeded; telemetry failure swallowed
    persist_records = [r for r in caplog.records if "scraper.persist_run" in r.getMessage()]
    assert len(persist_records) == 1
    assert "simulated DB outage" in persist_records[0].getMessage()


def _install_admin_session_capture(monkeypatch):
    """Replace `db.session.AdminSessionFactory` with a capturing fake.

    Returns a dict that gets `added` (model instances passed to
    `session.add`) and `committed` (bool) populated as `run_scraper`
    persists telemetry. Used instead of a live DB.
    """
    import db.session as db_session

    captured: dict = {"added": [], "committed": False}

    class _CaptureSession:
        def add(self, instance):
            captured["added"].append(instance)

        async def commit(self):
            captured["committed"] = True

    class _CaptureFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _CaptureSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(db_session, "AdminSessionFactory", _CaptureFactory())
    return captured


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


# ---------- Bulletin-parser core (table.py) ----------
#
# These exercise `services.price_scrapers.parsers.table` — the
# library-agnostic logic that turns a list-of-lists of cell strings into
# ScrapedPrice rows. They run with no optional deps installed (no
# python-docx, no pdfplumber); only the thin DOCX/PDF *adapters* need
# those, and the adapters lazy-import.


from services.price_scrapers.parsers.table import (
    ColumnMap,
    detect_columns,
    extract_effective_date,
    extract_prices_from_table,
)


class TestDetectColumns:
    """Header detection across realistic provincial column-name variants."""

    def test_canonical_vietnamese_headers(self):
        cols = detect_columns(["STT", "Tên vật liệu", "Đơn vị tính", "Đơn giá (VND)"])
        assert cols == ColumnMap(name=1, unit=2, price=3)

    def test_unit_abbreviation_dvt(self):
        # ĐVT is the most common unit abbreviation in older bulletins.
        cols = detect_columns(["Tên hàng", "ĐVT", "Đơn giá"])
        assert cols == ColumnMap(name=0, unit=1, price=2)

    def test_english_headers(self):
        cols = detect_columns(["#", "Material", "Unit", "Unit Price"])
        assert cols == ColumnMap(name=1, unit=2, price=3)

    def test_diacritics_folded_for_matching(self):
        # No diacritics on the input — must still match.
        cols = detect_columns(["Ten vat lieu", "Don vi", "Don gia"])
        assert cols == ColumnMap(name=0, unit=1, price=2)

    def test_extra_qualifying_text_in_header_cell(self):
        # Real bulletins often have parenthesised hints — must still match.
        cols = detect_columns(
            [
                "STT",
                "Tên vật liệu (chủng loại)",
                "Đơn vị tính (ĐVT)",
                "Đơn giá trước thuế (VND/đv)",
            ]
        )
        assert cols == ColumnMap(name=1, unit=2, price=3)

    def test_returns_none_when_any_column_missing(self):
        # Missing the price column.
        assert detect_columns(["STT", "Tên vật liệu", "Đơn vị"]) is None
        # Missing the unit column.
        assert detect_columns(["Tên", "Giá"]) is None
        # Pure header-less data row.
        assert detect_columns(["Bê tông C30", "m3", "2000000"]) is None

    def test_returns_none_when_columns_collide(self):
        # Two columns matching the same alias would shadow each other.
        # Defensive: refuse the row rather than guess.
        assert detect_columns(["Tên", "Đơn giá", "Đơn giá"]) is None


class TestExtractPricesFromTable:
    """End-to-end row extraction from list-of-lists input."""

    def test_extracts_rows_with_canonical_layout(self):
        rows = [
            ["I. Vật liệu xây dựng"],  # category banner — must be skipped
            ["STT", "Tên vật liệu", "ĐVT", "Đơn giá (VND)"],
            ["1", "Bê tông thương phẩm C30", "m3", "2.050.000"],
            ["2", "Thép cuộn CB500", "kg", "20.500"],
            ["3", "Gạch đỏ Tuynel", "viên", "1.200"],
        ]
        out = extract_prices_from_table(
            rows,
            effective_date=date(2026, 3, 1),
            source_url="https://x.gov.vn/bulletin",
            province="Da Nang",
        )

        assert len(out) == 3
        names = [r.raw_name for r in out]
        assert "Bê tông thương phẩm C30" in names
        assert all(r.province == "Da Nang" for r in out)
        assert all(r.effective_date == date(2026, 3, 1) for r in out)

        bt = next(r for r in out if r.raw_name.startswith("Bê tông"))
        assert bt.price_vnd == Decimal("2050000")
        assert bt.raw_unit == "m3"
        assert bt.source_url == "https://x.gov.vn/bulletin"

    def test_skips_blank_name_rows(self):
        # Section separators ("II. Cốt thép") have only one non-empty cell.
        rows = [
            ["Tên", "Đơn vị", "Đơn giá"],
            ["", "", ""],
            ["II. Cốt thép", "", ""],
            ["Thép CB500", "kg", "20000"],
        ]
        out = extract_prices_from_table(
            rows,
            effective_date=date(2026, 3, 1),
            source_url=None,
            province="Test",
        )
        assert [r.raw_name for r in out] == ["Thép CB500"]

    def test_skips_unparseable_or_zero_prices(self):
        rows = [
            ["Tên", "Đơn vị", "Đơn giá"],
            ["Bê tông C30", "m3", "—"],  # no digits
            ["Lao động", "công", "0"],  # zero — meaningless
            ["Thép CB500", "kg", "20.000"],  # ok
            ["Gạch", "viên", ""],  # empty cell
        ]
        out = extract_prices_from_table(
            rows,
            effective_date=date(2026, 3, 1),
            source_url=None,
            province="Test",
        )
        assert [r.raw_name for r in out] == ["Thép CB500"]

    def test_skips_ragged_rows_shorter_than_columns(self):
        # Merged-cell rows can be truncated by the upstream extractor.
        rows = [
            ["Tên", "Đơn vị", "Đơn giá"],
            ["Bê tông C30", "m3"],  # missing price cell
            ["Thép CB500", "kg", "20000"],
        ]
        out = extract_prices_from_table(
            rows,
            effective_date=date(2026, 3, 1),
            source_url=None,
            province="Test",
        )
        assert [r.raw_name for r in out] == ["Thép CB500"]

    def test_returns_empty_when_no_header_found(self):
        # Pure data with no recognisable header — log + return [], don't raise.
        rows = [
            ["Bê tông C30", "m3", "2000000"],
            ["Thép CB500", "kg", "20000"],
        ]
        out = extract_prices_from_table(
            rows,
            effective_date=date(2026, 3, 1),
            source_url=None,
            province="Test",
        )
        assert out == []

    def test_uses_first_matching_header_when_table_has_two(self):
        # PDF page-tables sometimes split across pages and re-emit the header.
        # The current core takes the *first* header it finds; subsequent
        # header rows look like data rows but their price cells aren't
        # parseable, so they get skipped — pinning that expected behaviour.
        rows = [
            ["Tên", "Đơn vị", "Đơn giá"],
            ["Bê tông C30", "m3", "2000000"],
            ["Tên", "Đơn vị", "Đơn giá"],  # repeat header on page 2
            ["Thép CB500", "kg", "20000"],
        ]
        out = extract_prices_from_table(
            rows,
            effective_date=date(2026, 3, 1),
            source_url=None,
            province="Test",
        )
        assert [r.raw_name for r in out] == ["Bê tông C30", "Thép CB500"]


class TestExtractEffectiveDate:
    """Effective-date extraction from bulletin free text."""

    def test_thang_mm_yyyy_form(self):
        assert extract_effective_date("Thông báo giá vật liệu xây dựng tháng 03/2026") == date(2026, 3, 1)

    def test_no_diacritics_form(self):
        assert extract_effective_date("thang 12-2025") == date(2025, 12, 1)

    def test_returns_none_for_invalid_month(self):
        assert extract_effective_date("tháng 13/2026") is None

    def test_returns_none_for_year_far_outside_window(self):
        assert extract_effective_date("tháng 03/1999") is None
        # Year > today.year + 1 also rejected.
        assert extract_effective_date("tháng 03/9999") is None

    def test_returns_none_when_no_date_present(self):
        assert extract_effective_date("Báo cáo vật liệu xây dựng") is None

    def test_returns_none_for_empty_string(self):
        assert extract_effective_date("") is None
        assert extract_effective_date(None) is None  # type: ignore[arg-type]


# ---------- PENDING-URL probe (B.3) ----------
#
# The probe tool is operator-run from a network that can reach .gov.vn,
# so we don't make real HTTP calls in tests. We unit-test the URL
# generation + the result-interpretation logic, and exercise probe_slug
# through a fake http_client.


from services.price_scrapers.probe import (
    ProbeResult,
    _slug_to_subdomain,
    candidate_urls,
    probe_slug,
    probe_url,
)


class TestCandidateUrls:
    """URL-template generation for PENDING_URL province probing."""

    def test_simple_slug_strips_hyphens_for_subdomain(self):
        urls = candidate_urls("ha-giang")
        # Every candidate must use `hagiang` as the domain segment.
        assert all("hagiang.gov.vn" in u for u in urls)
        assert not any("ha-giang.gov.vn" in u for u in urls)

    def test_multi_part_slug_joins_all_segments(self):
        # ba-ria-vung-tau → bariavungtau, no dots.
        assert _slug_to_subdomain("ba-ria-vung-tau") == "bariavungtau"
        urls = candidate_urls("ba-ria-vung-tau")
        assert all("bariavungtau.gov.vn" in u for u in urls)

    def test_candidate_count_is_prefix_x_path(self):
        # 2 prefixes × 5 paths = 10 candidates. If we add a prefix or path,
        # this test will fail loudly so the operator notices the probe
        # traffic budget changed.
        assert len(candidate_urls("ha-giang")) == 10

    def test_first_candidate_uses_most_common_pattern(self):
        # Most verified provinces use `sxd.<slug>.gov.vn/thong-bao-gia-vat-lieu`,
        # so that's what we should try first to short-circuit on the common
        # case before probing more rarely-used patterns.
        first = candidate_urls("ha-giang")[0]
        assert first == "https://sxd.hagiang.gov.vn/thong-bao-gia-vat-lieu"


class TestProbeResultInterpretation:
    """`ProbeResult.is_match` is the contract — pin its boundaries."""

    def test_200_with_bulletin_link_is_match(self):
        result = ProbeResult(
            slug="x",
            url="https://x",
            status=200,
            has_bulletin_link=True,
            error=None,
            elapsed_ms=10,
        )
        assert result.is_match is True

    def test_200_without_bulletin_link_is_not_match(self):
        # We landed on the DOC home page or a generic news index.
        result = ProbeResult(
            slug="x",
            url="https://x",
            status=200,
            has_bulletin_link=False,
            error=None,
            elapsed_ms=10,
        )
        assert result.is_match is False

    def test_404_is_not_match(self):
        result = ProbeResult(
            slug="x",
            url="https://x",
            status=404,
            has_bulletin_link=False,
            error=None,
            elapsed_ms=10,
        )
        assert result.is_match is False

    def test_transport_failure_is_not_match(self):
        # DNS / TLS / timeout — no HTTP status at all.
        result = ProbeResult(
            slug="x",
            url="https://x",
            status=None,
            has_bulletin_link=False,
            error="DNSError: NXDOMAIN",
            elapsed_ms=10,
        )
        assert result.is_match is False


class TestProbeUrl:
    """`probe_url` must turn http_client outcomes into ProbeResult shapes."""

    @pytest.mark.asyncio
    async def test_200_with_bulletin_href_in_body(self):
        client = MagicMock()
        client.get = AsyncMock(
            return_value=_probe_response(
                200,
                'irrelevant text <a href="/cong-bo-gia/2026-q1">Q1</a> more text',
            )
        )
        result = await probe_url("ha-giang", "https://sxd.hagiang.gov.vn/x", http_client=client)
        assert result.status == 200
        assert result.has_bulletin_link is True
        assert result.is_match is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_200_without_bulletin_href(self):
        client = MagicMock()
        client.get = AsyncMock(
            return_value=_probe_response(
                200,
                "<html><body><p>welcome</p></body></html>",
            )
        )
        result = await probe_url("x", "https://x", http_client=client)
        assert result.status == 200
        assert result.has_bulletin_link is False
        assert result.is_match is False

    @pytest.mark.asyncio
    async def test_404(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_probe_response(404, "not found"))
        result = await probe_url("x", "https://x", http_client=client)
        assert result.status == 404
        assert result.is_match is False

    @pytest.mark.asyncio
    async def test_transport_failure_is_caught(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=RuntimeError("simulated DNS"))
        result = await probe_url("x", "https://x", http_client=client)
        assert result.status is None
        assert result.error is not None
        assert "simulated DNS" in result.error
        assert result.is_match is False


class TestProbeSlug:
    """`probe_slug` should short-circuit on the first matching candidate."""

    @pytest.mark.asyncio
    async def test_returns_first_match_and_stops(self):
        # Set up a client that:
        #   - 404s the first candidate
        #   - 200s with no bulletin link on the second
        #   - 200s WITH a bulletin link on the third
        # `probe_slug` must return the third result and NOT call the client
        # any more after that.
        candidates = candidate_urls("ha-giang")
        responses = {
            candidates[0]: _probe_response(404, ""),
            candidates[1]: _probe_response(200, "<p>news</p>"),
            candidates[2]: _probe_response(200, '<a href="/thong-bao-gia/x">x</a>'),
        }
        seen_calls: list[str] = []

        async def _get(url, *a, **k):
            seen_calls.append(url)
            if url in responses:
                return responses[url]
            return _probe_response(404, "")

        client = MagicMock()
        client.get = AsyncMock(side_effect=_get)
        result = await probe_slug("ha-giang", http_client=client)

        assert result is not None
        assert result.url == candidates[2]
        assert result.is_match is True
        # Did NOT probe any candidates after the matching one.
        assert seen_calls == candidates[:3]

    @pytest.mark.asyncio
    async def test_returns_none_when_every_candidate_fails(self):
        # Universal 404 → no match → None.
        client = MagicMock()
        client.get = AsyncMock(return_value=_probe_response(404, ""))
        assert await probe_slug("ha-giang", http_client=client) is None


def _probe_response(status_code: int, text: str):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ---------- PDF OCR fallback (T2.4) ----------
#
# The full OCR pipeline depends on poppler (system) + pytesseract +
# tesseract-vie-traineddata, which only the prod containers have. These
# tests exercise the pure-Python row-splitter logic and the lazy-import
# degradation path so the parser stays robust whether OCR deps are
# present or not.


from services.price_scrapers.parsers.pdf import _split_ocr_text_into_rows


class TestSplitOcrTextIntoRows:
    """Tesseract-style output → list-of-list rows."""

    def test_splits_multispace_runs_into_columns(self):
        text = "Bê tông C30      m3      2.050.000\nThép cuộn CB500  kg      20.500\n"
        rows = _split_ocr_text_into_rows(text)
        assert rows == [
            ["Bê tông C30", "m3", "2.050.000"],
            ["Thép cuộn CB500", "kg", "20.500"],
        ]

    def test_keeps_single_spaces_inside_cells(self):
        # "Bê tông thương phẩm" is one cell — single spaces stay.
        text = "Bê tông thương phẩm C30    m3    2.000.000\n"
        rows = _split_ocr_text_into_rows(text)
        assert rows == [["Bê tông thương phẩm C30", "m3", "2.000.000"]]

    def test_drops_blank_and_paragraph_lines(self):
        # Banner text (one cell) and blank lines must NOT appear in rows.
        text = (
            "Thông báo giá tháng 03/2026\n"
            "\n"
            "Bê tông C30      m3      2.000.000\n"
            "  \n"
            "Phòng Kinh tế Vật liệu\n"
            "Thép CB500       kg      20.500\n"
        )
        rows = _split_ocr_text_into_rows(text)
        # Only the two table-shaped rows survive; banner / footer get pruned.
        assert rows == [
            ["Bê tông C30", "m3", "2.000.000"],
            ["Thép CB500", "kg", "20.500"],
        ]

    def test_returns_empty_for_pure_paragraph_text(self):
        # No 2+-space gaps anywhere — the whole document is prose.
        text = (
            "Phòng Kinh tế Vật liệu Xây dựng kính báo cáo các nhà thầu "
            "rằng giá vật liệu tháng này có những thay đổi như sau...\n"
        )
        assert _split_ocr_text_into_rows(text) == []


def test_ocr_tables_returns_empty_when_pytesseract_missing(monkeypatch, caplog):
    """Lazy-import: when pytesseract isn't installed, OCR returns ([], '').

    The parser should log + degrade rather than raise. We simulate the
    ImportError by injecting a fake `pytesseract` module that itself
    imports a missing dep.
    """
    import logging
    import sys

    from services.price_scrapers.parsers import pdf as pdf_parser

    # Swap pytesseract / pdf2image to None in sys.modules so the
    # `import` inside `_ocr_tables` raises ImportError. We avoid using
    # builtins.__import__ patches because `pdfplumber`'s own imports
    # would trip them.
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    monkeypatch.setitem(sys.modules, "pdf2image", None)

    with caplog.at_level(logging.INFO, logger="services.price_scrapers.parsers.pdf"):
        rows, full_text = pdf_parser._ocr_tables(b"%PDF-1.4 fake", province="test")

    assert rows == []
    assert full_text == ""
    log_msgs = [r.getMessage() for r in caplog.records]
    assert any("OCR deps not installed" in m for m in log_msgs)
