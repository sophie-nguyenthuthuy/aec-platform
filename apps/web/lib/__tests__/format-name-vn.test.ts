/**
 * Vietnamese name formatter (cycle QQ2).
 *
 * Pinned seams:
 *   1. Default "full" follows VN convention: family-first.
 *   2. "western" reverses to "given family" (middle dropped).
 *   3. "initials" includes all three parts.
 *   4. Empty middle gracefully omitted.
 *   5. Whitespace trimmed.
 *   6. Empty family → "".
 */

import { describe, expect, it } from "vitest";

import { type VietnameseName, formatNameVN } from "../format-name-vn";


function _name(
  overrides: Partial<VietnameseName> & { family: string },
): VietnameseName {
  return {
    middle: "",
    given: "",
    ...overrides,
  };
}


// ---------- Default (full) format ----------


describe("formatNameVN — full (default)", () => {
  it("follows VN convention: family first", () => {
    const name = _name({ family: "Nguyễn", middle: "Văn", given: "Anh" });
    expect(formatNameVN(name)).toBe("Nguyễn Văn Anh");
    expect(formatNameVN(name, "full")).toBe("Nguyễn Văn Anh");
  });

  it("omits empty middle", () => {
    const name = _name({ family: "Trần", given: "Linh" });
    expect(formatNameVN(name, "full")).toBe("Trần Linh");
  });

  it("omits empty given", () => {
    const name = _name({ family: "Phạm", middle: "Văn" });
    expect(formatNameVN(name, "full")).toBe("Phạm Văn");
  });

  it("family-only", () => {
    expect(formatNameVN(_name({ family: "Lê" }), "full")).toBe("Lê");
  });

  it("preserves multi-word middle", () => {
    const name = _name({
      family: "Phạm",
      middle: "Thị Thu",
      given: "Hương",
    });
    expect(formatNameVN(name, "full")).toBe("Phạm Thị Thu Hương");
  });
});


// ---------- Given format ----------


describe("formatNameVN — given", () => {
  it("returns given name only", () => {
    const name = _name({ family: "Nguyễn", middle: "Văn", given: "Anh" });
    expect(formatNameVN(name, "given")).toBe("Anh");
  });

  it("returns empty when given is empty", () => {
    const name = _name({ family: "Nguyễn", middle: "Văn" });
    expect(formatNameVN(name, "given")).toBe("");
  });
});


// ---------- Western format ----------


describe("formatNameVN — western", () => {
  it("reverses to given-then-family", () => {
    const name = _name({ family: "Nguyễn", middle: "Văn", given: "Anh" });
    expect(formatNameVN(name, "western")).toBe("Anh Nguyễn");
  });

  it("drops middle in Western format", () => {
    // Western convention often omits middle in casual contexts.
    const name = _name({
      family: "Phạm",
      middle: "Thị Thu",
      given: "Hương",
    });
    expect(formatNameVN(name, "western")).toBe("Hương Phạm");
  });

  it("falls back to family when given is empty", () => {
    expect(formatNameVN(_name({ family: "Lê" }), "western")).toBe("Lê");
  });
});


// ---------- Initials format ----------


describe("formatNameVN — initials", () => {
  it("includes all three parts", () => {
    const name = _name({ family: "Nguyễn", middle: "Văn", given: "Anh" });
    expect(formatNameVN(name, "initials")).toBe("NVA");
  });

  it("multi-word middle yields multi initial", () => {
    const name = _name({
      family: "Phạm",
      middle: "Thị Thu",
      given: "Hương",
    });
    expect(formatNameVN(name, "initials")).toBe("PTTH");
  });

  it("omits empty middle", () => {
    const name = _name({ family: "Trần", given: "Linh" });
    expect(formatNameVN(name, "initials")).toBe("TL");
  });

  it("uppercases initials", () => {
    const name = _name({ family: "nguyễn", given: "anh" });
    expect(formatNameVN(name, "initials")).toBe("NA");
  });
});


// ---------- Whitespace ----------


describe("formatNameVN — whitespace", () => {
  it("trims segment whitespace", () => {
    const name = _name({
      family: "  Nguyễn  ",
      middle: "  Văn  ",
      given: "  Anh  ",
    });
    expect(formatNameVN(name, "full")).toBe("Nguyễn Văn Anh");
  });

  it("treats whitespace-only middle as empty", () => {
    const name = _name({ family: "Trần", middle: "   ", given: "Linh" });
    expect(formatNameVN(name, "full")).toBe("Trần Linh");
  });
});


// ---------- Empty family ----------


describe("formatNameVN — empty family", () => {
  it("returns empty for full when family missing", () => {
    // Cardinal pin: family is required. Without it, we don't
    // know whether to render Western-first or VN-first.
    const name: VietnameseName = { family: "", middle: "Văn", given: "Anh" };
    expect(formatNameVN(name, "full")).toBe("");
  });

  it("returns empty for all formats when family missing", () => {
    const name: VietnameseName = { family: "", middle: "", given: "Anh" };
    expect(formatNameVN(name, "full")).toBe("");
    expect(formatNameVN(name, "given")).toBe("");
    expect(formatNameVN(name, "western")).toBe("");
    expect(formatNameVN(name, "initials")).toBe("");
  });

  it("whitespace-only family treated as empty", () => {
    const name: VietnameseName = { family: "   ", middle: "", given: "Anh" };
    expect(formatNameVN(name, "full")).toBe("");
  });
});
