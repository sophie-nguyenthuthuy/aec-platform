/**
 * File size formatter (cycle DD3, TS half).
 *
 * Pinned seams:
 *   1. BYTE_UNITS = [B, KB, MB, GB, TB] (closed, order matters).
 *   2. SI base 1000 (NOT 1024).
 *   3. Bytes < 1000 render as "N B" with no decimal.
 *   4. KB+ render with 2 decimals.
 *   5. vi locale uses comma decimal; en locale uses dot.
 *   6. TB is the cap (8 PB → "8000,00 TB", not "8 PB").
 *   7. null / undefined / NaN / Infinity / negative → "".
 */

import { describe, expect, it } from "vitest";

import { BYTE_UNITS, formatBytes } from "../format-bytes";


// ---------- Constants ----------


describe("BYTE_UNITS", () => {
  it("is the canonical 5-unit closed list in ascending order", () => {
    expect(BYTE_UNITS).toEqual(["B", "KB", "MB", "GB", "TB"]);
  });

  it("uses SI symbols (NOT binary IEC like KiB)", () => {
    // Pin: a refactor that swaps to ["B", "KiB", "MiB", ...] would
    // imply a base-1024 promotion threshold. AEC file managers
    // (macOS / Windows / Linux) all use SI base 1000 by default.
    expect(BYTE_UNITS).not.toContain("KiB");
    expect(BYTE_UNITS).not.toContain("MiB");
  });
});


// ---------- Bytes < 1000 ----------


describe("formatBytes — bytes range (no decimals)", () => {
  it("formats 0 B", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  it("formats sub-kilobyte values without decimals", () => {
    expect(formatBytes(1)).toBe("1 B");
    expect(formatBytes(99)).toBe("99 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(999)).toBe("999 B");
  });

  it("floors fractional sub-kilobyte input", () => {
    // Bytes are atomic — fractional input from a calculation
    // should floor (not round) since you can't have 999.9 bytes.
    expect(formatBytes(999.9)).toBe("999 B");
  });
});


// ---------- KB / MB / GB / TB promotion ----------


describe("formatBytes — promotion thresholds", () => {
  it("promotes to KB at 1000 (SI base)", () => {
    // Pin SI base: 1000 → KB, NOT 1024.
    expect(formatBytes(1000)).toBe("1,00 KB");
    // 1024 is NOT special — formats as ~1.02 KB.
    expect(formatBytes(1024)).toBe("1,02 KB");
  });

  it("formats KB with 2 decimals (vi default)", () => {
    expect(formatBytes(1234)).toBe("1,23 KB");
    expect(formatBytes(1500)).toBe("1,50 KB");
  });

  it("promotes to MB at 1_000_000", () => {
    expect(formatBytes(1_000_000)).toBe("1,00 MB");
    expect(formatBytes(1_234_567)).toBe("1,23 MB");
  });

  it("promotes to GB at 1_000_000_000", () => {
    expect(formatBytes(1_000_000_000)).toBe("1,00 GB");
    expect(formatBytes(1_234_567_890)).toBe("1,23 GB");
  });

  it("promotes to TB at 1_000_000_000_000", () => {
    expect(formatBytes(1_000_000_000_000)).toBe("1,00 TB");
    expect(formatBytes(1_234_567_890_123)).toBe("1,23 TB");
  });

  it("caps at TB even for PB-scale input", () => {
    // 8 PB = 8000 TB. Pin: don't promote to PB — surface the
    // "this is unusually huge" signal via a 4-digit TB number.
    expect(formatBytes(8e15)).toBe("8000,00 TB");
  });
});


// ---------- Locale ----------


describe("formatBytes — locale", () => {
  it("defaults to 'vi' with comma decimal", () => {
    expect(formatBytes(1500)).toBe("1,50 KB");
  });

  it("'en' locale uses dot decimal", () => {
    expect(formatBytes(1500, "en")).toBe("1.50 KB");
    expect(formatBytes(1_234_567_890, "en")).toBe("1.23 GB");
  });

  it("locale only affects the decimal separator (not units)", () => {
    // Units are SI symbols regardless of locale.
    expect(formatBytes(1500, "vi")).toMatch(/KB$/);
    expect(formatBytes(1500, "en")).toMatch(/KB$/);
  });
});


// ---------- Defensive ----------


describe("formatBytes — defensive", () => {
  it("returns '' for null / undefined", () => {
    expect(formatBytes(null)).toBe("");
    expect(formatBytes(undefined)).toBe("");
  });

  it("returns '' for NaN / Infinity", () => {
    expect(formatBytes(Number.NaN)).toBe("");
    expect(formatBytes(Number.POSITIVE_INFINITY)).toBe("");
    expect(formatBytes(Number.NEGATIVE_INFINITY)).toBe("");
  });

  it("returns '' for negative bytes (data bug)", () => {
    // Negative bytes is a calculation bug upstream — pin '' so
    // the row renders empty rather than displaying "-512 B".
    expect(formatBytes(-1)).toBe("");
    expect(formatBytes(-1000)).toBe("");
  });
});
