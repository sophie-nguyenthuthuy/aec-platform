"use client";

import Link from "next/link";
import { Leaf, ShieldCheck, Sprout } from "lucide-react";
import {
  CATEGORY_LABEL,
  CERT_SYSTEM_LABEL,
  TARGET_LEVEL_LABEL,
} from "./types";
import type { CertStatus, CertSummary } from "./types";

interface CertCardProps {
  cert: CertSummary;
  href?: string;
}

const STATUS_STYLES: Record<CertStatus, string> = {
  planning: "bg-slate-100 text-slate-700",
  self_assessment: "bg-blue-100 text-blue-800",
  submitted: "bg-indigo-100 text-indigo-800",
  provisional: "bg-amber-100 text-amber-800",
  final_cert: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-700",
  expired: "bg-slate-300 text-slate-700",
};

const STATUS_LABELS: Record<CertStatus, string> = {
  planning: "Lập kế hoạch",
  self_assessment: "Tự đánh giá",
  submitted: "Đã nộp hồ sơ",
  provisional: "Chứng nhận tạm",
  final_cert: "Chứng nhận chính thức",
  rejected: "Bị từ chối",
  expired: "Hết hiệu lực",
};

export function CertCard({ cert, href }: CertCardProps): JSX.Element {
  const earned = Number(cert.achieved_points);
  const max = Number(cert.max_points);
  const pct = max === 0 ? 0 : Math.round((earned / max) * 100);

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-emerald-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Sprout className="mt-0.5 text-emerald-600" size={20} />
          <div className="min-w-0">
            <p className="text-xs text-slate-500">
              {CERT_SYSTEM_LABEL[cert.system]} · Mục tiêu{" "}
              {TARGET_LEVEL_LABEL[cert.target_level]}
            </p>
            <h3 className="font-semibold text-slate-900">
              {earned.toFixed(1)} / {max.toFixed(1)} điểm
            </h3>
            {cert.achieved_level && (
              <p className="mt-0.5 flex items-center gap-1 text-xs text-emerald-700">
                <ShieldCheck size={12} />
                Đạt {TARGET_LEVEL_LABEL[cert.achieved_level]}
              </p>
            )}
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[cert.status]}`}
        >
          {STATUS_LABELS[cert.status]}
        </span>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>Tiến độ điểm</span>
          <span className="font-medium text-slate-900">
            {pct}% · {cert.credit_verified}/{cert.credit_total} thẩm định
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {cert.certification_no && (
        <div className="mt-4 flex items-center gap-1.5 text-xs text-slate-600">
          <Leaf size={14} className="text-emerald-500" />
          <span className="font-mono">{cert.certification_no}</span>
        </div>
      )}
    </div>
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return href ? <Link href={href as any}>{body}</Link> : body;
}

// Re-export so consumers can render category badges without re-importing.
export { CATEGORY_LABEL };
