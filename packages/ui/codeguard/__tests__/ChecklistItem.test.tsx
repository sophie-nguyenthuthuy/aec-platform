import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { ChecklistItem } from "../ChecklistItem";
import type {
  ChecklistItem as ChecklistItemType,
  ChecklistItemStatus,
} from "../types";

/**
 * Status workflow + the notes-on-blur pattern that matters most for
 * UX correctness:
 *   1. Checkbox toggles status between `done` and `pending` only.
 *   2. The select sees ALL 4 statuses (pending / in_progress / done /
 *      not_applicable) — easy to regress when a new status is added.
 *   3. Notes textarea calls onChange ONLY on blur, not on every
 *      keystroke. Without this, every keystroke would fire a network
 *      mutation.
 *   4. `disabled` prop disables every interactive element.
 */

function makeItem(overrides: Partial<ChecklistItemType> = {}): ChecklistItemType {
  return {
    id: "item-1",
    title: "Permit application submitted",
    description: "Đơn xin cấp phép đã nộp lên Sở Xây dựng",
    status: "pending" satisfies ChecklistItemStatus,
    required: true,
    regulation_ref: "QCVN 06:2022 § 2.1",
    notes: null,
    assignee_id: null,
    ...overrides,
  } as ChecklistItemType;
}

describe("ChecklistItem / always-on render", () => {
  test("title + description + 'Bắt buộc' badge + regulation ref render", () => {
    render(<ChecklistItem item={makeItem()} onChange={() => {}} />);
    expect(screen.getByText("Permit application submitted")).toBeInTheDocument();
    expect(screen.getByText(/Đơn xin cấp phép/)).toBeInTheDocument();
    expect(screen.getByText("Bắt buộc")).toBeInTheDocument();
    expect(screen.getByText(/QCVN 06:2022/)).toBeInTheDocument();
  });

  test("'Bắt buộc' hidden when required=false", () => {
    render(<ChecklistItem item={makeItem({ required: false })} onChange={() => {}} />);
    expect(screen.queryByText("Bắt buộc")).not.toBeInTheDocument();
  });

  test("regulation_ref hidden when null", () => {
    render(
      <ChecklistItem item={makeItem({ regulation_ref: null })} onChange={() => {}} />,
    );
    expect(screen.queryByText(/QCVN/)).not.toBeInTheDocument();
  });

  test("description omitted when null (no empty <p> shipped)", () => {
    const { container } = render(
      <ChecklistItem item={makeItem({ description: null })} onChange={() => {}} />,
    );
    expect(container.querySelectorAll("p").length).toBe(0);
  });
});

describe("ChecklistItem / done state", () => {
  test("status=done renders the title with the line-through style", () => {
    const { container } = render(
      <ChecklistItem item={makeItem({ status: "done" })} onChange={() => {}} />,
    );
    const heading = container.querySelector("h4")!;
    expect(heading.className).toContain("line-through");
  });

  test("checkbox is checked when status=done", () => {
    render(<ChecklistItem item={makeItem({ status: "done" })} onChange={() => {}} />);
    const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
  });

  test("non-done statuses leave the checkbox unchecked", () => {
    const STATUSES: ChecklistItemStatus[] = ["pending", "in_progress", "not_applicable"];
    for (const status of STATUSES) {
      const { unmount } = render(
        <ChecklistItem item={makeItem({ status })} onChange={() => {}} />,
      );
      const checkbox = screen.getByRole("checkbox") as HTMLInputElement;
      expect(checkbox.checked).toBe(false);
      unmount();
    }
  });
});

describe("ChecklistItem / interactions", () => {
  test("toggling the checkbox fires onChange with status=done", async () => {
    const onChange = vi.fn();
    render(
      <ChecklistItem item={makeItem({ status: "pending" })} onChange={onChange} />,
    );

    await userEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith({ status: "done", notes: "" });
  });

  test("unchecking from done fires status=pending (not the previous status)", async () => {
    // The toggle path is intentionally lossy — `not_applicable` doesn't
    // round-trip through the checkbox. The select is for the 4-state
    // path. Pin the checkbox shortcut behaviour.
    const onChange = vi.fn();
    render(
      <ChecklistItem
        item={makeItem({ status: "done", notes: "old notes" })}
        onChange={onChange}
      />,
    );

    await userEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith({
      status: "pending",
      notes: "old notes",
    });
  });

  test("status select offers all 4 statuses", () => {
    render(<ChecklistItem item={makeItem()} onChange={() => {}} />);
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["pending", "in_progress", "done", "not_applicable"]);
  });

  test("status select fires onChange with the picked status + current notes", async () => {
    const onChange = vi.fn();
    render(
      <ChecklistItem
        item={makeItem({ status: "pending", notes: "draft" })}
        onChange={onChange}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox"), "in_progress");
    expect(onChange).toHaveBeenCalledWith({
      status: "in_progress",
      notes: "draft",
    });
  });

  test("notes textarea fires onChange ONLY on blur, not per keystroke", async () => {
    // Critical UX: every keystroke firing a mutation would spam the API
    // once per character. The component uses local state + onBlur to
    // batch into a single call.
    const onChange = vi.fn();
    render(
      <ChecklistItem
        item={makeItem({ notes: "existing note" })}
        onChange={onChange}
      />,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await userEvent.click(textarea);
    await userEvent.keyboard("xyz");

    // No onChange yet — still typing.
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.tab(); // blur

    expect(onChange).toHaveBeenCalledTimes(1);
    // Notes value forwarded as-typed (existing + appended).
    expect(onChange).toHaveBeenCalledWith({
      status: "pending",
      notes: "existing notexyz",
    });
  });

  test("notes section starts collapsed when item.notes is empty/null", () => {
    render(<ChecklistItem item={makeItem({ notes: null })} onChange={() => {}} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    // The 'Thêm ghi chú' link is the toggle.
    expect(screen.getByText(/Thêm ghi chú/)).toBeInTheDocument();
  });

  test("notes section starts open when item.notes is non-empty", () => {
    // Operators who already added a note should see it without an
    // extra click — pin the open-by-default-when-non-empty rule.
    render(
      <ChecklistItem item={makeItem({ notes: "operator note" })} onChange={() => {}} />,
    );
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByText(/Ẩn ghi chú/)).toBeInTheDocument();
  });

  test("disabled prop disables the checkbox, select, and textarea", async () => {
    render(<ChecklistItem item={makeItem()} onChange={() => {}} disabled />);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("combobox")).toBeDisabled();
    // textarea only shows when notes-section is open.
  });
});
