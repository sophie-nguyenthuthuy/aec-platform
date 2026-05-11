import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";

import { cn } from "../lib/cn";

/**
 * Exported so consumers can apply button styling to a non-`<button>` —
 * typically a Next.js `<Link>`. Example:
 *
 *   <Link href="/foo" className={buttonStyles({ variant: "outline" })}>
 *     Go
 *   </Link>
 */
export const buttonStyles = cva(
  // Base — focus ring offsets the outline so it isn't swallowed by the
  // button's own background, and `gap-2` lets icon-only / icon+label
  // children sit consistently.
  "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background data-[loading=true]:cursor-progress",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        outline:
          "border border-input bg-background text-foreground hover:bg-accent hover:text-accent-foreground",
        ghost: "text-foreground hover:bg-accent hover:text-accent-foreground",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        success: "bg-success text-success-foreground hover:bg-success/90",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonStyles> {
  /**
   * Shows an in-button spinner, sets `aria-busy="true"`, and disables
   * interaction. Children stay rendered (so width doesn't jump) but
   * are visually muted under the spinner overlay.
   */
  loading?: boolean;
  /** Accessible name announced when `loading` is true. */
  loadingText?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size,
      loading = false,
      loadingText,
      disabled,
      children,
      type,
      ...props
    },
    ref,
  ) => (
    <button
      ref={ref}
      // Default to `type="button"` to prevent accidental form submits
      // — every button inside a <form> implicitly submits unless
      // typed, which is one of the most common React bug sources.
      type={type ?? "button"}
      data-loading={loading || undefined}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(buttonStyles({ variant, size }), className)}
      {...props}
    >
      {loading ? (
        <>
          <Loader2
            className="h-4 w-4 animate-spin"
            aria-hidden="true"
          />
          <span className="sr-only">
            {loadingText ?? "Loading…"}
          </span>
          <span aria-hidden="true" className="opacity-70">
            {children}
          </span>
        </>
      ) : (
        children
      )}
    </button>
  ),
);
Button.displayName = "Button";
