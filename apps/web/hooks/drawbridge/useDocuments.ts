"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type {
  Discipline,
  DocType,
  Document,
  DocumentSet,
  ProcessingStatus,
} from "@aec/ui/drawbridge";

import { drawbridgeKeys } from "./keys";

export interface DocumentFilters {
  project_id?: string;
  document_set_id?: string;
  discipline?: Discipline;
  doc_type?: DocType;
  processing_status?: ProcessingStatus;
  q?: string;
  limit?: number;
  offset?: number;
}

export function useDocuments(filters: DocumentFilters = {}) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: drawbridgeKeys.documents(filters),
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await apiFetch<Document[]>("/api/v1/drawbridge/documents", {
        method: "GET",
        token,
        orgId,
        query: {
          project_id: filters.project_id,
          document_set_id: filters.document_set_id,
          discipline: filters.discipline,
          doc_type: filters.doc_type,
          processing_status: filters.processing_status,
          q: filters.q,
          limit: filters.limit ?? 50,
          offset: filters.offset ?? 0,
        },
      });
      return { data: (res.data ?? []) as Document[], meta: res.meta };
    },
  });
}

export function useDocument(id: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(id),
    queryKey: id ? drawbridgeKeys.document(id) : ["noop"],
    queryFn: async () => {
      const res = await apiFetch<Document>(`/api/v1/drawbridge/documents/${id}`, {
        method: "GET",
        token,
        orgId,
      });
      return res.data as Document;
    },
  });
}

export interface UploadDocumentInput {
  file: File;
  project_id: string;
  document_set_id?: string;
  doc_type?: DocType;
  drawing_number?: string;
  title?: string;
  revision?: string;
  discipline?: Discipline;
  scale?: string;
}

export function useUploadDocument() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "documents", "upload"],
    mutationFn: async (input: UploadDocumentInput) => {
      const form = new FormData();
      form.append("file", input.file);
      form.append("project_id", input.project_id);
      if (input.document_set_id) form.append("document_set_id", input.document_set_id);
      if (input.doc_type) form.append("doc_type", input.doc_type);
      if (input.drawing_number) form.append("drawing_number", input.drawing_number);
      if (input.title) form.append("title", input.title);
      if (input.revision) form.append("revision", input.revision);
      if (input.discipline) form.append("discipline", input.discipline);
      if (input.scale) form.append("scale", input.scale);

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/drawbridge/documents/upload`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Org-ID": orgId,
          },
          body: form,
        },
      );
      if (!res.ok) {
        const json = (await res.json().catch(() => ({}))) as {
          errors?: Array<{ message?: string }>;
        };
        throw new Error(json.errors?.[0]?.message ?? `Upload failed (${res.status})`);
      }
      const json = (await res.json()) as { data: Document };
      return json.data;
    },
    onSuccess: (doc) => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
      qc.setQueryData(drawbridgeKeys.document(doc.id), doc);
    },
  });
}

export function useDeleteDocument() {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["drawbridge", "documents", "delete"],
    mutationFn: async (id: string) => {
      await apiFetch(`/api/v1/drawbridge/documents/${id}`, {
        method: "DELETE",
        token,
        orgId,
      });
      return id;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: drawbridgeKeys.all });
    },
  });
}

export function useDocumentSets(projectId: string | undefined) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(projectId),
    queryKey: drawbridgeKeys.documentSets(projectId),
    queryFn: async () => {
      const res = await apiFetch<DocumentSet[]>("/api/v1/drawbridge/document-sets", {
        method: "GET",
        token,
        orgId,
        query: { project_id: projectId },
      });
      return (res.data ?? []) as DocumentSet[];
    },
  });
}
