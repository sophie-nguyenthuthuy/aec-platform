"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { ISODate, UUID } from "@aec/types/envelope";

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
   *  not found). The stream stops after this. */
  onError?: (err: { message: string }) => void;
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
    handlers.onError?.({
      message: `HTTP ${res.status}: stream failed to start`,
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
