"use client";
import Link from "next/link";
import { useState } from "react";
import type { ProposalStatus } from "@aec/types/winwork";

import {
  Button,
  EmptyState,
  Input,
  PageHeader,
  Spinner,
  buttonStyles,
} from "@aec/ui/primitives";
import { ProposalCard } from "@aec/ui/winwork/ProposalCard";
import { useProposals } from "@/hooks/winwork/useProposals";

const STATUSES: (ProposalStatus | "all")[] = ["all", "draft", "sent", "won", "lost", "expired"];

export default function WinWorkListPage() {
  const [status, setStatus] = useState<ProposalStatus | "all">("all");
  const [q, setQ] = useState("");

  const { data, isLoading } = useProposals({
    status: status === "all" ? undefined : status,
    q: q || undefined,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Proposals"
        description="Track and manage client proposals"
        actions={
          <Link href="/winwork/proposals/new" className={buttonStyles({})}>
            New proposal
          </Link>
        }
      />

      <div className="flex flex-wrap gap-2">
        <div className="flex flex-wrap gap-1">
          {STATUSES.map((s) => (
            <Button
              key={s}
              variant={status === s ? "default" : "outline"}
              size="sm"
              onClick={() => setStatus(s)}
            >
              {s}
            </Button>
          ))}
        </div>
        <Input
          className="ml-auto w-64"
          placeholder="Search title or client…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner label="Loading proposals" />
        </div>
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState title="No proposals yet." />
      ) : (
        <div className="grid gap-3">
          {(data?.items ?? []).map((p) => (
            <ProposalCard key={p.id} proposal={p} />
          ))}
        </div>
      )}
    </div>
  );
}
