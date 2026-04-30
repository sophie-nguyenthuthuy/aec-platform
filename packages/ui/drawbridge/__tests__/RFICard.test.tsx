import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { RFICard } from "../RFICard";
import type { Rfi } from "../types";

/**
 * RFICard mixes a few branching paths worth pinning at unit level:
 *   1. The `overdue` derived flag (due_date in the past + status !== closed)
 *      drives a different colour treatment AND an extra "(trễ hạn)" suffix.
 *   2. The "Trả lời" answer button only renders when both `onAnswer` is
 *      supplied AND `status === "open"`. answered/closed RFIs hide it.
 *   3. The card's outer click → onOpen, but the inner "Trả lời" click
 *      stops propagation so onOpen DOESN'T fire when the user clicks
 *      Answer. Easy to assert here, awkward in Playwright.
 */

function makeRfi(overrides: Partial<Rfi> = {}): Rfi {
  return {
    id: "rfi-1",
    organization_id: "org-1",
    project_id: "project-1",
    number: "RFI-001",
    subject: "Clarify slab thickness on level 3",
    description: null,
    status: "open",
    priority: "normal",
    related_document_ids: [],
    raised_by: null,
    assigned_to: null,
    due_date: null,
    response: null,
    created_at: "2026-04-20T08:00:00Z",
    ...overrides,
  };
}

describe("RFICard / status-gated render", () => {
  test("answer button renders for open RFIs when onAnswer is supplied", () => {
    render(<RFICard rfi={makeRfi({ status: "open" })} onAnswer={() => {}} />);
    expect(screen.getByRole("button", { name: /trả lời/i })).toBeInTheDocument();
  });

  test("answer button is hidden for answered / closed RFIs even with onAnswer", () => {
    const { rerender } = render(
      <RFICard rfi={makeRfi({ status: "answered" })} onAnswer={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: /trả lời/i })).not.toBeInTheDocument();

    rerender(<RFICard rfi={makeRfi({ status: "closed" })} onAnswer={() => {}} />);
    expect(screen.queryByRole("button", { name: /trả lời/i })).not.toBeInTheDocument();
  });

  test("answer button is hidden when onAnswer is not supplied (read-only listing)", () => {
    render(<RFICard rfi={makeRfi({ status: "open" })} />);
    expect(screen.queryByRole("button", { name: /trả lời/i })).not.toBeInTheDocument();
  });
});

describe("RFICard / overdue computation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-01T00:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("due_date in the past + open status → renders 'trễ hạn'", () => {
    render(<RFICard rfi={makeRfi({ status: "open", due_date: "2026-04-15" })} />);
    // "trễ hạn" is the localized "overdue" tag the source appends
    expect(screen.getByText(/trễ hạn/)).toBeInTheDocument();
  });

  test("due_date in the past + closed status → NOT marked overdue", () => {
    // Closed RFIs that happen to have stale due_dates shouldn't keep
    // showing the red overdue treatment forever. The source explicitly
    // gates on `status !== "closed"`.
    render(<RFICard rfi={makeRfi({ status: "closed", due_date: "2026-04-15" })} />);
    expect(screen.queryByText(/trễ hạn/)).not.toBeInTheDocument();
  });

  test("future due_date → NOT marked overdue", () => {
    render(<RFICard rfi={makeRfi({ status: "open", due_date: "2026-06-01" })} />);
    expect(screen.queryByText(/trễ hạn/)).not.toBeInTheDocument();
  });
});

describe("RFICard / click handlers", () => {
  test("clicking the card invokes onOpen with the RFI", async () => {
    const onOpen = vi.fn();
    render(<RFICard rfi={makeRfi()} onOpen={onOpen} />);

    await userEvent.click(screen.getByRole("article"));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "rfi-1" }));
  });

  test("clicking the answer button does NOT bubble to onOpen", async () => {
    // The handler stops propagation. Without this, every "Trả lời"
    // click would also fire onOpen, opening the detail drawer at the
    // same time the answer dialog appeared.
    const onOpen = vi.fn();
    const onAnswer = vi.fn();
    render(
      <RFICard rfi={makeRfi({ status: "open" })} onOpen={onOpen} onAnswer={onAnswer} />,
    );

    await userEvent.click(screen.getByRole("button", { name: /trả lời/i }));

    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });
});

describe("RFICard / metadata footer", () => {
  test("doc-count footer renders only when related_document_ids is non-empty", () => {
    const { rerender } = render(
      <RFICard rfi={makeRfi({ related_document_ids: ["a", "b", "c"] })} />,
    );
    expect(screen.getByText(/3 tài liệu/)).toBeInTheDocument();

    rerender(<RFICard rfi={makeRfi({ related_document_ids: [] })} />);
    expect(screen.queryByText(/tài liệu/)).not.toBeInTheDocument();
  });
});
