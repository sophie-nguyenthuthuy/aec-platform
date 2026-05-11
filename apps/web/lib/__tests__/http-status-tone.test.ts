/**
 * HTTP status code → severity tone mapper (cycle EE3, TS half).
 *
 * Pinned seams:
 *   1. SEVERITIES = [success, redirect, client_error, server_error, unknown].
 *   2. TONES     = [emerald, sky, amber, rose, zinc] (parallel order).
 *   3. 2xx → success/emerald.
 *   4. 3xx → redirect/sky.
 *   5. 4xx → client_error/amber (408, 429 included).
 *   6. 5xx → server_error/rose.
 *   7. 1xx, 6xx+, null, NaN → unknown/zinc.
 */

import { describe, expect, it } from "vitest";

import {
  SEVERITIES,
  TONES,
  classifyStatus,
} from "../http-status-tone";


// ---------- Constants ----------


describe("SEVERITIES", () => {
  it("is the canonical 5-bucket closed list", () => {
    expect(SEVERITIES).toEqual([
      "success",
      "redirect",
      "client_error",
      "server_error",
      "unknown",
    ]);
  });
});


describe("TONES", () => {
  it("is the canonical Tailwind-compatible 5-tone list", () => {
    // Pin: NOT "danger", "warn", "ok" — those wouldn't generate
    // valid Tailwind class names.
    expect(TONES).toEqual(["emerald", "sky", "amber", "rose", "zinc"]);
  });

  it("is the same length as SEVERITIES (parallel arrays)", () => {
    expect(TONES.length).toBe(SEVERITIES.length);
  });
});


// ---------- 2xx success ----------


describe("classifyStatus — 2xx success", () => {
  it("classifies 200 as success/emerald", () => {
    expect(classifyStatus(200)).toEqual({ severity: "success", tone: "emerald" });
  });

  it("classifies 201, 204, 299 as success", () => {
    for (const code of [201, 204, 299]) {
      expect(classifyStatus(code).severity).toBe("success");
    }
  });
});


// ---------- 3xx redirect ----------


describe("classifyStatus — 3xx redirect", () => {
  it("classifies 301 as redirect/sky", () => {
    expect(classifyStatus(301)).toEqual({ severity: "redirect", tone: "sky" });
  });

  it("classifies 302, 307, 308 as redirect", () => {
    for (const code of [302, 307, 308]) {
      expect(classifyStatus(code).severity).toBe("redirect");
    }
  });
});


// ---------- 4xx client error ----------


describe("classifyStatus — 4xx client_error", () => {
  it("classifies 400 as client_error/amber", () => {
    expect(classifyStatus(400)).toEqual({ severity: "client_error", tone: "amber" });
  });

  it("classifies 404 as client_error", () => {
    expect(classifyStatus(404).severity).toBe("client_error");
  });

  it("classifies 408 (Request Timeout) as client_error (NOT server_error)", () => {
    // Pin: 408 is HTTP-spec client_error — the client is at fault
    // for taking too long. A "treat 408 as server_error because
    // the network died" shortcut would mis-classify the failure
    // card in the Slack digest.
    expect(classifyStatus(408)).toEqual({ severity: "client_error", tone: "amber" });
  });

  it("classifies 429 (Too Many Requests) as client_error", () => {
    // Pin: 429 is client_error — the client made too many
    // requests. NOT server_error.
    expect(classifyStatus(429)).toEqual({ severity: "client_error", tone: "amber" });
  });

  it("classifies 422, 499 as client_error (range boundary)", () => {
    expect(classifyStatus(422).severity).toBe("client_error");
    expect(classifyStatus(499).severity).toBe("client_error");
  });
});


// ---------- 5xx server error ----------


describe("classifyStatus — 5xx server_error", () => {
  it("classifies 500 as server_error/rose", () => {
    expect(classifyStatus(500)).toEqual({ severity: "server_error", tone: "rose" });
  });

  it("classifies 502, 503, 504 as server_error", () => {
    for (const code of [502, 503, 504]) {
      expect(classifyStatus(code).severity).toBe("server_error");
    }
  });

  it("classifies 599 as server_error (range boundary)", () => {
    expect(classifyStatus(599).severity).toBe("server_error");
  });
});


// ---------- Unknown / boundaries ----------


describe("classifyStatus — unknown", () => {
  it("classifies 1xx as unknown (rare in webhook delivery context)", () => {
    expect(classifyStatus(100)).toEqual({ severity: "unknown", tone: "zinc" });
    expect(classifyStatus(199)).toEqual({ severity: "unknown", tone: "zinc" });
  });

  it("classifies 600+ as unknown", () => {
    expect(classifyStatus(600)).toEqual({ severity: "unknown", tone: "zinc" });
    expect(classifyStatus(999)).toEqual({ severity: "unknown", tone: "zinc" });
  });

  it("classifies 0 and negatives as unknown", () => {
    expect(classifyStatus(0)).toEqual({ severity: "unknown", tone: "zinc" });
    expect(classifyStatus(-1)).toEqual({ severity: "unknown", tone: "zinc" });
  });

  it("classifies null / undefined / NaN / Infinity as unknown", () => {
    expect(classifyStatus(null)).toEqual({ severity: "unknown", tone: "zinc" });
    expect(classifyStatus(undefined)).toEqual({ severity: "unknown", tone: "zinc" });
    expect(classifyStatus(Number.NaN)).toEqual({ severity: "unknown", tone: "zinc" });
    expect(classifyStatus(Number.POSITIVE_INFINITY)).toEqual({ severity: "unknown", tone: "zinc" });
  });
});


// ---------- Boundary values ----------


describe("classifyStatus — exact range boundaries", () => {
  it("199 is unknown, 200 is success", () => {
    expect(classifyStatus(199).severity).toBe("unknown");
    expect(classifyStatus(200).severity).toBe("success");
  });

  it("299 is success, 300 is redirect", () => {
    expect(classifyStatus(299).severity).toBe("success");
    expect(classifyStatus(300).severity).toBe("redirect");
  });

  it("399 is redirect, 400 is client_error", () => {
    expect(classifyStatus(399).severity).toBe("redirect");
    expect(classifyStatus(400).severity).toBe("client_error");
  });

  it("499 is client_error, 500 is server_error", () => {
    expect(classifyStatus(499).severity).toBe("client_error");
    expect(classifyStatus(500).severity).toBe("server_error");
  });
});
