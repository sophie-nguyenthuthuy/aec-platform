"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, FileText } from "lucide-react";

import { useReviewRevision, useSubmittal } from "@/hooks/submittals";
import type { SubmittalRevision } from "@/hooks/submittals";

const STATUS_BADGE: Record<string, string> = {
  pending_review: "bg-slate-100 text-slate-700",
  under_review: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  approved_as_noted: "bg-emerald-50 text-emerald-700",
  revise_resubmit: "bg-orange-100 text-orange-700",
  rejected: "bg-red-100 text-red-700",
  superseded: "bg-zinc-100 text-zinc-600",
};

function formatDate(d: string | null | undefined): string {
  if (!d) return "—";
  return new Date(d).toLocaleString("vi-VN");
}

export default function SubmittalDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data, isLoading, isError } = useSubmittal(id);

  if (isLoading) return <p className="text-sm text-slate-500">Đang tải...</p>;
  if (isError || !data) {
    return (
      <div className="space-y-3">
        <Link href="/submittals" className="text-sm text-blue-600 hover:underline">
          <ArrowLeft size={14} className="mr-1 inline" /> Quay lại
        </Link>
        <p className="text-sm text-red-600">Không tìm thấy submittal.</p>
      </div>
    );
  }

  const { submittal, revisions } = data;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/submittals"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
        >
          <ArrowLeft size={12} /> Tất cả submittals
        </Link>
        <div className="mt-2 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              {submittal.package_number} — {submittal.title}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              {submittal.submittal_type}
              {submittal.spec_section && ` · Spec ${submittal.spec_section}`}
              {submittal.csi_division && ` · CSI ${submittal.csi_division}`}
              {" · "}Hạn: {submittal.due_date ?? "—"}
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1 text-xs font-medium ${
              STATUS_BADGE[submittal.status] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {submittal.status}
          </span>
        </div>
        {submittal.description && (
          <p className="mt-3 max-w-3xl rounded-md bg-slate-50 p-3 text-sm text-slate-700">
            {submittal.description}
          </p>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">
          Lịch sử revisions ({revisions.length})
        </div>
        {revisions.length === 0 ? (
          <p className="p-6 text-sm text-slate-500">Chưa có revision nào.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {[...revisions]
              .sort((a, b) => b.revision_number - a.revision_number)
              .map((rev) => (
                <RevisionRow
                  key={rev.id}
                  rev={rev}
                  submittalId={submittal.id}
                />
              ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function RevisionRow({
  rev,
  submittalId,
}: {
  rev: SubmittalRevision;
  submittalId: string;
}) {
  const review = useReviewRevision(submittalId);

  return (
    <li className="flex items-start gap-4 px-4 py-3">
      <div className="w-12 shrink-0 rounded bg-slate-100 px-2 py-1 text-center text-xs font-mono">
        R{rev.revision_number}
      </div>
      <div className="flex-1 space-y-1">
        <div className="flex items-baseline justify-between gap-3">
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
              STATUS_BADGE[rev.review_status] ?? "bg-slate-100 text-slate-700"
            }`}
          >
            {rev.review_status}
          </span>
          <span className="text-[11px] text-slate-500">
            {rev.reviewed_at
              ? `Duyệt: ${formatDate(rev.reviewed_at)}`
              : `Tạo: ${formatDate(rev.created_at)}`}
          </span>
        </div>
        {rev.reviewer_notes && (
          <p className="text-xs text-slate-700">{rev.reviewer_notes}</p>
        )}
        {rev.file_id && (
          <p className="inline-flex items-center gap-1 text-xs text-slate-500">
            <FileText size={11} /> File: {rev.file_id.slice(0, 8)}…
          </p>
        )}
        {rev.review_status === "pending_review" && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {[
              { value: "approved", label: "Duyệt" },
              { value: "approved_as_noted", label: "Duyệt + ghi chú" },
              { value: "revise_resubmit", label: "Sửa & nộp lại" },
              { value: "rejected", label: "Từ chối" },
            ].map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={review.isPending}
                onClick={() =>
                  review.mutate({
                    revisionId: rev.id,
                    payload: {
                      review_status: opt.value as Parameters<
                        typeof review.mutate
                      >[0]["payload"]["review_status"],
                    },
                  })
                }
                className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}
