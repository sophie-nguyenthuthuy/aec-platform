"use client";
import { useState } from "react";
import type { Discipline, FeeEstimateRequest, FeeEstimateResponse } from "@aec/types/winwork";

import { Button } from "../primitives/button";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";

const DISCIPLINES: Discipline[] = ["architecture", "structural", "mep", "civil"];
const PROJECT_TYPES = [
  "residential_villa",
  "residential_apartment",
  "commercial_office",
  "commercial_retail",
  "industrial",
  "infrastructure",
];

function fmt(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}

export interface FeeCalculatorProps {
  onEstimate: (req: FeeEstimateRequest) => Promise<FeeEstimateResponse>;
  loading?: boolean;
}

export function FeeCalculator({ onEstimate, loading }: FeeCalculatorProps) {
  const [discipline, setDiscipline] = useState<Discipline>("architecture");
  const [projectType, setProjectType] = useState("residential_villa");
  const [areaSqm, setAreaSqm] = useState(200);
  const [province, setProvince] = useState("");
  const [result, setResult] = useState<FeeEstimateResponse | null>(null);

  async function run() {
    const res = await onEstimate({
      discipline,
      project_type: projectType,
      area_sqm: areaSqm,
      country_code: "VN",
      province: province || undefined,
    });
    setResult(res);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Quick fee estimate</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <Label>Discipline</Label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
              value={discipline}
              onChange={(e) => setDiscipline(e.target.value as Discipline)}
            >
              {DISCIPLINES.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label>Project type</Label>
            <select
              className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
              value={projectType}
              onChange={(e) => setProjectType(e.target.value)}
            >
              {PROJECT_TYPES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label>Area (m²)</Label>
            <Input
              type="number"
              value={areaSqm}
              onChange={(e) => setAreaSqm(Number(e.target.value || 0))}
            />
          </div>
          <div className="space-y-1">
            <Label>Province (optional)</Label>
            <Input value={province} onChange={(e) => setProvince(e.target.value)} />
          </div>
        </div>
        <Button onClick={run} disabled={loading}>
          {loading ? "Estimating…" : "Estimate"}
        </Button>
        {result && (
          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-2 text-xs uppercase text-muted-foreground">
              Basis: {result.basis} · Confidence {Math.round(result.confidence * 100)}%
            </div>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <div className="text-muted-foreground">Low ({result.fee_percent_low}%)</div>
                <div className="text-lg font-semibold">{fmt(result.fee_low_vnd)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">Mid ({result.fee_percent_mid}%)</div>
                <div className="text-lg font-semibold">{fmt(result.fee_mid_vnd)}</div>
              </div>
              <div>
                <div className="text-muted-foreground">High ({result.fee_percent_high}%)</div>
                <div className="text-lg font-semibold">{fmt(result.fee_high_vnd)}</div>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
