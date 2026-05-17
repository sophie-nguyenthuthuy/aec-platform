"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  Clock,
  DollarSign,
  Loader2,
  Plus,
  ShieldCheck,
  ShieldX,
  Wrench,
  X,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Warranty Tracker — bảo hành công trình dashboard.
 *
 * Three-tab interface:
 *   1. Expiring soon — KPI tiles + warranties sorted by expiry ASC.
 *      The most-actionable view: "what do I need to inspect THIS
 *      week before warranty closes?".
 *   2. Active claims — list with status pills + cost paid-by attribution.
 *   3. Summary KPI — vendor-covered vs contractor-absorbed VND
 *      (proves the warranty's monetary value to building owner).
 */


type Tab = "expiring" | "claims" | "summary";


interface ExpiringItem {
  id: string;
  item_name: string;
  category: string | null;
  vendor: string | null;
  start_date: string | null;
  expiry_date: string | null;
  days_to_expiry: number | null;
  warranty_period_months: number | null;
  coverage: string | null;
  status: string;
  claim_contact: Record<string, unknown> | null;
}

interface Claim {
  id: string;
  status: string;
  severity: string;
  summary: string;
  description: string | null;
  reporter_name: string | null;
  reporter_email: string | null;
  reported_on: string | null;
  acknowledged_on: string | null;
  resolved_on: string | null;
  cost_vnd: number | null;
  paid_by: string | null;
  warranty_item_id: string;
  item_name: string;
  vendor: string | null;
  expiry_date: string | null;
  created_at: string;
}

interface Summary {
  active_count: number;
  expiring_30: number;
  expiring_90: number;
  open_claims: number;
  resolved_claims: number;
  rejected_claims: number;
  vendor_covered_vnd: number;
  contractor_absorbed_vnd: number;
}


const CLAIM_STATUS_LABEL: Record<string, string> = {
  open: "Mới mở",
  investigating: "Đang điều tra",
  vendor_notified: "Đã báo NCC",
  in_repair: "Đang sửa",
  resolved: "Đã giải quyết",
  rejected: "Bị từ chối",
  abandoned: "Bỏ dở",
};

const CLAIM_STATUS_PILL: Record<string, string> = {
  open: "bg-rose-100 text-rose-700",
  investigating: "bg-amber-100 text-amber-700",
  vendor_notified: "bg-blue-100 text-blue-700",
  in_repair: "bg-violet-100 text-violet-700",
  resolved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-slate-100 text-slate-600",
  abandoned: "bg-slate-100 text-slate-400",
};

const SEVERITY_PILL: Record<string, string> = {
  minor: "bg-slate-100 text-slate-700",
  major: "bg-amber-100 text-amber-700",
  critical: "bg-rose-100 text-rose-700",
};

const PAID_BY_LABEL: Record<string, string> = {
  vendor_covered: "NCC chi trả",
  contractor_absorbed: "Tổng thầu trả",
  owner_paid: "Chủ đầu tư trả",
  shared: "Chia sẻ",
};


export default function WarrantyTrackerPage() {
  const { token, orgId } = useSession();
  const params = useParams<{ project_id: string }>();
  const projectId = params?.project_id;

  const [tab, setTab] = useState<Tab>("expiring");
  const [expiring, setExpiring] = useState<ExpiringItem[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filingClaimFor, setFilingClaimFor] = useState<ExpiringItem | null>(null);

  const fetchAll = useCallback(async () => {
    if (!token || !orgId || !projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [e, c, s] = await Promise.all([
        apiFetch<{ items: ExpiringItem[]; horizon_days: number }>(
          `/api/v1/warranty-tracker/projects/${projectId}/expiring?days=90`,
          { token, orgId },
        ),
        apiFetch<{ claims: Claim[] }>(
          `/api/v1/warranty-tracker/projects/${projectId}/claims`,
          { token, orgId },
        ),
        apiFetch<Summary>(
          `/api/v1/warranty-tracker/projects/${projectId}/summary`,
          { token, orgId },
        ),
      ]);
      setExpiring(e.data!.items);
      setClaims(c.data!.claims);
      setSummary(s.data!);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token, orgId, projectId]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

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
              <ShieldCheck size={22} className="text-emerald-600" />
              Bảo hành công trình
            </h2>
            <p className="text-xs text-slate-500">
              Theo dõi hạng mục bảo hành + ghi nhận claims khi có vấn đề.
              Email nhắc nhở tự động 60/30/7 ngày trước hết hạn.
            </p>
          </div>
        </div>
      </div>

      {error && (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
      )}

      {filingClaimFor && (
        <FileClaimModal
          item={filingClaimFor}
          token={token ?? ""}
          orgId={orgId ?? ""}
          onClose={() => setFilingClaimFor(null)}
          onFiled={() => {
            setFilingClaimFor(null);
            void fetchAll();
          }}
        />
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải…
        </p>
      ) : summary ? (
        <>
          {/* KPI tiles always shown */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiTile
              icon={<ShieldCheck size={14} />}
              label="Đang còn bảo hành"
              value={summary.active_count.toString()}
              tone="emerald"
            />
            <KpiTile
              icon={<Clock size={14} />}
              label="Hết hạn 30 ngày tới"
              value={summary.expiring_30.toString()}
              tone={summary.expiring_30 > 0 ? "amber" : "default"}
            />
            <KpiTile
              icon={<Wrench size={14} />}
              label="Claims đang xử lý"
              value={summary.open_claims.toString()}
              tone={summary.open_claims > 0 ? "rose" : "default"}
            />
            <KpiTile
              icon={<DollarSign size={14} />}
              label="NCC đã chi trả"
              value={formatVndShort(summary.vendor_covered_vnd)}
              tone="emerald"
            />
          </div>

          {/* Vendor vs contractor split bar */}
          {(summary.vendor_covered_vnd > 0 ||
            summary.contractor_absorbed_vnd > 0) && (
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-900">
                Phân bổ chi phí claims đã giải quyết
              </h3>
              <CoverageBar
                vendor={summary.vendor_covered_vnd}
                contractor={summary.contractor_absorbed_vnd}
              />
            </section>
          )}

          {/* Tab toggle */}
          <div className="inline-flex rounded-md bg-slate-100 p-0.5 text-xs">
            <TabBtn
              active={tab === "expiring"}
              onClick={() => setTab("expiring")}
              label={`Sắp hết hạn (${expiring.length})`}
            />
            <TabBtn
              active={tab === "claims"}
              onClick={() => setTab("claims")}
              label={`Claims (${claims.length})`}
            />
          </div>

          {tab === "expiring" ? (
            <ExpiringList items={expiring} onFileClaim={setFilingClaimFor} />
          ) : (
            <ClaimsList claims={claims} />
          )}
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
  tone: "default" | "emerald" | "amber" | "rose";
}) {
  const valueTone = {
    default: "text-slate-900",
    emerald: "text-emerald-700",
    amber: "text-amber-700",
    rose: "text-rose-700",
  }[tone];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className={`mt-1 text-xl font-bold ${valueTone}`}>{value}</p>
    </div>
  );
}


function TabBtn({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded px-3 py-1.5 ${
        active
          ? "bg-white font-medium text-slate-900 shadow-sm"
          : "text-slate-500 hover:text-slate-700"
      }`}
    >
      {label}
    </button>
  );
}


function CoverageBar({
  vendor,
  contractor,
}: {
  vendor: number;
  contractor: number;
}) {
  const total = vendor + contractor;
  if (total === 0) return null;
  const vendorPct = (vendor / total) * 100;
  return (
    <div className="mt-3">
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full bg-emerald-500"
          style={{ width: `${vendorPct}%` }}
          title={`NCC: ${formatVnd(vendor)}`}
        />
        <div
          className="h-full bg-rose-400"
          style={{ width: `${100 - vendorPct}%` }}
          title={`Tổng thầu: ${formatVnd(contractor)}`}
        />
      </div>
      <div className="mt-2 flex justify-between text-xs">
        <span className="text-emerald-700">
          NCC chi trả: <b>{formatVnd(vendor)}</b> ({vendorPct.toFixed(1)}%)
        </span>
        <span className="text-rose-700">
          Tổng thầu trả: <b>{formatVnd(contractor)}</b> ({(100 - vendorPct).toFixed(1)}%)
        </span>
      </div>
    </div>
  );
}


function ExpiringList({
  items,
  onFileClaim,
}: {
  items: ExpiringItem[];
  onFileClaim: (item: ExpiringItem) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
        <ShieldCheck size={32} className="mx-auto text-emerald-500" />
        <p className="mt-3 text-sm text-slate-600">
          Không có bảo hành nào sắp hết hạn trong 90 ngày tới.
        </p>
      </div>
    );
  }
  return (
    <ul className="space-y-2">
      {items.map((item) => {
        const days = item.days_to_expiry ?? 0;
        const urgent = days <= 30;
        const critical = days <= 7;
        return (
          <li
            key={item.id}
            className={`rounded-xl border bg-white p-4 ${
              critical
                ? "border-rose-300"
                : urgent
                ? "border-amber-300"
                : "border-slate-200"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <h4 className="font-semibold text-slate-900">
                    {item.item_name}
                  </h4>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      critical
                        ? "bg-rose-100 text-rose-700"
                        : urgent
                        ? "bg-amber-100 text-amber-700"
                        : "bg-slate-100 text-slate-700"
                    }`}
                  >
                    Còn {days} ngày
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
                  {item.category && <span>{item.category}</span>}
                  {item.vendor && <span>NCC: {item.vendor}</span>}
                  {item.expiry_date && (
                    <span>
                      <Calendar size={10} className="mr-1 inline" />
                      Hết hạn: {formatVnDate(item.expiry_date)}
                    </span>
                  )}
                </div>
                {item.coverage && (
                  <p className="mt-1 text-xs text-slate-600">{item.coverage}</p>
                )}
              </div>
              <button
                onClick={() => onFileClaim(item)}
                className="flex-shrink-0 rounded-md bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100"
              >
                <Plus size={11} className="mr-1 inline" />
                File claim
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}


function ClaimsList({ claims }: { claims: Claim[] }) {
  if (claims.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
        <Wrench size={32} className="mx-auto text-slate-400" />
        <p className="mt-3 text-sm text-slate-600">
          Chưa có claim bảo hành nào.
        </p>
      </div>
    );
  }
  return (
    <ul className="space-y-2">
      {claims.map((claim) => (
        <li key={claim.id} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex items-start gap-3">
            {claim.status === "resolved" ? (
              <CheckCircle2 size={16} className="mt-0.5 text-emerald-500" />
            ) : claim.status === "rejected" ? (
              <ShieldX size={16} className="mt-0.5 text-slate-400" />
            ) : (
              <Wrench size={16} className="mt-0.5 text-amber-500" />
            )}
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-baseline gap-2">
                <h4 className="font-medium text-slate-900">{claim.summary}</h4>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    CLAIM_STATUS_PILL[claim.status] || "bg-slate-100"
                  }`}
                >
                  {CLAIM_STATUS_LABEL[claim.status] || claim.status}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    SEVERITY_PILL[claim.severity]
                  }`}
                >
                  {claim.severity === "critical" && <AlertTriangle size={10} className="mr-1 inline" />}
                  {claim.severity}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
                <span>Hạng mục: {claim.item_name}</span>
                {claim.vendor && <span>NCC: {claim.vendor}</span>}
                {claim.reported_on && (
                  <span>
                    Báo cáo: {formatVnDate(claim.reported_on)}
                  </span>
                )}
                {claim.resolved_on && (
                  <span>Xong: {formatVnDate(claim.resolved_on)}</span>
                )}
                {claim.reporter_name && (
                  <span>Người báo: {claim.reporter_name}</span>
                )}
              </div>
              {claim.description && (
                <p className="mt-1 text-xs text-slate-600">{claim.description}</p>
              )}
              {(claim.cost_vnd || claim.paid_by) && (
                <div className="mt-2 inline-flex items-center gap-2 rounded-md bg-slate-50 px-2 py-1 text-xs">
                  {claim.cost_vnd && <span className="font-semibold">{formatVnd(claim.cost_vnd)}</span>}
                  {claim.paid_by && (
                    <span className="text-slate-600">
                      {PAID_BY_LABEL[claim.paid_by] || claim.paid_by}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}


function FileClaimModal({
  item,
  token,
  orgId,
  onClose,
  onFiled,
}: {
  item: ExpiringItem;
  token: string;
  orgId: string;
  onClose: () => void;
  onFiled: () => void;
}) {
  const [severity, setSeverity] = useState<"minor" | "major" | "critical">("major");
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [reporterName, setReporterName] = useState("");
  const [reporterEmail, setReporterEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setErr(null);
    if (summary.length < 2) {
      setErr("Nhập tóm tắt ngắn (≥2 ký tự).");
      return;
    }
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/warranty-tracker/items/${item.id}/claims`, {
        method: "POST",
        token,
        orgId,
        body: {
          severity,
          summary: summary.trim(),
          description: description.trim() || null,
          reporter_name: reporterName.trim() || null,
          reporter_email: reporterEmail.trim() || null,
        },
      });
      onFiled();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">
              File claim — {item.item_name}
            </h3>
            <p className="text-xs text-slate-500">
              {item.vendor ? `NCC: ${item.vendor} · ` : ""}
              Còn {item.days_to_expiry ?? "—"} ngày bảo hành
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
            aria-label="Đóng"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 grid gap-3">
          <div>
            <label className="text-xs text-slate-600">Mức độ</label>
            <div className="mt-1 inline-flex w-full rounded-md bg-slate-100 p-0.5 text-xs">
              {(["minor", "major", "critical"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSeverity(s)}
                  className={`flex-1 rounded px-3 py-1.5 ${
                    severity === s
                      ? "bg-white font-medium text-slate-900 shadow-sm"
                      : "text-slate-500"
                  }`}
                >
                  {s === "minor"
                    ? "Nhẹ"
                    : s === "major"
                    ? "Vừa"
                    : "Nghiêm trọng"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-slate-600">Tóm tắt</label>
            <input
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="vd: Máy lạnh phòng 504 không lạnh, dấu hiệu rò gas"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>

          <div>
            <label className="text-xs text-slate-600">Mô tả chi tiết (tuỳ chọn)</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-slate-600">Người báo</label>
              <input
                value={reporterName}
                onChange={(e) => setReporterName(e.target.value)}
                placeholder="Tên"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-slate-600">Email</label>
              <input
                type="email"
                value={reporterEmail}
                onChange={(e) => setReporterEmail(e.target.value)}
                placeholder="email@..."
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
              />
            </div>
          </div>
        </div>

        {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-4 py-1.5 text-sm text-slate-700"
          >
            Huỷ
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
            Tạo claim
          </button>
        </div>
      </div>
    </div>
  );
}


function formatVnd(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}


function formatVndShort(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}T ₫`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ₫`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K ₫`;
  return `${n} ₫`;
}


function formatVnDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
