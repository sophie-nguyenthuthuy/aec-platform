/**
 * Estimate revision number formatter (cycle BBB2, TS half).
 *
 * Pinned seams:
 *   1. Format: <PREFIX>-<YYYY>-<NNN>[/r<R>].
 *   2. Prefix 2-4 uppercase letters (no digits).
 *   3. Sequence 3-digit zero-padded on output.
 *   4. Sequence range [1, 999], revision [0, 999].
 *   5. Year range [2020, 2099].
 *   6. revision=0 omits /r suffix; revision>=1 includes it.
 *   7. `/r0` on parse → null (canonical form omits).
 *   8. Round-trip stable.
 *   9. Cross-language byte-for-byte parity with Python half.
 */

import { describe, expect, it } from "vitest";

import {
  MAX_REVISION,
  MAX_SEQUENCE,
  MAX_YEAR,
  MIN_YEAR,
  PREFIX_LENGTH_MAX,
  PREFIX_LENGTH_MIN,
  SEQUENCE_LENGTH,
  formatRevisionNumber,
  isValidRevisionNumber,
  nextRevision,
  parseRevisionNumber,
} from "../format-revision";


// ---------- Constants ----------


describe("constants", () => {
  it("pinned values", () => {
    expect(PREFIX_LENGTH_MIN).toBe(2);
    expect(PREFIX_LENGTH_MAX).toBe(4);
    expect(SEQUENCE_LENGTH).toBe(3);
    expect(MAX_SEQUENCE).toBe(999);
    expect(MAX_REVISION).toBe(999);
    expect(MIN_YEAR).toBe(2020);
    expect(MAX_YEAR).toBe(2099);
  });
});


// ---------- parseRevisionNumber ----------


describe("parseRevisionNumber — base form", () => {
  it("parses canonical base", () => {
    expect(parseRevisionNumber("EST-2026-001")).toEqual({
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 0,
    });
  });

  it("parses non-padded sequence", () => {
    expect(parseRevisionNumber("EST-2026-1")).toEqual({
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 0,
    });
  });

  it("parses 4-char prefix", () => {
    expect(parseRevisionNumber("RFII-2026-001")).toEqual({
      prefix: "RFII",
      year: 2026,
      sequence: 1,
      revision: 0,
    });
  });

  it("parses 2-char prefix", () => {
    expect(parseRevisionNumber("CO-2026-001")).toEqual({
      prefix: "CO",
      year: 2026,
      sequence: 1,
      revision: 0,
    });
  });

  it("parses sequence at max", () => {
    expect(parseRevisionNumber("EST-2026-999")).toEqual({
      prefix: "EST",
      year: 2026,
      sequence: 999,
      revision: 0,
    });
  });

  it("strips whitespace", () => {
    expect(parseRevisionNumber("  EST-2026-001  ")).toEqual({
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 0,
    });
  });
});


describe("parseRevisionNumber — revised form", () => {
  it("parses /r2 revision", () => {
    expect(parseRevisionNumber("EST-2026-001/r2")).toEqual({
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 2,
    });
  });

  it("parses /r999 (max revision)", () => {
    expect(parseRevisionNumber("EST-2026-001/r999")).toEqual({
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 999,
    });
  });

  it("rejects /r0 — base form omits suffix", () => {
    // Cardinal pin: `/r0` is not canonical for revision=0.
    expect(parseRevisionNumber("EST-2026-001/r0")).toBeNull();
  });

  it("rejects /r1000 (over max)", () => {
    expect(parseRevisionNumber("EST-2026-001/r1000")).toBeNull();
  });
});


describe("parseRevisionNumber — rejection", () => {
  it("rejects lowercase prefix", () => {
    expect(parseRevisionNumber("est-2026-001")).toBeNull();
  });

  it("rejects prefix with digits", () => {
    expect(parseRevisionNumber("ES1-2026-001")).toBeNull();
  });

  it("rejects 1-char prefix", () => {
    expect(parseRevisionNumber("E-2026-001")).toBeNull();
  });

  it("rejects 5-char prefix", () => {
    expect(parseRevisionNumber("ESTIM-2026-001")).toBeNull();
  });

  it("rejects sequence 0", () => {
    expect(parseRevisionNumber("EST-2026-000")).toBeNull();
    expect(parseRevisionNumber("EST-2026-0")).toBeNull();
  });

  it("rejects 4-digit sequence", () => {
    expect(parseRevisionNumber("EST-2026-1000")).toBeNull();
  });

  it("rejects year before MIN", () => {
    expect(parseRevisionNumber("EST-2019-001")).toBeNull();
  });

  it("rejects year after MAX", () => {
    expect(parseRevisionNumber("EST-2100-001")).toBeNull();
  });

  it("rejects wrong separator", () => {
    expect(parseRevisionNumber("EST_2026_001")).toBeNull();
    expect(parseRevisionNumber("EST.2026.001")).toBeNull();
  });

  it("rejects uppercase R in revision tag", () => {
    expect(parseRevisionNumber("EST-2026-001/R2")).toBeNull();
  });

  it("rejects null / empty", () => {
    expect(parseRevisionNumber(null)).toBeNull();
    expect(parseRevisionNumber(undefined)).toBeNull();
    expect(parseRevisionNumber("")).toBeNull();
    expect(parseRevisionNumber("   ")).toBeNull();
  });

  it("rejects garbage", () => {
    expect(parseRevisionNumber("not-a-revision")).toBeNull();
    expect(parseRevisionNumber("EST")).toBeNull();
  });
});


