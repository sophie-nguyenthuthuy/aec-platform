"use client";

import { useMemo } from "react";
import type { PriceHistoryPoint } from "@aec/types";

import { cn } from "../lib/cn";
import { formatPct, formatVnd } from "./formatters";

interface PriceTrendChartProps {
  points: PriceHistoryPoint[];
  pctChange30d?: number | null;
  pctChange1y?: number | null;
  height?: number;
  className?: string;
  sparkline?: boolean;
}

export function PriceTrendChart({
  points,
  pctChange30d,
  pctChange1y,
  height = 180,
  className,
  sparkline = false,
}: PriceTrendChartProps): JSX.Element {
  const { path, area, min, max, latest } = useMemo(() => {
    if (points.length === 0) {
      return { path: "", area: "", min: 0, max: 0, latest: null };
    }
    const values = points.map((p) => Number(p.price_vnd));
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const span = hi - lo || 1;
    const w = 100;
    const h = 100;
    const step = points.length > 1 ? w / (points.length - 1) : 0;

    const coords = points.map((p, i) => {
      const v = Number(p.price_vnd);
      const x = i * step;
      const y = h - ((v - lo) / span) * h;
      return [x, y] as const;
    });

    const linePath = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
    const areaPath = `${linePath} L${coords[coords.length - 1]![0].toFixed(2)},${h} L0,${h} Z`;

    return {
      path: linePath,
      area: areaPath,
      min: lo,
      max: hi,
      latest: points[points.length - 1] ?? null,
    };
  }, [points]);

  const trendUp = (pctChange30d ?? 0) >= 0;

  if (sparkline) {
    return (
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className={cn("h-8 w-24", className)}
      >
        <path d={path} fill="none" stroke={trendUp ? "#ef4444" : "#10b981"} strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3 rounded-lg border border-slate-200 p-4", className)}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Latest price</div>
          <div className="text-2xl font-bold text-slate-900">
            {latest ? formatVnd(latest.price_vnd) : "—"}
          </div>
        </div>
        <div className="space-y-1 text-right text-xs">
          <div>
            <span className="text-slate-500">30d:</span>{" "}
            <span className={cn("font-semibold", (pctChange30d ?? 0) > 0 ? "text-red-600" : "text-emerald-600")}>
              {formatPct(pctChange30d)}
            </span>
          </div>
          <div>
            <span className="text-slate-500">1y:</span>{" "}
            <span className={cn("font-semibold", (pctChange1y ?? 0) > 0 ? "text-red-600" : "text-emerald-600")}>
              {formatPct(pctChange1y)}
            </span>
          </div>
        </div>
      </div>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        style={{ height }}
        className="w-full"
      >
        <path d={area} fill="rgba(14,165,233,0.12)" />
        <path d={path} fill="none" stroke="#0ea5e9" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-xs text-slate-500">
        <span>Min {formatVnd(min)}</span>
        <span>Max {formatVnd(max)}</span>
      </div>
    </div>
  );
}
