"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ClipboardList,
  Construction,
  Fuel,
  Loader2,
  MoreHorizontal,
  Plus,
  Truck,
  X,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * EquipmentRental dashboard — per-project view of máy thi công thuê.
 *
 * Layout:
 *   1. Header — back link + "Thêm hợp đồng" CTA.
 *   2. Utilization KPI tiles (used / idle / utilization% / fuel cost).
 *   3. Idle-heavy banner — alerts when rentals waste >50% on idle days.
 *   4. Rental list with inline "Ghi nhật ký hôm nay" quick-log button.
 *   5. New-rental modal.
 *
 * Daily-log modal is contextual: appears when a rental row's "Ghi
 * nhật ký" button is clicked, prefills the rental + today's date.
 */


// ---- Types ----

type RentalStatus = "planned" | "active" | "returned" | "cancelled";
type UsageState = "used" | "idle" | "maintenance" | "off";

interface Rental {
  id: string;
  equipment_type: string;
  equipment_name: string;
  equipment_serial: string | null;
  supplier_name: string;
  supplier_phone: string | null;
  contract_number: string | null;
  rate_vnd_per_day: number;
  planned_start: string;
  planned_finish: string;
  actual_start: string | null;
  actual_finish: string | null;
  status: RentalStatus;
  notes: string | null;
  log_count: number;
  used_days: number;
  idle_days: number;
}

interface UtilizationKpi {
  window: { since: string; until: string; days: number };
  total_equipment_days: number;
  used_days: number;
  idle_days: number;
  maintenance_days: number;
  off_days: number;
  billable_days: number;
  utilization_pct: number;
  total_fuel_cost_vnd: number;
  idle_heavy_rentals: Array<{
    id: string;
    equipment_name: string;
    supplier_name: string;
    used_days: number;
    idle_days: number;
    wasted_vnd: number;
  }>;
}


const EQUIPMENT_TYPE_LABEL: Record<string, string> = {
  crane: "Cẩu tháp / Cẩu bánh",
  excavator: "Máy đào / Máy xúc",
  concrete_pump: "Máy bơm bê tông",
  loader: "Máy nâng",
  generator: "Máy phát điện",
  compressor: "Máy nén khí",
  scaffolding: "Giàn giáo",
  formwork: "Cốp pha",
  truck: "Xe tải / Xe ben",
  lift: "Vận thăng",
  other: "Khác",
};

const STATUS_LABEL: Record<RentalStatus, string> = {
  planned: "Sắp thuê",
  active: "Đang dùng",
  returned: "Đã trả",
  cancelled: "Huỷ",
};

const STATUS_PILL: Record<RentalStatus, string> = {
  planned: "bg-slate-100 text-slate-700",
  active: "bg-blue-100 text-blue-700",
  returned: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-slate-100 text-slate-500",
};

const USAGE_LABEL: Record<UsageState, string> = {
  used: "Đã dùng",
  idle: "Ngồi không (vẫn tính tiền)",
  maintenance: "Đang sửa",
  off: "Không có ở site",
};


