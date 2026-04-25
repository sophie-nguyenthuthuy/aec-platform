// `object` (instead of Record<string, unknown>) lets typed filter interfaces
// pass without requiring an index signature.
export const drawbridgeKeys = {
  all: ["drawbridge"] as const,
  documents: (filters: object = {}) =>
    ["drawbridge", "documents", filters] as const,
  document: (id: string) => ["drawbridge", "documents", id] as const,
  documentSets: (projectId: string | undefined) =>
    ["drawbridge", "document-sets", projectId ?? "all"] as const,
  conflicts: (filters: object = {}) =>
    ["drawbridge", "conflicts", filters] as const,
  conflict: (id: string) => ["drawbridge", "conflicts", id] as const,
  rfis: (filters: object = {}) =>
    ["drawbridge", "rfis", filters] as const,
  rfi: (id: string) => ["drawbridge", "rfis", id] as const,
} as const;
