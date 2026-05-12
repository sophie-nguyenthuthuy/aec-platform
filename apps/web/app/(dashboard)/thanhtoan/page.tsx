"use client";

import { useState } from "react";
import { Banknote, Plus } from "lucide-react";
import { ClaimCard, formatVnd } from "@aec/ui/thanhtoan";
import type { ClaimStatus } from "@aec/ui/thanhtoan";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useClaims, useCreateClaim } from "@/hooks/thanhtoan";

const STATUS_FILTERS: Array<{ value: ClaimStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "submitted", label: "Đã nộp" },
  { value: "in_review", label: "Đang xét duyệt" },
  { value: "approved", label: "Đã chấp thuận" },
  { value: "paid", label: "Đã thanh toán" },
];

export default function ThanhToanPage() {
  const [statusFilter, setStatusFilter] = useState<ClaimStatus | "all">("all");
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useClaims({
    status: statusFilter === "all" ? undefined : statusFilter,
  });

  const outstandingTotal =
    data?.data
      .filter((c) => c.status === "approved")
      .reduce((acc, c) => acc + c.net_payable_vnd, 0) ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Hồ sơ thanh toán giai đoạn"
        description="Tự động tính VAT 8%, giữ lại bảo hành 5%, TNDN tạm thu 1%. Định tuyến ký duyệt CĐT – TVGS và theo dõi luỹ kế theo từng giai đoạn."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo claim mới
          </Button>
        }
      />

      {outstandingTotal > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
          <Banknote className="text-emerald-700" size={18} />
          <div>
            <div className="text-xs text-emerald-800">Đã duyệt — chờ thanh toán</div>
            <div className="text-base font-semibold text-emerald-900">
              {formatVnd(outstandingTotal)}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {STATUS_FILTERS.map((f) => (
          <Button
            key={f.value}
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
        <EmptyState
          icon={<Banknote size={20} />}
          title="Chưa có hồ sơ thanh toán nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((c) => (
            <ClaimCard key={c.id} claim={c} href={`/thanhtoan/${c.id}`} />
          ))}
        </div>
      )}

      {creating && <CreateClaimDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateClaimDialog({ onClose }: { onClose: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [projectId, setProjectId] = useState("");
  const [claimNo, setClaimNo] = useState("");
  const [periodStart, setPeriodStart] = useState(today);
  const [periodEnd, setPeriodEnd] = useState(today);
  const [dueAt, setDueAt] = useState("");
  const create = useCreateClaim();

  const onSubmit = async () => {
    if (!projectId || !claimNo) return;
    await create.mutateAsync({
      project_id: projectId,
      claim_no: claimNo,
      period_start: periodStart,
      period_end: periodEnd,
      due_at: dueAt || undefined,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">
          Tạo hồ sơ thanh toán
        </h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Mã dự án
            </span>
            <Input
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Số claim
            </span>
            <Input
              value={claimNo}
              onChange={(e) => setClaimNo(e.target.value)}
              placeholder="PT-2026-04"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Từ ngày
              </span>
              <Input
                type="date"
                value={periodStart}
                onChange={(e) => setPeriodStart(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Đến ngày
              </span>
              <Input
                type="date"
                value={periodEnd}
                onChange={(e) => setPeriodEnd(e.target.value)}
              />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Hạn thanh toán (tuỳ chọn)
            </span>
            <Input
              type="date"
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !claimNo}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
