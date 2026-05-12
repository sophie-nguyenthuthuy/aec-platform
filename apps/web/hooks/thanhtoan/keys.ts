export const thanhtoanKeys = {
  all: ["thanhtoan"] as const,
  claims: (filters: object) => ["thanhtoan", "claims", filters] as const,
  claim: (id: string) => ["thanhtoan", "claim", id] as const,
  cumulative: (id: string) => ["thanhtoan", "claim", id, "cumulative"] as const,
};
