"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";


/**
 * Responsive shell that wraps the dashboard layout's sidebar nav.
 *
 *   * md+   : the sidebar is sticky at 256px, always visible.
 *   * <md   : the sidebar is hidden behind a hamburger; tapping the
 *             button opens it as a slide-in drawer with a backdrop.
 *             Tapping the backdrop, pressing Escape, or tapping the X
 *             closes. Focus is moved into the drawer on open and
 *             returned to the hamburger on close. Tab is trapped
 *             inside the drawer while open.
 *
 * Auto-closes on route change so a tap-into-page doesn't leave the
 * drawer open behind the new content.
 */
export function MobileNavShell({
  nav,
  footer,
  children,
}: {
  nav: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const drawerRef = useRef<HTMLElement>(null);
  const hamburgerRef = useRef<HTMLButtonElement>(null);

  // Auto-close on navigation. The drawer would otherwise persist as an
  // overlay over the destination page until the user manually closes it.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Lock body scroll while the drawer is open so the underlying page
  // doesn't scroll behind the overlay (iOS especially is bad about this).
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Escape closes the drawer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Move focus into the drawer on open, restore on close.
  useEffect(() => {
    if (open) {
      // Defer one frame so the drawer is in the DOM.
      const handle = requestAnimationFrame(() => {
        const focusable = drawerRef.current?.querySelector<HTMLElement>(
          'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        );
        focusable?.focus();
      });
      return () => cancelAnimationFrame(handle);
    } else {
      // Return focus to the hamburger so keyboard users keep their place.
      hamburgerRef.current?.focus();
    }
  }, [open]);

  // Trap Tab inside the drawer when open.
  const onDrawerKeyDown = useCallback((e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "Tab") return;
    const drawer = drawerRef.current;
    if (!drawer) return;
    const focusable = Array.from(
      drawer.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => el.offsetParent !== null);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  return (
    <>
      {/* Skip link — keyboard users press Tab once and can jump past the
          ~25-item sidebar straight to page content. */}
      <a href="#main-content" className="skip-link">
        Đi tới nội dung chính
      </a>

      {/* ---------- Mobile top bar (visible <md) ---------- */}
      <header className="flex items-center gap-3 border-b bg-card px-4 py-3 md:hidden">
        <button
          ref={hamburgerRef}
          type="button"
          aria-label="Mở menu"
          aria-expanded={open}
          aria-controls="primary-sidebar"
          onClick={() => setOpen(true)}
          className="rounded-md p-1.5 text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        <span className="text-base font-semibold">AEC Platform</span>
      </header>

      <div className="flex min-h-screen">
        {/* ---------- Backdrop (mobile only, when drawer is open) ---------- */}
        {open && (
          <div
            aria-hidden="true"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-foreground/40 backdrop-blur-[1px] animate-fade-in md:hidden"
          />
        )}

        {/* ---------- Sidebar ---------- */}
        <aside
          ref={drawerRef}
          id="primary-sidebar"
          aria-label="Điều hướng chính"
          onKeyDown={onDrawerKeyDown}
          className={`
            flex w-64 flex-col gap-3 border-r bg-card p-4
            md:sticky md:top-0 md:h-screen md:translate-x-0
            fixed inset-y-0 left-0 z-40 transition-transform duration-200 ease-out
            ${open ? "translate-x-0" : "-translate-x-full"}
            md:flex
          `}
        >
          {/* Header row: brand + close (close is mobile only). */}
          <div className="flex items-center justify-between">
            <div className="text-lg font-semibold text-foreground">
              AEC Platform
            </div>
            <button
              type="button"
              aria-label="Đóng menu"
              onClick={() => setOpen(false)}
              className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-accent-foreground md:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          {nav}
          {footer && <div className="border-t pt-3">{footer}</div>}
        </aside>

        {/* ---------- Main content ---------- */}
        <main
          id="main-content"
          tabIndex={-1}
          className="min-w-0 flex-1 p-4 md:p-8 focus:outline-none"
        >
          {children}
        </main>
      </div>
    </>
  );
}
