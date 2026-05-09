import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { CitationCard } from "../CitationCard";
import type { Citation } from "../types";

/**
 * CitationCard renders the bottom of every CodeGuard answer. Two
 * branches worth pinning:
 *
 *   1. `index !== undefined` toggles the "[N+1]" prefix. Common bug
 *      shape: `if (index)` instead of `if (index !== undefined)` —
 *      that would hide the prefix when index === 0 (which is exactly
 *      the case the codeguard query page passes most often).
 *   2. `source_url` toggles the external "Nguồn" link. Citations
 *      backfilled from PDF excerpts have no source_url and the link
 *      must NOT render (otherwise the user clicks an empty href).
 */

function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    regulation_id: "reg-1",
    regulation: "QCVN 06:2022/BXD",
    section: "3.2.1",
    excerpt: "Hành lang thoát nạn ≥ 1.4m...",
    source_url: null,
    ...overrides,
  };
}

describe("CitationCard / index prefix", () => {
  test("index=0 still renders '[1]' — guarding against if(index) truthy bug", () => {
    render(<CitationCard citation={makeCitation()} index={0} />);
    expect(screen.getByText(/\[1\]/)).toBeInTheDocument();
  });

  test("index=2 renders '[3]'", () => {
    render(<CitationCard citation={makeCitation()} index={2} />);
    expect(screen.getByText(/\[3\]/)).toBeInTheDocument();
  });

  test("no index supplied → no '[N]' prefix at all", () => {
    render(<CitationCard citation={makeCitation()} />);
    expect(screen.queryByText(/\[\d+\]/)).not.toBeInTheDocument();
  });
});

describe("CitationCard / source link", () => {
  test("source_url present → 'Nguồn' link with target=_blank", () => {
    render(
      <CitationCard
        citation={makeCitation({ source_url: "https://example.com/qcvn-06.pdf" })}
      />,
    );

    const link = screen.getByRole("link", { name: /nguồn/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "https://example.com/qcvn-06.pdf");
    expect(link).toHaveAttribute("target", "_blank");
    // rel="noreferrer" is a small but real security thing — opening a
    // user-supplied URL in a new tab without it leaks window.opener.
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  test("source_url null → no link rendered (no empty-href footgun)", () => {
    render(<CitationCard citation={makeCitation({ source_url: null })} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("CitationCard / always-on content", () => {
  test("regulation + section render together as 'QCVN 06:2022/BXD § 3.2.1'", () => {
    const { container } = render(<CitationCard citation={makeCitation()} />);
    // The two pieces are in adjacent spans — match the combined text
    // content rather than each separately.
    expect(container.textContent).toMatch(/QCVN 06:2022\/BXD/);
    expect(container.textContent).toMatch(/§ 3\.2\.1/);
  });

  test("excerpt renders as a blockquote", () => {
    const { container } = render(<CitationCard citation={makeCitation()} />);
    const quote = container.querySelector("blockquote");
    expect(quote).not.toBeNull();
    expect(quote!.textContent).toMatch(/Hành lang thoát nạn ≥ 1\.4m/);
  });
});
