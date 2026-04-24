import type { Envelope } from "@aec/types/envelope";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  token: string;
  orgId: string;
}

function buildUrl(path: string, query?: ApiFetchOptions["query"]): string {
  const url = new URL(path.startsWith("http") ? path : `${BASE_URL}${path}`);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

export async function apiFetch<T>(path: string, opts: ApiFetchOptions): Promise<Envelope<T>> {
  const { body, query, token, orgId, headers, ...rest } = opts;
  const res = await fetch(buildUrl(path, query), {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Org-ID": orgId,
      ...(headers ?? {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const json = (await res.json().catch(() => ({}))) as Envelope<T>;

  if (!res.ok) {
    const err = json.errors?.[0];
    throw new ApiError(res.status, err?.code ?? String(res.status), err?.message ?? res.statusText, err?.field);
  }

  return json;
}
