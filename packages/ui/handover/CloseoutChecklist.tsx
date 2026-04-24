"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type {
  CloseoutCategory,
  CloseoutItem,
  CloseoutStatus,
} from "./types";

interface CloseoutChecklistProps {
  items: CloseoutItem[];
  onChange: (
    itemId: string,
    patch: { status?: CloseoutStatus; notes?: string },
  ) => void;
  pendingItemId?: string | null;
}

const CATEGORY_LABEL: Record<CloseoutCategory, string> = {
  drawings: "Bản vẽ hoàn công",
  documents: "Hồ sơ pháp lý",
  certificates: "Chứng chỉ & nghiệm thu",
  warranties: "Bảo hành",
  manuals: "Hướng dẫn vận hành",
  permits: "Giấy phép",
  testing: "Kiểm định & thử nghiệm",
  other: "Khác",
};

const STATUS_OPTIONS: Array<{ value: CloseoutStatus; label: string }> = [
  { value: "pending", label: "Chưa làm" },
  { value: "in_progress", label: "Đang làm" },
  { value: "done", label: "Hoàn thành" },
  { value: "not_applicable", label: "Không áp dụng" },
];

export function CloseoutChecklist({
  items,
  onChange,
  pendingItemId,
}: CloseoutChecklistProps): JSX.Element {
  const grouped = groupByCategory(items);
  const categories = Object.keys(grouped) as CloseoutCategory[];

  return (
    <div className="space-y-3">
      {categories.map((cat) => (
        <CategoryGroup
          key={cat}
          category={cat}
          items={grouped[cat] ?? []}
          onChange={onChange}
          pendingItemId={pendingItemId}
        />
      ))}
    </div>
  );
}

function CategoryGroup({
  category,
  items,
  onChange,
  pendingItemId,
}: {
  category: CloseoutCategory;
  items: CloseoutItem[];
  onChange: CloseoutChecklistProps["onChange"];
  pendingItemId?: string | null;
}): JSX.Element {
  const [open, setOpen] = useState(true);
  const done = items.filter((i) => i.status === "done").length;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-slate-50"
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="font-medium text-slate-900">
            {CATEGORY_LABEL[category]}
          </span>
        </div>
        <span className="text-xs text-slate-500">
          {done}/{items.length}
        </span>
      </button>
      {open && (
        <div className="divide-y divide-slate-100 border-t border-slate-100">
          {items.map((item) => (
            <Row
              key={item.id}
              item={item}
              onChange={onChange}
              pending={pendingItemId === item.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Row({
  item,
  onChange,
  pending,
}: {
  item: CloseoutItem;
  onChange: CloseoutChecklistProps["onChange"];
  pending: boolean;
}): JSX.Element {
  const [notes, setNotes] = useState(item.notes ?? "");
  const [notesOpen, setNotesOpen] = useState(Boolean(item.notes));
  const checked = item.status === "done";

  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <input
        type="checkbox"
        checked={checked}
        disabled={pending}
        onChange={(e) =>
          onChange(item.id, {
            status: e.target.checked ? "done" : "pending",
            notes,
          })
        }
        className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
      />
      <div className="flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`text-sm font-medium ${
              checked ? "text-slate-500 line-through" : "text-slate-900"
            }`}
          >
            {item.title}
          </span>
          {item.required && (
            <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">
              Bắt buộc
            </span>
          )}
        </div>
        {item.description && (
          <p className="mt-1 text-xs text-slate-600">{item.description}</p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            value={item.status}
            disabled={pending}
            onChange={(e) =>
              onChange(item.id, {
                status: e.target.value as CloseoutStatus,
                notes,
              })
            }
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
          {item.file_ids.length > 0 && (
            <span className="text-xs text-slate-500">
              {item.file_ids.length} tệp đính kèm
            </span>
          )}
        </div>
        {notesOpen && (
          <textarea
            value={notes}
            disabled={pending}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => onChange(item.id, { notes })}
            placeholder="Ghi chú..."
            rows={2}
            className="mt-2 w-full rounded border border-slate-300 p-2 text-sm"
          />
        )}
      </div>
    </div>
  );
}

function groupByCategory(
  items: CloseoutItem[],
): Partial<Record<CloseoutCategory, CloseoutItem[]>> {
  const result: Partial<Record<CloseoutCategory, CloseoutItem[]>> = {};
  for (const item of items) {
    const arr = result[item.category] ?? [];
    arr.push(item);
    result[item.category] = arr;
  }
  return result;
}
