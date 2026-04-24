"use client";

import { useState } from "react";
import { WarrantyRegister } from "@aec/ui/handover";
import type { WarrantyStatus } from "@aec/ui/handover";
import { useUpdateWarranty, useWarranties } from "@/hooks/handover";

const STATUS_FILTERS: Array<{ value: WarrantyStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "active", label: "Còn hiệu lực" },
  { value: "expiring", label: "Sắp hết" },
  { value: "expired", label: "Đã hết" },
  { value: "claimed", label: "Đã yêu cầu" },
];

const EXPIRY_WINDOWS: Array<{ days?: number; label: string }> = [
  { label: "Tất cả" },
  { days: 30, label: "30 ngày" },
  { days: 60, label: "60 ngày" },
  { days: 90, label: "90 ngày" },
];

export default function WarrantiesBoardPage() {
  const [statusFilter, setStatusFilter] = useState<WarrantyStatus | "all">("all");
  const [expiryDays, setExpiryDays] = useState<number | undefined>(undefined);

  const { data, isLoading } = useWarranties({
    status: statusFilter === "all" ? undefined : statusFilter,
    expiring_within_days: expiryDays,
    limit: 100,
  });
  const update = useUpdateWarranty();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Sổ bảo hành</h2>
        <p className="text-sm text-slate-600">
          Theo dõi thời hạn bảo hành của toàn bộ hạng mục qua mọi dự án.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-2">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatusFilter(f.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                statusFilter === f.value
                  ? "bg-blue-600 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs text-slate-600">
          <span>Hết hạn trong:</span>
          {EXPIRY_WINDOWS.map((w) => (
            <button
              key={w.label}
              type="button"
              onClick={() => setExpiryDays(w.days)}
              className={`rounded-full px-2 py-1 font-medium ${
                expiryDays === w.days
                  ? "bg-amber-500 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : (
        <WarrantyRegister
          items={data?.data ?? []}
          onClaim={(item) =>
            update.mutate({ id: item.id, patch: { status: "claimed" } })
          }
        />
      )}
    </div>
  );
}
