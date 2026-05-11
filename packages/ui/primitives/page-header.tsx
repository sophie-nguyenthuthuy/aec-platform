import type { ReactNode } from "react";
import { cn } from "../lib/cn";

interface PageHeaderProps {
  /** Page title — renders as `<h1>`. Always include one per page. */
  title: ReactNode;
  /** Optional subtitle / description below the title. */
  description?: ReactNode;
  /** Optional breadcrumb / eyebrow rendered above the title. */
  eyebrow?: ReactNode;
  /** Right-aligned action area (typically one or two buttons). */
  actions?: ReactNode;
  /** Extra row rendered below the title block (e.g. a tab nav). */
  extra?: ReactNode;
  className?: string;
}

/**
 * Standard page header — title + description + actions.
 *
 * Every dashboard page should start with one of these instead of an
 * inline `<h2>` so the visual rhythm (title size, spacing, action
 * placement) stays identical across modules.
 */
export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  extra,
  className,
}: PageHeaderProps) {
  return (
    <header className={cn("mb-6 space-y-4", className)}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1">
          {eyebrow && (
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {eyebrow}
            </div>
          )}
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {title}
          </h1>
          {description && (
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </div>
      {extra}
    </header>
  );
}
