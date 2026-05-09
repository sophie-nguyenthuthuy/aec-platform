import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { axe } from "vitest-axe";

import { DefectCard } from "../DefectCard";
import { PackageCard } from "../PackageCard";

/**
 * Component-level a11y for `packages/ui/handover/*`.
 *
 * Companion to `codeguard/__tests__/a11y.test.tsx` — same pattern,
 * different module. See that file's docstring for the rationale on
 * component-level vs page-level a11y.
 */

describe("PackageCard / a11y", () => {
  test("draft package renders without violations", async () => {
    const { container } = render(
      <PackageCard
        pkg={{
          id: "pkg-1",
          name: "Marina Tower — Phase 1 Closeout",
          status: "draft",
          project_id: "proj-1",
          closeout_total: 12,
          closeout_done: 5,
          warranty_expiring: 0,
          open_defects: 3,
          created_at: "2026-04-01T00:00:00Z",
        }}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  test("delivered package renders without violations", async () => {
    // Different status badge tone — pin the delivered variant
    // separately so a regression specific to the success-tone
    // chip surfaces here.
    const { container } = render(
      <PackageCard
        pkg={{
          id: "pkg-2",
          name: "Riverside Office — Phase 2",
          status: "delivered",
          project_id: "proj-2",
          closeout_total: 25,
          closeout_done: 25,
          warranty_expiring: 2,
          open_defects: 0,
          created_at: "2026-03-15T00:00:00Z",
        }}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("DefectCard / a11y", () => {
  test("open defect with photos renders without violations", async () => {
    const { container } = render(
      <DefectCard
        defect={{
          id: "d-1",
          project_id: "proj-1",
          package_id: "pkg-1",
          title: "Cracked floor tile in lobby",
          description: "Tile A-12 has a hairline crack from corner.",
          location: { room: "Lobby", floor: "1" },
          photo_file_ids: ["f1"],
          status: "open",
          priority: "low",
          assignee_id: null,
          reported_by: null,
          reported_at: "2026-04-15T00:00:00Z",
          resolved_at: null,
          resolution_notes: null,
        }}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  test("resolved critical defect renders without violations", async () => {
    // Different status (resolved) and priority (critical) tones —
    // exercises both the destructive (red) and success (green) chip
    // colours in one render. axe surfaces any contrast issue on
    // either tone independently.
    const { container } = render(
      <DefectCard
        defect={{
          id: "d-2",
          project_id: "proj-1",
          package_id: "pkg-1",
          title: "Water leak under sink",
          description: "Active leak from supply line.",
          location: { room: "Unit 3F-04 kitchen" },
          photo_file_ids: [],
          status: "resolved",
          priority: "critical",
          assignee_id: null,
          reported_by: null,
          reported_at: "2026-04-10T00:00:00Z",
          resolved_at: "2026-04-12T00:00:00Z",
          resolution_notes: "Replaced supply line; pressure-tested.",
        }}
      />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
