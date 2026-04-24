"use client";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiRequest, apiRequestWithMeta } from "@/lib/api-client";
import { useSession } from "@/lib/auth-context";
import { siteeyeKeys } from "./keys";
import type {
  PhotoBatchUploadRequest,
  PhotoBatchUploadResponse,
  PhotoListFilters,
  SitePhoto,
} from "./types";

export function usePhotos(filters: PhotoListFilters = {}) {
  const { token } = useSession();
  return useQuery({
    queryKey: siteeyeKeys.photos(filters),
    queryFn: () =>
      apiRequestWithMeta<SitePhoto[]>("/api/v1/siteeye/photos", {
        params: serialize(filters),
        token,
      }),
    placeholderData: keepPreviousData,
  });
}

export function useUploadPhotos() {
  const { token } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PhotoBatchUploadRequest) =>
      apiRequest<PhotoBatchUploadResponse>("/api/v1/siteeye/photos/upload", {
        method: "POST",
        body,
        token,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: siteeyeKeys.all });
    },
  });
}

function serialize(f: PhotoListFilters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (f.project_id) out.project_id = f.project_id;
  if (f.site_visit_id) out.site_visit_id = f.site_visit_id;
  if (f.safety_status) out.safety_status = f.safety_status;
  if (f.date_from) out.date_from = f.date_from;
  if (f.date_to) out.date_to = f.date_to;
  if (f.tags?.length) out.tags = f.tags.join(",");
  if (f.limit !== undefined) out.limit = f.limit;
  if (f.offset !== undefined) out.offset = f.offset;
  return out;
}
