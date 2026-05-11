"use client";

import Link from "next/link";
import { useState } from "react";
import { ClipboardList, Plus } from "lucide-react";

import {
  Alert,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
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
  pending_review: "bg-muted text-muted-foreground",
  under_review: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  approved_as_noted: "bg-emerald-50 text-emerald-700",
  revise_resubmit: "bg-orange-100 text-orange-700",
  rejected: "bg-red-100 text-red-700",
  superseded: "bg-muted text-muted-foreground",
};

const BIC_BADGE: Record<string, string> = {
  designer: "bg-blue-50 text-blue-700",
  contractor: "bg-purple-50 text-purple-700",
  unassigned: "bg-muted text-muted-foreground",
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
      <PageHeader
        title="Hồ sơ đệ trình"
        description="Bản vẽ thi công, mẫu vật liệu, dữ liệu sản phẩm và mock-up gửi từ nhà thầu cho đội thiết kế duyệt."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo submittal mới
          </Button>
        }
      />

      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={statusFilter === f.value ? "default" : "outline"}
              className="rounded-full"
              onClick={() => setStatusFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[
            { value: "all", label: "Trách nhiệm: Tất cả" },
            { value: "designer", label: "Đội thiết kế" },
            { value: "contractor", label: "Nhà thầu" },
          ].map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={bicFilter === f.value ? "default" : "outline"}
              className="rounded-full"
              onClick={() => setBicFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : isError ? (
        <Alert variant="destructive">Không thể tải danh sách submittals.</Alert>
      ) : !data?.data.length ? (
        <EmptyState
          icon={<ClipboardList size={20} />}
          title="Chưa có submittal nào."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-[11px] uppercase tracking-wide text-muted-foreground">
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
            <tbody className="divide-y">
              {data.data.map((s) => (
                <tr key={s.id} className="hover:bg-muted/40">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link
                      href={`/submittals/${s.id}`}
                      className="text-primary hover:underline"
                    >
                      {s.package_number}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{s.title}</td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {s.submittal_type}
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {s.csi_division ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-center text-xs">
                    {s.current_revision}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        STATUS_BADGE[s.status] ?? "bg-muted text-muted-foreground"
                      }`}
                    >
                      {s.status}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        BIC_BADGE[s.ball_in_court] ?? "bg-muted text-muted-foreground"
                      }`}
                    >
                      {s.ball_in_court}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo submittal mới</h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Mã dự án
            </span>
            <Input value={projectId} onChange={(e) => setProjectId(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Tên submittal
            </span>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Loại
            </span>
            <select
              value={submittalType}
              onChange={(e) => setSubmittalType(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
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
            <span className="mb-1 block text-sm font-medium text-foreground">
              CSI Division
            </span>
            <Input
              value={csiDivision}
              onChange={(e) => setCsiDivision(e.target.value)}
              placeholder="03 30 00"
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !title}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
