import type { ReactNode } from "react";

/**
 * Shared chrome for /login, /signup, /forgot-password, /reset-password,
 * /invite/[token]. Centred card on a muted background — keeps all auth
 * surfaces visually identical without copy-pasting markup.
 */
export function AuthShell({
  title,
  description,
  children,
  footer,
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  /** Optional row at the bottom (e.g. "Already have an account? Log in"). */
  footer?: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-muted/40 px-4 py-12 flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="rounded-xl border bg-card p-6 shadow-sm">
          <div className="mb-5 space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              {title}
            </h1>
            {description && (
              <p className="text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          {children}
        </div>
        {footer && (
          <p className="mt-4 text-center text-xs text-muted-foreground">
            {footer}
          </p>
        )}
      </div>
    </div>
  );
}
