/**
 * Webhook event-type catalog — `/docs/webhooks/events`.
 *
 * Public partner-docs page listing every event the platform emits.
 * Server-rendered: fetches from `GET /api/v1/webhooks/event-types`
 * (no auth — the route is deliberately public so partners evaluating
 * the platform can read it before getting an API key).
 *
 * Why fetch from the backend rather than ship a static table:
 *
 *   * The backend has the registry (`_KNOWN_EVENT_TYPES`) AND the
 *     metadata catalog (`EVENT_CATALOG`) as the source of truth.
 *     The integrator-surface snapshot pins them in sync. Drifting
 *     a static frontend table from the backend was the failure mode
 *     this page is designed to avoid.
 *
 *   * `force-dynamic` keeps the data fresh — the catalog updates
 *     when the platform adds an event, no Next rebuild needed.
 *
 * Why not split into client component + useQuery: this is read-only
 * docs. SSR with no client JS is faster, more crawlable, and one
 * fewer hydration boundary to debug.
 */

import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { ChevronLeft, Webhook } from "lucide-react";


export const dynamic = "force-dynamic";


interface EventCatalogEntry {
  event_type: string;
  description: string;
  payload_sample: Record<string, unknown>;
}


/** Server-side fetch of the catalog. Public endpoint, no auth. */
async function fetchCatalog(): Promise<EventCatalogEntry[]> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiUrl}/api/v1/webhooks/event-types`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const env = (await res.json()) as { data: EventCatalogEntry[] | null };
    return env.data ?? [];
  } catch {
    // Marketing surface MUST render even when the api is down — no
    // catalog still beats a 500 page on a partner's first impression.
    return [];
  }
}


/**
 * Group events by their domain prefix (e.g. "costpulse.*", "org.*")
 * for visual scanning. Partners typically read this page looking for
 * "events related to <module>", not browsing alphabetically.
 */
function groupByPrefix(items: EventCatalogEntry[]): Record<string, EventCatalogEntry[]> {
  const groups: Record<string, EventCatalogEntry[]> = {};
  for (const item of items) {
    const prefix = item.event_type.split(".")[0] ?? "other";
    (groups[prefix] ??= []).push(item);
  }
  return groups;
}


export default async function WebhookEventsPage() {
  const t = await getTranslations("marketing.docs.events");
  const items = await fetchCatalog();
  const groups = groupByPrefix(items);
  const prefixOrder = Object.keys(groups).sort();

  return (
    <section className="mx-auto max-w-4xl px-6 py-12">
      <Link
        href="/docs/webhooks"
        className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700"
      >
        <ChevronLeft size={14} />
        {t("back_link")}
      </Link>

      <header className="mt-4 space-y-2">
        <div className="flex items-center gap-2">
          <Webhook size={20} className="text-blue-600" />
          <h1 className="text-2xl font-bold text-slate-900">{t("title")}</h1>
        </div>
        <p className="text-sm text-slate-600">{t("intro")}</p>
        <p className="text-xs text-slate-500">
          {t("count", {
            events: items.length,
            modules: prefixOrder.length,
          })}
        </p>
      </header>

      {items.length === 0 ? (
        <div className="mt-12 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
          {t.rich("unreachable", {
            code: (chunks) => (
              <code className="mx-1 rounded bg-slate-100 px-1 text-xs">
                {chunks}
              </code>
            ),
          })}
        </div>
      ) : (
        <div className="mt-10 space-y-10">
          {prefixOrder.map((prefix) => (
            <section key={prefix}>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {prefix}.*
              </h2>
              <p className="mt-1 text-[11px] text-slate-400">
                {t("event_count", { n: groups[prefix]!.length })}
              </p>
              <div className="mt-4 space-y-3">
                {groups[prefix]!.map((item) => (
                  <EventCard
                    key={item.event_type}
                    item={item}
                    payloadLabel={t("payload_sample_label")}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}


function EventCard({
  item,
  payloadLabel,
}: {
  item: EventCatalogEntry;
  payloadLabel: string;
}) {
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4">
      <code className="font-mono text-sm font-semibold text-slate-900">
        {item.event_type}
      </code>
      <p className="mt-2 text-sm leading-relaxed text-slate-600">
        {item.description}
      </p>
      <div className="mt-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          {payloadLabel}
        </p>
        {/* Pretty-printed JSON — partners copy-paste into their
            integration tests. `whitespace-pre-wrap` keeps long string
            values readable without horizontal scroll. */}
        <pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-700">
          {JSON.stringify(item.payload_sample, null, 2)}
        </pre>
      </div>
    </article>
  );
}
