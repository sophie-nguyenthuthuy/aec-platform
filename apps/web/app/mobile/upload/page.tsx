"use client";
import { useState } from "react";

import { MobileUploader } from "@aec/ui/siteeye";
import { apiRequest } from "@/lib/api-client";
import { useSession } from "@/lib/auth-context";
import { useUploadPhotos } from "@/hooks/siteeye";

interface FilesUploadResponse {
  file_id: string;
  storage_key: string;
  thumbnail_url: string | null;
}

export default function MobileUploadPage() {
  const { token } = useSession();
  const upload = useUploadPhotos();
  const [projectId, setProjectId] = useState<string>("");
  const [visitId, setVisitId] = useState<string>("");
  const [lastJob, setLastJob] = useState<string | null>(null);

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
        <input
          type="text"
          placeholder="Project ID"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value.trim())}
          className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm"
        />
        <input
          type="text"
          placeholder="Visit ID (optional)"
          value={visitId}
          onChange={(e) => setVisitId(e.target.value.trim())}
          className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm"
        />
      </div>

      {projectId ? (
        <MobileUploader
          projectId={projectId}
          siteVisitId={visitId || undefined}
          uploading={upload.isPending}
          onUpload={handleUpload}
        />
      ) : (
        <p className="text-sm text-gray-500">Enter a project ID to begin.</p>
      )}

      {lastJob ? (
        <p className="rounded bg-emerald-50 p-2 text-xs text-emerald-800">
          Queued analysis job {lastJob}
        </p>
      ) : null}
    </main>
  );
}
