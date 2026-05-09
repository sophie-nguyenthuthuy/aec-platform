import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { DisciplineTag } from "../DisciplineTag";

describe("DisciplineTag", () => {
  test("renders the discipline label uppercase for each known value", () => {
    const { rerender } = render(<DisciplineTag discipline="architectural" />);
    expect(screen.getByText("ARCH")).toBeInTheDocument();

    rerender(<DisciplineTag discipline="structural" />);
    expect(screen.getByText("STRUCT")).toBeInTheDocument();

    rerender(<DisciplineTag discipline="mep" />);
    expect(screen.getByText("MEP")).toBeInTheDocument();

    rerender(<DisciplineTag discipline="civil" />);
    expect(screen.getByText("CIVIL")).toBeInTheDocument();
  });

  test("renders an em-dash when discipline is null", () => {
    render(<DisciplineTag discipline={null} />);
    // The fallback path uses an em-dash literal as the visible text.
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  test("renders an em-dash when discipline is undefined", () => {
    // Undefined matters because the source uses `if (!discipline)` which
    // catches both null and undefined. A regression that drops one of the
    // two falsy checks would still pass the null test above.
    render(<DisciplineTag discipline={undefined} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  test("size='sm' applies the smaller padding/text class", () => {
    const { container } = render(
      <DisciplineTag discipline="architectural" size="sm" />,
    );
    const span = container.querySelector("span")!;
    expect(span.className).toContain("px-1.5");
    expect(span.className).toContain("text-[10px]");
  });

  test("default size is md", () => {
    const { container } = render(<DisciplineTag discipline="architectural" />);
    const span = container.querySelector("span")!;
    expect(span.className).toContain("px-2");
    expect(span.className).toContain("text-xs");
  });

  test("custom className is appended (not replaced)", () => {
    const { container } = render(
      <DisciplineTag discipline="architectural" className="extra-cls" />,
    );
    const span = container.querySelector("span")!;
    expect(span.className).toContain("extra-cls");
    // The discipline-specific colour class still applies — `cn()` merges
    // rather than overrides.
    expect(span.className).toContain("violet");
  });
});
