import type { ISODate, UUID } from "./envelope";

export type PunchListStatus = "open" | "in_review" | "signed_off" | "cancelled";

export type PunchItemStatus =
  | "open"
  | "in_progress"
  | "fixed"
  | "verified"
  | "waived";

export type PunchTrade =
  | "architectural"
  | "mep"
  | "structural"
  | "civil"
  | "landscape"
  | "other";

export type PunchSeverity = "low" | "medium" | "high";

export interface PunchList {
  id: UUID;
  organization_id: UUID;
  project_id: UUID;
  name: string;
  walkthrough_date: ISODate;
  status: PunchListStatus | string;
  owner_attendees?: string | null;
  notes?: string | null;
  signed_off_at?: ISODate | null;
  signed_off_by?: UUID | null;
  created_by?: UUID | null;
  created_at: ISODate;
  updated_at: ISODate;
  total_items: number;
  open_items: number;
  fixed_items: number;
  verified_items: number;
}

export interface PunchItem {
  id: UUID;
  organization_id: UUID;
  list_id: UUID;
  item_number: number;
  description: string;
  location?: string | null;
  trade: PunchTrade | string;
  severity: PunchSeverity | string;
  status: PunchItemStatus | string;
  photo_id?: UUID | null;
  assigned_user_id?: UUID | null;
  due_date?: ISODate | null;
  fixed_at?: ISODate | null;
  verified_at?: ISODate | null;
  verified_by?: UUID | null;
  notes?: string | null;
  created_at: ISODate;
  updated_at: ISODate;
}

export interface PunchListDetail {
  list: PunchList;
  items: PunchItem[];
}
