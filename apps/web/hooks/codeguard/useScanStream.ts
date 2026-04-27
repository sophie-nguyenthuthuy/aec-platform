"use client";

import { useCallback } from "react";

import { useSession } from "@/lib/auth-context";
import type { Finding, RegulationCategory } from "@aec/ui/codeguard";
import type { ProjectParameters } from "./useScan";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ScanStreamRequest {
  project_id: string;
  parameters: ProjectParameters;
  categories?: RegulationCategory[];
}

export interface ScanDonePayload {
  check_id: string;
  total: number;
  pass_count: number;
  warn_count: number;
  fail_count: number;
}

export interface ScanCategoryDonePayload {
  category: RegulationCategory;
  findings: Finding[];
}

export interface ScanStreamHandlers {
  /** A category's retrieval + LLM call just started. Use to render an
   *  in-progress placeholder for that category. */
  onCategoryStart?: (category: RegulationCategory) => void;
  /** A category finished. `findings` may be empty (LLM returned nothing
   *  or retrieval was empty) — the UI should still acknowledge the
   *  category's completion, not silently drop it. */
  onCategoryDone?: (payload: ScanCategoryDonePayload) => void;
  /** Terminal: aggregate counts + check_id for the persisted audit row.
   *  No further events follow. */
  onDone?: (payload: ScanDonePayload) => void;
  /** Terminal: hard pipeline failure. Per-category LLM hiccups never
   *  produce this — they emit `category_done` with empty findings
   *  instead. */
  onError?: (message: string) => void;
}

/**
 * SSE consumer for `POST /api/v1/codeguard/scan/stream`.
 *
 * Same wire-parsing approach as `useCodeguardQueryStream` (double-newline
 * event delimiters, `event:` / `data:` line prefixes), specialised for
 * the scan event vocabulary. Categories arrive in input order so the
 * frontend can render a per-category status list that fills in
 * top-to-bottom — five sequential LLM calls (one per default category)
 * means a streamed scan goes from ~30s of dead time to a steady
 * progression of cards.
 *
 * `done` and `error` are terminal: the hook stops reading from the
 * stream after either fires.
 */
export function useCodeguardScanStream() {
  const { token, orgId } = useSession();

  return useCallback(
    async (
      payload: ScanStreamRequest,
      handlers: ScanStreamHandlers,
    ): Promise<void> => {
      let res: Response;
      try {
        res = await fetch(`${BASE_URL}/api/v1/codeguard/scan/stream`, {
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
          const envelope = (await res.json()) as {
            errors?: Array<{ message?: string }>;
          };
          message = envelope.errors?.[0]?.message ?? message;
        } catch {
          // Body wasn't JSON — keep the HTTP-status fallback.
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

          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() ?? "";

          for (const raw of blocks) {
            if (!raw.trim()) continue;
            const parsed = parseSseEvent(raw);
            if (!parsed) continue;
            const { event, data } = parsed;

            if (event === "category_start") {
              try {
                const { category } = JSON.parse(data) as {
                  category: RegulationCategory;
                };
                handlers.onCategoryStart?.(category);
              } catch {
                // Skip malformed frame — don't kill the stream.
              }
            } else if (event === "category_done") {
              try {
                const body = JSON.parse(data) as ScanCategoryDonePayload;
                handlers.onCategoryDone?.(body);
              } catch {
                // Skip malformed frame.
              }
            } else if (event === "done") {
              try {
                handlers.onDone?.(JSON.parse(data) as ScanDonePayload);
              } catch (err) {
                handlers.onError?.(
                  err instanceof Error ? err.message : "Bad done frame",
                );
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
            // Unknown event names ignored — forward-compat.
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
    if (line.startsWith("event: ")) {
      event = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice(6));
    }
  }
  if (!event || dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}
