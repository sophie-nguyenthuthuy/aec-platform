import type { ISODate, UUID } from "./envelope";

export type InboxItemKind =
  | "rfi"
  | "punch_item"
  | "defect"
  | "submittal"
  | "change_order"
  | "co_candidate";

export type InboxBucket = "assigned_to_me" | "awaiting_review";

export interface InboxItem {
  kind: InboxItemKind;
  bucket: InboxBucket;
  id: UUID;
  project_id?: UUID | null;
  project_name?: string | null;
  title: string;
  subtitle?: string | null;
  status?: string | null;
  severity?: string | null;
  due_date?: ISODate | null;
  created_at?: ISODate | null;
  deep_link: string;
}

export interface InboxBucketSummary {
  bucket: InboxBucket;
  count: number;
}

export interface InboxResponse {
  items: InboxItem[];
  summary: InboxBucketSummary[];
  total: number;
}
