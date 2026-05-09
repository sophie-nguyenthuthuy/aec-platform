/**
 * Meta-pin: every `/admin/*` page that exists in the codebase
 * MUST be referenced from `docs/admin-surfaces.md` (the master
 * index that's the single source of truth for "which dashboards
 * exist").
 *
 * Why this exists: the master index has a 10-step contribution
 * checklist for new admin surfaces. Step 10 is "update this
 * index." Steps 1-9 are functional changes (router, hook, page,
 * pin) that produce green CI immediately; step 10 is a docs
 * update that nobody enforces.
 *
 * Without this pin, the failure mode is:
 *
 *   1. Engineer ships a new admin page through steps 1-9. CI
 *      green. PR merges.
 *   2. Index doc not updated. Nobody finds the new page during
 *      an incident — it's not in `docs/admin-surfaces.md`.
 *   3. On-call rotation flips to a fresh engineer 6 weeks later.
 *      They open the index. Don't see the page. Don't know it
 *      exists.
 *
 * This pin closes that loop by failing CI when a `/admin/*`
 * directory exists in the source tree but isn't mentioned in
 * the index doc. The fix is one-line ("add a row to
 * `docs/admin-surfaces.md`"), and the failing test message
 * spells out exactly which row to add.
 */

import { describe, expect, test } from "vitest";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";


// Paths anchored to the repo root so the test works whether vitest
// runs from the apps/web subdir or via a workspace runner.
// __dirname = `…/aec-platform/apps/web/app/(dashboard)/admin/__tests__`
// → 6 levels up reaches the repo root.
const REPO_ROOT = resolve(__dirname, "..", "..", "..", "..", "..", "..");
const ADMIN_DIR = resolve(__dirname, "..");
const SURFACES_INDEX = join(REPO_ROOT, "docs/admin-surfaces.md");


/** List the immediate sub-directories under `app/(dashboard)/admin/`
 *  — each is one admin page (or page family with its own `[id]`
 *  drilldown).
 *
 *  Skips `__tests__` (this file's own dir) and any non-directory
 *  entries (the `page.tsx` for the landing).
 */
function adminPageSlugs(): string[] {
  const entries = readdirSync(ADMIN_DIR);
  return entries.filter((name) => {
    if (name === "__tests__") return false;
    const full = join(ADMIN_DIR, name);
    if (!statSync(full).isDirectory()) return false;
    // Each slug-dir should have a page.tsx — defensive check.
    // (Empty dirs left over from refactors don't count as "live"
    // admin pages.)
    return existsSync(join(full, "page.tsx"));
  });
}


