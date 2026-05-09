import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { FindingItem } from "../FindingItem";
import type { Citation, Finding } from "../types";

/**
 * FindingItem is the row that renders one CodeGuard scan result. The
 * file maps `finding.status` and `finding.severity` to two parallel
 * style tables — both are tone-critical (a FAIL rendered green or a
 * critical badge rendered slate gives the wrong signal at a glance).
 *
 * Three regression shapes worth pinning here:
 *   1. STATUS_STYLES table: FAIL/WARN/PASS each map to a distinct
 *      tone (red/amber/emerald). A swap is exactly the bug a reviewer
 *      can't spot in a unit-style mock.
 *   2. SEVERITY_STYLES uppercases the badge ("CRITICAL", "MAJOR",
 *      "MINOR") — pin the literal text plus the tone class.
 *   3. Conditional rendering: `resolution` and `citation` blocks each
 *      render only when the corresponding field is non-null. The
 *      "Khuyến nghị" header only appears with a resolution.
 */

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    status: "FAIL",
    severity: "critical",
    category: "fire_safety",
    title: "Hành lang thoát nạn không đủ rộng",
    description: "Hành lang chỉ rộng 1.0m, không đạt 1.4m tối thiểu.",
    resolution: null,
    citation: null,
    ...overrides,
  };
}

function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    regulation_id: "reg-1",
    regulation: "QCVN 06:2022/BXD",
    section: "3.2.1",
    excerpt: "Hành lang thoát nạn ≥ 1.4m...",
    source_url: null,
    ...overrides,
  };
}

describe("FindingItem / status → tone", () => {
  test("FAIL → red tone classes on the wrapper", () => {
    const { container } = render(
      <FindingItem finding={makeFinding({ status: "FAIL" })} />,
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toMatch(/bg-red-50/);
    expect(wrapper.className).toMatch(/border-red-200/);
  });

  test("WARN → amber tone classes on the wrapper", () => {
    const { container } = render(
      <FindingItem finding={makeFinding({ status: "WARN" })} />,
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toMatch(/bg-amber-50/);
    expect(wrapper.className).toMatch(/border-amber-200/);
  });

  test("PASS → emerald tone classes (NOT red, NOT amber)", () => {
    // Pin the not-red assertion explicitly: a swap of the FAIL ↔ PASS
    // entries in STATUS_STYLES would still render a div with valid
    // classes; the only signal is "is the colour green?"
    const { container } = render(
      <FindingItem finding={makeFinding({ status: "PASS" })} />,
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toMatch(/bg-emerald-50/);
    expect(wrapper.className).not.toMatch(/bg-red-/);
    expect(wrapper.className).not.toMatch(/bg-amber-/);
  });
});

describe("FindingItem / severity badge", () => {
  test("critical → uppercased 'CRITICAL' label with red-600 background", () => {
    const { container } = render(
      <FindingItem finding={makeFinding({ severity: "critical" })} />,
    );
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    // The severity badge is the only span with bg-red-600 (the wrapper
    // uses bg-red-50). Pin the badge tone explicitly.
    const badge = container.querySelector(".bg-red-600");
    expect(badge).not.toBeNull();
  });

  test("major → 'MAJOR' label with orange background", () => {
    const { container } = render(
      <FindingItem finding={makeFinding({ severity: "major" })} />,
    );
    expect(screen.getByText("MAJOR")).toBeInTheDocument();
    expect(container.querySelector(".bg-orange-500")).not.toBeNull();
  });

  test("minor → 'MINOR' label with slate background (intentionally muted)", () => {
    // Why slate (not yellow): a minor finding shouldn't compete
    // visually with critical/major in the same scan list. Pin so a
    // future "make it more visible" tweak is at least an explicit
    // decision.
    const { container } = render(
      <FindingItem finding={makeFinding({ severity: "minor" })} />,
    );
    expect(screen.getByText("MINOR")).toBeInTheDocument();
    expect(container.querySelector(".bg-slate-400")).not.toBeNull();
  });
});

describe("FindingItem / conditional sections", () => {
  test("title + description always render", () => {
    render(<FindingItem finding={makeFinding()} />);
    expect(
      screen.getByText("Hành lang thoát nạn không đủ rộng"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Hành lang chỉ rộng 1.0m/),
    ).toBeInTheDocument();
  });

  test("category renders as a small chip ('fire_safety')", () => {
    render(<FindingItem finding={makeFinding({ category: "fire_safety" })} />);
    expect(screen.getByText("fire_safety")).toBeInTheDocument();
  });

  test("resolution=null → no 'Khuyến nghị' block", () => {
    render(<FindingItem finding={makeFinding({ resolution: null })} />);
    expect(screen.queryByText(/Khuyến nghị/)).not.toBeInTheDocument();
  });

  test("resolution present → 'Khuyến nghị' header + body render", () => {
    render(
      <FindingItem
        finding={makeFinding({ resolution: "Mở rộng hành lang lên 1.4m." })}
      />,
    );
    expect(screen.getByText("Khuyến nghị")).toBeInTheDocument();
    expect(
      screen.getByText("Mở rộng hành lang lên 1.4m."),
    ).toBeInTheDocument();
  });

  test("citation=null → no CitationCard rendered (no empty section)", () => {
    const { container } = render(
      <FindingItem finding={makeFinding({ citation: null })} />,
    );
    // CitationCard wraps its content in a blockquote — pin its
    // absence rather than testing for the wrapper div, since the
    // status-tone div also matches.
    expect(container.querySelector("blockquote")).toBeNull();
  });

  test("citation present → CitationCard renders the regulation + excerpt", () => {
    const { container } = render(
      <FindingItem
        finding={makeFinding({
          citation: makeCitation({
            regulation: "QCVN 06:2022/BXD",
            section: "3.2.1",
            excerpt: "Hành lang thoát nạn ≥ 1.4m...",
          }),
        })}
      />,
    );
    expect(container.textContent).toMatch(/QCVN 06:2022\/BXD/);
    expect(container.textContent).toMatch(/§ 3\.2\.1/);
    const quote = container.querySelector("blockquote");
    expect(quote).not.toBeNull();
    expect(quote!.textContent).toMatch(/Hành lang thoát nạn ≥ 1\.4m/);
  });

  test("description with [1] marker AND a citation → marker becomes interactive chip", () => {
    // The component passes finding.citation as a single-element array
    // to AnswerWithCitations, so '[1]' is in-range and renders as a
    // hover-expandable button. Pin this composition — it's the
    // hot path through which scan results show their evidence.
    render(
      <FindingItem
        finding={makeFinding({
          description: "Hành lang chỉ rộng 1.0m [1].",
          citation: makeCitation(),
        })}
      />,
    );
    const chip = screen.getByRole("button", { name: /trích dẫn 1/i });
    expect(chip).toBeInTheDocument();
  });
});
