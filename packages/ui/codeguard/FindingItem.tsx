"use client";

import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { Finding } from "./types";
import { AnswerWithCitations } from "./AnswerWithCitations";
import { CitationCard } from "./CitationCard";

interface FindingItemProps {
  finding: Finding;
}

const STATUS_STYLES = {
  FAIL: { icon: XCircle, bg: "bg-red-50", border: "border-red-200", text: "text-red-800" },
  WARN: { icon: AlertTriangle, bg: "bg-amber-50", border: "border-amber-200", text: "text-amber-800" },
  PASS: { icon: CheckCircle2, bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-800" },
} as const;

const SEVERITY_STYLES = {
  critical: "bg-red-600 text-white",
  major: "bg-orange-500 text-white",
  minor: "bg-slate-400 text-white",
} as const;

export function FindingItem({ finding }: FindingItemProps): JSX.Element {
  const style = STATUS_STYLES[finding.status];
  const Icon = style.icon;

  return (
    <div className={`rounded-lg border p-4 ${style.bg} ${style.border}`}>
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 shrink-0 ${style.text}`} size={20} />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className={`font-semibold ${style.text}`}>{finding.title}</h3>
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[finding.severity]}`}
            >
              {finding.severity.toUpperCase()}
            </span>
            <span className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-600">
              {finding.category}
            </span>
          </div>
          {/*
            Inline `[N]` markers in the description hover-expand to show
            the cited chunk. Each finding has at most one citation, so
            `[1]` always points to it — the LLM is prompted to use that
            single marker (see `_SCAN_SYSTEM` in
            `apps/ml/pipelines/codeguard.py`). When `finding.citation`
            is null (e.g. some PASS findings), `<AnswerWithCitations>`
            renders any `[1]` text literally — same out-of-range fallback
            it uses on the query path.
          */}
          <AnswerWithCitations
            text={finding.description}
            citations={finding.citation ? [finding.citation] : []}
            className="mt-2 text-sm text-slate-700"
          />

          {finding.resolution && (
            <div className="mt-3 rounded bg-white/60 p-3 text-sm">
              <div className="mb-1 font-medium text-slate-900">Khuyến nghị</div>
              <p className="text-slate-700">{finding.resolution}</p>
            </div>
          )}
          {finding.citation && (
            <div className="mt-3">
              <CitationCard citation={finding.citation} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
