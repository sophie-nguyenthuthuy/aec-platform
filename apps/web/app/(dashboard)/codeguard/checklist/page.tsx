"use client";

import { useState } from "react";
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

  const generate = useGeneratePermitChecklist();

  const onGenerate = async () => {
    const res = await generate.mutateAsync({
      project_id: projectId,
      jurisdiction,
      project_type: projectType,
    });
    setChecklist(res);
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
      )}

      {checklist && <ChecklistView checklist={checklist} onUpdate={setChecklist} />}
    </div>
  );
}

function ChecklistView({
  checklist,
  onUpdate,
}: {
  checklist: PermitChecklistType;
  onUpdate: (c: PermitChecklistType) => void;
}) {
  const markItem = useMarkChecklistItem(checklist.id);

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

      <div className="space-y-2">
        {checklist.items.map((item) => (
          <ChecklistItem
            key={item.id}
            item={item}
            disabled={markItem.isPending}
            onChange={async (patch) => {
              const updated = await markItem.mutateAsync({ item_id: item.id, ...patch });
              onUpdate(updated);
            }}
          />
        ))}
      </div>
    </div>
  );
}
