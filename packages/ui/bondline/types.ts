export type BondType = "bid" | "performance" | "advance" | "warranty";

export type BondStatus =
  | "active"
  | "released"
  | "claimed"
  | "expired"
  | "cancelled";

export type ClaimType =
  | "default_call"
  | "extension"
  | "amount_increase"
  | "cancellation";

export type ClaimStatus =
  | "pending"
  | "accepted"
  | "partial"
  | "rejected"
  | "withdrawn";

export interface Bond {
  id: string;
  organization_id: string;
  project_id: string;
  bond_type: BondType;
  bond_no: string;
  issuing_bank: string;
  bank_branch?: string | null;
  beneficiary_name: string;
  beneficiary_mst?: string | null;
  face_amount_vnd: number;
  contract_value_vnd?: number | null;
  coverage_pct?: string | null;
  currency: string;
  issue_date: string;
  effective_date?: string | null;
  expiry_date: string;
  status: BondStatus;
  released_at?: string | null;
  released_reason?: string | null;
  contract_no?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BondSummary {
  id: string;
  project_id: string;
  bond_type: BondType;
  bond_no: string;
  issuing_bank: string;
  face_amount_vnd: number;
  status: BondStatus;
  issue_date: string;
  expiry_date: string;
  days_to_expiry?: number | null;
  claim_count: number;
  created_at: string;
}

export interface BondClaim {
  id: string;
  organization_id: string;
  bond_id: string;
  claim_type: ClaimType;
  claim_amount_vnd?: number | null;
  status: ClaimStatus;
  filed_date: string;
  decided_date?: string | null;
  decided_amount_vnd?: number | null;
  reason?: string | null;
  decision_note?: string | null;
  created_at: string;
}

export interface BondDetail extends Bond {
  claims: BondClaim[];
}

export interface BondAlert {
  bond_id: string;
  project_id: string;
  bond_type: BondType;
  code: "expiring_soon" | "expired_not_released" | "coverage_below_contract";
  severity: "info" | "warning" | "critical";
  message: string;
  days_until?: number | null;
  expiry_date?: string | null;
}

export const BOND_TYPE_LABEL: Record<BondType, string> = {
  bid: "Bảo lãnh dự thầu",
  performance: "Bảo lãnh thực hiện HĐ",
  advance: "Bảo lãnh tạm ứng",
  warranty: "Bảo lãnh bảo hành",
};

export const BOND_STATUS_LABEL: Record<BondStatus, string> = {
  active: "Đang hiệu lực",
  released: "Đã giải toả",
  claimed: "Đã bị gọi bảo lãnh",
  expired: "Hết hiệu lực",
  cancelled: "Đã huỷ",
};

export const CLAIM_TYPE_LABEL: Record<ClaimType, string> = {
  default_call: "Yêu cầu thanh toán bảo lãnh",
  extension: "Gia hạn",
  amount_increase: "Tăng giá trị",
  cancellation: "Yêu cầu huỷ",
};

const VND_FMT = new Intl.NumberFormat("vi-VN");
export function formatVnd(amount: number): string {
  return `${VND_FMT.format(amount)} ₫`;
}

export const VN_BANKS: Array<{ code: string; name: string }> = [
  { code: "VCB", name: "Vietcombank" },
  { code: "BIDV", name: "BIDV" },
  { code: "VTB", name: "Vietinbank" },
  { code: "AGB", name: "Agribank" },
  { code: "TCB", name: "Techcombank" },
  { code: "MBB", name: "MB Bank" },
  { code: "ACB", name: "ACB" },
  { code: "VPB", name: "VPBank" },
  { code: "TPB", name: "TPBank" },
  { code: "STB", name: "Sacombank" },
  { code: "HDB", name: "HDBank" },
  { code: "SHB", name: "SHB" },
  { code: "OCB", name: "OCB" },
  { code: "EIB", name: "Eximbank" },
  { code: "MSB", name: "Maritime" },
  { code: "VIB", name: "VIB" },
  { code: "SCB", name: "SCB" },
];
