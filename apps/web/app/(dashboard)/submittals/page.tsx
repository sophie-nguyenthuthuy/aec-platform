"use client";

import Link from "next/link";
import { useState } from "react";
import { ClipboardList, Plus } from "lucide-react";

import { useCreateSubmittal, useSubmittals } from "@/hooks/submittals";
import type { SubmittalListFilters } from "@/hooks/submittals";

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "pending_review", label: "Chờ duyệt" },
  { value: "under_review", label: "Đang duyệt" },
  { value: "approved", label: "Đã duyệt" },
  { value: "approved_as_noted", label: "Duyệt có ghi chú" },
  { value: "revise_resubmit", label: "Sửa & nộp lại" },
  { value: "rejected", label: "Từ chối" },
];

const STATUS_BADGE: Record<string, string> = {
  pending_review: "bg-slate-100 text-slate-700",
  under_review: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  approved_as_noted: "bg-emerald-50 text-emerald-700",
  revise_resubmit: "bg-orange-100 text-orange-700",
  rejected: "bg-red-100 text-red-700",
  superseded: "bg-zinc-100 text-zinc-600",
};

const BIC_BADGE: Record<string, string> = {
  designer: "bg-blue-50 text-blue-700",
  contractor: "bg-purple-50 text-purple-700",
  unassigned: "bg-slate-50 text-slate-600",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function SubmittalsPage() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [bicFilter, setBicFilter] = useState<string>("all");
  const [creating, setCreating] = useState(false);

  const filters: SubmittalListFilters = {
    status: statusFilter === "all" ? undefined : (statusFilter as SubmittalListFilters["status"]),
    ball_in_court: bicFilter === "all" ? undefined : (bicFilter as SubmittalListFilters["ball_in_court"]),
  };

  const { data, isLoading, isError } = useSubmittals(filters);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Submittals</h2>
          <p className="text-sm text-slate-600">
            Bản vẽ thi công, mẫu vật liệu, dữ liệu sản phẩm và mock-up gửi từ
            nhà thầu cho đội thiết kế duyệt.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={16} />
          Tạo submittal mới
        </button>
      </div>

      <div className="space-y-2">
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
        <div className="flex flex-wrap gap-1.5">
          {[
            { value: "all", label: "Trách nhiệm: Tất cả" },
            { value: "designer", label: "Đội thiết kế" },
            { value: "contractor", label: "Nhà thầu" },
          ].map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setBicFilter(f.value)}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                bicFilter === f.value
                  ? "bg-purple-600 text-white"
                  : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : isError ? (
        <p className="text-sm text-red-600">Không thể tải danh sách submittals.</p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <ClipboardList size={32} className="mx-auto mb-3 text-slate-400" aria-hidden />
          <p className="text-sm text-slate-500">Chưa có submittal nào.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">Số</th>
                <th className="px-4 py-2 text-left">Tên</th>
                <th className="px-4 py-2 text-left">Loại</th>
                <th className="px-4 py-2 text-left">CSI</th>
                <th className="px-4 py-2 text-center">Rev</th>
                <th className="px-4 py-2 text-left">Trạng thái</th>
                <th className="px-4 py-2 text-left">Trách nhiệm</th>
                <th className="px-4 py-2 text-left">Hạn</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.data.map((s) => (
                <tr key={s.id} className="hover:bg-slate-50">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link
                      href={`/submittals/${s.id}`}
                      className="text-blue-600 hover:underline"
                    >
                      {s.package_number}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{s.title}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">
                    {s.submittal_type}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-600">
                    {s.csi_division ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-center text-xs">
                    {s.current_revision}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        STATUS_BADGE[s.status] ?? "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {s.status}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        BIC_BADGE[s.ball_in_court] ?? "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {s.ball_in_court}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-600">
                    {formatDate(s.due_date)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && <CreateSubmittalDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateSubmittalDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [title, setTitle] = useState("");
  const [submittalType, setSubmittalType] = useState("shop_drawing");
  const [csiDivision, setCsiDivision] = useState("");
  const create = useCreateSubmittal();

  const onSubmit = async () => {
    if (!projectId || !title) return;
    await create.mutateAsync({
      project_id: projectId,
      title,
      submittal_type: submittalType as Parameters<
        typeof create.mutateAsync
      >[0]["submittal_type"],
      csi_division: csiDivision || undefined,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Tạo submittal mới</h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              Mã dự án
            </span>
            <input
              type="text"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              Tên submittal
            </span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              Loại
            </span>
            <select
              value={submittalType}
              onChange={(e) => setSubmittalType(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="shop_drawing">Shop drawing</option>
              <option value="sample">Sample</option>
              <option value="product_data">Product data</option>
              <option value="mock_up">Mock-up</option>
              <option value="certificate">Certificate</option>
              <option value="other">Khác</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">
              CSI Division
            </span>
            <input
              type="text"
              value={csiDivision}
              onChange={(e) => setCsiDivision(e.target.value)}
              placeholder="03 30 00"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
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
