"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { History, MessageSquarePlus, Sparkles, Trash2, X } from "lucide-react";

import {
  type AssistantSource,
  type ChatTurn,
  type ThreadSummary,
  streamAssistantAsk,
  useAssistantThread,
  useAssistantThreads,
  useDeleteAssistantThread,
} from "@/hooks/assistant";
import { useSession } from "@/lib/auth-context";
import type { UUID } from "@aec/types/envelope";


const SUGGESTED_PROMPTS = [
  "Có rủi ro nào tuần này không?",
  "Tóm tắt những thay đổi gần nhất",
  "Có RFI nào đang chờ phản hồi không?",
];

interface UiMessage extends ChatTurn {
  /** Optional sources attached to assistant turns. Populated either
   *  from the server (hydrated thread) or from the streaming `done`
   *  frame (live ask). */
  sources?: AssistantSource[];
  /** True while a streaming response is still arriving — used to
   *  render a subtle "typing" affordance. */
  pending?: boolean;
}

export function AskAiPanel({ projectId }: { projectId: UUID }) {
  const [open, setOpen] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState<UUID | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { token, orgId } = useSession();
  const threadsQ = useAssistantThreads(projectId);
  const threadDetailQ = useAssistantThread(activeThreadId);
  const deleteThread = useDeleteAssistantThread(projectId);

  // When the user picks an existing thread from the sidebar, hydrate
  // the message list from the server's transcript (authoritative).
  useEffect(() => {
    if (threadDetailQ.data) {
      setMessages(
        threadDetailQ.data.messages.map((m) => ({
          role: m.role,
          content: m.content,
          sources: m.sources,
        })),
      );
    }
  }, [threadDetailQ.data]);

  // Auto-scroll to the latest message on every update.
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    scrollerRef.current?.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const newConversation = () => {
    setActiveThreadId(null);
    setMessages([]);
    setDraft("");
    setErrorMsg(null);
  };

  const submit = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    setErrorMsg(null);
    setDraft("");

    // Optimistic user turn + an empty assistant turn that we'll fill
    // in token-by-token from the stream.
    setMessages((prev) => [
      ...prev,
      { role: "user", content: q },
      { role: "assistant", content: "", pending: true },
    ]);
    setStreaming(true);

    try {
      await streamAssistantAsk(
        projectId,
        { question: q, thread_id: activeThreadId ?? undefined },
        {
          token,
          orgId,
          handlers: {
            onMeta: ({ thread_id }) => {
              // Pin the new thread so follow-up turns append rather
              // than spawn yet another conversation.
              setActiveThreadId(thread_id);
            },
            onToken: ({ text }) => {
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (!last || last.role !== "assistant") return prev;
                const updated: UiMessage = {
                  ...last,
                  content: last.content + text,
                };
                return [...prev.slice(0, -1), updated];
              });
            },
            onDone: ({ sources }) => {
              setMessages((prev) => {
                const last = prev[prev.length - 1];
                if (!last) return prev;
                const updated: UiMessage = {
                  ...last,
                  sources,
                  pending: false,
                };
                return [...prev.slice(0, -1), updated];
              });
              // Refresh sidebar: the thread's last_message_at moved.
              threadsQ.refetch();
            },
            onError: ({ message }) => {
              setErrorMsg(message);
              // Roll back the placeholder assistant bubble — there's
              // nothing real to show.
              setMessages((prev) => prev.slice(0, -1));
            },
          },
        },
      );
    } finally {
      setStreaming(false);
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
            className="relative flex h-full w-full max-w-xl flex-col border-l border-slate-200 bg-white shadow-2xl"
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
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={newConversation}
                  className="inline-flex items-center gap-1 rounded p-1 text-xs text-slate-600 hover:bg-slate-100"
                  title="Cuộc trò chuyện mới"
                >
                  <MessageSquarePlus size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setShowSidebar((v) => !v)}
                  className={`inline-flex items-center gap-1 rounded p-1 text-xs ${
                    showSidebar
                      ? "bg-slate-100 text-slate-900"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                  title="Lịch sử cuộc trò chuyện"
                >
                  <History size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="rounded p-1 text-slate-500 hover:bg-slate-100"
                  aria-label="Đóng"
                >
                  <X size={16} />
                </button>
              </div>
            </header>

            <div className="flex flex-1 overflow-hidden">
              {showSidebar && (
                <ThreadsSidebar
                  threads={threadsQ.data ?? []}
                  loading={threadsQ.isLoading}
                  activeId={activeThreadId}
                  onSelect={(t) => {
                    setActiveThreadId(t.id);
                    setShowSidebar(false);
                  }}
                  onDelete={(t) => {
                    deleteThread.mutate(t.id, {
                      onSuccess: () => {
                        if (activeThreadId === t.id) {
                          newConversation();
                        }
                      },
                    });
                  }}
                />
              )}

              <div className="flex flex-1 flex-col">
                <div
                  ref={scrollerRef}
                  className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
                >
                  {messages.length === 0 && !streaming && (
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

                  {messages.map((turn, i) => (
                    <ChatBubble key={i} turn={turn} />
                  ))}

                  {errorMsg && (
                    <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                      {errorMsg}
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
                      disabled={streaming}
                      className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none disabled:opacity-50"
                    />
                    <button
                      type="submit"
                      disabled={!draft.trim() || streaming}
                      className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      Gửi
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}


function ThreadsSidebar({
  threads,
  loading,
  activeId,
  onSelect,
  onDelete,
}: {
  threads: ThreadSummary[];
  loading: boolean;
  activeId: UUID | null;
  onSelect: (t: ThreadSummary) => void;
  onDelete: (t: ThreadSummary) => void;
}) {
  return (
    <div className="w-56 shrink-0 border-r border-slate-200 bg-slate-50/60 px-2 py-3">
      <p className="px-1.5 pb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        Cuộc trò chuyện
      </p>
      {loading ? (
        <p className="px-1.5 text-xs text-slate-500">Đang tải...</p>
      ) : threads.length === 0 ? (
        <p className="px-1.5 text-xs text-slate-500">Chưa có cuộc nào.</p>
      ) : (
        <ul className="space-y-0.5">
          {threads.map((t) => (
            <li key={t.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(t)}
                className={`block w-full truncate rounded px-2 py-1.5 text-left text-xs ${
                  activeId === t.id
                    ? "bg-indigo-100 text-indigo-900"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
                title={t.title}
              >
                {t.title}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm("Xóa cuộc trò chuyện này?")) {
                    onDelete(t);
                  }
                }}
                className="absolute right-1 top-1 hidden rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 group-hover:block"
                aria-label="Xóa"
                title="Xóa"
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


function ChatBubble({ turn }: { turn: UiMessage }) {
  const isUser = turn.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[85%]">
        <div
          className={`whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
            isUser
              ? "bg-indigo-600 text-white"
              : "border border-slate-200 bg-white text-slate-800"
          }`}
        >
          {turn.content}
          {turn.pending && !turn.content && (
            <span className="italic text-slate-400">Đang suy nghĩ…</span>
          )}
          {turn.pending && turn.content && (
            <span className="ml-1 inline-block h-2 w-2 animate-pulse rounded-full bg-slate-400" />
          )}
        </div>
        {turn.role === "assistant" && turn.sources && turn.sources.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {turn.sources.map((s, i) =>
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
                  <span className="mr-1 font-medium uppercase">{s.module}</span>
                  {s.label}
                </li>
              ),
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
