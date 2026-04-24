"use client";
import { useRouter } from "next/navigation";

import { ProposalWizard } from "@aec/ui/winwork/ProposalWizard";
import { useGenerateProposal } from "@/hooks/winwork/useGenerateProposal";

export default function NewProposalPage() {
  const router = useRouter();
  const generate = useGenerateProposal();

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">New proposal</h1>
      <ProposalWizard
        generating={generate.isPending}
        onGenerate={async (payload) => generate.mutateAsync(payload)}
        onCreated={(id) => router.push(`/winwork/proposals/${id}`)}
      />
    </div>
  );
}
