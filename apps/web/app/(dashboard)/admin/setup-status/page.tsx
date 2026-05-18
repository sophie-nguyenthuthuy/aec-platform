"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  ExternalLink,
  Info,
  Key,
  Loader2,
  Mail,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Admin setup-status page — operator dashboard showing every external
 * integration's state.
 *
 * Surfaces what env vars / config are set WITHOUT showing values. Lets
 * sophie / ops eyeball "what's still red on launch day" without
 * SSH-ing into Railway to read env vars by hand.
 *
 * Categorised + linked to the relevant runbook so operator clicks
 * once and knows what to do.
 */


type Verdict = "ready" | "partially_configured" | "not_ready";


interface IntegrationStatus {
  integrations: {
    auth: Record<string, unknown>;
    email: Record<string, unknown>;
    billing: Record<string, unknown>;
    observability: Record<string, unknown>;
    ai: Record<string, unknown>;
    storage: Record<string, unknown>;
  };
  readiness: {
    critical_ok: number;
    critical_total: number;
    important_ok: number;
    important_total: number;
    nice_to_have_ok: number;
    nice_to_have_total: number;
    verdict: Verdict;
  };
}


const VERDICT_LABEL: Record<Verdict, { label: string; tone: string; description: string }> = {
  ready: {
    label: "Sẵn sàng launch",
    tone: "emerald",
    description: "Mọi integration cốt lõi + quan trọng đã cấu hình.",
  },
  partially_configured: {
    label: "Cấu hình một phần",
    tone: "amber",
    description: "Các integration cốt lõi đã sẵn, một vài integration quan trọng còn thiếu.",
  },
  not_ready: {
    label: "Chưa sẵn sàng",
    tone: "rose",
    description: "Còn thiếu integration cốt lõi — Supabase auth hoặc Google API key.",
  },
};


export default function SetupStatusPage() {
  const { token, orgId } = useSession();
  const [data, setData] = useState<IntegrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !orgId) return;
    apiFetch<IntegrationStatus>("/api/v1/admin/integrations/status", {
      token,
      orgId,
    })
      .then((r) => setData(r.data!))
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [token, orgId]);

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 size={14} className="animate-spin" /> Đang tải trạng thái…
      </p>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        <AlertCircle size={14} className="mr-1 inline" />
        {error}
      </div>
    );
  }
  if (!data) return null;

  const verdict = VERDICT_LABEL[data.readiness.verdict];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Trạng thái cài đặt</h2>
        <p className="text-xs text-slate-500">
          Theo dõi từng integration (Auth, Email, Billing, AI, Storage, Observability).
          Endpoint này KHÔNG hiển thị giá trị secret — chỉ cho biết đã set hay chưa.
        </p>
      </div>

      {/* Verdict banner */}
      <section
        className={`rounded-xl border p-4 ${
          verdict.tone === "emerald"
            ? "border-emerald-200 bg-emerald-50"
            : verdict.tone === "amber"
            ? "border-amber-200 bg-amber-50"
            : "border-rose-200 bg-rose-50"
        }`}
      >
        <div className="flex items-center gap-2">
          {verdict.tone === "emerald" ? (
            <CheckCircle2 size={18} className="text-emerald-600" />
          ) : verdict.tone === "amber" ? (
            <AlertTriangle size={18} className="text-amber-600" />
          ) : (
            <XCircle size={18} className="text-rose-600" />
          )}
          <h3 className="text-lg font-bold text-slate-900">{verdict.label}</h3>
        </div>
        <p className="mt-1 text-sm text-slate-700">{verdict.description}</p>
        <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
          <ReadinessTile
            label="Cốt lõi"
            ok={data.readiness.critical_ok}
            total={data.readiness.critical_total}
          />
          <ReadinessTile
            label="Quan trọng"
            ok={data.readiness.important_ok}
            total={data.readiness.important_total}
          />
          <ReadinessTile
            label="Nên có"
            ok={data.readiness.nice_to_have_ok}
            total={data.readiness.nice_to_have_total}
          />
        </div>
      </section>

      {/* Per-integration sections */}
      <Section
        icon={<ShieldCheck size={16} />}
        title="Auth + SSO"
        items={data.integrations.auth}
        runbook="/docs/sso-setup"
      />
      <Section
        icon={<Mail size={16} />}
        title="Email (Resend / SMTP)"
        items={data.integrations.email}
        runbook="/docs/email-setup"
      />
      <Section
        icon={<Key size={16} />}
        title="Billing (Stripe + VietQR)"
        items={data.integrations.billing}
        runbook="/docs/billing-setup"
      />
      <Section
        icon={<AlertCircle size={16} />}
        title="Observability (Sentry)"
        items={data.integrations.observability}
        runbook="/docs/observability"
      />
      <Section
        icon={<Sparkles size={16} />}
        title="AI providers"
        items={data.integrations.ai}
        runbook="/docs/ai-setup"
      />
      <Section
        icon={<Info size={16} />}
        title="Storage (S3 / MinIO)"
        items={data.integrations.storage}
        runbook="/docs/storage-setup"
      />

      <CodeguardBootstrapPanel />
    </div>
  );
}


