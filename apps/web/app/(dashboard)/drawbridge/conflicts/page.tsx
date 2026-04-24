"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Play, ShieldAlert } from "lucide-react";

import {
  ConflictCard,
  type ConflictSeverity,
  type ConflictStatus,
} from "@aec/ui/drawbridge";
import { useSession } from "@/lib/auth-context";
import {
  useConflicts,
  useConflictScan,
  useGenerateRFI,
  useUpdateConflict,
} from "@/hooks/drawbridge";

const SEVERITIES: Array<ConflictSeverity | "all"> = ["all", "critical", "major", "minor"];
const STATUSES: Array<ConflictStatus | "all"> = ["all", "open", "resolved", "dismissed"];

export default function ConflictDashboardPage() {
  const router = useRouter();
  const session = useSession();
  const [projectId, setProjectId] = useState<string>((session as { projectId?: string }).projectId ?? "");
  const [severity, setSeverity] = useState<ConflictSeverity | "all">("all");
  const [statusFilter, setStatusFilter] = useState<ConflictStatus | "all">("open");

  const { data, isLoading } = useConflicts({
    project_id: projectId,
    severity: severity === "all" ? undefined : severity,
    status: statusFilter === "all" ? undefined : statusFilter,
  });

  const scan = useConflictScan();
  const update = useUpdateConflict();
  const generateRfi = useGenerateRFI();

  const list = data?.data ?? [];

  const counts = list.reduce(
    (acc, c) => {
      if (c.severity) acc[c.severity] = (acc[c.severity] ?? 0) + 1;
      return acc;
    },
    {} as Record<ConflictSeverity, number>,
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-slate-900">Bảng điều khiển xung đột</h2>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            placeholder="project_id"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as ConflictSeverity | "all")}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as ConflictStatus | "all")}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!projectId || scan.isPending}
            onClick={() => scan.mutate({ project_id: projectId })}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Play size={14} />
            {scan.isPending ? "Đang quét..." : "Quét xung đột"}
          </button>
        </div>
      </div>

      <section className="grid grid-cols-3 gap-3">
        <SeverityTile severity="critical" count={counts.critical ?? 0} />
        <SeverityTile severity="major" count={counts.major ?? 0} />
        <SeverityTile severity="minor" count={counts.minor ?? 0} />
      </section>

      {scan.data && scan.isSuccess && (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800">
          Quét xong: {scan.data.scanned_documents} tài liệu, {scan.data.candidates_evaluated} cặp, phát hiện{" "}
          <strong>{scan.data.conflicts_found}</strong> xung đột.
        </div>
      )}

      <section className="space-y-3">
        {isLoading ? (
          <p className="text-sm text-slate-500">Đang tải...</p>
        ) : list.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
            <ShieldAlert className="mx-auto mb-3 text-slate-400" size={28} />
            <p className="text-sm text-slate-500">Không phát hiện xung đột.</p>
          </div>
        ) : (
          list.map((c) => (
            <ConflictCard
              key={c.id}
              conflict={c}
              onOpen={(cf) => router.push(`/drawbridge/conflicts/${cf.id}`)}
              onResolve={(cf) => update.mutate({ id: cf.id, status: "resolved" })}
              onDismiss={(cf) => update.mutate({ id: cf.id, status: "dismissed" })}
              onGenerateRfi={(cf) =>
                generateRfi.mutate(
                  { conflict_id: cf.id },
                  {
                    onSuccess: () => router.push("/drawbridge/rfis"),
                  },
                )
              }
            />
          ))
        )}
      </section>
    </div>
  );
}

function SeverityTile({ severity, count }: { severity: ConflictSeverity; count: number }) {
  const styles: Record<ConflictSeverity, string> = {
    critical: "bg-red-50 border-red-200 text-red-800",
    major: "bg-amber-50 border-amber-200 text-amber-800",
    minor: "bg-slate-50 border-slate-200 text-slate-700",
  };
  const label: Record<ConflictSeverity, string> = {
    critical: "Nghiêm trọng",
    major: "Lớn",
    minor: "Nhỏ",
  };
  return (
    <div className={`rounded-xl border p-4 ${styles[severity]}`}>
      <div className="text-xs font-medium uppercase tracking-wide">{label[severity]}</div>
      <div className="mt-1 text-3xl font-bold">{count}</div>
    </div>
  );
}
