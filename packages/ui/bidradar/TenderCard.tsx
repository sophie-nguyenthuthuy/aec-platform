import type { FC } from "react";
import type { TenderMatchWithTender } from "./types";
import { MatchScoreBadge } from "./MatchScoreBadge";
import { CompetitionBadge } from "./CompetitionBadge";

interface Props {
  match: TenderMatchWithTender;
  onSave?: (matchId: string) => void;
  onPass?: (matchId: string) => void;
  onCreateProposal?: (matchId: string) => void;
}

function formatVnd(value?: number | null): string {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B ₫`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(0)}M ₫`;
  return `${value.toLocaleString()} ₫`;
}

function formatDeadline(value?: string | null): string {
  if (!value) return "No deadline";
  const date = new Date(value);
  const now = new Date();
  const days = Math.round((date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 0) return `Closed ${-days}d ago`;
  if (days === 0) return "Closes today";
  if (days <= 7) return `${days}d left`;
  return date.toLocaleDateString();
}

export const TenderCard: FC<Props> = ({ match, onSave, onPass, onCreateProposal }) => {
  const { tender, ai_recommendation: rec } = match;
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base font-semibold text-slate-900">
            {tender.title}
          </h3>
          <p className="mt-0.5 truncate text-sm text-slate-500">
            {tender.issuer ?? "Unknown issuer"} · {tender.province ?? "—"}
          </p>
        </div>
        <MatchScoreBadge score={match.match_score ?? undefined} />
      </header>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">
          {formatVnd(tender.budget_vnd)}
        </span>
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-slate-700">
          {formatDeadline(tender.submission_deadline)}
        </span>
        <CompetitionBadge level={match.competition_level ?? undefined} />
        {match.recommended_bid ? (
          <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
            Recommended
          </span>
        ) : null}
      </div>

      {rec?.reasoning ? (
        <p className="line-clamp-3 text-sm text-slate-600">{rec.reasoning}</p>
      ) : null}

      {rec && (rec.strengths.length > 0 || rec.risks.length > 0) ? (
        <div className="grid grid-cols-2 gap-3 text-xs">
          {rec.strengths.length > 0 ? (
            <div>
              <p className="mb-1 font-medium text-emerald-700">Strengths</p>
              <ul className="list-inside list-disc space-y-0.5 text-slate-600">
                {rec.strengths.slice(0, 3).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {rec.risks.length > 0 ? (
            <div>
              <p className="mb-1 font-medium text-rose-700">Risks</p>
              <ul className="list-inside list-disc space-y-0.5 text-slate-600">
                {rec.risks.slice(0, 3).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <footer className="mt-auto flex flex-wrap items-center gap-2 pt-1">
        {onCreateProposal ? (
          <button
            type="button"
            onClick={() => onCreateProposal(match.id)}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          >
            Create proposal
          </button>
        ) : null}
        {onSave ? (
          <button
            type="button"
            onClick={() => onSave(match.id)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Save
          </button>
        ) : null}
        {onPass ? (
          <button
            type="button"
            onClick={() => onPass(match.id)}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-slate-500 hover:bg-slate-50"
          >
            Pass
          </button>
        ) : null}
        {tender.raw_url ? (
          <a
            href={tender.raw_url}
            target="_blank"
            rel="noreferrer noopener"
            className="ml-auto text-sm text-slate-500 hover:text-slate-700"
          >
            Source ↗
          </a>
        ) : null}
      </footer>
    </article>
  );
};
