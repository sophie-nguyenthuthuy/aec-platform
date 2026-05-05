import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { WinLossTag } from "../WinLossTag";

/**
 * Pure value-driven render. Each ProposalStatus drives both the visible
 * label AND the Badge variant (which controls colour). Pin both — a
 * regression that swapped variant ↔ label maps would silently render
 * "Won" with the destructive (red) tone, which is exactly the wrong
 * signal in front of a sales team scanning a list.
 */

describe("WinLossTag", () => {
  const cases: Array<[
    "draft" | "sent" | "won" | "lost" | "expired",
    string,
  ]> = [
    ["draft", "Draft"],
    ["sent", "Sent"],
    ["won", "Won"],
    ["lost", "Lost"],
    ["expired", "Expired"],
  ];

  for (const [status, label] of cases) {
    test(`${status} → '${label}' label`, () => {
      render(<WinLossTag status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  }

  test("won renders with the success variant (visually green)", () => {
    // The Badge primitive applies the variant via a class. We can't
    // assert the colour directly, but pinning the class string here
    // catches a swap that would silently render won as red.
    const { container } = render(<WinLossTag status="won" />);
    const badge = container.querySelector("span")!;
    // class-variance-authority emits "bg-emerald-100" or similar for
    // the success variant. Any of `success` / `emerald` / `green` is
    // acceptable signal — pin on `emerald` since that's the current
    // tailwind palette.
    expect(badge.className.toLowerCase()).toMatch(/emerald|success|green/);
  });

  test("lost renders with the destructive variant (visually red)", () => {
    const { container } = render(<WinLossTag status="lost" />);
    const badge = container.querySelector("span")!;
    expect(badge.className.toLowerCase()).toMatch(/destructive|red|rose/);
  });
});
