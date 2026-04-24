"use client";
import { useEffect, useState, type FC } from "react";
import type { FirmProfile, FirmProfileInput } from "./types";

interface Props {
  profile?: FirmProfile | null;
  onSubmit: (input: FirmProfileInput) => void;
  submitting?: boolean;
}

const EMPTY: FirmProfileInput = {
  disciplines: [],
  project_types: [],
  provinces: [],
  min_budget_vnd: null,
  max_budget_vnd: null,
  team_size: null,
  active_capacity_pct: null,
  past_wins: [],
  keywords: [],
};

function parseList(v: string): string[] {
  return v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export const FirmProfileForm: FC<Props> = ({ profile, onSubmit, submitting = false }) => {
  const [form, setForm] = useState<FirmProfileInput>(EMPTY);

  useEffect(() => {
    if (profile) {
      setForm({
        disciplines: profile.disciplines ?? [],
        project_types: profile.project_types ?? [],
        provinces: profile.provinces ?? [],
        min_budget_vnd: profile.min_budget_vnd ?? null,
        max_budget_vnd: profile.max_budget_vnd ?? null,
        team_size: profile.team_size ?? null,
        active_capacity_pct: profile.active_capacity_pct ?? null,
        past_wins: profile.past_wins ?? [],
        keywords: profile.keywords ?? [],
      });
    }
  }, [profile]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(form);
      }}
      className="space-y-4 rounded-lg border border-slate-200 bg-white p-5"
    >
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Disciplines</span>
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.disciplines.join(", ")}
            onChange={(e) => setForm({ ...form, disciplines: parseList(e.target.value) })}
            placeholder="architecture, structural, MEP"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Project types</span>
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.project_types.join(", ")}
            onChange={(e) => setForm({ ...form, project_types: parseList(e.target.value) })}
            placeholder="residential, commercial, civic"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Provinces</span>
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.provinces.join(", ")}
            onChange={(e) => setForm({ ...form, provinces: parseList(e.target.value) })}
            placeholder="Hanoi, HCMC, Danang"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Keywords</span>
          <input
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.keywords.join(", ")}
            onChange={(e) => setForm({ ...form, keywords: parseList(e.target.value) })}
            placeholder="BIM, LEED, retail fit-out"
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Min budget (VND)</span>
          <input
            type="number"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.min_budget_vnd ?? ""}
            onChange={(e) =>
              setForm({ ...form, min_budget_vnd: e.target.value ? Number(e.target.value) : null })
            }
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Max budget (VND)</span>
          <input
            type="number"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.max_budget_vnd ?? ""}
            onChange={(e) =>
              setForm({ ...form, max_budget_vnd: e.target.value ? Number(e.target.value) : null })
            }
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Team size</span>
          <input
            type="number"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.team_size ?? ""}
            onChange={(e) =>
              setForm({ ...form, team_size: e.target.value ? Number(e.target.value) : null })
            }
          />
        </label>
        <label className="space-y-1 text-sm">
          <span className="font-medium text-slate-700">Active capacity %</span>
          <input
            type="number"
            min={0}
            max={100}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            value={form.active_capacity_pct ?? ""}
            onChange={(e) =>
              setForm({ ...form, active_capacity_pct: e.target.value ? Number(e.target.value) : null })
            }
          />
        </label>
      </div>

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {submitting ? "Saving…" : "Save profile"}
        </button>
      </div>
    </form>
  );
};
