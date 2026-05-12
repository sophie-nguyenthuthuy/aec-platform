"use client";

import { useState } from "react";
import { Plus, FileSignature } from "lucide-react";
import { RecordCard } from "@aec/ui/nghiemthu";
import type { AcceptanceLevel, AcceptanceStatus } from "@aec/ui/nghiemthu";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useCreateRecord, useRecords } from "@/hooks/nghiemthu";

const STATUS_FILTERS: Array<{ value: AcceptanceStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "in_signoff", label: "Đang ký" },
  { value: "accepted", label: "Đã chấp thuận" },
  { value: "rejected", label: "Bị từ chối" },
];

const LEVEL_FILTERS: Array<{ value: AcceptanceLevel | "all"; label: string }> = [
  { value: "all", label: "Mọi cấp" },
  { value: "cong_viec", label: "Công việc" },
  { value: "giai_doan", label: "Giai đoạn" },
  { value: "hoan_thanh", label: "Hoàn thành" },
];

const LEVEL_OPTIONS: AcceptanceLevel[] = ["cong_viec", "giai_doan", "hoan_thanh"];
const LEVEL_LABEL_FORM: Record<AcceptanceLevel, string> = {
  cong_viec: "Nghiệm thu công việc",
  giai_doan: "Nghiệm thu giai đoạn",
  hoan_thanh: "Nghiệm thu hoàn thành",
};

export default function NghieThuPage() {
  const [statusFilter, setStatusFilter] = useState<AcceptanceStatus | "all">("all");
  const [levelFilter, setLevelFilter] = useState<AcceptanceLevel | "all">("all");
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useRecords({
    status: statusFilter === "all" ? undefined : statusFilter,
    level: levelFilter === "all" ? undefined : levelFilter,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Biên bản nghiệm thu"
        description="Quản lý BBNT công việc / giai đoạn / hoàn thành theo NĐ 06/2021/NĐ-CP. Theo dõi chữ ký CĐT – TVGS – NT."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo BBNT mới
          </Button>
        }
      />

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
      <div className="flex flex-wrap gap-2">
        {LEVEL_FILTERS.map((f) => (
          <Button
            key={`l-${f.value}`}
            size="sm"
            variant={levelFilter === f.value ? "default" : "outline"}
            onClick={() => setLevelFilter(f.value)}
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
          icon={<FileSignature size={20} />}
          title="Chưa có biên bản nghiệm thu nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((r) => (
            <RecordCard
              key={r.id}
              record={r}
              href={`/nghiemthu/${r.id}`}
            />
          ))}
        </div>
      )}

      {creating && <CreateRecordDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreateRecordDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [referenceNo, setReferenceNo] = useState("");
  const [title, setTitle] = useState("");
  const [level, setLevel] = useState<AcceptanceLevel>("cong_viec");
  const [acceptanceDate, setAcceptanceDate] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const create = useCreateRecord();

  const onSubmit = async () => {
    if (!projectId || !referenceNo || !title) return;
    await create.mutateAsync({
      project_id: projectId,
      reference_no: referenceNo,
      acceptance_level: level,
      title,
      acceptance_date: acceptanceDate,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">
          Tạo biên bản nghiệm thu
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
              Số biên bản
            </span>
            <Input
              value={referenceNo}
              onChange={(e) => setReferenceNo(e.target.value)}
              placeholder="BBNT-2026-04-001"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Tiêu đề
            </span>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Nghiệm thu cốt thép cột tầng 5"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Cấp nghiệm thu
            </span>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value as AcceptanceLevel)}
              className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
            >
              {LEVEL_OPTIONS.map((lv) => (
                <option key={lv} value={lv}>
                  {LEVEL_LABEL_FORM[lv]}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Ngày nghiệm thu
            </span>
            <Input
              type="date"
              value={acceptanceDate}
              onChange={(e) => setAcceptanceDate(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !referenceNo || !title}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