export default function EquipmentRentalPage() {
  const { token, orgId } = useSession();
  const params = useParams<{ project_id: string }>();
  const projectId = params?.project_id;

  const [rentals, setRentals] = useState<Rental[]>([]);
  const [kpi, setKpi] = useState<UtilizationKpi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [logRentalId, setLogRentalId] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    if (!token || !orgId || !projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [r, k] = await Promise.all([
        apiFetch<{ rentals: Rental[] }>(
          `/api/v1/equipment/projects/${projectId}/rentals`,
          { token, orgId },
        ),
        apiFetch<UtilizationKpi>(
          `/api/v1/equipment/projects/${projectId}/utilization?days=30`,
          { token, orgId },
        ),
      ]);
      setRentals(r.data!.rentals);
      setKpi(k.data!);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, orgId, projectId]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  const utilColour = useMemo(() => {
    if (!kpi || kpi.billable_days === 0) return "text-slate-700";
    if (kpi.utilization_pct >= 85) return "text-emerald-700";
    if (kpi.utilization_pct >= 65) return "text-amber-700";
    return "text-rose-700";
  }, [kpi]);

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/pulse/${projectId}` as never}
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Quay lại dự án
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
              <Construction size={22} className="text-amber-600" />
              Máy thi công thuê
            </h2>
            <p className="text-xs text-slate-500">
              Theo dõi hợp đồng + nhật ký sử dụng + đối chiếu hoá đơn NCC.
            </p>
          </div>
          <button
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={14} />
            Thêm hợp đồng
          </button>
        </div>
      </div>

      {error && (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
      )}

      {showAdd && projectId && (
        <AddRentalModal
          projectId={projectId}
          token={token ?? ""}
          orgId={orgId ?? ""}
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            void fetchAll();
          }}
        />
      )}

      {logRentalId && (
        <DailyLogModal
          rentalId={logRentalId}
          token={token ?? ""}
          orgId={orgId ?? ""}
          onClose={() => setLogRentalId(null)}
          onLogged={() => {
            setLogRentalId(null);
            void fetchAll();
          }}
        />
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải…
        </p>
      ) : kpi ? (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiTile
              icon={<Truck size={14} />}
              label="Ngày dùng (30 ngày)"
              value={kpi.used_days.toLocaleString("vi-VN")}
              tone="emerald"
            />
            <KpiTile
              icon={<ClipboardList size={14} />}
              label="Ngày idle"
              value={kpi.idle_days.toLocaleString("vi-VN")}
              tone={kpi.idle_days > kpi.used_days * 0.3 ? "rose" : "amber"}
            />
            <KpiTile
              icon={<CheckCircle2 size={14} />}
              label="Hiệu suất sử dụng"
              value={`${kpi.utilization_pct.toFixed(1)}%`}
              valueClass={utilColour}
            />
            <KpiTile
              icon={<Fuel size={14} />}
              label="Tổng tiền dầu"
              value={formatVnd(kpi.total_fuel_cost_vnd)}
            />
          </div>

          {/* Idle-heavy alert */}
          {kpi.idle_heavy_rentals.length > 0 && (
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-4">
              <p className="flex items-center gap-1.5 text-sm font-medium text-rose-900">
                <AlertTriangle size={14} />
                {kpi.idle_heavy_rentals.length} hợp đồng có ngày idle nhiều hơn ngày dùng
              </p>
              <ul className="mt-2 space-y-1 text-xs text-rose-900">
                {kpi.idle_heavy_rentals.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3">
                    <span>
                      <b>{r.equipment_name}</b> ({r.supplier_name}) —
                      idle {r.idle_days} ngày / used {r.used_days} ngày
                    </span>
                    <span className="font-mono font-semibold">
                      Đã trả {formatVnd(r.wasted_vnd)} cho idle
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Rental list */}
          <section className="rounded-xl border border-slate-200 bg-white">
            <header className="border-b border-slate-200 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Hợp đồng thuê ({rentals.length})
              </h3>
            </header>
            {rentals.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-slate-500">
                Chưa có hợp đồng thuê máy. Bấm "Thêm hợp đồng".
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {rentals.map((r) => (
                  <RentalRow
                    key={r.id}
                    rental={r}
                    onQuickLog={() => setLogRentalId(r.id)}
                  />
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}


function KpiTile({
  icon,
  label,
  value,
  tone,
  valueClass,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "default" | "emerald" | "amber" | "rose";
  valueClass?: string;
}) {
  const toneCls = valueClass || {
    default: "text-slate-900",
    emerald: "text-emerald-700",
    amber: "text-amber-700",
    rose: "text-rose-700",
  }[tone ?? "default"];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-1 text-xl font-bold ${toneCls}`}>{value}</p>
    </div>
  );
}


function RentalRow({
  rental,
  onQuickLog,
}: {
  rental: Rental;
  onQuickLog: () => void;
}) {
  const expectedDays = daysBetween(rental.planned_start, rental.planned_finish);
  const billableDays = rental.used_days + rental.idle_days;
  const progressPct = expectedDays > 0 ? Math.min(100, (billableDays / expectedDays) * 100) : 0;

  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-amber-100 text-amber-700">
          <Truck size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-baseline gap-2">
            <h4 className="font-medium text-slate-900">{rental.equipment_name}</h4>
            <span className="text-xs text-slate-500">
              {EQUIPMENT_TYPE_LABEL[rental.equipment_type] || rental.equipment_type}
            </span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                STATUS_PILL[rental.status]
              }`}
            >
              {STATUS_LABEL[rental.status]}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
            <span>NCC: {rental.supplier_name}</span>
            <span>
              <Calendar size={10} className="mr-1 inline" />
              {formatVnDate(rental.planned_start)} → {formatVnDate(rental.planned_finish)}
            </span>
            <span>
              Rate: {formatVnd(rental.rate_vnd_per_day)}/ngày
            </span>
            {rental.contract_number && (
              <span className="font-mono">HD: {rental.contract_number}</span>
            )}
          </div>

          {/* Progress + util breakdown */}
          <div className="mt-2">
            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>
                {rental.log_count} ngày đã ghi nhật ký · {rental.used_days} dùng · {rental.idle_days} idle
              </span>
              <span>
                {billableDays}/{expectedDays} ngày phải trả tiền
              </span>
            </div>
            <div className="mt-1 h-1.5 w-full rounded-full bg-slate-100">
              <div
                className="h-1.5 rounded-full bg-blue-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        </div>
        <button
          onClick={onQuickLog}
          className="flex-shrink-0 rounded-md bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
        >
          Ghi nhật ký
        </button>
      </div>
    </li>
  );
}


function AddRentalModal({
  projectId,
  token,
  orgId,
  onClose,
  onAdded,
}: {
  projectId: string;
  token: string;
  orgId: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [type, setType] = useState("crane");
  const [name, setName] = useState("");
  const [supplier, setSupplier] = useState("");
  const [supplierPhone, setSupplierPhone] = useState("");
  const [contract, setContract] = useState("");
  const [rate, setRate] = useState("");
  const [start, setStart] = useState(new Date().toISOString().slice(0, 10));
  const [finish, setFinish] = useState(
    new Date(Date.now() + 30 * 86400e3).toISOString().slice(0, 10),
  );
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    const rateNum = parseInt(rate.replace(/[^0-9]/g, ""), 10);
    if (!name.trim() || !supplier.trim() || !rateNum) {
      setErr("Nhập tên máy, NCC và rate đầy đủ.");
      return;
    }
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/equipment/projects/${projectId}/rentals`, {
        method: "POST",
        token,
        orgId,
        body: {
          equipment_type: type,
          equipment_name: name.trim(),
          supplier_name: supplier.trim(),
          supplier_phone: supplierPhone.trim() || null,
          contract_number: contract.trim() || null,
          rate_vnd_per_day: rateNum,
          planned_start: start,
          planned_finish: finish,
          notes: notes.trim() || null,
        },
      });
      onAdded();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title="Thêm hợp đồng thuê máy" onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs text-slate-600">Loại máy</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {Object.entries(EQUIPMENT_TYPE_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-600">Tên cụ thể</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="vd: Cẩu tháp TC5610"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Nhà cung cấp</label>
          <input
            value={supplier}
            onChange={(e) => setSupplier(e.target.value)}
            placeholder="vd: Cty Cho thuê Máy Hà Nội"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">SĐT NCC</label>
          <input
            value={supplierPhone}
            onChange={(e) => setSupplierPhone(e.target.value)}
            placeholder="0987-654-321"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Số hợp đồng (tuỳ chọn)</label>
          <input
            value={contract}
            onChange={(e) => setContract(e.target.value)}
            placeholder="HD-2026-..."
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Rate (VNĐ/ngày)</label>
          <input
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            placeholder="3500000"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            inputMode="numeric"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Ngày bắt đầu (dự kiến)</label>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Ngày kết thúc (dự kiến)</label>
          <input
            type="date"
            value={finish}
            onChange={(e) => setFinish(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">Ghi chú (tuỳ chọn)</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}

      <ModalActions
        onClose={onClose}
        onSubmit={submit}
        submitting={submitting}
        submitLabel="Tạo hợp đồng"
      />
    </ModalShell>
  );
}


