"use client";

import { useMemo, useState } from "react";

import type { Activity, Dependency } from "@/hooks/schedule";


/**
 * SVG Gantt chart for SchedulePilot.
 *
 * Why SVG (not a chart library):
 *   * Zero new deps — `recharts`/`visx`/`d3-gantt` would each be
 *     30-100kB minified for a single view that only renders bars
 *     and lines.
 *   * Vector output prints cleanly to PDF (the project-summary PDF
 *     can later embed the same SVG).
 *   * Fits naturally with React refs + Tailwind text classes for
 *     hover states and a11y.
 *
 * Layout:
 *   ┌────────────┬──────────────────────────────────────────────┐
 *   │ Mã / Tên   │ TimelineHeader: month + day tick marks       │
 *   ├────────────┼──────────────────────────────────────────────┤
 *   │ 1.1 Móng   │ ──────[BASELINE]──────                       │
 *   │            │     [█████PLANNED█] (progress overlay)       │
 *   │ 1.2 Cột    │   ─────────[BASELINE]──────────              │
 *   │            │       [██PLANNED]                            │
 *   └────────────┴──────────────────────────────────────────────┘
 *
 * Each row: 3-stack bar
 *   - thin grey bar above   = baseline (frozen)
 *   - mid coloured bar      = planned (current schedule)
 *   - dark overlay          = actual progress (percent_complete)
 *
 * Plus a vertical "today" line. Dependency arrows are simple
 * orthogonal connectors from predecessor.finish to successor.start
 * — straight + 90° elbow, no fancy curves.
 *
 * Critical path activities get a rose tint on the planned bar.
 */

const ROW_HEIGHT = 32;
const HEADER_HEIGHT = 40;
const LEFT_COL_PX = 220;
const RIGHT_GUTTER_PX = 12;
const DAY = 86_400_000;


interface Props {
  activities: Activity[];
  dependencies: Dependency[];
  criticalCodes: Set<string>;
  /** Optional baseline-frozen flag; controls whether baseline bars render. */
  baselineFrozen?: boolean;
}


