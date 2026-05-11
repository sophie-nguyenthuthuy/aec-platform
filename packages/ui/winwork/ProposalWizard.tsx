"use client";
import { useState } from "react";
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

const DISCIPLINES: Array<{ value: Discipline; label: string }> = [
  { value: "architecture", label: "Kiến trúc" },
  { value: "structural", label: "Kết cấu" },
  { value: "mep", label: "M&E" },
  { value: "civil", label: "Hạ tầng" },
];

export function ProposalWizard({ onGenerate, onCreated, generating }: ProposalWizardProps) {
  const [step, setStep] = useState<Step>("brief");
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
    const result = await onGenerate(form);
    const id = "proposal" in result ? result.proposal.id : result.id;
    onCreated(id);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Đề xuất mới</CardTitle>
        <div className="flex gap-2 text-xs text-muted-foreground">
          {([["brief", "Tóm tắt"], ["scope", "Phạm vi"], ["review", "Xem lại"]] as [Step, string][]).map(([s, label], i) => (
            <span key={s} className={step === s ? "font-semibold text-foreground" : ""}>
              {i + 1}. {label}
            </span>
          ))}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {step === "brief" && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label>Bộ môn</Label>
                <select
                  className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                  value={form.discipline}
                  onChange={(e) => update("discipline", e.target.value as Discipline)}
                >
                  {DISCIPLINES.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label>Loại dự án</Label>
                <Input
                  value={form.project_type}
                  onChange={(e) => update("project_type", e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label>Diện tích (m²)</Label>
                <Input
                  type="number"
                  value={form.area_sqm}
                  onChange={(e) => update("area_sqm", Number(e.target.value || 0))}
                />
              </div>
              <div className="space-y-1">
                <Label>Số tầng</Label>
                <Input
                  type="number"
                  value={form.floors}
                  onChange={(e) => update("floors", Number(e.target.value || 1))}
                />
              </div>
              <div className="col-span-2 space-y-1">
                <Label>Địa điểm</Label>
                <Input value={form.location} onChange={(e) => update("location", e.target.value)} />
              </div>
              <div className="col-span-2 space-y-1">
                <Label>Yêu cầu của khách hàng</Label>
                <Textarea
                  rows={6}
                  value={form.client_brief}
                  onChange={(e) => update("client_brief", e.target.value)}
                  placeholder="Dán yêu cầu, bối cảnh công trình, tiến độ, các ràng buộc…"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={() => setStep("scope")} disabled={form.client_brief.length < 10}>
                Tiếp theo
              </Button>
            </div>
          </>
        )}

        {step === "scope" && (
          <>
            <div className="space-y-1">
              <Label>Hạng mục công việc (mỗi dòng một mục)</Label>
              <Textarea
                rows={8}
                value={form.scope_items.join("\n")}
                onChange={(e) =>
                  update("scope_items", e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))
                }
              />
              <p className="text-xs text-muted-foreground">
                AI sẽ phân tích và bổ sung đầu ra theo từng giai đoạn.
              </p>
            </div>
            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep("brief")}>
                Quay lại
              </Button>
              <Button onClick={() => setStep("review")} disabled={form.scope_items.length === 0}>
                Tiếp theo
              </Button>
            </div>
          </>
        )}

        {step === "review" && (
          <>
            <div className="space-y-2 text-sm">
              <Row label="Bộ môn" value={DISCIPLINES.find((d) => d.value === form.discipline)?.label ?? form.discipline} />
              <Row label="Loại dự án" value={form.project_type} />
              <Row label="Diện tích" value={`${form.area_sqm} m²`} />
              <Row label="Số tầng" value={String(form.floors)} />
              <Row label="Địa điểm" value={form.location} />
              <Row label="Hạng mục" value={form.scope_items.join(", ")} />
            </div>
            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep("scope")} disabled={generating}>
                Quay lại
              </Button>
              <Button onClick={submit} disabled={generating}>
                {generating ? "Đang tạo…" : "Tạo đề xuất"}
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
