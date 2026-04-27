"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Bell,
  BellOff,
  CalendarRange,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  FileSignature,
  FileText,
  HardHat,
  ListChecks,
  Notebook,
  Replace,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import type { ReactNode } from "react";

import { useIsWatching, useToggleWatch } from "@/hooks/notifications";
import { useProject } from "@/hooks/projects";
import type { ProjectDetail } from "@aec/types/projects";

import { AskAiPanel } from "./AskAiPanel";

const STATUS_BADGE: Record<string, string> = {
  planning: "bg-slate-100 text-slate-700",
  design: "bg-indigo-100 text-indigo-700",
  bidding: "bg-amber-100 text-amber-700",
  construction: "bg-blue-100 text-blue-700",
  handover: "bg-purple-100 text-purple-700",
  completed: "bg-emerald-100 text-emerald-700",
  on_hold: "bg-yellow-100 text-yellow-700",
  cancelled: "bg-red-100 text-red-700",
};

function formatVnd(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B ₫`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(0)}M ₫`;
  return `${n.toLocaleString("vi-VN")} ₫`;
}

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("vi-VN");
}

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data, isLoading, isError } = useProject(id);

  if (isLoading) {
    return <p className="text-sm text-slate-500">Đang tải...</p>;
  }
  if (isError || !data) {
    return (
      <div className="space-y-3">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
        >
          <ArrowLeft size={14} /> Quay lại danh sách
        </Link>
        <p className="text-sm text-red-600">Không tìm thấy dự án này.</p>
      </div>
    );
  }

  const project: ProjectDetail = data;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/projects"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Quay lại danh sách dự án
        </Link>
        <div className="mt-2 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">{project.name}</h2>
            <p className="mt-1 text-sm text-slate-600">
              {project.type ?? "—"} ·{" "}
              {[
                project.address?.street,
                project.address?.district,
                project.address?.city,
              ]
                .filter(Boolean)
                .join(", ") || "Chưa có địa chỉ"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <WatchToggle projectId={project.id} />
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                STATUS_BADGE[project.status] ?? "bg-slate-100 text-slate-700"
              }`}
            >
              {project.status}
            </span>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Ngân sách" value={formatVnd(project.budget_vnd)} />
        <Stat label="Diện tích" value={project.area_sqm ? `${project.area_sqm.toLocaleString("vi-VN")} m²` : "—"} />
        <Stat label="Số tầng" value={project.floors?.toString() ?? "—"} />
        <Stat
          label="Thời gian"
          value={`${formatDate(project.start_date)} → ${formatDate(project.end_date)}`}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <ModuleCard
          title="WinWork"
          icon={<Wallet size={16} />}
          href="/winwork"
          tone="rose"
          rows={[
            ["Đề xuất", project.winwork.proposal_status ?? "—"],
            ["Phí dự kiến", formatVnd(project.winwork.total_fee_vnd ?? null)],
          ]}
        />
        <ModuleCard
          title="CostPulse"
          icon={<Wallet size={16} />}
          href="/costpulse"
          tone="amber"
          rows={[
            ["Số phương án", project.costpulse.estimate_count.toString()],
            ["Đã duyệt", project.costpulse.approved_count.toString()],
            ["Tổng giá mới nhất", formatVnd(project.costpulse.latest_total_vnd ?? null)],
          ]}
        />
        <ModuleCard
          title="Pulse"
          icon={<ListChecks size={16} />}
          href={`/pulse/${project.id}`}
          tone="blue"
          rows={[
            ["Tasks (todo / WIP / done)",
              `${project.pulse.tasks_todo} / ${project.pulse.tasks_in_progress} / ${project.pulse.tasks_done}`,
            ],
            ["CO mở", project.pulse.open_change_orders.toString()],
            ["Mốc trong 30 ngày", project.pulse.upcoming_milestones.toString()],
          ]}
        />
        <ModuleCard
          title="Drawbridge"
          icon={<FileText size={16} />}
          href="/drawbridge"
          tone="indigo"
          rows={[
            ["Tài liệu", project.drawbridge.document_count.toString()],
            ["RFI mở", project.drawbridge.open_rfi_count.toString()],
            ["Xung đột chưa giải", project.drawbridge.unresolved_conflict_count.toString()],
          ]}
        />
        <ModuleCard
          title="Handover"
          icon={<ClipboardList size={16} />}
          href="/handover"
          tone="purple"
          rows={[
            ["Số gói", project.handover.package_count.toString()],
            ["Defect mở", project.handover.open_defect_count.toString()],
            [
              "Bảo hành (active / sắp hết)",
              `${project.handover.warranty_active_count} / ${project.handover.warranty_expiring_count}`,
            ],
          ]}
        />
        <ModuleCard
          title="SiteEye"
          icon={<HardHat size={16} />}
          href="/siteeye"
          tone="orange"
          rows={[
            ["Lượt khảo sát", project.siteeye.visit_count.toString()],
            ["Sự cố mở", project.siteeye.open_safety_incident_count.toString()],
          ]}
        />
        <ModuleCard
          title="CodeGuard"
          icon={<ShieldCheck size={16} />}
          href="/codeguard"
          tone="emerald"
          rows={[
            ["Compliance check", project.codeguard.compliance_check_count.toString()],
            ["Permit checklist", project.codeguard.permit_checklist_count.toString()],
          ]}
        />
        <ModuleCard
          title="SchedulePilot"
          icon={<CalendarRange size={16} />}
          href="/schedule"
          tone="indigo"
          rows={[
            ["Lịch / hoạt động",
              `${project.schedulepilot.schedule_count} / ${project.schedulepilot.activity_count}`,
            ],
            ["Trễ tiến độ", project.schedulepilot.behind_schedule_count.toString()],
            ["Trên CPM", project.schedulepilot.on_critical_path_count.toString()],
            [
              "Trễ dự kiến",
              project.schedulepilot.overall_slip_days > 0
                ? `+${project.schedulepilot.overall_slip_days} ngày`
                : "Đúng tiến độ",
            ],
          ]}
        />
        <ModuleCard
          title="Submittals"
          icon={<ClipboardCheck size={16} />}
          href="/submittals"
          tone="purple"
          rows={[
            ["Đang mở", project.submittals.open_count.toString()],
            ["Sửa & nộp lại", project.submittals.revise_resubmit_count.toString()],
            ["Đã duyệt", project.submittals.approved_count.toString()],
            [
              "Bóng (TK / NT)",
              `${project.submittals.designer_court_count} / ${project.submittals.contractor_court_count}`,
            ],
          ]}
        />
        <ModuleCard
          title="Nhật ký công trường"
          icon={<Notebook size={16} />}
          href="/dailylog"
          tone="blue"
          rows={[
            ["Số nhật ký", project.dailylog.log_count.toString()],
            ["Vấn đề mở", project.dailylog.open_observation_count.toString()],
            [
              "Nghiêm trọng",
              project.dailylog.high_severity_observation_count.toString(),
            ],
            [
              "Nhật ký gần nhất",
              project.dailylog.last_log_date
                ? new Date(project.dailylog.last_log_date).toLocaleDateString("vi-VN")
                : "—",
            ],
          ]}
        />
        <ModuleCard
          title="Change orders"
          icon={<Replace size={16} />}
          href="/changeorder"
          tone="amber"
          rows={[
            [
              "Tổng / mở / duyệt",
              `${project.changeorder.total_count} / ${project.changeorder.open_count} / ${project.changeorder.approved_count}`,
            ],
            ["Đề xuất AI chờ", project.changeorder.pending_candidates.toString()],
            [
              "Tổng chi phí",
              project.changeorder.total_cost_impact_vnd > 0
                ? new Intl.NumberFormat("vi-VN", {
                    notation: "compact",
                    maximumFractionDigits: 1,
                  }).format(project.changeorder.total_cost_impact_vnd) + " ₫"
                : "—",
            ],
            [
              "Tổng trễ",
              project.changeorder.total_schedule_impact_days > 0
                ? `${project.changeorder.total_schedule_impact_days} ngày`
                : "—",
            ],
          ]}
        />
        <ModuleCard
          title="Punch list"
          icon={<FileSignature size={16} />}
          href="/punchlist"
          tone="rose"
          rows={[
            [
              "Lists (mở / đã ký)",
              `${project.punchlist.open_list_count} / ${project.punchlist.signed_off_list_count}`,
            ],
            [
              "Items (mở / đã xác minh)",
              `${project.punchlist.open_items} / ${project.punchlist.verified_items}`,
            ],
            [
              "Mức độ cao chưa xử lý",
              project.punchlist.high_severity_open_items.toString(),
            ],
          ]}
        />
        <RiskCard project={project} />
      </div>

      {/* Floating Ask-AI button + slide-over panel. Self-contained
          (manages its own open state + chat history); zero extra
          plumbing on this page. */}
      <AskAiPanel projectId={project.id} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

const TONE_CLASSES: Record<string, string> = {
  rose: "border-rose-200 bg-rose-50/50 text-rose-700",
  amber: "border-amber-200 bg-amber-50/50 text-amber-700",
  blue: "border-blue-200 bg-blue-50/50 text-blue-700",
  indigo: "border-indigo-200 bg-indigo-50/50 text-indigo-700",
  purple: "border-purple-200 bg-purple-50/50 text-purple-700",
  orange: "border-orange-200 bg-orange-50/50 text-orange-700",
  emerald: "border-emerald-200 bg-emerald-50/50 text-emerald-700",
  slate: "border-slate-200 bg-slate-50/50 text-slate-700",
};

function ModuleCard({
  title,
  icon,
  href,
  tone,
  rows,
}: {
  title: string;
  icon: ReactNode;
  href: string;
  tone: keyof typeof TONE_CLASSES;
  rows: Array<[string, string]>;
}) {
  return (
    <Link
      href={href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:shadow-sm"
    >
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`inline-flex h-7 w-7 items-center justify-center rounded ${TONE_CLASSES[tone]}`}
        >
          {icon}
        </span>
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      </div>
      <dl className="space-y-1.5 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3">
            <dt className="text-slate-500">{k}</dt>
            <dd className="text-right font-medium text-slate-800">{v}</dd>
          </div>
        ))}
      </dl>
    </Link>
  );
}

/** Aggregated cross-module risks at a glance — no API call, derived client-side. */
function RiskCard({ project }: { project: ProjectDetail }) {
  const risks: Array<{ icon: ReactNode; label: string }> = [];
  if (project.handover.open_defect_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-red-600" />,
      label: `${project.handover.open_defect_count} defect chưa xử lý`,
    });
  }
  if (project.siteeye.open_safety_incident_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-red-600" />,
      label: `${project.siteeye.open_safety_incident_count} sự cố an toàn mở`,
    });
  }
  if (project.drawbridge.unresolved_conflict_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-amber-600" />,
      label: `${project.drawbridge.unresolved_conflict_count} xung đột bản vẽ`,
    });
  }
  if (project.handover.warranty_expiring_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-amber-600" />,
      label: `${project.handover.warranty_expiring_count} bảo hành sắp hết hạn`,
    });
  }
  if (project.pulse.open_change_orders > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-amber-600" />,
      label: `${project.pulse.open_change_orders} change order mở`,
    });
  }
  if (project.schedulepilot.overall_slip_days > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-red-600" />,
      label: `Tiến độ trễ +${project.schedulepilot.overall_slip_days} ngày trên CPM`,
    });
  }
  if (project.dailylog.high_severity_observation_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-red-600" />,
      label: `${project.dailylog.high_severity_observation_count} vấn đề công trường nghiêm trọng`,
    });
  }
  if (project.submittals.revise_resubmit_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-amber-600" />,
      label: `${project.submittals.revise_resubmit_count} submittal cần sửa & nộp lại`,
    });
  }
  if (project.changeorder.pending_candidates > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-amber-600" />,
      label: `${project.changeorder.pending_candidates} đề xuất CO từ AI chờ duyệt`,
    });
  }
  if (project.punchlist.high_severity_open_items > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-red-600" />,
      label: `${project.punchlist.high_severity_open_items} punch item nghiêm trọng chưa xử lý`,
    });
  }
  if (project.punchlist.open_list_count > 0 && project.handover.package_count > 0) {
    risks.push({
      icon: <AlertTriangle size={14} className="text-amber-600" />,
      label: `${project.punchlist.open_list_count} punch list chưa ký — chặn bàn giao`,
    });
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded border-rose-200 bg-rose-50/50 text-rose-700">
          <AlertTriangle size={16} />
        </span>
        <h3 className="text-sm font-semibold text-slate-900">Rủi ro nổi bật</h3>
      </div>
      {risks.length === 0 ? (
        <div className="flex items-center gap-2 text-xs text-emerald-700">
          <CheckCircle2 size={14} /> Không có rủi ro nổi bật
        </div>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {risks.map((r, i) => (
            <li key={i} className="flex items-center gap-2 text-slate-700">
              {r.icon}
              <span>{r.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function WatchToggle({ projectId }: { projectId: string }) {
  const watching = useIsWatching(projectId);
  const { watch, unwatch } = useToggleWatch(projectId);
  const pending = watch.isPending || unwatch.isPending;

  const handleClick = () => {
    if (pending) return;
    if (watching) {
      unwatch.mutate();
    } else {
      watch.mutate();
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={pending}
      title={
        watching
          ? "Đang theo dõi — bấm để bỏ theo dõi"
          : "Bấm để theo dõi và nhận digest hằng ngày"
      }
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition disabled:opacity-50 ${
        watching
          ? "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"
          : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
      }`}
    >
      {watching ? <Bell size={12} /> : <BellOff size={12} />}
      <span>{watching ? "Đang theo dõi" : "Theo dõi"}</span>
    </button>
  );
}
