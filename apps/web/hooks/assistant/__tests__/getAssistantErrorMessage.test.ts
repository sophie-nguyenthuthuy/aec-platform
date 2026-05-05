import { describe, expect, test } from "vitest";

import { ApiError } from "@/lib/api";
import { getAssistantErrorMessage } from "@/hooks/assistant";

/**
 * `getAssistantErrorMessage` is the user-facing translator for
 * errors thrown by the assistant ask paths (both streaming and
 * non-streaming). The most important contract: a 403 from the role
 * gate (`require_min_role(Role.MEMBER)` on `/ask` and `/ask/stream`)
 * MUST render as a plain-language vi-VN message that names the
 * remediation, not as a generic "HTTP 403" string.
 *
 * Pin both error shapes the helper has to handle:
 *   1. ApiError thrown by `apiFetch` (non-streaming `useAskAssistant`).
 *   2. `{message, status}` shape passed by the streaming `onError`
 *      handler in `streamAssistantAsk`.
 */

describe("getAssistantErrorMessage", () => {
  test("translates ApiError(status=403) to the role-gate message", () => {
    const err = new ApiError(403, "FORBIDDEN", "raw backend detail");
    const out = getAssistantErrorMessage(err);
    // Must be the friendly vi-VN copy, NOT the raw backend message.
    expect(out).not.toBe("raw backend detail");
    expect(out).toContain("không có quyền");
    expect(out).toContain("viewer");
    expect(out).toContain("member");
  });

  test("translates streaming-handler 403 shape to the same role-gate message", () => {
    // The streaming path emits `{message, status}` via onError —
    // helper must recognize the shape and produce the same friendly
    // copy as for ApiError. Otherwise users hitting /ask/stream see
    // a different (worse) message than users hitting /ask.
    const out = getAssistantErrorMessage({
      message: "HTTP 403: stream failed to start",
      status: 403,
    });
    expect(out).toContain("không có quyền");
    expect(out).toContain("member");
  });

  test("falls back to ApiError.message for non-403 statuses", () => {
    // 429 (cap-check refusal), 500 (server error), etc. — pass the
    // backend's message through unchanged. The 403 special case is
    // load-bearing precisely because it's the assistant's only
    // role-gated 4xx; other statuses already carry useful detail.
    const err = new ApiError(429, "QUOTA_EXCEEDED", "Org over monthly cap");
    expect(getAssistantErrorMessage(err)).toBe("Org over monthly cap");
  });

  test("falls back to Error.message for plain errors", () => {
    const err = new Error("network failure");
    expect(getAssistantErrorMessage(err)).toBe("network failure");
  });

  test("returns vi-VN fallback for unknown error shapes", () => {
    // `throw "boom"` (string), `throw {}` (bare object), `throw 42`
    // — all hit the catch-all branch. Pin so the UI never shows a
    // raw "[object Object]" or empty string.
    const out1 = getAssistantErrorMessage("boom");
    const out2 = getAssistantErrorMessage({});
    const out3 = getAssistantErrorMessage(42);
    for (const out of [out1, out2, out3]) {
      expect(out).toContain("Đã xảy ra lỗi");
    }
  });
});
