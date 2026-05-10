/**
 * Frontend toast queue (cycle TT3).
 *
 * Pinned seams:
 *   1. Same key REPLACES existing.
 *   2. Higher priority consumed first.
 *   3. FIFO within same priority.
 *   4. Expired toasts skipped.
 *   5. Overflow drops OLDEST.
 *   6. Empty queue → null.
 *   7. Pure data structure (no timers).
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_DISMISS_AFTER_MS,
  KIND_PRIORITY,
  MAX_TOAST_QUEUE_SIZE,
  type Toast,
  type ToastKind,
  ToastQueue,
} from "../toast-queue";


function _toast(overrides: Partial<Toast> & { key: string; kind: ToastKind }): Toast {
  return {
    message: "msg",
    createdAt: 0,
    dismissAfterMs: 60000,
    ...overrides,
  };
}


// ---------- Constants ----------


describe("constants", () => {
  it("MAX_TOAST_QUEUE_SIZE = 50", () => {
    expect(MAX_TOAST_QUEUE_SIZE).toBe(50);
  });

  it("DEFAULT_DISMISS_AFTER_MS = 5000 (5s)", () => {
    expect(DEFAULT_DISMISS_AFTER_MS).toBe(5000);
  });

  it("KIND_PRIORITY: error > warn > info", () => {
    expect(KIND_PRIORITY.error).toBeGreaterThan(KIND_PRIORITY.warn);
    expect(KIND_PRIORITY.warn).toBeGreaterThan(KIND_PRIORITY.info);
  });
});


// ---------- Empty queue ----------


describe("empty queue", () => {
  it("size 0", () => {
    expect(new ToastQueue().size()).toBe(0);
  });

  it("consume returns null", () => {
    expect(new ToastQueue().consume(0)).toBeNull();
  });
});


// ---------- Enqueue + consume ----------


describe("enqueue + consume", () => {
  it("enqueued toast can be consumed", () => {
    const q = new ToastQueue();
    const t = _toast({ key: "a", kind: "info" });
    q.enqueue(t);
    expect(q.size()).toBe(1);
    expect(q.consume(100)).toEqual(t);
    expect(q.size()).toBe(0);
  });

  it("consume from empty after exhaust returns null", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info" }));
    q.consume(100);
    expect(q.consume(200)).toBeNull();
  });
});


// ---------- Dedup on key ----------


describe("dedup on key", () => {
  it("same key replaces existing", () => {
    // Cardinal pin: a retry that emits the same toast key
    // should NOT show as a duplicate notification.
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "save", kind: "info", message: "first" }));
    q.enqueue(_toast({ key: "save", kind: "info", message: "second" }));
    expect(q.size()).toBe(1);
    expect(q.consume(100)?.message).toBe("second");
  });

  it("different keys queue separately", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info" }));
    q.enqueue(_toast({ key: "b", kind: "info" }));
    expect(q.size()).toBe(2);
  });

  it("replace preserves higher kind from original", () => {
    // A subsequent enqueue with same key replaces wholesale —
    // including kind. Pin so a refactor that "merges" kinds
    // surfaces here.
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "x", kind: "error", message: "first" }));
    q.enqueue(_toast({ key: "x", kind: "info", message: "second" }));
    const consumed = q.consume(100);
    expect(consumed?.kind).toBe("info");
    expect(consumed?.message).toBe("second");
  });
});


// ---------- Priority ----------


describe("priority", () => {
  it("error consumed before warn before info", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "i", kind: "info", createdAt: 0 }));
    q.enqueue(_toast({ key: "e", kind: "error", createdAt: 100 }));
    q.enqueue(_toast({ key: "w", kind: "warn", createdAt: 50 }));

    expect(q.consume(200)?.kind).toBe("error");
    expect(q.consume(200)?.kind).toBe("warn");
    expect(q.consume(200)?.kind).toBe("info");
  });

  it("priority overrides FIFO when kinds differ", () => {
    // Earlier-created info should NOT preempt later error.
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "i", kind: "info", createdAt: 0 }));
    q.enqueue(_toast({ key: "e", kind: "error", createdAt: 1000 }));
    expect(q.consume(2000)?.kind).toBe("error");
  });
});


// ---------- FIFO within priority ----------


describe("FIFO within same priority", () => {
  it("earliest createdAt consumed first", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 100 }));
    q.enqueue(_toast({ key: "b", kind: "info", createdAt: 50 }));
    q.enqueue(_toast({ key: "c", kind: "info", createdAt: 200 }));

    expect(q.consume(300)?.key).toBe("b");
    expect(q.consume(300)?.key).toBe("a");
    expect(q.consume(300)?.key).toBe("c");
  });

  it("same createdAt — first inserted wins (stable)", () => {
    // Tie on createdAt — first one in queue wins (linear scan
    // returns first match).
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 100 }));
    q.enqueue(_toast({ key: "b", kind: "info", createdAt: 100 }));
    expect(q.consume(200)?.key).toBe("a");
  });
});


// ---------- Expiry ----------


describe("expiry", () => {
  it("expired toast skipped on consume", () => {
    const q = new ToastQueue();
    // Created at 0, dismiss after 100ms — expired at 100.
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 0, dismissAfterMs: 100 }));
    expect(q.consume(200)).toBeNull();
  });

  it("non-expired toast still consumed", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 0, dismissAfterMs: 1000 }));
    expect(q.consume(500)).not.toBeNull();
  });

  it("expiry boundary: expires at exactly createdAt + dismissAfterMs", () => {
    // Pin: strict `>` boundary. At now == grace_end, expired.
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 0, dismissAfterMs: 100 }));
    expect(q.consume(100)).toBeNull();
  });

  it("prune removes expired without consuming", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 0, dismissAfterMs: 100 }));
    q.enqueue(_toast({ key: "b", kind: "info", createdAt: 0, dismissAfterMs: 1000 }));
    q.prune(200);
    expect(q.size()).toBe(1);
  });

  it("prune leaves non-expired alone", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "a", kind: "info", createdAt: 0, dismissAfterMs: 1000 }));
    q.prune(100);
    expect(q.size()).toBe(1);
  });
});


// ---------- Overflow ----------


describe("overflow", () => {
  it("drops OLDEST when exceeding max size", () => {
    // Cardinal pin: drops OLDEST not newest. Recent toasts are
    // more relevant for user UX.
    const q = new ToastQueue();
    for (let i = 0; i < MAX_TOAST_QUEUE_SIZE + 1; i++) {
      q.enqueue(
        _toast({
          key: `k${i}`,
          kind: "info",
          createdAt: i,
          dismissAfterMs: 100000,
        }),
      );
    }
    expect(q.size()).toBe(MAX_TOAST_QUEUE_SIZE);
    // First (k0) should have been dropped; k1 is now the oldest.
    expect(q.consume(MAX_TOAST_QUEUE_SIZE + 100)?.key).toBe("k1");
  });

  it("drops multiple oldest if many over", () => {
    const q = new ToastQueue();
    for (let i = 0; i < MAX_TOAST_QUEUE_SIZE + 10; i++) {
      q.enqueue(
        _toast({
          key: `k${i}`,
          kind: "info",
          createdAt: i,
          dismissAfterMs: 100000,
        }),
      );
    }
    expect(q.size()).toBe(MAX_TOAST_QUEUE_SIZE);
    // First 10 dropped; k10 is now the oldest.
    expect(q.consume(1000)?.key).toBe("k10");
  });
});


// ---------- Realistic scenarios ----------


describe("realistic scenarios", () => {
  it("network error during repeated retry: dedupes by key", () => {
    // User clicks "Save" 3 times quickly, each retry emits the
    // same error toast. Should show ONE error, not three.
    const q = new ToastQueue();
    for (let i = 0; i < 3; i++) {
      q.enqueue(
        _toast({
          key: "save-failed",
          kind: "error",
          message: `attempt ${i}`,
          createdAt: i * 100,
          dismissAfterMs: 10000,
        }),
      );
    }
    expect(q.size()).toBe(1);
    // Latest message wins.
    expect(q.consume(1000)?.message).toBe("attempt 2");
  });

  it("error + info concurrent: error first", () => {
    const q = new ToastQueue();
    q.enqueue(_toast({ key: "i", kind: "info", message: "saved", createdAt: 0 }));
    q.enqueue(_toast({ key: "e", kind: "error", message: "ws err", createdAt: 100 }));
    expect(q.consume(200)?.key).toBe("e");
    expect(q.consume(200)?.key).toBe("i");
  });
});
