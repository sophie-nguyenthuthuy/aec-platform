"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import type { ClientReport } from "@aec/types/pulse";
import { Button, Input, Label } from "@aec/ui/primitives";
import {
  useGenerateReport,
  useSendReport,
} from "../../../../../hooks/pulse/useReports";

export default function PulseReportsPage() {
  const params = useParams<{ project_id: string }>();
  const projectId = params.project_id;

  const [period, setPeriod] = useState(
    new Date().toISOString().slice(0, 7), // YYYY-MM
  );
  const [language, setLanguage] = useState<"vi" | "en">("vi");
  const [report, setReport] = useState<ClientReport | null>(null);
  const [recipients, setRecipients] = useState("");

  const generate = useGenerateReport();
  const send = useSendReport();

  async function onGenerate() {
    const result = await generate.mutateAsync({
      project_id: projectId,
      period,
      language,
    });
    setReport(result);
  }

  async function onSend() {
    if (!report) return;
    const list = recipients
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (list.length === 0) return;
    const updated = await send.mutateAsync({
      id: report.id,
      payload: { recipients: list },
    });
    setReport(updated);
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Generate client report</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <Label>Period</Label>
            <Input value={period} onChange={(e) => setPeriod(e.target.value)} />
          </div>
          <div>
            <Label>Language</Label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as "vi" | "en")}
              className="h-9 w-full rounded-md border px-2 text-sm"
            >
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
            </select>
          </div>
          <div className="flex items-end">
            <Button onClick={onGenerate} disabled={generate.isPending}>
              {generate.isPending ? "Generating…" : "Generate"}
            </Button>
          </div>
        </div>
      </section>

      {report && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold">Preview</h3>
            <span className="text-xs text-muted-foreground">
              Status: {report.status}
            </span>
          </div>

          {report.rendered_html ? (
            <div
              className="rounded border p-4"
              dangerouslySetInnerHTML={{ __html: report.rendered_html }}
            />
          ) : (
            <pre className="whitespace-pre-wrap rounded border p-4 text-xs">
              {JSON.stringify(report.content, null, 2)}
            </pre>
          )}

          <div className="space-y-2">
            <Label>Recipients (comma-separated)</Label>
            <Input
              value={recipients}
              onChange={(e) => setRecipients(e.target.value)}
              placeholder="client@example.com, pm@example.com"
            />
            <Button
              variant="secondary"
              onClick={onSend}
              disabled={send.isPending || !recipients.trim()}
            >
              {send.isPending ? "Sending…" : "Send to client"}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
