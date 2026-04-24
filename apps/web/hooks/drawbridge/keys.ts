export const drawbridgeKeys = {
  all: ["drawbridge"] as const,
  documents: (filters: Record<string, unknown> = {}) =>
    ["drawbridge", "documents", filters] as const,
  document: (id: string) => ["drawbridge", "documents", id] as const,
  documentSets: (projectId: string | undefined) =>
    ["drawbridge", "document-sets", projectId ?? "all"] as const,
  conflicts: (filters: Record<string, unknown> = {}) =>
    ["drawbridge", "conflicts", filters] as const,
  conflict: (id: string) => ["drawbridge", "conflicts", id] as const,
  rfis: (filters: Record<string, unknown> = {}) =>
    ["drawbridge", "rfis", filters] as const,
  rfi: (id: string) => ["drawbridge", "rfis", id] as const,
} as const;
