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
  usePackagePreconditions,
  useProjectAsBuilts,
  usePromoteDrawings,
  useUpdateCloseoutItem,
  useUpdateDefect,
  useUpdateWarranty,
  useWarranties,
} from "@/hooks/handover";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

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
  const { data: precond } = usePackagePreconditions(packageId);

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

      {precond && !precond.deliverable && pkg.status !== "delivered" && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-700" />
            <div className="flex-1 text-sm text-amber-900">
              <p className="font-medium">
                Gói này chưa thể bàn giao — còn punch list chủ đầu tư chưa ký
              </p>
              <ul className="mt-1.5 space-y-1 text-xs">
                {precond.blockers.map((b) => (
                  <li key={b.list_id} className="flex items-baseline gap-2">
                    <Link
                      href={`/punchlist/${b.list_id}`}
                      className="font-medium text-amber-800 underline hover:text-amber-900"
                    >
                      {b.name}
                    </Link>
                    <span className="text-amber-700">
                      ({b.status} · {b.open_items} item chưa xử lý)
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

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
        {tab === "as-built" && (
          <AsBuiltTab projectId={pkg.project_id} packageId={pkg.id} />
        )}
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

function AsBuiltTab({
  projectId,
  packageId,
}: {
  projectId: string;
  packageId: string;
}) {
  const { data, isLoading } = useProjectAsBuilts(projectId);
  const promote = usePromoteDrawings(packageId);
  // The most recent run's summary lives on the mutation result; show a
  // breakdown so the user can see what got created/versioned/skipped.
  const summary = promote.data;

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;

  const created = summary?.promoted.filter((p) => p.action === "created").length ?? 0;
  const versioned = summary?.promoted.filter((p) => p.action === "versioned").length ?? 0;
  const skipped = summary?.promoted.filter((p) => p.action === "skipped").length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
        <div className="text-xs text-blue-900">
          <p className="font-semibold">Quét bản vẽ từ Drawbridge</p>
          <p className="mt-0.5">
            Lấy phiên bản mới nhất của mỗi <code>drawing_number</code> trong dự án
            và đăng ký thành as-built. An toàn để chạy lại — bản vẽ đã ở phiên
            bản hiện tại sẽ bị bỏ qua.
          </p>
        </div>
        <button
          type="button"
          onClick={() => promote.mutate({})}
          disabled={promote.isPending}
          className="shrink-0 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {promote.isPending ? "Đang quét..." : "Quét Drawbridge"}
        </button>
      </div>

      {promote.isError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-800">
          Quét thất bại: {(promote.error as Error)?.message ?? "lỗi không xác định"}
        </div>
      )}

      {summary && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs text-emerald-900">
          Đã xét {summary.documents_considered} tài liệu — tạo mới {created} ·
          cập nhật phiên bản {versioned} · bỏ qua {skipped}.
        </div>
      )}

      <AsBuiltList drawings={data ?? []} />
    </div>
  );
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
