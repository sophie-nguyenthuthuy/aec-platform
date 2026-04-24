import type { ProposalStatus } from "@aec/types/winwork";
import { Badge } from "../primitives/badge";

const VARIANT: Record<ProposalStatus, "default" | "secondary" | "success" | "warning" | "destructive" | "outline"> = {
  draft: "secondary",
  sent: "warning",
  won: "success",
  lost: "destructive",
  expired: "outline",
};

const LABEL: Record<ProposalStatus, string> = {
  draft: "Draft",
  sent: "Sent",
  won: "Won",
  lost: "Lost",
  expired: "Expired",
};

export function WinLossTag({ status }: { status: ProposalStatus }) {
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
