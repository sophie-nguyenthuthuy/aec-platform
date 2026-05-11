/**
 * VN address formatter (cycle MM1, TS half).
 *
 * Vietnamese address structure:
 *   street → ward (Phường/Xã) → district (Quận/Huyện) → province
 *
 * Today the org settings address line, the RFQ supplier
 * addresses, and the project location form each format inline
 * with subtly different segment ordering and trailing-comma
 * handling. This module is the single source of truth.
 *
 *   formatAddressVN(address)   — canonical comma-separated form
 *   isValidProvince(name)      — bool against VN_PROVINCES set
 *   VN_PROVINCES               — closed set of 63 administrative divisions
 *
 * Pure TS, no React. Mirrors `apps/api/services/format_address_vn.py`.
 *
 * Pinned invariants:
 *   * Empty / whitespace-only segments OMITTED from output
 *     (no trailing/dangling commas).
 *   * `province` is the only required field in practice (other
 *     segments may be empty in legacy data).
 *   * Cross-language byte-for-byte parity.
 */


export interface Address {
  street: string;
  ward: string;
  district: string;
  province: string;
}


/** All 63 Vietnamese administrative divisions (5 centrally-
 *  administered cities + 58 provinces). Stored as bare canonical
 *  names without "Tỉnh"/"Thành phố" prefix. Pin so a refactor
 *  that adds "Tỉnh" prefix to one half of the cross-language
 *  pair surfaces in the parity test. */
export const VN_PROVINCES: ReadonlySet<string> = new Set([
  // 5 centrally-administered cities
  "Hà Nội",
  "Hồ Chí Minh",
  "Hải Phòng",
  "Đà Nẵng",
  "Cần Thơ",
  // 58 provinces
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
]);


/**
 * Format an Address as a canonical comma-separated string.
 *
 *   * Full address  → "123 Lê Lợi, Phường Bến Nghé, Quận 1, Hồ Chí Minh"
 *   * Empty street  → "Phường Bến Nghé, Quận 1, Hồ Chí Minh"
 *   * Province only → "Hồ Chí Minh"
 *   * All empty     → ""
 *
 * Whitespace-only segments are treated as empty (no
 * `"  ,  Hồ Chí Minh"` artifacts).
 */
export function formatAddressVN(address: Address): string {
  const segments = [
    address.street.trim(),
    address.ward.trim(),
    address.district.trim(),
    address.province.trim(),
  ];
  return segments.filter((s) => s.length > 0).join(", ");
}


/** True iff `name` (after whitespace strip) is in VN_PROVINCES.
 *  Case-sensitive and diacritic-sensitive — pin canonical form
 *  exactly. */
export function isValidProvince(name: string | null | undefined): boolean {
  if (!name) return false;
  return VN_PROVINCES.has(name.trim());
}
