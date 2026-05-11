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
import { Badge, Input, PageHeader } from "@aec/ui/primitives";
import { useSession } from "@/lib/auth-context";
import { useDocuments, useUploadDocument } from "@/hooks/drawbridge";
import { ProjectSelect } from "@/app/(dashboard)/_components/ProjectSelect";

const DISCIPLINES: Array<{ value: Discipline; label: string }> = [
  { value: "architectural", label: "Kiến trúc" },
  { value: "structural", label: "Kết cấu" },
  { value: "mep", label: "MEP" },
  { value: "civil", label: "Hạ tầng" },
];
const DOC_TYPES: Array<{ value: DocType; label: string }> = [
  { value: "drawing", label: "Bản vẽ" },
  { value: "spec", label: "Thuyết minh kỹ thuật" },
  { value: "report", label: "Báo cáo" },
  { value: "contract", label: "Hợp đồng" },
  { value: "rfi", label: "RFI" },
  { value: "submittal", label: "Hồ sơ đệ trình" },
];
const PROCESSING_STATUS_LABEL: Record<string, string> = {
  pending: "Chờ xử lý",
  processing: "Đang xử lý",
  ready: "Sẵn sàng",
  failed: "Lỗi",
};

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
      alert("Vui lòng chọn dự án trước khi tải lên");
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
      <PageHeader
        title="Thư viện tài liệu"
        actions={
          <>
            <ProjectSelect value={projectId} onChange={setProjectId} />
            <select
              value={discipline}
              onChange={(e) => setDiscipline(e.target.value as Discipline | "")}
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">Tất cả bộ môn</option>
              {DISCIPLINES.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value as DocType | "")}
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="">Tất cả loại</option>
              {DOC_TYPES.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
            <div className="relative">
              <Search
                size={14}
                className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Tìm kiếm..."
                className="w-56 pl-7"
              />
            </div>
          </>
        }
      />

      <DocumentUploadZone onFilesAdded={onFilesAdded} tasks={uploadTasks} disabled={!projectId} />

      <section className="rounded-xl border bg-card">
        <header className="border-b px-4 py-2 text-sm font-semibold text-foreground">
          {isLoading ? "Đang tải..." : `${docs.length} tài liệu`}
        </header>
        <ul className="divide-y">
          {docs.map((d) => (
            <DocumentRow key={d.id} doc={d} />
          ))}
          {!isLoading && docs.length === 0 && (
            <li className="px-4 py-12 text-center text-sm text-muted-foreground">
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
        className="flex items-center gap-3 px-4 py-3 hover:bg-muted/40"
      >
        <FileText size={16} className="text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {doc.drawing_number && (
              <span className="font-mono text-xs text-foreground">{doc.drawing_number}</span>
            )}
            <span className="truncate text-sm font-medium text-foreground">
              {doc.title ?? "(Không tiêu đề)"}
            </span>
            <DisciplineTag discipline={doc.discipline} size="sm" />
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-xs text-muted-foreground">
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
  const variant: Record<Document["processing_status"], "default" | "secondary" | "success" | "destructive"> = {
    pending: "secondary",
    processing: "default",
    ready: "success",
    failed: "destructive",
  };
  return (
    <Badge variant={variant[status]}>
      {PROCESSING_STATUS_LABEL[status] ?? status}
    </Badge>
  );
}
