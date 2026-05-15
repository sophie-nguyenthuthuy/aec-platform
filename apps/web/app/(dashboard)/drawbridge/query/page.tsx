"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  ChevronDown,
  FileText,
  Loader2,
  Sparkles,
  Wand2,
} from "lucide-react";

import { DisciplineTag, type QueryResponse, type SourceDocument } from "@aec/ui/drawbridge";
import { useSession } from "@/lib/auth-context";
import { useDrawbridgeQuery } from "@/hooks/drawbridge";
import { ProjectSelect } from "@/app/(dashboard)/_components/ProjectSelect";


/**
 * Polished Drawbridge chat surface.
 *
 * Improvements over the v1:
 *   * Two-bubble layout (user right / assistant left with avatar dot)
 *     instead of a flat alternating list — reads like every messaging
 *     app the user already knows.
 *   * Token-by-token typing reveal animation. The backend `/query`
 *     endpoint is still a single round-trip — we simulate streaming
 *     on the client to give the "assistant is thinking and writing"
 *     feel without the SSE infra overhead. Bonus: a real backend
 *     streaming swap later is a pure backend change; the UI is
 *     already shaped for it.
 *   * Thinking dots while the request is in flight.
 *   * `[N]` markers in the answer body convert to inline citation
 *     chips with hover-tooltip showing the source excerpt + click-
 *     through to /drawbridge/documents/{id}.
 *   * Related-questions surface as one-click follow-up pills below
 *     the transcript so a user can drill deeper without retyping.
 *   * Suggested-openers on the empty state — drops the cold-start
 *     paralysis ("what should I even ask?").
 *
 * State management: simple useState chain. Multi-turn context is
 * UI-only — the API call still carries one question at a time. A
 * future hardening adds `recent_turns[]` to the request so the model
 * can reason about the previous turn ("and what about on the 5th
 * floor?"). Out of scope here.
 */

interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Animated display state — characters revealed so far. For assistant
   *  turns only; user turns render immediately. */
  visibleChars?: number;
  response?: QueryResponse;
  errored?: boolean;
}

const SUGGESTED_OPENERS = [
  "Bản vẽ này có bao nhiêu lối thoát hiểm?",
  "Tổng chiều dài hệ thống đường ống ngầm bao nhiêu?",
  "Thông số kỹ thuật của thang máy là gì?",
  "Có mấy phòng kỹ thuật điện trên mặt bằng tầng 1?",
];

/** Reveal characters per frame. Larger → faster typing animation. */
const STREAM_CHARS_PER_TICK = 4;
const STREAM_TICK_MS = 18;


