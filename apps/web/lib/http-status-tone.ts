/**
 * HTTP status code → severity tone mapper (cycle EE3, TS half).
 *
 * Used by:
 *   * The webhook delivery row badge — color the response code.
 *   * The audit retry trail's status pill.
 *   * The dead-letter dashboard.
 *   * The Slack alert digest tone selector (the failure card
 *     uses a different background tint depending on whether
 *     the failed delivery was a 4xx or 5xx).
 *
 *   classifyStatus(code)  — { severity, tone }
 *   SEVERITIES            — closed severity list
 *   TONES                 — closed Tailwind tone list (parallel)
 *
 * Pure TS, no React. Mirrors `apps/api/services/http_status_tone.py`.
 */


export type Severity = "success" | "redirect" | "client_error" | "server_error" | "unknown";

export type Tone = "emerald" | "sky" | "amber" | "rose" | "zinc";

export interface StatusTone {
  severity: Severity;
  tone: Tone;
}


/** Closed severity list. Order matches TONES so the index
 *  positions parallel. Pin via test. */
export const SEVERITIES: readonly Severity[] = [
  "success",
  "redirect",
  "client_error",
  "server_error",
  "unknown",
];


/** Closed tone list. Tailwind-compatible color names — pin so
 *  a refactor that swaps to a Tailwind-incompatible tone (e.g.
 *  "danger") would break every consuming component's class
 *  generation. */
export const TONES: readonly Tone[] = ["emerald", "sky", "amber", "rose", "zinc"];


const _UNKNOWN: StatusTone = { severity: "unknown", tone: "zinc" };


/**
 * Classify an HTTP status code into a severity bucket + tone.
 *
 *   * 2xx → { success, emerald }
 *   * 3xx → { redirect, sky }
 *   * 4xx → { client_error, amber }   ← 408, 429 are HERE (not 5xx)
 *   * 5xx → { server_error, rose }
 *   * 1xx / 6xx+ / null / NaN → { unknown, zinc }
 *
 * 408 (Request Timeout) and 429 (Too Many Requests) are
 * client_error per the spec — they signal the client is at
 * fault (took too long, sent too many requests). Pin so a
 * "treat 408 as server_error because the connection died"
 * shortcut doesn't slip in.
 */
export function classifyStatus(
  code: number | null | undefined,
): StatusTone {
  if (code === null || code === undefined) return _UNKNOWN;
  if (!Number.isFinite(code)) return _UNKNOWN;
  const c = Math.floor(code);
  if (c >= 200 && c < 300) return { severity: "success", tone: "emerald" };
  if (c >= 300 && c < 400) return { severity: "redirect", tone: "sky" };
  if (c >= 400 && c < 500) return { severity: "client_error", tone: "amber" };
  if (c >= 500 && c < 600) return { severity: "server_error", tone: "rose" };
  return _UNKNOWN;
}
