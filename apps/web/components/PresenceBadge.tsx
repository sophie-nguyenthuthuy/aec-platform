"use client";

import { useEffect, useState } from "react";
import { Users } from "lucide-react";

import { supabaseBrowser } from "@/lib/supabase-browser";
import { useSession } from "@/lib/auth-context";


/**
 * Real-time presence indicator. Drop into any page to show
 * "X người đang xem" for a specific resource (project, drawing,
 * schedule, etc.).
 *
 * Uses Supabase Realtime presence — a postgres-backed pub/sub channel
 * that broadcasts each subscriber's lightweight metadata to every
 * other subscriber on the same channel. We track only:
 *   * email (display)
 *   * joined_at (sort by recency)
 *
 * No PII beyond what's already in the auth context. Channel names
 * are scoped by `resource_type` + `resource_id` so two PMs on
 * /pulse/abc123 only see each other, not the unrelated user on
 * /pulse/def456.
 *
 * When the page closes, the underlying `channel.untrack()` fires
 * automatically so the indicator decrements within ~1 second on
 * peers. Realtime handles the disconnection edge cases (network
 * blips, sleep, tab close).
 *
 * Falls back to a hard no-op when:
 *   * NEXT_PUBLIC_AEC_REALTIME=off — disable wholesale via env
 *   * the supabase client doesn't expose `.channel()` (older SDK)
 *   * the user has no session — they shouldn't see other users
 */

interface PresenceEntry {
  email: string;
  joined_at: number;
}


interface Props {
  /** Logical channel namespace, e.g. "project". */
  resourceType: string;
  /** Per-resource identifier (UUID-ish, or any stable string). */
  resourceId: string;
  /** Optional CSS class for the wrapper. */
  className?: string;
}


export function PresenceBadge({ resourceType, resourceId, className = "" }: Props) {
  const { email } = useSession();
  const [peers, setPeers] = useState<PresenceEntry[]>([]);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_AEC_REALTIME === "off") return;
    if (!email || !resourceId) return;

    const supabase = supabaseBrowser();
    if (!("channel" in supabase)) return;

    // Channel name must be stable across all subscribers — include
    // both type + id so we don't accidentally cross resources.
    const channelName = `presence:${resourceType}:${resourceId}`;
    const channel = supabase.channel(channelName, {
      config: { presence: { key: email } },
    });

    const update = () => {
      const state = channel.presenceState() as Record<
        string,
        Array<{ email?: string; joined_at?: number }>
      >;
      // presenceState returns each key as an array of metas (one
      // per concurrent tab from the same user). Flatten + dedupe
      // by email so two tabs from the same person count as 1.
      const seen = new Map<string, PresenceEntry>();
      for (const entries of Object.values(state)) {
        for (const meta of entries) {
          const e = meta.email;
          if (typeof e !== "string") continue;
          const j = typeof meta.joined_at === "number" ? meta.joined_at : Date.now();
          const prior = seen.get(e);
          if (!prior || prior.joined_at > j) seen.set(e, { email: e, joined_at: j });
        }
      }
      setPeers(Array.from(seen.values()).sort((a, b) => a.joined_at - b.joined_at));
    };

    channel
      .on("presence", { event: "sync" }, update)
      .on("presence", { event: "join" }, update)
      .on("presence", { event: "leave" }, update)
      .subscribe(async (status: string) => {
        if (status === "SUBSCRIBED") {
          await channel.track({ email, joined_at: Date.now() });
          setShow(true);
        }
      });

    return () => {
      // `untrack` then `removeChannel` — peers see the leave event
      // promptly instead of waiting for the connection timeout.
      channel.untrack().catch(() => undefined);
      supabase.removeChannel(channel).catch(() => undefined);
    };
  }, [email, resourceType, resourceId]);

  // Don't render anything until we know someone OTHER than ourselves
  // is here — solo presence is just noise.
  const others = peers.filter((p) => p.email !== email);
  if (!show || others.length === 0) return null;

  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 ${className}`}
      title={others.map((p) => p.email).join("\n")}
    >
      <Users size={11} />
      <span>{others.length} người đang xem</span>
      {others.length <= 3 && (
        <span className="text-blue-500">
          · {others.map((p) => shortName(p.email)).join(", ")}
        </span>
      )}
    </div>
  );
}


/** "nguyen.thi.thuy@cty.vn" → "nguyen.thi.thuy" — keeps the badge tight. */
function shortName(email: string): string {
  const at = email.indexOf("@");
  if (at < 0) return email;
  return email.slice(0, at);
}
