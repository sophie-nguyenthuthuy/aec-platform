"use client";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ClientEmailModal } from "@aec/ui/winwork/ClientEmailModal";
import { ProposalEditor } from "@aec/ui/winwork/ProposalEditor";
import { useMarkOutcome, useProposal, useSendProposal, useUpdateProposal } from "@/hooks/winwork/useProposal";

export default function ProposalDetailPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const id = params.id;
  // `from_tender=<tender_id>` is set when the proposal is spawned from a
  // BIDRADAR match (see apps/api/routers/bidradar.py::create_proposal). We
  // surface a breadcrumb back to the tender so the user can cross-check the
  // original brief without losing the proposal draft.
  const fromTender = search.get("from_tender");

  const { data, isLoading } = useProposal(id);
  const update = useUpdateProposal(id);
  const send = useSendProposal(id);
  const outcome = useMarkOutcome(id);

  const [emailOpen, setEmailOpen] = useState(false);

  if (isLoading) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (!data) return <div className="text-sm text-muted-foreground">Proposal not found.</div>;

  return (
    <div className="space-y-4">
      {fromTender ? (
        <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-900">
          Spawned from a BIDRADAR tender.{" "}
          <Link href={`/bidradar?tender=${fromTender}`} className="font-medium underline">
            View source tender →
          </Link>
        </div>
      ) : null}
      <ProposalEditor
        proposal={data}
        saving={update.isPending}
        onSave={(patch) => update.mutate(patch)}
        onSendClick={() => setEmailOpen(true)}
        onMarkWon={() => outcome.mutate({ status: "won" })}
        onMarkLost={() => outcome.mutate({ status: "lost" })}
      />
      <ClientEmailModal
        open={emailOpen}
        onOpenChange={setEmailOpen}
        defaultSubject={`Proposal — ${data.title}`}
        sending={send.isPending}
        onSend={async (payload) => {
          await send.mutateAsync(payload);
        }}
      />
    </div>
  );
}
