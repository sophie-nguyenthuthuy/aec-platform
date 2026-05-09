// Extend Vitest's `expect` with Testing Library's DOM matchers
// (`toBeInTheDocument`, `toHaveClass`, etc.). Without this, every
// matcher would have to be hand-rolled.
import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// `next/link` is a server-aware client component that pulls in router
// context jsdom can't provide. For component tests we just want a
// passthrough `<a>` — the link's job (href passthrough, click bubbling)
// is fully expressible as a plain anchor here. Anything that depends
// on prefetch / route-level state belongs in the Playwright lane.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));
