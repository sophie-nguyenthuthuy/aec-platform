/**
 * Alternative API client used by siteeye / mobile pages. Thin-envelope wrapper
 * with a different signature from `apiFetch` — kept separate so we don't churn
 * the whole codebase while parallel modules stabilize.
 *
 * Contract used by callers:
 *   apiRequest<T>(path, { method?, body?, params?, token, headers? })
 *     -> Promise<T>                               (data unwrapped)
 *
 *   apiRequestWithMeta<T>(path, { params?, token })
 *     -> Promise<{ data: T; meta: Meta }>
 */
import type { Envelope, Meta } from "@aec/types/envelope";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  token: string;
  orgId?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = new URL(path.startsWith("http") ? path : `${BASE_URL}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public field?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, opts: RequestOptions): Promise<Envelope<T>> {
  const { method = "GET", body, params, token, orgId, headers, signal } = opts;
  const init: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(orgId ? { "X-Org-ID": orgId } : {}),
      ...(headers ?? {}),
    },
    signal,
  };
  if (body !== undefined) init.body = JSON.stringify(body);

  const res = await fetch(buildUrl(path, params), init);
  const json = (await res.json().catch(() => ({}))) as Envelope<T>;
  if (!res.ok) {
    const err = json.errors?.[0];
    throw new ApiError(
      res.status,
      err?.code ?? String(res.status),
      err?.message ?? res.statusText,
      err?.field ?? undefined,
    );
  }
  return json;
}

/** Returns just the `data` payload. Throws on non-2xx. */
export async function apiRequest<T>(path: string, opts: RequestOptions): Promise<T> {
  const env = await request<T>(path, opts);
  return env.data as T;
}

/** Returns `{ data, meta }` for callers that need pagination totals. */
export async function apiRequestWithMeta<T>(
  path: string,
  opts: RequestOptions,
): Promise<{ data: T; meta: Meta }> {
  const env = await request<T>(path, opts);
  return { data: env.data as T, meta: env.meta ?? {} };
}
