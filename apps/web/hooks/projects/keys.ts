// `object` (instead of Record<string, unknown>) lets typed filter interfaces
// pass without requiring an index signature.
export const projectKeys = {
  all: ["projects"] as const,
  list: (filters: object = {}) => ["projects", "list", filters] as const,
  detail: (id: string) => ["projects", "detail", id] as const,
} as const;