// ---------- formatRevisionNumber ----------


describe("formatRevisionNumber", () => {
  it("formats base (revision=0)", () => {
    expect(
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 1,
        revision: 0,
      }),
    ).toBe("EST-2026-001");
  });

  it("formats revised", () => {
    expect(
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 1,
        revision: 2,
      }),
    ).toBe("EST-2026-001/r2");
  });

  it("zero-pads sequence to 3 digits", () => {
    expect(
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 7,
        revision: 0,
      }),
    ).toBe("EST-2026-007");
  });

  it("does NOT zero-pad revision", () => {
    // Pin: revision is single-digit / non-padded; padding it
    // would diverge from VN AEC convention.
    expect(
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 1,
        revision: 2,
      }),
    ).toBe("EST-2026-001/r2");
    expect(
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 1,
        revision: 12,
      }),
    ).toBe("EST-2026-001/r12");
  });

  it("throws on invalid prefix", () => {
    expect(() =>
      formatRevisionNumber({
        prefix: "est",
        year: 2026,
        sequence: 1,
        revision: 0,
      }),
    ).toThrow(RangeError);
  });

  it("throws on year out of range", () => {
    expect(() =>
      formatRevisionNumber({
        prefix: "EST",
        year: 1999,
        sequence: 1,
        revision: 0,
      }),
    ).toThrow(RangeError);
  });

  it("throws on sequence 0", () => {
    expect(() =>
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 0,
        revision: 0,
      }),
    ).toThrow(RangeError);
  });

  it("throws on revision over max", () => {
    expect(() =>
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 1,
        revision: 1000,
      }),
    ).toThrow(RangeError);
  });
});


// ---------- isValidRevisionNumber ----------


describe("isValidRevisionNumber", () => {
  it("true for canonical", () => {
    expect(isValidRevisionNumber("EST-2026-001")).toBe(true);
    expect(isValidRevisionNumber("EST-2026-001/r2")).toBe(true);
  });

  it("false for invalid", () => {
    expect(isValidRevisionNumber(null)).toBe(false);
    expect(isValidRevisionNumber("")).toBe(false);
    expect(isValidRevisionNumber("invalid")).toBe(false);
    expect(isValidRevisionNumber("EST-2026-000")).toBe(false);
  });
});


// ---------- Round-trip ----------


describe("round-trip", () => {
  it("parse → format canonical", () => {
    const canonical = "EST-2026-001";
    const parsed = parseRevisionNumber(canonical);
    expect(parsed).not.toBeNull();
    expect(formatRevisionNumber(parsed!)).toBe(canonical);
  });

  it("parse → format revised", () => {
    const canonical = "EST-2026-042/r3";
    const parsed = parseRevisionNumber(canonical);
    expect(parsed).not.toBeNull();
    expect(formatRevisionNumber(parsed!)).toBe(canonical);
  });

  it("canonicalizes non-padded sequence", () => {
    const parsed = parseRevisionNumber("EST-2026-1");
    expect(parsed).not.toBeNull();
    expect(formatRevisionNumber(parsed!)).toBe("EST-2026-001");
  });
});


// ---------- nextRevision ----------


describe("nextRevision", () => {
  it("0 → 1", () => {
    const base = {
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 0,
    } as const;
    expect(nextRevision(base).revision).toBe(1);
  });

  it("2 → 3", () => {
    const r2 = {
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: 2,
    } as const;
    expect(nextRevision(r2).revision).toBe(3);
  });

  it("preserves other fields", () => {
    const r = {
      prefix: "EST",
      year: 2026,
      sequence: 42,
      revision: 0,
    } as const;
    const next = nextRevision(r);
    expect(next.prefix).toBe("EST");
    expect(next.year).toBe(2026);
    expect(next.sequence).toBe(42);
  });

  it("throws at MAX_REVISION", () => {
    const max = {
      prefix: "EST",
      year: 2026,
      sequence: 1,
      revision: MAX_REVISION,
    } as const;
    expect(() => nextRevision(max)).toThrow(RangeError);
  });
});


// ---------- Realistic ----------


describe("realistic AEC scenarios", () => {
  it("initial bid estimate", () => {
    expect(
      formatRevisionNumber({
        prefix: "EST",
        year: 2026,
        sequence: 1,
        revision: 0,
      }),
    ).toBe("EST-2026-001");
  });

  it("change order revised after clarification", () => {
    expect(
      formatRevisionNumber({
        prefix: "CO",
        year: 2026,
        sequence: 12,
        revision: 1,
      }),
    ).toBe("CO-2026-012/r1");
  });

  it("RFI in 4-char prefix form", () => {
    expect(
      formatRevisionNumber({
        prefix: "RFII",
        year: 2026,
        sequence: 7,
        revision: 0,
      }),
    ).toBe("RFII-2026-007");
  });
});
