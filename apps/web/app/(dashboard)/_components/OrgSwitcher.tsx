"use client";

import { useState, useTransition } from "react";

import { useSession } from "@/lib/auth-context";

import { signOut, switchOrg } from "../_actions/session";

/**
 * Compact org switcher + user menu, rendered in the dashboard sidebar.
 * Single-org users see a static label; multi-org users get a dropdown.
 * The sign-out button posts a server action that clears the Supabase
 * session cookie and redirects to /login.
 */
export function OrgSwitcher() {
  const { email, orgId, orgs } = useSession();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  const active = orgs.find((o) => o.id === orgId);
  const hasMultiple = orgs.length > 1;

  function onPick(id: string) {
    setOpen(false);
    if (id === orgId) return;
    startTransition(() => {
      void switchOrg(id);
    });
  }

  function onSignOut() {
    startTransition(() => {
      void signOut();
    });
  }

  return (
    <div className="space-y-2 border-t border-slate-200 pt-3">
      <div className="px-3 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        Tổ chức
      </div>

      {hasMultiple ? (
        <div className="relative">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            disabled={pending}
            className="flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-60"
          >
            <span className="truncate">{active?.name ?? "—"}</span>
            <span className="ml-2 text-slate-400">▾</span>
          </button>
          {open ? (
            <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded border border-slate-200 bg-white shadow-lg">
              {orgs.map((o) => (
                <li key={o.id}>
                  <button
                    type="button"
                    onClick={() => onPick(o.id)}
                    className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                      o.id === orgId ? "font-semibold text-slate-900" : "text-slate-700"
                    }`}
                  >
                    <span className="truncate">{o.name}</span>
                    <span className="ml-2 text-[10px] uppercase text-slate-400">{o.role}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <div className="px-3 py-2 text-sm text-slate-700">{active?.name ?? "—"}</div>
      )}

      <div className="px-3 pt-1 text-xs text-slate-500">{email}</div>
      <button
        type="button"
        onClick={onSignOut}
        disabled={pending}
        className="w-full rounded px-3 py-2 text-left text-xs text-slate-600 hover:bg-muted disabled:opacity-60"
      >
        Đăng xuất
      </button>
    </div>
  );
}
