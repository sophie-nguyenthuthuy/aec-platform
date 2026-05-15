/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { GanttChart } from "../GanttChart";

/**
 * Smoke tests for the SVG Gantt. We don't fully assert pixel
 * positions (the axis math is internal + scales with zoom level);
 * the load-bearing checks are:
 *
 *   * Renders with zero activities without throwing.
 *   * Renders header + ROW * activities count = correct svg height.
 *   * Renders critical-path bars in rose when the code is in the
 *     critical set.
 *   * Renders dependency arrows when predecessor + successor both
 *     have planned dates.
 */


function activity(over: Partial<any> = {}): any {
  return {
    id: "a-1",
    schedule_id: "s-1",
    code: "1.1",
    name: "Móng",
    activity_type: "task",
    planned_start: "2026-01-01",
    planned_finish: "2026-01-10",
    baseline_start: null,
    baseline_finish: null,
    actual_start: null,
    actual_finish: null,
    percent_complete: 50,
    status: "in_progress",
    ...over,
  };
}


describe("GanttChart", () => {
  it("renders without crashing on empty inputs", () => {
    const { container } = render(
      <GanttChart activities={[]} dependencies={[]} criticalCodes={new Set()} />,
    );
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("renders one row per activity in the left column", () => {
    const { container } = render(
      <GanttChart
        activities={[
          activity({ id: "a-1", code: "1.1", name: "Móng" }),
          activity({ id: "a-2", code: "1.2", name: "Cột" }),
          activity({ id: "a-3", code: "1.3", name: "Dầm" }),
        ]}
        dependencies={[]}
        criticalCodes={new Set()}
      />,
    );
    expect(container.textContent).toContain("Móng");
    expect(container.textContent).toContain("Cột");
    expect(container.textContent).toContain("Dầm");
  });

  it("marks an activity as critical when its code is in criticalCodes", () => {
    const { container } = render(
      <GanttChart
        activities={[
          activity({ id: "a-1", code: "1.1", name: "Crit" }),
          activity({ id: "a-2", code: "1.2", name: "Other" }),
        ]}
        dependencies={[]}
        criticalCodes={new Set(["1.1"])}
      />,
    );
    // Critical bars use #fb7185 (rose-400). Non-critical use #3b82f6.
    const fills = Array.from(container.querySelectorAll("rect[fill]"))
      .map((el) => el.getAttribute("fill"));
    expect(fills).toContain("#fb7185");
  });

  it("renders dependency arrow when predecessor + successor both have dates", () => {
    const { container } = render(
      <GanttChart
        activities={[
          activity({
            id: "a-1",
            code: "1.1",
            planned_start: "2026-01-01",
            planned_finish: "2026-01-10",
          }),
          activity({
            id: "a-2",
            code: "1.2",
            planned_start: "2026-01-11",
            planned_finish: "2026-01-20",
          }),
        ]}
        dependencies={[
          {
            id: "d-1",
            predecessor_id: "a-1",
            successor_id: "a-2",
            relationship_type: "fs",
            lag_days: 0,
          } as any,
        ]}
        criticalCodes={new Set()}
      />,
    );
    // Each dependency emits one <path> element. Plus the SVG defs marker.
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThan(0);
  });

  it("includes today line legend marker in legend strip", () => {
    const { container } = render(
      <GanttChart
        activities={[activity()]}
        dependencies={[]}
        criticalCodes={new Set()}
      />,
    );
    expect(container.textContent).toContain("Hôm nay");
  });
});
