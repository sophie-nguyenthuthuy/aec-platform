"use client";

import Link from "next/link";
import { useState } from "react";
import { Plus, Sparkles } from "lucide-react";

import {
  useAcceptCandidate,
  useChangeOrders,
  useCreateChangeOrder,
  useExtractCandidates,
} from "@/hooks/changeorder";
import type { ChangeOrderListFilters } from "@/hooks/changeorder";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "submitted", label: "Đã trình" },
  { value: "reviewed", label: "Đã review" },
  { value: "approved", label: "Đã duyệt" },
  { value: "rejected", label: "Từ chối" },
  { value: "executed", label: "Đã thi công" },
];

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  submitted: "bg-amber-100 text-amber-700",
  reviewed: "bg-blue-100 text-blue-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  executed: "bg-purple-100 text-purple-700",
  cancelled: "bg-zinc-100 text-zinc-600",
};

function formatVnd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1_000_000_000)
    return `${(n / 1_000_000_000).toFixed(2)}B ₫`;
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ₫`;
  return `${n.toLocaleString("vi-VN")} ₫`;
}

export default function ChangeOrderPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [creating, setCreating] = useState(false);
  const [extracting, setExtracting] = useState(false);

  const filters: ChangeOrderListFilters = {
    status:
      statusFilter === "all"
        ? undefined
        : (statusFilter as ChangeOrderListFilters["status"]),
  };

  const { data, isLoading, isError } = useChangeOrders(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Change Orders</h2>
          <p className="text-sm text-slate-600">
            Quản lý phát sinh: chi phí, thời gian, lịch sử duyệt. Trợ lý AI có
            thể phát hiện đề xuất từ RFI hoặc email.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setExtracting(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
          >
            <Sparkles size={14} />
            Phát hiện CO bằng AI
          </button>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={16} />
            Tạo CO mới
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
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

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <p className="text-sm text-red-600">Không thể tải danh sách CO.</p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center text-sm text-slate-500">
          Chưa có change order nào.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">Số</th>
                <th className="px-4 py-2 text-left">Tên</th>
                <th className="px-4 py-2 text-left">Trạng thái</th>
                <th className="px-4 py-2 text-right">Chi phí</th>
                <th className="px-4 py-2 text-right">Thời gian</th>
                <th className="px-4 py-2 text-left">Người đề xuất</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.data.map((co) => (
                <tr key={co.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link
                      href={`/changeorder/${co.id}`}
                      className="text-blue-600 hover:underline"
                    >
                      {co.number}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{co.title}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        STATUS_BADGE[co.status] ?? "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {co.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-medium text-slate-900">
                    {formatVnd(co.cost_impact_vnd)}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-700">
                    {co.schedule_impact_days != null
                      ? `${co.schedule_impact_days} ngày`
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-600">
                    {co.initiator ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && <CreateCoDialog onClose={() => setCreating(false)} />}
      {extracting && <ExtractDialog onClose={() => setExtracting(false)} />}
    </div>
  );
}

function CreateCoDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [cost, setCost] = useState("");
  const [days, setDays] = useState("");
  const create = useCreateChangeOrder();

  const onSubmit = async () => {
    if (!projectId || !title) return;
    await create.mutateAsync({
      project_id: projectId,
      title,
      description: description || undefined,
      cost_impact_vnd: cost ? Number(cost) : undefined,
      schedule_impact_days: days ? Number(days) : undefined,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Tạo CO mới</h3>
        <div className="mt-4 space-y-3">
          <input
            type="text"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="Mã dự án (UUID)"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tên CO"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Mô tả phát sinh"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              type="number"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
              placeholder="Chi phí (VND)"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
            <input
              type="number"
              value={days}
              onChange={(e) => setDays(e.target.value)}
              placeholder="Số ngày trễ"
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
        </div>
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
            disabled={!projectId || !title || create.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ExtractDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [text, setText] = useState("");
  const extract = useExtractCandidates();
  const accept = useAcceptCandidate();
  const candidates = extract.data;

  const onExtract = async () => {
    if (!projectId || !text.trim()) return;
    await extract.mutateAsync({
      project_id: projectId,
      text,
      source_kind: "manual_paste",
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">
          AI: Phát hiện CO từ email/RFI
        </h3>
        <p className="mt-1 text-sm text-slate-600">
          Dán nội dung email từ chủ đầu tư hoặc RFI. AI sẽ đề xuất các CO
          tiềm năng kèm ước tính chi phí và thời gian.
        </p>
        <div className="mt-4 space-y-3">
          <input
            type="text"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="Mã dự án (UUID)"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <textarea
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Dán email/RFI vào đây..."
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={onExtract}
            disabled={!projectId || !text.trim() || extract.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Sparkles size={14} />
            {extract.isPending ? "Đang phân tích..." : "Phân tích"}
          </button>
        </div>

        {candidates && candidates.length > 0 && (
          <div className="mt-6 space-y-3">
            <h4 className="text-sm font-semibold text-slate-900">
              Đề xuất từ AI ({candidates.length})
            </h4>
            {candidates.map((c) => (
              <div
                key={c.id}
                className="rounded-lg border border-blue-200 bg-blue-50/50 p-4 text-sm"
              >
                <div className="flex items-baseline justify-between">
                  <h5 className="font-medium text-slate-900">
                    {c.proposal.title}
                  </h5>
                  {c.proposal.confidence_pct != null && (
                    <span className="text-xs text-slate-500">
                      Tin cậy: {c.proposal.confidence_pct}%
                    </span>
                  )}
                </div>
                <p className="mt-1 text-slate-700">{c.proposal.description}</p>
                <p className="mt-2 text-xs text-slate-600">
                  {c.proposal.cost_impact_vnd_estimate != null &&
                    `Chi phí: ${formatVnd(c.proposal.cost_impact_vnd_estimate as number)}`}
                  {c.proposal.schedule_impact_days_estimate != null &&
                    ` · Trễ ${c.proposal.schedule_impact_days_estimate} ngày`}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      accept.mutate({ candidateId: c.id })
                    }
                    disabled={accept.isPending || c.accepted_co_id != null}
                    className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
                  >
                    {c.accepted_co_id ? "Đã chấp nhận" : "Chấp nhận → tạo CO"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {candidates && candidates.length === 0 && (
          <p className="mt-6 text-sm text-slate-500">
            AI không phát hiện CO nào trong nội dung này.
          </p>
        )}

        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}

