/**
 * Geographic coordinate parser/formatter (cycle TT1).
 *
 * Pinned seams:
 *   1. Lat ∈ [-90, 90]; lng ∈ [-180, 180].
 *   2. Decimal degrees + DMS both parsed.
 *   3. DMS hemispheres flip sign.
 *   4. 6 decimals default on format.
 *   5. Out of range → null/"".
 *   6. VN_LAT_BAND ≈ (8.0, 24.0); VN_LNG_BAND ≈ (102.0, 110.0).
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_DECIMALS,
  LAT_MAX,
  LAT_MIN,
  LNG_MAX,
  LNG_MIN,
  VN_LAT_BAND,
  VN_LNG_BAND,
  formatLatLng,
  isInVietnam,
  parseLatLng,
} from "../format-geo";


// ---------- Constants ----------


describe("constants", () => {
  it("LAT_MIN/MAX = -90/90", () => {
    expect(LAT_MIN).toBe(-90);
    expect(LAT_MAX).toBe(90);
  });

  it("LNG_MIN/MAX = -180/180", () => {
    expect(LNG_MIN).toBe(-180);
    expect(LNG_MAX).toBe(180);
  });

  it("DEFAULT_DECIMALS = 6 (~0.1m precision)", () => {
    expect(DEFAULT_DECIMALS).toBe(6);
  });

  it("VN_LAT_BAND ≈ [8.0, 24.0]", () => {
    expect(VN_LAT_BAND).toEqual([8.0, 24.0]);
  });

  it("VN_LNG_BAND ≈ [102.0, 110.0]", () => {
    expect(VN_LNG_BAND).toEqual([102.0, 110.0]);
  });
});


// ---------- parseLatLng — decimal degrees ----------


describe("parseLatLng — decimal degrees", () => {
  it("comma-space separated", () => {
    expect(parseLatLng("21.0285, 105.8542")).toEqual([21.0285, 105.8542]);
  });

  it("comma-only separated", () => {
    expect(parseLatLng("21.0285,105.8542")).toEqual([21.0285, 105.8542]);
  });

  it("space-only separated", () => {
    expect(parseLatLng("21.0285 105.8542")).toEqual([21.0285, 105.8542]);
  });

  it("negative coordinates", () => {
    expect(parseLatLng("-21.0285, -105.8542")).toEqual([-21.0285, -105.8542]);
  });

  it("explicit positive sign", () => {
    expect(parseLatLng("+21.0, +105.0")).toEqual([21.0, 105.0]);
  });

  it("integer coordinates", () => {
    expect(parseLatLng("0, 0")).toEqual([0, 0]);
  });

  it("boundary lat", () => {
    expect(parseLatLng("90, 0")).toEqual([90, 0]);
    expect(parseLatLng("-90, 0")).toEqual([-90, 0]);
  });

  it("boundary lng", () => {
    expect(parseLatLng("0, 180")).toEqual([0, 180]);
    expect(parseLatLng("0, -180")).toEqual([0, -180]);
  });
});


// ---------- parseLatLng — DMS ----------


describe("parseLatLng — DMS", () => {
  it("parses canonical DMS", () => {
    const result = parseLatLng("21°01'42.6\"N 105°51'15.1\"E");
    expect(result).not.toBeNull();
    expect(result![0]).toBeCloseTo(21.0285, 3);
    expect(result![1]).toBeCloseTo(105.8542, 3);
  });

  it("south hemisphere flips lat sign", () => {
    const result = parseLatLng("21°01'42.6\"S 105°51'15.1\"E");
    expect(result![0]).toBeCloseTo(-21.0285, 3);
  });

  it("west hemisphere flips lng sign", () => {
    const result = parseLatLng("21°01'42.6\"N 105°51'15.1\"W");
    expect(result![1]).toBeCloseTo(-105.8542, 3);
  });

  it("DMS lng-first ordering still works", () => {
    // Hemisphere letter determines lat vs lng, NOT position order.
    const result = parseLatLng("105°51'15.1\"E 21°01'42.6\"N");
    expect(result![0]).toBeCloseTo(21.0285, 3);
    expect(result![1]).toBeCloseTo(105.8542, 3);
  });
});


// ---------- parseLatLng — invalid ----------


describe("parseLatLng — invalid", () => {
  it("lat out of range → null", () => {
    expect(parseLatLng("91, 0")).toBeNull();
    expect(parseLatLng("-91, 0")).toBeNull();
  });

  it("lng out of range → null", () => {
    expect(parseLatLng("0, 181")).toBeNull();
    expect(parseLatLng("0, -181")).toBeNull();
  });

  it("non-numeric → null", () => {
    expect(parseLatLng("not-coords")).toBeNull();
    expect(parseLatLng("21.0285")).toBeNull();  // single value
  });

  it("null/empty → null", () => {
    expect(parseLatLng(null)).toBeNull();
    expect(parseLatLng(undefined)).toBeNull();
    expect(parseLatLng("")).toBeNull();
    expect(parseLatLng("   ")).toBeNull();
  });
});


// ---------- formatLatLng ----------


describe("formatLatLng", () => {
  it("formats with default 6 decimals", () => {
    expect(formatLatLng(21.0285, 105.8542)).toBe("21.028500, 105.854200");
  });

  it("custom decimals", () => {
    expect(formatLatLng(21.0285, 105.8542, 4)).toBe("21.0285, 105.8542");
  });

  it("zero decimals", () => {
    expect(formatLatLng(21.5, 105.5, 0)).toBe("22, 106");
  });

  it("integer coordinates with default decimals", () => {
    expect(formatLatLng(0, 0)).toBe("0.000000, 0.000000");
  });

  it("negative coordinates", () => {
    expect(formatLatLng(-21.0285, -105.8542, 4)).toBe("-21.0285, -105.8542");
  });

  it("out of range → empty", () => {
    expect(formatLatLng(91, 0)).toBe("");
    expect(formatLatLng(0, 181)).toBe("");
  });

  it("NaN → empty", () => {
    expect(formatLatLng(Number.NaN, 0)).toBe("");
    expect(formatLatLng(0, Number.NaN)).toBe("");
  });

  it("negative decimals → empty", () => {
    expect(formatLatLng(0, 0, -1)).toBe("");
  });
});


// ---------- isInVietnam ----------


describe("isInVietnam", () => {
  it("true for Hanoi", () => {
    // Hanoi: ~21.0285°N, 105.8542°E
    expect(isInVietnam(21.0285, 105.8542)).toBe(true);
  });

  it("true for Hồ Chí Minh", () => {
    // ~10.7626°N, 106.6602°E
    expect(isInVietnam(10.7626, 106.6602)).toBe(true);
  });

  it("true for Đà Nẵng", () => {
    // ~16.0544°N, 108.2022°E
    expect(isInVietnam(16.0544, 108.2022)).toBe(true);
  });

  it("false for NYC", () => {
    expect(isInVietnam(40.7128, -74.0060)).toBe(false);
  });

  it("false for Tokyo", () => {
    expect(isInVietnam(35.6762, 139.6503)).toBe(false);
  });

  it("false for swapped lat/lng (defensive)", () => {
    // Hanoi swapped: 105.8542°N (out of range, fails validation).
    expect(isInVietnam(105.8542, 21.0285)).toBe(false);
  });

  it("false for invalid coordinates", () => {
    expect(isInVietnam(Number.NaN, 100)).toBe(false);
    expect(isInVietnam(91, 100)).toBe(false);
  });
});


// ---------- Round-trip ----------


describe("round-trip parse → format", () => {
  it("preserves Hanoi", () => {
    const parsed = parseLatLng("21.028500, 105.854200");
    expect(parsed).not.toBeNull();
    expect(formatLatLng(parsed![0], parsed![1])).toBe("21.028500, 105.854200");
  });
});
