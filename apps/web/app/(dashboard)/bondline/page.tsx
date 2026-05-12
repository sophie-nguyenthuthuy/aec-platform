"use client";

import { useState } from "react";
import { AlertTriangle, Landmark, Plus } from "lucide-react";
import {
  BOND_TYPE_LABEL,
  BondCard,
  VN_BANKS,
  formatVnd,
} from "@aec/ui/bondline";
import type { BondAlert, BondStatus, BondType } from "@aec/ui/bondline";
import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import { useBondAlerts, useBonds, useCreateBond } from "@/hooks/bondline";

const STATUS_FILTERS: Array<{ value: BondStatus | "all"; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: "active", label: "Đang hiệu lực" },
  { value: "claimed", label: "Bị gọi" },
  { value: "released", label: "Đã giải toả" },
  { value: "expired", label: "Hết hạn" },
];

const TYPE_OPTIONS: BondType[] = ["bid", "performance", "advance", "warranty"];

export default function BondLinePage() {
  const [statusFilter, setStatusFilter] = useState<BondStatus | "all">("all");
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useBonds({
    status: statusFilter === "all" ? undefined : statusFilter,
  });
  const { data: alerts } = useBondAlerts();

  const totalActive =
    data?.data
      .filter((b) => b.status === "active")
      .reduce((acc, b) => acc + b.face_amount_vnd, 0) ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bảo lãnh ngân hàng"
        description="Quản lý bảo lãnh dự thầu / thực hiện hợp đồng / tạm ứng / bảo hành theo Luật Đấu thầu 2023 + NĐ 24/2024. Theo dõi hạn hiệu lực và yêu cầu thanh toán bảo lãnh."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus size={16} />
            Thêm bảo lãnh
          </Button>
        }
      />

      {totalActive > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm">
          <Landmark className="text-blue-700" size={18} />
          <div>
            <div className="text-xs text-blue-800">Tổng giá trị bảo lãnh đang hiệu lực</div>
            <div className="text-base font-semibold text-blue-900">
              {formatVnd(totalActive)}
            </div>
          </div>
        </div>
      )}

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
        <EmptyState icon={<Landmark size={20} />} title="Chưa có bảo lãnh nào." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.data.map((b) => (
            <BondCard key={b.id} bond={b} href={`/bondline/${b.id}`} />
          ))}
        </div>
      )}

      {creating && <CreateBondDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

function AlertBanner({ alerts }: { alerts: BondAlert[] }) {
  const critical = alerts.filter((a) => a.severity === "critical").length;
  if (critical === 0 && alerts.length === 0) return null;
  return (
    <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
      <AlertTriangle className="mt-0.5 text-amber-600" size={18} />
      <div className="flex-1">
        <div className="font-medium text-amber-900">
          {critical > 0
            ? `${critical} bảo lãnh sắp hết hạn / quá hạn / thiếu giá trị bảo đảm`
            : `${alerts.length} cảnh báo`}
        </div>
        <ul className="mt-1 space-y-0.5 text-xs text-amber-800">
          {alerts.slice(0, 3).map((a) => (
            <li key={`${a.bond_id}-${a.code}`}>{a.message}</li>
          ))}
          {alerts.length > 3 && (
            <li className="italic text-amber-700">… và {alerts.length - 3} cảnh báo khác</li>
          )}
        </ul>
      </div>
    </div>
  );
}

function CreateBondDialog({ onClose }: { onClose: () => void }) {
  const [projectId, setProjectId] = useState("");
  const [bondType, setBondType] = useState<BondType>("performance");
  const [bondNo, setBondNo] = useState("");
  const [bank, setBank] = useState("VCB");
  const [beneficiary, setBeneficiary] = useState("");
  const [faceAmount, setFaceAmount] = useState("");
  const [issueDate, setIssueDate] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [expiryDate, setExpiryDate] = useState("");
  const create = useCreateBond();

  const onSubmit = async () => {
    if (!projectId || !bondNo || !beneficiary || !faceAmount || !expiryDate) return;
    await create.mutateAsync({
      project_id: projectId,
      bond_type: bondType,
      bond_no: bondNo,
      issuing_bank: bank,
      beneficiary_name: beneficiary,
      face_amount_vnd: parseInt(faceAmount, 10),
      issue_date: issueDate,
      expiry_date: expiryDate,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-card p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-foreground">Thêm bảo lãnh ngân hàng</h3>
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
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Loại
              </span>
              <select
                value={bondType}
                onChange={(e) => setBondType(e.target.value as BondType)}
                className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
              >
                {TYPE_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {BOND_TYPE_LABEL[t]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Ngân hàng
              </span>
              <select
                value={bank}
                onChange={(e) => setBank(e.target.value)}
                className="block w-full rounded-md border bg-card px-3 py-2 text-sm"
              >
                {VN_BANKS.map((b) => (
                  <option key={b.code} value={b.code}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Số bảo lãnh
            </span>
            <Input
              value={bondNo}
              onChange={(e) => setBondNo(e.target.value)}
              placeholder="VCB-2026-001"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Thụ hưởng
            </span>
            <Input
              value={beneficiary}
              onChange={(e) => setBeneficiary(e.target.value)}
              placeholder="Chủ đầu tư X"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-foreground">
              Mệnh giá (VND)
            </span>
            <Input
              type="number"
              value={faceAmount}
              onChange={(e) => setFaceAmount(e.target.value)}
              placeholder="5000000000"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Ngày phát hành
              </span>
              <Input
                type="date"
                value={issueDate}
                onChange={(e) => setIssueDate(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-foreground">
                Hết hạn
              </span>
              <Input
                type="date"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
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
            disabled={
              !projectId || !bondNo || !beneficiary || !faceAmount || !expiryDate
            }
            loading={create.isPending}
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </Button>
        </div>
      </div>
    </div>
  );
}
