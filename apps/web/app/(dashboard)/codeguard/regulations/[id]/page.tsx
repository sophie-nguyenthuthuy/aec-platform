"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft, ExternalLink } from "lucide-react";
import { useRegulation } from "@/hooks/codeguard";

export default function RegulationDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, isLoading, error } = useRegulation(params?.id);

  if (isLoading) return <div className="p-6 text-sm text-slate-500">Đang tải...</div>;
  if (error) return <div className="p-6 text-sm text-red-600">Lỗi: {error.message}</div>;
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
          <div className="p-6 text-sm text-slate-500">Chưa có nội dung đã xử lý.</div>
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
