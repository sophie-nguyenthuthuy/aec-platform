import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { RAGStatus } from "../RAGStatus";

/**
 * RAGStatus is the smallest possible "value-driven render" component:
 * a single status enum drives the label + colour + dot. Easy to lock
 * down — and useful as a regression target since these labels appear
 * across most dashboards (project hub, weekly reports, schedule risk).
 */

describe("RAGStatus / Vietnamese labels (default)", () => {
  test("green → 'Tốt'", () => {
    render(<RAGStatus status="green" />);
    expect(screen.getByText("Tốt")).toBeInTheDocument();
  });

  test("amber → 'Cần chú ý'", () => {
    render(<RAGStatus status="amber" />);
    expect(screen.getByText("Cần chú ý")).toBeInTheDocument();
  });

  test("red → 'Rủi ro cao'", () => {
    render(<RAGStatus status="red" />);
    expect(screen.getByText("Rủi ro cao")).toBeInTheDocument();
  });
});

describe("RAGStatus / English labels", () => {
  test("language='en' switches the localized strings", () => {
    const { rerender } = render(<RAGStatus status="green" language="en" />);
    expect(screen.getByText("On track")).toBeInTheDocument();

    rerender(<RAGStatus status="amber" language="en" />);
    expect(screen.getByText("Needs attention")).toBeInTheDocument();

    rerender(<RAGStatus status="red" language="en" />);
    expect(screen.getByText("At risk")).toBeInTheDocument();
  });
});

describe("RAGStatus / accessibility", () => {
  test("aria-label matches the visible label (screen-reader picks up the same text)", () => {
    render(<RAGStatus status="amber" />);
    // aria-label IS "Cần chú ý" too, so the accessible name lookup
    // should find it without ambiguity.
    expect(screen.getByLabelText("Cần chú ý")).toBeInTheDocument();
  });

  test("custom className is appended (not replaced)", () => {
    const { container } = render(
      <RAGStatus status="green" className="ml-auto" />,
    );
    const span = container.querySelector("span")!;
    expect(span.className).toContain("ml-auto");
    // Status colour class still applied.
    expect(span.className).toContain("emerald");
  });
});
