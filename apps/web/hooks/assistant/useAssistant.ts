"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";

/** Translate a thrown error from the assistant ask paths into a
 *  user-facing message. Special-cases the `403` (role-gated `/ask`
 *  + `/ask/stream`): viewers get a plain-language "you don't have
 *  permission" message instead of a generic backend detail string.
 *
 *  Why this lives here (not in a global error renderer): the role
 *  gate is specific to the assistant — the same 403 shape from a
 *  different surface (e.g. admin-only audit endpoint) wants a
 *  different sentence. Keep the translation co-located with the
 *  hook that triggers the call so a future "kill switch" 403 from
 *  this same surface can extend the same helper without touching
 *  unrelated error UI elsewhere.
 *
 *  Component usage:
 *    onError: (err) => toast.error(getAssistantErrorMessage(err))
 */
export function getAssistantErrorMessage(err: unknown): string {
  // Streaming path emits a `{message, status}` shape via `onError`;
  // recognize it the same way as a thrown ApiError for the 403
  // special case. Both paths converge on the same friendly copy.
  const status =
    err instanceof ApiError
      ? err.status
      : typeof err === "object" && err !== null && "status" in err
        ? (err as { status?: unknown }).status
        : undefined;

  if (status === 403) {
    return (
      "Bạn không có quyền sử dụng trợ lý AI. " +
      "Vai trò 'viewer' chỉ xem được dữ liệu — liên hệ quản trị " +
      "tổ chức để được nâng cấp lên 'member' hoặc cao hơn nếu " +
      "bạn cần đặt câu hỏi cho trợ lý."
    );
  }

  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Đã xảy ra lỗi khi gọi trợ lý AI. Vui lòng thử lại sau.";
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantSource {
  module: string;
  label: string;
  route?: string | null;
}

export interface AssistantResponse {
  project_id: UUID;
  thread_id?: UUID | null;
  answer: string;
  sources: AssistantSource[];
  context_token_estimate: number;
}

export interface AskRequest {
  question: string;
  thread_id?: UUID | null;
  /** Legacy slot — ignored when thread_id is provided. */
  history?: ChatTurn[];
}

// ---------- Threads (sidebar + transcript hydration) ----------

export interface ThreadSummary {
  id: UUID;
  project_id: UUID;
  title: string;
  last_message_at: ISODate;
  created_at: ISODate;
}

export interface ThreadMessage {
  id: UUID;
  role: "user" | "assistant";
  content: string;
  sources: AssistantSource[];
  created_at: ISODate;
}

export interface ThreadDetail extends ThreadSummary {
  messages: ThreadMessage[];
}

const threadsKey = (projectId: UUID) =>
  ["assistant", "threads", projectId] as const;

const threadKey = (threadId: UUID) =>
  ["assistant", "thread", threadId] as const;

export function useAssistantThreads(projectId: UUID) {
  const { token, orgId } = useSession();
  return useQuery({
    queryKey: threadsKey(projectId),
    queryFn: async () => {
      const res = await apiFetch<ThreadSummary[]>(
        `/api/v1/assistant/projects/${projectId}/threads`,
        { method: "GET", token, orgId },
      );
      return (res.data ?? []) as ThreadSummary[];
    },
  });
}

export function useAssistantThread(threadId: UUID | null) {
  const { token, orgId } = useSession();
  return useQuery({
    enabled: Boolean(threadId),
    queryKey: threadId ? threadKey(threadId) : ["assistant", "thread", "noop"],
    queryFn: async () => {
      const res = await apiFetch<ThreadDetail>(
        `/api/v1/assistant/threads/${threadId}`,
        { method: "GET", token, orgId },
      );
      return res.data as ThreadDetail;
    },
  });
}

export function useDeleteAssistantThread(projectId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (threadId: UUID) => {
      await apiFetch<null>(
        `/api/v1/assistant/threads/${threadId}`,
        { method: "DELETE", token, orgId },
      );
      return threadId;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: threadsKey(projectId) });
    },
  });
}

