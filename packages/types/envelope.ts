export interface Meta {
  page?: number | null;
  per_page?: number | null;
  total?: number | null;
}

export interface ErrorDetail {
  code: string;
  message: string;
  field?: string | null;
  /**
   * Optional in-app URL the client can deep-link the user to for
   * context on this error. Today only the codeguard cap-check 429
   * populates it (→ "/codeguard/quota"). Treat null as "no CTA" —
   * render a plain toast / inline error without an action button.
   */
  details_url?: string | null;
}

export interface Envelope<T> {
  data: T | null;
  meta: Meta | null;
  errors: ErrorDetail[] | null;
}

export type UUID = string;
export type ISODate = string;
