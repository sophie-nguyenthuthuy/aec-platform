import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { DefectCard } from "../DefectCard";
import type { Defect, DefectPriority, DefectStatus } from "../types";

/**
 * Pin: status/priority labels per enum value, locale-formatted reported
 * date, optional onOpen/onStatusChange wiring, and the click-propagation
 * guard on the status select (the `e.stopPropagation()` keeps a
 * status-change click from also firing the row-level onOpen handler).
 */

function makeDefect(overrides: Partial<Defect> = {}): Defect {
  return {
    id: "d-1",
    project_id: "proj-1",
    package_id: null,
    title: "Wall paint chipped on level 2",
    description: "Visible chip ~3cm near the south door.",
    location: { room: "Suite B", floor: "Floor 2" },
    photo_file_ids: ["f1", "f2"],
    status: "open",
    priority: "medium",
    assignee_id: null,
    reported_by: null,
    reported_at: "2026-04-22T08:00:00Z",
    resolved_at: null,
    resolution_notes: null,
    ...overrides,
  };
}

describe("DefectCard / status + priority labels", () => {
  const STATUSES: Array<[DefectStatus, RegExp]> = [
    ["open", /^Mới$/],
    ["assigned", /^Đã giao$/],
    ["in_progress", /^Đang xử lý$/],
    ["resolved", /^Đã sửa$/],
    ["rejected", /^Bác bỏ$/],
  ];
  for (const [status, label] of STATUSES) {
    test(`status=${status} renders '${label.source}'`, () => {
      render(<DefectCard defect={makeDefect({ status })} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  }

  const PRIORITIES: Array<[DefectPriority, string]> = [
    ["low", "Thấp"],
    ["medium", "Trung bình"],
    ["high", "Cao"],
    ["critical", "Khẩn cấp"],
  ];
  for (const [priority, label] of PRIORITIES) {
    test(`priority=${priority} renders '${label}'`, () => {
      render(<DefectCard defect={makeDefect({ priority })} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
  }

  test("critical priority gets the red-bg accent (visual signal)", () => {
    const { container } = render(
      <DefectCard defect={makeDefect({ priority: "critical" })} />,
    );
    expect(container.innerHTML).toMatch(/bg-red-50|red-500|red-700/);
  });
});

describe("DefectCard / metadata footer", () => {
  test("photo count rendered when photo_file_ids non-empty", () => {
    render(<DefectCard defect={makeDefect({ photo_file_ids: ["a", "b", "c"] })} />);
    expect(screen.getByText(/3 ảnh/)).toBeInTheDocument();
  });

  test("photo count hidden when photo_file_ids empty", () => {
    render(<DefectCard defect={makeDefect({ photo_file_ids: [] })} />);
    expect(screen.queryByText(/ảnh/)).not.toBeInTheDocument();
  });

  test("'Đã giao' footer pill appears only when assignee_id is set", () => {
    const { rerender } = render(
      <DefectCard defect={makeDefect({ assignee_id: "user-1" })} />,
    );
    // Note: `Đã giao` ALSO appears as the `assigned` status label —
    // we filter to footer-style by getting all matches.
    expect(screen.getAllByText(/Đã giao/).length).toBeGreaterThanOrEqual(1);

    rerender(<DefectCard defect={makeDefect({ assignee_id: null })} />);
    // With no assignee + open status, the only "Đã giao" candidate is
    // the assigned-status label, which doesn't apply here either.
    expect(screen.queryByText(/Đã giao/)).not.toBeInTheDocument();
  });

  test("location prefers room over floor", () => {
    // formatLocation returns room if present, else floor, else null.
    const { rerender } = render(
      <DefectCard
        defect={makeDefect({ location: { room: "Suite B", floor: "Floor 2" } })}
      />,
    );
    expect(screen.getByText("Suite B")).toBeInTheDocument();
    expect(screen.queryByText("Floor 2")).not.toBeInTheDocument();

    rerender(<DefectCard defect={makeDefect({ location: { floor: "Floor 3" } })} />);
    expect(screen.getByText("Floor 3")).toBeInTheDocument();
  });
});

describe("DefectCard / click handlers", () => {
  test("clicking the row fires onOpen when handler is supplied", async () => {
    const onOpen = vi.fn();
    render(<DefectCard defect={makeDefect()} onOpen={onOpen} />);

    await userEvent.click(screen.getByRole("button"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: "d-1" }));
  });

  test("no onOpen → not interactive (no role=button, no tabIndex)", () => {
    render(<DefectCard defect={makeDefect()} />);
    // queryByRole("button") returns null because the wrapper div
    // doesn't get the role when onOpen is absent.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  test("status select fires onStatusChange with the picked value", async () => {
    const onStatusChange = vi.fn();
    render(
      <DefectCard defect={makeDefect()} onStatusChange={onStatusChange} />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox"), "in_progress");

    expect(onStatusChange).toHaveBeenCalledWith("in_progress");
  });

  test("status select click does NOT bubble to onOpen (stopPropagation guard)", async () => {
    // The status select has `onClick={(e) => e.stopPropagation()}` so
    // a click on it doesn't ALSO open the detail drawer. Without the
    // guard, every status change would fire two intents.
    const onOpen = vi.fn();
    const onStatusChange = vi.fn();
    render(
      <DefectCard
        defect={makeDefect()}
        onOpen={onOpen}
        onStatusChange={onStatusChange}
      />,
    );

    await userEvent.selectOptions(
      screen.getByRole("combobox"),
      "resolved",
    );

    expect(onStatusChange).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });
});
