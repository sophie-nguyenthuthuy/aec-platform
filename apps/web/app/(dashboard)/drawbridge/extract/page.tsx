"use client";

import { useMemo, useState } from "react";
import { Download, FileSearch, Play, Ruler } from "lucide-react";

import {
  DisciplineTag,
  ExtractedScheduleTable,
  type Document,
  type ExtractedSchedule,
  type ExtractResponse,
} from "@aec/ui/drawbridge";
import { useSession } from "@/lib/auth-context";
import { useDocuments, useExtract, type ExtractInput } from "@/hooks/drawbridge";

type Target = NonNullable<ExtractInput["target"]>;

const TARGETS: Array<{ key: Target; label: string }> = [
  { key: "all", label: "Tất cả" },
  { key: "schedule", label: "Schedule" },
  { key: "dimensions", label: "Dimensions" },
  { key: "materials", label: "Materials" },
  { key: "title_block", label: "Title block" },
];

export default function ScheduleExtractorPage() {
  const session = useSession();
  const [projectId, setProjectId] = useState<string>(
    (session as { projectId?: string }).projectId ?? "",
  );
  const [selectedId, setSelectedId] = useState<string>("");
  const [target, setTarget] = useState<Target>("all");
  const [pagesInput, setPagesInput] = useState("");
  const [result, setResult] = useState<ExtractResponse | null>(null);

  const { data: docData, isLoading: docsLoading } = useDocuments({
    project_id: projectId || undefined,
    doc_type: "drawing",
    limit: 100,
  });
  const docs = docData?.data ?? [];
  const selectedDoc = useMemo(
    () => docs.find((d) => d.id === selectedId) ?? null,
    [docs, selectedId],
  );

  const extract = useExtract();

  const handleExtract = () => {
    if (!selectedId) return;
    const pages = parsePages(pagesInput);
    extract.mutate(
      {
        document_id: selectedId,
        target,
        pages: pages.length > 0 ? pages : undefined,
      },
      {
        onSuccess: (data) => setResult(data),
      },
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-slate-900">Trích xuất dữ liệu</h2>
        <div className="ml-auto">
          <input
            placeholder="project_id"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto]">
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Bản vẽ</span>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              disabled={!projectId || docsLoading}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">
                {docsLoading ? "Đang tải..." : "— Chọn bản vẽ —"}
              </option>
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {[d.drawing_number, d.title ?? "(không tiêu đề)"].filter(Boolean).join(" · ")}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Mục tiêu</span>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value as Target)}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {TARGETS.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-slate-600">Trang (vd: 1,3-5)</span>
            <input
              value={pagesInput}
              onChange={(e) => setPagesInput(e.target.value)}
              placeholder="Tất cả"
              className="w-32 rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <div className="flex items-end">
            <button
              type="button"
              disabled={!selectedId || extract.isPending}
              onClick={handleExtract}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              <Play size={14} />
              {extract.isPending ? "Đang trích xuất..." : "Trích xuất"}
            </button>
          </div>
        </div>

        {selectedDoc && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
            {selectedDoc.drawing_number && (
              <span className="font-mono text-slate-800">{selectedDoc.drawing_number}</span>
            )}
            <span className="text-slate-700">{selectedDoc.title ?? "(Không tiêu đề)"}</span>
            <DisciplineTag discipline={selectedDoc.discipline} size="sm" />
            <StatusPill doc={selectedDoc} />
          </div>
        )}

        {extract.error && (
          <p className="mt-3 text-sm text-red-600">
            {extract.error instanceof Error ? extract.error.message : "Lỗi không xác định"}
          </p>
        )}
      </section>

      {!result && !extract.isPending && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <FileSearch size={28} className="mx-auto mb-3 text-slate-400" />
          <p className="text-sm text-slate-500">
            Chọn một bản vẽ và bấm "Trích xuất" để lấy schedule, dimension, material.
          </p>
        </div>
      )}

      {result && (
        <ResultView result={result} />
      )}
    </div>
  );
}

