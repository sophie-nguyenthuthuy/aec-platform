"""VN address formatter (cycle MM1, Python half).

Server-side mirror of `apps/web/lib/format-address-vn.ts`. Used
by the org settings address line, RFQ supplier addresses, the
audit row's address-impact detector, and the invoice template's
recipient address block.

  format_address_vn(addr)    — canonical comma-separated form
  is_valid_province(name)    — bool against VN_PROVINCES set
  Address                    — frozen dataclass: 4 segments
  VN_PROVINCES               — closed set of 63 administrative divisions

Pure stdlib.

Pinned invariants:
  * Empty / whitespace-only segments OMITTED.
  * Bare canonical names (no Tỉnh/Thành phố prefix in registry).
  * Case-sensitive + diacritic-sensitive validation.
  * Cross-language byte-for-byte parity with TS half.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    """VN address structure.

    Segments may be empty for partial addresses. Province is
    typically required in practice but the formatter handles
    any combination.
    """

    street: str
    ward: str
    district: str
    province: str


# All 63 VN administrative divisions (5 centrally-administered
# cities + 58 provinces). Stored as bare canonical names without
# "Tỉnh"/"Thành phố" prefix — pin so a refactor that adds a
# prefix to one half of the cross-language pair surfaces in the
# parity test.
VN_PROVINCES: frozenset[str] = frozenset(
    {
        # 5 centrally-administered cities
        "Hà Nội",
        "Hồ Chí Minh",
        "Hải Phòng",
        "Đà Nẵng",
        "Cần Thơ",
        # 58 provinces
        "An Giang",
        "Bà Rịa - Vũng Tàu",
        "Bắc Giang",
        "Bắc Kạn",
        "Bạc Liêu",
        "Bắc Ninh",
        "Bến Tre",
        "Bình Định",
        "Bình Dương",
        "Bình Phước",
        "Bình Thuận",
        "Cà Mau",
        "Cao Bằng",
        "Đắk Lắk",
        "Đắk Nông",
        "Điện Biên",
        "Đồng Nai",
        "Đồng Tháp",
        "Gia Lai",
        "Hà Giang",
        "Hà Nam",
        "Hà Tĩnh",
        "Hải Dương",
        "Hậu Giang",
        "Hòa Bình",
        "Hưng Yên",
        "Khánh Hòa",
        "Kiên Giang",
        "Kon Tum",
        "Lai Châu",
        "Lâm Đồng",
        "Lạng Sơn",
        "Lào Cai",
        "Long An",
        "Nam Định",
        "Nghệ An",
        "Ninh Bình",
        "Ninh Thuận",
        "Phú Thọ",
        "Phú Yên",
        "Quảng Bình",
        "Quảng Nam",
        "Quảng Ngãi",
        "Quảng Ninh",
        "Quảng Trị",
        "Sóc Trăng",
        "Sơn La",
        "Tây Ninh",
        "Thái Bình",
        "Thái Nguyên",
        "Thanh Hóa",
        "Thừa Thiên Huế",
        "Tiền Giang",
        "Trà Vinh",
        "Tuyên Quang",
        "Vĩnh Long",
        "Vĩnh Phúc",
        "Yên Bái",
    }
)


def format_address_vn(address: Address) -> str:
    """Format an Address as a canonical comma-separated string.

    Empty / whitespace-only segments OMITTED. All-empty input
    returns "".
    """
    segments = [
        address.street.strip(),
        address.ward.strip(),
        address.district.strip(),
        address.province.strip(),
    ]
    return ", ".join(s for s in segments if s)


def is_valid_province(name: str | None) -> bool:
    """True iff `name` (after whitespace strip) is in VN_PROVINCES.

    Case-sensitive + diacritic-sensitive — pin canonical form.
    """
    if not name:
        return False
    return name.strip() in VN_PROVINCES
