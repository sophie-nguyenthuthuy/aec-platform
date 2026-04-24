"use client";

import { useState } from "react";
import { Send } from "lucide-react";

import { DisciplineTag, type QueryResponse } from "@aec/ui/drawbridge";
import { useSession } from "@/lib/auth-context";
import { useDrawbridgeQuery } from "@/hooks/drawbridge";

interface Turn {
  role: "user" | "assistant";
  text: string;
  response?: QueryResponse;
}

export default function DrawingChatPage() {
  const session = useSession();
  const [projectId, setProjectId] = useState<string>((session as { projectId?: string }).projectId ?? "");
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const mutation = useDrawbridgeQuery();

  const submit = async () => {
    const question = input.trim();
    if (!question || !projectId || mutation.isPending) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", text: question }]);
    try {
      const response = await mutation.mutateAsync({ project_id: projectId, question });
      setTurns((t) => [...t, { role: "assistant", text: response.answer, response }]);
    } catch (err) {
      setTurns((t) => [
        ...t,
        { role: "assistant", text: `Lỗi: ${err instanceof Error ? err.message : "unknown"}` },
      ]);
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <div className="flex items-center gap-2">
        <input
          placeholder="project_id"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        />
      </div>

      <div className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-6">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-slate-500">
            <h2 className="text-xl font-semibold text-slate-800">Hỏi bất cứ điều gì về bản vẽ dự án</h2>
            <p className="mt-2 max-w-md text-sm">
              Ví dụ: "Độ dày sàn tầng 3 là bao nhiêu?" hoặc "Liệt kê toàn bộ vật liệu trong schedule M2".
            </p>
          </div>
        ) : (
          <ul className="space-y-6">
            {turns.map((t, i) => (
              <li key={i} className={t.role === "user" ? "text-right" : ""}>
                {t.role === "user" ? (
                  <div className="inline-block max-w-[80%] rounded-2xl bg-blue-600 px-4 py-2 text-left text-sm text-white">
                    {t.text}
                  </div>
                ) : (
                  <AssistantTurn text={t.text} response={t.response} />
                )}
              </li>
            ))}
            {mutation.isPending && (
              <li className="text-sm text-slate-500">Đang đọc bản vẽ...</li>
            )}
          </ul>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex gap-2 rounded-xl border border-slate-200 bg-white p-3"
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Đặt câu hỏi về bản vẽ, dimension, material, schedule..."
          disabled={mutation.isPending || !projectId}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={mutation.isPending || !input.trim() || !projectId}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Send size={14} />
          Gửi
        </button>
      </form>
    </div>
  );
}

function AssistantTurn({ text, response }: { text: string; response?: QueryResponse }) {
  return (
    <div className="inline-block max-w-full rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-900">
      <p className="whitespace-pre-wrap">{text}</p>
      {response && response.source_documents.length > 0 && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2 text-xs text-slate-600">
            <span>Độ tin cậy:</span>
            <ConfidenceBar value={response.confidence} />
            <span>{Math.round(response.confidence * 100)}%</span>
          </div>
          <ul className="space-y-2">
            {response.source_documents.map((s, i) => (
              <li key={i} className="rounded-lg border border-slate-200 bg-white p-3 text-xs">
                <div className="mb-1 flex items-center gap-2">
                  <span className="font-semibold text-slate-500">[{i + 1}]</span>
                  {s.drawing_number && <span className="font-mono text-slate-800">{s.drawing_number}</span>}
                  <DisciplineTag discipline={s.discipline} size="sm" />
                  {s.page != null && <span className="text-slate-500">p.{s.page}</span>}
                </div>
                <blockquote className="border-l-2 border-blue-400 pl-2 italic text-slate-700">
                  {s.excerpt}
                </blockquote>
              </li>
            ))}
          </ul>
        </div>
      )}
      {response && response.related_questions.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium text-slate-600">Câu hỏi liên quan</div>
          <ul className="space-y-1 text-xs">
            {response.related_questions.map((q, i) => (
              <li key={i} className="text-blue-600 hover:underline">
                {q}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color = pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-300">
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
