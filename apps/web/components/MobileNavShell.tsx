"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";


/**
 * Responsive shell that wraps the dashboard layout's sidebar nav.
 *
 *   * md+   : the sidebar is always visible at 240px, identical to the
 *             pre-mobile-pass layout. No top bar.
 *   * <md   : the sidebar is hidden behind a hamburger; tapping the
 *             button opens it as a slide-in drawer with a 60% black
 *             backdrop. Tapping the backdrop or the X closes.
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

  return (
    <>
      {/* ---------- Mobile top bar (visible <md) ---------- */}
      <header className="flex items-center gap-3 border-b bg-white px-4 py-3 md:hidden">
        <button
          type="button"
          aria-label="Mở menu"
          onClick={() => setOpen(true)}
          className="rounded p-1.5 text-slate-700 hover:bg-slate-100"
        >
          <Menu size={20} />
        </button>
        <span className="text-base font-semibold">AEC Platform</span>
      </header>

      <div className="flex min-h-screen">
        {/* ---------- Backdrop (mobile only, when drawer is open) ---------- */}
        {open && (
          <button
            type="button"
            aria-label="Đóng menu"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-slate-900/40 md:hidden"
          />
        )}

        {/* ---------- Sidebar ---------- */}
        <aside
          className={`
            flex w-60 flex-col border-r bg-muted/30 p-4
            md:static md:translate-x-0
            fixed inset-y-0 left-0 z-40 transition-transform duration-200
            ${open ? "translate-x-0" : "-translate-x-full"}
            md:flex
          `}
        >
          {/* Close button — mobile only. Mirrors the top-bar hamburger
              so the user always has a visible exit. */}
          <button
            type="button"
            aria-label="Đóng menu"
            onClick={() => setOpen(false)}
            className="mb-2 self-end rounded p-1 text-slate-500 hover:bg-slate-100 md:hidden"
          >
            <X size={18} />
          </button>
          <div className="mb-4 hidden text-lg font-semibold md:block">
            AEC Platform
          </div>
          {nav}
          {footer}
        </aside>

        {/* ---------- Main content ---------- */}
        <main className="flex-1 p-4 md:p-8">{children}</main>
      </div>
    </>
  );
}
