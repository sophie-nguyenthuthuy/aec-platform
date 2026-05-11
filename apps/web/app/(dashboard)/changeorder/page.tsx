"use client";

import Link from "next/link";
import { useState } from "react";
import { Plus, Sparkles } from "lucide-react";

import {
  Alert,
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
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
  draft: "bg-muted text-muted-foreground",
  submitted: "bg-amber-100 text-amber-700",
  reviewed: "bg-blue-100 text-blue-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-red-100 text-red-700",
  executed: "bg-purple-100 text-purple-700",
  cancelled: "bg-muted text-muted-foreground",
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
      <PageHeader
        title="Change Orders"
        description="Quản lý phát sinh: chi phí, thời gian, lịch sử duyệt. Trợ lý AI có thể phát hiện đề xuất từ RFI hoặc email."
        actions={
          <>
            <Button variant="outline" onClick={() => setExtracting(true)}>
              <Sparkles size={14} />
              Phát hiện CO bằng AI
            </Button>
            <Button onClick={() => setCreating(true)}>
              <Plus size={16} />
              Tạo CO mới
            </Button>
          </>
        }
      />

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

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : isError ? (
        <Alert variant="destructive">Không thể tải danh sách CO.</Alert>
      ) : !data?.data.length ? (
        <EmptyState title="Chưa có change order nào." />
      ) : (
        <div className="overflow-hidden rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left">Số</th>
                <th className="px-4 py-2 text-left">Tên</th>
                <th className="px-4 py-2 text-left">Trạng thái</th>
                <th className="px-4 py-2 text-right">Chi phí</th>
                <th className="px-4 py-2 text-right">Thời gian</th>
                <th className="px-4 py-2 text-left">Người đề xuất</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.data.map((co) => (
                <tr key={co.id} className="hover:bg-muted/40">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link
                      href={`/changeorder/${co.id}`}
                      className="text-primary hover:underline"
                    >
                      {co.number}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{co.title}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        STATUS_BADGE[co.status] ?? "bg-muted text-muted-foreground"
                      }`}
                    >
                      {co.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-medium text-foreground">
                    {formatVnd(co.cost_impact_vnd)}
                  </td>
                  <td className="px-4 py-2 text-right text-foreground">
                    {co.schedule_impact_days != null
                      ? `${co.schedule_impact_days} ngày`
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo CO mới</h3>
        <div className="mt-4 space-y-3">
          <Input
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="Mã dự án (UUID)"
          />
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Tên CO"
          />
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Mô tả phát sinh"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
          <div className="grid grid-cols-2 gap-2">
            <Input
              type="number"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
              placeholder="Chi phí (VND)"
            />
            <Input
              type="number"
              value={days}
              onChange={(e) => setDays(e.target.value)}
              placeholder="Số ngày trễ"
            />
          </div>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">
          AI: Phát hiện CO từ email/RFI
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Dán nội dung email từ chủ đầu tư hoặc RFI. AI sẽ đề xuất các CO
          tiềm năng kèm ước tính chi phí và thời gian.
        </p>
        <div className="mt-4 space-y-3">
          <Input
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="Mã dự án (UUID)"
          />
          <textarea
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Dán email/RFI vào đây..."
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
          />
          <Button
            onClick={onExtract}
            disabled={!projectId || !text.trim()}
            loading={extract.isPending}
          >
            <Sparkles size={14} />
            {extract.isPending ? "Đang phân tích..." : "Phân tích"}
          </Button>
        </div>

        {candidates && candidates.length > 0 && (
          <div className="mt-6 space-y-3">
            <h4 className="text-sm font-semibold text-foreground">
              Đề xuất từ AI ({candidates.length})
            </h4>
            {candidates.map((c) => (
              <div
                key={c.id}
                className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm"
              >
                <div className="flex items-baseline justify-between">
                  <h5 className="font-medium text-foreground">
                    {c.proposal.title}
                  </h5>
                  {c.proposal.confidence_pct != null && (
                    <span className="text-xs text-muted-foreground">
                      Tin cậy: {c.proposal.confidence_pct}%
                    </span>
                  )}
                </div>
                <p className="mt-1 text-foreground">{c.proposal.description}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {c.proposal.cost_impact_vnd_estimate != null &&
                    `Chi phí: ${formatVnd(c.proposal.cost_impact_vnd_estimate as number)}`}
                  {c.proposal.schedule_impact_days_estimate != null &&
                    ` · Trễ ${c.proposal.schedule_impact_days_estimate} ngày`}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <Button
                    variant="success"
                    size="sm"
                    onClick={() => accept.mutate({ candidateId: c.id })}
                    disabled={accept.isPending || c.accepted_co_id != null}
                  >
                    {c.accepted_co_id ? "Đã chấp nhận" : "Chấp nhận → tạo CO"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
        {candidates && candidates.length === 0 && (
          <p className="mt-6 text-sm text-muted-foreground">
            AI không phát hiện CO nào trong nội dung này.
          </p>
        )}

        <div className="mt-6 flex justify-end">
          <Button variant="ghost" onClick={onClose}>
            Đóng
          </Button>
        </div>
      </div>
    </div>
  );
}
