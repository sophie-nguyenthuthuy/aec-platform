/**
 * Enum coalescer (cycle RR1).
 *
 * Pinned seams:
 *   1. Exact match preferred over case-insensitive.
 *   2. Case-insensitive fallback.
 *   3. Whitespace stripped.
 *   4. null / empty / no-match → defaultValue.
 *   5. Empty choices → defaultValue.
 *   6. First match wins.
 */

import { describe, expect, it } from "vitest";

import { coalesceEnum } from "../coalesce-enum";


// ---------- Exact match ----------


describe("coalesceEnum — exact match", () => {
  it("matches exact canonical", () => {
    expect(coalesceEnum("open", ["open", "closed"])).toBe("open");
  });

  it("preserves canonical case on exact match", () => {
    // Pin: when both `Open` and `OPEN` are in choices, exact
    // case match wins.
    expect(coalesceEnum("Open", ["Open", "OPEN"])).toBe("Open");
    expect(coalesceEnum("OPEN", ["Open", "OPEN"])).toBe("OPEN");
  });
});


// ---------- Case-insensitive ----------


describe("coalesceEnum — case-insensitive", () => {
  it("matches different case", () => {
    expect(coalesceEnum("OPEN", ["open", "closed"])).toBe("open");
    expect(coalesceEnum("Open", ["open", "closed"])).toBe("open");
  });

  it("returns canonical (NOT input) on case-insensitive match", () => {
    // Pin: result is from `choices`, not the user's input case.
    expect(coalesceEnum("oPeN", ["open"])).toBe("open");
  });

  it("first match wins when multiple choices match case-insensitively", () => {
    // Edge case: two choices that lowercase to the same value.
    // First in input order wins.
    expect(coalesceEnum("foo", ["FOO", "Foo"])).toBe("FOO");
  });
});


// ---------- Whitespace ----------


describe("coalesceEnum — whitespace", () => {
  it("strips boundary whitespace from input", () => {
    expect(coalesceEnum("  open  ", ["open"])).toBe("open");
    expect(coalesceEnum("\topen\n", ["open"])).toBe("open");
  });

  it("strips whitespace from choices for matching", () => {
    expect(coalesceEnum("open", [" open "])).toBe(" open ");
  });
});


// ---------- Defaults / empty ----------


describe("coalesceEnum — defaults", () => {
  it("returns null by default for no match", () => {
    expect(coalesceEnum("nope", ["open", "closed"])).toBeNull();
  });

  it("returns custom default for no match", () => {
    expect(coalesceEnum("nope", ["open"], "fallback")).toBe("fallback");
  });

  it("returns default for null input", () => {
    expect(coalesceEnum(null, ["open"], "x")).toBe("x");
  });

  it("returns default for undefined input", () => {
    expect(coalesceEnum(undefined, ["open"], "x")).toBe("x");
  });

  it("returns default for empty input", () => {
    expect(coalesceEnum("", ["open"], "x")).toBe("x");
    expect(coalesceEnum("   ", ["open"], "x")).toBe("x");
  });

  it("returns default for empty choices", () => {
    expect(coalesceEnum("open", [], "x")).toBe("x");
  });
});


// ---------- Realistic shapes ----------


describe("coalesceEnum — realistic", () => {
  it("works with status filter chips", () => {
    const STATUSES = ["open", "in_progress", "resolved", "closed"] as const;
    expect(coalesceEnum("In_Progress", STATUSES)).toBe("in_progress");
    expect(coalesceEnum("RESOLVED", STATUSES)).toBe("resolved");
    expect(coalesceEnum("invalid", STATUSES)).toBeNull();
  });

  it("works with role lookup", () => {
    const ROLES = ["owner", "admin", "member", "viewer"] as const;
    expect(coalesceEnum("Admin", ROLES)).toBe("admin");
    expect(coalesceEnum("OWNER", ROLES)).toBe("owner");
  });
});
