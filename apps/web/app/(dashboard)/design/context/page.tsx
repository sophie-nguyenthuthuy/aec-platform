"use client";

import { useRef, useState } from "react";
import { Send, Sparkles } from "lucide-react";

import { useDesignContextStream } from "@/hooks/design";
import type { ChatTurn, DesignBrief } from "@/hooks/design";

// ---------- Types ----------

interface UserTurn {
  role: "user";
  text: string;
}

interface AssistantTurn {
  role: "assistant";
  text: string;
  questions: string[];
  svg: string | null;
  brief: DesignBrief | null;
  stage: "gathering" | "generating" | null;
  streaming: boolean;
}

type Turn = UserTurn | AssistantTurn;

// ---------- Starter prompts ----------

const STARTERS = [
  "Nhà ở phố 4 tầng, lô góc, Hà Nội",
  "Biệt thự nghỉ dưỡng 2 tầng ven biển Đà Nẵng",
  "Nhà xưởng sản xuất nhỏ, Bình Dương",
  "Căn hộ studio cho thuê, TP.HCM",
];

// ---------- Page ----------

export default function DesignContextPage() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [pending, setPending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const startStream = useDesignContextStream();

  const patchAssistant = (patch: (t: AssistantTurn) => AssistantTurn) => {
    setTurns((curr) => {
      const last = curr.at(-1);
      if (!last || last.role !== "assistant") return curr;
      return [...curr.slice(0, -1), patch(last)];
    });
  };

  const buildHistory = (upToIndex: number): ChatTurn[] =>
    turns.slice(0, upToIndex).map((t) => ({
      role: t.role,
      content: t.role === "user" ? t.text : (t as AssistantTurn).text,
    }));

  const submit = async (messageText?: string) => {
    const message = (messageText ?? input).trim();
    if (!message || pending) return;
    if (messageText === undefined) setInput("");

    const historySnapshot = buildHistory(turns.length);

    setTurns((t) => [
      ...t,
      { role: "user", text: message },
      { role: "assistant", text: "", questions: [], svg: null, brief: null, stage: null, streaming: true },
    ]);
    setPending(true);
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);

    await startStream(
      { message, history: historySnapshot },
      {
        onToken: (delta) => {
          patchAssistant((a) => ({ ...a, text: a.text + delta }));
          bottomRef.current?.scrollIntoView({ behavior: "smooth" });
        },
        onQuestions: (questions) => {
          patchAssistant((a) => ({ ...a, questions }));
        },
        onSvg: (svg) => {
          patchAssistant((a) => ({ ...a, svg }));
        },
        onDone: ({ stage, brief, follow_up_questions }) => {
          patchAssistant((a) => ({
            ...a,
            stage: stage as "gathering" | "generating",
            brief: brief ?? a.brief,
            questions: follow_up_questions.length > 0 ? follow_up_questions : a.questions,
            streaming: false,
          }));
          setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
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
      {/* Chat area */}
      <div className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-6">
        {turns.length === 0 ? (
          <EmptyState onSelect={(s) => void submit(s)} />
        ) : (
          <ul className="space-y-6">
            {turns.map((t, i) =>
              t.role === "user" ? (
                <li key={i} className="text-right">
                  <div className="inline-block max-w-[80%] rounded-2xl bg-blue-600 px-4 py-2 text-left text-sm text-white">
                    {t.text}
                  </div>
                </li>
              ) : (
                <li key={i}>
                  <AssistantBubble turn={t} onAsk={(q) => void submit(q)} />
                </li>
              ),
            )}
            <div ref={bottomRef} />
          </ul>
        )}
      </div>

      {/* Input bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex gap-2 rounded-xl border border-slate-200 bg-white p-3"
      >
        <input
          type="text"
          aria-label="Mô tả dự án kiến trúc"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Mô tả dự án của bạn (loại công trình, diện tích, vị trí...)"
          disabled={pending}
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 placeholder:text-slate-400 disabled:opacity-60"
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

// ---------- Empty state ----------

function EmptyState({ onSelect }: { onSelect: (s: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <div className="flex flex-col items-center gap-2">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
          <Sparkles size={24} className="text-blue-600" />
        </div>
        <h2 className="text-xl font-semibold text-slate-800">Tạo bản vẽ context kiến trúc</h2>
        <p className="max-w-sm text-sm text-slate-500">
          Mô tả dự án của bạn. Tôi sẽ hỏi thêm để hiểu rõ yêu cầu, rồi tạo sơ đồ vị trí và tóm tắt thiết kế.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {STARTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSelect(s)}
            className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left text-sm text-slate-700 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------- Assistant bubble ----------

function AssistantBubble({
  turn,
  onAsk,
}: {
  turn: AssistantTurn;
  onAsk: (q: string) => void;
}) {
  const { text, questions, svg, brief, streaming } = turn;

  return (
    <div className="space-y-3">
      {/* Text answer */}
      <div
        aria-live="polite"
        aria-busy={streaming}
        className="inline-block max-w-full rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-900"
      >
        {streaming && text.length === 0 ? (
          <p className="text-slate-400">Đang phân tích yêu cầu...</p>
        ) : (
          <p className="whitespace-pre-wrap">
            {text}
            {streaming && (
              <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-slate-400 align-middle" />
            )}
          </p>
        )}
      </div>

      {/* Follow-up question chips */}
      {!streaming && questions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-slate-500">Câu hỏi làm rõ:</p>
          <div className="flex flex-wrap gap-2">
            {questions.map((q, i) => (
              <button
                key={i}
                type="button"
                onClick={() => onAsk(q)}
                className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-left text-xs text-blue-700 transition-colors hover:border-blue-400 hover:bg-blue-100"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* SVG site context diagram */}
      {svg && (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-4 py-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Bản vẽ context — Sơ đồ vị trí
            </span>
          </div>
          <div
            className="p-4"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      )}

      {/* Design brief summary */}
      {brief && !streaming && <DesignBriefCard brief={brief} />}
    </div>
  );
}

// ---------- Brief card ----------

function DesignBriefCard({ brief }: { brief: DesignBrief }) {
  const fields: Array<{ label: string; value: string | number | undefined }> = [
    { label: "Loại công trình", value: brief.project_type },
    { label: "Vị trí", value: brief.location },
    { label: "Diện tích lô", value: brief.site_area },
    { label: "Kích thước", value: brief.site_dimensions },
    { label: "Hướng mặt tiền", value: brief.orientation },
    { label: "Số tầng", value: brief.floors },
    { label: "Phong cách", value: brief.style },
    { label: "Ngân sách", value: brief.budget },
  ].filter((f) => f.value !== undefined && f.value !== null && f.value !== "");

  if (fields.length === 0) return null;

  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-emerald-700">
        Tóm tắt thiết kế
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
        {fields.map(({ label, value }) => (
          <div key={label}>
            <dt className="font-medium text-emerald-700">{label}</dt>
            <dd className="text-slate-800">{String(value)}</dd>
          </div>
        ))}
      </dl>
      {brief.special_requirements && brief.special_requirements.length > 0 && (
        <div className="mt-3 text-xs">
          <span className="font-medium text-emerald-700">Yêu cầu đặc biệt: </span>
          <span className="text-slate-700">{brief.special_requirements.join(", ")}</span>
        </div>
      )}
    </div>
  );
}
