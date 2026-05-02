"use client";

import { useCallback } from "react";

import { useSession } from "@/lib/auth-context";
import type { QueryResponse, RegulationCategory } from "@aec/ui/codeguard";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface QueryStreamRequest {
  project_id?: string;
  question: string;
  language?: "vi" | "en";
  jurisdiction?: string;
  categories?: RegulationCategory[];
  top_k?: number;
}

export interface QueryStreamHandlers {
  /** Each incremental delta appended to the answer text. Concatenating all
   *  deltas reproduces the final `answer` field. */
  onToken?: (delta: string) => void;
  /** Terminal: full grounded `QueryResponse` arrived. No further events
   *  follow. */
  onDone?: (response: QueryResponse) => void;
  /** Terminal: pipeline reported an error, OR the HTTP request itself
   *  failed (network, 5xx, etc.). Same shape either way.
   *
   *  `detailsUrl` is set when the server returns an error envelope with
   *  `details_url` populated — currently only the codeguard cap-check
   *  429 (→ "/codeguard/quota"). UIs should render a CTA pointing at
   *  it. Falls back to undefined for stream-internal errors and
   *  network failures, where there's no in-app surface to point at. */
  onError?: (err: { message: string; detailsUrl?: string }) => void;
}

/**
 * SSE consumer for `POST /api/v1/codeguard/query/stream`.
 *
 * Wire format (matches the backend route's documented shape):
 *
 *     event: token
 *     data: {"delta": "..."}
 *
 *     event: done
 *     data: {answer, confidence, citations, related_questions, check_id}
 *
 *     event: error
 *     data: {"message": "..."}
 *
 * `done` and `error` are terminal: this hook stops reading from the stream
 * after either of them. The handlers fire in arrival order so the caller
 * can update React state directly inside `onToken` to render incremental
 * text.
 *
 * Why a callback-style hook (not state-style): consumers like
 * `query/page.tsx` already maintain a list of chat turns, and the
 * "currently streaming" turn needs to be updated in-place as tokens
 * arrive. Returning a `text` state from the hook would force the page
 * to mirror that state into its own turn list anyway. Callbacks let the
 * page do that mirror in one place without intermediate state.
 */
export function useCodeguardQueryStream() {
  const { token, orgId } = useSession();

  return useCallback(
    async (
      payload: QueryStreamRequest,
      handlers: QueryStreamHandlers,
    ): Promise<void> => {
      let res: Response;
      try {
        res = await fetch(`${BASE_URL}/api/v1/codeguard/query/stream`, {
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
        handlers.onError?.({
          message: err instanceof Error ? err.message : "Network error",
        });
        return;
      }

      if (!res.ok || !res.body) {
        // Try to extract an envelope-shaped error message; fall back to
        // the bare HTTP status when the body isn't JSON (which happens
        // for plain proxy 502s, etc.). Also extract `details_url` for
        // the cap-check 429 → /codeguard/quota CTA.
        let message = `HTTP ${res.status}`;
        let detailsUrl: string | undefined;
        try {
          const envelope = (await res.json()) as {
            errors?: Array<{ message?: string; details_url?: string | null }>;
          };
          message = envelope.errors?.[0]?.message ?? message;
          detailsUrl = envelope.errors?.[0]?.details_url ?? undefined;
        } catch {
          // Body wasn't JSON — keep the HTTP-status fallback.
        }
        handlers.onError?.({ message, detailsUrl });
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

          // SSE events are double-newline-delimited. Split off completed
          // events; the trailing partial chunk stays in `buffer` until
          // the next read fills it in.
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
                if (typeof delta === "string" && delta.length > 0) {
                  handlers.onToken?.(delta);
                }
              } catch {
                // Malformed token frame — skip silently. A single bad
                // frame shouldn't kill the whole stream.
              }
            } else if (event === "done") {
              try {
                const response = JSON.parse(data) as QueryResponse;
                handlers.onDone?.(response);
              } catch (err) {
                handlers.onError?.({
                  message: err instanceof Error ? err.message : "Bad done frame",
                });
              }
              terminated = true;
              break;
            } else if (event === "error") {
              try {
                const { message } = JSON.parse(data) as { message?: string };
                handlers.onError?.({ message: message ?? "Unknown server error" });
              } catch {
                handlers.onError?.({ message: "Unknown server error" });
              }
              terminated = true;
              break;
            }
            // Unknown event names are intentionally ignored — they let
            // the backend evolve (e.g. add a `progress` event) without
            // breaking older clients.
          }
        }
      } catch (err) {
        handlers.onError?.({
          message: err instanceof Error ? err.message : "Stream read error",
        });
      } finally {
        // Best-effort cleanup; cancel() rejects gracefully if the stream
        // has already completed naturally.
        reader.cancel().catch(() => undefined);
      }
    },
    [token, orgId],
  );
}

/** Parse a single SSE event block ("event: x\ndata: y") into its parts.
 *  Returns null if the block doesn't carry both fields. */
function parseSseEvent(block: string): { event: string; data: string } | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) {
      event = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      // SSE allows multi-line `data:` fields concatenated with `\n`.
      dataLines.push(line.slice(6));
    }
  }
  if (!event || dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
