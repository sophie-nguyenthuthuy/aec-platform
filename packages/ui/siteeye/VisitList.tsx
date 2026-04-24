import type { SiteVisit } from "./types";

interface Props {
  visits: SiteVisit[];
  onOpen?: (visit: SiteVisit) => void;
}

export function VisitList({ visits, onOpen }: Props) {
  if (visits.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 p-8 text-center text-sm text-gray-500">
        No site visits recorded yet.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-gray-100 overflow-hidden rounded-lg border border-gray-200 bg-white">
      {visits.map((v) => (
        <li key={v.id}>
          <button
            type="button"
            onClick={() => onOpen?.(v)}
            className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition hover:bg-gray-50"
          >
            <div className="flex flex-col">
              <span className="font-medium text-gray-900">{v.visit_date}</span>
              <span className="text-xs text-gray-500">
                {v.photo_count} photos
                {v.weather ? ` · ${v.weather}` : ""}
                {v.workers_count !== null ? ` · ${v.workers_count} workers` : ""}
              </span>
            </div>
            {v.ai_summary ? (
              <p className="line-clamp-2 max-w-md text-sm text-gray-600">{v.ai_summary}</p>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  );
}
