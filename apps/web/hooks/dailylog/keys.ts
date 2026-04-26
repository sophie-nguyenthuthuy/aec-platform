export const dailylogKeys = {
  all: ["dailylog"] as const,
  list: (filters: object = {}) => ["dailylog", "list", filters] as const,
  detail: (id: string) => ["dailylog", "detail", id] as const,
  patterns: (projectId: string, range: object) =>
    ["dailylog", "patterns", projectId, range] as const,
} as const;
