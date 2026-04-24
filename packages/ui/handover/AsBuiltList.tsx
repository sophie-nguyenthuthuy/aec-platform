"use client";

import { useState } from "react";
import { FileText, History } from "lucide-react";
import type { AsBuiltDrawing, Discipline } from "./types";

interface AsBuiltListProps {
  drawings: AsBuiltDrawing[];
  onDownload?: (fileId: string) => void;
}

const DISCIPLINE_LABEL: Record<Discipline, string> = {
  architecture: "Kiến trúc",
  structure: "Kết cấu",
  mep: "Cơ điện",
  electrical: "Điện",
  plumbing: "Cấp thoát nước",
  hvac: "Điều hòa",
  fire: "Phòng cháy",
  landscape: "Cảnh quan",
  interior: "Nội thất",
};

export function AsBuiltList({
  drawings,
  onDownload,
}: AsBuiltListProps): JSX.Element {
  if (drawings.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        Chưa có bản vẽ hoàn công nào được đăng ký.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {drawings.map((d) => (
        <DrawingRow key={d.id} drawing={d} onDownload={onDownload} />
      ))}
    </div>
  );
}

function DrawingRow({
  drawing,
  onDownload,
}: {
  drawing: AsBuiltDrawing;
  onDownload?: (fileId: string) => void;
}): JSX.Element {
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="flex items-start gap-3">
          <FileText className="mt-0.5 text-blue-600" size={20} />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold text-slate-900">
                {drawing.drawing_code}
              </span>
              <span className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-xs text-slate-600">
                {DISCIPLINE_LABEL[drawing.discipline]}
              </span>
              <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800">
                v{drawing.current_version}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-700">{drawing.title}</p>
            <p className="mt-0.5 text-xs text-slate-500">
              Cập nhật {new Date(drawing.last_updated_at).toLocaleString("vi-VN")}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {drawing.changelog.length > 1 && (
            <button
              type="button"
              onClick={() => setHistoryOpen((v) => !v)}
              className="flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              <History size={12} />
              {drawing.changelog.length} phiên bản
            </button>
          )}
          {drawing.current_file_id && onDownload && (
            <button
              type="button"
              onClick={() => onDownload(drawing.current_file_id as string)}
              className="rounded bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700"
            >
              Tải về
            </button>
          )}
        </div>
      </div>
      {historyOpen && drawing.changelog.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50 px-4 py-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Lịch sử phiên bản
          </h4>
          <ul className="space-y-1.5">
            {[...drawing.changelog]
              .sort((a, b) => b.version - a.version)
              .map((entry) => (
                <li
                  key={`${entry.version}-${entry.file_id}`}
                  className="flex items-start gap-2 text-xs"
                >
                  <span className="mt-0.5 rounded bg-slate-200 px-1.5 py-0.5 font-mono text-slate-700">
                    v{entry.version}
                  </span>
                  <div className="flex-1">
                    <div className="text-slate-700">
                      {entry.change_note ?? "(không có ghi chú thay đổi)"}
                    </div>
                    <div className="text-slate-500">
                      {new Date(entry.recorded_at).toLocaleString("vi-VN")}
                    </div>
                  </div>
                  {onDownload && (
                    <button
                      type="button"
                      onClick={() => onDownload(entry.file_id)}
                      className="text-blue-600 hover:underline"
                    >
                      Tải
                    </button>
                  )}
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
