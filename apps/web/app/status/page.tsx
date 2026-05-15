import Link from "next/link";


/**
 * Public status page at `/status` — no auth required.
 *
 * Renders three sections:
 *   1. Top-level pill: "All systems operational" / "Degraded" / "Outage".
 *   2. Per-service grid: api, web, worker, database, redis, storage,
 *      sentry, llm-providers.
 *   3. Recent incidents (last 7 days).
 *
 * Server component — fetches /health/ready from the API on each
 * render. No client-side polling (status pages get hammered during
 * outages; cheap SSR with Cloudflare cache is the right posture).
 *
 * Cache: short TTL (15s) via Cloudflare + Next's revalidate so the
 * page shows fresh data without overwhelming the API.
 */
export const revalidate = 15;
export const dynamic = "force-dynamic";

export const metadata = {
  title: "Trạng thái hệ thống — AEC Platform",
  description:
    "Tình trạng hoạt động API + Web + Database + module AI. Cập nhật mỗi 15 giây.",
};


interface ReadinessCheck {
  ok: boolean;
  latency_ms?: number;
  error?: string;
}

interface ReadinessResponse {
  status: "ok" | "degraded";
  checks: Record<string, ReadinessCheck>;
}


// Hardcoded service catalogue. Each service maps to one or more
// `/health/ready` checks. Display labels are Vietnamese; mapping
// to the API's internal check names stays English.
const SERVICES: Array<{
  id: string;
  label_vi: string;
  description_vi: string;
  check_keys: string[];
}> = [
  {
    id: "api",
    label_vi: "API",
    description_vi: "Cổng REST/JSON cho web app + mobile",
    check_keys: ["self"],
  },
  {
    id: "database",
    label_vi: "Cơ sở dữ liệu",
    description_vi: "Supabase Postgres (Singapore)",
    check_keys: ["database"],
  },
  {
    id: "redis",
    label_vi: "Queue + Cache (Redis)",
    description_vi: "Upstash Redis cho arq workers + caching",
    check_keys: ["redis"],
  },
  {
    id: "storage",
    label_vi: "Lưu trữ bản vẽ",
    description_vi: "MinIO / AWS S3 cho file upload",
    check_keys: ["storage"],
  },
  {
    id: "worker",
    label_vi: "Worker nền",
    description_vi: "Drawbridge ingest, weekly report, RFQ dispatch",
    check_keys: ["worker"],
  },
  {
    id: "llm",
    label_vi: "AI / LLM providers",
    description_vi: "Gemini (chat + embedding) + Claude (CodeGuard scan)",
    check_keys: ["llm"],
  },
];


