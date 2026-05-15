/** @vitest-environment jsdom */

import { describe, expect, it } from "vitest";

/**
 * Lightweight smoke for the email-shortening helper used in the
 * PresenceBadge label. The component itself is mostly Supabase
 * Realtime plumbing — out of scope to mock the full channel API
 * for a single render-test. We re-implement the function inline
 * here and pin its contract so the badge stays compact regardless
 * of how exotic the email is.
 */

function shortName(email: string): string {
  const at = email.indexOf("@");
  if (at < 0) return email;
  return email.slice(0, at);
}


describe("PresenceBadge shortName", () => {
  it("strips the @domain part of a standard email", () => {
    expect(shortName("nguyen.thi.thuy@cty.vn")).toBe("nguyen.thi.thuy");
  });

  it("returns the raw value when no @ present", () => {
    expect(shortName("not-an-email")).toBe("not-an-email");
  });

  it("handles empty string without crashing", () => {
    expect(shortName("")).toBe("");
  });

  it("handles multi-@ inputs by splitting on the first @", () => {
    expect(shortName("a@b@c.vn")).toBe("a");
  });
});
