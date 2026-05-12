"use client";

import { useState } from "react";
import { AlertTriangle, HardHat, Plus, UserRound } from "lucide-react";
import { EMPLOYMENT_TYPE_LABEL, WorkerCard } from "@aec/ui/workforce";
import type {
  EmploymentType,
  WorkerStatus,
  WorkforceAlert,
} from "@aec/ui/workforce";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useCreateWorker, useWorkers, useWorkforceAlerts } from "@/hooks/workforce";

const STATUS_FILTERS: Array<{ value: WorkerStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "active", label: "Đang làm việc" },
  { value: "inactive", label: "Tạm nghỉ" },
  { value: "terminated", label: "Đã nghỉ" },
];

const EMPLOYMENT_OPTIONS: EmploymentType[] = [
  "direct",
  "subcontractor",
  "temporary",
  "foreign",
];

export default function WorkforcePage() {
  const [statusFilter, setStatusFilter] = useState<WorkerStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useWorkers({
    status: statusFilter === "all" ? undefined : statusFilter,
    q: search || undefined,
  });
  const { data: alerts } = useWorkforceAlerts();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quản lý nhân công"
        description="Hồ sơ nhân công, huấn luyện ATVSLĐ theo NĐ 44/2016, BHXH/BHYT/BHTN theo Luật BHXH 58/2014, và giấy phép lao động nước ngoài theo NĐ 152/2020."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Thêm nhân công
          </Button>
        }
      />

      {alerts && alerts.length > 0 && <AlertBanner alerts={alerts} />}

      <div className="flex flex-wrap items-center gap-2">
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
        <div className="ml-auto w-64">
          <Input
            placeholder="Tìm theo tên / CCCD"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : !data?.data.length ? (
        <EmptyState
          icon={<HardHat size={20} />}
          title="Chưa có nhân công nào."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((w) => (
            <WorkerCard key={w.id} worker={w} href={`/workforce/${w.id}`} />
          ))}
        </div>
      )}

      {creating && <CreateWorkerDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function AlertBanner({ alerts }: { alerts: WorkforceAlert[] }) {
  const critical = alerts.filter((a) => a.severity === "critical").length;
  if (alerts.length === 0) return null;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
      <AlertTriangle className="mt-0.5 text-amber-600" size={18} />
      <div className="flex-1">
        <div className="font-medium text-amber-900">
          {critical > 0
            ? `${critical} cảnh báo nghiêm trọng`
            : `${alerts.length} cảnh báo`}
        </div>
        <ul className="mt-1 space-y-0.5 text-xs text-amber-800">
          {alerts.slice(0, 5).map((a, i) => (
            <li key={`${a.worker_id}-${a.code}-${i}`}>{a.message}</li>
          ))}
          {alerts.length > 5 && (
            <li className="italic text-amber-700">
              … và {alerts.length - 5} cảnh báo khác
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

function CreateWorkerDialog({ onClose }: { onClose: () => void }) {
  const [fullName, setFullName] = useState("");
  const [trade, setTrade] = useState("mason");
  const [employmentType, setEmploymentType] = useState<EmploymentType>("direct");
  const [idNo, setIdNo] = useState("");
  const [phone, setPhone] = useState("");
  const [nationality, setNationality] = useState("VN");
  const create = useCreateWorker();

  const onSubmit = async () => {
    if (!fullName || !trade) return;
    await create.mutateAsync({
      full_name: fullName,
      trade,
      employment_type: employmentType,
      id_no: idNo || undefined,
      phone: phone || undefined,
      nationality,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Thêm nhân công</h3>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Họ và tên
            </span>
            <Input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Nguyễn Văn A"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Nghề
              </span>
              <Input
                value={trade}
                onChange={(e) => setTrade(e.target.value)}
                placeholder="mason, electrician, foreman…"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Hình thức
              </span>
              <select
                value={employmentType}
                onChange={(e) =>
                  setEmploymentType(e.target.value as EmploymentType)
                }
                className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
              >
                {EMPLOYMENT_OPTIONS.map((e) => (
                  <option key={e} value={e}>
                    {EMPLOYMENT_TYPE_LABEL[e]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              CCCD / CMND (9 hoặc 12 số)
            </span>
            <Input
              value={idNo}
              onChange={(e) => setIdNo(e.target.value)}
              placeholder="079090123456"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Số điện thoại
              </span>
              <Input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Quốc tịch
              </span>
              <Input
                value={nationality}
                onChange={(e) => setNationality(e.target.value)}
                placeholder="VN"
              />
            </label>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Huỷ
          </Button>
          <Button
            onClick={onSubmit}
            disabled={!fullName || !trade}
            loading={create.isPending}
          >
            <UserRound size={14} />
            {create.isPending ? "Đang tạo..." : "Thêm"}
          </Button>
        </div>
      </div>
    </div>
  );
}
