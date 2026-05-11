"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { UUID } from "@aec/types/envelope";

import { activityKeys } from "./keys";


export interface ActivityStreamEvent {
  action: string;
  resource_type: string;
  resource_id: string | null;
  project_id: string | null;
  actor_user_id: string | null;
  actor_api_key_id: string | null;
}


type StreamStatus = "idle" | "connecting" | "open" | "fallback" | "error";


/**
 * Subscribes to the per-project activity SSE stream. On every event,
 * invalidates the `useActivityFeed` cache so the table re-fetches —
 * cheap because the events arrive infrequently relative to the user's
 * scroll/filter actions, and the user sees fresh data within ~500ms
 * of an audit-loggable mutation.
 *
 * Two-step auth:
 *   1. POST /api/v1/activity/stream/ticket (Bearer-authed) → ticket
 *      UUID + TTL.
 *   2. EventSource opens GET /api/v1/activity/stream?ticket=…&project_id=…
 *      The browser's EventSource API can't carry custom headers so we
 *      pass the ticket via query string.
 *
 * Fallback: if the ticket-mint endpoint returns 503 (Redis
 * unavailable), the hook reports `status='fallback'` and the page
 * falls back to the existing 30s poll. The transition is silent to
 * the user.
 */
export function useActivityStream(projectId: UUID | null): {
  status: StreamStatus;
  lastEvent: ActivityStreamEvent | null;
} {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [lastEvent, setLastEvent] = useState<ActivityStreamEvent | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!projectId || !token) return;

    let cancelled = false;
    setStatus("connecting");

    (async () => {
      // Step 1: mint a ticket. Standard Bearer header — POST avoids
      // CSRF concerns on the stream itself.
      let ticket: string | null = null;
      try {
        const res = await apiFetch<{ ticket: string; expires_in: number }>(
          "/api/v1/activity/stream/ticket",
          {
            method: "POST",
            token,
            orgId,
            query: { project_id: projectId },
          },
        );
        ticket = res.data?.ticket ?? null;
      } catch (err) {
        // 503 (no Redis) → silently fall back to polling. Other
        // errors (401, 5xx) also fall through to fallback so a
        // misconfigured deploy doesn't break the feed entirely.
        if (!cancelled) setStatus("fallback");
        return;
      }
      if (cancelled || !ticket) {
        if (!cancelled) setStatus("fallback");
        return;
      }

      // Step 2: open the SSE channel. EventSource follows redirects
      // and reconnects on transient drops with its own backoff.
      const baseUrl =
        process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const url = `${baseUrl}/api/v1/activity/stream?ticket=${encodeURIComponent(
        ticket,
      )}&project_id=${encodeURIComponent(projectId)}`;
      const source = new EventSource(url);
      sourceRef.current = source;

      source.addEventListener("ready", () => {
        if (!cancelled) setStatus("open");
      });

      source.addEventListener("activity", (evt) => {
        if (cancelled) return;
        try {
          const parsed = JSON.parse((evt as MessageEvent).data) as ActivityStreamEvent;
          setLastEvent(parsed);
          // Invalidate the feed cache — react-query refetches.
          // Cheaper than appending to the cache directly because the
          // server has the canonical ordering + pagination meta.
          qc.invalidateQueries({
            queryKey: activityKeys.feed({ project_id: projectId }),
          });
        } catch {
          // Malformed payload — skip silently. The next event likely
          // arrives intact.
        }
      });

      source.onerror = () => {
        // EventSource auto-reconnects on transient errors; we only
        // report 'error' if it goes into a hard close (readyState=2).
        if (cancelled) return;
        if (source.readyState === EventSource.CLOSED) {
          setStatus("error");
        }
      };
    })();

    return () => {
      cancelled = true;
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [projectId, token, orgId, qc]);

  return { status, lastEvent };
}
