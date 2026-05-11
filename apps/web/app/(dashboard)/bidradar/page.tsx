"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { MatchFilters, TenderCard } from "@aec/ui/bidradar";
import type { MatchStatus } from "@aec/ui/bidradar";
import { Button, EmptyState, PageHeader, Spinner } from "@aec/ui/primitives";
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
      <PageHeader
        title="Hồ sơ đấu thầu phù hợp"
        description={`${data?.total ?? 0} hồ sơ · AI xếp hạng theo hồ sơ công ty`}
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => scrape.mutate({ source: "mua-sam-cong.gov.vn" })}
              loading={scrape.isPending}
            >
              {scrape.isPending ? "Đang thu thập..." : "Thu thập cổng VN"}
            </Button>
            <Button
              size="sm"
              onClick={() => score.mutate({ rescore_existing: false })}
              loading={score.isPending}
            >
              {score.isPending ? "Đang chấm điểm..." : "Chấm điểm lại"}
            </Button>
          </>
        }
      />

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
        <div className="flex justify-center py-8">
          <Spinner label="Đang tải" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="Chưa có hồ sơ phù hợp."
          description="Cập nhật hồ sơ công ty và thu thập nguồn dữ liệu để bắt đầu."
        />
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
