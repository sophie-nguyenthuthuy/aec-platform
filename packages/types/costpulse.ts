import type { ISODate, UUID } from "./envelope";

export type MaterialCategory = "concrete" | "steel" | "finishing" | "mep" | "timber" | "masonry" | "other";
export type EstimateStatus = "draft" | "approved" | "superseded";
export type EstimateConfidence = "rough_order" | "preliminary" | "detailed";
export type EstimateMethod = "ai_generated" | "manual" | "imported";
export type RfqStatus = "draft" | "sent" | "responded" | "responding" | "closed";

/** Supplier-side state for one (rfq, supplier) slot. Lives inside `Rfq.responses[]`. */
export type RfqResponseStatus =
  | "dispatched"  // email out, no quote yet
  | "bounced"     // email send failed
  | "skipped"     // no contact email / supplier hidden / not yet dispatched
  | "responded";  // supplier submitted via the public portal
export type PriceSource = "government" | "supplier" | "crowdsource";
export type BoqItemSource = "ai_extracted" | "manual" | "price_db";
export type QualityTier = "economy" | "standard" | "premium";

export interface MaterialPrice {
  id: UUID;
  material_code: string;
  name: string;
  category: MaterialCategory | null;
  unit: string;
  price_vnd: string;
  price_usd: string | null;
  province: string | null;
  source: PriceSource | null;
  effective_date: ISODate;
  expires_date: ISODate | null;
  supplier_id: UUID | null;
}

export interface PriceHistoryPoint {
  effective_date: ISODate;
  price_vnd: string;
  province: string | null;
  source: PriceSource | null;
}

export interface PriceHistory {
  material_code: string;
  name: string;
  unit: string;
  points: PriceHistoryPoint[];
  pct_change_30d: number | null;
  pct_change_1y: number | null;
}

export interface BoqItem {
  id: UUID;
  estimate_id: UUID;
  parent_id: UUID | null;
  sort_order: number;
  code: string | null;
  description: string;
  unit: string | null;
  quantity: string | null;
  unit_price_vnd: string | null;
  total_price_vnd: string | null;
  material_code: string | null;
  source: BoqItemSource | null;
  notes: string | null;
}

export interface BoqItemInput {
  id?: UUID | null;
  parent_id?: UUID | null;
  sort_order?: number;
  code?: string | null;
  description: string;
  unit?: string | null;
  quantity?: string | number | null;
  unit_price_vnd?: string | number | null;
  total_price_vnd?: string | number | null;
  material_code?: string | null;
  source?: BoqItemSource | null;
  notes?: string | null;
}

export interface EstimateSummary {
  id: UUID;
  project_id: UUID | null;
  name: string;
  version: number;
  status: EstimateStatus;
  total_vnd: number | null;
  confidence: EstimateConfidence | null;
  method: EstimateMethod | null;
  created_by: UUID | null;
  approved_by: UUID | null;
  created_at: string;
}

export interface EstimateDetail extends EstimateSummary {
  items: BoqItem[];
}

export interface EstimateFromBriefInput {
  project_id?: UUID | null;
  name: string;
  project_type: string;
  area_sqm: number;
  floors: number;
  province: string;
  quality_tier: QualityTier;
  structure_type: "reinforced_concrete" | "steel" | "mixed";
  notes?: string | null;
}

export interface EstimateFromDrawingsInput {
  project_id?: UUID | null;
  name: string;
  drawing_file_ids: UUID[];
  province: string;
  include_contingency_pct?: number;
}

export interface Supplier {
  id: UUID;
  organization_id: UUID | null;
  name: string;
  categories: string[];
  provinces: string[];
  contact: Record<string, unknown>;
  verified: boolean;
  rating: string | null;
  created_at: string;
}

/**
 * One quote line as submitted by a supplier through the public portal.
 *
 * Mirrors `apps/api/schemas/public_rfq.py::PublicRfqQuoteLine`. Numeric
 * fields land here as strings because the buyer-side surface ingests
 * them via Pydantic Decimal serialisation, which is JSON-serialised as
 * strings to avoid float drift.
 */
export interface RfqQuoteLine {
  material_code: string | null;
  description: string;
  quantity: number | null;
  unit: string | null;
  unit_price_vnd: string | null;
}

export interface RfqQuote {
  total_vnd: string | null;
  lead_time_days: number | null;
  valid_until: ISODate | null;
  notes: string | null;
  line_items: RfqQuoteLine[];
}

/** One per-supplier slot inside `Rfq.responses[]`. */
export interface RfqResponseEntry {
  supplier_id: UUID;
  status: RfqResponseStatus;
  /** Set when the dispatcher email-out happened. */
  dispatched_at?: string | null;
  /** Set when the supplier submitted through the public portal. */
  responded_at?: string | null;
  /** Email-transport bookkeeping written by `services.rfq_dispatch`. */
  delivery?: {
    to?: string;
    subject?: string;
    delivered: boolean;
    reason?: string | null;
  } | null;
  /** Null until the supplier submits a quote. */
  quote: RfqQuote | null;
}

export interface Rfq {
  id: UUID;
  project_id: UUID | null;
  estimate_id: UUID | null;
  status: RfqStatus;
  sent_to: UUID[];
  responses: RfqResponseEntry[];
  deadline: ISODate | null;
  /**
   * Buyer's accepted-quote columns from migration 0024_rfq_acceptance.
   * Set when the buyer picks a winner; null until then. Drives the
   * "✓ Accepted" badge in `QuoteComparisonTable`.
   */
  accepted_supplier_id: UUID | null;
  accepted_at: string | null;
  created_at: string;
}

export interface RfqInput {
  project_id?: UUID | null;
  estimate_id?: UUID | null;
  supplier_ids: UUID[];
  deadline?: ISODate | null;
  message?: string | null;
  material_codes?: string[];
}

export interface CostBenchmarkBucket {
  project_type: string;
  province: string | null;
  quality_tier: string | null;
  cost_per_sqm_vnd_p25: number;
  cost_per_sqm_vnd_median: number;
  cost_per_sqm_vnd_p75: number;
  sample_size: number;
}

export interface AiEstimateResult {
  estimate_id: UUID;
  total_vnd: number;
  confidence: EstimateConfidence;
  items: BoqItem[];
  warnings: string[];
  missing_price_codes: string[];
}
