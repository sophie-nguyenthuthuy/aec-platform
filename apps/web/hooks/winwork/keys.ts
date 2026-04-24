import type { ProposalStatus } from "@aec/types/winwork";

export const winworkKeys = {
  all: ["winwork"] as const,
  proposals: () => [...winworkKeys.all, "proposals"] as const,
  proposalList: (filters: { page: number; per_page: number; status?: ProposalStatus; q?: string }) =>
    [...winworkKeys.proposals(), "list", filters] as const,
  proposalDetail: (id: string) => [...winworkKeys.proposals(), "detail", id] as const,
  analytics: () => [...winworkKeys.all, "analytics", "win-rate"] as const,
  benchmarks: (filters: Record<string, unknown>) => [...winworkKeys.all, "benchmarks", filters] as const,
};
