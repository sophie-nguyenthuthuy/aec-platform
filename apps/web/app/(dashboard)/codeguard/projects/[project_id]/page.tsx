"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Loader2,
  RefreshCcw,
  XCircle,
} from "lucide-react";

import { FindingItem } from "@aec/ui/codeguard";
import type { Finding } from "@aec/ui/codeguard";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Per-project CodeGuard dashboard.
 *
 * Surfaces every scan that's been run for one specific project so a PM
 * can answer "what's the compliance state of project X right now?"
 * without re-running a scan or scrolling the global history.
 *
 * Layout (top-to-bottom):
 *   1. Header — back link, project ID, "Quét lại" CTA.
 *   2. Trend chart — latest 10 scans, status counters as stacked bars.
 *      Pure CSS, no chart library.
 *   3. Latest scan card — pass/warn/fail counts, generated_at, findings.
 *   4. Prior scans — collapsible list, click to swap into the detail view.
 *
 * Data: GET /api/v1/codeguard/checks/{project_id} returns the list with
 * findings inlined; no second fetch needed.
 */

interface ComplianceCheck {
  id: string;
  project_id: string | null;
  check_type: string;
  status: "completed" | "failed" | "pending" | string;
  findings: Finding[] | null;
  regulations_referenced: string[];
  input: Record<string, unknown> | null;
  created_at?: string;
}


