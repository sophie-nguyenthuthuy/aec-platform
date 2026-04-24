"use client";
import { FeeCalculator } from "@aec/ui/winwork/FeeCalculator";
import { Card, CardContent, CardHeader, CardTitle } from "@aec/ui/primitives/card";
import { useBenchmarks } from "@/hooks/winwork/useBenchmarks";
import { useFeeEstimate } from "@/hooks/winwork/useFeeEstimate";

export default function BenchmarksPage() {
  const { data: benchmarks } = useBenchmarks();
  const estimate = useFeeEstimate();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Fee benchmarks</h1>
        <p className="text-sm text-muted-foreground">Reference rates and a quick estimator.</p>
      </div>

      <FeeCalculator
        loading={estimate.isPending}
        onEstimate={(req) => estimate.mutateAsync(req)}
      />

      <Card>
        <CardHeader>
          <CardTitle>Benchmark rows</CardTitle>
        </CardHeader>
        <CardContent>
          {(benchmarks ?? []).length === 0 ? (
            <div className="text-sm text-muted-foreground">No benchmarks loaded.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase text-muted-foreground">
                  <th className="py-2">Discipline</th>
                  <th>Project type</th>
                  <th>Province</th>
                  <th className="text-right">Low %</th>
                  <th className="text-right">Mid %</th>
                  <th className="text-right">High %</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {(benchmarks ?? []).map((b) => (
                  <tr key={b.id} className="border-b last:border-0">
                    <td className="py-2">{b.discipline}</td>
                    <td>{b.project_type}</td>
                    <td>{b.province ?? "—"}</td>
                    <td className="text-right">{String(b.fee_percent_low ?? "—")}</td>
                    <td className="text-right">{String(b.fee_percent_mid ?? "—")}</td>
                    <td className="text-right">{String(b.fee_percent_high ?? "—")}</td>
                    <td>{b.source ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
