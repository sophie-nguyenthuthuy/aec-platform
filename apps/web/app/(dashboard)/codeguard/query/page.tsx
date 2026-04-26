"use client";

import { useState } from "react";
import { Info, Send } from "lucide-react";
import { CitationCard } from "@aec/ui/codeguard";
import type { QueryResponse } from "@aec/ui/codeguard";
import { useCodeguardQueryStream } from "@/hooks/codeguard";

interface UserTurn {
  role: "user";
  text: string;
}

interface AssistantTurnState {
  role: "assistant";
  /** Text rendered for this turn — incremental during streaming, final
   *  on `done`, "Lỗi: ..." on error. */
  text: string;
  /** Set on `done`; carries citations + confidence + related_questions. */
  response?: QueryResponse;
  /** True from when the user submits until the terminal SSE event. */
  streaming: boolean;
}

type ChatTurn = UserTurn | AssistantTurnState;

export default function RegulationChatPage() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState(false);
  const startStream = useCodeguardQueryStream();

  /**
   * Patch the most-recent assistant turn (which is always the in-flight
   * one when this is called). Using a callback form so consecutive
   * setStates inside a single SSE batch all see the latest state — React
   * batches them but each token handler reads `state.turns` via the
   * functional update.
   */
  const patchAssistant = (patch: (t: AssistantTurnState) => AssistantTurnState) => {
    setTurns((curr) => {
      const last = curr.at(-1);
      // Defensive: only patch if the last turn is the in-flight assistant
      // turn we expect. A user-then-assistant append always sets this up
      // before submit() awaits, so in practice this guard never triggers
      // — TS just needs the explicit narrowing for noUncheckedIndexedAccess.
      if (!last || last.role !== "assistant") return curr;
      return [...curr.slice(0, -1), patch(last)];
    });
  };

  const submit = async (questionText?: string) => {
    const question = (questionText ?? input).trim();
    if (!question || pending) return;
    if (questionText === undefined) setInput("");

    // Append user turn + a placeholder assistant turn that starts in
    // streaming mode. The assistant turn is mutated in place by the
    // SSE handlers below; on terminal events `streaming` flips to
    // false and any final state (response or error) is attached.
    setTurns((t) => [
      ...t,
      { role: "user", text: question },
      { role: "assistant", text: "", streaming: true },
    ]);
    setPending(true);

    await startStream(
      { question },
      {
        onToken: (delta) => {
          patchAssistant((a) => ({ ...a, text: a.text + delta }));
        },
        onDone: (response) => {
          patchAssistant((a) => ({
            ...a,
            // For the abstain shape (confidence===0 + empty citations)
            // the streaming path emits `done` with no preceding tokens,
            // so we always sync `text` to the canonical answer here
            // — covers both "tokens accumulated" and "tokens skipped"
            // cases without branching.
            text: response.answer,
            response,
            streaming: false,
          }));
        },
        onError: (message) => {
          patchAssistant((a) => ({
            ...a,
            text: `Lỗi: ${message}`,
            streaming: false,
          }));
        },
      },
    );
    setPending(false);
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
                  <AssistantTurn turn={t} onAskRelated={submit} />
                )}
              </li>
            ))}
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
          disabled={pending}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={pending || !input.trim()}
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
  turn,
  onAskRelated,
}: {
  turn: AssistantTurnState;
  onAskRelated: (q: string) => void;
}) {
  const { text, response, streaming } = turn;

  // Backend abstain contract (see `_abstain_response` in
  // apps/ml/pipelines/codeguard.py): when retrieval returns no chunks the
  // pipeline skips the LLM entirely and returns confidence=0 with empty
  // citations. Render this distinctly so users see "we couldn't answer"
  // rather than mistaking it for a low-confidence answer — for a compliance
  // tool the difference matters.
  const isAbstain =
    !streaming &&
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
      {/* Empty-text-while-streaming placeholder: gives the user
          immediate visual feedback that something started, before the
          first token arrives. */}
      {streaming && text.length === 0 ? (
        <p className="text-slate-500">Đang tra cứu quy chuẩn...</p>
      ) : (
        <p className="whitespace-pre-wrap">
          {text}
          {streaming && (
            <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-slate-400 align-middle" />
          )}
        </p>
      )}
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
