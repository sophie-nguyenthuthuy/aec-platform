"use client";
import { useId, useState } from "react";
import type { Discipline, ProposalGenerateRequest } from "@aec/types/winwork";

import { Button } from "../primitives/button";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Textarea } from "../primitives/textarea";

type Step = "brief" | "scope" | "review";

interface ProposalWizardProps {
  onGenerate: (payload: ProposalGenerateRequest) => Promise<{ id: string } | { proposal: { id: string } }>;
  onCreated: (proposalId: string) => void;
  generating?: boolean;
}

const DISCIPLINES: Discipline[] = ["architecture", "structural", "mep", "civil"];

export function ProposalWizard({ onGenerate, onCreated, generating }: ProposalWizardProps) {
  const [step, setStep] = useState<Step>("brief");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const disciplineId = useId();
  const projectTypeId = useId();
  const areaId = useId();
  const floorsId = useId();
  const locationId = useId();
  const briefId = useId();
  const scopeId = useId();

  const [form, setForm] = useState<ProposalGenerateRequest>({
    project_type: "residential_villa",
    area_sqm: 200,
    floors: 3,
    location: "Hanoi, Vietnam",
    scope_items: ["architectural design", "permit drawings"],
    client_brief: "",
    discipline: "architecture",
    language: "vi",
  });

  function update<K extends keyof ProposalGenerateRequest>(key: K, value: ProposalGenerateRequest[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submit() {
    setSubmitError(null);
    try {
      const result = await onGenerate(form);
      const id = "proposal" in result ? result.proposal.id : result.id;
      onCreated(id);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : "Failed to generate proposal.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>New proposal</CardTitle>
        <div className="flex gap-2 text-xs text-muted-foreground">
          {(["brief", "scope", "review"] as Step[]).map((s, i) => (
            <span key={s} className={step === s ? "font-semibold text-foreground" : ""}>
              {i + 1}. {s}
            </span>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {step === "brief" && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label htmlFor={disciplineId}>Discipline</Label>
                <select
                  id={disciplineId}
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                  value={form.discipline}
                  onChange={(e) => update("discipline", e.target.value as Discipline)}
                >
                  {DISCIPLINES.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor={projectTypeId}>Project type</Label>
                <Input
                  id={projectTypeId}
                  value={form.project_type}
                  onChange={(e) => update("project_type", e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={areaId}>Area (m²)</Label>
                <Input
                  id={areaId}
                  type="number"
                  value={form.area_sqm}
                  onChange={(e) => update("area_sqm", Number(e.target.value || 0))}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor={floorsId}>Floors</Label>
                <Input
                  id={floorsId}
                  type="number"
                  value={form.floors}
                  onChange={(e) => update("floors", Number(e.target.value || 1))}
                />
              </div>
              <div className="col-span-2 space-y-1">
                <Label htmlFor={locationId}>Location</Label>
                <Input
                  id={locationId}
                  value={form.location}
                  onChange={(e) => update("location", e.target.value)}
                />
              </div>
              <div className="col-span-2 space-y-1">
                <Label htmlFor={briefId}>Client brief</Label>
                <Textarea
                  id={briefId}
                  rows={6}
                  value={form.client_brief}
                  onChange={(e) => update("client_brief", e.target.value)}
                  placeholder="Paste the client's ask, site context, schedule, any constraints…"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={() => setStep("scope")} disabled={form.client_brief.length < 10}>
                Next
              </Button>
            </div>
          </>
        )}

        {step === "scope" && (
          <>
            <div className="space-y-1">
              <Label htmlFor={scopeId}>Scope items (one per line)</Label>
              <Textarea
                id={scopeId}
                rows={8}
                value={form.scope_items.join("\n")}
                onChange={(e) =>
                  update("scope_items", e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))
                }
              />
              <p className="text-xs text-muted-foreground">
                The AI will expand these into phase-based deliverables.
              </p>
            </div>
            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep("brief")}>
                Back
              </Button>
              <Button onClick={() => setStep("review")} disabled={form.scope_items.length === 0}>
                Next
              </Button>
            </div>
          </>
        )}

        {step === "review" && (
          <>
            <div className="space-y-2 text-sm">
              <Row label="Discipline" value={form.discipline} />
              <Row label="Project type" value={form.project_type} />
              <Row label="Area" value={`${form.area_sqm} m²`} />
              <Row label="Floors" value={String(form.floors)} />
              <Row label="Location" value={form.location} />
              <Row label="Scope items" value={form.scope_items.join(", ")} />
            </div>
            {submitError ? (
              <p className="text-sm text-red-600">{submitError}</p>
            ) : null}
            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep("scope")} disabled={generating}>
                Back
              </Button>
              <Button onClick={submit} disabled={generating}>
                {generating ? "Generating…" : "Generate proposal"}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b py-1 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
