"use client";

import Link from "next/link";
import { useState } from "react";
import { RegulationSearch } from "@aec/ui/codeguard";
import type { RegulationCategory } from "@aec/ui/codeguard";
import { useRegulations } from "@/hooks/codeguard";

const CATEGORY_LABELS: Record<RegulationCategory, string> = {
  fire_safety: "PCCC",
  accessibility: "Tiếp cận",
  structure: "Kết cấu",
  zoning: "Quy hoạch",
  energy: "Năng lượng",
};

export default function RegulationBrowserPage() {
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<RegulationCategory | "">("");
  const { data, isLoading } = useRegulations({
    q: q || undefined,
    category: category || undefined,
    limit: 50,
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Thư viện quy chuẩn</h2>
        <p className="text-sm text-slate-600">
          Tra cứu QCVN, TCVN, luật xây dựng và các văn bản pháp quy.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[280px] flex-1">
          <RegulationSearch onSearch={setQ} defaultValue={q} loading={isLoading} />
        </div>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as RegulationCategory | "")}
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">Tất cả hạng mục</option>
          {Object.entries(CATEGORY_LABELS).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white">
        {isLoading && !data ? (
          <div className="p-8 text-center text-sm text-slate-500">Đang tải...</div>
        ) : !data || data.data.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">Không có kết quả.</div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.data.map((r) => (
              <li key={r.id}>
                <Link
                  href={`/codeguard/regulations/${r.id}`}
                  className="block px-4 py-3 hover:bg-slate-50"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-medium text-slate-900">{r.code_name}</div>
                      <div className="text-xs text-slate-500">
                        {r.jurisdiction ?? r.country_code}
                        {r.effective_date && ` · Hiệu lực ${r.effective_date}`}
                      </div>
                    </div>
                    {r.category && (
                      <span className="rounded border border-slate-300 bg-slate-50 px-2 py-0.5 text-xs text-slate-700">
                        {CATEGORY_LABELS[r.category]}
                      </span>
                    )}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
