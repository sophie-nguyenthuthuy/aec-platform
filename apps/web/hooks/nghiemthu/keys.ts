export const nghiemthuKeys = {
  all: ["nghiemthu"] as const,
  records: (filters: object) =>
    ["nghiemthu", "records", filters] as const,
  record: (id: string) => ["nghiemthu", "record", id] as const,
};
