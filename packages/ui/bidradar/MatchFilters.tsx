import type { FC } from "react";
import type { MatchStatus } from "./types";

interface Props {
  status: MatchStatus | "all";
  minScore: number;
  recommendedOnly: boolean;
  onChange: (next: { status: MatchStatus | "all"; minScore: number; recommendedOnly: boolean }) => void;
}

const STATUSES: Array<{ value: MatchStatus | "all"; label: string }> = [
  { value: "all", label: "All" },
  { value: "new", label: "New" },
  { value: "saved", label: "Saved" },
  { value: "pursuing", label: "Pursuing" },
  { value: "passed", label: "Passed" },
];

export const MatchFilters: FC<Props> = ({ status, minScore, recommendedOnly, onChange }) => {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1">
        {STATUSES.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange({ status: opt.value, minScore, recommendedOnly })}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              status === opt.value
                ? "bg-slate-900 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-700">
        Min score
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={minScore}
          onChange={(e) => onChange({ status, minScore: Number(e.target.value), recommendedOnly })}
          className="w-32"
        />
        <span className="w-8 tabular-nums text-slate-500">{minScore}</span>
      </label>

      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={recommendedOnly}
          onChange={(e) => onChange({ status, minScore, recommendedOnly: e.target.checked })}
          className="rounded border-slate-300"
        />
        Recommended only
      </label>
    </div>
  );
};
