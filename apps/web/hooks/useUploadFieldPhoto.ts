"use client";

import { useMutation } from "@tanstack/react-query";

import { useSession } from "@/lib/auth-context";

export interface UploadedFieldPhoto {
  file_id: string;
  storage_key: string;
  thumbnail_url: string | null;
  mime_type: string | null;
  size_bytes: number;
  name: string;
}

export interface UploadFieldPhotoInput {
  file: File;
  source_module: "punchlist" | "dailylog" | "siteeye";
  project_id?: string;
}

/**
 * Single-shot upload for a field-captured image. Posts FormData to the
 * shared `/api/v1/files` endpoint with `source_module=<caller>` so the
 * file row gets tagged for the right module's lifecycle (cleanup,
 * thumbnail generation, presign rules).
 *
 * Designed to back a `<input type="file" accept="image/*"
 * capture="environment">` chooser — on iOS / Android the `capture` hint
 * makes Safari / Chrome jump straight to the rear camera instead of the
 * gallery picker. On desktop it falls back to the file dialog gracefully,
 * so the same component works everywhere without a `userAgent` sniff.
 *
 * Returns the file UUID + thumbnail URL the caller can stash in
 * (e.g.) a punch item's `photo_id` or render in a preview grid.
 */
export function useUploadFieldPhoto() {
  const { token, orgId } = useSession();

  return useMutation({
    mutationKey: ["files", "upload-field-photo"],
    mutationFn: async ({
      file,
      source_module,
      project_id,
    }: UploadFieldPhotoInput): Promise<UploadedFieldPhoto> => {
      const form = new FormData();
      form.append("file", file);
      form.append("source_module", source_module);
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

      const json = (await res.json()) as { data: Omit<UploadedFieldPhoto, "name"> };
      return { ...json.data, name: file.name };
    },
  });
}
