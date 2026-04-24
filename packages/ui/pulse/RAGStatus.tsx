import type { RAG } from "@aec/types/pulse";
import { cn } from "../lib/cn";

const labelVi: Record<RAG, string> = {
  green: "Tốt",
  amber: "Cần chú ý",
  red: "Rủi ro cao",
};

const labelEn: Record<RAG, string> = {
  green: "On track",
  amber: "Needs attention",
  red: "At risk",
};

const styles: Record<RAG, string> = {
  green: "bg-emerald-100 text-emerald-800 border-emerald-300",
  amber: "bg-amber-100 text-amber-800 border-amber-300",
  red: "bg-rose-100 text-rose-800 border-rose-300",
};

export function RAGStatus({
  status,
  language = "vi",
  className,
}: {
  status: RAG;
  language?: "vi" | "en";
  className?: string;
}) {
  const label = (language === "en" ? labelEn : labelVi)[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium",
        styles[status],
        className,
      )}
      aria-label={label}
    >
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          status === "green" && "bg-emerald-500",
          status === "amber" && "bg-amber-500",
          status === "red" && "bg-rose-500",
        )}
      />
      {label}
    </span>
  );
}
