"use client";

import Link from "next/link";
import type { Route } from "next";
import { useState } from "react";
import { Sparkles, X } from "lucide-react";

import {
  type ChatTurn,
  useAskAssistant,
} from "@/hooks/assistant";
import type { UUID } from "@aec/types/envelope";


const SUGGESTED_PROMPTS = [
  "Có rủi ro nào tuần này không?",
  "Tóm tắt những thay đổi gần nhất",
  "Có RFI nào đang chờ phản hồi không?",
];

export function AskAiPanel({ projectId }: { projectId: UUID }) {
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");

  const ask = useAskAssistant(projectId);

  const submit = async (question: string) => {
    if (!question.trim() || ask.isPending) return;
    // Optimistically push the user turn so it appears immediately —
    // backend is stateless, we control the transcript here.
    const nextHistory: ChatTurn[] = [
      ...history,
      { role: "user", content: question },
    ];
    setHistory(nextHistory);
    setDraft("");
    try {
      const res = await ask.mutateAsync({
        question,
        history: nextHistory.slice(0, -1), // exclude the just-pushed user msg
      });
      setHistory((h) => [
        ...h,
        { role: "assistant", content: res.answer },
      ]);
    } catch {
      // Roll back the optimistic push if the call failed.
      setHistory((h) => h.slice(0, -1));
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-30 inline-flex items-center gap-2 rounded-full bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-indigo-700"
      >
        <Sparkles size={14} />
        Hỏi AI
      </button>

      {open && (
        <div className="fixed inset-0 z-40 flex justify-end">
          <button
            type="button"
            aria-label="Đóng"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
          />
          <aside
            className="relative flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl"
            role="dialog"
            aria-label="AI assistant"
          >
            <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-indigo-100 text-indigo-700">
                  <Sparkles size={14} />
                </span>
                <h3 className="text-sm font-semibold text-slate-900">
                  Trợ lý AI dự án
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded p-1 text-slate-500 hover:bg-slate-100"
                aria-label="Đóng"
              >
                <X size={16} />
              </button>
            </header>

            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
              {history.length === 0 && !ask.isPending && (
                <div className="space-y-2">
                  <p className="text-xs text-slate-500">
                    Hỏi về tình trạng dự án — task mở, change order, RFI,
                    sự cố an toàn, lỗi tồn đọng. Trả lời dựa trên dữ liệu
                    hiện tại của dự án này.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {SUGGESTED_PROMPTS.map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => submit(p)}
                        className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-50"
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {history.map((turn, i) => (
                <ChatBubble key={i} turn={turn} />
              ))}

              {ask.isPending && (
                <ChatBubble
                  turn={{ role: "assistant", content: "Đang suy nghĩ…" }}
                  pending
                />
              )}

              {ask.data?.sources && ask.data.sources.length > 0 && (
                <div className="border-t border-slate-100 pt-2">
                  <p className="text-[11px] uppercase tracking-wide text-slate-500">
                    Nguồn
                  </p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {ask.data.sources.map((s, i) =>
                      s.route ? (
                        <li key={i}>
                          <Link
                            href={s.route as Route}
                            className="inline-flex rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-[11px] text-blue-700 hover:bg-blue-100"
                          >
                            <span className="mr-1 font-medium uppercase">
                              {s.module}
                            </span>
                            <span>{s.label}</span>
                          </Link>
                        </li>
                      ) : (
                        <li
                          key={i}
                          className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] text-slate-700"
                        >
                          <span className="mr-1 font-medium uppercase">
                            {s.module}
                          </span>
                          {s.label}
                        </li>
                      ),
                    )}
                  </ul>
                </div>
              )}
            </div>

            <form
              className="border-t border-slate-200 px-4 py-3"
              onSubmit={(e) => {
                e.preventDefault();
                submit(draft);
              }}
            >
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="Hỏi AI về dự án này..."
                  disabled={ask.isPending}
                  className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={!draft.trim() || ask.isPending}
                  className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  Gửi
                </button>
              </div>
              {ask.isError && (
                <p className="mt-1.5 text-xs text-red-600">
                  Không thể gửi yêu cầu. Vui lòng thử lại.
                </p>
              )}
            </form>
          </aside>
        </div>
      )}
    </>
  );
}


function ChatBubble({
  turn,
  pending = false,
}: {
  turn: ChatTurn;
  pending?: boolean;
}) {
  const isUser = turn.role === "user";
  return (
    <div
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
          isUser
            ? "bg-indigo-600 text-white"
            : pending
              ? "border border-slate-200 bg-slate-50 italic text-slate-500"
              : "border border-slate-200 bg-white text-slate-800"
        }`}
      >
        {turn.content}
      </div>
    </div>
  );
}
