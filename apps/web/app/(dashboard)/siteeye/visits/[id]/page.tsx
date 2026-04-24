"use client";
import { useParams } from "next/navigation";

import { PhotoGallery } from "@aec/ui/siteeye";
import { usePhotos } from "@/hooks/siteeye";

export default function VisitDetailPage() {
  const { id } = useParams<{ id: string }>();
  const photosQ = usePhotos({ site_visit_id: id, limit: 100 });

  const photos = photosQ.data?.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-gray-900">Visit</h1>
      <p className="text-xs text-gray-500">ID: <span className="font-mono">{id}</span></p>
      <PhotoGallery photos={photos} />
    </div>
  );
}
