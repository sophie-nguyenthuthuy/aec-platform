"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft, ExternalLink, Info } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useRegulation } from "@/hooks/codeguard";

export default function RegulationDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, isLoading, error } = useRegulation(params?.id);

  if (isLoading) return <div className="p-6 text-sm text-slate-500">Đang tải...</div>;

  if (error) {
    // 404 vs other errors: 404 is "regulation doesn't exist" (or was
    // deleted) — render a neutral "not found" page with a back link;
    // other errors get the red-banner treatment matching the rest of
    // the module.
    const is404 = error instanceof ApiError && error.status === 404;
    return (
      <div className="space-y-6">
        <Link
          href="/codeguard/regulations"
          className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
        >
          <ChevronLeft size={14} /> Quay lại thư viện
        </Link>
        {is404 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
            <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
              <Info size={14} />
              Không tìm thấy quy chuẩn
            </div>
            <p>
              Quy chuẩn này không tồn tại hoặc đã bị xóa khỏi thư viện. Hãy
              quay lại thư viện và chọn một mục khác.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
            <div className="mb-1 font-medium">Lỗi khi tải quy chuẩn</div>
            <p>{error.message}</p>
          </div>
        )}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      <Link
        href="/codeguard/regulations"
        className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
      >
        <ChevronLeft size={14} /> Quay lại thư viện
      </Link>

      <header className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{data.code_name}</h1>
            <p className="mt-1 text-sm text-slate-600">
              {data.jurisdiction ?? data.country_code}
              {data.effective_date && ` · Hiệu lực ${data.effective_date}`}
              {data.expiry_date && ` · Hết hiệu lực ${data.expiry_date}`}
            </p>
          </div>
          {data.source_url && (
            <a
              href={data.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline"
            >
              Nguồn <ExternalLink size={14} />
            </a>
          )}
        </div>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white">
        <h2 className="border-b border-slate-100 px-6 py-3 text-sm font-semibold text-slate-900">
          Nội dung ({data.sections.length} mục)
        </h2>
        {data.sections.length === 0 ? (
          // Empty sections is the same disambiguation problem as
          // empty findings on the scan page: could mean "regulation
          // exists but ingest didn't extract sections" (a real
          // operational issue worth flagging) rather than "all clear."
          // Amber advisory matches the pattern across the module.
          <div className="m-4 rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
            <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
              <Info size={14} />
              Chưa có nội dung đã xử lý
            </div>
            <p>
              Quy chuẩn này tồn tại nhưng chưa có nội dung được phân tách
              thành mục. Hãy chạy lại pipeline ingest cho mã này.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.sections.map((s, i) => (
              <li key={i} className="px-6 py-4">
                <div className="mb-1 text-sm font-semibold text-slate-900">
                  {s.section_ref}
                  {s.title && <span className="ml-2 text-slate-600">{s.title}</span>}
                </div>
                <p className="whitespace-pre-wrap text-sm text-slate-700">{s.content}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
