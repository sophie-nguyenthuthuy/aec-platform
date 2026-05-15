"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownCircle,
  ArrowLeft,
  ArrowUpCircle,
  Calendar,
  CheckCircle2,
  Loader2,
  Plus,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Per-project CashFlow (Dòng tiền dự án) dashboard.
 *
 * Shows:
 *   * KPI tiles: tổng inflow / outflow / net forecast.
 *   * Bar chart by month — inflow (xanh) vs outflow (đỏ), with
 *     cumulative line overlay. Deficit months highlighted.
 *   * Entry list grouped by month, with status pills + action menu.
 *   * "Thêm dòng tiền" inline form for admins.
 */

type EntryKind = "inflow" | "outflow";
type EntryStatus =
  | "planned"
  | "committed"
  | "invoiced"
  | "paid"
  | "overdue"
  | "cancelled";

interface CashflowEntry {
  id: string;
  kind: EntryKind;
  label: string;
  amount_vnd: number;
  expected_date: string;
  status: EntryStatus;
  milestone_id: string | null;
  supplier_id: string | null;
  notes: string | null;
  paid_actual_vnd: number;
  created_at: string;
}

interface ForecastPoint {
  month: string;
  inflow_vnd: number;
  outflow_vnd: number;
  net_vnd: number;
  cumulative_vnd: number;
}

interface ForecastResponse {
  series: ForecastPoint[];
  summary: {
    total_inflow_vnd: number;
    total_outflow_vnd: number;
    total_net_vnd: number;
    deficit_months: string[];
    horizon_months: number;
  };
}


const STATUS_LABEL: Record<EntryStatus, string> = {
  planned: "Dự kiến",
  committed: "Đã ký",
  invoiced: "Đã xuất HĐ",
  paid: "Đã trả",
  overdue: "Trễ hạn",
  cancelled: "Huỷ",
};
const STATUS_PILL: Record<EntryStatus, string> = {
  planned: "bg-slate-100 text-slate-700",
  committed: "bg-blue-100 text-blue-700",
  invoiced: "bg-amber-100 text-amber-700",
  paid: "bg-emerald-100 text-emerald-700",
  overdue: "bg-rose-100 text-rose-700",
  cancelled: "bg-slate-100 text-slate-500",
};


