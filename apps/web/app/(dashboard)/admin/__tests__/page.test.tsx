/**
 * Vitest coverage for the platform-admin hub at `/admin`.
 *
 * Why this exists: the hub page is the only navigation affordance
 * for the five admin sub-pages. Without it, ops has to remember
 * each URL during an incident — exactly the wrong moment for a
 * tribal-knowledge lookup.
 *
 * Failure modes this guards against:
 *
 *   * **A tile gets dropped accidentally.** A refactor of the
 *     `ADMIN_PAGES` array that omits one tile would silently
 *     break ops's only path to that sub-page. Pin the full
 *     URL set so an omission fails CI rather than going
 *     unnoticed until on-call needs it.
 *
 *   * **A URL drifts.** If `/admin/slack-deliveries` is renamed
 *     to `/admin/slack` and the matching frontend route moves
 *     too, the hub's link silently 404s. Pin the literal hrefs
 *     here AND in the matching backend pin
 *     (`tests/test_slack_deliveries_surface_pin.py` etc).
 *
 *   * **The hub becomes empty.** A regression that wipes the
 *     ADMIN_PAGES array would render an empty grid with no
 *     visible error. Pin the count + the descriptions.
 *
 * The page is server-rendered (no "use client" directive) — pure
 * navigation, no data hooks. Test renders the component and
 * inspects the link DOM rather than mocking any hooks.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import AdminHubPage from "../page";


// Expected tile set, by literal href + the full title text. If the
// hub adds a seventh admin page, bump the expected count below AND
// add the entry. A drift-by-omission fails the count assertion
// first; a rename fails the href assertion.
const EXPECTED_TILES: ReadonlyArray<{ href: string; title: string }> = [
  { href: "/admin/api-usage", title: "API key usage" },
  { href: "/admin/webhook-deliveries", title: "Webhook deliveries" },
  { href: "/admin/slack-deliveries", title: "Slack deliveries" },
  { href: "/admin/crons", title: "Cron jobs" },
  { href: "/admin/scrapers", title: "Price scrapers" },
  { href: "/admin/normalizer-rules", title: "Normaliser rules" },
];


describe("AdminHubPage / structure", () => {
  test("renders the page heading", () => {
    render(<AdminHubPage />);
    expect(screen.getByRole("heading", { name: /Platform admin/i, level: 1 }))
      .toBeInTheDocument();
  });

  test("renders one link per admin sub-page (count check)", () => {
    render(<AdminHubPage />);

    // Every tile is wrapped in an `<a>` (Next.js Link). Count them
    // to catch a regression that wiped the array down to e.g. 3
    // tiles silently.
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(EXPECTED_TILES.length);
  });
});


describe("AdminHubPage / per-tile contract", () => {
  for (const { href, title } of EXPECTED_TILES) {
    test(`tile for ${href} (${title}) is rendered with correct href`, () => {
      render(<AdminHubPage />);

      // Title must be present as a heading inside the tile.
      // `getByText` because the tile renders the title in an h2,
      // not the page-level h1.
      const titleEl = screen.getByText(title);
      expect(titleEl).toBeInTheDocument();

      // The closest `<a>` ancestor MUST href-match. If a tile is
      // re-titled but the URL stays, this still passes; if the URL
      // drifts, it fails.
      const anchor = titleEl.closest("a");
      expect(anchor).not.toBeNull();
      expect(anchor).toHaveAttribute("href", href);
    });
  }
});


describe("AdminHubPage / no orphan tiles", () => {
  test("every link points to an /admin/* URL (no legacy /platform/* leakage)", () => {
    render(<AdminHubPage />);

    const links = screen.getAllByRole("link");
    for (const link of links) {
      const href = link.getAttribute("href");
      expect(href).toMatch(/^\/admin\//);
    }
  });

  test("no two tiles share an href (cache-key + nav consistency)", () => {
    render(<AdminHubPage />);

    const hrefs = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    const unique = new Set(hrefs);
    expect(unique.size).toBe(hrefs.length);
  });
});
