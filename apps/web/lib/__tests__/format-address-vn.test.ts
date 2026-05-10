/**
 * VN address formatter (cycle MM1, TS half).
 *
 * Pinned seams:
 *   1. VN_PROVINCES has 63 entries (5 cities + 58 provinces).
 *   2. Empty segments OMITTED from output.
 *   3. Whitespace-only segments treated as empty.
 *   4. Comma-separated joining.
 *   5. is_valid_province case-sensitive + diacritic-sensitive.
 */

import { describe, expect, it } from "vitest";

import {
  type Address,
  VN_PROVINCES,
  formatAddressVN,
  isValidProvince,
} from "../format-address-vn";


// ---------- VN_PROVINCES ----------


describe("VN_PROVINCES", () => {
  it("has exactly 63 entries", () => {
    expect(VN_PROVINCES.size).toBe(63);
  });

  it("includes 5 centrally-administered cities", () => {
    for (const city of ["Hà Nội", "Hồ Chí Minh", "Hải Phòng", "Đà Nẵng", "Cần Thơ"]) {
      expect(VN_PROVINCES.has(city)).toBe(true);
    }
  });

  it("includes major provinces", () => {
    for (const prov of ["An Giang", "Bình Dương", "Đồng Nai", "Khánh Hòa", "Quảng Nam"]) {
      expect(VN_PROVINCES.has(prov)).toBe(true);
    }
  });

  it("excludes invented names", () => {
    expect(VN_PROVINCES.has("Foobar")).toBe(false);
    expect(VN_PROVINCES.has("HCMC")).toBe(false);  // abbreviation
  });

  it("uses bare canonical names (no Tỉnh/Thành phố prefix)", () => {
    // Pin: stored as "Hồ Chí Minh", NOT "Thành phố Hồ Chí Minh".
    expect(VN_PROVINCES.has("Thành phố Hồ Chí Minh")).toBe(false);
    expect(VN_PROVINCES.has("Tỉnh An Giang")).toBe(false);
  });
});


// ---------- formatAddressVN ----------


describe("formatAddressVN — full address", () => {
  it("joins all segments with comma-space", () => {
    const addr: Address = {
      street: "123 Lê Lợi",
      ward: "Phường Bến Nghé",
      district: "Quận 1",
      province: "Hồ Chí Minh",
    };
    expect(formatAddressVN(addr)).toBe(
      "123 Lê Lợi, Phường Bến Nghé, Quận 1, Hồ Chí Minh",
    );
  });
});


describe("formatAddressVN — empty segments", () => {
  it("omits empty street", () => {
    const addr: Address = {
      street: "",
      ward: "Phường Bến Nghé",
      district: "Quận 1",
      province: "Hồ Chí Minh",
    };
    expect(formatAddressVN(addr)).toBe("Phường Bến Nghé, Quận 1, Hồ Chí Minh");
  });

  it("omits multiple empty segments", () => {
    const addr: Address = {
      street: "",
      ward: "",
      district: "Quận 1",
      province: "Hồ Chí Minh",
    };
    expect(formatAddressVN(addr)).toBe("Quận 1, Hồ Chí Minh");
  });

  it("returns empty for all-empty address", () => {
    const addr: Address = { street: "", ward: "", district: "", province: "" };
    expect(formatAddressVN(addr)).toBe("");
  });

  it("returns province-only when other segments empty", () => {
    const addr: Address = {
      street: "",
      ward: "",
      district: "",
      province: "Hà Nội",
    };
    expect(formatAddressVN(addr)).toBe("Hà Nội");
  });

  it("treats whitespace-only segments as empty", () => {
    // Cardinal pin: no `"  ,  Hồ Chí Minh"` artifacts.
    const addr: Address = {
      street: "   ",
      ward: "\t",
      district: "Quận 1",
      province: "Hồ Chí Minh",
    };
    expect(formatAddressVN(addr)).toBe("Quận 1, Hồ Chí Minh");
  });

  it("trims whitespace from non-empty segments", () => {
    const addr: Address = {
      street: "  123 Lê Lợi  ",
      ward: "",
      district: "",
      province: "  Hồ Chí Minh  ",
    };
    expect(formatAddressVN(addr)).toBe("123 Lê Lợi, Hồ Chí Minh");
  });
});


// ---------- isValidProvince ----------


describe("isValidProvince", () => {
  it("returns true for known provinces", () => {
    expect(isValidProvince("Hà Nội")).toBe(true);
    expect(isValidProvince("Hồ Chí Minh")).toBe(true);
  });

  it("returns false for unknown names", () => {
    expect(isValidProvince("Foobar")).toBe(false);
    expect(isValidProvince("HCMC")).toBe(false);
  });

  it("strips boundary whitespace", () => {
    expect(isValidProvince("  Hà Nội  ")).toBe(true);
  });

  it("is case-sensitive", () => {
    // Cardinal pin: VN names are case-sensitive (proper-noun
    // capitalization). "ha noi" doesn't match.
    expect(isValidProvince("ha noi")).toBe(false);
    expect(isValidProvince("HÀ NỘI")).toBe(false);
  });

  it("is diacritic-sensitive", () => {
    // Pin: "Ha Noi" (no diacritics) doesn't match "Hà Nội".
    // Stored canonical form requires exact diacritics.
    expect(isValidProvince("Ha Noi")).toBe(false);
  });

  it("rejects with prefix", () => {
    // Stored as bare name; with prefix doesn't match.
    expect(isValidProvince("Thành phố Hồ Chí Minh")).toBe(false);
    expect(isValidProvince("Tỉnh An Giang")).toBe(false);
  });

  it("returns false for null / undefined / empty", () => {
    expect(isValidProvince(null)).toBe(false);
    expect(isValidProvince(undefined)).toBe(false);
    expect(isValidProvince("")).toBe(false);
    expect(isValidProvince("   ")).toBe(false);
  });
});
