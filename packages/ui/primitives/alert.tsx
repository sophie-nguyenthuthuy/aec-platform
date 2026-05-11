import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
} from "lucide-react";
import { cn } from "../lib/cn";

const alertStyles = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm [&>svg+div]:translate-y-[-3px] [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-3.5 [&>svg]:h-4 [&>svg]:w-4 [&>svg~*]:pl-7",
  {
    variants: {
      variant: {
        default: "border-border bg-card text-card-foreground",
        info: "border-primary/30 bg-primary/5 text-foreground [&>svg]:text-primary",
        success:
          "border-success/30 bg-success/5 text-foreground [&>svg]:text-success",
        warning:
          "border-warning/40 bg-warning/5 text-foreground [&>svg]:text-warning",
        destructive:
          "border-destructive/40 bg-destructive/5 text-destructive [&>svg]:text-destructive",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

const ICONS: Record<NonNullable<VariantProps<typeof alertStyles>["variant"]>, ReactNode> = {
  default: <Info />,
  info: <Info />,
  success: <CheckCircle2 />,
  warning: <AlertTriangle />,
  destructive: <AlertCircle />,
};

export interface AlertProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertStyles> {
  /** Set to `false` to render without the leading icon. */
  withIcon?: boolean;
}

/**
 * Inline alert / banner. Variants pick semantic colors automatically.
 * The `role="alert"` on destructive variants means SR users hear the
 * message immediately; informational variants stay silent so they don't
 * interrupt.
 */
export const Alert = forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant, withIcon = true, children, ...props }, ref) => {
    const effectiveVariant = variant ?? "default";
    return (
      <div
        ref={ref}
        role={effectiveVariant === "destructive" || effectiveVariant === "warning" ? "alert" : "status"}
        className={cn(alertStyles({ variant }), className)}
        {...props}
      >
        {withIcon && ICONS[effectiveVariant]}
        <div>{children}</div>
      </div>
    );
  },
);
Alert.displayName = "Alert";

export const AlertTitle = forwardRef<
  HTMLHeadingElement,
  HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h5
    ref={ref}
    className={cn("mb-1 font-medium leading-none", className)}
    {...props}
  />
));
AlertTitle.displayName = "AlertTitle";

export const AlertDescription = forwardRef<
  HTMLDivElement,
  HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm [&_p]:leading-relaxed", className)}
    {...props}
  />
));
AlertDescription.displayName = "AlertDescription";
