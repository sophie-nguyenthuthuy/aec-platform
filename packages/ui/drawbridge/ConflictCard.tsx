"use client";

import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

import type { ConflictSeverity, ConflictStatus, ConflictWithExcerpts } from "./types";
import { DisciplineTag } from "./DisciplineTag";
import { cn } from "../lib/cn";

interface ConflictCardProps {
  conflict: ConflictWithExcerpts;
  onResolve?(conflict: ConflictWithExcerpts): void;
  onDismiss?(conflict: ConflictWithExcerpts): void;
  onOpen?(conflict: ConflictWithExcerpts): void;
  onGenerateRfi?(conflict: ConflictWithExcerpts): void;
}

const SEVERITY_STYLE: Record<ConflictSeverity, { icon: typeof AlertTriangle; tone: string; label: string }> = {
  critical: { icon: XCircle, tone: "text-red-600 bg-red-50 border-red-200", label: "Nghiêm trọng" },
  major: { icon: AlertTriangle, tone: "text-amber-700 bg-amber-50 border-amber-200", label: "Lớn" },
  minor: { icon: AlertTriangle, tone: "text-slate-700 bg-slate-50 border-slate-200", label: "Nhỏ" },
};

const STATUS_BADGE: Record<ConflictStatus, string> = {
  open: "bg-blue-100 text-blue-800",
  resolved: "bg-emerald-100 text-emerald-800",
  dismissed: "bg-slate-100 text-slate-600",
};

export function ConflictCard({
  conflict,
  onResolve,
  onDismiss,
  onOpen,
  onGenerateRfi,
}: ConflictCardProps): JSX.Element {
  const sev = conflict.severity ? SEVERITY_STYLE[conflict.severity] : SEVERITY_STYLE.minor;
  const Icon = sev.icon;

  return (
    <article className={cn("rounded-xl border bg-white p-4 shadow-sm", sev.tone.split(" ").slice(2).join(" "))}>
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Icon size={20} className={sev.tone.split(" ")[0]} />
          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
              <span className={cn("rounded-full px-2 py-0.5 font-medium", STATUS_BADGE[conflict.status])}>
                {conflict.status}
              </span>
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 font-medium",
                  sev.tone,
                )}
              >
                {sev.label}
              </span>
              {conflict.conflict_type && (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">
                  {conflict.conflict_type}
                </span>
              )}
            </div>
            <h3 className="text-sm font-semibold text-slate-900">
              {conflict.description ?? "Xung đột giữa bản vẽ"}
            </h3>
          </div>
        </div>
        <div className="text-xs text-slate-500">
          {new Date(conflict.detected_at).toLocaleDateString()}
        </div>
      </header>

      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <ExcerptPanel side="A" excerpt={conflict.document_a} />
        <ExcerptPanel side="B" excerpt={conflict.document_b} />
      </div>

      {conflict.ai_explanation && (
        <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
          <span className="mr-1 font-semibold text-slate-900">AI:</span>
          {conflict.ai_explanation}
        </p>
      )}

      <footer className="mt-4 flex flex-wrap gap-2">
        {onOpen && (
          <button
            type="button"
            onClick={() => onOpen(conflict)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Chi tiết
          </button>
        )}
        {conflict.status === "open" && onGenerateRfi && (
          <button
            type="button"
            onClick={() => onGenerateRfi(conflict)}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
          >
            Tạo RFI
          </button>
        )}
        {conflict.status === "open" && onResolve && (
          <button
            type="button"
            onClick={() => onResolve(conflict)}
            className="inline-flex items-center gap-1 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
          >
            <CheckCircle2 size={12} /> Đã xử lý
          </button>
        )}
        {conflict.status === "open" && onDismiss && (
          <button
            type="button"
            onClick={() => onDismiss(conflict)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            Bỏ qua
          </button>
        )}
      </footer>
    </article>
  );
}

function ExcerptPanel({
  side,
  excerpt,
}: {
  side: "A" | "B";
  excerpt: ConflictWithExcerpts["document_a"];
}): JSX.Element {
  if (!excerpt) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 p-3 text-xs text-slate-400">
        Bản vẽ {side} — không khả dụng
      </div>
    );
  }
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-1 flex items-center gap-2 text-xs text-slate-600">
        <span className="font-semibold text-slate-900">{side}</span>
        <DisciplineTag discipline={excerpt.discipline} size="sm" />
        {excerpt.drawing_number && <span className="font-mono">{excerpt.drawing_number}</span>}
        {excerpt.page != null && <span className="text-slate-400">p.{excerpt.page}</span>}
      </div>
      <blockquote className="border-l-2 border-slate-300 pl-2 text-xs italic text-slate-700">
        {excerpt.excerpt}
      </blockquote>
    </div>
  );
}
