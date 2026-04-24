"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import {
  AsBuiltList,
  CloseoutChecklist,
  DefectCard,
  OmManualViewer,
  WarrantyRegister,
} from "@aec/ui/handover";
import type { CloseoutItem, OmManual } from "@aec/ui/handover";
import {
  useDefects,
  usePackage,
  usePackageOmManuals,
  useProjectAsBuilts,
  useUpdateCloseoutItem,
  useUpdateDefect,
  useUpdateWarranty,
  useWarranties,
} from "@/hooks/handover";

type Tab = "checklist" | "as-built" | "om" | "warranties" | "defects";

const TABS: Array<{ value: Tab; label: string }> = [
  { value: "checklist", label: "Checklist" },
  { value: "as-built", label: "Hoàn công" },
  { value: "om", label: "Sổ tay vận hành" },
  { value: "warranties", label: "Bảo hành" },
  { value: "defects", label: "Lỗi tồn đọng" },
];

export default function PackageDetailPage() {
  const params = useParams<{ packageId: string }>();
  const packageId = params.packageId;
  const [tab, setTab] = useState<Tab>("checklist");

  const { data: pkg, isLoading } = usePackage(packageId);

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (!pkg)
    return (
      <p className="text-sm text-slate-500">Không tìm thấy gói bàn giao.</p>
    );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">{pkg.name}</h2>
        <p className="text-xs text-slate-500">
          Tạo {new Date(pkg.created_at).toLocaleString("vi-VN")} · Trạng thái{" "}
          {pkg.status}
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={`border-b-2 px-4 py-2 text-sm font-medium ${
              tab === t.value
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-slate-600 hover:text-slate-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === "checklist" && (
          <ChecklistTab packageId={pkg.id} items={pkg.closeout_items} />
        )}
        {tab === "as-built" && <AsBuiltTab projectId={pkg.project_id} />}
        {tab === "om" && <OmTab packageId={pkg.id} />}
        {tab === "warranties" && (
          <WarrantiesTab projectId={pkg.project_id} packageId={pkg.id} />
        )}
        {tab === "defects" && (
          <DefectsTab projectId={pkg.project_id} packageId={pkg.id} />
        )}
      </div>
    </div>
  );
}

function ChecklistTab({
  packageId,
  items,
}: {
  packageId: string;
  items: CloseoutItem[];
}) {
  const update = useUpdateCloseoutItem(packageId);
  return (
    <CloseoutChecklist
      items={items}
      pendingItemId={
        update.isPending ? (update.variables?.item_id ?? null) : null
      }
      onChange={(itemId, patch) => {
        update.mutate({ item_id: itemId, patch });
      }}
    />
  );
}

function AsBuiltTab({ projectId }: { projectId: string }) {
  const { data, isLoading } = useProjectAsBuilts(projectId);
  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  return <AsBuiltList drawings={data ?? []} />;
}

function OmTab({ packageId }: { packageId: string }) {
  const { data, isLoading } = usePackageOmManuals(packageId);
  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (!data?.length)
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        Chưa có sổ tay vận hành nào được sinh ra.
      </div>
    );
  return (
    <div className="space-y-8">
      {data.map((m: OmManual) => (
        <OmManualViewer key={m.id} manual={m} />
      ))}
    </div>
  );
}

function WarrantiesTab({
  projectId,
  packageId,
}: {
  projectId: string;
  packageId: string;
}) {
  const { data, isLoading } = useWarranties({
    project_id: projectId,
    package_id: packageId,
  });
  const update = useUpdateWarranty();
  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  return (
    <WarrantyRegister
      items={data?.data ?? []}
      onClaim={(item) =>
        update.mutate({ id: item.id, patch: { status: "claimed" } })
      }
    />
  );
}

function DefectsTab({
  projectId,
  packageId,
}: {
  projectId: string;
  packageId: string;
}) {
  const { data, isLoading } = useDefects({
    project_id: projectId,
    package_id: packageId,
  });
  const update = useUpdateDefect();
  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (!data?.data.length)
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        Chưa có lỗi tồn đọng.
      </div>
    );
  return (
    <div className="space-y-2">
      {data.data.map((d) => (
        <DefectCard
          key={d.id}
          defect={d}
          onStatusChange={(status) =>
            update.mutate({ id: d.id, patch: { status } })
          }
        />
      ))}
    </div>
  );
}
