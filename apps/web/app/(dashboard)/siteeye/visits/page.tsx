"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { VisitForm, VisitList } from "@aec/ui/siteeye";
import { useCreateVisit, useVisits } from "@/hooks/siteeye";

import { useSelectedProject } from "../project-context";

export default function VisitsPage() {
  const router = useRouter();
  const { projectId } = useSelectedProject();
  const [showForm, setShowForm] = useState(false);

  const visitsQ = useVisits({ project_id: projectId ?? undefined, limit: 50 });
  const createM = useCreateVisit();

  if (!projectId) {
    return <p className="text-sm text-gray-600">Select a project first.</p>;
  }

  const visits = visitsQ.data?.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Site visits</h1>
        <button
          type="button"
          onClick={() => setShowForm((s) => !s)}
          className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white"
        >
          {showForm ? "Cancel" : "New visit"}
        </button>
      </div>

      {showForm ? (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <VisitForm
            projectId={projectId}
            submitting={createM.isPending}
            onSubmit={async (payload) => {
              const visit = await createM.mutateAsync(payload);
              setShowForm(false);
              router.push(`/siteeye/visits/${visit.id}`);
            }}
          />
        </div>
      ) : null}

      <VisitList
        visits={visits}
        onOpen={(v) => router.push(`/siteeye/visits/${v.id}`)}
      />
    </div>
  );
}
