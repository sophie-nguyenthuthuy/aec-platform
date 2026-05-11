/**
 * Wildcard-aware preview collapse for webhook event subscriptions
 * (cycle V2).
 *
 * Backend cycle U2 added wildcard subscription patterns
 * (`costpulse.*`, `costpulse.estimate.*`). The R2 preview rendered
 * one card per literal entry — for a `costpulse.*` selection it
 * showed a "loading" placeholder instead of the concrete events
 * the partner's receiver will actually get.
 *
 * This helper takes the partner's selected entries plus the public
 * event catalog and produces a list of "preview cards":
 *
 *   * Literal selection → one card per literal event_type with the
 *     event's catalog metadata.
 *   * Wildcard selection (`<prefix>.*`) → one collapsed card with a
 *     prefix label + the list of concrete events that match.
 *
 * The collapsed card lets a partner picking `costpulse.*` see
 * exactly which payloads their receiver will get without needing
 * to mentally expand the wildcard.
 *
 * Why a frontend helper rather than backend-side: the catalog
 * endpoint is already cached client-side (cycle R2's
 * `useWebhookEventCatalog` has 1h staleTime). Doing the expansion
 * server-side would force a round-trip per selection change.
 */


export interface CatalogEntry {
  event_type: string;
  description: string;
  payload_sample: Record<string, unknown>;
}


/** A literal-event preview card. */
export interface LiteralPreviewCard {
  kind: "literal";
  event_type: string;
  description: string;
  payload_sample: Record<string, unknown>;
}


/**
 * A wildcard preview card — one entry per `<prefix>.*` selection.
 * `matched_events` is the list of catalog entries whose event_type
 * starts with `<prefix>.` (any depth — `costpulse.*` matches
 * `costpulse.estimate.approve` AND `costpulse.boq.import`).
 */
export interface WildcardPreviewCard {
  kind: "wildcard";
  pattern: string; // e.g. "costpulse.*"
  prefix: string; // e.g. "costpulse" — the part before `.*`
  matched_events: CatalogEntry[];
}


export type PreviewCard = LiteralPreviewCard | WildcardPreviewCard;


/**
 * Build the preview-card list from the partner's selection.
 *
 * Selection items can be:
 *   * literal event_type strings (`costpulse.estimate.approve`)
 *   * wildcard patterns (`costpulse.*`, `costpulse.estimate.*`)
 *
 * Order is preserved — partners typically check events in a
 * meaningful order; the preview should reflect that.
 *
 * Defensive against unknown literals (typo'd / catalog-out-of-date):
 * a literal that's not in the catalog produces a card with
 * `description = ""` and `payload_sample = {}` so the UI can render
 * "(catalog entry pending)" without crashing.
 */
export function buildPreviewCards(
  selected: string[],
  catalog: CatalogEntry[],
): PreviewCard[] {
  const catalogByType: Record<string, CatalogEntry> = {};
  for (const entry of catalog) {
    catalogByType[entry.event_type] = entry;
  }

  const cards: PreviewCard[] = [];
  for (const item of selected) {
    if (isWildcardPattern(item)) {
      const prefix = item.slice(0, -2); // drop trailing `.*`
      const matched = catalog.filter((e) =>
        e.event_type.startsWith(prefix + "."),
      );
      cards.push({
        kind: "wildcard",
        pattern: item,
        prefix,
        matched_events: matched,
      });
    } else {
      const entry = catalogByType[item];
      cards.push({
        kind: "literal",
        event_type: item,
        description: entry?.description ?? "",
        payload_sample: entry?.payload_sample ?? {},
      });
    }
  }
  return cards;
}


/**
 * True iff `entry` is a `<prefix>.*` wildcard form. Mirrors the
 * backend schema validator's wildcard rule: must end with `.*`,
 * must have a non-empty prefix, no embedded `*`.
 *
 * The check is intentionally permissive on the prefix shape — the
 * server's pydantic validator is the authoritative gate. We use
 * this client-side helper to drive UI grouping; an item that
 * doesn't match is rendered as a literal (and the server rejects
 * the create call if it's truly malformed).
 */
export function isWildcardPattern(entry: string): boolean {
  if (!entry.endsWith(".*")) return false;
  const prefix = entry.slice(0, -2);
  if (!prefix) return false;
  if (prefix.includes("*")) return false;
  return true;
}
