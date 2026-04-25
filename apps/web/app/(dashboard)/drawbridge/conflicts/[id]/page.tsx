"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, FileText, Sparkles, XCircle } from "lucide-react";

import {
  DisciplineTag,
  PDFViewer,
  type ConflictExcerpt,
  type PdfHighlight,
} from "@aec/ui/drawbridge";
import {
  useConflict,
  useGenerateRFI,
  useUpdateConflict,
} from "@/hooks/drawbridge";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SEVERITY_STYLES = {
  critical: "bg-red-50 border-red-200 text-red-800",
  major: "bg-amber-50 border-amber-200 text-amber-800",
  minor: "bg-slate-50 border-slate-200 text-slate-700",
} as const;

const SEVERITY_LABEL = {
  critical: "Nghiêm trọng",
  major: "Lớn",
  minor: "Nhỏ",
} as const;

export default function ConflictDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: conflict, isLoading, error } = useConflict(id);

  const update = useUpdateConflict();
  const generateRfi = useGenerateRFI();
  const [notes, setNotes] = useState("");

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (error || !conflict)
    return (
      <div className="space-y-3">
        <BackLink />
        <p className="text-sm text-red-600">Không tìm thấy xung đột.</p>
      </div>
    );

  const sevKey = conflict.severity ?? "minor";

  const handleResolve = () => {
    update.mutate(
      { id: conflict.id, status: "resolved", resolution_notes: notes || undefined },
      { onSuccess: () => router.push("/drawbridge/conflicts") },
    );
  };

  const handleDismiss = () => {
    update.mutate(
      { id: conflict.id, status: "dismissed", resolution_notes: notes || undefined },
      { onSuccess: () => router.push("/drawbridge/conflicts") },
    );
  };

  const handleGenerateRfi = () => {
    generateRfi.mutate(
      { conflict_id: conflict.id },
      { onSuccess: () => router.push("/drawbridge/rfis") },
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <BackLink />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full border px-2 py-0.5 text-xs font-medium ${SEVERITY_STYLES[sevKey]}`}
            >
              {SEVERITY_LABEL[sevKey]}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
              {conflict.status}
            </span>
            {conflict.conflict_type && (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                {conflict.conflict_type}
              </span>
            )}
            <span className="text-xs text-slate-500">
              Phát hiện {new Date(conflict.detected_at).toLocaleString()}
            </span>
          </div>
          <h2 className="mt-2 text-xl font-semibold text-slate-900">
            {conflict.description ?? "Xung đột giữa bản vẽ"}
          </h2>
        </div>

        {conflict.status === "open" && (
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={generateRfi.isPending}
              onClick={handleGenerateRfi}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Sparkles size={14} />
              {generateRfi.isPending ? "Đang tạo..." : "Tạo RFI"}
            </button>
          </div>
        )}
      </div>

      {conflict.ai_explanation && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide">
            <Sparkles size={12} /> Phân tích AI
          </div>
          <p className="whitespace-pre-wrap">{conflict.ai_explanation}</p>
        </div>
      )}

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DocumentPane side="A" excerpt={conflict.document_a} />
        <DocumentPane side="B" excerpt={conflict.document_b} />
      </section>

      {conflict.status === "open" && (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Ghi chú xử lý</h3>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Mô tả cách xử lý xung đột (tuỳ chọn)..."
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={update.isPending}
              onClick={handleResolve}
              className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
            >
              <CheckCircle2 size={14} /> Đánh dấu đã xử lý
            </button>
            <button
              type="button"
              disabled={update.isPending}
              onClick={handleDismiss}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              <XCircle size={14} /> Bỏ qua
            </button>
          </div>
        </section>
      )}

      {conflict.status !== "open" && conflict.resolution_notes && (
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h3 className="mb-1 text-sm font-semibold text-slate-900">Ghi chú xử lý</h3>
          <p className="whitespace-pre-wrap text-sm text-slate-700">
            {conflict.resolution_notes}
          </p>
          {conflict.resolved_at && (
            <p className="mt-2 text-xs text-slate-500">
              {new Date(conflict.resolved_at).toLocaleString()}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/drawbridge/conflicts"
      className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"
    >
      <ArrowLeft size={12} /> Quay lại danh sách
    </Link>
  );
}

function DocumentPane({
  side,
  excerpt,
}: {
  side: "A" | "B";
  excerpt: ConflictExcerpt | null;
}) {
  const src = useMemo(() => {
    if (!excerpt?.document_id) return "";
    // Server-side redirect to /api/v1/files/{file_id}/download (see router.get_document_file).
    return `${BASE_URL}/api/v1/drawbridge/documents/${excerpt.document_id}/file`;
  }, [excerpt?.document_id]);

  const highlights: PdfHighlight[] = useMemo(() => {
    if (!excerpt?.bbox) return [];
    return [
      {
        id: `${side}-bbox`,
        page: excerpt.page ?? excerpt.bbox.page ?? 1,
        bbox: {
          x: excerpt.bbox.x,
          y: excerpt.bbox.y,
          width: excerpt.bbox.width,
          height: excerpt.bbox.height,
        },
        tone: "danger",
      },
    ];
  }, [excerpt, side]);

  if (!excerpt) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
        <FileText size={24} className="mx-auto mb-2 text-slate-400" />
        <p className="text-sm text-slate-500">Tài liệu {side} không khả dụng</p>
      </div>
    );
  }

  const page = excerpt.page ?? excerpt.bbox?.page ?? 1;

  return (
    <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-sm font-semibold text-slate-900">Tài liệu {side}</span>
        <DisciplineTag discipline={excerpt.discipline} size="sm" />
        {excerpt.drawing_number && (
          <Link
            href={`/drawbridge/documents/${excerpt.document_id}`}
            className="font-mono text-slate-700 hover:underline"
          >
            {excerpt.drawing_number}
          </Link>
        )}
        {excerpt.page != null && <span className="text-slate-500">p.{excerpt.page}</span>}
      </div>
      <blockquote className="rounded-md border-l-2 border-blue-400 bg-slate-50 px-3 py-2 text-xs italic text-slate-700">
        {excerpt.excerpt}
      </blockquote>
      {src ? (
        <PDFViewer src={src} page={page} highlights={highlights} className="w-full" />
      ) : (
        <p className="text-xs text-slate-500">Không thể tải tệp.</p>
      )}
    </div>
  );
}
