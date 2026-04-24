import Link from "next/link";
import type { Proposal } from "@aec/types/winwork";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { WinLossTag } from "./WinLossTag";
import { AIConfidenceBadge } from "./AIConfidenceBadge";

function fmtVND(value: number | null): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND", maximumFractionDigits: 0 }).format(value);
}

export function ProposalCard({ proposal }: { proposal: Proposal }) {
  return (
    <Link href={`/winwork/proposals/${proposal.id}`}>
      <Card className="transition-colors hover:bg-muted/40">
        <CardHeader className="flex-row items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">{proposal.title}</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {proposal.client_name ?? "Unassigned client"}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <WinLossTag status={proposal.status} />
            {proposal.ai_generated && <AIConfidenceBadge confidence={proposal.ai_confidence} />}
          </div>
        </CardHeader>
        <CardContent className="flex items-center justify-between pt-0 text-sm">
          <span className="text-muted-foreground">
            {new Date(proposal.created_at).toLocaleDateString("vi-VN")}
          </span>
          <span className="font-semibold">{fmtVND(proposal.total_fee_vnd)}</span>
        </CardContent>
      </Card>
    </Link>
  );
}
