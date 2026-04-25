"use client";
import Link from "next/link";
import type { Route } from "next";

import {
  PhaseBar,
  PhotoGallery,
  ProgressGauge,
  SafetyBadge,
} from "@aec/ui/siteeye";
import {
  usePhotos,
  useProgressTimeline,
  useSafetyIncidents,
} from "@/hooks/siteeye";

import { useSelectedProject } from "../project-context";

export default function SiteDashboardPage() {
  const { projectId } = useSelectedProject();

  const progressQ = useProgressTimeline(projectId ?? undefined);
  const photosQ = usePhotos({ project_id: projectId ?? undefined, limit: 8 });
  const incidentsQ = useSafetyIncidents({
    project_id: projectId ?? undefined,
    status: "open",
    limit: 1,
  });

  if (!projectId) {
    return (
      <p className="text-sm text-gray-600">
        Select a project first.{" "}
        <Link href={"/projects" as Route} className="text-sky-600 underline">
          Browse projects
        </Link>
      </p>
    );
  }

  const timeline = progressQ.data;
  const latest = timeline?.snapshots.at(-1);
  const photos = photosQ.data?.data ?? [];
  const openIncidents = incidentsQ.data?.meta?.total ?? 0;

  const safetyStatus =
    openIncidents === 0 ? "clear" : openIncidents > 3 ? "critical" : "warning";

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Site dashboard</h1>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <ProgressGauge
            value={latest?.overall_progress_pct ?? 0}
            scheduleStatus={timeline?.schedule_status ?? "unknown"}
          />
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-gray-600">Phase progress</h2>
          <PhaseBar phaseProgress={latest?.phase_progress ?? {}} />
        </div>
        <div className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-gray-600">Safety</h2>
          <div className="flex items-center justify-between">
            <span className="text-2xl font-semibold text-gray-900">{openIncidents}</span>
            <SafetyBadge status={safetyStatus} />
          </div>
          <Link
            href="/siteeye/safety"
            className="text-xs text-sky-600 hover:underline"
          >
            View incidents →
          </Link>
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-600">Recent photos</h2>
          <Link href="/siteeye/visits" className="text-xs text-sky-600 hover:underline">
            All visits →
          </Link>
        </div>
        <PhotoGallery photos={photos} />
      </section>
    </div>
  );
}