// ---------- Non-streaming ask (legacy, kept for fallback) ----------

export function useAskAssistant(projectId: UUID) {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (req: AskRequest) => {
      const res = await apiFetch<AssistantResponse>(
        `/api/v1/assistant/projects/${projectId}/ask`,
        { method: "POST", token, orgId, body: req },
      );
      return res.data as AssistantResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: threadsKey(projectId) });
    },
  });
}

// ---------- Streaming ask ----------

export interface StreamEventHandlers {
  /** Fired with the thread_id once the server has resolved/created the
   *  thread. Use this to pin the new thread to the URL or sidebar
   *  selection state immediately, even before any tokens arrive. */
  onMeta?: (meta: { thread_id: UUID }) => void;
  /** Fired for every assistant token chunk as it streams back. */
  onToken?: (chunk: { text: string }) => void;
  /** Fired exactly once when the stream completes, with sources + the
   *  context-token estimate from the request. */
  onDone?: (done: {
    sources: AssistantSource[];
    context_token_estimate: number;
  }) => void;
  /** Fired when the server emits an `event: error` frame (e.g. project
   *  not found) OR when the request fails to start (e.g. 403 from the
   *  role gate; 401 expired token). `status` is the HTTP status code
   *  for pre-stream failures, or `undefined` for in-stream errors —
   *  consumers can pipe this through `getAssistantErrorMessage` to
   *  render the friendly copy for known statuses (403 → "you don't
   *  have permission"). */
  onError?: (err: { message: string; status?: number }) => void;
}

/** POST a question to the streaming endpoint and consume the SSE response.
 *
 * Why fetch + ReadableStream instead of `EventSource`: the browser's
 * EventSource only supports GET requests and can't send a JSON body or
 * arbitrary headers (we need Authorization + X-Org-ID). Fetch gives us
 * both at the cost of a tiny manual SSE parser. */
export interface StreamAskOptions {
  token: string;
  orgId: string;
  signal?: AbortSignal;
  handlers: StreamEventHandlers;
}

export async function streamAssistantAsk(
  projectId: UUID,
  req: AskRequest,
  opts: StreamAskOptions,
): Promise<void> {
  const { token, orgId, signal, handlers } = opts;
  const baseUrl =
    typeof window !== "undefined" && window.location?.origin
      ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
      : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
  const res = await fetch(
    `${baseUrl}/api/v1/assistant/projects/${projectId}/ask/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
        "X-Org-ID": orgId,
      },
      body: JSON.stringify(req),
      signal,
    },
  );
  if (!res.ok || !res.body) {
    // Surface the status so consumers (or `getAssistantErrorMessage`)
    // can branch on 403 → "you don't have permission" copy. The role
    // gate fires BEFORE the StreamingResponse is constructed, so a
    // viewer's request lands here as a hard 4xx — never as an in-band
    // `event: error` frame.
    handlers.onError?.({
      message: `HTTP ${res.status}: stream failed to start`,
      status: res.status,
    });
    return;
  }

  const reader = res.body
    .pipeThrough(new TextDecoderStream())
    .getReader();

  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;

    // Frames are delimited by a blank line. Process complete frames,
    // keep the trailing partial in `buffer` for the next read.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      dispatchSseFrame(frame, handlers);
    }
  }
}

function dispatchSseFrame(
  frame: string,
  handlers: StreamEventHandlers,
): void {
  // SSE: lines like `event: token\ndata: {"text": "..."}`. We only
  // implement the subset our backend emits.
  let event = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data = line.slice(5).trim();
    }
  }
  if (!data) return;

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(data);
  } catch {
    return;
  }

  switch (event) {
    case "meta":
      handlers.onMeta?.(parsed as { thread_id: UUID });
      break;
    case "token":
      handlers.onToken?.(parsed as { text: string });
      break;
    case "done":
      handlers.onDone?.(
        parsed as {
          sources: AssistantSource[];
          context_token_estimate: number;
        },
      );
      break;
    case "error":
      handlers.onError?.(parsed as { message: string });
      break;
  }
}
