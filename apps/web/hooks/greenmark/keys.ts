export const greenmarkKeys = {
  all: ["greenmark"] as const,
  certs: (filters: object) => ["greenmark", "certs", filters] as const,
  cert: (id: string) => ["greenmark", "cert", id] as const,
  gap: (id: string) => ["greenmark", "cert", id, "gap"] as const,
};
