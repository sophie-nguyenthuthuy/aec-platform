"use client";

import { useState } from "react";
import { Plus, PackageCheck } from "lucide-react";
import { PackageCard } from "@aec/ui/handover";
import type { PackageStatus } from "@aec/ui/handover";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useCreatePackage, usePackages } from "@/hooks/handover";

const STATUS_FILTERS: Array<{ value: PackageStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "draft", label: "Bản nháp" },
  { value: "in_review", label: "Đang duyệt" },
  { value: "approved", label: "Đã duyệt" },
  { value: "delivered", label: "Đã bàn giao" },
];

export default function HandoverPackagesPage() {
  const [statusFilter, setStatusFilter] = useState<PackageStatus | "all">("all");
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = usePackages({
    status: statusFilter === "all" ? undefined : statusFilter,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Gói bàn giao"
        description="Quản lý hồ sơ bàn giao, bản vẽ hoàn công, sổ tay vận hành, bảo hành và lỗi tồn đọng theo từng dự án."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo gói mới
          </Button>
        }
      />

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
          icon={<PackageCheck size={20} />}
          title="Chưa có gói bàn giao nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((pkg) => (
            <PackageCard
              key={pkg.id}
              pkg={pkg}
              href={`/handover/${pkg.id}`}
            />
          ))}
        </div>
      )}

      {creating && <CreatePackageDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function CreatePackageDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [autoPopulate, setAutoPopulate] = useState(true);
  const create = useCreatePackage();

  const onSubmit = async () => {
    if (!projectId || !name) return;
    await create.mutateAsync({
      project_id: projectId,
      name,
      auto_populate: autoPopulate,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo gói bàn giao</h3>
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
              Tên gói
            </span>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Bàn giao giai đoạn 1"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={autoPopulate}
              onChange={(e) => setAutoPopulate(e.target.checked)}
              className="h-4 w-4 rounded border text-primary"
            />
            Tự tạo checklist mặc định
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !name}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
