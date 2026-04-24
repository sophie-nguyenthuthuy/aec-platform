import { Sparkles } from "lucide-react";
import { Badge } from "../primitives/badge";
import { cn } from "../lib/cn";

export function AIConfidenceBadge({ confidence, className }: { confidence: number | null; className?: string }) {
  if (confidence == null) return null;
  const pct = Math.round(confidence * 100);
  const variant = pct >= 75 ? "success" : pct >= 50 ? "warning" : "destructive";
  return (
    <Badge variant={variant} className={cn("gap-1", className)}>
      <Sparkles className="h-3 w-3" />
      AI · {pct}%
    </Badge>
  );
}
