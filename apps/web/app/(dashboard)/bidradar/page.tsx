"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { MatchFilters, TenderCard } from "@aec/ui/bidradar";
import type { MatchStatus } from "@aec/ui/bidradar";
import {
  useMatches,
  useUpdateMatchStatus,
  useCreateProposal,
  useTriggerScrape,
  useScoreMatches,
} from "@/hooks/bidradar";

export default function BidRadarMatchesPage() {
  const router = useRouter();
  const [status, setStatus] = useState<MatchStatus | "all">("new");
  const [minScore, setMinScore] = useState(50);
  const [recommendedOnly, setRecommendedOnly] = useState(false);

  const { data, isLoading } = useMatches({
    status: status === "all" ? undefined : status,
    min_score: minScore || undefined,
    recommended_only: recommendedOnly,
  });
  const updateStatus = useUpdateMatchStatus();
  const createProposal = useCreateProposal();
  const scrape = useTriggerScrape();
  const score = useScoreMatches();

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            Your tender matches
          </h2>
          <p className="text-sm text-slate-500">
            {data?.total ?? 0} matches · AI-ranked by fit to your firm profile
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => scrape.mutate({ source: "mua-sam-cong.gov.vn" })}
            disabled={scrape.isPending}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {scrape.isPending ? "Scraping…" : "Scrape Vietnam portal"}
          </button>
          <button
            type="button"
            onClick={() => score.mutate({ rescore_existing: false })}
            disabled={score.isPending}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
          >
            {score.isPending ? "Scoring…" : "Re-score matches"}
          </button>
        </div>
      </div>

      <MatchFilters
        status={status}
        minScore={minScore}
        recommendedOnly={recommendedOnly}
        onChange={(next) => {
          setStatus(next.status);
          setMinScore(next.minScore);
          setRecommendedOnly(next.recommendedOnly);
        }}
      />

      {isLoading ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Loading matches…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          No matches yet. Set up your firm profile and scrape a source to get started.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((m) => (
            <TenderCard
              key={m.id}
              match={m}
              onSave={(id) => updateStatus.mutate({ matchId: id, status: "saved" })}
              onPass={(id) => updateStatus.mutate({ matchId: id, status: "passed" })}
              onCreateProposal={async (id) => {
                const res = await createProposal.mutateAsync(id);
                router.push(res.winwork_url as Route);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
