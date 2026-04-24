"use client";

import { Shield, AlertTriangle, XCircle } from "lucide-react";
import type { WarrantyItem, WarrantyStatus } from "./types";

interface WarrantyRegisterProps {
  items: WarrantyItem[];
  onClaim?: (item: WarrantyItem) => void;
}

const STATUS_LABEL: Record<WarrantyStatus, string> = {
  active: "Còn hiệu lực",
  expiring: "Sắp hết hạn",
  expired: "Đã hết hạn",
  claimed: "Đã yêu cầu bảo hành",
};

const STATUS_STYLE: Record<WarrantyStatus, string> = {
  active: "bg-emerald-100 text-emerald-800",
  expiring: "bg-amber-100 text-amber-800",
  expired: "bg-red-100 text-red-800",
  claimed: "bg-blue-100 text-blue-800",
};

export function WarrantyRegister({
  items,
  onClaim,
}: WarrantyRegisterProps): JSX.Element {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        Chưa có hạng mục bảo hành.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-3 py-2">Hạng mục</th>
            <th className="px-3 py-2">Nhà cung cấp</th>
            <th className="px-3 py-2">Hiệu lực</th>
            <th className="px-3 py-2">Còn lại</th>
            <th className="px-3 py-2">Trạng thái</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {items.map((item) => (
            <tr key={item.id}>
              <td className="px-3 py-2">
                <div className="font-medium text-slate-900">{item.item_name}</div>
                {item.category && (
                  <div className="text-xs text-slate-500">{item.category}</div>
                )}
              </td>
              <td className="px-3 py-2 text-slate-700">{item.vendor ?? "—"}</td>
              <td className="px-3 py-2 text-slate-700">
                {item.start_date && item.expiry_date
                  ? `${formatDate(item.start_date)} → ${formatDate(item.expiry_date)}`
                  : item.expiry_date
                    ? formatDate(item.expiry_date)
                    : "—"}
              </td>
              <td className="px-3 py-2">
                <DaysRemaining
                  days={item.days_to_expiry ?? null}
                  status={item.status}
                />
              </td>
              <td className="px-3 py-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[item.status]}`}
                >
                  {STATUS_LABEL[item.status]}
                </span>
              </td>
              <td className="px-3 py-2 text-right">
                {onClaim && item.status !== "expired" && item.status !== "claimed" && (
                  <button
                    type="button"
                    onClick={() => onClaim(item)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Yêu cầu bảo hành
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DaysRemaining({
  days,
  status,
}: {
  days: number | null;
  status: WarrantyStatus;
}): JSX.Element {
  if (days === null) return <span className="text-slate-400">—</span>;
  if (days < 0) {
    return (
      <span className="inline-flex items-center gap-1 text-red-600">
        <XCircle size={12} />
        Hết {Math.abs(days)} ngày
      </span>
    );
  }
  if (days <= 60 || status === "expiring") {
    return (
      <span className="inline-flex items-center gap-1 text-amber-600">
        <AlertTriangle size={12} />
        {days} ngày
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-emerald-600">
      <Shield size={12} />
      {days} ngày
    </span>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("vi-VN");
}
