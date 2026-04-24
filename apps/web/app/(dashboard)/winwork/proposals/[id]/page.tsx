"use client";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ClientEmailModal } from "@aec/ui/winwork/ClientEmailModal";
import { ProposalEditor } from "@aec/ui/winwork/ProposalEditor";
import { useMarkOutcome, useProposal, useSendProposal, useUpdateProposal } from "@/hooks/winwork/useProposal";

export default function ProposalDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const { data, isLoading } = useProposal(id);
  const update = useUpdateProposal(id);
  const send = useSendProposal(id);
  const outcome = useMarkOutcome(id);

  const [emailOpen, setEmailOpen] = useState(false);

  if (isLoading) return <div className="text-sm text-muted-foreground">Loading…</div>;
  if (!data) return <div className="text-sm text-muted-foreground">Proposal not found.</div>;

  return (
    <>
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
    </>
  );
}
