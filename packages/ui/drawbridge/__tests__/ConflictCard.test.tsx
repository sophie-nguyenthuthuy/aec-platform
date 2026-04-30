import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { ConflictCard } from "../ConflictCard";
import type { ConflictWithExcerpts } from "../types";

/**
 * Component-level tests for ConflictCard.
 *
 * The Drawbridge conflicts page (`apps/web/app/(dashboard)/drawbridge/conflicts/page.tsx`)
 * already has Playwright coverage that exercises the network round-trip
 * + redirect flow. These component tests cover the things that are
 * easier to assert in isolation:
 *
 *   1. Severity styling — critical vs major vs minor render different
 *      label copy + a different icon. A regression that swapped the
 *      icon-by-severity map would slip past Playwright unless every
 *      severity was seeded.
 *   2. Action buttons only render for `status === "open"` (resolved /
 *      dismissed conflicts shouldn't surface "Đã xử lý" / "Bỏ qua"
 *      buttons; that's the whole point of the dropdown).
 *   3. Click handlers fire with the conflict object as the argument —
 *      easy here, awkward to assert on Playwright (you'd need to
 *      mock the network round-trip and check the request body).
 */

const baseExcerpt = (side: "A" | "B") => ({
  document_id: side === "A" ? "doc-a-id" : "doc-b-id",
  drawing_number: side === "A" ? "A-101" : "S-301",
  discipline: side === "A" ? ("architectural" as const) : ("structural" as const),
  page: 2,
  excerpt: `Excerpt from doc ${side}.`,
  bbox: null,
});

function makeConflict(overrides: Partial<ConflictWithExcerpts> = {}): ConflictWithExcerpts {
  return {
    id: "conflict-1",
    organization_id: "org-1",
    project_id: "project-1",
    status: "open",
    severity: "critical",
    conflict_type: "dimension",
    description: "Slab thickness mismatch: A-101 vs S-301",
    document_a_id: null,
    chunk_a_id: null,
    document_b_id: null,
    chunk_b_id: null,
    ai_explanation: null,
    resolution_notes: null,
    detected_at: "2026-04-20T08:00:00Z",
    resolved_at: null,
    resolved_by: null,
    document_a: baseExcerpt("A"),
    document_b: baseExcerpt("B"),
    ...overrides,
  };
}

describe("ConflictCard / severity rendering", () => {
  test("critical → 'Nghiêm trọng' label", () => {
    render(<ConflictCard conflict={makeConflict({ severity: "critical" })} />);
    expect(screen.getByText("Nghiêm trọng")).toBeInTheDocument();
  });

  test("major → 'Lớn' label", () => {
    render(<ConflictCard conflict={makeConflict({ severity: "major" })} />);
    expect(screen.getByText("Lớn")).toBeInTheDocument();
  });

  test("minor → 'Nhỏ' label", () => {
    render(<ConflictCard conflict={makeConflict({ severity: "minor" })} />);
    expect(screen.getByText("Nhỏ")).toBeInTheDocument();
  });

  test("null severity falls through to the minor styling (backstop)", () => {
    // Defensive default in the source: `conflict.severity ? STYLE[severity] : STYLE.minor`.
    // A regression that crashed instead would surface here.
    render(<ConflictCard conflict={makeConflict({ severity: null })} />);
    expect(screen.getByText("Nhỏ")).toBeInTheDocument();
  });
});

describe("ConflictCard / action buttons", () => {
  test("open status renders all 4 action buttons when handlers are provided", () => {
    render(
      <ConflictCard
        conflict={makeConflict({ status: "open" })}
        onOpen={() => {}}
        onResolve={() => {}}
        onDismiss={() => {}}
        onGenerateRfi={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /chi tiết/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /tạo rfi/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /đã xử lý/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /bỏ qua/i })).toBeInTheDocument();
  });

  test("resolved status hides 'Tạo RFI' / 'Đã xử lý' / 'Bỏ qua' (only Chi tiết remains)", () => {
    render(
      <ConflictCard
        conflict={makeConflict({ status: "resolved" })}
        onOpen={() => {}}
        onResolve={() => {}}
        onDismiss={() => {}}
        onGenerateRfi={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /chi tiết/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /tạo rfi/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /đã xử lý/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /bỏ qua/i })).not.toBeInTheDocument();
  });

  test("dismissed status — same hide rule as resolved", () => {
    render(
      <ConflictCard
        conflict={makeConflict({ status: "dismissed" })}
        onOpen={() => {}}
        onResolve={() => {}}
        onDismiss={() => {}}
        onGenerateRfi={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /tạo rfi/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /đã xử lý/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /bỏ qua/i })).not.toBeInTheDocument();
  });

  test("buttons missing entirely when no handler is passed (action is opt-in)", () => {
    // The page uses an opt-in pattern — listing pages can pass onResolve
    // but a read-only "audit log" page wouldn't. Make sure the button
    // doesn't render when its handler is undefined.
    render(<ConflictCard conflict={makeConflict({ status: "open" })} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("ConflictCard / handler invocation", () => {
  test("clicking 'Đã xử lý' calls onResolve with the conflict object", async () => {
    const conflict = makeConflict({ status: "open" });
    const onResolve = vi.fn();
    render(<ConflictCard conflict={conflict} onResolve={onResolve} />);

    await userEvent.click(screen.getByRole("button", { name: /đã xử lý/i }));

    expect(onResolve).toHaveBeenCalledTimes(1);
    expect(onResolve).toHaveBeenCalledWith(conflict);
  });

  test("clicking 'Tạo RFI' calls onGenerateRfi with the conflict object", async () => {
    const conflict = makeConflict({ status: "open" });
    const onGenerateRfi = vi.fn();
    render(<ConflictCard conflict={conflict} onGenerateRfi={onGenerateRfi} />);

    await userEvent.click(screen.getByRole("button", { name: /tạo rfi/i }));

    expect(onGenerateRfi).toHaveBeenCalledWith(conflict);
  });
});

describe("ConflictCard / fallbacks", () => {
  test("renders default description when conflict.description is null", () => {
    render(<ConflictCard conflict={makeConflict({ description: null })} />);
    expect(screen.getByText("Xung đột giữa bản vẽ")).toBeInTheDocument();
  });

  test("excerpt panel for missing side renders the 'không khả dụng' fallback", () => {
    render(<ConflictCard conflict={makeConflict({ document_b: null })} />);
    expect(screen.getByText("Bản vẽ B — không khả dụng")).toBeInTheDocument();
    // Side A still renders normally
    expect(screen.getByText("A-101")).toBeInTheDocument();
  });
});
