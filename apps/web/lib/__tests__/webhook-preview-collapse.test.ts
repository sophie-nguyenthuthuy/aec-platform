/**
 * Wildcard-aware preview collapse helper (cycle V2).
 *
 * Pinned seams:
 *   1. `isWildcardPattern` matches the backend schema validator's
 *      rule (must end `.*`, non-empty prefix, no embedded `*`).
 *   2. `buildPreviewCards` produces literal cards for literal
 *      selections and collapsed cards for wildcards, expanding
 *      the wildcard against the catalog.
 *   3. Literal selections not in the catalog still produce a card
 *      (graceful degrade — empty description + payload_sample).
 *   4. Selection order is preserved.
 */

import { describe, expect, it } from "vitest";

import {
  buildPreviewCards,
  isWildcardPattern,
  type CatalogEntry,
} from "../webhook-preview-collapse";


const CATALOG: CatalogEntry[] = [
  {
    event_type: "costpulse.estimate.approve",
    description: "Estimate approved.",
    payload_sample: { estimate_id: "<uuid>" },
  },
  {
    event_type: "costpulse.boq.import",
    description: "BOQ import landed.",
    payload_sample: { row_count: 47 },
  },
  {
    event_type: "pulse.change_order.approve",
    description: "Change order approved.",
    payload_sample: { change_order_id: "<uuid>" },
  },
];


describe("isWildcardPattern", () => {
  it("matches single-segment wildcards", () => {
    expect(isWildcardPattern("costpulse.*")).toBe(true);
  });

  it("matches multi-segment wildcards", () => {
    expect(isWildcardPattern("costpulse.estimate.*")).toBe(true);
  });

  it("rejects bare asterisk", () => {
    expect(isWildcardPattern("*")).toBe(false);
  });

  it("rejects entries without a trailing `.*`", () => {
    expect(isWildcardPattern("costpulse.estimate.approve")).toBe(false);
    expect(isWildcardPattern("costpulse")).toBe(false);
  });

  it("rejects embedded asterisk", () => {
    // `costpulse.*.approve` is invalid per the backend rule (no
    // mid-segment wildcards).
    expect(isWildcardPattern("costpulse.*.approve")).toBe(false);
  });
});


describe("buildPreviewCards", () => {
  it("produces a literal card per known literal", () => {
    const cards = buildPreviewCards(
      ["costpulse.estimate.approve"],
      CATALOG,
    );
    expect(cards).toHaveLength(1);
    expect(cards[0]).toMatchObject({
      kind: "literal",
      event_type: "costpulse.estimate.approve",
      description: "Estimate approved.",
    });
  });

  it("produces a literal card with empty meta for unknown literal", () => {
    // Catalog drift / typo defense — UI renders "(pending)" via
    // empty description rather than crashing.
    const cards = buildPreviewCards(["unknown.event.type"], CATALOG);
    expect(cards).toHaveLength(1);
    const c = cards[0];
    expect(c.kind).toBe("literal");
    if (c.kind === "literal") {
      expect(c.description).toBe("");
      expect(c.payload_sample).toEqual({});
    }
  });

  it("collapses a `<module>.*` wildcard with the matching events", () => {
    const cards = buildPreviewCards(["costpulse.*"], CATALOG);
    expect(cards).toHaveLength(1);
    const c = cards[0];
    expect(c.kind).toBe("wildcard");
    if (c.kind === "wildcard") {
      expect(c.pattern).toBe("costpulse.*");
      expect(c.prefix).toBe("costpulse");
      // Both costpulse.* events match; pulse.* does NOT.
      const matchedTypes = c.matched_events.map((e) => e.event_type);
      expect(matchedTypes).toEqual([
        "costpulse.estimate.approve",
        "costpulse.boq.import",
      ]);
    }
  });

  it("expands a multi-segment wildcard correctly", () => {
    // `costpulse.estimate.*` matches `costpulse.estimate.approve` but
    // NOT `costpulse.boq.import` — the prefix-with-trailing-dot check
    // is what enforces the depth.
    const cards = buildPreviewCards(["costpulse.estimate.*"], CATALOG);
    const c = cards[0];
    expect(c.kind).toBe("wildcard");
    if (c.kind === "wildcard") {
      const matchedTypes = c.matched_events.map((e) => e.event_type);
      expect(matchedTypes).toEqual(["costpulse.estimate.approve"]);
    }
  });

  it("preserves selection order across mixed literal + wildcard", () => {
    const cards = buildPreviewCards(
      ["pulse.change_order.approve", "costpulse.*", "costpulse.estimate.approve"],
      CATALOG,
    );
    expect(cards).toHaveLength(3);
    expect(cards[0].kind).toBe("literal");
    expect(cards[1].kind).toBe("wildcard");
    expect(cards[2].kind).toBe("literal");
  });

  it("returns an empty wildcard when the catalog has no matches", () => {
    // Subscription to a wildcard for a module that has no events
    // yet — the partner sees an empty card. UI can render
    // "no events match this prefix yet" inline.
    const cards = buildPreviewCards(["unknownmodule.*"], CATALOG);
    expect(cards).toHaveLength(1);
    const c = cards[0];
    expect(c.kind).toBe("wildcard");
    if (c.kind === "wildcard") {
      expect(c.matched_events).toEqual([]);
    }
  });
});
