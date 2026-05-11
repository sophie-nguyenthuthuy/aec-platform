/**
 * Admin hub — `/admin`.
 *
 * Lists every platform-admin sub-page with a one-line description.
 * Without this index, the five admin sub-pages (api-usage,
 * normalizer-rules, scrapers, slack-deliveries, webhook-deliveries)
 * are reachable only by typing the URL or via deep-links — there's
 * no discovery affordance from the dashboard nav.
 *
 * Section grid pattern matches `/codeguard` and `/costpulse` hub
 * pages elsewhere in the app for visual consistency.
 *
 * Server-side `require_role("admin")` already gates each sub-page's
 * api endpoints; this index is just a navigation surface, so it
 * renders for everyone (clicking through reveals the 403 banner on
 * the page that's actually gated). Cleaner than a page-level role
 * check that hides links — admins on a fresh org might end up here
 * without realising they need to set up an org first.
 */

import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  Archive,
  ChartLine,
  Clock,
  FlaskConical,
  GitBranch,
  Send,
} from "lucide-react";


// One source of truth for the hub layout. Adding a new admin page
// = one entry here + a new directory under `/admin/`. Order picks
// frequency: ops opens api-usage and the two delivery dashboards
// during incidents (top); normalizer-rules + scrapers are
// configuration UIs that get touched weekly at most (bottom).
const ADMIN_PAGES = [
  {
    href: "/admin/api-usage",
    title: "API key usage",
    description:
      "Cross-org leaderboard of API keys by call volume. Click a row to drill into hour-bucketed telemetry.",
    icon: Activity,
  },
  {
    href: "/admin/webhook-deliveries",
    title: "Webhook deliveries",
    description:
      "Cross-tenant webhook outbox health. Per-event-type delivery rate, failures by org, drilldown to error messages.",
    icon: Send,
  },
  {
    href: "/admin/slack-deliveries",
    title: "Slack deliveries",
    description:
      "Platform Slack-webhook telemetry. One row per delivery kind with rate, last-failure breadcrumb.",
    icon: AlertTriangle,
  },
  {
    href: "/admin/crons",
    title: "Cron jobs",
    description:
      "Static registry of arq cron jobs registered on the worker. Schedule + next-due time per cron. Telemetry (last-run / success rate) is a follow-up.",
    icon: Clock,
  },
  {
    href: "/admin/retention",
    title: "Data retention",
    description:
      "Per-table TTL, row count, age of oldest row, and how many rows the next nightly prune will delete. Read-only telemetry of what `retention_prune_cron` is doing.",
    icon: Archive,
  },
  {
    href: "/admin/scrapers",
    title: "Price scrapers",
    description:
      "Provincial bulletin scraper drift trends. Top of table = slugs that need ops attention now.",
    icon: ChartLine,
  },
  {
    href: "/admin/normalizer-rules",
    title: "Normaliser rules",
    description:
      "Material-name regex rules merged on top of the in-code normaliser. Add / edit without a redeploy.",
    icon: GitBranch,
  },
] as const;


export default function AdminHubPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header className="space-y-2">
        <div className="flex items-center gap-2">
          <FlaskConical size={20} className="text-blue-600" />
          <h1 className="text-2xl font-bold text-slate-900">
            Platform admin
          </h1>
        </div>
        <p className="text-sm text-slate-600">
          Cross-tenant ops surface. Mỗi trang con đều admin-gated phía
          server — non-admin caller sẽ thấy banner hướng dẫn thay vì 403
          rỗng. Dùng cho triage incidents, audit drift, và quản lý cấu hình
          platform-wide.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        {ADMIN_PAGES.map((p) => (
          <Link
            key={p.href}
            href={p.href}
            className="block rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"
          >
            <div className="flex items-start gap-3">
              <div className="rounded-md bg-slate-100 p-2 text-slate-600">
                <p.icon size={16} aria-hidden />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-base font-semibold text-slate-900">
                  {p.title}
                </h2>
                <p className="mt-1 text-xs leading-relaxed text-slate-600">
                  {p.description}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
