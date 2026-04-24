"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { PackageCard } from "@aec/ui/handover";
import type { PackageStatus } from "@aec/ui/handover";
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900">Gói bàn giao</h2>
          <p className="text-sm text-slate-600">
            Quản lý hồ sơ bàn giao, bản vẽ hoàn công, sổ tay vận hành, bảo hành và
            lỗi tồn đọng theo từng dự án.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus size={16} />
          Tạo gói mới
        </button>
      </div>

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

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : !data?.data.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
          Chưa có gói bàn giao nào.
        </div>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-900">Tạo gói bàn giao</h3>
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
              Tên gói
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Bàn giao giai đoạn 1"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={autoPopulate}
              onChange={(e) => setAutoPopulate(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-blue-600"
            />
            Tự tạo checklist mặc định
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
            disabled={!projectId || !name || create.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </button>
        </div>
      </div>
    </div>
  );
}
