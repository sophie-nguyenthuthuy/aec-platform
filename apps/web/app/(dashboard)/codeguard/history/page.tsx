"use client";

/**
 * CODEGUARD compliance-check audit trail.
 *
 * Surfaces what the backend has been silently persisting since round 4:
 * every `/query` and `/scan` call writes a `ComplianceCheck` row keyed on
 * (organization_id, project_id) — see `apps/api/routers/codeguard.py`.
 * Without this page there's no UI for "what was asked, what was answered,
 * what was flagged." For a *compliance* tool that's the half of the
 * value prop the rest of the UI doesn't expose.
 *
 * Scope:
 *   - Project ID input (UUID) + check-type filter (all / query / scan).
 *   - List of cards, type-specific summary per card:
 *       * manual_query → question + answer (truncated) + citation count
 *       * auto_scan    → PASS/WARN/FAIL counts + categories scanned
 *   - Empty state distinguishes "no project entered yet" from "no checks
 *     for this project."
 *   - Loading + error states match the rest of the codeguard module.
 *
 * Click-through to a full check detail view is deliberately out of scope
 * — the summaries are dense enough to answer the audit-trail question
 * (was X asked, did it find Y) and adding a detail route doubles the
 * surface area.
 */

import { useState } from "react";
import { Info, Search } from "lucide-react";
import {
  useProjectChecks,
  type ComplianceCheck,
} from "@/hooks/codeguard";

const TYPE_FILTERS: Array<{ value: string | undefined; label: string }> = [
  { value: undefined, label: "Tất cả" },
  { value: "manual_query", label: "Hỏi quy chuẩn" },
  { value: "auto_scan", label: "Quét tuân thủ" },
];

const TYPE_BADGE: Record<string, { label: string; classes: string }> = {
  manual_query: { label: "Hỏi", classes: "bg-blue-100 text-blue-800" },
  auto_scan: { label: "Quét", classes: "bg-purple-100 text-purple-800" },
  permit_checklist: { label: "Checklist", classes: "bg-emerald-100 text-emerald-800" },
};

const STATUS_BADGE: Record<string, { label: string; classes: string }> = {
  completed: { label: "Hoàn thành", classes: "bg-slate-100 text-slate-700" },
  running: { label: "Đang chạy", classes: "bg-amber-100 text-amber-800" },
  failed: { label: "Thất bại", classes: "bg-red-100 text-red-800" },
  pending: { label: "Chờ", classes: "bg-slate-100 text-slate-600" },
};