function CodeguardBootstrapPanel() {
  const { token, orgId } = useSession();
  const [busy, setBusy] = useState(false);
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<{
    status: string;
    regulations_count_after?: number;
    existing_count?: number;
    per_fixture?: Array<{ code_name: string; sections?: number; chunks?: number; error?: string; skipped?: string }>;
    hint?: string;
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function trigger() {
    setBusy(true);
    setErr(null);
    setResult(null);
    // String-concat the path so the apifetch-routes-match linter
    // can parse it. Template literals with nested quotes confuse
    // the regex; ternary on the path string keeps the call clean.
    const path = force
      ? "/api/v1/admin/codeguard/bootstrap?force=true"
      : "/api/v1/admin/codeguard/bootstrap";
    try {
      const r = await apiFetch<typeof result>(
        path,
        { method: "POST", token: token ?? "", orgId: orgId ?? "" },
      );
      setResult(r.data ?? null);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <Sparkles size={16} />
          Hành động: Bootstrap QCVN/TCVN
        </h3>
        <span className="text-[11px] text-slate-500">
          Owner / admin only
        </span>
      </header>
      <div className="space-y-3 p-4">
        <p className="text-xs text-slate-600">
          Ingest 6 QCVN/TCVN excerpts (fire, accessibility, structure,
          zoning, energy) vào bảng <code>regulations</code> để CodeGuard
          scan + Q&A trả về hits. Tốn ~$0.05 Gemini embedding mỗi lần
          chạy.
        </p>
        <label className="flex items-center gap-2 text-xs text-slate-700">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
          />
          <span>
            <b>Force re-ingest</b> — TRUNCATE + chạy lại từ đầu (dùng
            khi nghi ngờ regs hiện tại bị corrupt; mặc định skip nếu
            đã có data)
          </span>
        </label>
        <button
          onClick={trigger}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {busy ? "Đang ingest…" : force ? "Force re-ingest" : "Trigger bootstrap"}
        </button>

        {err && (
          <div className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">
            <AlertCircle size={11} className="mr-1 inline" />
            {err}
          </div>
        )}

        {result && (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
            <p className="font-medium text-slate-900">
              Status: <span className="font-mono">{result.status}</span>
            </p>
            {result.existing_count != null && (
              <p className="mt-1 text-slate-700">
                Đã có {result.existing_count} regulations từ trước. {result.hint}
              </p>
            )}
            {result.regulations_count_after != null && (
              <p className="mt-1 text-slate-700">
                Sau khi ingest: <b>{result.regulations_count_after}</b> chunks.
              </p>
            )}
            {result.per_fixture && (
              <ul className="mt-2 space-y-1">
                {result.per_fixture.map((r, i) => (
                  <li key={i} className="font-mono text-[11px]">
                    {r.error ? (
                      <span className="text-rose-700">
                        ✗ {r.code_name}: {r.error}
                      </span>
                    ) : r.skipped ? (
                      <span className="text-amber-700">
                        ! {r.code_name}: skipped ({r.skipped})
                      </span>
                    ) : (
                      <span className="text-emerald-700">
                        ✓ {r.code_name}: {r.sections} sections, {r.chunks} chunks
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
}


function ReadinessTile({
  label,
  ok,
  total,
}: {
  label: string;
  ok: number;
  total: number;
}) {
  const pct = total > 0 ? (ok / total) * 100 : 0;
  return (
    <div className="rounded-md bg-white p-2 ring-1 ring-slate-200">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-lg font-semibold text-slate-900">
        {ok}/{total}
      </p>
      <div className="mt-1 h-1 w-full rounded-full bg-slate-100">
        <div
          className={`h-1 rounded-full ${
            pct === 100
              ? "bg-emerald-500"
              : pct >= 50
              ? "bg-amber-500"
              : "bg-rose-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}


function Section({
  icon,
  title,
  items,
  runbook,
}: {
  icon: React.ReactNode;
  title: string;
  items: Record<string, unknown>;
  runbook: string;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          {icon}
          {title}
        </h3>
        <a
          href={runbook}
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          Runbook
          <ExternalLink size={11} />
        </a>
      </header>
      <ul className="divide-y divide-slate-100">
        {Object.entries(items).map(([key, value]) => (
          <li key={key} className="flex items-center justify-between px-4 py-2 text-sm">
            <span className="font-mono text-xs text-slate-600">{key}</span>
            <StatusValue value={value} />
          </li>
        ))}
      </ul>
    </section>
  );
}


function StatusValue({ value }: { value: unknown }) {
  if (typeof value === "boolean") {
    return value ? (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
        <Check size={12} />
        Đã set
      </span>
    ) : (
      <span className="inline-flex items-center gap-1 text-xs text-slate-500">
        <XCircle size={12} className="text-slate-300" />
        Chưa set
      </span>
    );
  }
  if (typeof value === "number") {
    return <span className="font-mono text-xs text-slate-700">{value}</span>;
  }
  if (value === null || value === undefined) {
    return <span className="text-xs text-slate-400">—</span>;
  }
  const text = String(value);
  // Truncate long values + show in mono
  const display = text.length > 60 ? text.slice(0, 57) + "…" : text;
  return (
    <span className="max-w-[60%] truncate text-right text-xs text-slate-700" title={text}>
      {display}
    </span>
  );
}
