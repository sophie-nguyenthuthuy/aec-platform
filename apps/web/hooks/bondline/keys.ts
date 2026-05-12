export const bondlineKeys = {
  all: ["bondline"] as const,
  bonds: (filters: object) => ["bondline", "bonds", filters] as const,
  bond: (id: string) => ["bondline", "bond", id] as const,
  alerts: (filters: object) => ["bondline", "alerts", filters] as const,
};
