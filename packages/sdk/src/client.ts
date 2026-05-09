/**
 * Hand-written core for the auto-generated SDK methods. Lives outside
 * `generated.ts` so re-running the generator doesn't clobber the
 * retry / auth / envelope unwrap logic.
 *
 * Surface:
 *   * `AecClient(opts)` — the public entry point. Holds the api key
 *     + base URL.
 *   * `request(...)` — generic verb-typed call with retry on 429/5xx.
 *   * `Envelope<T>` — the platform's standard response shape.
 *
 * Why no third-party HTTP lib: native `fetch` is on every modern
 * runtime (node >= 18, browsers, Cloudflare Workers, Deno). One
 * fewer dep = one fewer thing partners have to reconcile in their
 * own bundle.
 */


export interface Envelope<T> {
  data: T | null;
  errors?: Array<{ message: string; code?: string }>;
  meta?: Record<string, unknown>;
}


export interface AecClientOptions {
  /** API key. Provide via env var, vault, etc. — never commit. */
  apiKey: string;
  /** Defaults to https://api.aec-platform.vn. Override for staging. */
  baseUrl?: string;
  /** Max retries on 429 / 5xx. Default 3. Set to 0 to disable. */
  maxRetries?: number;
  /** Custom fetch — pass undici, polyfill, etc. Defaults to global fetch. */
  fetch?: typeof fetch;
}


export class AecApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "AecApiError";
    this.status = status;
    this.body = body;
  }
}


export class AecClientCore {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly maxRetries: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: AecClientOptions) {
    if (!opts.apiKey) {
      throw new Error("AecClient: apiKey is required");
    }
    this.apiKey = opts.apiKey;
    this.baseUrl = (opts.baseUrl ?? "https://api.aec-platform.vn").replace(/\/$/, "");
    this.maxRetries = opts.maxRetries ?? 3;
    this.fetchImpl = opts.fetch ?? fetch;
  }

  async request<T>(
    method: string,
    path: string,
    query?: Record<string, string | number | boolean | undefined>,
    body?: unknown,
  ): Promise<T> {
    const qs = query ? toQueryString(query) : "";
    const url = `${this.baseUrl}${path}${qs}`;

    let attempt = 0;
    let delayMs = 500;
    while (true) {
      const res = await this.fetchImpl(url, {
        method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });

      // 2xx → unwrap envelope.
      if (res.ok) {
        const json = (await res.json()) as Envelope<T>;
        return json.data as T;
      }

      // 429 → respect Retry-After (in seconds).
      if (res.status === 429 && attempt < this.maxRetries) {
        const retryAfter = Number(res.headers.get("retry-after") ?? "1");
        await sleep(Math.max(retryAfter, 1) * 1000);
        attempt++;
        continue;
      }

      // 5xx → exponential backoff with jitter.
      if (res.status >= 500 && attempt < this.maxRetries) {
        await sleep(delayMs + Math.random() * 250);
        delayMs *= 2;
        attempt++;
        continue;
      }

      // Terminal error.
      let errBody: unknown = null;
      try {
        errBody = await res.json();
      } catch {
        // Body wasn't JSON — fall back to status text.
      }
      const msg = extractErrorMessage(errBody) ?? `${res.status} ${res.statusText}`;
      throw new AecApiError(res.status, msg, errBody);
    }
  }
}


function toQueryString(q: Record<string, string | number | boolean | undefined>): string {
  const pairs: string[] = [];
  for (const [k, v] of Object.entries(q)) {
    if (v === undefined) continue;
    pairs.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return pairs.length > 0 ? `?${pairs.join("&")}` : "";
}


function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}


function extractErrorMessage(body: unknown): string | null {
  // The platform's standard envelope error shape:
  //   { data: null, errors: [{ message: "..." }] }
  // Fall back gracefully if the body diverges.
  if (
    body &&
    typeof body === "object" &&
    "errors" in body &&
    Array.isArray((body as { errors: unknown[] }).errors)
  ) {
    const first = (body as { errors: { message?: string }[] }).errors[0];
    return first?.message ?? null;
  }
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    return typeof d === "string" ? d : null;
  }
  return null;
}
