import type { WeeklyReport } from "./types";

interface Props {
  report: WeeklyReport;
}

export function WeeklyReportViewer({ report }: Props) {
  const c = report.content;
  if (!c) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500">
        Report content is still being generated.
      </div>
    );
  }
  return (
    <article className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-gray-900">
          Weekly report · {report.week_start} → {report.week_end}
        </h1>
        <p className="mt-1 text-sm text-gray-600">{c.executive_summary}</p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Overall" value={`${c.kpis.overall_progress_pct.toFixed(0)}%`} />
        <Kpi label="Days elapsed" value={String(c.kpis.days_elapsed)} />
        <Kpi
          label="Days remaining"
          value={c.kpis.days_remaining === null ? "—" : String(c.kpis.days_remaining)}
        />
        <Kpi label="Schedule" value={c.kpis.schedule_status.replace("_", " ")} />
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-600">Issues & risks</h2>
        {c.issues_and_risks.length ? (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-800">
            {c.issues_and_risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-gray-500">No issues flagged.</p>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-600">Next week plan</h2>
        {c.next_week_plan.length ? (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-800">
            {c.next_week_plan.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-gray-500">No plan recorded.</p>
        )}
      </section>

      {report.pdf_url ? (
        <a
          href={report.pdf_url}
          className="inline-block rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white"
          download
        >
          Download PDF
        </a>
      ) : null}
    </article>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <p className="text-xs uppercase text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-gray-900">{value}</p>
    </div>
  );
}
