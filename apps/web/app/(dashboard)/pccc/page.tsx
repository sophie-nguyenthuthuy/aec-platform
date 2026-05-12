"use client";

import { useState } from "react";
import { AlertTriangle, Flame, Plus } from "lucide-react";
import {
  BUILDING_CLASS_LABEL,
  CERT_TYPE_LABEL,
  CertCard,
  HAZARD_CATEGORY_LABEL,
} from "@aec/ui/pccc";
import type {
  BuildingClass,
  CertAlert,
  CertStatus,
  CertType,
  HazardCategory,
} from "@aec/ui/pccc";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useAlerts, useCerts, useCreateCert } from "@/hooks/pccc";

const STATUS_FILTERS: Array<{ value: CertStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "planning", label: "Lập kế hoạch" },
  { value: "submitted", label: "Đã nộp" },
  { value: "inspection_scheduled", label: "Đã hẹn kiểm tra" },
  { value: "approved", label: "Đã phê duyệt" },
  { value: "rfi", label: "Yêu cầu bổ sung" },
];

const CERT_TYPE_OPTIONS: CertType[] = ["design", "acceptance", "recert"];
const HAZARD_OPTIONS: HazardCategory[] = ["A", "B", "C", "D", "E", "F"];
const BUILDING_CLASS_OPTIONS: BuildingClass[] = ["CO1", "CO2", "CO3", "CO4"];

export default function PCCCPage() {
  const [statusFilter, setStatusFilter] = useState<CertStatus | "all">("all");
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useCerts({
    status: statusFilter === "all" ? undefined : statusFilter,
  });
  const { data: alerts } = useAlerts();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Phòng cháy chữa cháy (PCCC)"
        description="Quản lý thẩm duyệt thiết kế và nghiệm thu PCCC theo QCVN 06:2022/BXD và NĐ 136/2020/NĐ-CP. Theo dõi vòng kiểm tra với PC07."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Tạo hồ sơ PCCC
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
        <EmptyState icon={<Flame size={20} />} title="Chưa có hồ sơ PCCC nào." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((c) => (
            <CertCard key={c.id} cert={c} href={`/pccc/${c.id}`} />
          ))}
        </div>
      )}

      {creating && <CreateCertDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function AlertBanner({ alerts }: { alerts: CertAlert[] }) {
  const critical = alerts.filter((a) => a.severity === "critical").length;
  const warning = alerts.filter((a) => a.severity === "warning").length;
  if (critical + warning === 0) return null;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm">
      <AlertTriangle className="mt-0.5 text-rose-600" size={18} />
      <div className="flex-1">
        <div className="font-medium text-rose-900">
          {critical > 0 && `${critical} cảnh báo nghiêm trọng`}
          {critical > 0 && warning > 0 && " · "}
          {warning > 0 && `${warning} cảnh báo`}
        </div>
        <ul className="mt-1 space-y-0.5 text-xs text-rose-800">
          {alerts.slice(0, 3).map((a) => (
            <li key={`${a.cert_id}-${a.code}`}>{a.message}</li>
          ))}
          {alerts.length > 3 && (
            <li className="italic text-rose-700">
              … và {alerts.length - 3} cảnh báo khác
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

function CreateCertDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [referenceNo, setReferenceNo] = useState("");
  const [certType, setCertType] = useState<CertType>("acceptance");
  const [hazard, setHazard] = useState<HazardCategory>("C");
  const [buildingClass, setBuildingClass] = useState<BuildingClass>("CO1");
  const [pc07Unit, setPc07Unit] = useState("PC07-HCM");
  const create = useCreateCert();

  const onSubmit = async () => {
    if (!projectId || !referenceNo || !pc07Unit) return;
    await create.mutateAsync({
      project_id: projectId,
      cert_type: certType,
      reference_no: referenceNo,
      hazard_category: hazard,
      building_class: buildingClass,
      pc07_unit: pc07Unit,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Tạo hồ sơ PCCC</h3>
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
              Số hồ sơ
            </span>
            <Input
              value={referenceNo}
              onChange={(e) => setReferenceNo(e.target.value)}
              placeholder="PCCC-2026-001"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Loại hồ sơ
            </span>
            <select
              value={certType}
              onChange={(e) => setCertType(e.target.value as CertType)}
              className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
            >
              {CERT_TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {CERT_TYPE_LABEL[t]}
                </option>
              ))}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Nhóm nguy hiểm
              </span>
              <select
                value={hazard}
                onChange={(e) => setHazard(e.target.value as HazardCategory)}
                className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
              >
                {HAZARD_OPTIONS.map((h) => (
                  <option key={h} value={h}>
                    {HAZARD_CATEGORY_LABEL[h]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Bậc chịu lửa
              </span>
              <select
                value={buildingClass}
                onChange={(e) =>
                  setBuildingClass(e.target.value as BuildingClass)
                }
                className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
              >
                {BUILDING_CLASS_OPTIONS.map((b) => (
                  <option key={b} value={b}>
                    {BUILDING_CLASS_LABEL[b]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Đơn vị PC07
            </span>
            <Input
              value={pc07Unit}
              onChange={(e) => setPc07Unit(e.target.value)}
              placeholder="PC07-HCM"
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!projectId || !referenceNo || !pc07Unit}
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
