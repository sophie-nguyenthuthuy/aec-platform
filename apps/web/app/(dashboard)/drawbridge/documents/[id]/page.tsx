"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { DisciplineTag, PDFViewer, type PdfHighlight } from "@aec/ui/drawbridge";
import { useDocument } from "@/hooks/drawbridge";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function DocumentViewerPage() {
  const { id } = useParams<{ id: string }>();
  const { data: doc, isLoading, error } = useDocument(id);
  const [page, setPage] = useState(1);

  const src = useMemo(() => {
    if (!doc?.file_id) return "";
    // The API should sign and serve file bytes via /files/{file_id}/download.
    return `${BASE_URL}/api/v1/files/${doc.file_id}/download`;
  }, [doc?.file_id]);

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (error || !doc) return <p className="text-sm text-red-600">Không tìm thấy tài liệu.</p>;

  const highlights: PdfHighlight[] = [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section>
        <header className="mb-3 flex items-center gap-2">
          {doc.drawing_number && (
            <span className="font-mono text-sm text-slate-700">{doc.drawing_number}</span>
          )}
          <h2 className="text-lg font-semibold text-slate-900">{doc.title ?? "Tài liệu"}</h2>
          <DisciplineTag discipline={doc.discipline} />
        </header>
        <div className="flex items-center gap-2 pb-3">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50"
          >
            ← Trang
          </button>
          <span className="text-xs text-slate-600">Trang {page}</span>
          <button
            type="button"
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50"
          >
            Trang →
          </button>
        </div>
        {src ? (
          <PDFViewer src={src} page={page} highlights={highlights} className="w-full" />
        ) : (
          <p className="text-sm text-slate-500">Tệp không khả dụng.</p>
        )}
      </section>

      <aside className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <h3 className="text-sm font-semibold text-slate-900">Thông tin</h3>
        <dl className="space-y-1 text-xs">
          <MetaRow label="Loại" value={doc.doc_type ?? "—"} />
          <MetaRow label="Revision" value={doc.revision ?? "—"} />
          <MetaRow label="Scale" value={doc.scale ?? "—"} />
          <MetaRow label="Trạng thái xử lý" value={doc.processing_status} />
          <MetaRow label="Ngày tạo" value={new Date(doc.created_at).toLocaleString()} />
        </dl>
      </aside>
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-100 py-1 last:border-b-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-800">{value}</dd>
    </div>
  );
}
