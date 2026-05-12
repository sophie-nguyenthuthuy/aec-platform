export const pcccKeys = {
  all: ["pccc"] as const,
  certs: (filters: object) => ["pccc", "certs", filters] as const,
  cert: (id: string) => ["pccc", "cert", id] as const,
  alerts: (filters: object) => ["pccc", "alerts", filters] as const,
};