export function GanttChart({
  activities,
  dependencies,
  criticalCodes,
  baselineFrozen = false,
}: Props) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  // ---- Compute date axis ----
  // Use the union of baseline + planned + actual ranges so a freshly
  // re-baselined schedule still fits on screen.
  const { axisStart, axisEnd, totalDays } = useMemo(() => {
    let lo: number | null = null;
    let hi: number | null = null;
    for (const a of activities) {
      const dates = [
        a.planned_start,
        a.planned_finish,
        a.baseline_start,
        a.baseline_finish,
        a.actual_start,
        a.actual_finish,
      ].filter(Boolean) as string[];
      for (const d of dates) {
        const t = new Date(d).getTime();
        if (lo === null || t < lo) lo = t;
        if (hi === null || t > hi) hi = t;
      }
    }
    if (lo === null || hi === null) {
      const now = Date.now();
      lo = now;
      hi = now + 30 * DAY;
    }
    // Pad +-2 days so the leftmost/rightmost bars don't kiss the edge.
    lo -= 2 * DAY;
    hi += 2 * DAY;
    const days = Math.max(7, Math.ceil((hi - lo) / DAY));
    return {
      axisStart: lo,
      axisEnd: hi,
      totalDays: days,
    };
  }, [activities]);

  // Pixels-per-day. Dynamic so a 6-month schedule fits without scroll;
  // a 3-year schedule horizontal-scrolls but stays readable.
  const PX_PER_DAY = totalDays <= 60 ? 14 : totalDays <= 180 ? 5 : 2.5;
  const chartWidth = totalDays * PX_PER_DAY + RIGHT_GUTTER_PX;
  const chartHeight = HEADER_HEIGHT + activities.length * ROW_HEIGHT;

  // ---- Index activities by ID for dependency arrows ----
  const byId = useMemo(() => {
    const m = new Map<string, { activity: Activity; rowIndex: number }>();
    activities.forEach((a, i) => m.set(a.id, { activity: a, rowIndex: i }));
    return m;
  }, [activities]);

  // ---- Helpers ----
  function xFromDate(iso: string): number {
    return ((new Date(iso).getTime() - axisStart) / DAY) * PX_PER_DAY;
  }

  function todayX(): number | null {
    const now = Date.now();
    if (now < axisStart || now > axisEnd) return null;
    return ((now - axisStart) / DAY) * PX_PER_DAY;
  }

  const monthTicks = useMemo(() => buildMonthTicks(axisStart, axisEnd, PX_PER_DAY), [
    axisStart,
    axisEnd,
    PX_PER_DAY,
  ]);

  const tx = todayX();

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <div className="flex">
        {/* Left frozen column — activity code + name */}
        <div
          className="shrink-0 border-r border-slate-200"
          style={{ width: LEFT_COL_PX }}
        >
          <div
            className="flex items-end border-b border-slate-200 bg-slate-50 px-3 pb-2 text-[10px] uppercase tracking-wide text-slate-500"
            style={{ height: HEADER_HEIGHT }}
          >
            Mã & Tên hoạt động
          </div>
          {activities.map((a) => (
            <div
              key={a.id}
              onMouseEnter={() => setHoveredId(a.id)}
              onMouseLeave={() => setHoveredId(null)}
              className={`flex items-center gap-2 border-b border-slate-100 px-3 text-xs ${
                hoveredId === a.id ? "bg-slate-50" : ""
              }`}
              style={{ height: ROW_HEIGHT }}
            >
              <span className="w-12 shrink-0 truncate font-mono text-slate-500">
                {a.code}
              </span>
              <span className="truncate text-slate-900">{a.name}</span>
            </div>
          ))}
        </div>

        {/* Right scrollable chart area */}
        <div className="flex-1 overflow-x-auto">
          <svg
            width={chartWidth}
            height={chartHeight}
            className="block"
            role="img"
            aria-label={`Biểu đồ Gantt với ${activities.length} hoạt động`}
          >
            {/* Month ticks */}
            <g>
              {monthTicks.map((t) => (
                <g key={t.x}>
                  <line
                    x1={t.x}
                    y1={0}
                    x2={t.x}
                    y2={chartHeight}
                    stroke="#e2e8f0"
                    strokeWidth={1}
                  />
                  <text
                    x={t.x + 4}
                    y={HEADER_HEIGHT - 24}
                    fontSize={11}
                    fontWeight={600}
                    fill="#475569"
                  >
                    {t.label}
                  </text>
                </g>
              ))}
            </g>

            {/* Header weekday band */}
            <rect
              x={0}
              y={0}
              width={chartWidth}
              height={HEADER_HEIGHT}
              fill="#f8fafc"
              opacity={0.6}
            />
            <line
              x1={0}
              y1={HEADER_HEIGHT}
              x2={chartWidth}
              y2={HEADER_HEIGHT}
              stroke="#cbd5e1"
              strokeWidth={1}
            />

            {/* Today vertical line */}
            {tx !== null && (
              <g>
                <line
                  x1={tx}
                  y1={0}
                  x2={tx}
                  y2={chartHeight}
                  stroke="#ef4444"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  opacity={0.7}
                />
                <text
                  x={tx + 3}
                  y={HEADER_HEIGHT - 4}
                  fontSize={10}
                  fill="#ef4444"
                  fontWeight={600}
                >
                  Hôm nay
                </text>
              </g>
            )}

            {/* Activity bars */}
            {activities.map((a, i) => {
              const yTop = HEADER_HEIGHT + i * ROW_HEIGHT;
              const isCrit = criticalCodes.has(a.code);
              const hovered = hoveredId === a.id;
              const rowBg = i % 2 === 0 ? "#ffffff" : "#fbfdff";

              return (
                <g
                  key={a.id}
                  onMouseEnter={() => setHoveredId(a.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  style={{ cursor: "default" }}
                >
                  {/* Row background */}
                  <rect
                    x={0}
                    y={yTop}
                    width={chartWidth}
                    height={ROW_HEIGHT}
                    fill={hovered ? "#f1f5f9" : rowBg}
                  />

                  {/* Baseline bar (top track) */}
                  {baselineFrozen && a.baseline_start && a.baseline_finish && (
                    <BaselineBar
                      x1={xFromDate(a.baseline_start)}
                      x2={xFromDate(a.baseline_finish)}
                      y={yTop + 6}
                    />
                  )}

                  {/* Planned bar */}
                  {a.planned_start && a.planned_finish && (
                    <PlannedBar
                      x1={xFromDate(a.planned_start)}
                      x2={xFromDate(a.planned_finish)}
                      y={yTop + (baselineFrozen ? 14 : 10)}
                      percent={a.percent_complete}
                      critical={isCrit}
                      slipped={isSlipped(a)}
                      onHover={() => setHoveredId(a.id)}
                      title={tooltipFor(a)}
                    />
                  )}

                  {/* Milestone diamond (zero-duration) */}
                  {a.activity_type === "milestone" && a.planned_start && (
                    <MilestoneDiamond
                      x={xFromDate(a.planned_start)}
                      y={yTop + ROW_HEIGHT / 2}
                      critical={isCrit}
                    />
                  )}
                </g>
              );
            })}

            {/* Dependency arrows — drawn last so they sit above bars */}
            <g>
              {dependencies.map((d) => {
                const pre = byId.get(d.predecessor_id);
                const suc = byId.get(d.successor_id);
                if (!pre || !suc) return null;
                const a = pre.activity;
                const b = suc.activity;
                if (!a.planned_finish || !b.planned_start) return null;
                const x1 = xFromDate(a.planned_finish);
                const y1 = HEADER_HEIGHT + pre.rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2;
                const x2 = xFromDate(b.planned_start);
                const y2 = HEADER_HEIGHT + suc.rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2;
                return (
                  <DependencyArrow
                    key={d.id}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                  />
                );
              })}
            </g>
          </svg>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
        <LegendSwatch color="#94a3b8" label="Baseline" />
        <LegendSwatch color="#3b82f6" label="Kế hoạch" />
        <LegendSwatch color="#1d4ed8" label="Đã hoàn thành (overlay)" />
        <LegendSwatch color="#f59e0b" label="Trễ baseline" />
        <LegendSwatch color="#e11d48" label="Đường găng (Critical path)" />
        <span className="inline-flex items-center gap-1">
          <span
            className="inline-block h-2.5 w-0.5"
            style={{ borderLeft: "2px dashed #ef4444" }}
          />
          Hôm nay
        </span>
      </div>
    </div>
  );
}


