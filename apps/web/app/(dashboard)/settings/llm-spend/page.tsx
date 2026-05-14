"use client";

import { useEffect, useState } from "react";
import { Activity, Cpu, DollarSign, Loader2, Sparkles } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


type Period = "current_month" | "last_month" | "last_30_days";

interface BreakdownRow {
  module: string;
  provider: string;
  cost_vnd: number;
  input_tokens: number;
  output_tokens: number;
  call_count: number;
}

interface SeriesPoint {
  day: string;
  cost_vnd: number;
}

interface SpendPayload {
  period: Period;
  since: string;
  until: string;
  totals: {
    cost_vnd: number;
    input_tokens: number;
    output_tokens: number;
    call_count: number;
  };
  breakdown: BreakdownRow[];
  daily_series: SeriesPoint[];
}


const PERIOD_OPTIONS: Array<{ value: Period; label: string }> = [
  { value: "current_month", label: "Tháng này" },
  { value: "last_month", label: "Tháng trước" },
  { value: "last_30_days", label: "30 ngày gần nhất" },
];

const MODULE_LABELS: Record<string, string> = {
  codeguard: "CodeGuard — đối chiếu QCVN",
  drawbridge: "Drawbridge — Q&A bản vẽ",
  winwork: "WinWork — đề xuất",
  costpulse: "CostPulse — RFQ + dự toán",
  bidradar: "BidRadar — săn gói thầu",
  pulse: "Pulse — báo cáo tuần",
  siteeye: "SiteEye — phân tích ảnh",
  other: "Khác",
};

const PROVIDER_LABELS: Record<string, string> = {
  gemini: "Google Gemini",
  anthropic: "Anthropic Claude",
  openai: "OpenAI",
};


export default function LlmSpendPage() {
  const { token, orgId } = useSession();
  const [period, setPeriod] = useState<Period>("current_month");
  const [data, setData] = useState<SpendPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await apiFetch<SpendPayload>(
          `/api/v1/billing/llm-spend?period=${period}`,
          { token, orgId },
        );
        if (!cancelled) setData(res.data!);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, orgId, period]);

  // Pre-compute the per-module aggregate (sum across providers) so the
  // breakdown table can show "Drawbridge: 850k đ — 65% Gemini / 35% Claude".
  const moduleSummary = aggregateByModule(data?.breakdown ?? []);
  const peakDay = (data?.daily_series ?? []).reduce(
    (max, p) => (p.cost_vnd > max ? p.cost_vnd : max),
    0,
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Chi phí AI</h2>
        <p className="text-sm text-slate-600">
          Theo dõi chi phí sử dụng Gemini / Claude / OpenAI cho toàn bộ
          module. Số liệu cập nhật theo từng lệnh gọi LLM — không phụ
          thuộc gói cước.
        </p>
      </div>

      {/* Period toggle */}
      <div className="flex flex-wrap gap-1.5">
        {PERIOD_OPTIONS.map((p) => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              period === p.value
                ? "bg-blue-600 text-white"
                : "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {error && (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {error}
        </p>
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải…
        </p>
      ) : data ? (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <KpiTile
              icon={<DollarSign size={14} />}
              label="Tổng chi phí"
              value={formatVnd(data.totals.cost_vnd)}
            />
            <KpiTile
              icon={<Activity size={14} />}
              label="Số lượt gọi"
              value={data.totals.call_count.toLocaleString("vi-VN")}
            />
            <KpiTile
              icon={<Cpu size={14} />}
              label="Token input"
              value={formatTokens(data.totals.input_tokens)}
            />
            <KpiTile
              icon={<Sparkles size={14} />}
              label="Token output"
              value={formatTokens(data.totals.output_tokens)}
            />
          </div>

          {/* Daily series — simple bar chart */}
          {data.daily_series.length > 0 && (
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-900">
                Chi phí theo ngày
              </h3>
              <div className="mt-4 flex h-32 items-end gap-1">
                {data.daily_series.map((p) => (
                  <div
                    key={p.day}
                    className="group flex-1 min-w-0 relative flex flex-col items-center"
                    title={`${formatVnDate(p.day)}: ${formatVnd(p.cost_vnd)}`}
                  >
                    <div
                      className="w-full bg-blue-500 hover:bg-blue-600 rounded-t"
                      style={{
                        height: `${peakDay > 0 ? (p.cost_vnd / peakDay) * 100 : 0}%`,
                        minHeight: p.cost_vnd > 0 ? "2px" : "0",
                      }}
                    />
                  </div>
                ))}
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-slate-400">
                <span>{formatVnDate(data.since)}</span>
                <span>{formatVnDate(data.until)}</span>
              </div>
            </section>
          )}

          {/* Per-module breakdown */}
          <section className="rounded-xl border border-slate-200 bg-white">
            <header className="border-b border-slate-200 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Phân loại theo module
              </h3>
            </header>
            {moduleSummary.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-slate-500">
                Chưa có lượt gọi AI nào trong khoảng thời gian này.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {moduleSummary.map((m) => {
                  const pct =
                    data.totals.cost_vnd > 0
                      ? (m.cost_vnd / data.totals.cost_vnd) * 100
                      : 0;
                  return (
                    <li key={m.module} className="px-4 py-3">
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="text-sm font-medium text-slate-900">
                          {MODULE_LABELS[m.module] || m.module}
                        </p>
                        <p className="text-sm font-semibold text-slate-900">
                          {formatVnd(m.cost_vnd)}
                        </p>
                      </div>
                      <div className="mt-1.5 h-1.5 w-full rounded-full bg-slate-100">
                        <div
                          className="h-1.5 rounded-full bg-blue-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                        <span>{pct.toFixed(1)}% tổng</span>
                        <span>·</span>
                        <span>{m.call_count} lượt gọi</span>
                        <span>·</span>
                        <span>{formatTokens(m.input_tokens + m.output_tokens)} token</span>
                        {m.providers.length > 1 && (
                          <>
                            <span>·</span>
                            <span>
                              {m.providers
                                .map(
                                  (p) =>
                                    `${PROVIDER_LABELS[p.provider] || p.provider}: ${formatVnd(p.cost_vnd)}`,
                                )
                                .join(" / ")}
                            </span>
                          </>
                        )}
                      </div>
                    </li>
                  );
                })}
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
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        <span>{label}</span>
      </div>
      <p className="mt-1 text-xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}


function aggregateByModule(rows: BreakdownRow[]) {
  const map = new Map<
    string,
    {
      module: string;
      cost_vnd: number;
      input_tokens: number;
      output_tokens: number;
      call_count: number;
      providers: { provider: string; cost_vnd: number }[];
    }
  >();
  for (const r of rows) {
    const cur = map.get(r.module) || {
      module: r.module,
      cost_vnd: 0,
      input_tokens: 0,
      output_tokens: 0,
      call_count: 0,
      providers: [],
    };
    cur.cost_vnd += r.cost_vnd;
    cur.input_tokens += r.input_tokens;
    cur.output_tokens += r.output_tokens;
    cur.call_count += r.call_count;
    cur.providers.push({ provider: r.provider, cost_vnd: r.cost_vnd });
    map.set(r.module, cur);
  }
  return Array.from(map.values()).sort((a, b) => b.cost_vnd - a.cost_vnd);
}


function formatVnd(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}


function formatTokens(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}


function formatVnDate(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}/${String(
    d.getMonth() + 1,
  ).padStart(2, "0")}`;
}
