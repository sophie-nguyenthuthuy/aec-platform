export const codeguardKeys = {
  all: ["codeguard"] as const,
  // `object` (not `Record<string, unknown>`) so callers can pass any typed
  // filter interface without needing an explicit index signature.
  regulations: (filters: object = {}) =>
    ["codeguard", "regulations", filters] as const,
  regulation: (id: string) => ["codeguard", "regulations", id] as const,
  checks: (projectId: string) => ["codeguard", "checks", projectId] as const,
  checklist: (id: string) => ["codeguard", "checklist", id] as const,
} as const;
