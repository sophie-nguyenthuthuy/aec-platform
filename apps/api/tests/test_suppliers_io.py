"""Unit tests for `services.suppliers_io`.

Covers both the library-agnostic core (column detection + row
coercion) and the two thin format adapters (CSV via stdlib, XLSX via
openpyxl).

Endpoint-level integration with the costpulse router lives in
`test_costpulse_router.py`.
"""

from __future__ import annotations

import pytest

from services.suppliers_io.core import (
    SupplierImportError,
    SupplierRow,
    coerce_row,
    detect_columns,
)

# ---------- detect_columns ----------


class TestDetectColumns:
    def test_canonical_vietnamese_headers(self):
        cols = detect_columns(["Tên nhà cung cấp", "Email", "Số điện thoại", "Danh mục", "Tỉnh thành"])
        assert cols.name == 0
        assert cols.email == 1
        assert cols.phone == 2
        assert cols.categories == 3
        assert cols.provinces == 4

    def test_english_headers(self):
        cols = detect_columns(["Company Name", "E-mail", "Phone", "Categories", "Province"])
        assert (cols.name, cols.email, cols.phone, cols.categories, cols.provinces) == (
            0,
            1,
            2,
            3,
            4,
        )

    def test_mixed_case_with_extra_text_in_cells(self):
        cols = detect_columns(["Tên (bắt buộc)", "Số điện thoại liên hệ", "Email công ty"])
        assert cols.name == 0
        assert cols.phone == 1
        assert cols.email == 2

    def test_only_name_column_present_other_fields_none(self):
        cols = detect_columns(["Tên"])
        assert cols.name == 0
        assert cols.email is None
        assert cols.phone is None
        assert cols.categories is None
        assert cols.provinces is None

    def test_raises_when_name_column_missing(self):
        with pytest.raises(SupplierImportError) as exc:
            detect_columns(["Email", "Phone"])
        assert "name" in str(exc.value).lower()

    def test_name_match_does_not_steal_other_columns(self):
        # `Tên` matches the name alias, but `Email` and `Phone` must
        # still be detected — earlier bug had the name-match flagging
        # cell 0 + the `name` regex eating subsequent matches.
        cols = detect_columns(["Tên", "Email", "Phone"])
        assert (cols.name, cols.email, cols.phone) == (0, 1, 2)


# ---------- coerce_row ----------


class TestCoerceRow:
    def setup_method(self):
        self.cols = detect_columns(["Tên", "Email", "Phone", "Categories", "Provinces"])

    def test_full_row(self):
        row = coerce_row(
            ["Hòa Phát Steel", "sales@hoaphat.vn", "+84 24 1234 5678", "steel; rebar", "Hanoi, HCMC"],
            self.cols,
        )
        assert isinstance(row, SupplierRow)
        assert row.name == "Hòa Phát Steel"
        assert row.email == "sales@hoaphat.vn"
        assert row.phone == "+84 24 1234 5678"
        # Mixed separators (`;` and `,`) both split the list.
        assert row.categories == ["steel", "rebar"]
        assert row.provinces == ["Hanoi", "HCMC"]

    def test_email_lowercased(self):
        """Email uniqueness is case-insensitive in practice; lowercase here."""
        row = coerce_row(["X", "FOO@BAR.com", "", "", ""], self.cols)
        assert row.email == "foo@bar.com"

    def test_blank_name_returns_none(self):
        """Spacer rows with blank name should be skipped silently."""
        assert coerce_row(["   ", "x@y", "", "", ""], self.cols) is None

    def test_short_row_falls_back_to_empty_for_missing_cells(self):
        """A 2-cell row when the header has 5 columns shouldn't crash."""
        row = coerce_row(["Hòa Phát", "sales@hp.vn"], self.cols)
        assert row is not None
        assert row.name == "Hòa Phát"
        assert row.email == "sales@hp.vn"
        assert row.phone is None
        assert row.categories == []

    def test_pipe_and_slash_separators_split_lists(self):
        """Buyers paste from various sources; accept | and / too."""
        row = coerce_row(["X", "", "", "steel|rebar/cement", "Hanoi|HCMC"], self.cols)
        assert row.categories == ["steel", "rebar", "cement"]
        assert row.provinces == ["Hanoi", "HCMC"]

    def test_phone_preserved_verbatim(self):
        """Don't try to normalise phone numbers — formats vary across countries."""
        row = coerce_row(["X", "", "(+84) 90.123.4567", "", ""], self.cols)
        assert row.phone == "(+84) 90.123.4567"


