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
 * Trigger a browser download of the per-entity CSV template the user
 * fills in. The wizard surfaces this as "Tải file mẫu" — without it,
 * users have to guess column names from the inline hint, which they
 * don't always do correctly (typo `external id` → entire upload fails
 * validation, frustrating UX).
 *
 * We synthesize the download via a temporary anchor instead of
 * `window.location = url` so the Authorization + X-Org-ID headers
 * carry. The blob is revoked synchronously after the click — leaking
 * blob URLs is a slow memory drip in long-lived dashboard sessions.
 */
export function useImportTemplateDownload() {
  const { token, orgId } = useSession();
  return async (entity: ImportEntity) => {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/import/${entity}/template.csv`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Org-ID": orgId,
        },
      },
    );
    if (!res.ok) {
      throw new Error(`Failed to download template: ${res.statusText}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aec-${entity}-template.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };
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
