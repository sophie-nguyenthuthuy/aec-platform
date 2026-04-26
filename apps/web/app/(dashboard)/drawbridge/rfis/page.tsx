"use client";

import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";

import { RFICard, type Rfi, type RfiPriority, type RfiStatus } from "@aec/ui/drawbridge";
import { useSession } from "@/lib/auth-context";
import { useAnswerRFI, useCreateRFI, useRFIs } from "@/hooks/drawbridge";

const COLUMNS: Array<{ key: RfiStatus; label: string; tone: string }> = [
  { key: "open", label: "Đang mở", tone: "bg-blue-50 border-blue-200" },
  { key: "answered", label: "Đã trả lời", tone: "bg-amber-50 border-amber-200" },
  { key: "closed", label: "Đã đóng", tone: "bg-slate-50 border-slate-200" },
];

const PRIORITIES: RfiPriority[] = ["low", "normal", "high", "urgent"];

export default function RFITrackerPage() {
  const session = useSession();
  const [projectId, setProjectId] = useState<string>(
    (session as { projectId?: string }).projectId ?? "",
  );
  const [priorityFilter, setPriorityFilter] = useState<RfiPriority | "">("");
  const [creatorOpen, setCreatorOpen] = useState(false);
  const [answerTarget, setAnswerTarget] = useState<Rfi | null>(null);

  const { data, isLoading } = useRFIs({
    project_id: projectId,
    priority: priorityFilter || undefined,
    limit: 200,
  });

  // useMemo so identity is stable for the grouped useMemo below.
  const list = useMemo(() => data?.data ?? [], [data]);

  const grouped = useMemo(() => {
    const g: Record<RfiStatus, Rfi[]> = { open: [], answered: [], closed: [] };
    for (const r of list) g[r.status].push(r);
    return g;
  }, [list]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-slate-900">RFI tracker</h2>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            placeholder="project_id"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          />
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value as RfiPriority | "")}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Mọi mức độ</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!projectId}
            onClick={() => setCreatorOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            <Plus size={14} /> Tạo RFI
          </button>
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">Đang tải...</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {COLUMNS.map((col) => (
            <section
              key={col.key}
              className={`flex flex-col rounded-xl border ${col.tone} p-3`}
            >
              <header className="mb-3 flex items-center justify-between px-1">
                <h3 className="text-sm font-semibold text-slate-800">{col.label}</h3>
                <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-slate-700">
                  {grouped[col.key].length}
                </span>
              </header>
              <div className="flex flex-1 flex-col gap-2">
                {grouped[col.key].length === 0 ? (
                  <p className="py-8 text-center text-xs text-slate-400">Trống</p>
                ) : (
                  grouped[col.key].map((rfi) => (
                    <RFICard
                      key={rfi.id}
                      rfi={rfi}
                      onAnswer={(r) => setAnswerTarget(r)}
                    />
                  ))
                )}
              </div>
            </section>
          ))}
        </div>
      )}

      {creatorOpen && projectId && (
        <CreateRfiDialog
          projectId={projectId}
          onClose={() => setCreatorOpen(false)}
        />
      )}
      {answerTarget && (
        <AnswerRfiDialog rfi={answerTarget} onClose={() => setAnswerTarget(null)} />
      )}
    </div>
  );
}

function CreateRfiDialog({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const create = useCreateRFI();
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<RfiPriority>("normal");
  const [dueDate, setDueDate] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim()) return;
    create.mutate(
      {
        project_id: projectId,
        subject: subject.trim(),
        description: description.trim() || undefined,
        priority,
        due_date: dueDate || undefined,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <DialogShell title="Tạo RFI mới" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Tiêu đề *">
          <input
            required
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </Field>
        <Field label="Mô tả">
          <textarea
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mức độ">
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as RfiPriority)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Hạn chót">
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </Field>
        </div>
        {create.error && (
          <p className="text-xs text-red-600">
            {create.error instanceof Error ? create.error.message : "Lỗi không xác định"}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Huỷ
          </button>
          <button
            type="submit"
            disabled={create.isPending || !subject.trim()}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {create.isPending ? "Đang tạo..." : "Tạo"}
          </button>
        </div>
      </form>
    </DialogShell>
  );
}

function AnswerRfiDialog({ rfi, onClose }: { rfi: Rfi; onClose: () => void }) {
  const answer = useAnswerRFI();
  const [response, setResponse] = useState("");
  const [close, setClose] = useState(true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!response.trim()) return;
    answer.mutate(
      { id: rfi.id, response: response.trim(), close },
      { onSuccess: onClose },
    );
  };

  return (
    <DialogShell title={`Trả lời ${rfi.number ?? "RFI"}`} onClose={onClose}>
      <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
        <div className="font-semibold text-slate-900">{rfi.subject}</div>
        {rfi.description && (
          <p className="mt-1 whitespace-pre-wrap text-slate-600">{rfi.description}</p>
        )}
      </div>
      <form onSubmit={handleSubmit} className="space-y-3">
        <Field label="Phản hồi *">
          <textarea
            required
            rows={6}
            value={response}
            onChange={(e) => setResponse(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </Field>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={close}
            onChange={(e) => setClose(e.target.checked)}
          />
          Đóng RFI sau khi trả lời
        </label>
        {answer.error && (
          <p className="text-xs text-red-600">
            {answer.error instanceof Error ? answer.error.message : "Lỗi không xác định"}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Huỷ
          </button>
          <button
            type="submit"
            disabled={answer.isPending || !response.trim()}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {answer.isPending ? "Đang gửi..." : "Gửi phản hồi"}
          </button>
        </div>
      </form>
    </DialogShell>
  );
}

function DialogShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100"
          >
            <X size={16} />
          </button>
        </header>
        <div className="px-4 py-4">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}
