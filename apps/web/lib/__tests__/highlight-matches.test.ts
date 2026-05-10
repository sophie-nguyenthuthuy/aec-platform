/**
 * Audit search highlighter (cycle WW1).
 *
 * Pinned seams:
 *   1. Case-insensitive matching.
 *   2. Non-overlapping (greedy, longer-on-tie wins).
 *   3. Empty / null text → [].
 *   4. Empty terms → [].
 *   5. Whitespace-only term skipped.
 *   6. Indexes refer to original (NOT lowercased) text.
 */

import { describe, expect, it } from "vitest";

import { type Match, findMatches } from "../highlight-matches";


// ---------- Empty inputs ----------


describe("findMatches — empty", () => {
  it("null text → []", () => {
    expect(findMatches(null, ["foo"])).toEqual([]);
  });

  it("undefined text → []", () => {
    expect(findMatches(undefined, ["foo"])).toEqual([]);
  });

  it("empty text → []", () => {
    expect(findMatches("", ["foo"])).toEqual([]);
  });

  it("empty terms → []", () => {
    expect(findMatches("hello world", [])).toEqual([]);
  });
});


// ---------- Single match ----------


describe("findMatches — single match", () => {
  it("matches at start", () => {
    expect(findMatches("hello world", ["hello"])).toEqual([
      { start: 0, end: 5 },
    ]);
  });

  it("matches at end", () => {
    expect(findMatches("hello world", ["world"])).toEqual([
      { start: 6, end: 11 },
    ]);
  });

  it("matches in middle", () => {
    expect(findMatches("hello world foo", ["world"])).toEqual([
      { start: 6, end: 11 },
    ]);
  });

  it("no match → []", () => {
    expect(findMatches("hello world", ["xyz"])).toEqual([]);
  });
});


// ---------- Multiple matches ----------


describe("findMatches — multiple matches", () => {
  it("multiple terms in document order", () => {
    expect(findMatches("hello world", ["hello", "world"])).toEqual([
      { start: 0, end: 5 },
      { start: 6, end: 11 },
    ]);
  });

  it("repeated occurrences of same term", () => {
    expect(findMatches("foo bar foo baz foo", ["foo"])).toEqual([
      { start: 0, end: 3 },
      { start: 8, end: 11 },
      { start: 16, end: 19 },
    ]);
  });

  it("multiple terms in mixed order", () => {
    // Terms in arbitrary order; matches in document order.
    expect(findMatches("alpha beta gamma", ["gamma", "alpha"])).toEqual([
      { start: 0, end: 5 },
      { start: 11, end: 16 },
    ]);
  });
});


// ---------- Case insensitivity ----------


describe("findMatches — case insensitive", () => {
  it("uppercase term matches lowercase text", () => {
    expect(findMatches("hello world", ["HELLO"])).toEqual([
      { start: 0, end: 5 },
    ]);
  });

  it("mixed-case term matches", () => {
    expect(findMatches("Hello World", ["hello"])).toEqual([
      { start: 0, end: 5 },
    ]);
  });

  it("indexes refer to ORIGINAL text", () => {
    // Pin: start/end are positions in the ORIGINAL `text`,
    // NOT the lowercased version. Caller can slice directly.
    const matches = findMatches("Hello World", ["hello"]);
    expect("Hello World".slice(matches[0]!.start, matches[0]!.end)).toBe("Hello");
  });
});


// ---------- Overlap resolution ----------


describe("findMatches — overlap resolution", () => {
  it("longer-on-tie wins at same start", () => {
    // Terms: "ell" (3 chars) and "hello" (5 chars). Both start
    // candidates at 0/1. Greedy chooses "hello" first (longer).
    expect(findMatches("hello", ["hello", "ell"])).toEqual([
      { start: 0, end: 5 },
    ]);
  });

  it("non-overlapping repeated matches", () => {
    // "aaaa" with term "aa" → candidates (0,2), (1,3), (2,4).
    // Greedy: (0,2) selected, (1,3) skipped, (2,4) selected.
    expect(findMatches("aaaa", ["aa"])).toEqual([
      { start: 0, end: 2 },
      { start: 2, end: 4 },
    ]);
  });

  it("greedy left-to-right earlier wins", () => {
    // "abcabc" with terms "abc" and "bca". Earlier (abc at 0)
    // wins; "bca" at 1..4 overlaps (1 < 3) → skipped. Then
    // "abc" at 3..6 picked.
    expect(findMatches("abcabc", ["abc", "bca"])).toEqual([
      { start: 0, end: 3 },
      { start: 3, end: 6 },
    ]);
  });
});


// ---------- Whitespace + edge cases ----------


describe("findMatches — edge cases", () => {
  it("whitespace-only term skipped", () => {
    expect(findMatches("hello world", ["   "])).toEqual([]);
  });

  it("empty string in terms list skipped", () => {
    expect(findMatches("hello", ["", "hello"])).toEqual([
      { start: 0, end: 5 },
    ]);
  });

  it("terms trimmed", () => {
    expect(findMatches("hello", ["  hello  "])).toEqual([
      { start: 0, end: 5 },
    ]);
  });

  it("unicode text + ascii term", () => {
    // Vietnamese text matched by ASCII term.
    expect(findMatches("Hà Nội Construction", ["construction"])).toEqual([
      { start: 7, end: 19 },
    ]);
  });

  it("unicode term", () => {
    // Vietnamese term matches Vietnamese text.
    const result = findMatches("123 Lê Lợi, Quận 1", ["Lê Lợi"]);
    expect(result.length).toBe(1);
    expect(result[0]!.start).toBe(4);
  });
});


// ---------- Realistic ----------


describe("findMatches — realistic", () => {
  it("audit note with multiple search terms", () => {
    const note = "Approved change order CO-2026-042 by Nguyễn";
    const matches = findMatches(note, ["change", "approved"]);
    expect(matches.length).toBe(2);
    // Document order: "Approved" (0), "change" (9).
    expect(matches[0]!.start).toBe(0);
    expect(matches[1]!.start).toBe(9);
  });
});
