"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { Envelope } from "@aec/types/envelope";


// ---------- Response types ----------
//
// Mirror the payload returned by `POST /api/v1/import/{entity}/preview`
// and friends. Lifted to this file so the page renders results without
// dipping into the api router's Pydantic schemas.

export type ImportEntity = "projects" | "suppliers";

export type ImportStatus = "previewed" | "committed" | "failed";

export interface ImportRowError {
  row_idx: number;
  message: string;
}

export interface ImportJobSummary {
  id: string;
  entity: ImportEntity;
  filename: string;
  status: ImportStatus;
  row_count: number;
  valid_count: number;
  error_count: number;
  errors: ImportRowError[];
  created_at: string;
  // Present on detail/commit fetches; preview returns null.
  committed_count?: number | null;
  committed_at?: string | null;
}


export interface PreviewVars {
  entity: ImportEntity;
  file: File;
}


/**
 * Multipart upload + parse + validate. Cannot use `apiFetch` because
 * that helper forces `Content-Type: application/json`; the FastAPI
 * `UploadFile` parameter needs the browser to set the multipart
 * boundary, which only happens when we let `fetch` look at FormData
 * itself (no Content-Type header from us).
 */
export function useImportPreview() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["imports", "preview"],
    mutationFn: async ({ entity, file }: PreviewVars) => {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/import/${entity}/preview`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Org-ID": orgId,
          },
          body: form,
        },
      );
      const json = (await res.json().catch(() => ({}))) as Envelope<ImportJobSummary>;
      if (!res.ok) {
        const err = json.errors?.[0];
        throw new Error(err?.message ?? res.statusText);
      }
      return json.data as ImportJobSummary;
    },
  });
}


/**
 * Commit a previewed job. Idempotent on the server side — the second
 * call short-circuits via the `committed` status check, so a flaky
 * network retry won't double-write.
 */
export function useImportCommit() {
  const { token, orgId } = useSession();
  return useMutation({
    mutationKey: ["imports", "commit"],
    mutationFn: async (jobId: string) => {
      const res = await apiFetch<{ id: string; status: ImportStatus; committed_count: number }>(
        `/api/v1/import/jobs/${jobId}/commit`,
        { method: "POST", token, orgId },
      );
      return res.data as { id: string; status: ImportStatus; committed_count: number };
    },
  });
}
