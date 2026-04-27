import type { ISODate, UUID } from "./envelope";

/**
 * One row from `/api/v1/admin/scraper-runs` — a single run of
 * `services.price_scrapers.run_scraper`. Used by the drift-monitoring
 * panel on the prices page.
 */
export interface ScraperRun {
  id: UUID;
  slug: string;
  started_at: ISODate;
  finished_at: ISODate | null;
  ok: boolean;
  error: string | null;
  scraped: number;
  matched: number;
  unmatched: number;
  written: number;
  /** `material_code` → hits in this run. Codes that didn't fire are 0. */
  rule_hits: Record<string, number>;
  /** Distinct names that didn't match any rule, capped at 25. */
  unmatched_sample: string[];
}
