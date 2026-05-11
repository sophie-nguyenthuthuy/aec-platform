import type { ReactNode } from "react";
import { cn } from "../lib/cn";

interface EmptyStateProps {
  /** Top icon — Lucide icon component is the typical choice. */
  icon?: ReactNode;
  /** Headline. Keep it 1 line. */
  title: ReactNode;
  /** Optional body copy — explain why empty and what to do next. */
  description?: ReactNode;
  /** Primary action(s) — usually one `<Button>`, sometimes a secondary too. */
  action?: ReactNode;
  className?: string;
  /**
   * "error" variant uses a destructive tint — for failure states (e.g.
   * "Couldn't load projects"). "default" is the standard empty.
   */
  variant?: "default" | "error";
}

/**
 * Empty / zero / error state shown when a list, table, or query has
 * no data to display. Standardizing this stops every module from
 * rolling its own dashed-border box.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  variant = "default",
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-12 text-center",
        variant === "error"
          ? "border-destructive/40 bg-destructive/5"
          : "border-border bg-card",
        className,
      )}
    >
      {icon && (
        <div
          aria-hidden="true"
          className={cn(
            "mb-3 flex h-12 w-12 items-center justify-center rounded-full",
            variant === "error"
              ? "bg-destructive/10 text-destructive"
              : "bg-muted text-muted-foreground",
          )}
        >
          {icon}
        </div>
      )}
      <p
        className={cn(
          "text-sm font-medium",
          variant === "error" ? "text-destructive" : "text-foreground",
        )}
      >
        {title}
      </p>
      {description && (
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-4 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}
