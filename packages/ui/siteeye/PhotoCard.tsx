import type { SitePhoto } from "./types";
import { SafetyBadge } from "./SafetyBadge";

interface Props {
  photo: SitePhoto;
  onClick?: (photo: SitePhoto) => void;
}

export function PhotoCard({ photo, onClick }: Props) {
  const thumb = photo.thumbnail_url;
  const takenAt = photo.taken_at ? new Date(photo.taken_at) : null;

  return (
    <button
      type="button"
      onClick={() => onClick?.(photo)}
      className="group relative flex w-full flex-col overflow-hidden rounded-lg border border-gray-200 bg-white text-left transition hover:shadow-md"
    >
      <div className="aspect-[4/3] w-full overflow-hidden bg-gray-100">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumb}
            alt={photo.ai_analysis?.description ?? "Site photo"}
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-gray-400">
            No preview
          </div>
        )}
      </div>
      <div className="flex flex-col gap-1 p-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">
            {takenAt ? takenAt.toLocaleString() : "—"}
          </span>
          {photo.safety_status ? <SafetyBadge status={photo.safety_status} /> : null}
        </div>
        {photo.ai_analysis?.description ? (
          <p className="line-clamp-2 text-xs text-gray-700">
            {photo.ai_analysis.description}
          </p>
        ) : null}
        {photo.tags.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {photo.tags.slice(0, 4).map((t) => (
              <span
                key={t}
                className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600"
              >
                {t}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </button>
  );
}
