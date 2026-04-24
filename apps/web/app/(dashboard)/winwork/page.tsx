"use client";
import Link from "next/link";
import { useState } from "react";
import type { ProposalStatus } from "@aec/types/winwork";

import { Button } from "@aec/ui/primitives/button";
import { Input } from "@aec/ui/primitives/input";
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Proposals</h1>
          <p className="text-sm text-muted-foreground">Track and manage client proposals</p>
        </div>
        <Link
          href="/winwork/proposals/new"
          className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          New proposal
        </Link>
      </div>

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
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : (data?.items ?? []).length === 0 ? (
        <div className="rounded-md border p-8 text-center text-sm text-muted-foreground">
          No proposals yet.
        </div>
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
