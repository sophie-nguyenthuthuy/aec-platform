"use client";

import Link from "next/link";
import { CheckCircle2, HardHat, ShieldAlert, UserRound, XCircle } from "lucide-react";
import { EMPLOYMENT_TYPE_LABEL, WORKER_STATUS_LABEL } from "./types";
import type { WorkerStatus, WorkerSummary } from "./types";

interface WorkerCardProps {
  worker: WorkerSummary;
  href?: string;
}

const STATUS_STYLES: Record<WorkerStatus, string> = {
  active: "bg-emerald-100 text-emerald-800",
  inactive: "bg-amber-100 text-amber-800",
  terminated: "bg-slate-200 text-slate-600",
};

export function WorkerCard({ worker, href }: WorkerCardProps): JSX.Element {
  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <UserRound className="mt-0.5 text-blue-600" size={20} />
          <div className="min-w-0">
            <h3 className="font-semibold text-slate-900">{worker.full_name}</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              {worker.trade} · {EMPLOYMENT_TYPE_LABEL[worker.employment_type]} ·{" "}
              {worker.nationality}
            </p>
            {worker.id_no && (
              <p className="mt-0.5 font-mono text-xs text-slate-500">
                ID: {worker.id_no}
              </p>
            )}
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[worker.status]}`}
        >
          {WORKER_STATUS_LABEL[worker.status]}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs">
        <ComplianceChip
          label="ATLĐ"
          ok={worker.has_valid_safety_training}
        />
        <ComplianceChip
          label="BHXH"
          ok={worker.has_active_insurance}
        />
        {worker.employment_type === "foreign" && (
          <ComplianceChip
            label="WP"
            ok={worker.has_active_permit}
          />
        )}
        <div className="flex items-center gap-1.5 text-slate-600">
          <HardHat size={14} className="text-slate-500" />
          <span>
            <span className="font-semibold text-slate-900">
              {worker.active_assignment_count}
            </span>{" "}
            dự án
          </span>
        </div>
      </div>
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return href ? <Link href={href as any}>{body}</Link> : body;
}

function ComplianceChip({ label, ok }: { label: string; ok: boolean }): JSX.Element {
  const Icon = ok ? CheckCircle2 : ok === false ? XCircle : ShieldAlert;
  return (
    <div
      className={`flex items-center gap-1 ${ok ? "text-emerald-700" : "text-rose-600"}`}
    >
      <Icon size={14} />
      <span className="font-medium">{label}</span>
    </div>
  );
}
