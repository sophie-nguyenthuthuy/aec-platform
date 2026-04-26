"use client";

import { useState } from "react";
import { Info, Send } from "lucide-react";
import { CitationCard } from "@aec/ui/codeguard";
import type { QueryResponse } from "@aec/ui/codeguard";
import { useCodeguardQuery } from "@/hooks/codeguard";

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  response?: QueryResponse;
}

export default function RegulationChatPage() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const mutation = useCodeguardQuery();

  // Parameterised so it can be invoked both from the form and from a
  // clicked "related question" suggestion. When called with no arg it
  // consumes the current `input` state and clears the textbox; when
  // called with `questionText` it leaves `input` alone (so the user
  // doesn't lose anything they were typing).
  const submit = async (questionText?: string) => {
    const question = (questionText ?? input).trim();
    if (!question || mutation.isPending) return;
    if (questionText === undefined) setInput("");
    setTurns((t) => [...t, { role: "user", text: question }]);
    try {
      const response = await mutation.mutateAsync({ question });
      setTurns((t) => [...t, { role: "assistant", text: response.answer, response }]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Đã xảy ra lỗi";
      setTurns((t) => [...t, { role: "assistant", text: `Lỗi: ${message}` }]);
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <div className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-6">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center text-slate-500">
            <h2 className="text-xl font-semibold text-slate-800">Hỏi bất cứ câu nào về quy chuẩn xây dựng</h2>
            <p className="mt-2 max-w-md text-sm">
              Ví dụ: "Chiều cao tối thiểu của hành lang thoát nạn trong nhà ở cao tầng là bao nhiêu?"
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
                  <AssistantTurn text={t.text} response={t.response} onAskRelated={submit} />
                )}
              </li>
            ))}
            {mutation.isPending && (
              <li className="text-sm text-slate-500">Đang tra cứu quy chuẩn...</li>
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
          placeholder="Đặt câu hỏi về QCVN, TCVN, luật xây dựng..."
          disabled={mutation.isPending}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={mutation.isPending || !input.trim()}
          className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          <Send size={14} />
          Gửi
        </button>
      </form>
    </div>
  );
}

function AssistantTurn({
  text,
  response,
  onAskRelated,
}: {
  text: string;
  response?: QueryResponse;
  onAskRelated: (q: string) => void;
}) {
  // Backend abstain contract (see `_abstain_response` in
  // apps/ml/pipelines/codeguard.py): when retrieval returns no chunks the
  // pipeline skips the LLM entirely and returns confidence=0 with empty
  // citations. Render this distinctly so users see "we couldn't answer"
  // rather than mistaking it for a low-confidence answer — for a compliance
  // tool the difference matters.
  const isAbstain =
    response !== undefined &&
    response.confidence === 0 &&
    response.citations.length === 0;

  if (isAbstain) {
    return (
      <div className="inline-block max-w-full rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-amber-700">
          <Info size={14} />
          Không có kết quả phù hợp
        </div>
        <p className="whitespace-pre-wrap">{text}</p>
      </div>
    );
  }

  return (
    <div className="inline-block max-w-full rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-900">
      <p className="whitespace-pre-wrap">{text}</p>
      {response && response.citations.length > 0 && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center gap-2 text-xs text-slate-600">
            <span>Độ tin cậy:</span>
            <ConfidenceBar value={response.confidence} />
            <span>{Math.round(response.confidence * 100)}%</span>
          </div>
          <div className="space-y-2">
            {response.citations.map((c, i) => (
              <CitationCard key={i} citation={c} index={i} />
            ))}
          </div>
        </div>
      )}
      {response && response.related_questions.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium text-slate-600">Câu hỏi liên quan</div>
          <ul className="space-y-1 text-xs">
            {response.related_questions.map((q, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => onAskRelated(q)}
                  className="rounded text-left text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-400"
                >
                  {q}
                </button>
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