# ---------- CSV adapter ----------


class TestParseCsv:
    def test_utf8_with_bom(self):
        from services.suppliers_io.csv_adapter import parse_suppliers_csv

        # Excel "Save as CSV UTF-8" prepends ﻿.
        body = (
            "﻿Tên,Email,Số điện thoại,Danh mục,Tỉnh\r\n"
            "Hòa Phát,sales@hp.vn,+84-1234,thép;cọc,Hanoi\r\n"
            "Vĩnh Tường,info@vt.vn,,gypsum,HCMC\r\n"
        ).encode()
        rows = parse_suppliers_csv(body)
        assert len(rows) == 2
        assert rows[0].name == "Hòa Phát"
        assert rows[0].categories == ["thép", "cọc"]
        assert rows[1].name == "Vĩnh Tường"
        assert rows[1].phone is None

    def test_semicolon_delimiter(self):
        """VN locale Excel often uses `;` as field delim."""
        from services.suppliers_io.csv_adapter import parse_suppliers_csv

        body = "Tên;Email;Phone\nHòa Phát;a@b.vn;123\n".encode()
        rows = parse_suppliers_csv(body)
        assert len(rows) == 1
        assert rows[0].name == "Hòa Phát"
        assert rows[0].email == "a@b.vn"

    def test_empty_body_raises(self):
        from services.suppliers_io.csv_adapter import parse_suppliers_csv

        with pytest.raises(SupplierImportError):
            parse_suppliers_csv(b"")

    def test_blank_rows_skipped_silently(self):
        from services.suppliers_io.csv_adapter import parse_suppliers_csv

        body = ("Tên,Email\n\nHòa Phát,a@b.vn\n,,,\nVĩnh Tường,c@d.vn\n").encode()
        rows = parse_suppliers_csv(body)
        assert [r.name for r in rows] == ["Hòa Phát", "Vĩnh Tường"]


# ---------- XLSX adapter ----------


class TestParseXlsx:
    def test_round_trip_via_openpyxl(self):
        """Build a workbook in memory and parse it back. Pins both the
        adapter's Vietnamese column-detection AND openpyxl's
        cell-value coercion (numeric → string for phone numbers)."""
        openpyxl = pytest.importorskip("openpyxl")
        from io import BytesIO

        from services.suppliers_io.xlsx import parse_suppliers_xlsx

        wb = openpyxl.Workbook()
        sheet = wb.active
        sheet.append(["Tên", "Email", "Số điện thoại", "Danh mục", "Tỉnh"])
        sheet.append(["Hòa Phát Steel", "sales@hp.vn", 84241234567, "thép, cọc", "Hanoi"])
        sheet.append(["Vĩnh Tường", None, None, "gypsum", "HCMC"])

        buf = BytesIO()
        wb.save(buf)
        rows = parse_suppliers_xlsx(buf.getvalue())

        assert [r.name for r in rows] == ["Hòa Phát Steel", "Vĩnh Tường"]
        # Numeric phone in the cell → coerced to string by adapter.
        assert rows[0].phone == "84241234567"
        assert rows[0].categories == ["thép", "cọc"]

    def test_skips_leading_blank_rows(self):
        """Banner-style spreadsheets with empty title rows still parse."""
        openpyxl = pytest.importorskip("openpyxl")
        from io import BytesIO

        from services.suppliers_io.xlsx import parse_suppliers_xlsx

        wb = openpyxl.Workbook()
        sheet = wb.active
        sheet.append([None, None, None])  # blank
        sheet.append([None, None, None])  # blank
        sheet.append(["Name", "Email", "Phone"])  # header
        sheet.append(["Hòa Phát", "x@y.vn", "+84"])

        buf = BytesIO()
        wb.save(buf)
        rows = parse_suppliers_xlsx(buf.getvalue())
        assert len(rows) == 1
        assert rows[0].name == "Hòa Phát"

    def test_malformed_bytes_raises_supplier_import_error(self):
        from services.suppliers_io.xlsx import parse_suppliers_xlsx

        with pytest.raises(SupplierImportError):
            parse_suppliers_xlsx(b"not a real xlsx file")