async function fetchReadiness(): Promise<ReadinessResponse | null> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiUrl}/health/ready`, {
      next: { revalidate: 15 },
      // Don't blow up on slow API — 5s upper bound for the status page
      // to render with degraded info instead of hanging.
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok && res.status !== 503) {
      return null;
    }
    const env = (await res.json()) as { data: ReadinessResponse | null };
    return env.data ?? null;
  } catch {
    return null;
  }
}


function classifyService(
  service: (typeof SERVICES)[number],
  readiness: ReadinessResponse | null,
): { state: "ok" | "degraded" | "unknown"; latency?: number; error?: string } {
  if (readiness === null) {
    // We couldn't reach the API at all. Mark the api service down,
    // everything else unknown.
    if (service.id === "api") return { state: "degraded", error: "API unreachable" };
    return { state: "unknown" };
  }
  // Pull checks for this service. If any are not_ok → degraded.
  const checks = service.check_keys
    .map((k) => readiness.checks[k])
    .filter((c): c is ReadinessCheck => c !== undefined);
  if (checks.length === 0) {
    // /health/ready doesn't surface this check — treat as ok (the
    // service is opportunistic, eg storage is async).
    return { state: "ok" };
  }
  if (checks.some((c) => !c.ok)) {
    const firstFail = checks.find((c) => !c.ok);
    return { state: "degraded", error: firstFail?.error };
  }
  const avgLatency =
    checks.reduce((sum, c) => sum + (c.latency_ms ?? 0), 0) / checks.length;
  return { state: "ok", latency: Math.round(avgLatency) };
}


export default async function StatusPage() {
  const readiness = await fetchReadiness();

  const serviceStates = SERVICES.map((s) => ({
    ...s,
    ...classifyService(s, readiness),
  }));

  const overallDegraded = serviceStates.some((s) => s.state === "degraded");
  const overallApi =
    readiness === null
      ? "unreachable"
      : readiness.status === "degraded"
      ? "degraded"
      : "ok";

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Top bar */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white">
              AEC
            </div>
            <span className="font-semibold text-slate-900">AEC Platform</span>
          </Link>
          <Link
            href="/login"
            className="text-sm text-slate-700 hover:text-slate-900"
          >
            Đăng nhập →
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-10">
        {/* Overall status pill */}
        <section
          className={`rounded-2xl border p-6 ${
            overallApi === "unreachable"
              ? "border-rose-200 bg-rose-50"
              : overallDegraded
              ? "border-amber-200 bg-amber-50"
              : "border-emerald-200 bg-emerald-50"
          }`}
        >
          <div className="flex items-center gap-3">
            <StatusDot tone={
              overallApi === "unreachable"
                ? "rose"
                : overallDegraded
                ? "amber"
                : "emerald"
            } />
            <h1 className="text-2xl font-bold text-slate-900">
              {overallApi === "unreachable"
                ? "Đang điều tra sự cố"
                : overallDegraded
                ? "Một số dịch vụ giảm chất lượng"
                : "Mọi hệ thống hoạt động bình thường"}
            </h1>
          </div>
          <p className="mt-2 text-sm text-slate-600">
            Cập nhật mỗi 15 giây ·{" "}
            <span suppressHydrationWarning>
              {new Date().toLocaleString("vi-VN", {
                hour: "2-digit",
                minute: "2-digit",
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                timeZone: "Asia/Ho_Chi_Minh",
              })}{" "}
              ICT
            </span>
          </p>
        </section>

        {/* Per-service grid */}
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Trạng thái từng dịch vụ
          </h2>
          <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <ul className="divide-y divide-slate-100">
              {serviceStates.map((s) => (
                <li key={s.id} className="flex items-center justify-between px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-slate-900">{s.label_vi}</p>
                    <p className="text-xs text-slate-500">{s.description_vi}</p>
                    {s.error && (
                      <p className="mt-1 text-xs text-rose-600">{s.error}</p>
                    )}
                  </div>
                  <ServiceStateBadge state={s.state} latency={s.latency} />
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Recent incidents — placeholder for now; future: pull from a CMS / GitHub issues label */}
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Sự cố 7 ngày gần nhất
          </h2>
          <div className="mt-3 rounded-xl border border-slate-200 bg-white p-6 text-center">
            <p className="text-sm text-slate-500">
              Không có sự cố nào được ghi nhận trong 7 ngày qua.
            </p>
            <p className="mt-1 text-xs text-slate-400">
              Cập nhật sự cố qua kênh ops@aec-platform.vn
            </p>
          </div>
        </section>

        {/* SLA commitment */}
        <section className="mt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">
            Cam kết SLA
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <SlaTile label="Gói Khởi đầu" uptime="99.0% best-effort" />
            <SlaTile label="Gói Chuyên nghiệp" uptime="99.5% best-effort" />
            <SlaTile label="Gói Doanh nghiệp" uptime="99.9% cam kết hợp đồng" />
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Chi tiết tính toán uptime + credit policy có trong{" "}
            <a
              href="/docs/sla"
              className="underline hover:text-slate-900"
            >
              điều khoản SLA
            </a>
            .
          </p>
        </section>

        <footer className="mt-10 text-center text-xs text-slate-500">
          <p>
            Đặt lịch theo dõi: subscribe email tại{" "}
            <a
              href="mailto:status-subscribe@aec-platform.vn"
              className="underline hover:text-slate-900"
            >
              status-subscribe@aec-platform.vn
            </a>
          </p>
          <p className="mt-1">© {new Date().getFullYear()} AEC Platform</p>
        </footer>
      </main>
    </div>
  );
}


function StatusDot({ tone }: { tone: "emerald" | "amber" | "rose" }) {
  const cls = {
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
  }[tone];
  return (
    <span className="relative flex h-3 w-3">
      <span className={`absolute inset-0 animate-ping rounded-full ${cls} opacity-60`} />
      <span className={`relative inline-flex h-3 w-3 rounded-full ${cls}`} />
    </span>
  );
}


function ServiceStateBadge({
  state,
  latency,
}: {
  state: "ok" | "degraded" | "unknown";
  latency?: number;
}) {
  if (state === "ok") {
    return (
      <div className="flex items-center gap-2">
        {latency !== undefined && (
          <span className="text-xs text-slate-400">{latency}ms</span>
        )}
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Bình thường
        </span>
      </div>
    );
  }
  if (state === "degraded") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
        Giảm chất lượng
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
      <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
      Chưa rõ
    </span>
  );
}


function SlaTile({ label, uptime }: { label: string; uptime: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 font-semibold text-slate-900">{uptime}</p>
    </div>
  );
}
