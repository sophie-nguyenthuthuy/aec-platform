"use client";
import { useState } from "react";
import { ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import type { ChangeOrder } from "@aec/types/pulse";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { Badge } from "../primitives/badge";
import { Button } from "../primitives/button";
import { cn } from "../lib/cn";

const statusTone: Record<ChangeOrder["status"], string> = {
  draft: "bg-slate-200 text-slate-800",
  submitted: "bg-blue-100 text-blue-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-800",
};

function fmtVND(value: number | null): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(value);
}

export interface ChangeOrderCardProps {
  changeOrder: ChangeOrder;
  onAnalyze?: (id: string) => void;
  onApprove?: (id: string, decision: "approve" | "reject") => void;
  analyzing?: boolean;
}

export function ChangeOrderCard({
  changeOrder,
  onAnalyze,
  onApprove,
  analyzing,
}: ChangeOrderCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { ai_analysis } = changeOrder;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="text-base">
            #{changeOrder.number} — {changeOrder.title}
          </CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            {changeOrder.initiator ?? "—"} •{" "}
            {new Date(changeOrder.created_at).toLocaleDateString("vi-VN")}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
            statusTone[changeOrder.status],
          )}
        >
          {changeOrder.status}
        </span>
      </CardHeader>

      <CardContent className="space-y-3 text-sm">
        {changeOrder.description && (
          <p className="text-muted-foreground">{changeOrder.description}</p>
        )}

        <div className="flex gap-6 text-sm">
          <div>
            <div className="text-xs text-muted-foreground">Cost impact</div>
            <div className="font-semibold">
              {fmtVND(changeOrder.cost_impact_vnd)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">Schedule impact</div>
            <div className="font-semibold">
              {changeOrder.schedule_impact_days ?? "—"} days
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {!ai_analysis && onAnalyze && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => onAnalyze(changeOrder.id)}
              disabled={analyzing}
            >
              <Sparkles className="mr-1 h-3.5 w-3.5" />
              {analyzing ? "Analyzing…" : "AI analyze"}
            </Button>
          )}
          {ai_analysis && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? (
                <ChevronUp className="mr-1 h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="mr-1 h-3.5 w-3.5" />
              )}
              AI analysis
            </Button>
          )}
          {changeOrder.status === "submitted" && onApprove && (
            <>
              <Button
                size="sm"
                onClick={() => onApprove(changeOrder.id, "approve")}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => onApprove(changeOrder.id, "reject")}
              >
                Reject
              </Button>
            </>
          )}
        </div>

        {expanded && ai_analysis && (
          <div className="mt-2 space-y-2 rounded-md border bg-muted/30 p-3 text-xs">
            <div className="flex items-center gap-2">
              <Badge variant="outline">{ai_analysis.root_cause}</Badge>
              <Badge variant="secondary">
                {ai_analysis.recommendation.replace("_", " ")}
              </Badge>
              <span className="text-muted-foreground">
                {Math.round(ai_analysis.confidence * 100)}% confidence
              </span>
            </div>
            <p>{ai_analysis.reasoning}</p>
            {ai_analysis.contract_clauses.length > 0 && (
              <div>
                <div className="font-medium">Relevant clauses</div>
                <ul className="list-disc pl-4">
                  {ai_analysis.contract_clauses.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
