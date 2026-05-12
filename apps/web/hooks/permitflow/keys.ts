export const permitflowKeys = {
  all: ["permitflow"] as const,
  dossiers: (filters: object) =>
    ["permitflow", "dossiers", filters] as const,
  dossier: (id: string) => ["permitflow", "dossier", id] as const,
  stages: (dossierId: string) =>
    ["permitflow", "dossier", dossierId, "stages"] as const,
  timeline: (dossierId: string) =>
    ["permitflow", "dossier", dossierId, "timeline"] as const,
  alerts: (filters: object) =>
    ["permitflow", "alerts", filters] as const,
};
