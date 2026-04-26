export const changeOrderKeys = {
  all: ["changeorder"] as const,
  list: (filters: object = {}) => ["changeorder", "list", filters] as const,
  detail: (id: string) => ["changeorder", "detail", id] as const,
  candidates: (projectId: string) =>
    ["changeorder", "candidates", projectId] as const,
} as const;
