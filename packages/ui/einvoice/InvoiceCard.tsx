"use client";

import Link from "next/link";
import { FileText, ListChecks, Receipt } from "lucide-react";
import {
  INVOICE_DIRECTION_LABEL,
  INVOICE_STATUS_LABEL,
  formatMoney,
} from "./types";
import type { InvoiceStatus, InvoiceSummary } from "./types";

interface InvoiceCardProps {
  invoice: InvoiceSummary;
  href?: string;
}

const STATUS_STYLES: Record<InvoiceStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  issued: "bg-blue-100 text-blue-800",
  submitted_gdt: "bg-indigo-100 text-indigo-800",
  accepted_gdt: "bg-emerald-100 text-emerald-800",
  rejected_gdt: "bg-rose-100 text-rose-700",
  cancelled: "bg-slate-200 text-slate-600",
  adjustment_issued: "bg-amber-100 text-amber-800",
};

export function InvoiceCard({ invoice, href }: InvoiceCardProps): JSX.Element {
  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Receipt className="mt-0.5 text-blue-600" size={20} />
          <div className="min-w-0">
            <p className="text-xs text-slate-500">
              {invoice.template_no}·{invoice.serial_no}·{invoice.invoice_no}
            </p>
            <h3 className="font-semibold text-slate-900">
              {formatMoney(invoice.total)}
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">
              {INVOICE_DIRECTION_LABEL[invoice.direction]} ·{" "}
              {invoice.direction === "issued" ? invoice.buyer_name : invoice.issuer_name}
            </p>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[invoice.status]}`}
        >
          {INVOICE_STATUS_LABEL[invoice.status]}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5 text-slate-600">
          <FileText size={14} className="text-slate-500" />
          <span>
            Phát hành{" "}
            {new Date(invoice.issue_date).toLocaleDateString("vi-VN")}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-slate-600">
          <ListChecks size={14} className="text-slate-500" />
          <span>
            <span className="font-medium text-slate-900">
              {invoice.line_count}
            </span>{" "}
            dòng
          </span>
        </div>
        {invoice.gdt_code && (
          <div className="flex items-center gap-1.5 text-emerald-700">
            <span className="font-mono">{invoice.gdt_code}</span>
          </div>
        )}
      </div>
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return href ? <Link href={href as any}>{body}</Link> : body;
}