// ---------- Sub-components ----------


function BaselineBar({ x1, x2, y }: { x1: number; x2: number; y: number }) {
  return (
    <rect
      x={x1}
      y={y}
      width={Math.max(1, x2 - x1)}
      height={4}
      fill="#94a3b8"
      opacity={0.55}
      rx={2}
    />
  );
}


function PlannedBar({
  x1,
  x2,
  y,
  percent,
  critical,
  slipped,
  onHover,
  title,
}: {
  x1: number;
  x2: number;
  y: number;
  percent: number;
  critical: boolean;
  slipped: boolean;
  onHover: () => void;
  title: string;
}) {
  const width = Math.max(2, x2 - x1);
  const fill = critical ? "#fb7185" : slipped ? "#f59e0b" : "#3b82f6";
  const progressFill = critical ? "#be123c" : slipped ? "#b45309" : "#1d4ed8";
  const progressWidth = Math.max(0, Math.min(1, percent / 100)) * width;

  return (
    <g onMouseEnter={onHover}>
      <title>{title}</title>
      <rect
        x={x1}
        y={y}
        width={width}
        height={14}
        fill={fill}
        rx={3}
      />
      {progressWidth > 0 && (
        <rect
          x={x1}
          y={y}
          width={progressWidth}
          height={14}
          fill={progressFill}
          rx={3}
        />
      )}
    </g>
  );
}


function MilestoneDiamond({
  x,
  y,
  critical,
}: {
  x: number;
  y: number;
  critical: boolean;
}) {
  const s = 8;
  const points = `${x},${y - s} ${x + s},${y} ${x},${y + s} ${x - s},${y}`;
  return (
    <polygon
      points={points}
      fill={critical ? "#be123c" : "#0f172a"}
      stroke="#fff"
      strokeWidth={1}
    />
  );
}


function DependencyArrow({
  x1,
  y1,
  x2,
  y2,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}) {
  // Orthogonal: out from finish → right a bit → vertically → into start.
  // If the successor starts BEFORE the predecessor ends (lead time), the
  // arrow loops left around the row — kept simple here (straight line).
  const stub = 6;
  const path = `M ${x1} ${y1} L ${x1 + stub} ${y1} L ${x1 + stub} ${y2} L ${x2} ${y2}`;
  return (
    <g>
      <path
        d={path}
        fill="none"
        stroke="#94a3b8"
        strokeWidth={1}
        markerEnd="url(#dep-arrow)"
      />
      <defs>
        <marker
          id="dep-arrow"
          viewBox="0 0 6 6"
          refX={5}
          refY={3}
          markerWidth={6}
          markerHeight={6}
          orient="auto"
        >
          <path d="M 0 0 L 6 3 L 0 6 z" fill="#64748b" />
        </marker>
      </defs>
    </g>
  );
}


function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block h-2.5 w-3.5 rounded-sm"
        style={{ background: color }}
        aria-hidden
      />
      {label}
    </span>
  );
}


// ---------- Helpers ----------


function isSlipped(a: Activity): boolean {
  if (!a.baseline_finish || !a.planned_finish) return false;
  return new Date(a.planned_finish) > new Date(a.baseline_finish);
}


function tooltipFor(a: Activity): string {
  return [
    `${a.code} — ${a.name}`,
    a.planned_start && a.planned_finish
      ? `${fmt(a.planned_start)} → ${fmt(a.planned_finish)}`
      : null,
    `${a.percent_complete.toFixed(0)}% hoàn thành`,
    a.status,
  ]
    .filter(Boolean)
    .join("\n");
}


function fmt(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(
    2,
    "0",
  )}/${d.getFullYear()}`;
}


function buildMonthTicks(
  axisStart: number,
  axisEnd: number,
  pxPerDay: number,
): Array<{ x: number; label: string }> {
  // First day of each month falling inside [axisStart, axisEnd].
  const ticks: Array<{ x: number; label: string }> = [];
  const d = new Date(axisStart);
  d.setDate(1);
  d.setHours(0, 0, 0, 0);
  // Jump forward one month at a time.
  while (d.getTime() < axisEnd) {
    if (d.getTime() >= axisStart) {
      const dayOffset = (d.getTime() - axisStart) / DAY;
      ticks.push({
        x: dayOffset * pxPerDay,
        label: `${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`,
      });
    }
    d.setMonth(d.getMonth() + 1);
  }
  return ticks;
}
