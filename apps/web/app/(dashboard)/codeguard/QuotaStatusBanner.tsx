"use client";

import { AlertTriangle, Info } from "lucide-react";

import { useCodeguardQuota, type CodeguardQuota } from "@/hooks/codeguard";

/** Banner thresholds — pinned at module scope so an ops-tunable
 *  warning level is one PR away. Below 80% the banner is hidden;
 *  80-95% renders yellow ("approaching"), 95%+ renders red ("imminent
 *  cap"). The numbers are deliberately conservative: yellow gives a
 *  user multi-day notice in typical usage patterns, red gives a clear
 *  "next request might 429" signal. */
const WARN_PCT = 80;
const CRITICAL_PCT = 95;

export function QuotaStatusBanner() {
  const { data, isLoading, isError } = useCodeguardQuota();

  // Hide entirely while loading or on error. The banner is purely
  // advisory — failing to surface it shouldn't block the user from
  // working, and a "loading quota..." flash on every page mount would
  // be more distracting than helpful.
  if (isLoading || isError || !data) return null;

  // Unlimited orgs (no quota row) → nothing to show.
  if (data.unlimited) return null;

  const binding = pickBindingDimension(data);
  if (binding === null) return null;

  // Below the warn threshold — usage is well within bounds, the banner
  // would just be visual noise. Pin so the threshold is the only knob.
  if (binding.percent < WARN_PCT) return null;

  const isCritical = binding.percent >= CRITICAL_PCT;
  const palette = isCritical
    ? {
        // Red: cap is imminent, next request may 429.
        wrap: "border-red-200 bg-red-50 text-red-900",
        icon: "text-red-700",
        bar: "bg-red-500",
        track: "bg-red-100",
      }
    : {
        // Yellow: approaching the cap, finance/admin should be told.
        wrap: "border-amber-200 bg-amber-50 text-amber-900",
        icon: "text-amber-700",
        bar: "bg-amber-500",
        track: "bg-amber-100",
      };

  return (
    <div
      role="status"
      aria-live="polite"
      className={`mx-auto w-full max-w-7xl px-6 pt-3`}
    >
      <div className={`rounded-lg border px-4 py-3 text-sm ${palette.wrap}`}>
        <div className="flex items-start gap-2">
          <AlertTriangle size={16} className={`mt-0.5 shrink-0 ${palette.icon}`} />
          <div className="flex-1 space-y-2">
            <div className="font-medium">
              {isCritical
                ? `Sắp đạt hạn mức tháng — ${binding.dimensionLabel} ở ${binding.percent.toFixed(1)}%`
                : `Đã dùng ${binding.percent.toFixed(1)}% hạn mức ${binding.dimensionLabel} trong tháng`}
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              <span>
                {binding.used.toLocaleString("vi-VN")}{" "}
                / {binding.limit?.toLocaleString("vi-VN")} token
                {data.period_start ? ` (kỳ ${data.period_start})` : ""}
              </span>
              {/* Weighted-accounting tooltip. Without this, an admin
                  comparing the banner percent to their raw-token
                  logs sees a discrepancy (a heavy /scan day pushes
                  the percent at 5× the raw-token rate) and files a
                  "your number is wrong" ticket. The tooltip text
                  matches the threshold email/Slack copy so an admin
                  reading either doesn't see two diverging
                  explanations. Native `title` attribute keeps the
                  bundle small and is keyboard-accessible. */}
              <span
                tabIndex={0}
                aria-label="Lưu ý về tính trọng số theo route"
                title="Lưu ý: các yêu cầu /scan tính 5× và /permit-checklist tính 2× so với /query để phản ánh chi phí compute thực tế."
                className="inline-flex cursor-help items-center"
              >
                <Info size={12} aria-hidden="true" className="opacity-60" />
              </span>
            </div>
            <ProgressBar
              percent={binding.percent}
              barClass={palette.bar}
              trackClass={palette.track}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

interface BindingDimension {
  /** "input" | "output" — which dimension is at the higher percent. */
  dimensionLabel: string;
  used: number;
  limit: number | null;
  percent: number;
}

/** Pick the dimension with the higher percent-of-cap. Returns null when
 *  both dimensions are null/unlimited (the banner shows nothing). */
function pickBindingDimension(quota: CodeguardQuota): BindingDimension | null {
  const candidates: BindingDimension[] = [];
  if (quota.input && quota.input.percent !== null) {
    candidates.push({
      dimensionLabel: "input",
      used: quota.input.used,
      limit: quota.input.limit,
      percent: quota.input.percent,
    });
  }
  if (quota.output && quota.output.percent !== null) {
    candidates.push({
      dimensionLabel: "output",
      used: quota.output.used,
      limit: quota.output.limit,
      percent: quota.output.percent,
    });
  }
  if (candidates.length === 0) return null;
  // Highest percent wins — that's the dimension that will trigger the
  // 429 first if usage continues, so it's the right thing to highlight.
  return candidates.reduce((a, b) => (a.percent >= b.percent ? a : b));
}

function ProgressBar({
  percent,
  barClass,
  trackClass,
}: {
  percent: number;
  barClass: string;
  trackClass: string;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div
      className={`h-1.5 w-full overflow-hidden rounded-full ${trackClass}`}
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={`h-full ${barClass}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}
