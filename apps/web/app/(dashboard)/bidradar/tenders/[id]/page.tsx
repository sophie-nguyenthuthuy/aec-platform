"use client";
import Link from "next/link";
import { useTender } from "@/hooks/bidradar";

// Next.js 14 contract: `params` is a plain object on a "use client" page.
// `use(params)` (the Next 15 pattern) throws "unsupported type passed to
// use()" at runtime here — same bug as `app/invite/[token]/page.tsx`.
export default function TenderDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const { data, isLoading } = useTender(id);

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading tender…</div>;
  }
  if (!data) {
    return <div className="text-sm text-slate-500">Tender not found.</div>;
  }

  return (
    <article className="space-y-4">
      <Link href="/bidradar/tenders" className="text-sm text-slate-500 hover:underline">
        ← All tenders
      </Link>

      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-slate-900">{data.title}</h2>
        <p className="text-sm text-slate-500">
          {data.issuer ?? "Unknown issuer"} · {data.province ?? "—"} · {data.source}
        </p>
      </header>

      <dl className="grid grid-cols-2 gap-4 rounded-lg border border-slate-200 bg-white p-4 text-sm md:grid-cols-4">
        <div>
          <dt className="text-xs uppercase text-slate-500">Budget</dt>
          <dd className="font-medium text-slate-900">
            {data.budget_vnd ? `${data.budget_vnd.toLocaleString()} ${data.currency}` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-slate-500">Deadline</dt>
          <dd className="font-medium text-slate-900">
            {data.submission_deadline
              ? new Date(data.submission_deadline).toLocaleString()
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-slate-500">Type</dt>
          <dd className="font-medium text-slate-900">{data.type ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-slate-500">Disciplines</dt>
          <dd className="font-medium text-slate-900">
            {data.disciplines?.join(", ") ?? "—"}
          </dd>
        </div>
      </dl>

      {data.description ? (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Description</h3>
          <p className="whitespace-pre-wrap text-sm text-slate-700">{data.description}</p>
        </section>
      ) : null}

      {data.raw_url ? (
        <a
          href={data.raw_url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center text-sm text-slate-600 hover:underline"
        >
          View original source ↗
        </a>
      ) : null}
    </article>
  );
}