describe("docs/admin-surfaces.md / meta-coverage", () => {
  test("the master index file exists", () => {
    // Without the index, this whole pin is moot. Surface the
    // missing-file case loudly with a fix-it message.
    expect(existsSync(SURFACES_INDEX)).toBe(true);
  });

  test("every /admin/* page directory is referenced in docs/admin-surfaces.md", () => {
    const indexContent = readFileSync(SURFACES_INDEX, "utf-8");
    const slugs = adminPageSlugs();

    // Should match the count + composition of the EXPECTED_TILES
    // pin in `page.test.tsx` (the landing-page tile pin). If they
    // diverge, one of them is wrong — the contribution checklist
    // says BOTH have to update together.
    expect(slugs.length).toBeGreaterThan(0);

    const missing: string[] = [];
    for (const slug of slugs) {
      // The index references each page by its full URL `/admin/<slug>`.
      // We require an exact substring match — a markdown-table row
      // would render as e.g. `| /admin/scrapers |`, which contains
      // the literal `/admin/scrapers`.
      if (!indexContent.includes(`/admin/${slug}`)) {
        missing.push(slug);
      }
    }

    expect(missing).toEqual([]);

    // Friendly fix-it message: if missing is non-empty, the test
    // above fails AND we surface a more readable error.
    if (missing.length > 0) {
      throw new Error(
        `These admin pages are missing from docs/admin-surfaces.md:\n  ${missing
          .map((s) => `/admin/${s}`)
          .join("\n  ")}\n\n` +
          "Add a row to the appropriate table in docs/admin-surfaces.md " +
          "(triage or configuration), with columns: URL, runbook, backend " +
          "pin, frontend pin. See the contribution checklist at the bottom " +
          "of that doc for the full per-page expectations.",
      );
    }
  });

  test("every referenced /admin/* URL in the index has a matching page directory", () => {
    // Inverse direction: catches stale doc rows for retired pages.
    // If the doc lists `/admin/foo` but the dir doesn't exist,
    // ops will follow the doc to a 404.
    const indexContent = readFileSync(SURFACES_INDEX, "utf-8");

    // Match `/admin/<slug>` only when the slug isn't followed by
    // another path segment. The contribution checklist in the doc
    // references file paths like `apps/web/app/(dashboard)/admin/X/page.tsx`
    // — those would match `X` if we accepted any continuation.
    // The `(?![/.])` lookahead excludes those (a real URL slug is
    // followed by space, ` | `, `)`, newline, or `[id]` for drilldowns).
    const matches = indexContent.matchAll(
      /\/admin\/([a-zA-Z0-9_-]+)(?![/.a-zA-Z0-9_-])/g,
    );
    const referencedSlugs = new Set<string>();
    for (const m of matches) {
      const slug = m[1]!;
      // Filter out the documented placeholder. The contribution
      // checklist uses `/admin/X` as a literal stand-in for "your
      // new admin slug" — it's never a real URL. Real slugs are
      // kebab-case lowercase strings of length ≥ 2.
      if (slug === "X") continue;
      referencedSlugs.add(slug);
    }

    const liveSlugs = new Set(adminPageSlugs());

    const stale: string[] = [];
    for (const slug of referencedSlugs) {
      // The landing page itself is at `/admin` (no slug); skip.
      // Drilldown paths like `/admin/webhook-deliveries/[id]` are
      // matched as `webhook-deliveries` which IS a valid slug.
      if (!liveSlugs.has(slug)) {
        stale.push(slug);
      }
    }

    expect(stale).toEqual([]);

    if (stale.length > 0) {
      throw new Error(
        `docs/admin-surfaces.md references admin pages that don't exist:\n  ${stale
          .map((s) => `/admin/${s}`)
          .join("\n  ")}\n\n` +
          "Either the page was retired (remove the row from the index) or " +
          "the dir was renamed (update the index to match). The index is the " +
          "discovery surface for on-call; stale rows lead to 404s during incidents.",
      );
    }
  });
});


describe("docs/admin-surfaces.md / runbook coverage hint", () => {
  // This is a soft-warn rather than a hard pin. Some pages
  // legitimately don't need a runbook (api-usage is pure
  // observability with no escalation path). But the EXPECTED set
  // here is the documented "should have a runbook" subset; if
  // this list grows without runbooks landing, future on-call
  // rotations get less and less context during incidents.
  const PAGES_WITH_RUNBOOKS = [
    "webhook-deliveries",
    "slack-deliveries",
    "crons",
  ];

  for (const slug of PAGES_WITH_RUNBOOKS) {
    test(`docs/runbook-${slug}.md (or runbook-cron-admin.md for crons) is referenced from the index`, () => {
      const indexContent = readFileSync(SURFACES_INDEX, "utf-8");
      // The index links to the runbook with a relative-link macro
      // like `[`runbook-X.md`](runbook-X.md)`. We just substring-
      // match the filename.
      // `crons` runbook is named `runbook-cron-admin.md` (set by
      // the historical filename) — accept either form.
      const runbookCandidates = [
        `runbook-${slug}.md`,
        slug === "crons" ? "runbook-cron-admin.md" : null,
      ].filter((x): x is string => x !== null);

      const matched = runbookCandidates.some((c) => indexContent.includes(c));

      expect(matched).toBe(true);

      if (!matched) {
        throw new Error(
          `Page /admin/${slug} should have a runbook referenced from ` +
            `docs/admin-surfaces.md (one of: ${runbookCandidates.join(", ")}). ` +
            "On-call needs a runbook for incident-grade dashboards.",
        );
      }
    });
  }
});