export default function CashflowProjectPage() {
  const { token, orgId } = useSession();
  const params = useParams<{ project_id: string }>();
  const projectId = params?.project_id;

  const [entries, setEntries] = useState<CashflowEntry[]>([]);
  const [forecast, setForecast] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [adding, setAdding] = useState(false);

  const fetchAll = useCallback(async () => {
    if (!token || !orgId || !projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [e, f] = await Promise.all([
        apiFetch<{ entries: CashflowEntry[] }>(
          "/api/v1/cashflow/projects/" + projectId + "/entries",
          { token, orgId },
        ),
        apiFetch<ForecastResponse>(
          "/api/v1/cashflow/projects/" + projectId + "/forecast",
          { token, orgId },
        ),
      ]);
      setEntries(e.data!.entries);
      setForecast(f.data!);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, orgId, projectId]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  // Peak across (inflow+outflow) per month — bar-chart scaler
  const peak = useMemo(() => {
    if (!forecast) return 1;
    return Math.max(
      1,
      ...forecast.series.map((p) => Math.max(p.inflow_vnd, p.outflow_vnd)),
    );
  }, [forecast]);

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
            <h2 className="text-2xl font-bold text-slate-900">Dòng tiền dự án</h2>
            <p className="text-xs text-slate-500">
              Dự báo thu/chi theo tháng. Theo dõi gap vốn lưu động.
            </p>
          </div>
          <button
            onClick={() => setShowAdd((s) => !s)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            <Plus size={14} />
            Thêm dòng tiền
          </button>
        </div>
      </div>

      {error && (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
      )}

      {showAdd && projectId && (
        <AddEntryForm
          projectId={projectId}
          token={token ?? ""}
          orgId={orgId ?? ""}
          submitting={adding}
          setSubmitting={setAdding}
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            void fetchAll();
          }}
        />
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải…
        </p>
      ) : forecast ? (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiTile
              icon={<ArrowDownCircle size={14} />}
              label="Tổng thu (Inflow)"
              value={formatVnd(forecast.summary.total_inflow_vnd)}
              tone="emerald"
            />
            <KpiTile
              icon={<ArrowUpCircle size={14} />}
              label="Tổng chi (Outflow)"
              value={formatVnd(forecast.summary.total_outflow_vnd)}
              tone="rose"
            />
            <KpiTile
              icon={forecast.summary.total_net_vnd >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
              label="Net dự kiến"
              value={formatVnd(forecast.summary.total_net_vnd)}
              tone={forecast.summary.total_net_vnd >= 0 ? "emerald" : "rose"}
            />
            <KpiTile
              icon={<AlertTriangle size={14} />}
              label="Tháng âm dòng tiền"
              value={String(forecast.summary.deficit_months.length)}
              tone={forecast.summary.deficit_months.length > 0 ? "rose" : "default"}
            />
          </div>

          {/* Monthly bar chart */}
          <section className="rounded-xl border border-slate-200 bg-white p-4">
            <h3 className="text-sm font-semibold text-slate-900">
              Dự báo theo tháng
            </h3>
            {forecast.series.length === 0 ? (
              <p className="mt-4 text-sm text-slate-500">
                Chưa có dòng tiền nào. Bấm "Thêm dòng tiền" để bắt đầu.
              </p>
            ) : (
              <div className="mt-4">
                <div className="flex h-48 items-end gap-3 overflow-x-auto">
                  {forecast.series.map((p) => {
                    const inH = (p.inflow_vnd / peak) * 100;
                    const outH = (p.outflow_vnd / peak) * 100;
                    const isDeficit = p.cumulative_vnd < 0;
                    return (
                      <div
                        key={p.month}
                        className="group flex flex-col items-center"
                        title={`${formatMonthVi(p.month)}\nThu: ${formatVnd(p.inflow_vnd)}\nChi: ${formatVnd(p.outflow_vnd)}\nNet: ${formatVnd(p.net_vnd)}\nLuỹ kế: ${formatVnd(p.cumulative_vnd)}`}
                      >
                        <div className="relative flex h-40 w-12 items-end gap-0.5">
                          <div
                            className="w-1/2 rounded-t bg-emerald-500"
                            style={{ height: `${inH}%`, minHeight: p.inflow_vnd > 0 ? "2px" : "0" }}
                          />
                          <div
                            className="w-1/2 rounded-t bg-rose-500"
                            style={{ height: `${outH}%`, minHeight: p.outflow_vnd > 0 ? "2px" : "0" }}
                          />
                        </div>
                        <span
                          className={`mt-1 text-[10px] ${isDeficit ? "font-semibold text-rose-700" : "text-slate-500"}`}
                        >
                          {formatMonthVi(p.month)}
                        </span>
                        <span
                          className={`text-[10px] ${isDeficit ? "font-semibold text-rose-700" : "text-slate-400"}`}
                        >
                          {formatVndShort(p.cumulative_vnd)}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                  <LegendDot color="#10b981" label="Thu (inflow)" />
                  <LegendDot color="#f43f5e" label="Chi (outflow)" />
                  <span className="text-slate-400">
                    Số dưới: luỹ kế · đỏ = âm dòng tiền
                  </span>
                </div>
              </div>
            )}
          </section>

          {/* Entry list */}
          <section className="rounded-xl border border-slate-200 bg-white">
            <header className="border-b border-slate-200 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Danh sách dòng tiền ({entries.length})
              </h3>
            </header>
            {entries.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-slate-500">
                Chưa có dòng tiền nào.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {entries.map((e) => (
                  <EntryRow key={e.id} entry={e} />
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
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: "default" | "emerald" | "rose";
}) {
  const valueTone = {
    default: "text-slate-900",
    emerald: "text-emerald-700",
    rose: "text-rose-700",
  }[tone];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-1 text-lg font-bold ${valueTone}`}>{value}</p>
    </div>
  );
}


function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block h-2 w-3 rounded-sm"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}


function EntryRow({ entry }: { entry: CashflowEntry }) {
  const isInflow = entry.kind === "inflow";
  const partial = entry.paid_actual_vnd > 0 && entry.paid_actual_vnd < entry.amount_vnd;
  const fullyPaid = entry.paid_actual_vnd >= entry.amount_vnd;

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-start gap-3">
        {isInflow ? (
          <ArrowDownCircle size={16} className="mt-0.5 flex-shrink-0 text-emerald-500" />
        ) : (
          <ArrowUpCircle size={16} className="mt-0.5 flex-shrink-0 text-rose-500" />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-slate-900">{entry.label}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
            <span>
              <Calendar size={10} className="mr-1 inline" />
              {formatVnDate(entry.expected_date)}
            </span>
            <span className={`rounded-full px-2 py-0.5 ${STATUS_PILL[entry.status]}`}>
              {STATUS_LABEL[entry.status]}
            </span>
            {partial && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-700">
                Đã thu/trả {formatVnd(entry.paid_actual_vnd)} / {formatVnd(entry.amount_vnd)}
              </span>
            )}
            {fullyPaid && (
              <span className="inline-flex items-center gap-0.5 text-emerald-600">
                <CheckCircle2 size={11} /> Hoàn tất
              </span>
            )}
            {entry.notes && (
              <span className="text-slate-400">— {entry.notes}</span>
            )}
          </div>
        </div>
        <p
          className={`flex-shrink-0 text-sm font-semibold ${
            isInflow ? "text-emerald-700" : "text-rose-700"
          }`}
        >
          {isInflow ? "+" : "−"}
          {formatVnd(entry.amount_vnd)}
        </p>
      </div>
    </li>
  );
}


function AddEntryForm({
  projectId,
  token,
  orgId,
  submitting,
  setSubmitting,
  onClose,
  onAdded,
}: {
  projectId: string;
  token: string;
  orgId: string;
  submitting: boolean;
  setSubmitting: (b: boolean) => void;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [kind, setKind] = useState<EntryKind>("inflow");
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState<string>("");
  const [expectedDate, setExpectedDate] = useState<string>(
    new Date().toISOString().slice(0, 10),
  );
  const [notes, setNotes] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    const amt = parseInt(amount.replace(/[^0-9]/g, ""), 10);
    if (!label.trim() || !amt || amt < 0) {
      setErr("Nhập tên + số tiền hợp lệ.");
      return;
    }
    setSubmitting(true);
    try {
      await apiFetch(
        "/api/v1/cashflow/projects/" + projectId + "/entries",
        {
          method: "POST",
          token,
          orgId,
          body: {
            kind,
            label: label.trim(),
            amount_vnd: amt,
            expected_date: expectedDate,
            notes: notes.trim() || null,
            status: "planned",
          },
        },
      );
      onAdded();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-4">
      <h3 className="text-sm font-semibold text-slate-900">Thêm dòng tiền mới</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="text-xs text-slate-600">Loại</label>
          <div className="mt-1 inline-flex w-full rounded-md bg-white p-0.5 text-xs ring-1 ring-slate-200">
            <button
              type="button"
              onClick={() => setKind("inflow")}
              className={`flex-1 rounded px-3 py-1.5 ${
                kind === "inflow" ? "bg-emerald-500 text-white" : "text-slate-700"
              }`}
            >
              Thu (Bên A trả)
            </button>
            <button
              type="button"
              onClick={() => setKind("outflow")}
              className={`flex-1 rounded px-3 py-1.5 ${
                kind === "outflow" ? "bg-rose-500 text-white" : "text-slate-700"
              }`}
            >
              Chi (Trả NCC / công nhân)
            </button>
          </div>
        </div>
        <div>
          <label className="text-xs text-slate-600">Ngày dự kiến</label>
          <input
            type="date"
            value={expectedDate}
            onChange={(e) => setExpectedDate(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div className="sm:col-span-2">
          <label className="text-xs text-slate-600">Mô tả</label>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="vd: Thanh toán 30% sau khi nghiệm thu kết cấu"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Số tiền (VNĐ)</label>
          <input
            type="text"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="vd: 850000000"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            inputMode="numeric"
          />
        </div>
        <div>
          <label className="text-xs text-slate-600">Ghi chú (tuỳ chọn)</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="—"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}

      <div className="mt-3 flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm text-slate-700"
        >
          Huỷ
        </button>
        <button
          onClick={submit}
          disabled={submitting}
          className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
          Thêm
        </button>
      </div>
    </div>
  );
}


// ---------- Formatters ----------


function formatVnd(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}


function formatVndShort(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (abs >= 1_000_000_000) return `${sign}${(abs / 1_000_000_000).toFixed(1)}T`;
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(0)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(0)}K`;
  return `${sign}${abs}`;
}


function formatMonthVi(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
}


function formatVnDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
