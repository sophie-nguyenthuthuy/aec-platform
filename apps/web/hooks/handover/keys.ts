export const handoverKeys = {
  all: ["handover"] as const,
  packages: (filters: Record<string, unknown> = {}) =>
    ["handover", "packages", filters] as const,
  package: (id: string) => ["handover", "packages", id] as const,
  asBuilts: (projectId: string, discipline?: string) =>
    ["handover", "as-builts", projectId, discipline ?? "all"] as const,
  omManuals: (packageId: string) =>
    ["handover", "om-manuals", packageId] as const,
  warranties: (filters: Record<string, unknown> = {}) =>
    ["handover", "warranties", filters] as const,
  defects: (filters: Record<string, unknown> = {}) =>
    ["handover", "defects", filters] as const,
} as const;
