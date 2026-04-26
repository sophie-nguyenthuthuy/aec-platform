export const submittalsKeys = {
  all: ["submittals"] as const,
  list: (filters: object = {}) => ["submittals", "list", filters] as const,
  detail: (id: string) => ["submittals", "detail", id] as const,
  rfiSimilar: (rfiId: string) => ["submittals", "rfi-similar", rfiId] as const,
  rfiDraft: (rfiId: string) => ["submittals", "rfi-draft", rfiId] as const,
} as const;
