export const workforceKeys = {
  all: ["workforce"] as const,
  workers: (filters: object) => ["workforce", "workers", filters] as const,
  worker: (id: string) => ["workforce", "worker", id] as const,
  contribution: (id: string) =>
    ["workforce", "worker", id, "contribution"] as const,
  manifest: (projectId: string) =>
    ["workforce", "manifest", projectId] as const,
  alerts: (filters: object) => ["workforce", "alerts", filters] as const,
};
