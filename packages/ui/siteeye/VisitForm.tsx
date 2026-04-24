"use client";
import { useState } from "react";

import type { SiteVisitCreate, UUID } from "./types";

interface Props {
  projectId: UUID;
  onSubmit: (payload: SiteVisitCreate) => Promise<void> | void;
  submitting?: boolean;
}

export function VisitForm({ projectId, onSubmit, submitting }: Props) {
  const [visitDate, setVisitDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [weather, setWeather] = useState("");
  const [workers, setWorkers] = useState<number | "">("");
  const [notes, setNotes] = useState("");
  const [lat, setLat] = useState<number | null>(null);
  const [lng, setLng] = useState<number | null>(null);

  function captureLocation() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      setLat(pos.coords.latitude);
      setLng(pos.coords.longitude);
    });
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await onSubmit({
      project_id: projectId,
      visit_date: visitDate,
      weather: weather || null,
      workers_count: workers === "" ? null : Number(workers),
      notes: notes || null,
      location: lat !== null && lng !== null ? { lat, lng } : null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Field label="Visit date">
        <input
          type="date"
          required
          value={visitDate}
          onChange={(e) => setVisitDate(e.target.value)}
          className="w-full rounded border border-gray-300 px-3 py-2"
        />
      </Field>
      <Field label="Weather">
        <input
          type="text"
          value={weather}
          onChange={(e) => setWeather(e.target.value)}
          placeholder="e.g. sunny, 32°C"
          className="w-full rounded border border-gray-300 px-3 py-2"
        />
      </Field>
      <Field label="Workers on site">
        <input
          type="number"
          min={0}
          value={workers}
          onChange={(e) =>
            setWorkers(e.target.value === "" ? "" : Number(e.target.value))
          }
          className="w-full rounded border border-gray-300 px-3 py-2"
        />
      </Field>
      <Field label="Notes">
        <textarea
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full rounded border border-gray-300 px-3 py-2"
        />
      </Field>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={captureLocation}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm"
        >
          Capture GPS
        </button>
        <span className="text-xs text-gray-500">
          {lat !== null && lng !== null
            ? `${lat.toFixed(5)}, ${lng.toFixed(5)}`
            : "No location captured"}
        </span>
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="rounded bg-sky-600 px-4 py-2 font-medium text-white disabled:opacity-50"
      >
        {submitting ? "Saving…" : "Create visit"}
      </button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-gray-700">{label}</span>
      {children}
    </label>
  );
}
