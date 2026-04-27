"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Plus, Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";

import {
  useAddLineItem,
  useAnalyzeImpact,
  useChangeOrder,
  usePriceSuggestions,
  useRecordApproval,
} from "@/hooks/changeorder";
import type { CoStatus } from "@aec/types/changeorder";

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  submitted: "bg-amber-100 text-amber-700",
  reviewed: "bg-blue-100 text-blue-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  executed: "bg-purple-100 text-purple-700",
  cancelled: "bg-zinc-100 text-zinc-600",
};

const NEXT_STATES: Record<string, CoStatus[]> = {
  draft: ["submitted", "cancelled"],
  submitted: ["reviewed", "rejected", "cancelled"],
  reviewed: ["approved", "rejected"],
  approved: ["executed"],
};

function formatVnd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1_000_000_000)
    return `${(n / 1_000_000_000).toFixed(2)}B ₫`;
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ₫`;
  return `${n.toLocaleString("vi-VN")} ₫`;
}

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleString("vi-VN");
}

export default function ChangeOrderDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data, isLoading, isError } = useChangeOrder(id);
  const recordApproval = useRecordApproval(id ?? "");
  const analyze = useAnalyzeImpact(id ?? "");

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (isError || !data) {
    return (
      <div className="space-y-3">
        <Link href="/changeorder" className="text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} className="mr-1 inline" /> Quay lại
        </Link>
        <p className="text-sm text-red-600">Không tìm thấy CO này.</p>
      </div>
    );
  }

  const { change_order: co, sources, line_items, approvals } = data;
  const nextStates = NEXT_STATES[co.status] ?? [];
  const lineCostSum = line_items.reduce(
    (s, li) => s + (li.cost_vnd ?? 0),
    0,
  );

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/changeorder"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Tất cả change orders
        </Link>
        <div className="mt-2 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              {co.number} — {co.title}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Người đề xuất: {co.initiator ?? "—"}
              {co.submitted_at && ` · Trình: ${formatDate(co.submitted_at)}`}
              {co.approved_at && ` · Duyệt: ${formatDate(co.approved_at)}`}
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              STATUS_BADGE[co.status] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {co.status}
          </span>
        </div>
      </div>

      {/* Impact strip */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Chi phí tổng" value={formatVnd(co.cost_impact_vnd)} />
        <Stat
          label="Thời gian"
          value={
            co.schedule_impact_days != null
              ? `${co.schedule_impact_days} ngày`
              : "—"
          }
        />
        <Stat
          label="Tổng line items"
          value={`${line_items.length} mục · ${formatVnd(lineCostSum)}`}
        />
      </div>

      {/* AI analyze button */}
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-slate-900">Phân tích AI</h3>
          <button
            type="button"
            onClick={() => analyze.mutate(true)}
            disabled={analyze.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Sparkles size={12} />
            {analyze.isPending
              ? "Đang phân tích..."
              : co.ai_analysis
              ? "Phân tích lại"
              : "Phân tích chi phí & thời gian"}
          </button>
        </div>
        {co.ai_analysis ? (
          <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
            <div className="rounded bg-slate-50 px-3 py-2">
              <p className="text-slate-500">Phương pháp rollup</p>
              <p className="mt-0.5 font-mono text-slate-800">
                {String(co.ai_analysis["rollup_method"] ?? "—")}
              </p>
            </div>
            <div className="rounded bg-slate-50 px-3 py-2">
              <p className="text-slate-500">Mức độ tin cậy</p>
              <p className="mt-0.5 font-medium text-slate-800">
                {co.ai_analysis["confidence_pct"] != null
                  ? `${String(co.ai_analysis["confidence_pct"])}%`
                  : "—"}
              </p>
            </div>
            {co.ai_analysis["summary"] != null && (
              <p className="sm:col-span-2 text-slate-700">
                {String(co.ai_analysis["summary"])}
              </p>
            )}
            {Array.isArray(co.ai_analysis["assumptions"]) && (
              <ul className="sm:col-span-2 list-inside list-disc text-slate-600">
                {(co.ai_analysis["assumptions"] as string[]).map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p className="mt-2 text-xs text-slate-500">Chưa có phân tích AI.</p>
        )}
      </div>

      {/* Status transitions */}
      {nextStates.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">
            Chuyển trạng thái
          </h3>
          <div className="flex flex-wrap gap-2">
            {nextStates.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => recordApproval.mutate({ to_status: s })}
                disabled={recordApproval.isPending}
                className="rounded border border-slate-200 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
              >
                → {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Line items */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="flex items-baseline justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Line items ({line_items.length})
          </h3>
          <AddLineItemButton coId={co.id} />
        </div>
        {line_items.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">Chưa có line item nào.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">Mô tả</th>
                <th className="px-4 py-2 text-left">Loại</th>
                <th className="px-4 py-2 text-right">SL × đơn giá</th>
                <th className="px-4 py-2 text-right">Chi phí</th>
                <th className="px-4 py-2 text-right">Trễ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {line_items.map((li) => (
                <tr key={li.id}>
                  <td className="px-4 py-2">{li.description}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{li.line_kind}</td>
                  <td className="px-4 py-2 text-right text-xs">
                    {li.quantity != null && li.unit_cost_vnd != null
                      ? `${li.quantity} ${li.unit ?? ""} × ${formatVnd(li.unit_cost_vnd)}`
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-medium">
                    {formatVnd(li.cost_vnd)}
                  </td>
                  <td className="px-4 py-2 text-right text-xs">
                    {li.schedule_impact_days != null
                      ? `${li.schedule_impact_days} ngày`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Sources + Approval audit */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">
            Nguồn ({sources.length})
          </div>
          {sources.length === 0 ? (
            <p className="p-4 text-sm text-slate-500">Không có nguồn.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {sources.map((s) => (
                <li key={s.id} className="px-4 py-2 text-xs">
                  <span className="font-medium uppercase text-slate-700">
                    {s.source_kind}
                  </span>
                  {s.notes && <p className="mt-0.5 text-slate-600">{s.notes}</p>}
                  {s.rfi_id && (
                    <p className="mt-0.5 text-slate-500">
                      RFI ID: {s.rfi_id.slice(0, 8)}…
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">
            Lịch sử duyệt ({approvals.length})
          </div>
          {approvals.length === 0 ? (
            <p className="p-4 text-sm text-slate-500">Chưa có lịch sử.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {approvals.map((a) => (
                <li key={a.id} className="px-4 py-2 text-xs">
                  <span className="text-slate-600">
                    {formatDate(a.created_at)}
                  </span>
                  <span className="mx-2 text-slate-400">·</span>
                  <span className="font-mono">
                    {a.from_status ?? "—"} → {a.to_status}
                  </span>
                  {a.notes && (
                    <p className="mt-0.5 text-slate-700">{a.notes}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

/** "Add line item" button + inline form with CostPulse-backed unit-price hints. */
function AddLineItemButton({ coId }: { coId: string }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
      >
        <Plus size={12} /> Thêm line item
      </button>
    );
  }
  return <AddLineItemForm coId={coId} onClose={() => setOpen(false)} />;
}

function AddLineItemForm({
  coId,
  onClose,
}: {
  coId: string;
  onClose: () => void;
}) {
  const [description, setDescription] = useState("");
  const [specSection, setSpecSection] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState("");
  const [unitCost, setUnitCost] = useState("");
  const [days, setDays] = useState("");
  const add = useAddLineItem(coId);

  // Live CostPulse hints — keyed on description+spec_section, debounced
  // implicitly via React Query's `staleTime` and the input cadence.
  const sugg = usePriceSuggestions({
    q: description.trim() || undefined,
    spec_section: specSection.trim() || undefined,
    limit: 5,
  });

  const onSubmit = async () => {
    if (!description.trim()) return;
    await add.mutateAsync({
      description: description.trim(),
      spec_section: specSection.trim() || undefined,
      quantity: quantity ? Number(quantity) : undefined,
      unit: unit.trim() || undefined,
      unit_cost_vnd: unitCost ? Number(unitCost) : undefined,
      schedule_impact_days: days ? Number(days) : undefined,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Thêm line item</h3>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-slate-700">Mô tả</span>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Bê tông M300 sàn tầng 4"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">CSI section</span>
            <input
              type="text"
              value={specSection}
              onChange={(e) => setSpecSection(e.target.value)}
              placeholder="03 30 00"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Đơn vị</span>
            <input
              type="text"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              placeholder="m3"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Số lượng</span>
            <input
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Đơn giá (VND)</span>
            <input
              type="number"
              value={unitCost}
              onChange={(e) => setUnitCost(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-sm font-medium text-slate-700">Trễ (ngày)</span>
            <input
              type="number"
              value={days}
              onChange={(e) => setDays(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        {/* CostPulse hint pill — appears once the user types enough to query */}
        {sugg.data && sugg.data.results.length > 0 && (
          <div className="mt-4 rounded-md border border-blue-200 bg-blue-50/60 p-3">
            <p className="mb-2 flex items-center gap-1 text-xs font-medium text-blue-900">
              <TrendingUp size={12} />
              Gợi ý đơn giá từ CostPulse (mới nhất)
            </p>
            <ul className="space-y-1 text-xs">
              {sugg.data.results.slice(0, 3).map((s) => (
                <li
                  key={s.material_price_id}
                  className="flex items-center justify-between gap-2"
                >
                  <span className="truncate text-slate-700">
                    {s.name}{" "}
                    <span className="text-slate-500">
                      · {s.unit}
                      {s.province ? ` · ${s.province}` : ""}
                      {s.effective_date ? ` · ${s.effective_date}` : ""}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setUnitCost(String(s.price_vnd));
                      if (!unit.trim()) setUnit(s.unit);
                    }}
                    className="shrink-0 rounded border border-blue-300 bg-white px-2 py-0.5 font-medium text-blue-700 hover:bg-blue-100"
                  >
                    {s.price_vnd.toLocaleString("vi-VN")} ₫
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            Huỷ
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!description.trim() || add.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {add.isPending ? "Đang thêm..." : "Thêm"}
          </button>
        </div>
      </div>
    </div>
  );
}
