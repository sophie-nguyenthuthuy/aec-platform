export const punchListKeys = {
  all: ["punchlist"] as const,
  list: (filters: object = {}) => ["punchlist", "list", filters] as const,
  detail: (id: string) => ["punchlist", "detail", id] as const,
} as const;
