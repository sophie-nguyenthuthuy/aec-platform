"use client";
import { useState } from "react";
import Link from "next/link";
import { useTenders } from "@/hooks/bidradar";

export default function AllTendersPage() {
  const [q, setQ] = useState("");
  const [province, setProvince] = useState("");
  const [discipline, setDiscipline] = useState("");
  const { data, isLoading } = useTenders({
    q: q || undefined,
    province: province || undefined,
    discipline: discipline || undefined,
  });

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">All scraped tenders</h2>
        <p className="text-sm text-slate-500">
          {data?.total ?? 0} opportunities across sources
        </p>
      </div>

      <div className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-3">
        <input
          className="flex-1 min-w-48 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          placeholder="Search title, issuer, description…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <input
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          placeholder="Province"
          value={province}
          onChange={(e) => setProvince(e.target.value)}
        />
        <input
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          placeholder="Discipline"
          value={discipline}
          onChange={(e) => setDiscipline(e.target.value)}
        />
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Title</th>
              <th className="px-4 py-2">Issuer</th>
              <th className="px-4 py-2">Province</th>
              <th className="px-4 py-2">Budget (VND)</th>
              <th className="px-4 py-2">Deadline</th>
              <th className="px-4 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                  No tenders match your filters.
                </td>
              </tr>
            ) : (
              items.map((t) => (
                <tr key={t.id} className="border-t border-slate-100">
                  <td className="px-4 py-2">
                    <Link
                      href={`/bidradar/tenders/${t.id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {t.title}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{t.issuer ?? "—"}</td>
                  <td className="px-4 py-2 text-slate-600">{t.province ?? "—"}</td>
                  <td className="px-4 py-2 tabular-nums text-slate-600">
                    {t.budget_vnd ? t.budget_vnd.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {t.submission_deadline
                      ? new Date(t.submission_deadline).toLocaleDateString()
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-500">{t.source}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
