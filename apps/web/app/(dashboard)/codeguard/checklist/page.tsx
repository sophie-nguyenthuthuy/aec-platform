"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { ChecklistItem } from "@aec/ui/codeguard";
import type { PermitChecklist as PermitChecklistType } from "@aec/ui/codeguard";
import {
  useGeneratePermitChecklist,
  useMarkChecklistItem,
} from "@/hooks/codeguard";

export default function PermitChecklistPage() {
  const [projectId, setProjectId] = useState("");
  const [jurisdiction, setJurisdiction] = useState("Hồ Chí Minh");
  const [projectType, setProjectType] = useState("residential");
  const [checklist, setChecklist] = useState<PermitChecklistType | null>(null);
  const [error, setError] = useState<string | null>(null);

  const generate = useGeneratePermitChecklist();

  const onGenerate = async () => {
    // Mirror the query/scan pages' error-handling shape: catch the
    // rejection, surface a red banner where the form was, but leave the
    // form filled so the user can retry without re-typing.
    setError(null);
    try {
      const res = await generate.mutateAsync({
        project_id: projectId,
        jurisdiction,
        project_type: projectType,
      });
      setChecklist(res);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Đã xảy ra lỗi";
      setError(message);
    }
  };

  const onReset = () => {
    setChecklist(null);
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

      {!checklist && (
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
                disabled={!projectId || generate.isPending}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {generate.isPending ? "Đang tạo..." : "Tạo checklist"}
              </button>
            </div>
          </div>
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
