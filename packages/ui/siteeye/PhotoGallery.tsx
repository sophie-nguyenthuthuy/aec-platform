import type { SitePhoto } from "./types";
import { PhotoCard } from "./PhotoCard";

interface Props {
  photos: SitePhoto[];
  onSelect?: (photo: SitePhoto) => void;
  emptyMessage?: string;
}

export function PhotoGallery({ photos, onSelect, emptyMessage = "No photos yet" }: Props) {
  if (photos.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 p-8 text-center text-sm text-gray-500">
        {emptyMessage}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {photos.map((p) => (
        <PhotoCard key={p.id} photo={p} onClick={onSelect} />
      ))}
    </div>
  );
}
