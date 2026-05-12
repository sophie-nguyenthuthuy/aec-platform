export type InvoiceDirection = "issued" | "received";

export type InvoiceStatus =
  | "draft"
  | "issued"
  | "submitted_gdt"
  | "accepted_gdt"
  | "rejected_gdt"
  | "cancelled"
  | "adjustment_issued";

export type GdtStatus = "active" | "suspended" | "closed" | "not_found";

export interface EInvoice {
  id: string;
  organization_id: string;
  project_id?: string | null;
  direction: InvoiceDirection;
  invoice_no: string;
  template_no: string;
  serial_no: string;
  status: InvoiceStatus;
  issuer_mst: string;
  issuer_name: string;
  buyer_mst?: string | null;
  buyer_name: string;
  issue_date: string;
  due_date?: string | null;
  paid_at?: string | null;
  currency: string;
  exchange_rate: string;
  subtotal: number;
  vat_breakdown: Array<{
    rate: number | null;
    base: number;
    vat_amount: number;
    description: string;
  }>;
  vat_total: number;
  total: number;
  gdt_code?: string | null;
  gdt_rejection_reason?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface EInvoiceLine {
  id: string;
  organization_id: string;
  invoice_id: string;
  sort_order: number;
  description: string;
  item_code?: string | null;
  unit: string;
  qty: string;
  unit_price: number;
  discount_pct: string;
  line_total: number;
  vat_rate?: string | null;
  vat_amount: number;
  created_at: string;
}

export interface InvoiceSummary {
  id: string;
  project_id?: string | null;
  direction: InvoiceDirection;
  invoice_no: string;
  template_no: string;
  serial_no: string;
  status: InvoiceStatus;
  issuer_mst: string;
  issuer_name: string;
  buyer_mst?: string | null;
  buyer_name: string;
  issue_date: string;
  due_date?: string | null;
  paid_at?: string | null;
  total: number;
  line_count: number;
  gdt_code?: string | null;
  created_at: string;
}

export interface InvoiceDetail extends EInvoice {
  lines: EInvoiceLine[];
}

export interface MstInfo {
  mst: string;
  gdt_status: GdtStatus;
  legal_name?: string | null;
  address?: string | null;
  registered_at?: string | null;
  business_type?: string | null;
  last_checked_at: string;
}

export const INVOICE_DIRECTION_LABEL: Record<InvoiceDirection, string> = {
  issued: "Phát hành",
  received: "Đầu vào",
};

export const INVOICE_STATUS_LABEL: Record<InvoiceStatus, string> = {
  draft: "Bản nháp",
  issued: "Đã phát hành",
  submitted_gdt: "Đã gửi GDT",
  accepted_gdt: "GDT chấp thuận",
  rejected_gdt: "GDT từ chối",
  cancelled: "Đã huỷ",
  adjustment_issued: "Điều chỉnh",
};

export const GDT_STATUS_LABEL: Record<GdtStatus, string> = {
  active: "Đang hoạt động",
  suspended: "Tạm ngừng",
  closed: "Đã đóng",
  not_found: "Chưa tra cứu",
};

const VND_FMT = new Intl.NumberFormat("vi-VN");
export function formatMoney(amount: number, currency = "VND"): string {
  if (currency === "VND") return `${VND_FMT.format(amount)} ₫`;
  return `${VND_FMT.format(amount)} ${currency}`;
}

export function formatVatRate(rate: string | null | undefined): string {
  if (rate === null || rate === undefined) return "Miễn thuế";
  return `${Math.round(parseFloat(rate) * 100)}%`;
}
