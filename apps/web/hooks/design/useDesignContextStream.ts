"use client";

import { useCallback } from "react";

import { useSession } from "@/lib/auth-context";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface DesignBrief {
  project_type?: string;
  location?: string;
  site_area?: string;
  site_dimensions?: string;
  orientation?: string;
  floors?: number;
  style?: string;
  budget?: string;
  special_requirements?: string[];
}

export interface DesignContextStreamRequest {
  message: string;
  history: ChatTurn[];
}

export interface DesignContextStreamHandlers {
  onToken?: (delta: string) => void;
  onQuestions?: (questions: string[]) => void;
  onSvg?: (svg: string) => void;
  onDone?: (result: { stage: string; brief?: DesignBrief; follow_up_questions: string[] }) => void;
  onError?: (message: string) => void;
}

/**
 * SSE consumer for POST /api/v1/design/context/stream.
 *
 * Wire format:
 *   event: token     → {"delta": "..."}
 *   event: questions → {"questions": [...]}
 *   event: svg       → {"svg": "..."}
 *   event: done      → {stage, brief, follow_up_questions}
 *   event: error     → {"message": "..."}
 */
export function useDesignContextStream() {
  const { token, orgId } = useSession();

  return useCallback(
    async (
      payload: DesignContextStreamRequest,
      handlers: DesignContextStreamHandlers,
    ): Promise<void> => {
      let res: Response;
      try {
        res = await fetch(`${BASE_URL}/api/v1/design/context/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
            Authorization: `Bearer ${token}`,
            "X-Org-ID": orgId,
          },
          body: JSON.stringify(payload),
        });
      } catch (err) {
        handlers.onError?.(err instanceof Error ? err.message : "Network error");
        return;
      }

      if (!res.ok || !res.body) {
        let message = `HTTP ${res.status}`;
        try {
          const envelope = (await res.json()) as { errors?: Array<{ message?: string }> };
          message = envelope.errors?.[0]?.message ?? message;
        } catch {
          /* keep HTTP status fallback */
        }
        handlers.onError?.(message);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let terminated = false;

      try {
        while (!terminated) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";

          for (const raw of events) {
            if (!raw.trim()) continue;
            const parsed = parseSseEvent(raw);
            if (!parsed) continue;
            const { event, data } = parsed;

            if (event === "token") {
              try {
                const { delta } = JSON.parse(data) as { delta: string };
                if (delta) handlers.onToken?.(delta);
              } catch {
                /* skip malformed frame */
              }
            } else if (event === "questions") {
              try {
                const { questions } = JSON.parse(data) as { questions: string[] };
                if (Array.isArray(questions)) handlers.onQuestions?.(questions);
              } catch {
                /* skip */
              }
            } else if (event === "svg") {
              try {
                const { svg } = JSON.parse(data) as { svg: string };
                if (svg) handlers.onSvg?.(svg);
              } catch {
                /* skip */
              }
            } else if (event === "done") {
              try {
                const result = JSON.parse(data) as {
                  stage: string;
                  brief?: DesignBrief;
                  follow_up_questions: string[];
                };
                handlers.onDone?.(result);
              } catch (err) {
                handlers.onError?.(err instanceof Error ? err.message : "Bad done frame");
              }
              terminated = true;
              break;
            } else if (event === "error") {
              try {
                const { message } = JSON.parse(data) as { message?: string };
                handlers.onError?.(message ?? "Unknown server error");
              } catch {
                handlers.onError?.("Unknown server error");
              }
              terminated = true;
              break;
            }
          }
        }
      } catch (err) {
        handlers.onError?.(err instanceof Error ? err.message : "Stream read error");
      } finally {
        reader.cancel().catch(() => undefined);
      }
    },
    [token, orgId],
  );
}

function parseSseEvent(block: string): { event: string; data: string } | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (!event || dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
