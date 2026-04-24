export const bidradarKeys = {
  all: ["bidradar"] as const,
  profile: () => [...bidradarKeys.all, "profile"] as const,
  tenders: (filters: Record<string, unknown>) =>
    [...bidradarKeys.all, "tenders", filters] as const,
  tender: (id: string) => [...bidradarKeys.all, "tender", id] as const,
  matches: (filters: Record<string, unknown>) =>
    [...bidradarKeys.all, "matches", filters] as const,
  match: (id: string) => [...bidradarKeys.all, "match", id] as const,
  digests: () => [...bidradarKeys.all, "digests"] as const,
};
