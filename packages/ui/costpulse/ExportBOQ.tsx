"use client";

import type { BoqItem, EstimateSummary } from "@aec/types";

import { Button } from "../primitives/button";
import { formatVnd } from "./formatters";

interface ExportBOQProps {
  estimate: EstimateSummary;
  items: BoqItem[];
  className?: string;
}

function toCsv(items: BoqItem[]): string {
  const header = ["Code", "Description", "Unit", "Quantity", "Unit Price (VND)", "Total (VND)", "Material Code", "Notes"];
  const rows = items
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((i) =>
      [
        i.code ?? "",
        i.description.replaceAll('"', '""'),
        i.unit ?? "",
        i.quantity ?? "",
        i.unit_price_vnd ?? "",
        i.total_price_vnd ?? "",
        i.material_code ?? "",
        (i.notes ?? "").replaceAll('"', '""'),
      ]
        .map((cell) => `"${cell}"`)
        .join(","),
    );
  return [header.map((h) => `"${h}"`).join(","), ...rows].join("\n");
}

export function ExportBOQ({ estimate, items, className }: ExportBOQProps): JSX.Element {
  function download(filename: string, content: string, type: string) {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportCsv() {
    const safeName = estimate.name.replaceAll(/\s+/g, "_");
    download(`${safeName}_v${estimate.version}.csv`, toCsv(items), "text/csv;charset=utf-8");
  }

  function exportHtmlAsPdf() {
    const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order);
    const rows = sorted
      .map(
        (i) => `<tr>
          <td>${i.code ?? ""}</td>
          <td>${escapeHtml(i.description)}</td>
          <td>${i.unit ?? ""}</td>
          <td style="text-align:right">${i.quantity ?? ""}</td>
          <td style="text-align:right">${formatVnd(i.unit_price_vnd)}</td>
          <td style="text-align:right">${formatVnd(i.total_price_vnd)}</td>
        </tr>`,
      )
      .join("");
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(estimate.name)}</title>
      <style>body{font-family:sans-serif;padding:24px}table{width:100%;border-collapse:collapse}
      th,td{border:1px solid #ccc;padding:6px 8px;font-size:12px}th{background:#f5f5f5}</style></head>
      <body><h1>${escapeHtml(estimate.name)} — v${estimate.version}</h1>
      <p>Total: <strong>${formatVnd(estimate.total_vnd)}</strong></p>
      <table><thead><tr><th>Code</th><th>Description</th><th>Unit</th><th>Qty</th><th>Unit price</th><th>Total</th></tr></thead>
      <tbody>${rows}</tbody></table></body></html>`;
    const w = window.open("", "_blank");
    if (w) {
      w.document.write(html);
      w.document.close();
      w.print();
    }
  }

  return (
    <div className={className}>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={exportCsv}>
          Export CSV (Excel)
        </Button>
        <Button size="sm" variant="outline" onClick={exportHtmlAsPdf}>
          Print / PDF
        </Button>
      </div>
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