function ResultView({ result }: { result: ExtractResponse }) {
  return (
    <div className="space-y-5">
      {result.title_block && Object.keys(result.title_block).length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-900">Title block</h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs md:grid-cols-3">
            {Object.entries(result.title_block).map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-slate-100 py-1">
                <dt className="text-slate-500">{k}</dt>
                <dd className="font-medium text-slate-800">{formatValue(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {result.schedules.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Schedules ({result.schedules.length})
          </h3>
          {result.schedules.map((s, i) => (
            <ExtractedScheduleTable
              key={`${s.name}-${i}`}
              schedule={s}
              onExportCsv={downloadScheduleCsv}
            />
          ))}
        </section>
      )}

      {result.dimensions.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white">
          <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
            <h3 className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <Ruler size={14} /> Dimensions ({result.dimensions.length})
            </h3>
          </header>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Nhãn</th>
                <th className="px-3 py-2 text-left font-medium">Giá trị (mm)</th>
                <th className="px-3 py-2 text-left font-medium">Gốc</th>
                <th className="px-3 py-2 text-left font-medium">Trang</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {result.dimensions.map((d, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-1.5 text-slate-800">{d.label}</td>
                  <td className="px-3 py-1.5 font-mono text-slate-800">
                    {d.value_mm != null ? d.value_mm.toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-slate-600">{d.raw}</td>
                  <td className="px-3 py-1.5 text-slate-500">{d.page ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {result.materials.length > 0 && (
        <section className="rounded-xl border border-slate-200 bg-white">
          <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
            <h3 className="text-sm font-semibold text-slate-900">
              Materials ({result.materials.length})
            </h3>
            <button
              type="button"
              onClick={() => downloadMaterialsCsv(result.materials)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <Download size={12} /> CSV
            </button>
          </header>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Mã</th>
                <th className="px-3 py-2 text-left font-medium">Mô tả</th>
                <th className="px-3 py-2 text-left font-medium">Khối lượng</th>
                <th className="px-3 py-2 text-left font-medium">Đơn vị</th>
                <th className="px-3 py-2 text-left font-medium">Trang</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {result.materials.map((m, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-3 py-1.5 font-mono text-slate-800">{m.code ?? "—"}</td>
                  <td className="px-3 py-1.5 text-slate-800">{m.description}</td>
                  <td className="px-3 py-1.5 text-slate-800">
                    {m.quantity != null ? m.quantity.toLocaleString() : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-slate-600">{m.unit ?? "—"}</td>
                  <td className="px-3 py-1.5 text-slate-500">{m.page ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {result.schedules.length === 0 &&
        result.dimensions.length === 0 &&
        result.materials.length === 0 &&
        !result.title_block && (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
            <p className="text-sm text-slate-500">Không tìm thấy dữ liệu để trích xuất.</p>
          </div>
        )}
    </div>
  );
}

function StatusPill({ doc }: { doc: Document }) {
  const styles: Record<Document["processing_status"], string> = {
    pending: "bg-slate-200 text-slate-700",
    processing: "bg-blue-100 text-blue-800",
    ready: "bg-emerald-100 text-emerald-800",
    failed: "bg-red-100 text-red-700",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[doc.processing_status]}`}>
      {doc.processing_status}
    </span>
  );
}

function parsePages(input: string): number[] {
  const out = new Set<number>();
  for (const chunk of input.split(",")) {
    const part = chunk.trim();
    if (!part) continue;
    const range = part.match(/^(\d+)\s*-\s*(\d+)$/);
    if (range) {
      // The regex above guarantees both groups are present.
      const start = parseInt(range[1]!, 10);
      const end = parseInt(range[2]!, 10);
      if (Number.isFinite(start) && Number.isFinite(end)) {
        for (let i = Math.min(start, end); i <= Math.max(start, end); i++) out.add(i);
      }
    } else {
      const n = parseInt(part, 10);
      if (Number.isFinite(n)) out.add(n);
    }
  }
  return Array.from(out).sort((a, b) => a - b);
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function csvEscape(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function triggerDownload(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function downloadScheduleCsv(schedule: ExtractedSchedule) {
  const header = schedule.columns.map(csvEscape).join(",");
  const rows = schedule.rows
    .map((r) => schedule.columns.map((c) => csvEscape(r.cells[c])).join(","))
    .join("\n");
  const csv = [header, rows].filter(Boolean).join("\n");
  triggerDownload(csv, `${schedule.name.replace(/[^a-z0-9-_]+/gi, "_")}.csv`);
}

function downloadMaterialsCsv(materials: ExtractResponse["materials"]) {
  const header = ["code", "description", "quantity", "unit", "page"].join(",");
  const rows = materials
    .map((m) =>
      [m.code, m.description, m.quantity, m.unit, m.page].map(csvEscape).join(","),
    )
    .join("\n");
  triggerDownload([header, rows].filter(Boolean).join("\n"), "materials.csv");
}
