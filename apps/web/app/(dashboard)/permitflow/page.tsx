"use client";

import { useState } from "react";
import { Plus, FileCheck, AlertTriangle } from "lucide-react";
import { DossierCard } from "@aec/ui/permitflow";
import {
  CLASSIFICATION_LABEL,
  INVESTMENT_TYPE_LABEL,
  STAGE_CODE_LABEL,
} from "@aec/ui/permitflow";
import type {
  DossierStatus,
  InvestmentType,
  PermitAlert,
  ProjectClassification,
} from "@aec/ui/permitflow";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useAlerts, useCreateDossier, useDossiers } from "@/hooks/permitflow";

const STATUS_FILTERS: Array<{ value: DossierStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "planning", label: "Lập kế hoạch" },
  { value: "in_progress", label: "Đang xử lý" },
  { value: "on_hold", label: "Tạm dừng" },
  { value: "completed", label: "Hoàn thành" },
];

const CLASSIFICATION_OPTIONS: ProjectClassification[] = [
  "cap_iv",
  "cap_iii",
  "cap_ii",
  "cap_i",
  "dac_biet",
];

const INVESTMENT_OPTIONS: InvestmentType[] = ["domestic", "fdi"];

export default function PermitflowPage() {
  const [statusFilter, setStatusFilter] = useState<DossierStatus | "all">("all");
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useDossiers({
    status: statusFilter === "all" ? undefined : statusFilter,
  });
  const { data: alerts } = useAlerts();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Hồ sơ pháp lý xây dựng"
        description="Theo dõi 5 giai đoạn cấp phép: chủ trương đầu tư → quy hoạch 1/500 → thẩm định TKCS → giấy phép xây dựng → nghiệm thu PCCC."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo hồ sơ mới
          </Button>
        }
      />

      {alerts && alerts.length > 0 && <AlertBanner alerts={alerts} />}

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
          icon={<FileCheck size={20} />}
          title="Chưa có hồ sơ pháp lý nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((d) => (
            <DossierCard
              key={d.id}
              dossier={d}
              href={`/permitflow/${d.id}`}
            />
          ))}
        </div>
      )}

      {creating && <CreateDossierDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function AlertBanner({ alerts }: { alerts: PermitAlert[] }) {
  const critical = alerts.filter((a) => a.severity === "critical").length;
  const warning = alerts.filter((a) => a.severity === "warning").length;
  if (critical + warning === 0) return null;

  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
      <AlertTriangle className="mt-0.5 text-amber-600" size={18} />
      <div className="flex-1">
        <div className="font-medium text-amber-900">
          {critical > 0 && `${critical} cảnh báo nghiêm trọng`}
          {critical > 0 && warning > 0 && " · "}
          {warning > 0 && `${warning} cảnh báo`}
        </div>
        <ul className="mt-1 space-y-0.5 text-xs text-amber-800">
          {alerts.slice(0, 3).map((a) => (
            <li key={`${a.stage_id}-${a.code}`}>
              {STAGE_CODE_LABEL[a.stage_code]} — {a.message}
            </li>
          ))}
          {alerts.length > 3 && (
            <li className="italic text-amber-700">
              … và {alerts.length - 3} cảnh báo khác
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

function CreateDossierDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [classification, setClassification] =
    useState<ProjectClassification>("cap_iii");
  const [investmentType, setInvestmentType] =
    useState<InvestmentType>("domestic");
  const create = useCreateDossier();

  const onSubmit = async () => {
    if (!projectId || !name) return;
    await create.mutateAsync({
      project_id: projectId,
      name,
      classification,
      investment_type: investmentType,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo hồ sơ pháp lý</h3>
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
              Tên hồ sơ
            </span>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Hồ sơ chính — Toà A"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Cấp công trình
            </span>
            <select
              value={classification}
              onChange={(e) =>
                setClassification(e.target.value as ProjectClassification)
              }
              className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
            >
              {CLASSIFICATION_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {CLASSIFICATION_LABEL[c]}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Loại hình đầu tư
            </span>
            <select
              value={investmentType}
              onChange={(e) =>
                setInvestmentType(e.target.value as InvestmentType)
              }
              className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
            >
              {INVESTMENT_OPTIONS.map((i) => (
                <option key={i} value={i}>
                  {INVESTMENT_TYPE_LABEL[i]}
                </option>
              ))}
            </select>
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
