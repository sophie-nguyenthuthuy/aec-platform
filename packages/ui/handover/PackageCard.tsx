"use client";

import Link from "next/link";
import { AlertTriangle, CheckSquare, Package, ShieldAlert } from "lucide-react";
import type { PackageStatus, PackageSummary } from "./types";

interface PackageCardProps {
  pkg: PackageSummary;
  href?: string;
}

const STATUS_LABEL: Record<PackageStatus, string> = {
  draft: "Bản nháp",
  in_review: "Đang duyệt",
  approved: "Đã duyệt",
  delivered: "Đã bàn giao",
};

const STATUS_STYLES: Record<PackageStatus, string> = {
  draft: "bg-slate-100 text-slate-700",
  in_review: "bg-amber-100 text-amber-800",
  approved: "bg-blue-100 text-blue-800",
  delivered: "bg-emerald-100 text-emerald-800",
};

export function PackageCard({ pkg, href }: PackageCardProps): JSX.Element {
  const donePct =
    pkg.closeout_total === 0
      ? 0
      : Math.round((pkg.closeout_done / pkg.closeout_total) * 100);

  const body = (
    <div className="rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-400 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Package className="mt-0.5 text-blue-600" size={20} />
          <div>
            <h3 className="font-semibold text-slate-900">{pkg.name}</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Tạo {new Date(pkg.created_at).toLocaleDateString("vi-VN")}
            </p>
          </div>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[pkg.status]}`}
        >
          {STATUS_LABEL[pkg.status]}
        </span>
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>Tiến độ hồ sơ</span>
          <span className="font-medium text-slate-900">
            {pkg.closeout_done}/{pkg.closeout_total} ({donePct}%)
          </span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full bg-blue-500 transition-all"
            style={{ width: `${donePct}%` }}
          />
        </div>
      </div>

      <div className="mt-4 flex gap-4 text-xs">
        <Stat
          icon={CheckSquare}
          label="Hạng mục"
          value={pkg.closeout_total}
          tone="slate"
        />
        <Stat
          icon={AlertTriangle}
          label="Bảo hành sắp hết"
          value={pkg.warranty_expiring}
          tone={pkg.warranty_expiring > 0 ? "amber" : "slate"}
        />
        <Stat
          icon={ShieldAlert}
          label="Lỗi mở"
          value={pkg.open_defects}
          tone={pkg.open_defects > 0 ? "red" : "slate"}
        />
      </div>
    </div>
  );

  return href ? <Link href={href}>{body}</Link> : body;
}

type StatTone = "slate" | "amber" | "red";

const TONE_STYLES: Record<StatTone, string> = {
  slate: "text-slate-500",
  amber: "text-amber-600",
  red: "text-red-600",
};

function Stat({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof CheckSquare;
  label: string;
  value: number;
  tone: StatTone;
}): JSX.Element {
  return (
    <div className="flex items-center gap-1.5">
      <Icon size={14} className={TONE_STYLES[tone]} />
      <span className="text-slate-600">{label}:</span>
      <span className={`font-semibold ${TONE_STYLES[tone]}`}>{value}</span>
    </div>
  );
}
