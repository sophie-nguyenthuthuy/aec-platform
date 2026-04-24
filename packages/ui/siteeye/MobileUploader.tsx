"use client";
import { useRef, useState } from "react";

import type { PhotoUploadItem, UUID } from "./types";

interface Props {
  projectId: UUID;
  siteVisitId?: UUID;
  onUpload: (files: File[], location: { lat: number; lng: number } | null) => Promise<void>;
  uploading?: boolean;
}

export function MobileUploader({ projectId, siteVisitId, onUpload, uploading }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [queued, setQueued] = useState<File[]>([]);
  const [location, setLocation] = useState<{ lat: number; lng: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handlePick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    setQueued((prev) => [...prev, ...files].slice(0, 50));
    if (!location && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
        () => null,
        { enableHighAccuracy: true, timeout: 5_000 },
      );
    }
  }

  function remove(idx: number) {
    setQueued((prev) => prev.filter((_, i) => i !== idx));
  }

  async function submit() {
    if (queued.length === 0) return;
    setError(null);
    try {
      await onUpload(queued, location);
      setQueued([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <p className="text-sm text-gray-600">
          Project: <span className="font-mono text-xs">{projectId}</span>
          {siteVisitId ? (
            <>
              {" "}
              · Visit: <span className="font-mono text-xs">{siteVisitId}</span>
            </>
          ) : null}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {location
            ? `GPS: ${location.lat.toFixed(5)}, ${location.lng.toFixed(5)}`
            : "GPS not captured yet"}
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png"
        multiple
        capture="environment"
        onChange={handlePick}
        className="hidden"
      />

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="flex-1 rounded-lg bg-sky-600 px-4 py-3 font-medium text-white"
        >
          Take / pick photos
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={queued.length === 0 || uploading}
          className="flex-1 rounded-lg bg-emerald-600 px-4 py-3 font-medium text-white disabled:opacity-40"
        >
          {uploading ? "Uploading…" : `Upload ${queued.length}`}
        </button>
      </div>

      {error ? (
        <p className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</p>
      ) : null}

      {queued.length > 0 ? (
        <div className="grid grid-cols-3 gap-2">
          {queued.map((f, i) => (
            <div
              key={`${f.name}-${i}`}
              className="relative overflow-hidden rounded border border-gray-200"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={URL.createObjectURL(f)}
                alt={f.name}
                className="aspect-[4/3] w-full object-cover"
              />
              <button
                type="button"
                onClick={() => remove(i)}
                aria-label="Remove"
                className="absolute right-1 top-1 h-6 w-6 rounded-full bg-black/60 text-xs text-white"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export type { PhotoUploadItem };
