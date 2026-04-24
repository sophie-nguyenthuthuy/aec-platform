export interface Meta {
  page?: number | null;
  per_page?: number | null;
  total?: number | null;
}

export interface ErrorDetail {
  code: string;
  message: string;
  field?: string | null;
}

export interface Envelope<T> {
  data: T | null;
  meta: Meta | null;
  errors: ErrorDetail[] | null;
}

export type UUID = string;
export type ISODate = string;
