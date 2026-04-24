"use client";
import { useParams } from "next/navigation";
import { useState } from "react";

import { WeeklyReportViewer } from "@aec/ui/siteeye";
import { useReports, useSendReport } from "@/hooks/siteeye";

export default function WeeklyReportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const listQ = useReports({ limit: 100 });
  const send = useSendReport();
  const [recipients, setRecipients] = useState("");
  const [ok, setOk] = useState<string | null>(null);

  const report = listQ.data?.data.find((r) => r.id === id);

  if (!report) {
    return <p className="text-sm text-gray-500">Loading…</p>;
  }

  async function handleSend() {
    const list = recipients
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (list.length === 0) return;
    await send.mutateAsync({ reportId: id, recipients: list });
    setOk(`Sent to ${list.join(", ")}`);
    setRecipients("");
  }

  return (
    <div className="space-y-6">
      <WeeklyReportViewer report={report} />

      <section className="rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold text-gray-700">Send to stakeholders</h2>
        <div className="flex flex-wrap gap-2">
          <input
            type="text"
            placeholder="email1@co.com, email2@co.com"
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            className="flex-1 rounded border border-gray-300 px-3 py-2"
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={send.isPending || recipients.trim() === ""}
            className="rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            {send.isPending ? "Sending…" : "Send"}
          </button>
        </div>
        {ok ? <p className="mt-2 text-sm text-emerald-600">{ok}</p> : null}
      </section>
    </div>
  );
}
