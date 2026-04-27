"use client";

import { useState } from "react";
import { Info, Loader2 } from "lucide-react";
import { ChecklistItem } from "@aec/ui/codeguard";
import type {
  ChecklistItemType,
  PermitChecklist as PermitChecklistType,
} from "@aec/ui/codeguard";
import {
  useCodeguardChecklistStream,
  useMarkChecklistItem,
} from "@/hooks/codeguard";

export default function PermitChecklistPage() {
  const [projectId, setProjectId] = useState("");
  const [jurisdiction, setJurisdiction] = useState("Hồ Chí Minh");
  const [projectType, setProjectType] = useState("residential");
  // `checklist` is set only after the terminal `done` event arrives —
  // it carries the persisted checklist_id which the mark-item flow
  // needs. While streaming, items live in `streamingItems` and the
  // mark-item interactions are disabled (checklist_id not yet known).
  const [checklist, setChecklist] = useState<PermitChecklistType | null>(null);
  const [streamingItems, setStreamingItems] = useState<ChecklistItemType[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startStream = useCodeguardChecklistStream();

  const onGenerate = async () => {
    if (!projectId || streaming) return;
    setError(null);
    setStreamingItems([]);
    setChecklist(null);
    setStreaming(true);

    await startStream(
      {
        project_id: projectId,
        jurisdiction,
        project_type: projectType,
      },
      {
        onItem: (item) => {
          setStreamingItems((curr) => [...curr, item]);
        },
        onDone: (payload) => {
          // Build the canonical PermitChecklist shape from the streamed
          // items + the persisted ids the `done` event carries. This
          // is what enables the mark-item view, which targets
          // `/checks/{checklist_id}/mark-item`.
          setStreamingItems((items) => {
            setChecklist({
              id: payload.checklist_id,
              project_id: projectId || null,
              jurisdiction,
              project_type: projectType,
              items,
              generated_at: payload.generated_at,
              completed_at: null,
            });
            return items;
          });
        },
        onError: (message) => {
          setError(message);
        },
      },
    );
    setStreaming(false);
  };

  const onReset = () => {
    setChecklist(null);
    setStreamingItems([]);
    setError(null);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Checklist cấp phép</h2>
        <p className="text-sm text-slate-600">
          Sinh danh sách hồ sơ cần chuẩn bị theo địa phương và loại công trình.
        </p>
      </div>

      {!checklist && !streaming && (
        <div className="space-y-4">
          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              <div className="mb-1 font-medium">Lỗi khi tạo checklist</div>
              <p>{error}</p>
            </div>
          )}
          <div className="grid gap-4 rounded-xl border border-slate-200 bg-white p-6 md:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Mã dự án</span>
              <input
                type="text"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Địa phương</span>
              <input
                type="text"
                value={jurisdiction}
                onChange={(e) => setJurisdiction(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Loại công trình</span>
              <select
                value={projectType}
                onChange={(e) => setProjectType(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="residential">Nhà ở</option>
                <option value="commercial">Thương mại</option>
                <option value="mixed_use">Hỗn hợp</option>
                <option value="industrial">Công nghiệp</option>
                <option value="public">Công cộng</option>
              </select>
            </label>
            <div className="md:col-span-3 flex justify-end">
              <button
                type="button"
                onClick={onGenerate}
                disabled={!projectId}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Tạo checklist
              </button>
            </div>
          </div>
        </div>
      )}

      {streaming && (
        // Streaming view: items pop in as the LLM emits them. Mark-item
        // checkboxes are intentionally absent because no checklist_id
        // exists yet (the route persists the row only after the LLM
        // finishes). The `done` event hands off to the full
        // ChecklistView below.
        <div className="space-y-4">
          <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
            <Loader2 size={16} className="animate-spin text-blue-600" />
            <span>Đang sinh danh sách... ({streamingItems.length} mục)</span>
          </div>
          <ul className="space-y-2">
            {streamingItems.map((item) => (
              <li
                key={item.id}
                data-testid={`streaming-item-${item.id}`}
                className="rounded-lg border border-slate-200 bg-white p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="font-medium text-slate-900">{item.title}</h4>
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
              </li>
            ))}
          </ul>
        </div>
      )}

      {checklist && <ChecklistView checklist={checklist} onUpdate={setChecklist} onReset={onReset} />}
    </div>
  );
}

function ChecklistView({
  checklist,
  onUpdate,
  onReset,
}: {
  checklist: PermitChecklistType;
  onUpdate: (c: PermitChecklistType) => void;
  onReset: () => void;
}) {
  const markItem = useMarkChecklistItem(checklist.id);
  const [markError, setMarkError] = useState<string | null>(null);

  const done = checklist.items.filter((i) => i.status === "done").length;
  const total = checklist.items.length;
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="font-semibold">
              {checklist.jurisdiction} · {checklist.project_type}
            </h3>
            <p className="text-xs text-slate-500">
              Tạo lúc {new Date(checklist.generated_at).toLocaleString("vi-VN")}
            </p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-slate-900">
              {done}/{total}
            </div>
            <div className="text-xs text-slate-500">{pct}% hoàn thành</div>
          </div>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full bg-blue-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {markError && (
        // Inline banner rather than a toast: stays put until the next
        // successful mark-item (or until the user dismisses it implicitly
        // by clicking "Tạo lại"). Lets the user see exactly which action
        // failed without having to chase a transient notification.
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <div className="mb-1 flex items-center justify-between font-medium">
            <span>Không lưu được trạng thái</span>
            <button
              type="button"
              onClick={() => setMarkError(null)}
              className="text-xs font-normal text-red-700 hover:underline"
            >
              Đóng
            </button>
          </div>
          <p>{markError}</p>
        </div>
      )}

      <div className="space-y-2">
        {/*
          Empty-items advisory: total === 0 means the LLM returned no
          checklist entries. Mirrors the scan page's empty-findings
          treatment — amber Info card rather than a silent empty list,
          since the disambiguation between "valid empty result" and
          "bad LLM output" matters for a permit-prep workflow.
        */}
        {checklist.items.length === 0 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
            <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
              <Info size={14} />
              Checklist trống
            </div>
            <p>
              Hệ thống chưa sinh được mục nào cho địa phương "{checklist.jurisdiction}" và
              loại công trình "{checklist.project_type}". Hãy thử lại với địa phương cụ thể hơn
              hoặc kiểm tra log của hệ thống.
            </p>
          </div>
        ) : (
          checklist.items.map((item) => (
            <ChecklistItem
              key={item.id}
              item={item}
              disabled={markItem.isPending}
              onChange={async (patch) => {
                // Catch at the view level so a failed mark-item produces
                // a visible error banner instead of an unhandled promise
                // rejection in the console. The optimistic-looking
                // checkbox flip in ChecklistItem is purely local; we
                // call onUpdate only on success so the UI rebinds to the
                // server's state of truth.
                setMarkError(null);
                try {
                  const updated = await markItem.mutateAsync({ item_id: item.id, ...patch });
                  onUpdate(updated);
                } catch (err) {
                  const message = err instanceof Error ? err.message : "Đã xảy ra lỗi";
                  setMarkError(message);
                }
              }}
            />
          ))
        )}
      </div>

      <button
        type="button"
        onClick={onReset}
        className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm"
      >
        Tạo lại
      </button>
    </div>
  );
}
