// `object` (instead of Record<string, unknown>) lets typed filter interfaces
// pass without requiring an index signature.
export const handoverKeys = {
  all: ["handover"] as const,
  packages: (filters: object = {}) =>
    ["handover", "packages", filters] as const,
  package: (id: string) => ["handover", "packages", id] as const,
  asBuilts: (projectId: string, discipline?: string) =>
    ["handover", "as-builts", projectId, discipline ?? "all"] as const,
  omManuals: (packageId: string) =>
    ["handover", "om-manuals", packageId] as const,
  warranties: (filters: object = {}) =>
    ["handover", "warranties", filters] as const,
  defects: (filters: object = {}) =>
    ["handover", "defects", filters] as const,
} as const;
