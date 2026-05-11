"use client";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { X } from "lucide-react";
import { cn } from "../lib/cn";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  description?: string;
  children: ReactNode;
  className?: string;
  /**
   * Hide the close (×) button — useful for confirmation dialogs where
   * the only sanctioned exits are the action buttons.
   */
  hideCloseButton?: boolean;
  /**
   * Optional accessible label when no `title` is provided (e.g.
   * media-viewer dialogs).
   */
  ariaLabel?: string;
}

/**
 * Accessible modal dialog.
 *
 *   * `role="dialog"` + `aria-modal="true"` so screen readers know to
 *     treat the rest of the page as inert.
 *   * Focus is moved into the dialog on open and restored to the
 *     previously-focused element on close.
 *   * Tab/Shift+Tab is trapped inside the dialog.
 *   * Escape closes; backdrop-click closes; both are keyboard-accessible.
 *   * Body scroll is locked while open.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  hideCloseButton,
  ariaLabel,
}: DialogProps) {
  const titleId = useId();
  const descId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  // Escape to close. Window-level so the listener catches keys even when
  // focus is briefly outside the panel (e.g. on the backdrop button).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onOpenChange(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  // Lock body scroll. We restore the previous overflow value so we don't
  // clobber a value some other component set.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Focus management — capture the element that opened the dialog so we
  // can return focus to it on close, then move focus into the panel.
  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    // Defer to next frame so the panel is in the DOM.
    const handle = requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = getFocusable(panel);
      (focusable[0] ?? panel).focus();
    });
    return () => {
      cancelAnimationFrame(handle);
      previouslyFocused.current?.focus?.();
    };
  }, [open]);

  // Trap Tab key inside the panel.
  const onKeyDownTrap = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusable = getFocusable(panel);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) {
      // No focusable elements — swallow Tab so focus can't leak out of
      // the modal onto the inert page behind it.
      e.preventDefault();
      return;
    }
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop. Click closes. `aria-hidden` because the dialog is the
          meaningful UI; SR users navigate the panel directly. */}
      <div
        aria-hidden="true"
        onClick={() => onOpenChange(false)}
        className="absolute inset-0 bg-foreground/40 backdrop-blur-[1px] animate-fade-in"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={!title ? ariaLabel : undefined}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        onKeyDown={onKeyDownTrap}
        className={cn(
          "relative w-full max-w-lg rounded-lg border bg-card text-card-foreground p-6 shadow-lg animate-zoom-in",
          "focus:outline-none",
          className,
        )}
      >
        {!hideCloseButton && (
          <button
            type="button"
            aria-label="Đóng"
            onClick={() => onOpenChange(false)}
            className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <X className="h-4 w-4" />
          </button>
        )}
        {title && (
          <h2
            id={titleId}
            className="text-lg font-semibold leading-tight tracking-tight pr-8"
          >
            {title}
          </h2>
        )}
        {description && (
          <p id={descId} className="mt-1 text-sm text-muted-foreground">
            {description}
          </p>
        )}
        <div className={cn(title || description ? "mt-4" : undefined)}>
          {children}
        </div>
      </div>
    </div>
  );
}

// Tab-trap helper. We exclude elements that have `display: none` parents
// (offsetParent === null) — they're in the DOM but not focusable.
function getFocusable(root: HTMLElement): HTMLElement[] {
  const selector = [
    "a[href]",
    "area[href]",
    'input:not([disabled]):not([type="hidden"])',
    "select:not([disabled])",
    "textarea:not([disabled])",
    "button:not([disabled])",
    "iframe",
    "object",
    "embed",
    '[tabindex]:not([tabindex="-1"])',
    "[contenteditable]",
  ].join(",");
  return Array.from(root.querySelectorAll<HTMLElement>(selector)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}
