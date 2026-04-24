"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Input, Label } from "@aec/ui/primitives";
import { DrawingUploader, type UploadedDrawing } from "@aec/ui/costpulse";
import {
  useEstimateFromBrief,
  useEstimateFromDrawings,
  useUploadDrawing,
} from "@/hooks/costpulse";

type Mode = "brief" | "drawings";

export default function EstimateWizardPage(): JSX.Element {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("brief");
  const brief = useEstimateFromBrief();
  const drawings = useEstimateFromDrawings();

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">New estimate</h1>
        <p className="text-slate-600">Choose your starting point.</p>
      </div>

      <div className="flex gap-3">
        {(["brief", "drawings"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`flex-1 rounded-lg border p-4 text-left transition ${
              mode === m ? "border-sky-500 bg-sky-50" : "border-slate-200 hover:border-slate-300"
            }`}
          >
            <div className="font-semibold">
              {m === "brief" ? "From brief" : "From drawings"}
            </div>
            <div className="mt-1 text-xs text-slate-600">
              {m === "brief"
                ? "Rough-order estimate from project parameters."
                : "Detailed BOQ extraction from uploaded drawings."}
            </div>
          </button>
        ))}
      </div>

      {mode === "brief" ? (
        <BriefForm
          loading={brief.isPending}
          error={brief.error?.message}
          onSubmit={async (input) => {
            const res = await brief.mutateAsync(input);
            router.push(`/costpulse/estimates/${res.estimate_id}`);
          }}
        />
      ) : (
        <DrawingsForm
          loading={drawings.isPending}
          error={drawings.error?.message}
          onSubmit={async (input) => {
            const res = await drawings.mutateAsync(input);
            router.push(`/costpulse/estimates/${res.estimate_id}`);
          }}
        />
      )}
    </div>
  );
}

interface BriefInput {
  name: string;
  project_type: string;
  area_sqm: number;
  floors: number;
  province: string;
  quality_tier: "economy" | "standard" | "premium";
  structure_type: "reinforced_concrete" | "steel" | "mixed";
  notes: string;
}

function BriefForm({
  loading,
  error,
  onSubmit,
}: {
  loading: boolean;
  error?: string;
  onSubmit: (input: BriefInput) => Promise<void>;
}): JSX.Element {
  const [form, setForm] = useState<BriefInput>({
    name: "",
    project_type: "residential",
    area_sqm: 500,
    floors: 3,
    province: "Hanoi",
    quality_tier: "standard",
    structure_type: "reinforced_concrete",
    notes: "",
  });

  return (
    <form
      className="space-y-4 rounded-lg border border-slate-200 bg-white p-6"
      onSubmit={(e) => {
        e.preventDefault();
        void onSubmit(form);
      }}
    >
      <Field label="Estimate name">
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Project type">
          <select
            className="h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-sm"
            value={form.project_type}
            onChange={(e) => setForm({ ...form, project_type: e.target.value })}
          >
            {["residential", "commercial", "villa", "factory", "mixed_use"].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </Field>
        <Field label="Province">
          <Input value={form.province} onChange={(e) => setForm({ ...form, province: e.target.value })} required />
        </Field>
        <Field label="Area (m²)">
          <Input
            type="number"
            value={form.area_sqm}
            onChange={(e) => setForm({ ...form, area_sqm: Number(e.target.value) })}
            required
          />
        </Field>
        <Field label="Floors">
          <Input
            type="number"
            value={form.floors}
            onChange={(e) => setForm({ ...form, floors: Number(e.target.value) })}
            required
          />
        </Field>
        <Field label="Quality tier">
          <select
            className="h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-sm"
            value={form.quality_tier}
            onChange={(e) =>
              setForm({ ...form, quality_tier: e.target.value as BriefInput["quality_tier"] })
            }
          >
            <option value="economy">Economy</option>
            <option value="standard">Standard</option>
            <option value="premium">Premium</option>
          </select>
        </Field>
        <Field label="Structure">
          <select
            className="h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-sm"
            value={form.structure_type}
            onChange={(e) =>
              setForm({ ...form, structure_type: e.target.value as BriefInput["structure_type"] })
            }
          >
            <option value="reinforced_concrete">Reinforced concrete</option>
            <option value="steel">Steel</option>
            <option value="mixed">Mixed</option>
          </select>
        </Field>
      </div>

      <Field label="Notes">
        <textarea
          className="min-h-[80px] w-full rounded-md border border-slate-200 bg-white p-2 text-sm"
          value={form.notes}
          onChange={(e) => setForm({ ...form, notes: e.target.value })}
        />
      </Field>

      {error && <div className="text-sm text-red-600">{error}</div>}

      <div className="flex justify-end">
        <Button type="submit" disabled={loading}>
          {loading ? "Generating…" : "Generate estimate"}
        </Button>
      </div>
    </form>
  );
}

interface DrawingsInput {
  name: string;
  province: string;
  drawing_file_ids: string[];
  include_contingency_pct: number;
}

function DrawingsForm({
  loading,
  error,
  onSubmit,
}: {
  loading: boolean;
  error?: string;
  onSubmit: (input: DrawingsInput) => Promise<void>;
}): JSX.Element {
  const [form, setForm] = useState<Omit<DrawingsInput, "drawing_file_ids">>({
    name: "",
    province: "Hanoi",
    include_contingency_pct: 10,
  });
  const [uploaded, setUploaded] = useState<UploadedDrawing[]>([]);
  const upload = useUploadDrawing();

  return (
    <form
      className="space-y-4 rounded-lg border border-slate-200 bg-white p-6"
      onSubmit={(e) => {
        e.preventDefault();
        void onSubmit({
          ...form,
          drawing_file_ids: uploaded.map((u) => u.file_id),
        });
      }}
    >
      <Field label="Estimate name">
        <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Province">
          <Input value={form.province} onChange={(e) => setForm({ ...form, province: e.target.value })} required />
        </Field>
        <Field label="Contingency (%)">
          <Input
            type="number"
            value={form.include_contingency_pct}
            onChange={(e) =>
              setForm({ ...form, include_contingency_pct: Number(e.target.value) })
            }
          />
        </Field>
      </div>

      <Field label="Drawings">
        <DrawingUploader
          value={uploaded}
          onChange={setUploaded}
          onUpload={(file) => upload.mutateAsync({ file })}
        />
      </Field>

      {error && <div className="text-sm text-red-600">{error}</div>}

      <div className="flex justify-end">
        <Button type="submit" disabled={loading || uploaded.length === 0}>
          {loading ? "Analyzing drawings…" : "Generate BOQ"}
        </Button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
