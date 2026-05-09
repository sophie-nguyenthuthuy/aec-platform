import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { axe } from "vitest-axe";

import { AIConfidenceBadge } from "../AIConfidenceBadge";
import { FeeBreakdownTable } from "../FeeBreakdownTable";
import { ProposalCard } from "../ProposalCard";
import { WinLossTag } from "../WinLossTag";
import type { FeeBreakdown, Proposal } from "@aec/types/winwork";

/**
 * Component-level a11y for `packages/ui/winwork/*`.
 *
 * These components surface money + status — the two visual signals
 * a screen-reader user MUST be able to parse independently of color.
 * axe doesn't catch "user can't understand the status without seeing
 * green/red," but it DOES catch the prerequisites: text alternatives
 * on icons, sufficient contrast on chips, labels on form controls.
 */

function makeProposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    id: "prop-1",
    project_id: null,
    title: "Marina Tower curtain wall design",
    status: "draft",
    client_name: "Marina Tower JV",
    client_email: null,
    scope_of_work: null,
    fee_breakdown: null,
    total_fee_vnd: 1_200_000_000,
    total_fee_currency: "VND",
    valid_until: null,
    ai_generated: false,
    ai_confidence: null,
    notes: null,
    sent_at: null,
    responded_at: null,
    created_by: null,
    created_at: "2026-04-15T00:00:00Z",
    ...overrides,
  };
}

describe("WinLossTag / a11y", () => {
  // 5 status × axe → 5 quick assertions. Each tone (won=green,
  // lost=red, draft=neutral, sent=blue, expired=amber) has its own
  // contrast risk surface.
  const statuses: Array<"draft" | "sent" | "won" | "lost" | "expired"> = [
    "draft",
    "sent",
    "won",
    "lost",
    "expired",
  ];
  for (const status of statuses) {
    test(`${status} renders without violations`, async () => {
      const { container } = render(<WinLossTag status={status} />);
      expect(await axe(container)).toHaveNoViolations();
    });
  }
});

describe("AIConfidenceBadge / a11y", () => {
  test("high-confidence renders without violations", async () => {
    const { container } = render(<AIConfidenceBadge confidence={0.92} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  test("low-confidence (destructive tone) renders without violations", async () => {
    // Destructive variant uses red tones — most likely to have
    // contrast issues if the bg/fg ratio drifts.
    const { container } = render(<AIConfidenceBadge confidence={0.35} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  test("null confidence renders nothing (vacuously a11y-clean)", async () => {
    // The early-return path. Pin so a regression that started
    // rendering "AI · NaN%" or an empty chip surfaces.
    const { container } = render(<AIConfidenceBadge confidence={null} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("ProposalCard / a11y", () => {
  test("draft, no AI badge renders without violations", async () => {
    const { container } = render(<ProposalCard proposal={makeProposal()} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  test("won + AI-generated renders without violations", async () => {
    // Most-loaded variant — the AI badge + the status tag both
    // appear, plus the fee text. If any tone-on-tone combination
    // fails contrast, axe surfaces it here on this single render.
    const { container } = render(
      <ProposalCard
        proposal={makeProposal({
          status: "won",
          ai_generated: true,
          ai_confidence: 0.88,
        })}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("FeeBreakdownTable / a11y", () => {
  function makeBreakdown(): FeeBreakdown {
    return {
      lines: [
        { phase: "Concept", label: "Concept design", amount_vnd: 100_000_000 },
        { phase: "DD", label: "Design development", amount_vnd: 200_000_000 },
      ],
      subtotal_vnd: 300_000_000,
      vat_vnd: 24_000_000,
      total_vnd: 324_000_000,
    };
  }

  test("read-only mode renders without violations", async () => {
    const { container } = render(
      <FeeBreakdownTable value={makeBreakdown()} readOnly />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  test("editable mode renders without violations", async () => {
    // The editable path renders <Input>s and a Remove button per row
    // plus an Add button — all need accessible names. axe surfaces
    // any unlabeled form control here, just like it caught the
    // ChecklistItem checkbox + select.
    const { container } = render(
      <FeeBreakdownTable
        value={makeBreakdown()}
        onChange={() => undefined}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
