"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  Check,
  Copy,
  CreditCard,
  Loader2,
  QrCode,
  Sparkles,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


// ---------- Types matching apps/api/services/billing.py ----------

interface Plan {
  slug: "starter" | "pro" | "enterprise";
  name_vi: string;
  tagline_vi: string;
  price_vnd_monthly: number | null;
  price_usd_monthly: number | null;
  max_users: number | null;
  max_projects: number | null;
  max_drawings_gb: number | null;
  features_vi: string[];
}

interface CurrentSubscription {
  plan: string;
  status: string;
  billing_source: string | null;
  period_end: string | null;
  vietqr_reference: string | null;
  limits: {
    name_vi: string;
    max_users: number | null;
    max_projects: number | null;
    max_drawings_gb: number | null;
  };
}

interface VietQrPayload {
  reference: string;
  amount_vnd: number;
  plan: string;
  bank: {
    bank_name: string;
    account_number: string;
    account_holder: string;
    memo_format: string;
  };
  instructions_vi: string;
}


export default function BillingPage() {
  const { token, orgId } = useSession();
  const params = useSearchParams();

  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [current, setCurrent] = useState<CurrentSubscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // VietQR modal state
  const [vietqr, setVietqr] = useState<VietQrPayload | null>(null);
  const [vietqrSubmitting, setVietqrSubmitting] = useState(false);

  const stripeStatus = params.get("stripe_status");

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    (async () => {
      try {
        const [plansRes, currentRes] = await Promise.all([
          apiFetch<{ plans: Plan[] }>("/api/v1/billing/plans", { token, orgId }),
          apiFetch<CurrentSubscription>("/api/v1/billing/current", { token, orgId }),
        ]);
        if (cancelled) return;
        setPlans(plansRes.data!.plans);
        setCurrent(currentRes.data!);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, orgId]);

  async function startVietQr(plan: Plan["slug"]) {
    setError(null);
    try {
      const res = await apiFetch<VietQrPayload>(
        `/api/v1/billing/checkout/vietqr?plan=${plan}`,
        { method: "POST", token: token ?? "", orgId: orgId ?? "" },
      );
      setVietqr(res.data!);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function startStripe(plan: Plan["slug"]) {
    setError(null);
    try {
      const res = await apiFetch<{ checkout_url: string }>(
        `/api/v1/billing/checkout/stripe?plan=${plan}`,
        { method: "POST", token: token ?? "", orgId: orgId ?? "" },
      );
      window.location.href = res.data!.checkout_url;
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function confirmVietQr() {
    if (!vietqr) return;
    setVietqrSubmitting(true);
    setError(null);
    try {
      await apiFetch(
        `/api/v1/billing/vietqr/${encodeURIComponent(vietqr.reference)}/confirm`,
        { method: "POST", token: token ?? "", orgId: orgId ?? "" },
      );
      // Refresh current state
      const refreshed = await apiFetch<CurrentSubscription>(
        "/api/v1/billing/current",
        { token: token ?? "", orgId: orgId ?? "" },
      );
      setCurrent(refreshed.data!);
      setVietqr(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setVietqrSubmitting(false);
    }
  }

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 size={14} className="animate-spin" /> Đang tải gói cước…
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Gói cước & Thanh toán</h2>
        <p className="text-sm text-slate-600">
          Chọn gói phù hợp với quy mô công ty bạn. Tất cả 14 module luôn
          được kích hoạt — gói chỉ ảnh hưởng giới hạn dự án + lưu trữ +
          quota AI.
        </p>
      </div>

      {/* Status banners */}
      {stripeStatus === "success" && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
          ✓ Thanh toán Stripe thành công. Gói cước sẽ kích hoạt trong vài giây.
        </div>
      )}
      {stripeStatus === "cancelled" && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Bạn đã huỷ thanh toán. Chưa có thay đổi nào trên gói cước.
        </div>
      )}

      {/* Current subscription card */}
      {current && (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-900">
            Gói hiện tại
          </h3>
          <div className="mt-2 flex flex-wrap items-baseline gap-3">
            <p className="text-2xl font-bold text-slate-900">
              {current.limits.name_vi}
            </p>
            <StatusBadge status={current.status} />
            {current.period_end && (
              <p className="text-xs text-slate-500">
                Hiệu lực đến: {formatVnDate(current.period_end)}
              </p>
            )}
          </div>
          <div className="mt-3 grid grid-cols-3 gap-3 text-xs text-slate-600 sm:grid-cols-4">
            <Limit label="Người dùng" value={current.limits.max_users} />
            <Limit label="Dự án" value={current.limits.max_projects} />
            <Limit label="Lưu trữ" value={current.limits.max_drawings_gb} suffix=" GB" />
          </div>
          {current.status === "pending_payment" && current.vietqr_reference && (
            <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
              Đang chờ chuyển khoản cho mã: <b>{current.vietqr_reference}</b>
            </p>
          )}
        </section>
      )}

      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <AlertCircle size={14} className="inline mr-1" />
          {error}
        </div>
      )}

      {/* Plan picker */}
      <div className="grid gap-4 sm:grid-cols-3">
        {plans?.map((plan) => (
          <PlanCard
            key={plan.slug}
            plan={plan}
            current={plan.slug === current?.plan}
            onUpgradeVietQr={() => startVietQr(plan.slug)}
            onUpgradeStripe={() => startStripe(plan.slug)}
          />
        ))}
      </div>

      {/* VietQR transfer modal */}
      {vietqr && (
        <VietQrModal
          payload={vietqr}
          submitting={vietqrSubmitting}
          onClose={() => setVietqr(null)}
          onConfirm={confirmVietQr}
        />
      )}
    </div>
  );
}


// ---------- Subcomponents ----------


function StatusBadge({ status }: { status: string }) {
  const cls = {
    active: "bg-emerald-100 text-emerald-700",
    pending_payment: "bg-amber-100 text-amber-700",
    past_due: "bg-rose-100 text-rose-700",
    cancelled: "bg-slate-200 text-slate-600",
  }[status] || "bg-slate-100 text-slate-600";
  const label = {
    active: "Đang hoạt động",
    pending_payment: "Đang chờ thanh toán",
    past_due: "Trễ thanh toán",
    cancelled: "Đã huỷ",
  }[status] || status;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}


function Limit({
  label,
  value,
  suffix = "",
}: {
  label: string;
  value: number | null;
  suffix?: string;
}) {
  return (
    <div>
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="font-medium text-slate-900">
        {value === null ? "Không giới hạn" : `${value}${suffix}`}
      </p>
    </div>
  );
}


function PlanCard({
  plan,
  current,
  onUpgradeVietQr,
  onUpgradeStripe,
}: {
  plan: Plan;
  current: boolean;
  onUpgradeVietQr: () => void;
  onUpgradeStripe: () => void;
}) {
  const isEnterprise = plan.slug === "enterprise";
  const isStarter = plan.slug === "starter";

  return (
    <article
      className={`flex flex-col rounded-xl border p-4 ${
        current
          ? "border-blue-500 bg-blue-50/50 ring-2 ring-blue-200"
          : "border-slate-200 bg-white"
      }`}
    >
      <header className="flex items-baseline justify-between gap-2">
        <h3 className="text-lg font-bold text-slate-900">{plan.name_vi}</h3>
        {current && (
          <span className="rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-semibold text-white">
            Đang dùng
          </span>
        )}
      </header>
      <p className="mt-1 text-xs text-slate-600">{plan.tagline_vi}</p>

      <div className="mt-3">
        {isEnterprise ? (
          <p className="text-sm font-medium text-slate-900">Liên hệ báo giá</p>
        ) : (
          <>
            <p className="text-3xl font-bold text-slate-900">
              {plan.price_vnd_monthly === 0
                ? "Miễn phí"
                : formatVnd(plan.price_vnd_monthly ?? 0)}
            </p>
            {plan.price_vnd_monthly !== 0 && (
              <p className="text-xs text-slate-500">/tháng (chưa VAT)</p>
            )}
          </>
        )}
      </div>

      <ul className="mt-3 flex-1 space-y-1.5 text-xs text-slate-700">
        {plan.features_vi.map((f) => (
          <li key={f} className="flex items-start gap-1.5">
            <Check size={12} className="mt-0.5 flex-shrink-0 text-emerald-500" />
            <span>{f}</span>
          </li>
        ))}
      </ul>

      <div className="mt-4 space-y-2">
        {current || isStarter ? (
          <button
            disabled
            className="w-full rounded-md bg-slate-100 px-4 py-2 text-sm font-medium text-slate-500"
          >
            {current ? "Gói hiện tại" : "Mặc định khi tạo tổ chức"}
          </button>
        ) : isEnterprise ? (
          <a
            href="mailto:sales@aec-platform.vn?subject=Quan%20t%C3%A2m%20g%C3%B3i%20Doanh%20nghi%E1%BB%87p"
            className="block w-full rounded-md bg-slate-900 px-4 py-2 text-center text-sm font-medium text-white hover:bg-slate-800"
          >
            Liên hệ sales
          </a>
        ) : (
          <>
            <button
              onClick={onUpgradeVietQr}
              className="flex w-full items-center justify-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              <QrCode size={14} />
              Chuyển khoản VietQR
            </button>
            <button
              onClick={onUpgradeStripe}
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <CreditCard size={14} />
              Thanh toán bằng thẻ (USD)
            </button>
          </>
        )}
      </div>
    </article>
  );
}


function VietQrModal({
  payload,
  submitting,
  onClose,
  onConfirm,
}: {
  payload: VietQrPayload;
  submitting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  function copy(value: string, what: string) {
    navigator.clipboard?.writeText(value);
    setCopied(what);
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      role="dialog"
    >
      <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-xl bg-white p-5">
        <header className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-bold text-slate-900">
              Chuyển khoản nâng cấp gói {payload.plan.toUpperCase()}
            </h3>
            <p className="mt-1 text-xs text-slate-600">
              {payload.instructions_vi}
            </p>
          </div>
          <button
            onClick={onClose}
            type="button"
            className="text-slate-400 hover:text-slate-600"
            aria-label="Đóng"
          >
            ✕
          </button>
        </header>

        <div className="mt-4 space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
          <CopyRow
            label="Ngân hàng"
            value={payload.bank.bank_name}
            copyState={copied}
            onCopy={() => copy(payload.bank.bank_name, "Ngân hàng")}
          />
          <CopyRow
            label="Số tài khoản"
            value={payload.bank.account_number}
            copyState={copied}
            onCopy={() => copy(payload.bank.account_number, "Số tài khoản")}
          />
          <CopyRow
            label="Chủ tài khoản"
            value={payload.bank.account_holder}
            copyState={copied}
            onCopy={() => copy(payload.bank.account_holder, "Chủ tài khoản")}
          />
          <CopyRow
            label="Số tiền"
            value={formatVnd(payload.amount_vnd)}
            copyState={copied}
            onCopy={() => copy(String(payload.amount_vnd), "Số tiền")}
          />
          <CopyRow
            label="Nội dung CK"
            value={payload.bank.memo_format}
            highlight
            copyState={copied}
            onCopy={() => copy(payload.bank.memo_format, "Nội dung CK")}
          />
        </div>

        <p className="mt-4 text-[11px] text-slate-500">
          ⚠ Nội dung chuyển khoản phải <b>chính xác từng ký tự</b>. Sau khi
          chuyển khoản, bấm "Tôi đã chuyển khoản" để kích hoạt gói. Ops sẽ
          đối chiếu với sao kê ngân hàng — sai sót sẽ được xử lý trong 1
          ngày làm việc.
        </p>

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
          >
            Để sau
          </button>
          <button
            onClick={onConfirm}
            disabled={submitting}
            className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : null}
            Tôi đã chuyển khoản
          </button>
        </div>
      </div>
    </div>
  );
}


function CopyRow({
  label,
  value,
  highlight,
  copyState,
  onCopy,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  copyState: string | null;
  onCopy: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex-1">
        <p className="text-[10px] uppercase tracking-wide text-slate-500">
          {label}
        </p>
        <p
          className={`mt-0.5 break-all ${
            highlight ? "font-mono font-semibold text-blue-700" : "text-slate-900"
          }`}
        >
          {value}
        </p>
      </div>
      <button
        onClick={onCopy}
        type="button"
        className="flex-shrink-0 rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700"
        title={`Copy ${label}`}
      >
        {copyState === label ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}


function formatVnd(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}


function formatVnDate(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}/${String(
    d.getMonth() + 1,
  ).padStart(2, "0")}/${d.getFullYear()}`;
}
