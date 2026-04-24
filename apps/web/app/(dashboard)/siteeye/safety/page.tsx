"use client";
import { useState } from "react";

import { IncidentTable, SeverityBadge } from "@aec/ui/siteeye";
import {
  useAcknowledgeIncident,
  useSafetyIncidents,
  type IncidentStatus,
} from "@/hooks/siteeye";

import { useSelectedProject } from "../project-context";

const STATUS_FILTERS: Array<{ label: string; value: IncidentStatus | undefined }> = [
  { label: "All", value: undefined },
  { label: "Open", value: "open" },
  { label: "Acknowledged", value: "acknowledged" },
  { label: "Resolved", value: "resolved" },
];

export default function SafetyDashboardPage() {
  const { projectId } = useSelectedProject();
  const [status, setStatus] = useState<IncidentStatus | undefined>("open");

  const q = useSafetyIncidents({
    project_id: projectId ?? undefined,
    status,
    limit: 100,
  });
  const ack = useAcknowledgeIncident();

  const incidents = q.data?.data ?? [];

  const bySeverity = incidents.reduce<Record<string, number>>((acc, i) => {
    acc[i.severity] = (acc[i.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-gray-900">Safety incidents</h1>

      <section className="flex flex-wrap gap-2">
        {Object.entries(bySeverity).map(([sev, n]) => (
          <div
            key={sev}
            className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2"
          >
            <SeverityBadge severity={sev as "low" | "medium" | "high" | "critical"} />
            <span className="font-semibold">{n}</span>
          </div>
        ))}
      </section>

      <div className="flex gap-2">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            onClick={() => setStatus(f.value)}
            className={`rounded px-3 py-1 text-sm ${
              status === f.value
                ? "bg-sky-600 text-white"
                : "border border-gray-300 bg-white text-gray-700"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <IncidentTable
        incidents={incidents}
        onAcknowledge={(id) => ack.mutate({ id })}
        onResolve={(id) => ack.mutate({ id, resolve: true })}
      />
    </div>
  );
}
