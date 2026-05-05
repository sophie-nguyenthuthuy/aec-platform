"use client";

import { useCallback } from "react";

import { useSession } from "@/lib/auth-context";
import type { ChecklistItemType } from "@aec/ui/codeguard";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChecklistStreamRequest {
  project_id: string;
  jurisdiction: string;
  project_type: string;
  parameters?: Record<string, unknown>;
}

export interface ChecklistStreamDonePayload {
  checklist_id: string;
  total: number;
  generated_at: string;
}

export interface ChecklistStreamHandlers {
  /** A single checklist item is now stable enough to render. Items
   *  arrive in input order, exactly once each. */
  onItem?: (item: ChecklistItemType) => void;
  /** Terminal: all items emitted, checklist persisted, `checklist_id`
   *  is the id the mark-item route targets. */
  onDone?: (payload: ChecklistStreamDonePayload) => void;
  /** Terminal: hard pipeline failure or non-200 HTTP.
   *
   *  `detailsUrl` is set when the server returns an error envelope with
   *  `details_url` populated — currently only the codeguard cap-check
   *  429 (→ "/codeguard/quota"). UIs should render a CTA pointing at
   *  it. Falls back to undefined for stream-internal errors. */
  onError?: (err: { message: string; detailsUrl?: string }) => void;
}

/**
 * SSE consumer for `POST /api/v1/codeguard/permit-checklist/stream`.
 *
 * Same parser pattern as the query/scan stream consumers — double-newline
 * event blocks, `event:` / `data:` line prefixes, terminal `done` /
 * `error`. Specialised for the checklist event vocabulary (`item`
 * deltas + a terminal `done` carrying the persisted checklist_id).
 *
 * The `done` event's `checklist_id` is the load-bearing handoff: the
 * page can't enable mark-item interactions until that id arrives,
 * because the mark-item route targets `/checks/{id}/mark-item` against
 * a row that doesn't exist until the streamed items finish landing.
 */
export function useCodeguardChecklistStream() {
  const { token, orgId } = useSession();

  return useCallback(
    async (
      payload: ChecklistStreamRequest,
      handlers: ChecklistStreamHandlers,
    ): Promise<void> => {
      let res: Response;
      try {
        res = await fetch(
          `${BASE_URL}/api/v1/codeguard/permit-checklist/stream`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "text/event-stream",
              Authorization: `Bearer ${token}`,
              "X-Org-ID": orgId,
            },
            body: JSON.stringify(payload),
          },
        );
      } catch (err) {
        handlers.onError?.({
          message: err instanceof Error ? err.message : "Network error",
        });
        return;
      }

      if (!res.ok || !res.body) {
        let message = `HTTP ${res.status}`;
        let detailsUrl: string | undefined;
        try {
          const envelope = (await res.json()) as {
            errors?: Array<{ message?: string; details_url?: string | null }>;
          };
          message = envelope.errors?.[0]?.message ?? message;
          detailsUrl = envelope.errors?.[0]?.details_url ?? undefined;
        } catch {
          // Fall through to the HTTP-status message.
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

          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() ?? "";

          for (const raw of blocks) {
            if (!raw.trim()) continue;
            const parsed = parseSseEvent(raw);
            if (!parsed) continue;
            const { event, data } = parsed;

            if (event === "item") {
              try {
                const item = JSON.parse(data) as ChecklistItemType;
                handlers.onItem?.(item);
              } catch {
                // Skip malformed item frame; don't kill the stream.
              }
            } else if (event === "done") {
              try {
                handlers.onDone?.(JSON.parse(data) as ChecklistStreamDonePayload);
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
            // Unknown event names ignored — forward-compat.
          }
        }
      } catch (err) {
        handlers.onError?.({
          message: err instanceof Error ? err.message : "Stream read error",
        });
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
    if (line.startsWith("event: ")) {
      event = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    }
  }
  if (!event || dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
