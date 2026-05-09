import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { ScraperRun } from "@aec/types";

import { ScraperRunsPanel } from "../ScraperRunsPanel";

/**
 * `<ScraperRunsPanel>` is the admin-facing drift readout. The three
 * branches worth pinning:
 *
 *   1. Status badge gating — failed → 🔴, drift > 30% → 🟡, else 🟢.
 *      The 30% threshold has to match the API's `_DRIFT_THRESHOLD`.
 *   2. Empty / loading / error states — admins panic when a panel
 *      disappears; "no runs yet" copy is the safety net.
 *   3. Sample-name preview is capped at 3 in the row + drift-only.
 *      Without the cap, a 25-row sample would blow up the table.
 */

function makeRun(overrides: Partial<ScraperRun> = {}): ScraperRun {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    slug: "hanoi",
    started_at: "2026-04-30T10:00:00Z",
    finished_at: "2026-04-30T10:01:00Z",
    ok: true,
    error: null,
    scraped: 100,
    matched: 95,
    unmatched: 5,
    written: 95,
    rule_hits: {},
    unmatched_sample: [],
    ...overrides,
  };
}


describe("<ScraperRunsPanel>", () => {
  test("renders OK badge when ratio is below 30%", () => {
    const run = makeRun({ scraped: 100, unmatched: 5 });  // 5%
    render(<ScraperRunsPanel runs={[run]} />);

    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.queryByText("Drift")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  test("renders Drift badge when ratio is at or above 30%", () => {
    const run = makeRun({ scraped: 10, unmatched: 4 });  // 40%
    render(<ScraperRunsPanel runs={[run]} />);

    expect(screen.getByText("Drift")).toBeInTheDocument();
    expect(screen.queryByText("OK")).not.toBeInTheDocument();
  });

  test("renders Failed badge when run.ok is false regardless of ratio", () => {
    const run = makeRun({ ok: false, error: "upstream 500", scraped: 100, unmatched: 5 });
    render(<ScraperRunsPanel runs={[run]} />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.queryByText("OK")).not.toBeInTheDocument();
    expect(screen.queryByText("Drift")).not.toBeInTheDocument();
  });

  test("shows error preview text when run.ok is false", () => {
    const run = makeRun({
      ok: false,
      error: "Connection refused: 198.51.100.42:80",
    });
    render(<ScraperRunsPanel runs={[run]} />);

    expect(screen.getByText(/Connection refused/)).toBeInTheDocument();
  });

  test("renders empty state when runs is empty", () => {
    render(<ScraperRunsPanel runs={[]} />);
    expect(screen.getByText(/No scraper runs yet/i)).toBeInTheDocument();
  });

  test("renders loading state while fetching", () => {
    render(<ScraperRunsPanel runs={[]} isLoading />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    // Empty-state copy must NOT also show — would be a confusing race.
    expect(screen.queryByText(/No scraper runs yet/i)).not.toBeInTheDocument();
  });

  test("renders error state when an error is provided", () => {
    render(
      <ScraperRunsPanel runs={[]} error={{ message: "403 Forbidden" }} />,
    );
    expect(screen.getByText("403 Forbidden")).toBeInTheDocument();
  });

  test("caps sample names at 3 in the inline preview for drifting rows", () => {
    const run = makeRun({
      scraped: 10,
      unmatched: 4,
      unmatched_sample: ["A", "B", "C", "D", "E"],
    });
    render(<ScraperRunsPanel runs={[run]} />);

    // First three appear; "D" and "E" don't (they'd appear in a per-run
    // detail view, not this row preview).
    const tableBody = screen.getByRole("table");
    expect(within(tableBody).getByText(/A, B, C/)).toBeInTheDocument();
    expect(within(tableBody).queryByText(/, D,/)).not.toBeInTheDocument();
  });

  test("counts header summarises ok/failed/drifting across runs", () => {
    const runs = [
      makeRun({ id: "1", scraped: 100, unmatched: 5 }),                     // ok
      makeRun({ id: "2", scraped: 10, unmatched: 4 }),                      // drifting
      makeRun({ id: "3", ok: false, error: "boom" }),                       // failed
      makeRun({ id: "4", scraped: 100, unmatched: 10 }),                    // ok (10%)
    ];
    render(<ScraperRunsPanel runs={runs} />);

    // Format: "2 ok · 1 failed · 1 drifting"
    expect(screen.getByText(/2 ok/)).toBeInTheDocument();
    expect(screen.getByText(/1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/1 drifting/)).toBeInTheDocument();
  });
});
