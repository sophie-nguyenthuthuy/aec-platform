/**
 * Vitest coverage for the bulk paste-list tester on the normaliser-
 * rules admin. The behaviour matters because ops uses this panel to
 * decide whether to add a new rule — so a regex-matching bug here
 * silently degrades the rule-coverage workflow.
 *
 * Test buckets:
 *   1. Single-line gating: <2 lines means the panel hides (the
 *      per-rule green-dot in the outer table covers that case).
 *   2. First-match wins (mirrors server-side `_match` semantics).
 *   3. Bad-regex rules are dead — they don't crash, don't match.
 *   4. Orphan inputs surface as the actionable "needs a new rule"
 *      signal.
 *   5. Match counts in the header summary.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { NormalizerRule } from "@/hooks/admin";

import { TesterResults, type Translator } from "../TesterResults";


/**
 * Stub translator: echoes the key plus a JSON dump of the params.
 * Tests assert on rendered values (param counts), not on label
 * wording — the labels can stay synthetic.
 */
const t: Translator = (key, params) => {
  return params ? `${key}:${JSON.stringify(params)}` : key;
};


function rule(overrides: Partial<NormalizerRule> = {}): NormalizerRule {
  // Defaults are the in-code "Concrete C30" rule shape from
  // `services.price_scrapers.normalizer._RULES` — production-realistic
  // so a regression in the matching logic would surface here.
  return {
    id: "rule-1",
    priority: 50,
    pattern: "bê\\s*tông.*c30",
    material_code: "CONC_C30",
    category: "concrete",
    canonical_name: "Concrete C30",
    preferred_units: "m3",
    enabled: true,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}


describe("TesterResults / single-line gating", () => {
  test("empty sample → renders nothing (panel hidden)", () => {
    const { container } = render(<TesterResults sample="" rules={[rule()]} t={t} />);
    expect(container).toBeEmptyDOMElement();
  });

  test("one line → renders nothing (single-line mode handled by outer table)", () => {
    const { container } = render(<TesterResults sample="Bê tông C30" rules={[rule()]} t={t} />);
    expect(container).toBeEmptyDOMElement();
  });

  test("blank lines don't count toward the line count", () => {
    // Three lines but two are blank → effective count is 1 → hide.
    const { container } = render(
      <TesterResults sample="\n  Bê tông C30\n\n" rules={[rule()]} t={t} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});


describe("TesterResults / first-match wins", () => {
  test("first matching rule wins; later-rule with same code is skipped", () => {
    // Two rules whose patterns BOTH match — the panel must pick the
    // first (priority-sorted) one. This is the semantic that lets ops
    // override an in-code rule by inserting a high-priority DB rule.
    const winner = rule({
      id: "rule-1",
      pattern: "bê\\s*tông",
      priority: 1,
      material_code: "OVERRIDE",
      canonical_name: "Concrete (override)",
    });
    const loser = rule({
      id: "rule-2",
      pattern: "c30",
      priority: 2,
      material_code: "CONC_C30",
      canonical_name: "Concrete C30",
    });
    render(
      <TesterResults sample={"Bê tông C30\nGạch đỏ"} rules={[winner, loser]} t={t} />,
    );
    const rows = screen.getAllByTestId("tester-result-row");
    expect(rows[0]!.getAttribute("data-input")).toBe("Bê tông C30");
    expect(rows[0]!.getAttribute("data-winner")).toBe("OVERRIDE");
  });

  test("ranks rules in array order, not by priority field", () => {
    // The component trusts that `rules` is already priority-sorted
    // (server default). It must NOT re-sort by `priority` — otherwise
    // a fresh DB rule with a low number wouldn't beat an in-code
    // rule even when the server places it first.
    const first = rule({ id: "a", pattern: "x", priority: 999, material_code: "A" });
    const second = rule({ id: "b", pattern: "x", priority: 1, material_code: "B" });
    render(
      <TesterResults sample={"x\ny"} rules={[first, second]} t={t} />,
    );
    const rows = screen.getAllByTestId("tester-result-row");
    expect(rows[0]!.getAttribute("data-winner")).toBe("A");
  });
});


describe("TesterResults / bad-regex tolerance", () => {
  test("a rule with an invalid regex doesn't crash and doesn't match", () => {
    const broken = rule({ id: "broken", pattern: "[unclosed-class", material_code: "BAD" });
    const good = rule({ id: "good", pattern: "bê\\s*tông", material_code: "OK" });
    render(
      <TesterResults sample={"Bê tông C30\nKhác"} rules={[broken, good]} t={t} />,
    );
    const rows = screen.getAllByTestId("tester-result-row");
    // Bad-regex rule is silently skipped; the next rule wins.
    expect(rows[0]!.getAttribute("data-winner")).toBe("OK");
  });
});


describe("TesterResults / orphan flag", () => {
  test("inputs with no matching rule render the no-match badge", () => {
    render(
      <TesterResults
        sample={"Bê tông C30\nLao động phổ thông"}
        rules={[rule()]}
        t={t}
      />,
    );
    const orphans = screen.getAllByTestId("tester-result-no-match");
    // Only the second line has no rule — the first matches the
    // default Concrete C30 stub.
    expect(orphans.length).toBe(1);
  });
});


describe("TesterResults / summary counts", () => {
  test("header reports matched + unmatched counts", () => {
    render(
      <TesterResults
        sample={"Bê tông C30\nLao động\nXi măng"}
        rules={[rule()]}
        t={t}
      />,
    );
    // Stub translator emits the JSON params verbatim — easier to
    // assert on than locale-dependent string templates. The header
    // should encode 1 matched, 2 unmatched.
    expect(
      screen.getByText(/results_summary:\{"matched":1,"unmatched":2\}/),
    ).toBeInTheDocument();
  });
});
