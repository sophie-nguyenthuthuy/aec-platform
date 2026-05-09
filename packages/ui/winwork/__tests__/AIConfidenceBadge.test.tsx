import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { AIConfidenceBadge } from "../AIConfidenceBadge";

/**
 * Two render branches + three colour bands worth pinning:
 *   1. `confidence == null` → renders nothing (not "AI · 0%").
 *   2. The pct → variant mapping at 75 / 50 thresholds. Each border
 *      case (74 vs 75, 49 vs 50) crosses a colour band, so a `>` vs
 *      `>=` regression flips the visible signal.
 */

describe("AIConfidenceBadge", () => {
  test("null confidence renders nothing", () => {
    const { container } = render(<AIConfidenceBadge confidence={null} />);
    expect(container.firstChild).toBeNull();
  });

  test("confidence renders as a percent (rounded)", () => {
    render(<AIConfidenceBadge confidence={0.876} />);
    expect(screen.getByText(/AI · 88%/)).toBeInTheDocument();
  });

  test("0 renders as 'AI · 0%' (not blank)", () => {
    // Distinct from null — explicit 0 means "model couldn't generate
    // anything actionable", which is a meaningful signal worth showing.
    render(<AIConfidenceBadge confidence={0} />);
    expect(screen.getByText(/AI · 0%/)).toBeInTheDocument();
  });

  test("pct=75 → success variant (boundary inclusive)", () => {
    const { container } = render(<AIConfidenceBadge confidence={0.75} />);
    const badge = container.querySelector("span")!;
    expect(badge.className.toLowerCase()).toMatch(/emerald|success|green/);
  });

  test("pct=74 → warning variant (just below the success boundary)", () => {
    const { container } = render(<AIConfidenceBadge confidence={0.74} />);
    const badge = container.querySelector("span")!;
    expect(badge.className.toLowerCase()).toMatch(/amber|warning|yellow/);
  });

  test("pct=50 → warning variant (boundary inclusive)", () => {
    const { container } = render(<AIConfidenceBadge confidence={0.5} />);
    const badge = container.querySelector("span")!;
    expect(badge.className.toLowerCase()).toMatch(/amber|warning|yellow/);
  });

  test("pct=49 → destructive variant (just below the warning boundary)", () => {
    const { container } = render(<AIConfidenceBadge confidence={0.49} />);
    const badge = container.querySelector("span")!;
    expect(badge.className.toLowerCase()).toMatch(/destructive|red|rose/);
  });

  test("custom className is appended (not replaced)", () => {
    const { container } = render(
      <AIConfidenceBadge confidence={0.9} className="ml-auto" />,
    );
    const badge = container.querySelector("span")!;
    expect(badge.className).toContain("ml-auto");
    // The variant tone class is still applied.
    expect(badge.className.toLowerCase()).toMatch(/emerald|success|green/);
  });
});