export default function ComplianceHistoryPage() {
  const [projectId, setProjectId] = useState("");
  const [submitted, setSubmitted] = useState<string | undefined>(undefined);
  const [checkType, setCheckType] = useState<string | undefined>(undefined);

  const { data, isLoading, isError, error } = useProjectChecks(submitted, checkType);

  const onSearch = () => {
    const trimmed = projectId.trim();
    if (!trimmed) return;
    setSubmitted(trimmed);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Lịch sử kiểm tra</h2>
        <p className="text-sm text-slate-600">
          Lịch sử các lần hỏi quy chuẩn và quét tuân thủ của một dự án.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block flex-1 min-w-[260px]">
            <span className="mb-1 block text-sm font-medium text-slate-700">Mã dự án (UUID)</span>
            <input
              type="text"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSearch();
              }}
              placeholder="00000000-0000-0000-0000-000000000000"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Loại</span>
            <select
              value={checkType ?? ""}
              onChange={(e) => setCheckType(e.target.value || undefined)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {TYPE_FILTERS.map((f) => (
                <option key={f.label} value={f.value ?? ""}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={onSearch}
            disabled={!projectId.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Search size={14} />
            Tra cứu
          </button>
        </div>
      </div>

      {/* Three-state empty/loading/error/results layout, ordered from most
          specific to most general so the right state shows even when
          react-query data is stale-loading. */}
      {!submitted ? (
        <EmptyHint />
      ) : isLoading ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
          Đang tải...
        </div>
      ) : isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
          <div className="mb-1 font-medium">Lỗi khi tải lịch sử</div>
          <p>{error instanceof Error ? error.message : "Đã xảy ra lỗi"}</p>
        </div>
      ) : !data || data.length === 0 ? (
        <NoChecksAdvisory projectId={submitted} />
      ) : (
        <div className="space-y-3">
          {data.map((c) => (
            <CheckCard key={c.id} check={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyHint() {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
      Nhập mã dự án để xem lịch sử kiểm tra.
    </div>
  );
}

function NoChecksAdvisory({ projectId }: { projectId: string }) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
      <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
        <Info size={14} />
        Chưa có kiểm tra nào
      </div>
      <p>
        Dự án <code className="rounded bg-white px-1">{projectId}</code> chưa có lượt
        hỏi quy chuẩn hoặc quét tuân thủ nào trong tổ chức của bạn. Hãy thử "Hỏi quy chuẩn"
        hoặc "Quét tuân thủ" để bắt đầu.
      </p>
    </div>
  );
}

function CheckCard({ check }: { check: ComplianceCheck }) {
  const typeStyle = TYPE_BADGE[check.check_type] ?? {
    label: check.check_type,
    classes: "bg-slate-100 text-slate-700",
  };
  const statusStyle = STATUS_BADGE[check.status] ?? {
    label: check.status,
    classes: "bg-slate-100 text-slate-700",
  };

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4">
      <header className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${typeStyle.classes}`}>
          {typeStyle.label}
        </span>
        <span className={`rounded px-2 py-0.5 text-xs ${statusStyle.classes}`}>
          {statusStyle.label}
        </span>
        <time className="ml-auto text-xs text-slate-500">
          {new Date(check.created_at).toLocaleString("vi-VN")}
        </time>
      </header>

      <div className="mt-3">
        {check.check_type === "manual_query" ? (
          <QuerySummary check={check} />
        ) : check.check_type === "auto_scan" ? (
          <ScanSummary check={check} />
        ) : (
          // Defensive: surfaced if the backend ever introduces a new
          // check_type before the UI is updated. Better than rendering
          // nothing.
          <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-xs text-slate-600">
            {JSON.stringify(check.input, null, 2)}
          </pre>
        )}
      </div>

      {check.regulations_referenced.length > 0 && (
        <footer className="mt-3 text-xs text-slate-500">
          {check.regulations_referenced.length} quy chuẩn được tham chiếu
        </footer>
      )}
    </article>
  );
}

function QuerySummary({ check }: { check: ComplianceCheck }) {
  const input = (check.input ?? {}) as { question?: string };
  // The query route persists `result.model_dump(mode="json")` as
  // `findings`, so for manual_query it's a single object, not an array
  // — the typed `unknown[] | null` shape is wrong for this branch but
  // fine at runtime since we treat it as opaque here.
  const findings = (check.findings as unknown as {
    answer?: string;
    citations?: Array<unknown>;
    confidence?: number;
  } | null) ?? null;

  return (
    <div className="space-y-2 text-sm">
      {input.question && (
        <div>
          <div className="text-xs font-medium text-slate-500">Câu hỏi</div>
          <p className="text-slate-900">{input.question}</p>
        </div>
      )}
      {findings?.answer && (
        <div>
          <div className="text-xs font-medium text-slate-500">Trả lời</div>
          <p className="line-clamp-3 text-slate-700">{findings.answer}</p>
        </div>
      )}
      {findings && (
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>{findings.citations?.length ?? 0} trích dẫn</span>
          {typeof findings.confidence === "number" && (
            <span>Độ tin cậy: {Math.round(findings.confidence * 100)}%</span>
          )}
        </div>
      )}
    </div>
  );
}

function ScanSummary({ check }: { check: ComplianceCheck }) {
  // For auto_scan the backend persists `[Finding.model_dump(), ...]` as
  // findings, so the typed `unknown[]` shape is accurate here.
  const findings = (check.findings ?? []) as Array<{
    status?: string;
    category?: string;
  }>;
  const passCount = findings.filter((f) => f.status === "PASS").length;
  const warnCount = findings.filter((f) => f.status === "WARN").length;
  const failCount = findings.filter((f) => f.status === "FAIL").length;
  const categories = Array.from(
    new Set(findings.map((f) => f.category).filter((c): c is string => Boolean(c))),
  );
  const input = (check.input ?? {}) as {
    parameters?: { project_type?: string; floors_above?: number };
  };

  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-2">
        <CountChip label="Đạt" value={passCount} color="bg-emerald-100 text-emerald-800" />
        <CountChip label="Cảnh báo" value={warnCount} color="bg-amber-100 text-amber-800" />
        <CountChip label="Vi phạm" value={failCount} color="bg-red-100 text-red-800" />
      </div>
      {categories.length > 0 && (
        <div className="text-xs text-slate-500">
          Hạng mục: {categories.join(", ")}
        </div>
      )}
      {input.parameters?.project_type && (
        <div className="text-xs text-slate-500">
          Loại công trình: {input.parameters.project_type}
        </div>
      )}
    </div>
  );
}

function CountChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${color}`}>
      {label}: <strong>{value}</strong>
    </span>
  );
}
