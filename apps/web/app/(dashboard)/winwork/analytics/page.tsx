"use client";
import { WinRateDashboard } from "@aec/ui/winwork/WinRateDashboard";
import { useWinRateAnalytics } from "@/hooks/winwork/useWinRateAnalytics";

export default function WinworkAnalyticsPage() {
  const { data, isLoading } = useWinRateAnalytics();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Win rate analytics</h1>
        <p className="text-sm text-muted-foreground">How proposals convert to wins over time.</p>
      </div>
      {isLoading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : data ? (
        <WinRateDashboard data={data} />
      ) : (
        <div className="text-sm text-muted-foreground">No data yet.</div>
      )}
    </div>
  );
}
