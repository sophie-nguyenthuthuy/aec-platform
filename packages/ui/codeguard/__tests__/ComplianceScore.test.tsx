import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { ComplianceScore } from "../ComplianceScore";

/**
 * Two pieces of derived logic worth pinning:
 *   1. `scorePct = round(pass / (pass+warn+fail) × 100)`, with a
 *      special case for total=0 returning 0 instead of NaN. Without
 *      the divide-by-zero guard the SVG would ship `NaN%` text.
 *   2. The donut segments — non-zero counts produce one segment each,
 *      zero counts produce no segment. Total=0 produces a single
 *      grey "no data" ring.
 */

describe("ComplianceScore / pct computation", () => {
  test("8 pass / 12 total → 67% in the centre label", () => {
    render(<ComplianceScore pass={8} warn={2} fail={2} />);
    expect(screen.getByText("67%")).toBeInTheDocument();
  });

  test("12/12 → 100%", () => {
    render(<ComplianceScore pass={12} warn={0} fail={0} />);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  test("0/0/0 → 0% (divide-by-zero guard, not NaN%)", () => {
    // Without the special-case, scorePct would be NaN and the SVG
    // text would read "NaN%". The donut also renders a single grey
    // "no data" ring instead of three zero-length segments.
    render(<ComplianceScore pass={0} warn={0} fail={0} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.queryByText("NaN%")).not.toBeInTheDocument();
  });

  test("0 pass / non-zero warn+fail → 0%", () => {
    render(<ComplianceScore pass={0} warn={5} fail={3} />);
    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});

describe("ComplianceScore / legend", () => {
  test("legend shows the raw counts for each tone", () => {
    render(<ComplianceScore pass={8} warn={3} fail={1} />);
    // The legend rows are { color, label, value } — the values are
    // rendered as standalone numbers, so getByText('8') / '3' / '1'
    // resolves to those legend cells.
    expect(screen.getByText("Đạt")).toBeInTheDocument();
    expect(screen.getByText("Cảnh báo")).toBeInTheDocument();
    expect(screen.getByText("Vi phạm")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });
});

describe("ComplianceScore / donut segments", () => {
  test("each non-zero count produces one stroke-dashed circle segment", () => {
    // The svg has one BACKGROUND ring + N SEGMENTS. With pass=4,
    // warn=2, fail=1 we expect 1 + 3 = 4 circles total.
    const { container } = render(
      <ComplianceScore pass={4} warn={2} fail={1} />,
    );
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(4);
  });

  test("zero counts produce no segment for that tone", () => {
    // pass=4, warn=0, fail=2 → background + 2 segments = 3 circles.
    // The "warn" tone (no count) doesn't render an empty arc.
    const { container } = render(
      <ComplianceScore pass={4} warn={0} fail={2} />,
    );
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(3);
  });

  test("total=0 produces a single grey 'no data' ring (background + 1 fallback)", () => {
    const { container } = render(
      <ComplianceScore pass={0} warn={0} fail={0} />,
    );
    const circles = container.querySelectorAll("circle");
    // Background + 1 grey fallback segment = 2 circles.
    expect(circles.length).toBe(2);
  });
});

describe("ComplianceScore / size prop", () => {
  test("default size is 160", () => {
    const { container } = render(<ComplianceScore pass={1} warn={0} fail={0} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("160");
    expect(svg.getAttribute("height")).toBe("160");
  });

  test("explicit size overrides the default", () => {
    const { container } = render(
      <ComplianceScore pass={1} warn={0} fail={0} size={240} />,
    );
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("240");
  });
});
