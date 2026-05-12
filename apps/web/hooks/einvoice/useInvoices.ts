"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  EInvoice,
  InvoiceDetail,
  InvoiceDirection,
  InvoiceStatus,
  InvoiceSummary,
  MstInfo,
} from "@aec/ui/einvoice";
import { einvoiceKeys } from "./keys";

export interface InvoiceListFilters {
  project_id?: string;
  direction?: InvoiceDirection;
  status?: InvoiceStatus;
  buyer_mst?: string;
  issuer_mst?: string;
  issued_year?: number;
  limit?: number;
  offset?: number;
}

export interface CreateInvoiceLine {
  description: string;
  unit?: string;
  qty: string;
  unit_price: number;
  discount_pct?: string;
  vat_rate?: string | null;
  item_code?: string;
  sort_order?: number;
}

export interface CreateInvoiceRequest {
  project_id?: string;
  direction: InvoiceDirection;
  invoice_no: string;
  template_no: string;
  serial_no: string;
  issue_date: string;
  due_date?: string;
  issuer_mst: string;
  issuer_name: string;
  issuer_address?: string;
  buyer_mst?: string;
  buyer_name: string;
  buyer_address?: string;
  buyer_email?: string;
  currency?: string;
  payment_method?: string;
  notes?: string;
  lines?: CreateInvoiceLine[];
}

export function useInvoices(filters: InvoiceListFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: einvoiceKeys.invoices(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<InvoiceSummary[]>(
        "/api/v1/einvoice/invoices",
        {
          method: "GET",
          token,
          orgId,
          query: {
            project_id: filters.project_id,
            direction: filters.direction,
            status: filters.status,
            buyer_mst: filters.buyer_mst,
            issuer_mst: filters.issuer_mst,
            issued_year: filters.issued_year,
            limit: filters.limit ?? 20,
            offset: filters.offset ?? 0,
          },
        },
      );
      return { data: (res.data ?? []) as InvoiceSummary[], meta: res.meta };
    },
  });
}

export function useInvoice(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? einvoiceKeys.invoice(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<InvoiceDetail>(
        `/api/v1/einvoice/invoices/${id}`,
        { method: "GET", token, orgId },
      );
      return res.data as InvoiceDetail;
    },
  });
}

export function useCreateInvoice() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["einvoice", "invoices", "create"],
    mutationFn: async (payload: CreateInvoiceRequest) => {
      const res = await apiFetch<EInvoice>("/api/v1/einvoice/invoices", {
        method: "POST",
        token,
        orgId,
        body: payload,
      });
      return res.data as EInvoice;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: einvoiceKeys.all });
    },
  });
}

export function useIssueInvoice(invoiceId: string) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["einvoice", "invoice", invoiceId, "issue"],
    mutationFn: async () => {
      const res = await apiFetch<EInvoice>(
        `/api/v1/einvoice/invoices/${invoiceId}/issue`,
        { method: "POST", token, orgId, body: {} },
      );
      return res.data as EInvoice;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: einvoiceKeys.invoice(invoiceId) });
      qc.invalidateQueries({ queryKey: einvoiceKeys.all });
    },
  });
}

export function useValidateMst() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["einvoice", "mst", "validate"],
    mutationFn: async (mst: string) => {
      const res = await apiFetch<MstInfo>("/api/v1/einvoice/mst/validate", {
        method: "POST",
        token,
        orgId,
        body: { mst },
      });
      return res.data as MstInfo;
    },
  });
}
