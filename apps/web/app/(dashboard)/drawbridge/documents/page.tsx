"use client";

import Link from "next/link";
import { useState } from "react";
import { FileText, Search } from "lucide-react";

import {
  DisciplineTag,
  DocumentUploadZone,
  type Discipline,
  type DocType,
  type Document,
  type UploadTask,
} from "@aec/ui/drawbridge";
import { useSession } from "@/lib/auth-context";
import { useDocuments, useUploadDocument } from "@/hooks/drawbridge";

const DISCIPLINES: Discipline[] = ["architectural", "structural", "mep", "civil"];
const DOC_TYPES: DocType[] = ["drawing", "spec", "report", "contract", "rfi", "submittal"];

export default function DocumentLibraryPage() {
  // Project scoping: in production pull from URL or a ProjectPicker context.
  const session = useSession();
  const [projectId, setProjectId] = useState<string>(
    (session as { projectId?: string }).projectId ?? "",
  );
  const [discipline, setDiscipline] = useState<Discipline | "">("");
  const [docType, setDocType] = useState<DocType | "">("");
  const [q, setQ] = useState("");
  const [uploadTasks, setUploadTasks] = useState<UploadTask[]>([]);

  const { data, isLoading } = useDocuments({
    project_id: projectId || undefined,
    discipline: discipline || undefined,
    doc_type: docType || undefined,
    q: q || undefined,
  });

  const upload = useUploadDocument();

  const onFilesAdded = async (files: File[]) => {
    if (!projectId) {
      alert("Vui lòng nhập project_id trước khi tải lên");
      return;
    }
    const queued: UploadTask[] = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      status: "uploading",
    }));
    setUploadTasks((prev) => [...queued, ...prev]);

    for (const task of queued) {
      try {
        const doc = await upload.mutateAsync({
          file: task.file,
          project_id: projectId,
          discipline: (discipline || undefined) as Discipline | undefined,
          doc_type: (docType || undefined) as DocType | undefined,
        });
        setUploadTasks((prev) =>
          prev.map((t) => (t.id === task.id ? { ...t, status: doc.processing_status } : t)),
        );
      } catch (err) {
        setUploadTasks((prev) =>
          prev.map((t) =>
            t.id === task.id
              ? { ...t, status: "failed", error: err instanceof Error ? err.message : "Upload failed" }
              : t,
          ),
        );
      }
    }
  };

  const docs = data?.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-slate-900">Thư viện tài liệu</h2>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            placeholder="project_id"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value as Discipline | "")}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Tất cả bộ môn</option>
            {DISCIPLINES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as DocType | "")}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Tất cả loại</option>
            {DOC_TYPES.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <div className="relative">
            <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Tìm kiếm..."
              className="w-56 rounded-md border border-slate-300 py-1.5 pl-7 pr-3 text-sm"
            />
          </div>
        </div>
      </div>

      <DocumentUploadZone onFilesAdded={onFilesAdded} tasks={uploadTasks} disabled={!projectId} />

      <section className="rounded-xl border border-slate-200 bg-white">
        <header className="border-b border-slate-200 px-4 py-2 text-sm font-semibold text-slate-800">
          {isLoading ? "Đang tải..." : `${docs.length} tài liệu`}
        </header>
        <ul className="divide-y divide-slate-100">
          {docs.map((d) => (
            <DocumentRow key={d.id} doc={d} />
          ))}
          {!isLoading && docs.length === 0 && (
            <li className="px-4 py-12 text-center text-sm text-slate-400">
              Chưa có tài liệu nào. Tải lên để bắt đầu.
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}

function DocumentRow({ doc }: { doc: Document }) {
  return (
    <li>
      <Link
        href={`/drawbridge/documents/${doc.id}`}
        className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50"
      >
        <FileText size={16} className="text-slate-500" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {doc.drawing_number && (
              <span className="font-mono text-xs text-slate-700">{doc.drawing_number}</span>
            )}
            <span className="truncate text-sm font-medium text-slate-900">
              {doc.title ?? "(Không tiêu đề)"}
            </span>
            <DisciplineTag discipline={doc.discipline} size="sm" />
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-slate-500">
            {doc.doc_type && <span className="uppercase">{doc.doc_type}</span>}
            {doc.revision && <span>rev {doc.revision}</span>}
            <span>{new Date(doc.created_at).toLocaleDateString()}</span>
          </div>
        </div>
        <StatusBadge status={doc.processing_status} />
      </Link>
    </li>
  );
}

function StatusBadge({ status }: { status: Document["processing_status"] }) {
  const map = {
    pending: "bg-slate-100 text-slate-600",
    processing: "bg-blue-100 text-blue-800",
    ready: "bg-emerald-100 text-emerald-800",
    failed: "bg-red-100 text-red-700",
  } as const;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${map[status]}`}>{status}</span>
  );
}
