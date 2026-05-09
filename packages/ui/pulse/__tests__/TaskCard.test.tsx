import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { TaskCard } from "../TaskCard";
import type { Task } from "@aec/types/pulse";

/**
 * TaskCard mirrors RFICard's overdue-flag pattern (overdue = past due_date
 * AND status !== done) but adds keyboard support: Enter / Space on the
 * card triggers onClick. That's a real a11y contract — the Pulse Kanban
 * has no other way to "open" a card without a mouse.
 */

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    organization_id: "org-1",
    project_id: "project-1",
    parent_id: null,
    title: "Review structural drawings",
    description: null,
    status: "todo",
    priority: "normal",
    assignee_id: null,
    phase: "design",
    discipline: null,
    start_date: null,
    due_date: null,
    completed_at: null,
    position: 1,
    tags: [],
    created_by: null,
    created_at: "2026-04-20T00:00:00Z",
    ...overrides,
  };
}

describe("TaskCard / keyboard interaction", () => {
  test("Enter key on the card fires onClick (a11y)", async () => {
    const onClick = vi.fn();
    render(<TaskCard task={makeTask()} onClick={onClick} />);

    const card = screen.getByRole("button");
    card.focus();
    await userEvent.keyboard("{Enter}");

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ id: "task-1" }));
  });

  test("Space key on the card also fires onClick (a11y)", async () => {
    const onClick = vi.fn();
    render(<TaskCard task={makeTask()} onClick={onClick} />);

    const card = screen.getByRole("button");
    card.focus();
    await userEvent.keyboard(" ");

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  test("other keys do nothing (no false positive on, say, Tab or Esc)", async () => {
    const onClick = vi.fn();
    render(<TaskCard task={makeTask()} onClick={onClick} />);

    screen.getByRole("button").focus();
    await userEvent.keyboard("{Escape}");
    await userEvent.keyboard("a");

    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("TaskCard / drag wiring", () => {
  test("onDragStart fires with the task when dragged", () => {
    const onDragStart = vi.fn();
    render(
      <TaskCard task={makeTask()} draggable onDragStart={onDragStart} />,
    );

    // jsdom doesn't fire a real drag, but firing the synthetic event is
    // sufficient to exercise the handler.
    const card = screen.getByRole("button");
    card.dispatchEvent(new Event("dragstart", { bubbles: true }));

    expect(onDragStart).toHaveBeenCalledWith(
      expect.objectContaining({ id: "task-1" }),
    );
  });

  test("draggable={false} (default) → element is not draggable", () => {
    render(<TaskCard task={makeTask()} />);
    const card = screen.getByRole("button");
    // React maps draggable={undefined} to the absence of the attribute.
    expect(card.getAttribute("draggable")).not.toBe("true");
  });
});

describe("TaskCard / overdue treatment", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-01T00:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("past due_date + non-done status → due-date span gets rose colour", () => {
    const { container } = render(
      <TaskCard task={makeTask({ due_date: "2026-04-15", status: "in_progress" })} />,
    );
    // The due-date span gets the rose-600 text colour.
    const dueSpan = container.querySelector('[class*="rose-600"]');
    expect(dueSpan).not.toBeNull();
  });

  test("done tasks shed the overdue treatment even with stale due_date", () => {
    const { container } = render(
      <TaskCard task={makeTask({ due_date: "2026-04-15", status: "done" })} />,
    );
    expect(container.querySelector('[class*="rose-600"]')).toBeNull();
  });
});

describe("TaskCard / tag truncation", () => {
  test("only the first 2 tags render (UI cap)", () => {
    render(
      <TaskCard task={makeTask({ tags: ["urgent", "blocker", "design", "v2"] })} />,
    );

    expect(screen.getByText("urgent")).toBeInTheDocument();
    expect(screen.getByText("blocker")).toBeInTheDocument();
    expect(screen.queryByText("design")).not.toBeInTheDocument();
    expect(screen.queryByText("v2")).not.toBeInTheDocument();
  });
});
