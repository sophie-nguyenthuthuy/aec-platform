"use client";

import { useState } from "react";
import { Plus, Receipt } from "lucide-react";
import { InvoiceCard, formatMoney } from "@aec/ui/einvoice";
import type { InvoiceDirection, InvoiceStatus } from "@aec/ui/einvoice";
import {
  Button,
  EmptyState,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useInvoices } from "@/hooks/einvoice";

const STATUS_FILTERS: Array<{ value: InvoiceStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "issued", label: "Đã phát hành" },
  { value: "submitted_gdt", label: "Đã gửi GDT" },
  { value: "accepted_gdt", label: "GDT chấp thuận" },
  { value: "rejected_gdt", label: "GDT từ chối" },
];

const DIRECTION_FILTERS: Array<{ value: InvoiceDirection | "all"; label: string }> = [
  { value: "all", label: "Cả hai chiều" },
  { value: "issued", label: "Phát hành" },
  { value: "received", label: "Đầu vào" },
];

export default function EInvoicePage() {
  const [statusFilter, setStatusFilter] = useState<InvoiceStatus | "all">("all");
  const [directionFilter, setDirectionFilter] = useState<InvoiceDirection | "all">("all");

  const { data, isLoading } = useInvoices({
    status: statusFilter === "all" ? undefined : statusFilter,
    direction: directionFilter === "all" ? undefined : directionFilter,
  });

  const totalReceivable =
    data?.data
      .filter(
        (i) => i.direction === "issued" && !i.paid_at && i.status === "accepted_gdt",
      )
      .reduce((acc, i) => acc + i.total, 0) ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Hoá đơn điện tử (HĐĐT)"
        description="Phát hành và quản lý hoá đơn điện tử theo NĐ 123/2020/NĐ-CP + TT 78/2021. Tự động tính VAT, tra cứu MST với Tổng cục Thuế."
        actions={
          <Button>
            <Plus size={16} />
            Tạo HĐĐT
          </Button>
        }
      />

      {totalReceivable > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
          <Receipt className="text-emerald-700" size={18} />
          <div>
            <div className="text-xs text-emerald-800">Phải thu (HĐĐT đã GDT chấp thuận, chưa thanh toán)</div>
            <div className="text-base font-semibold text-emerald-900">
              {formatMoney(totalReceivable)}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {DIRECTION_FILTERS.map((f) => (
          <Button
            key={`d-${f.value}`}
            size="sm"
            variant={directionFilter === f.value ? "default" : "outline"}
            onClick={() => setDirectionFilter(f.value)}
            className="rounded-full"
          >
            {f.label}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={`s-${f.value}`}
            size="sm"
            variant={statusFilter === f.value ? "default" : "outline"}
            onClick={() => setStatusFilter(f.value)}
            className="rounded-full"
          >
            {f.label}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : !data?.data.length ? (
        <EmptyState icon={<Receipt size={20} />} title="Chưa có hoá đơn nào." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((inv) => (
            <InvoiceCard
              key={inv.id}
              invoice={inv}
              href={`/einvoice/${inv.id}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
