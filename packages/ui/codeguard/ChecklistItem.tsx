"use client";

import { useState } from "react";
import type { ChecklistItem as ChecklistItemType, ChecklistItemStatus } from "./types";

interface ChecklistItemProps {
  item: ChecklistItemType;
  onChange: (patch: { status: ChecklistItemStatus; notes?: string; assignee_id?: string }) => void;
  disabled?: boolean;
}

const STATUS_OPTIONS: Array<{ value: ChecklistItemStatus; label: string }> = [
  { value: "pending", label: "Chưa làm" },
  { value: "in_progress", label: "Đang làm" },
  { value: "done", label: "Hoàn thành" },
  { value: "not_applicable", label: "Không áp dụng" },
];

export function ChecklistItem({ item, onChange, disabled = false }: ChecklistItemProps): JSX.Element {
  const [notesOpen, setNotesOpen] = useState(Boolean(item.notes));
  const [notes, setNotes] = useState(item.notes ?? "");

  const checked = item.status === "done";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) =>
            onChange({ status: e.target.checked ? "done" : "pending", notes })
          }
          className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
        />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className={`font-medium ${checked ? "text-slate-500 line-through" : "text-slate-900"}`}>
              {item.title}
            </h4>
            {item.required && (
              <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
                Bắt buộc
              </span>
            )}
            {item.regulation_ref && (
              <span className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-xs text-slate-600">
                {item.regulation_ref}
              </span>
            )}
          </div>
          {item.description && (
            <p className="mt-1 text-sm text-slate-600">{item.description}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              value={item.status}
              disabled={disabled}
              onChange={(e) => onChange({ status: e.target.value as ChecklistItemStatus, notes })}
              className="rounded border border-slate-300 px-2 py-1 text-xs"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="text-xs text-blue-600 hover:underline"
              onClick={() => setNotesOpen((v) => !v)}
            >
              {notesOpen ? "Ẩn ghi chú" : "Thêm ghi chú"}
            </button>
          </div>
          {notesOpen && (
            <textarea
              value={notes}
              disabled={disabled}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => onChange({ status: item.status, notes })}
              placeholder="Ghi chú..."
              rows={2}
              className="mt-2 w-full rounded border border-slate-300 p-2 text-sm"
            />
          )}
        </div>
      </div>
    </div>
  );
}
