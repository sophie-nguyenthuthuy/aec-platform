"use client";

import { useMutation } from "@tanstack/react-query";

import { useSession } from "@/lib/auth-context";

export interface UploadedDrawing {
  file_id: string;
  storage_key: string;
  thumbnail_url: string | null;
  mime_type: string | null;
  size_bytes: number;
  name: string;
}

export interface UploadDrawingInput {
  file: File;
  project_id?: string;
}

/**
 * Uploads a single drawing file to the shared /api/v1/files endpoint with
 * source_module="costpulse" and returns the newly-created file UUID so the
 * caller can feed it into /estimate/from-drawings.
 */
export function useUploadDrawing() {
  const { token, orgId } = useSession();

  return useMutation({
    mutationKey: ["costpulse", "upload-drawing"],
    mutationFn: async ({ file, project_id }: UploadDrawingInput): Promise<UploadedDrawing> => {
      const form = new FormData();
      form.append("file", file);
      form.append("source_module", "costpulse");
      if (project_id) form.append("project_id", project_id);

      const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${base}/api/v1/files`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Org-ID": orgId,
        },
        body: form,
      });

      if (!res.ok) {
        const json = (await res.json().catch(() => ({}))) as {
          errors?: Array<{ message?: string }>;
        };
        throw new Error(json.errors?.[0]?.message ?? `Upload failed (${res.status})`);
      }

      const json = (await res.json()) as { data: Omit<UploadedDrawing, "name"> };
      return { ...json.data, name: file.name };
    },
  });
}
