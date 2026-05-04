"use client";

import Link from "next/link";
import { useState } from "react";
import { Info } from "lucide-react";
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
  const { data, isLoading, isError, error } = useRegulations({
    q: q || undefined,
    category: category || undefined,
    limit: 50,
  });

  // The empty state differs by whether the user has actively narrowed
  // the corpus: filtered empty → amber advisory ("nothing matched
  // YOUR filter"); unfiltered empty → neutral hint ("library is empty,
  // run `make seed-codeguard`"). Without this split a filter that
  // returns nothing looks identical to a misconfigured deployment.
  const hasFilter = Boolean(q) || Boolean(category);

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
          aria-label="Lọc theo hạng mục"
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

      {isError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <div className="mb-1 font-medium">Lỗi khi tải thư viện quy chuẩn</div>
          <p>{error instanceof Error ? error.message : "Đã xảy ra lỗi"}</p>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white">
        {isLoading && !data ? (
          <div className="p-8 text-center text-sm text-slate-500">Đang tải...</div>
        ) : !data || data.data.length === 0 ? (
          hasFilter ? (
            // Filtered empty: user typed/filtered and nothing matched.
            // Amber Info card matches the abstain treatment elsewhere.
            <div className="m-4 rounded-lg border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
              <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
                <Info size={14} />
                Không có kết quả phù hợp
              </div>
              <p>
                Không có quy chuẩn nào khớp với bộ lọc hiện tại. Hãy thử bỏ một
                điều kiện hoặc dùng từ khóa khác.
              </p>
            </div>
          ) : (
            // Unfiltered empty: corpus itself is empty. Neutral hint
            // pointing to the seed step — distinguishes a fresh install
            // from a filter-driven empty result.
            <div className="p-8 text-center text-sm text-slate-500">
              Thư viện chưa có quy chuẩn nào. Chạy <code>make seed-codeguard</code>{" "}
              hoặc dùng pipeline ingest để nạp dữ liệu.
            </div>
          )
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
