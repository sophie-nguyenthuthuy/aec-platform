/**
 * Vitest coverage for the drift sparkline rendered on
 * `/admin/scrapers`. Locks down four behaviours that have user-
 * visible meaning:
 *
 *   1. Empty-state fallback (a flat dashed baseline) so the table
 *      column doesn't collapse when a slug only has zero-row runs.
 *   2. Threshold tinting — line goes amber when any point is at-or-
 *      above the threshold; otherwise stays slate.
 *   3. Null-ratio points (division-by-zero runs) are silently skipped
 *      from the rendered path.
 *   4. The peak-percentage tooltip is rendered as `<title>` for a11y
 *      so the SR/keyboard surface matches the visual one.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { Sparkline } from "../Sparkline";


describe("Sparkline / empty state", () => {
  test("zero points → flat baseline placeholder, no path drawn", () => {
    render(<Sparkline points={[]} threshold={0.3} />);
    expect(screen.getByTestId("sparkline-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("sparkline-path")).toBeNull();
  });

  test("all-null-ratio points (only zero-row runs) → empty placeholder", () => {
    // Slug ran twice but both runs scraped 0 rows — no drift ratio
    // can be computed. The component should fall back to the
    // placeholder, not crash on the empty `valid` list.
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: null },
          { started_at: "2026-04-02T00:00:00Z", ratio: null },
        ]}
        threshold={0.3}
      />,
    );
    expect(screen.getByTestId("sparkline-empty")).toBeInTheDocument();
  });
});


describe("Sparkline / threshold tinting", () => {
  test("all points below threshold → slate line", () => {
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: 0.05 },
          { started_at: "2026-04-02T00:00:00Z", ratio: 0.1 },
          { started_at: "2026-04-03T00:00:00Z", ratio: 0.15 },
        ]}
        threshold={0.3}
      />,
    );
    const path = screen.getByTestId("sparkline-path");
    // The slate stroke colour comes from `rgb(71 85 105)` (slate-600).
    expect(path.getAttribute("stroke")).toBe("rgb(71 85 105)");
  });

  test("any point at-or-above threshold → amber line", () => {
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: 0.05 },
          // This single point trips the threshold — a single bad day
          // is the actionable signal, not just "average is high."
          { started_at: "2026-04-02T00:00:00Z", ratio: 0.42 },
          { started_at: "2026-04-03T00:00:00Z", ratio: 0.1 },
        ]}
        threshold={0.3}
      />,
    );
    const path = screen.getByTestId("sparkline-path");
    expect(path.getAttribute("stroke")).toBe("rgb(180 83 9)");
  });

  test("end-marker dot uses the same colour as the line", () => {
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: 0.5 },
          { started_at: "2026-04-02T00:00:00Z", ratio: 0.55 },
        ]}
        threshold={0.3}
      />,
    );
    const path = screen.getByTestId("sparkline-path");
    const dot = screen.getByTestId("sparkline-end-dot");
    expect(dot.getAttribute("fill")).toBe(path.getAttribute("stroke"));
  });
});


describe("Sparkline / null-ratio handling", () => {
  test("null points are skipped from the drawn path", () => {
    // 3 valid + 1 null = 3 path commands ("M …, L …, L …").
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: 0.1 },
          { started_at: "2026-04-02T00:00:00Z", ratio: null },
          { started_at: "2026-04-03T00:00:00Z", ratio: 0.2 },
          { started_at: "2026-04-04T00:00:00Z", ratio: 0.25 },
        ]}
        threshold={0.5}
      />,
    );
    const d = screen.getByTestId("sparkline-path").getAttribute("d") ?? "";
    // Path command count: one "M" + (valid_count - 1) "L"s.
    const moveCount = (d.match(/M/g) ?? []).length;
    const lineCount = (d.match(/L/g) ?? []).length;
    expect(moveCount).toBe(1);
    expect(lineCount).toBe(2); // 3 valid points → 1 M + 2 L
  });

  test("threshold + tooltip use only the valid-point peak", () => {
    // Peak across valid points is 0.25 → 25%. The null shouldn't be
    // counted as "peak", and the tooltip text should reflect the
    // surviving sample size (3, not 4).
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: 0.1 },
          { started_at: "2026-04-02T00:00:00Z", ratio: null },
          { started_at: "2026-04-03T00:00:00Z", ratio: 0.2 },
          { started_at: "2026-04-04T00:00:00Z", ratio: 0.25 },
        ]}
        threshold={0.5}
      />,
    );
    // Tooltip is on the <title> child; testing-library queries by
    // accessible name to bridge the SR-visible text.
    const svg = screen.getByLabelText(/Peak 25% drift across 3 run/);
    expect(svg).toBeInTheDocument();
  });
});


describe("Sparkline / a11y", () => {
  test("aria-label captures peak% and run count for SR users", () => {
    render(
      <Sparkline
        points={[
          { started_at: "2026-04-01T00:00:00Z", ratio: 0.42 },
          { started_at: "2026-04-02T00:00:00Z", ratio: 0.5 },
        ]}
        threshold={0.3}
      />,
    );
    // Round to nearest %: 0.5 → 50%.
    expect(screen.getByLabelText(/Peak 50% drift across 2 run/)).toBeInTheDocument();
  });
});
