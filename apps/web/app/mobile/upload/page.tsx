"use client";
import { useState } from "react";

import { MobileUploader } from "@aec/ui/siteeye";
import { useSession } from "@/lib/auth-context";
import { useProjects } from "@/hooks/projects";
import { useUploadPhotos } from "@/hooks/siteeye";

interface FilesUploadResponse {
  file_id: string;
  storage_key: string;
  thumbnail_url: string | null;
}

/**
 * Field-crew photo upload. Hits this from a phone on a job site.
 *
 * Replaced the prior typed-UUID inputs with a project picker driven by
 * `useProjects` — typing a 36-char UUID on a 5-inch screen with a
 * grease-gloved finger was never going to work. Visit ID stays
 * optional and free-form because not every visit has a synced UUID
 * yet (you might capture photos during an unscheduled walk).
 */
export default function MobileUploadPage() {
  const { token } = useSession();
  const upload = useUploadPhotos();
  // Recent active projects come back from `/api/v1/projects` already
  // filtered to caller's org. We pull the top 50 — anything beyond
  // that is stale enough that re-typing the name in search is fine.
  const { data: projectsData } = useProjects({ status: "active", per_page: 50 });
  const [projectId, setProjectId] = useState<string>("");
  const [visitId, setVisitId] = useState<string>("");
  const [lastJob, setLastJob] = useState<string | null>(null);

  const projects = projectsData?.data ?? [];

  async function handleUpload(
    files: File[],
    location: { lat: number; lng: number } | null,
  ) {
    if (!projectId) throw new Error("Project is required");

    const uploaded = await Promise.all(
      files.map(async (file) => {
        const form = new FormData();
        form.append("file", file);
        form.append("source_module", "siteeye");
        form.append("project_id", projectId);
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/files`,
          {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: form,
          },
        );
        const json = (await res.json()) as { data: FilesUploadResponse };
        return {
          file_id: json.data.file_id,
          thumbnail_url: json.data.thumbnail_url ?? null,
          taken_at: new Date(file.lastModified).toISOString(),
          location,
        };
      }),
    );

    const result = await upload.mutateAsync({
      project_id: projectId,
      site_visit_id: visitId || null,
      photos: uploaded,
    });
    setLastJob(result.job_id);
  }

  return (
    <main className="mx-auto max-w-md space-y-4 p-4">
      <header>
        <h1 className="text-lg font-semibold text-gray-900">Upload site photos</h1>
        <p className="text-xs text-gray-500">
          Take photos on site and upload in batch. AI analysis runs in the background.
        </p>
      </header>

      <div className="space-y-2">
        {/* Project picker — `<select>` because native iOS / Android
            controls handle long lists better than custom comboboxes
            on small screens, and it's keyboard-free. */}
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-700">
            Project
          </span>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-full rounded border border-gray-300 bg-white px-3 py-2 text-sm"
          >
            <option value="">— Choose a project —</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-700">
            Visit ID <span className="text-gray-400">(optional)</span>
          </span>
          <input
            type="text"
            inputMode="text"
            autoComplete="off"
            placeholder="e.g. visit-2026-04-28"
            value={visitId}
            onChange={(e) => setVisitId(e.target.value.trim())}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </label>
      </div>

      {projectId ? (
        <MobileUploader
          projectId={projectId}
          siteVisitId={visitId || undefined}
          uploading={upload.isPending}
          onUpload={handleUpload}
        />
      ) : (
        <p className="text-sm text-gray-500">Choose a project to begin.</p>
      )}

      {lastJob ? (
        <p className="rounded bg-emerald-50 p-2 text-xs text-emerald-800">
          Queued analysis job {lastJob}
        </p>
      ) : null}
    </main>
  );
}
