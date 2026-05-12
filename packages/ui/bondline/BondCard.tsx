"use client";

import Link from "next/link";
import { AlertTriangle, CalendarClock, Landmark, ShieldCheck } from "lucide-react";
import { BOND_STATUS_LABEL, BOND_TYPE_LABEL, formatVnd } from "./types";
import type { BondStatus, BondSummary } from "./types";

interface BondCardProps {
  bond: BondSummary;
  href?: string;
}

const STATUS_STYLES: Record<BondStatus, string> = {
  active: "bg-emerald-100 text-emerald-800",
  released: "bg-slate-200 text-slate-700",
  claimed: "bg-rose-100 text-rose-700",
  expired: "bg-amber-200 text-amber-900",
  cancelled: "bg-slate-200 text-slate-600",
};

export function BondCard({ bond, href }: BondCardProps): JSX.Element {
  const daysToExpiry =
    typeof bond.days_to_expiry === "number" ? bond.days_to_expiry : null;
  const overdue = daysToExpiry !== null && daysToExpiry < 0 && bond.status === "active";

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Landmark className="mt-0.5 text-blue-600" size={20} />
          <div className="min-w-0">
            <p className="text-xs text-slate-500">
              {bond.issuing_bank} · {bond.bond_no}
            </p>
            <h3 className="font-semibold text-slate-900">
              {formatVnd(bond.face_amount_vnd)}
            </h3>
            <p className="mt-0.5 text-xs text-slate-500">
              {BOND_TYPE_LABEL[bond.bond_type]}
            </p>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[bond.status]}`}
        >
          {BOND_STATUS_LABEL[bond.status]}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5 text-slate-600">
          <CalendarClock size={14} className="text-slate-500" />
          <span>
            Hết hạn{" "}
            {new Date(bond.expiry_date).toLocaleDateString("vi-VN")}
          </span>
        </div>
        {daysToExpiry !== null && (
          <div
            className={`flex items-center gap-1.5 ${
              overdue
                ? "text-rose-600"
                : daysToExpiry <= 30
                  ? "text-amber-600"
                  : "text-slate-500"
            }`}
          >
            {overdue ? <AlertTriangle size={14} /> : <ShieldCheck size={14} />}
            <span>
              {overdue
                ? `Quá hạn ${-daysToExpiry} ngày`
                : `còn ${daysToExpiry} ngày`}
            </span>
          </div>
        )}
        {bond.claim_count > 0 && (
          <div className="flex items-center gap-1.5 text-rose-700">
            <AlertTriangle size={14} />
            <span>
              <span className="font-semibold">{bond.claim_count}</span>{" "}
              yêu cầu / khiếu nại
            </span>
          </div>
        )}
      </div>
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return href ? <Link href={href as any}>{body}</Link> : body;
}
