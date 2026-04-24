"use client";
import { useEffect, useState } from "react";
import type { FeeBreakdown, Proposal, ScopeOfWork } from "@aec/types/winwork";

import { Button } from "../primitives/button";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Textarea } from "../primitives/textarea";
import { AIConfidenceBadge } from "./AIConfidenceBadge";
import { FeeBreakdownTable } from "./FeeBreakdownTable";
import { ScopeBuilder } from "./ScopeBuilder";
import { WinLossTag } from "./WinLossTag";

interface ProposalEditorProps {
  proposal: Proposal;
  saving?: boolean;
  onSave: (patch: Partial<Proposal>) => void;
  onSendClick: () => void;
  onMarkWon: () => void;
  onMarkLost: () => void;
}

const EMPTY_FEES: FeeBreakdown = { lines: [], subtotal_vnd: 0, vat_vnd: 0, total_vnd: 0 };
const EMPTY_SCOPE: ScopeOfWork = { items: [] };

export function ProposalEditor({
  proposal,
  saving,
  onSave,
  onSendClick,
  onMarkWon,
  onMarkLost,
}: ProposalEditorProps) {
  const [title, setTitle] = useState(proposal.title);
  const [clientName, setClientName] = useState(proposal.client_name ?? "");
  const [clientEmail, setClientEmail] = useState(proposal.client_email ?? "");
  const [notes, setNotes] = useState(proposal.notes ?? "");
  const [scope, setScope] = useState<ScopeOfWork>(proposal.scope_of_work ?? EMPTY_SCOPE);
  const [fees, setFees] = useState<FeeBreakdown>(proposal.fee_breakdown ?? EMPTY_FEES);

  useEffect(() => {
    setTitle(proposal.title);
    setClientName(proposal.client_name ?? "");
    setClientEmail(proposal.client_email ?? "");
    setNotes(proposal.notes ?? "");
    setScope(proposal.scope_of_work ?? EMPTY_SCOPE);
    setFees(proposal.fee_breakdown ?? EMPTY_FEES);
  }, [proposal.id]);

  function save() {
    onSave({
      title,
      client_name: clientName || null,
      client_email: clientEmail || null,
      notes: notes || null,
      scope_of_work: scope,
      fee_breakdown: fees,
      total_fee_vnd: fees.total_vnd,
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} className="w-[480px] text-lg font-semibold" />
          <div className="flex items-center gap-2">
            <WinLossTag status={proposal.status} />
            {proposal.ai_generated && <AIConfidenceBadge confidence={proposal.ai_confidence} />}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button onClick={onSendClick} disabled={!clientEmail}>
            Send to client
          </Button>
          {proposal.status !== "won" && (
            <Button variant="secondary" onClick={onMarkWon}>
              Mark won
            </Button>
          )}
          {proposal.status !== "lost" && (
            <Button variant="destructive" onClick={onMarkLost}>
              Mark lost
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Client</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <Label>Name</Label>
            <Input value={clientName} onChange={(e) => setClientName(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>Email</Label>
            <Input type="email" value={clientEmail} onChange={(e) => setClientEmail(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scope of work</CardTitle>
        </CardHeader>
        <CardContent>
          <ScopeBuilder items={scope.items} onChange={(items) => setScope({ items })} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Fee breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <FeeBreakdownTable value={fees} onChange={setFees} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Notes</CardTitle>
        </CardHeader>
        <CardContent>
          <Textarea rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </CardContent>
      </Card>
    </div>
  );
}
