/**
 * Shared empty-state panel.
 *
 * Why a component (not a one-liner per page):
 *   - Every module page rolled its own "Chưa có ... nào" panel with
 *     subtly different padding/border/colour. The pattern was
 *     identical at the visual level but drift snuck in (some had a
 *     top icon, some didn't; some had a CTA, some left it as a dead
 *     screen). One component = one shape across modules.
 *   - First-run users land on whichever module their persona uses
 *     first. A consistent empty state with a CTA turns a "this is
 *     blank" moment into a "here's what to do" moment — the
 *     difference between bouncing and exploring.
 *
 * NOT for use cases that need bespoke layout (the projects page's
 * "seed demo data" panel is rich enough that its own JSX is clearer
 * than parameterising this further).
 *
 * The CTA can be either:
 *   * `cta={{ href, label }}` — internal navigation via Next Link.
 *   * `cta={{ onClick, label }}` — a button (e.g. opens a modal).
 *   * Or omitted — pure informational state.
 *
 * Icons come from lucide-react; pass any component that renders a
 * 24-32px SVG. We size the wrapper, not the icon, so future swaps
 * to heroicons/etc. don't need a per-callsite tweak.
 */

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";


export interface EmptyStateProps {
  /** Lucide icon component. Rendered at 24px in a slate halo. */
  icon: LucideIcon;
  /** Bold, single-line title. ~3-6 words is the sweet spot. */
  title: string;
  /** One or two sentences explaining the empty state + what to do. */
  body?: ReactNode;
  /** Optional primary action. Pass either href OR onClick, not both. */
  cta?:
    | { label: string; href: string; onClick?: never }
    | { label: string; href?: never; onClick: () => void };
  /** Optional secondary text below the CTA — usage hints, "safe to retry", etc. */
  hint?: ReactNode;
}


export function EmptyState({
  icon: Icon,
  title,
  body,
  cta,
  hint,
}: EmptyStateProps) {
  return (
    <div
      // `text-center` + `mx-auto max-w-md` keeps the body width readable
      // even when the parent container is wide (admin pages span 1200px+).
      // The dashed border telegraphs "transient state" rather than a
      // permanent error panel.
      className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-10 text-center"
    >
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-white text-slate-400 ring-1 ring-slate-200">
        <Icon size={24} aria-hidden />
      </div>
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {body ? (
        <div className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-slate-500">
          {body}
        </div>
      ) : null}
      {cta ? (
        cta.href ? (
          <Link
            href={cta.href}
            className="mt-5 inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            {cta.label}
          </Link>
        ) : (
          <button
            type="button"
            onClick={cta.onClick}
            className="mt-5 inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            {cta.label}
          </button>
        )
      ) : null}
      {hint ? (
        <p className="mx-auto mt-3 max-w-md text-[11px] text-slate-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