function DailyLogModal({
  rentalId,
  token,
  orgId,
  onClose,
  onLogged,
}: {
  rentalId: string;
  token: string;
  orgId: string;
  onClose: () => void;
  onLogged: () => void;
}) {
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [state, setState] = useState<UsageState>("used");
  const [hours, setHours] = useState("");
  const [operator, setOperator] = useState("");
  const [fuel, setFuel] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/equipment/rentals/${rentalId}/logs`, {
        method: "POST",
        token,
        orgId,
        body: {
          log_date: logDate,
          usage_state: state,
          hours_operated: hours ? parseFloat(hours) : null,
          operator_name: operator.trim() || null,
          fuel_cost_vnd: fuel ? parseInt(fuel.replace(/[^0-9]/g, ""), 10) : null,
          notes: notes.trim() || null,
        },
      });
      onLogged();
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.toLowerCase().includes("log_already_exists")) {
        setErr("Đã có nhật ký cho ngày này — sửa thay vì thêm mới.");
      } else {
        setErr(msg);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <ModalShell title="Ghi nhật ký sử dụng" onClose={onClose}>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs text-slate-600">Ngày</label>
          <input
            type="date"
            value={logDate}
            onChange={(e) => setLogDate(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Trạng thái</label>
          <select
            value={state}
            onChange={(e) => setState(e.target.value as UsageState)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {Object.entries(USAGE_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-600">Số giờ vận hành</label>
          <input
            value={hours}
            onChange={(e) => setHours(e.target.value)}
            placeholder="8.5"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            inputMode="decimal"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Tài xế / Vận hành</label>
          <input
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="Nguyễn Văn A"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Tiền dầu (VNĐ)</label>
          <input
            value={fuel}
            onChange={(e) => setFuel(e.target.value)}
            placeholder="500000"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            inputMode="numeric"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">Ghi chú</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}

      <ModalActions
        onClose={onClose}
        onSubmit={submit}
        submitting={submitting}
        submitLabel="Lưu nhật ký"
      />
    </ModalShell>
  );
}


function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-5">
        <div className="flex items-start justify-between">
          <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
            aria-label="Đóng"
          >
            <X size={16} />
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}


function ModalActions({
  onClose,
  onSubmit,
  submitting,
  submitLabel,
}: {
  onClose: () => void;
  onSubmit: () => void;
  submitting: boolean;
  submitLabel: string;
}) {
  return (
    <div className="mt-4 flex justify-end gap-2">
      <button
        onClick={onClose}
        className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm text-slate-700"
      >
        Huỷ
      </button>
      <button
        onClick={onSubmit}
        disabled={submitting}
        className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
      >
        {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
        {submitLabel}
      </button>
    </div>
  );
}


function formatVnd(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}


function formatVnDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}


function daysBetween(a: string, b: string): number {
  const ta = new Date(a).getTime();
  const tb = new Date(b).getTime();
  return Math.max(0, Math.round((tb - ta) / 86400e3) + 1);
}
