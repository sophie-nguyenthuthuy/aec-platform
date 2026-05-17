"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Building2,
  Calendar,
  Layers,
  Loader2,
  Package,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";


/**
 * Bảng giá vật tư VN — Material Price Index.
 *
 * Customer-facing surface over the price scrapers that have been
 * running for months. Three views:
 *
 *   1. **Compare**: province × material pivot — "which province is
 *      cheapest for cement this month?". Default landing tab.
 *   2. **Time series**: one material × selected provinces, last 12
 *      months. Pure CSS line chart.
 *   3. **Latest**: flat list of newest prices, filterable.
 *
 * No tenant scope on the data side — public ingest from Sở Xây dựng
 * bulletins. Auth required to gate anonymous traffic.
 */


type Tab = "compare" | "series" | "latest";


interface MaterialMeta {
  material_code: string;
  name: string;
  category: string | null;
  unit: string;
  observation_count: number;
  last_observed: string | null;
  province_count: number;
}

interface CompareRow {
  material_code: string;
  name: string;
  unit: string;
  prices: Record<string, { price_vnd: number; effective_date: string }>;
}

interface CompareResponse {
  provinces: string[];
  materials: CompareRow[];
}

interface SeriesPoint {
  date: string;
  price_vnd: number;
}

interface SeriesResponse {
  material_code: string;
  material_name: string;
  unit: string;
  since: string;
  until: string;
  series: Array<{ province: string; points: SeriesPoint[] }>;
}

interface LatestRow {
  material_code: string;
  name: string;
  category: string | null;
  unit: string;
  price_vnd: number;
  province: string;
  source: string | null;
  effective_date: string;
}


const PROVINCE_LABEL: Record<string, string> = {
  hanoi: "Hà Nội",
  hcmc: "TP HCM",
  danang: "Đà Nẵng",
  haiphong: "Hải Phòng",
  cantho: "Cần Thơ",
  binhduong: "Bình Dương",
  quangninh: "Quảng Ninh",
  vungtau: "Bà Rịa - Vũng Tàu",
};

function provinceLabel(slug: string): string {
  return PROVINCE_LABEL[slug] || slug;
}


