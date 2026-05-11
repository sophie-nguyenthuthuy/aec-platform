import type { HTMLAttributes } from "react";
import { cn } from "../lib/cn";

/**
 * Skeleton placeholder. Renders an animated shimmer that gives users a
 * sense of layout before the real data arrives. Should be paired with an
 * `aria-busy` parent so SR users get a single announcement instead of
 * "Loading, loading, loading…" for every shimmer.
 */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative overflow-hidden rounded-md bg-muted/60",
        "before:absolute before:inset-0 before:-translate-x-full before:animate-shimmer before:bg-gradient-to-r before:from-transparent before:via-background/60 before:to-transparent",
        className,
      )}
      {...props}
    />
  );
}

/**
 * Convenience: a stack of evenly-spaced text-line skeletons. `lines`
 * controls how many. Useful for list rows and card previews.
 */
export function SkeletonLines({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          // Last line is shorter — feels more natural than uniform bars.
          className={cn("h-3", i === lines - 1 ? "w-3/5" : "w-full")}
        />
      ))}
    </div>
  );
}