export default function DrawingChatPage() {
  const session = useSession();
  const [projectId, setProjectId] = useState<string>(
    (session as { projectId?: string }).projectId ?? "",
  );
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const mutation = useDrawbridgeQuery();

  const scrollerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [turns]);

  // Animated reveal for assistant turns.
  useEffect(() => {
    const idx = turns.findIndex(
      (t) =>
        t.role === "assistant" &&
        !t.errored &&
        t.text.length > 0 &&
        (t.visibleChars ?? 0) < t.text.length,
    );
    if (idx < 0) return;

    const id = setTimeout(() => {
      setTurns((prev) =>
        prev.map((t, i) =>
          i === idx
            ? {
                ...t,
                visibleChars: Math.min(
                  t.text.length,
                  (t.visibleChars ?? 0) + STREAM_CHARS_PER_TICK,
                ),
              }
            : t,
        ),
      );
    }, STREAM_TICK_MS);
    return () => clearTimeout(id);
  }, [turns]);

  async function submit(question?: string) {
    const q = (question ?? input).trim();
    if (!q || !projectId || mutation.isPending) return;
    setInput("");
    const userId = `u-${Date.now()}`;
    const assistantId = `a-${Date.now()}`;
    setTurns((t) => [
      ...t,
      { id: userId, role: "user", text: q },
      { id: assistantId, role: "assistant", text: "", visibleChars: 0 },
    ]);
    try {
      const response = await mutation.mutateAsync({
        project_id: projectId,
        question: q,
      });
      setTurns((t) =>
        t.map((turn) =>
          turn.id === assistantId
            ? {
                ...turn,
                text: response.answer,
                response,
                visibleChars: 0,
              }
            : turn,
        ),
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "unknown";
      setTurns((t) =>
        t.map((turn) =>
          turn.id === assistantId
            ? {
                ...turn,
                text: `Lỗi: ${msg}`,
                errored: true,
                visibleChars: msg.length + 5,
              }
            : turn,
        ),
      );
    }
  }

  function reset() {
    setTurns([]);
    setInput("");
  }

  const lastAssistant = useMemo(
    () => [...turns].reverse().find((t) => t.role === "assistant" && !t.errored),
    [turns],
  );
  const followups = lastAssistant?.response?.related_questions ?? [];

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col gap-3">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Drawbridge — Hỏi bản vẽ</h2>
          <p className="text-xs text-slate-500">
            Trợ lý AI trả lời từ kho bản vẽ + tài liệu kỹ thuật của dự án bạn chọn.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ProjectSelect value={projectId} onChange={setProjectId} />
          {turns.length > 0 && (
            <button
              onClick={reset}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
            >
              Đoạn chat mới
            </button>
          )}
        </div>
      </div>

      {/* Transcript */}
      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white"
      >
        {turns.length === 0 ? (
          <EmptyState disabled={!projectId} onPick={(q) => submit(q)} />
        ) : (
          <ul className="space-y-4 p-4">
            {turns.map((t, idx) => (
              <li key={t.id}>
                {t.role === "user" ? (
                  <UserBubble text={t.text} />
                ) : (
                  <AssistantBubble
                    turn={t}
                    pending={mutation.isPending && idx === turns.length - 1}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Suggested follow-ups */}
      {followups.length > 0 && !mutation.isPending && (
        <div className="flex flex-wrap gap-1.5">
          {followups.map((f, i) => (
            <button
              key={i}
              onClick={() => submit(f)}
              className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-700 hover:bg-blue-100"
            >
              <Wand2 size={11} />
              {f}
            </button>
          ))}
        </div>
      )}

      {/* Composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white p-2"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={1}
          placeholder={projectId ? "Hỏi gì đó về bản vẽ…" : "Chọn dự án trước"}
          disabled={!projectId || mutation.isPending}
          className="flex-1 resize-none rounded-md px-3 py-2 text-sm focus:outline-none disabled:bg-slate-50"
        />
        <button
          type="submit"
          disabled={!input.trim() || !projectId || mutation.isPending}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-600 text-white disabled:opacity-40"
          aria-label="Gửi"
        >
          {mutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <ArrowUp size={14} />
          )}
        </button>
      </form>
    </div>
  );
}


// ---------- Bubbles ----------


function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2 text-sm text-white">
        {text}
      </div>
    </div>
  );
}


function AssistantBubble({
  turn,
  pending,
}: {
  turn: ChatTurn;
  pending: boolean;
}) {
  const visible = turn.text.slice(0, turn.visibleChars ?? turn.text.length);
  const fullyRendered =
    (turn.visibleChars ?? turn.text.length) >= turn.text.length;
  const isThinking = pending && !turn.text;

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[88%] gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
          <Sparkles size={13} />
        </div>
        <div className="space-y-2">
          <div
            className={`rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed ${
              turn.errored
                ? "bg-rose-50 text-rose-800"
                : "bg-slate-100 text-slate-900"
            }`}
          >
            {isThinking ? (
              <ThinkingDots />
            ) : (
              <>
                {renderWithCitations(visible, turn.response?.source_documents ?? [])}
                {!fullyRendered && !turn.errored && (
                  <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-slate-500/40 align-middle" />
                )}
              </>
            )}
          </div>

          {fullyRendered && turn.response && turn.response.source_documents.length > 0 && (
            <CitationsPanel
              docs={turn.response.source_documents}
              confidence={turn.response.confidence}
            />
          )}
        </div>
      </div>
    </div>
  );
}


function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1 text-slate-500">
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400"
        style={{ animationDelay: "0ms" }}
      />
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400"
        style={{ animationDelay: "150ms" }}
      />
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-slate-400"
        style={{ animationDelay: "300ms" }}
      />
      <span className="ml-1 text-xs">Đang đọc bản vẽ…</span>
    </span>
  );
}


/**
 * Render answer text, converting `[N]` markers into clickable citation
 * chips. The Drawbridge prompt embeds [1], [2], … indexing into
 * `source_documents`. If a chip's index is out of range we render
 * the literal `[N]` so a malformed response doesn't lose content.
 */
function renderWithCitations(
  text: string,
  docs: SourceDocument[],
): React.ReactNode {
  if (docs.length === 0) return text;
  const parts: React.ReactNode[] = [];
  const re = /\[(\d+)\]/g;
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    const before = text.slice(lastIdx, m.index);
    if (before) parts.push(before);
    const n = parseInt(m[1] ?? "0", 10);
    const doc = docs[n - 1];
    if (doc) {
      parts.push(<CitationChip key={`c-${key++}`} index={n} doc={doc} />);
    } else {
      parts.push(m[0]);
    }
    lastIdx = m.index + m[0].length;
  }
  parts.push(text.slice(lastIdx));
  return parts;
}


function CitationChip({ index, doc }: { index: number; doc: SourceDocument }) {
  return (
    <span className="group relative inline-block align-baseline">
      <a
        href={`/drawbridge/documents/${doc.document_id}`}
        className="mx-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-blue-600 align-middle text-[9px] font-bold text-white hover:bg-blue-700"
        title={doc.title || doc.drawing_number || "Source"}
      >
        {index}
      </a>
      <span className="invisible absolute bottom-full left-1/2 z-10 mb-1 w-72 -translate-x-1/2 rounded-md bg-slate-900 px-3 py-2 text-xs text-white shadow-lg group-hover:visible">
        <div className="mb-1 flex items-center gap-1 font-semibold">
          <FileText size={11} />
          {doc.drawing_number || doc.title || "Source"}
          {doc.page && <span className="text-slate-300"> · trang {doc.page}</span>}
        </div>
        <div className="line-clamp-4 text-slate-300">{doc.excerpt}</div>
      </span>
    </span>
  );
}


function CitationsPanel({
  docs,
  confidence,
}: {
  docs: SourceDocument[];
  confidence: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      className="rounded-md border border-slate-200 bg-slate-50 text-xs"
    >
      <summary className="flex cursor-pointer items-center justify-between px-3 py-1.5 text-slate-600">
        <span className="flex items-center gap-1.5">
          <FileText size={11} />
          {docs.length} nguồn tham chiếu · độ tin cậy{" "}
          <b className="text-slate-900">{(confidence * 100).toFixed(0)}%</b>
        </span>
        <ChevronDown
          size={12}
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        />
      </summary>
      <ol className="divide-y divide-slate-200 px-3 pb-2">
        {docs.map((d, i) => (
          <li key={i} className="py-2">
            <div className="flex items-center gap-2">
              <a
                href={`/drawbridge/documents/${d.document_id}`}
                className="font-medium text-blue-700 hover:underline"
              >
                [{i + 1}] {d.drawing_number || d.title || "Tài liệu"}
                {d.page ? ` · trang ${d.page}` : ""}
              </a>
              {d.discipline && <DisciplineTag discipline={d.discipline} size="sm" />}
            </div>
            <p className="mt-1 text-slate-600">{d.excerpt}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}


function EmptyState({
  disabled,
  onPick,
}: {
  disabled: boolean;
  onPick: (q: string) => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 py-10 text-center text-slate-600">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-blue-100">
        <Sparkles size={24} className="text-blue-600" />
      </div>
      <h3 className="mt-4 text-lg font-semibold text-slate-900">
        Hỏi gì đó về bản vẽ
      </h3>
      <p className="mt-1 max-w-md text-sm">
        Trợ lý sẽ trả lời từ kho bản vẽ + thuyết minh kỹ thuật đã upload
        cho dự án bạn chọn. Mỗi câu trả lời đi kèm trích dẫn về tài liệu
        gốc — click số <b>[1]</b> để xem nguồn.
      </p>
      {!disabled && (
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {SUGGESTED_OPENERS.map((q) => (
            <button
              key={q}
              onClick={() => onPick(q)}
              className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