export default function MaterialPricesPage() {
  const { token, orgId } = useSession();
  const [tab, setTab] = useState<Tab>("compare");
  const [materials, setMaterials] = useState<MaterialMeta[]>([]);
  const [compare, setCompare] = useState<CompareResponse | null>(null);
  const [series, setSeries] = useState<SeriesResponse | null>(null);
  const [latest, setLatest] = useState<LatestRow[]>([]);
  const [selectedMaterial, setSelectedMaterial] = useState("cement");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch material catalogue once
  useEffect(() => {
    if (!token || !orgId) return;
    apiFetch<{ materials: MaterialMeta[] }>(
      "/api/v1/material-prices/materials",
      { token, orgId },
    )
      .then((r) => setMaterials(r.data!.materials))
      .catch((e) => setError((e as Error).message));
  }, [token, orgId]);

  const fetchTab = useCallback(async () => {
    if (!token || !orgId) return;
    setLoading(true);
    setError(null);
    try {
      if (tab === "compare") {
        const r = await apiFetch<CompareResponse>(
          "/api/v1/material-prices/compare",
          { token, orgId },
        );
        setCompare(r.data!);
      } else if (tab === "series") {
        const r = await apiFetch<SeriesResponse>(
          `/api/v1/material-prices/series?material_code=${selectedMaterial}&days=365`,
          { token, orgId },
        );
        setSeries(r.data!);
      } else if (tab === "latest") {
        const r = await apiFetch<{ prices: LatestRow[] }>(
          "/api/v1/material-prices/latest?limit=100",
          { token, orgId },
        );
        setLatest(r.data!.prices);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [tab, selectedMaterial, token, orgId]);

  useEffect(() => {
    void fetchTab();
  }, [fetchTab]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          <Package size={22} className="text-blue-600" />
          Bảng giá vật tư xây dựng
        </h2>
        <p className="text-xs text-slate-500">
          Dữ liệu cập nhật từ bản tin giá Sở Xây dựng 64 tỉnh thành.
          Cập nhật hàng tháng. Áp dụng để dự toán BoQ + RFQ vật tư.
        </p>
      </div>

      {error && (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
      )}

      {/* Tab toggle */}
      <div className="inline-flex rounded-md bg-slate-100 p-0.5 text-xs">
        <TabBtn active={tab === "compare"} onClick={() => setTab("compare")} label="So sánh tỉnh" />
        <TabBtn active={tab === "series"} onClick={() => setTab("series")} label="Xu hướng theo thời gian" />
        <TabBtn active={tab === "latest"} onClick={() => setTab("latest")} label="Giá mới nhất" />
      </div>

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> Đang tải…
        </p>
      ) : tab === "compare" && compare ? (
        <CompareView data={compare} />
      ) : tab === "series" ? (
        <SeriesView
          data={series}
          selectedMaterial={selectedMaterial}
          materials={materials}
          onMaterialChange={setSelectedMaterial}
        />
      ) : tab === "latest" ? (
        <LatestView rows={latest} />
      ) : null}
    </div>
  );
}


function TabBtn({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded px-3 py-1.5 ${
        active
          ? "bg-white font-medium text-slate-900 shadow-sm"
          : "text-slate-500 hover:text-slate-700"
      }`}
    >
      {label}
    </button>
  );
}


function CompareView({ data }: { data: CompareResponse }) {
  if (data.materials.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
        <p className="text-sm text-slate-500">Chưa có dữ liệu giá cho các vật tư phổ biến.</p>
      </div>
    );
  }
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <header className="border-b border-slate-200 px-4 py-2.5">
        <h3 className="text-sm font-semibold text-slate-900">
          So sánh giá theo tỉnh ({data.provinces.length} tỉnh)
        </h3>
      </header>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Vật tư</th>
              {data.provinces.map((p) => (
                <th
                  key={p}
                  className="px-4 py-2 text-right font-medium text-slate-700"
                >
                  {provinceLabel(p)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.materials.map((m) => {
              const allPrices = data.provinces
                .map((p) => m.prices[p]?.price_vnd)
                .filter((x): x is number => typeof x === "number");
              const min = Math.min(...allPrices);
              const max = Math.max(...allPrices);
              return (
                <tr key={m.material_code} className="border-t border-slate-100">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-slate-900">{m.name}</div>
                    <div className="text-[10px] text-slate-500">{m.material_code} · {m.unit}</div>
                  </td>
                  {data.provinces.map((p) => {
                    const cell = m.prices[p];
                    const isMin = cell && cell.price_vnd === min && allPrices.length > 1;
                    const isMax = cell && cell.price_vnd === max && allPrices.length > 1;
                    return (
                      <td key={p} className="px-4 py-2.5 text-right font-mono">
                        {cell ? (
                          <span
                            className={
                              isMin
                                ? "text-emerald-700 font-semibold"
                                : isMax
                                ? "text-rose-700 font-semibold"
                                : "text-slate-900"
                            }
                          >
                            {formatVnd(cell.price_vnd)}
                          </span>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-500">
        <span className="text-emerald-700">Xanh</span> = giá thấp nhất ·
        <span className="ml-2 text-rose-700">Đỏ</span> = giá cao nhất
      </p>
    </section>
  );
}


function SeriesView({
  data,
  selectedMaterial,
  materials,
  onMaterialChange,
}: {
  data: SeriesResponse | null;
  selectedMaterial: string;
  materials: MaterialMeta[];
  onMaterialChange: (code: string) => void;
}) {
  // Compute chart bounds across all provinces × points
  const allPoints = useMemo(() => {
    if (!data) return [];
    return data.series.flatMap((s) => s.points);
  }, [data]);

  const { minPrice, maxPrice, dates } = useMemo(() => {
    if (allPoints.length === 0) {
      return { minPrice: 0, maxPrice: 0, dates: [] as string[] };
    }
    const prices = allPoints.map((p) => p.price_vnd);
    const datesSet = new Set(allPoints.map((p) => p.date));
    return {
      minPrice: Math.min(...prices),
      maxPrice: Math.max(...prices),
      dates: Array.from(datesSet).sort(),
    };
  }, [allPoints]);

  const lineColors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-sm text-slate-700">Vật tư:</label>
        <select
          value={selectedMaterial}
          onChange={(e) => onMaterialChange(e.target.value)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        >
          {materials.map((m) => (
            <option key={m.material_code} value={m.material_code}>
              {m.name} ({m.unit})
            </option>
          ))}
        </select>
      </div>

      {data && data.series.length > 0 ? (
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
            <BarChart3 size={14} />
            {data.material_name} · {data.unit}
          </h3>
          <p className="text-xs text-slate-500">
            Khoảng: {formatVnDate(data.since)} → {formatVnDate(data.until)}
          </p>

          {/* Simple SVG line chart */}
          <div className="mt-4 overflow-x-auto">
            <svg
              viewBox={`0 0 ${Math.max(600, dates.length * 60)} 260`}
              className="w-full"
              style={{ minWidth: "600px" }}
            >
              {/* Y-axis labels */}
              <text x={5} y={20} fontSize="10" fill="#64748b">
                {formatVndShort(maxPrice)}
              </text>
              <text x={5} y={250} fontSize="10" fill="#64748b">
                {formatVndShort(minPrice)}
              </text>
              {/* Grid */}
              <line x1={50} y1={20} x2="100%" y2={20} stroke="#e2e8f0" />
              <line x1={50} y1={130} x2="100%" y2={130} stroke="#e2e8f0" />
              <line x1={50} y1={240} x2="100%" y2={240} stroke="#e2e8f0" />

              {/* Lines per province */}
              {data.series.map((s, idx) => {
                const color = lineColors[idx % lineColors.length];
                const pts = s.points
                  .map((p, i) => {
                    const x =
                      50 +
                      (dates.indexOf(p.date) / Math.max(1, dates.length - 1)) *
                        (Math.max(600, dates.length * 60) - 70);
                    const y =
                      240 -
                      ((p.price_vnd - minPrice) /
                        Math.max(1, maxPrice - minPrice)) *
                        220;
                    return `${x},${y}`;
                  })
                  .join(" ");
                return (
                  <g key={s.province}>
                    <polyline
                      points={pts}
                      fill="none"
                      stroke={color}
                      strokeWidth={2}
                    />
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Legend */}
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {data.series.map((s, idx) => (
              <span key={s.province} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block h-2 w-4 rounded-sm"
                  style={{ background: lineColors[idx % lineColors.length] }}
                />
                <span className="text-slate-700">{provinceLabel(s.province)}</span>
                <span className="text-slate-400">
                  ({s.points.length} điểm)
                </span>
              </span>
            ))}
          </div>
        </section>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Không có dữ liệu cho vật tư này trong 12 tháng qua.
        </div>
      )}
    </div>
  );
}


function LatestView({ rows }: { rows: LatestRow[] }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <header className="border-b border-slate-200 px-4 py-2.5">
        <h3 className="text-sm font-semibold text-slate-900">
          Giá mới nhất ({rows.length})
        </h3>
      </header>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-slate-500">
          Chưa có dữ liệu.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-700">
                  Vật tư
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-700">
                  Tỉnh
                </th>
                <th className="px-4 py-2 text-right text-xs font-medium text-slate-700">
                  Giá / Đơn vị
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-700">
                  Ngày hiệu lực
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-700">
                  Nguồn
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.material_code}-${r.province}-${i}`} className="border-t border-slate-100">
                  <td className="px-4 py-2">
                    <div className="font-medium text-slate-900">{r.name}</div>
                    <div className="text-[10px] text-slate-500">
                      {r.category ?? "—"}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    <Building2 size={11} className="mr-1 inline" />
                    {provinceLabel(r.province)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-slate-900">
                    {formatVnd(r.price_vnd)}
                    <span className="ml-1 text-[10px] text-slate-500">/{r.unit}</span>
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    <Calendar size={11} className="mr-1 inline" />
                    {formatVnDate(r.effective_date)}
                  </td>
                  <td className="px-4 py-2 text-[11px] text-slate-500">
                    {r.source ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}


function formatVnd(n: number): string {
  return new Intl.NumberFormat("vi-VN").format(n) + " ₫";
}


function formatVndShort(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}T`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}


function formatVnDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
