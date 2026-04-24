"use client";
import Link from "next/link";
import { useState } from "react";

import { useGenerateReport, useReports } from "@/hooks/siteeye";

import { useSelectedProject } from "../project-context";

function defaultWeek(): { start: string; end: string } {
  const today = new Date();
  const day = today.getDay();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((day + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return {
    start: monday.toISOString().slice(0, 10),
    end: sunday.toISOString().slice(0, 10),
  };
}

export default function ReportListPage() {
  const { projectId } = useSelectedProject();
  const reportsQ = useReports({ project_id: projectId ?? undefined, limit: 30 });
  const gen = useGenerateReport();
  const [{ start, end }, setRange] = useState(defaultWeek);

  if (!projectId) {
    return <p className="text-sm text-gray-600">Select a project first.</p>;
  }

  const reports = reportsQ.data?.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-gray-900">Weekly reports</h1>

      <section className="flex flex-wrap items-end gap-2 rounded-lg border border-gray-200 bg-white p-3">
        <label className="flex flex-col text-xs">
          <span className="text-gray-500">Week start</span>
          <input
            type="date"
            value={start}
            onChange={(e) => setRange((p) => ({ ...p, start: e.target.value }))}
            className="rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col text-xs">
          <span className="text-gray-500">Week end</span>
          <input
            type="date"
            value={end}
            onChange={(e) => setRange((p) => ({ ...p, end: e.target.value }))}
            className="rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <button
          type="button"
          onClick={() =>
            gen.mutate({ project_id: projectId, week_start: start, week_end: end })
          }
          disabled={gen.isPending}
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {gen.isPending ? "Generating…" : "Generate report"}
        </button>
      </section>

      <ul className="divide-y divide-gray-100 overflow-hidden rounded-lg border border-gray-200 bg-white">
        {reports.length === 0 ? (
          <li className="p-6 text-center text-sm text-gray-500">No reports yet.</li>
        ) : null}
        {reports.map((r) => (
          <li key={r.id}>
            <Link
              href={`/siteeye/reports/${r.id}`}
              className="flex items-center justify-between px-4 py-3 hover:bg-gray-50"
            >
              <div>
                <p className="font-medium text-gray-900">
                  {r.week_start} → {r.week_end}
                </p>
                <p className="text-xs text-gray-500">
                  {r.sent_at ? `Sent ${new Date(r.sent_at).toLocaleString()}` : "Not sent"}
                </p>
              </div>
              <span className="text-xs text-sky-600">Open →</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
