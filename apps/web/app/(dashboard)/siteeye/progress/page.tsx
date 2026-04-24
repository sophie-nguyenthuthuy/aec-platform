"use client";

import { PhaseBar, ProgressChart, ProgressGauge } from "@aec/ui/siteeye";
import { useProgressTimeline } from "@/hooks/siteeye";

import { useSelectedProject } from "../project-context";

export default function ProgressTimelinePage() {
  const { projectId } = useSelectedProject();
  const q = useProgressTimeline(projectId ?? undefined);

  if (!projectId) {
    return <p className="text-sm text-gray-600">Select a project first.</p>;
  }

  const timeline = q.data;
  const latest = timeline?.snapshots.at(-1);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Progress timeline</h1>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <ProgressGauge
            value={latest?.overall_progress_pct ?? 0}
            scheduleStatus={timeline?.schedule_status ?? "unknown"}
          />
        </div>
        <div className="md:col-span-2 rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-gray-600">Phase progress</h2>
          <PhaseBar phaseProgress={latest?.phase_progress ?? {}} />
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-gray-600">Overall % over time</h2>
        <ProgressChart snapshots={timeline?.snapshots ?? []} />
      </section>

      {latest?.ai_notes ? (
        <section className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-1 text-sm font-semibold text-gray-600">AI notes</h2>
          <p className="text-sm text-gray-800">{latest.ai_notes}</p>
        </section>
      ) : null}
    </div>
  );
}