export default function CodeguardProjectDashboard() {
  const { token, orgId } = useSession();
  const params = useParams<{ project_id: string }>();
  const projectId = params?.project_id;

  const [checks, setChecks] = useState<ComplianceCheck[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCheckId, setActiveCheckId] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !orgId || !projectId) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const res = await apiFetch<ComplianceCheck[]>(
          `/api/v1/codeguard/checks/${projectId}?limit=50`,
          { token, orgId },
        );
        if (cancelled) return;
        const items = res.data ?? [];
        setChecks(items);
        const first = items[0];
        if (first) setActiveCheckId(first.id);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, orgId, projectId]);

  const activeCheck = useMemo(
    () => (checks ?? []).find((c) => c.id === activeCheckId) ?? null,
    [checks, activeCheckId],
  );

  // Derive trend: last 10 scans, ordered oldest → newest, with counts.
  const trend = useMemo(() => {
    if (!checks) return [];
    return [...checks]
      .slice(0, 10)
      .reverse()
      .map((c) => {
        const findings = c.findings ?? [];
        return {
          id: c.id,
          created_at: c.created_at,
          pass: findings.filter((f) => f.status === "PASS").length,
          warn: findings.filter((f) => f.status === "WARN").length,
          fail: findings.filter((f) => f.status === "FAIL").length,
        };
      });
  }, [checks]);

  const peak = useMemo(
    () =>
      Math.max(
        1,
        ...trend.map((t) => t.pass + t.warn + t.fail),
      ),
    [trend],
  );

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/codeguard"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Tất cả CodeGuard
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              CodeGuard — Dự án
            </h2>
            <p className="font-mono text-xs text-slate-500">{projectId}</p>
          </div>
          <Link
            href={`/codeguard/scan?project_id=${projectId}` as never}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            <RefreshCcw size={14} />
            Quét lại
          </Link>
        </div>
      </div>

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải dữ liệu…
        </p>
      ) : error ? (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {error}
        </div>
      ) : !checks || checks.length === 0 ? (
        <EmptyState projectId={projectId ?? ""} />
      ) : (
        <>
          {/* Trend chart */}
          {trend.length > 1 && (
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-900">
                Xu hướng tuân thủ ({trend.length} lượt quét gần nhất)
              </h3>
              <div className="mt-4 flex h-40 items-end gap-2">
                {trend.map((t) => {
                  const total = t.pass + t.warn + t.fail;
                  const h = (total / peak) * 100;
                  return (
                    <button
                      key={t.id}
                      onClick={() => setActiveCheckId(t.id)}
                      className={`group relative flex-1 min-w-0 flex flex-col justify-end ${
                        activeCheckId === t.id ? "opacity-100" : "opacity-80 hover:opacity-100"
                      }`}
                      title={`${t.pass} pass · ${t.warn} warn · ${t.fail} fail`}
                    >
                      <div
                        className="w-full overflow-hidden rounded-t"
                        style={{ height: `${h}%`, minHeight: "4px" }}
                      >
                        {/* Stacked fail/warn/pass from bottom to top */}
                        <div className="flex h-full flex-col">
                          <Stack value={t.fail} total={total} color="#e11d48" />
                          <Stack value={t.warn} total={total} color="#f59e0b" />
                          <Stack value={t.pass} total={total} color="#10b981" />
                        </div>
                      </div>
                      <span
                        className={`mt-1 truncate text-[9px] ${
                          activeCheckId === t.id ? "font-semibold text-slate-900" : "text-slate-400"
                        }`}
                      >
                        {t.created_at ? formatVnDate(t.created_at) : "—"}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="mt-2 flex gap-3 text-[11px] text-slate-500">
                <LegendDot color="#10b981" label="Đạt" />
                <LegendDot color="#f59e0b" label="Cảnh báo" />
                <LegendDot color="#e11d48" label="Không đạt" />
              </div>
            </section>
          )}

          {/* Active check detail */}
          {activeCheck && (
            <CheckDetailCard check={activeCheck} />
          )}

          {/* Prior scans */}
          <section className="rounded-xl border border-slate-200 bg-white">
            <header className="border-b border-slate-200 px-4 py-2.5">
              <h3 className="text-sm font-semibold text-slate-900">
                Tất cả lượt quét ({checks.length})
              </h3>
            </header>
            <ul className="divide-y divide-slate-100">
              {checks.map((c) => {
                const findings = c.findings ?? [];
                const fail = findings.filter((f) => f.status === "FAIL").length;
                const warn = findings.filter((f) => f.status === "WARN").length;
                const isActive = c.id === activeCheckId;
                return (
                  <li key={c.id}>
                    <button
                      onClick={() => setActiveCheckId(c.id)}
                      className={`flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm ${
                        isActive ? "bg-blue-50/50" : "hover:bg-slate-50"
                      }`}
                    >
                      <ClipboardCheck
                        size={14}
                        className={isActive ? "text-blue-600" : "text-slate-400"}
                      />
                      <div className="flex-1 min-w-0">
                        <p
                          className={`font-medium ${
                            isActive ? "text-blue-900" : "text-slate-900"
                          }`}
                        >
                          {c.check_type === "scan" ? "Quét tuân thủ" : c.check_type}
                        </p>
                        <p className="text-[11px] text-slate-500">
                          <Clock size={10} className="mr-1 inline" />
                          {c.created_at ? formatVnDateTime(c.created_at) : "—"}
                          {" · "}
                          {findings.length} hạng mục
                        </p>
                      </div>
                      <div className="flex gap-1.5">
                        {fail > 0 && (
                          <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[10px] font-semibold text-rose-700">
                            {fail} FAIL
                          </span>
                        )}
                        {warn > 0 && (
                          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
                            {warn} WARN
                          </span>
                        )}
                        {fail === 0 && warn === 0 && (
                          <CheckCircle2 size={14} className="text-emerald-500" />
                        )}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}


function Stack({
  value,
  total,
  color,
}: {
  value: number;
  total: number;
  color: string;
}) {
  if (value === 0 || total === 0) return null;
  return (
    <div
      style={{ background: color, flexGrow: value / total }}
      className="w-full"
    />
  );
}


function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}


function CheckDetailCard({ check }: { check: ComplianceCheck }) {
  const findings = check.findings ?? [];
  const fail = findings.filter((f) => f.status === "FAIL").length;
  const warn = findings.filter((f) => f.status === "WARN").length;
  const pass = findings.filter((f) => f.status === "PASS").length;

  return (
    <section className="space-y-3">
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Chi tiết lượt quét
          </h3>
          <span className="text-xs text-slate-500">
            <Clock size={10} className="mr-1 inline" />
            {check.created_at ? formatVnDateTime(check.created_at) : "—"}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-3 text-center">
          <ScoreTile
            icon={<XCircle size={14} className="text-rose-600" />}
            label="Không đạt"
            value={fail}
            tone="rose"
          />
          <ScoreTile
            icon={<AlertTriangle size={14} className="text-amber-600" />}
            label="Cảnh báo"
            value={warn}
            tone="amber"
          />
          <ScoreTile
            icon={<CheckCircle2 size={14} className="text-emerald-600" />}
            label="Đạt"
            value={pass}
            tone="emerald"
          />
        </div>
      </div>

      {findings.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">
          Lượt quét này không tạo ra hạng mục nào.
        </div>
      ) : (
        <div className="space-y-3">
          {findings.map((f, i) => (
            <FindingItem key={i} finding={f} />
          ))}
        </div>
      )}
    </section>
  );
}


function ScoreTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: "rose" | "amber" | "emerald";
}) {
  const cls = {
    rose: "bg-rose-50",
    amber: "bg-amber-50",
    emerald: "bg-emerald-50",
  }[tone];
  return (
    <div className={`rounded-md ${cls} px-2 py-2`}>
      <div className="flex items-center justify-center gap-1 text-[11px] text-slate-600">
        {icon}
        {label}
      </div>
      <p className="mt-1 text-2xl font-bold text-slate-900">{value}</p>
    </div>
  );
}


function EmptyState({ projectId }: { projectId: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
      <ClipboardCheck size={32} className="mx-auto text-slate-400" />
      <p className="mt-3 text-sm text-slate-600">
        Chưa có lượt quét tuân thủ nào cho dự án này.
      </p>
      <Link
        href={`/codeguard/scan?project_id=${projectId}` as never}
        className="mt-4 inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
      >
        Bắt đầu quét đầu tiên
      </Link>
    </div>
  );
}


function formatVnDate(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}/${String(
    d.getMonth() + 1,
  ).padStart(2, "0")}`;
}


function formatVnDateTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}/${String(
    d.getMonth() + 1,
  ).padStart(2, "0")}/${d.getFullYear()} ${String(d.getHours()).padStart(
    2,
    "0",
  )}:${String(d.getMinutes()).padStart(2, "0")}`;
}
