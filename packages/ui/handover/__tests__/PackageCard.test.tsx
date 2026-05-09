import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { PackageCard } from "../PackageCard";
import type { PackageStatus, PackageSummary } from "../types";

/**
 * PackageCard has two pieces of derived logic worth pinning:
 *
 *   1. `donePct = round(closeout_done / closeout_total × 100)`, with a
 *      special case for `closeout_total === 0` returning 0 instead of
 *      NaN/Infinity. The progress bar inline-styles `width: ${donePct}%`,
 *      so a regression that dropped the divide-by-zero guard would
 *      ship a `width: NaN%` to production.
 *   2. The `tone` of the warranty/defect Stat tiles flips amber/red
 *      when the count is > 0. Easy to miss in a refactor that swaps
 *      `value > 0` for `value >= 0`.
 *
 * Optional href wrapping (Link vs. plain div) is also tested — there
 * are call-sites that render packages read-only (no detail page yet)
 * and must not crash without an href.
 */

function makePackage(overrides: Partial<PackageSummary> = {}): PackageSummary {
  return {
    id: "pkg-1",
    project_id: "project-1",
    name: "Bàn giao giai đoạn 1",
    status: "in_review" satisfies PackageStatus,
    closeout_total: 12,
    closeout_done: 8,
    warranty_expiring: 0,
    open_defects: 0,
    delivered_at: null,
    created_at: "2026-04-15T08:00:00Z",
    ...overrides,
  };
}

describe("PackageCard / progress percent", () => {
  test("done/total → rounded percent (8/12 → 67%)", () => {
    render(<PackageCard pkg={makePackage({ closeout_done: 8, closeout_total: 12 })} />);
    expect(screen.getByText(/8\/12 \(67%\)/)).toBeInTheDocument();
  });

  test("zero total → 0% (not NaN%) — the divide-by-zero guard", () => {
    // Regression target: without the special-case, donePct would be
    // `NaN`, the inline `width: ${NaN}%` would ship to the DOM, and
    // the bar would render at its default 0 width — but the LABEL
    // would say "NaN%" which is what the user sees.
    render(<PackageCard pkg={makePackage({ closeout_done: 0, closeout_total: 0 })} />);
    expect(screen.getByText(/0\/0 \(0%\)/)).toBeInTheDocument();
  });

  test("100% complete renders as exactly 100%", () => {
    render(<PackageCard pkg={makePackage({ closeout_done: 24, closeout_total: 24 })} />);
    expect(screen.getByText(/24\/24 \(100%\)/)).toBeInTheDocument();
  });
});

describe("PackageCard / status pills", () => {
  const cases: Array<[PackageStatus, RegExp]> = [
    ["draft", /bản nháp/i],
    ["in_review", /đang duyệt/i],
    ["approved", /đã duyệt/i],
    ["delivered", /đã bàn giao/i],
  ];
  for (const [status, label] of cases) {
    test(`${status} → '${label.source}' label`, () => {
      render(<PackageCard pkg={makePackage({ status })} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  }
});

describe("PackageCard / Stat tile tones", () => {
  test("warranty_expiring > 0 → amber tone (visually different from default)", () => {
    const { container } = render(
      <PackageCard pkg={makePackage({ warranty_expiring: 3 })} />,
    );
    // The Stat tile with the amber count should have an amber-toned text.
    const amberSpans = container.querySelectorAll('[class*="amber-600"]');
    expect(amberSpans.length).toBeGreaterThan(0);
  });

  test("open_defects > 0 → red tone", () => {
    const { container } = render(
      <PackageCard pkg={makePackage({ open_defects: 5 })} />,
    );
    const redSpans = container.querySelectorAll('[class*="red-600"]');
    expect(redSpans.length).toBeGreaterThan(0);
  });

  test("zero counts → no amber/red tone (everything stays slate)", () => {
    const { container } = render(
      <PackageCard pkg={makePackage({ warranty_expiring: 0, open_defects: 0 })} />,
    );
    expect(container.querySelectorAll('[class*="amber-600"]').length).toBe(0);
    expect(container.querySelectorAll('[class*="red-600"]').length).toBe(0);
  });
});

describe("PackageCard / href wrapping", () => {
  test("href provided → wrapped in a Link (an anchor in tests)", () => {
    const { container } = render(
      <PackageCard pkg={makePackage()} href="/handover/pkg-1" />,
    );
    const link = container.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toBe("/handover/pkg-1");
  });

  test("href omitted → no anchor wrapper, content still renders", () => {
    const { container } = render(<PackageCard pkg={makePackage()} />);
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getByText("Bàn giao giai đoạn 1")).toBeInTheDocument();
  });
});
