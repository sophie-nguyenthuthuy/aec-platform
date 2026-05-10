/**
 * Frontend toast queue (cycle TT3, TS-only).
 *
 * Pure FIFO queue with priority + dedup + auto-expire for the
 * global notification system. Today the global toast layer
 * implements queueing inline; the dashboard's "saving..." toast
 * pattern duplicates dedup logic. This module is the single
 * source of truth.
 *
 *   ToastQueue                  — class with enqueue/consume/prune
 *   Toast                       — interface (key, kind, message, ...)
 *   ToastKind                   — "error" | "warn" | "info"
 *   MAX_TOAST_QUEUE_SIZE        — 50
 *   DEFAULT_DISMISS_AFTER_MS    — 5000
 *   KIND_PRIORITY               — error > warn > info
 *
 * Frontend-only — pure data structure with no DOM / timer.
 *
 * Pinned invariants:
 *   * Same `key` REPLACES existing entry (NOT inserted as duplicate).
 *   * Higher-priority kinds consumed first.
 *   * FIFO within same priority (earliest createdAt first).
 *   * Expired toasts skipped on consume (NOT returned).
 *   * Queue overflow drops OLDEST (NOT newest — recent toasts
 *     more relevant in user UX).
 *   * Pure data — no DOM, no setTimeout / setInterval.
 */


export type ToastKind = "error" | "warn" | "info";


export interface Toast {
  /** Stable identity — same key REPLACES rather than enqueueing
   *  a duplicate. Common case: a "saving..." toast retried fast. */
  key: string;
  kind: ToastKind;
  message: string;
  /** Wall-clock ms since epoch. */
  createdAt: number;
  /** TTL in ms. The toast expires at `createdAt + dismissAfterMs`. */
  dismissAfterMs: number;
}


export const MAX_TOAST_QUEUE_SIZE = 50;
export const DEFAULT_DISMISS_AFTER_MS = 5000;


/** Priority for `consume()` ordering. error > warn > info. */
export const KIND_PRIORITY: Readonly<Record<ToastKind, number>> = {
  error: 3,
  warn: 2,
  info: 1,
};


export class ToastQueue {
  private items: Toast[] = [];

  /** Add a toast to the queue. If a toast with the same `key`
   *  already exists, it is REPLACED (not duplicated).
   *
   *  Overflow (>MAX_TOAST_QUEUE_SIZE) drops the OLDEST entry.
   */
  enqueue(toast: Toast): void {
    const idx = this.items.findIndex((t) => t.key === toast.key);
    if (idx >= 0) {
      // Replace in place — preserves ordering vs. removing + re-adding.
      this.items[idx] = toast;
      return;
    }
    this.items.push(toast);
    while (this.items.length > MAX_TOAST_QUEUE_SIZE) {
      this.items.shift();
    }
  }

  /** Remove and return the highest-priority non-expired toast,
   *  breaking ties by FIFO (earliest createdAt). Returns null
   *  if the queue is empty (after pruning expired toasts). */
  consume(now: number): Toast | null {
    this.prune(now);
    if (this.items.length === 0) return null;

    let bestIdx = 0;
    for (let i = 1; i < this.items.length; i++) {
      const cur = this.items[i]!;
      const best = this.items[bestIdx]!;
      const curPri = KIND_PRIORITY[cur.kind];
      const bestPri = KIND_PRIORITY[best.kind];
      if (curPri > bestPri) {
        bestIdx = i;
      } else if (curPri === bestPri && cur.createdAt < best.createdAt) {
        bestIdx = i;
      }
    }

    const result = this.items[bestIdx]!;
    this.items.splice(bestIdx, 1);
    return result;
  }

  /** Remove all expired toasts. */
  prune(now: number): void {
    this.items = this.items.filter(
      (t) => t.createdAt + t.dismissAfterMs > now,
    );
  }

  size(): number {
    return this.items.length;
  }
}
