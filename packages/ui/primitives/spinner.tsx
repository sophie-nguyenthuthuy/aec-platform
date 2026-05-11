import { Loader2 } from "lucide-react";
import { cn } from "../lib/cn";

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
  /**
   * Accessible label announced to screen readers. Defaults to "Loading".
   * Pass `null` to opt out (e.g. when a parent already announces the
   * loading state via `aria-busy`).
   */
  label?: string | null;
}

/**
 * Inline loading indicator. For full-page loaders, compose with
 * `<EmptyState>` or a card and pass a label.
 */
export function Spinner({ size = "md", className, label = "Loading" }: SpinnerProps) {
  const sizeClass = size === "sm" ? "h-4 w-4" : size === "lg" ? "h-8 w-8" : "h-5 w-5";
  return (
    <span
      role={label === null ? undefined : "status"}
      aria-live={label === null ? undefined : "polite"}
      className={cn("inline-flex items-center gap-2 text-muted-foreground", className)}
    >
      <Loader2 className={cn(sizeClass, "animate-spin")} aria-hidden="true" />
      {label !== null && <span className="sr-only">{label}</span>}
    </span>
  );
}
