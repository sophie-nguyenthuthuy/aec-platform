"use client";
import { useState } from "react";
import { useDigests, useSendDigest } from "@/hooks/bidradar";

export default function DigestsPage() {
  const { data, isLoading } = useDigests();
  const send = useSendDigest();
  const [recipients, setRecipients] = useState("");

  const digests = data ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Weekly digests</h2>
        <p className="text-sm text-slate-500">
          Send your team the top 5 recommended tenders from the past week.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const list = recipients.split(",").map((s) => s.trim()).filter(Boolean);
          if (list.length === 0) return;
          send.mutate({ recipients: list });
        }}
        className="flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-3"
      >
        <input
          type="text"
          className="flex-1 min-w-64 rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          placeholder="comma-separated emails"
          value={recipients}
          onChange={(e) => setRecipients(e.target.value)}
        />
        <button
          type="submit"
          disabled={send.isPending}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
        >
          {send.isPending ? "Sending…" : "Send this week's digest"}
        </button>
      </form>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Week</th>
              <th className="px-4 py-2"># matches</th>
              <th className="px-4 py-2">Recipients</th>
              <th className="px-4 py-2">Sent at</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : digests.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                  No digests sent yet.
                </td>
              </tr>
            ) : (
              digests.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="px-4 py-2 text-slate-700">
                    {new Date(d.week_start).toLocaleDateString()} —{" "}
                    {new Date(d.week_end).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 tabular-nums text-slate-600">
                    {d.top_match_ids.length}
                  </td>
                  <td className="px-4 py-2 text-slate-600">{d.sent_to.join(", ")}</td>
                  <td className="px-4 py-2 text-slate-600">
                    {d.sent_at ? new Date(d.sent_at).toLocaleString() : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
