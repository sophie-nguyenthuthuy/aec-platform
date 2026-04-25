import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

const NAV: Array<{ href: Route; label: string }> = [
  { href: "/handover", label: "Gói bàn giao" },
  { href: "/handover/warranties", label: "Bảo hành" },
  { href: "/handover/defects", label: "Lỗi tồn đọng" },
];

export default function HandoverLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
          <h1 className="text-lg font-bold text-slate-900">HANDOVER</h1>
          <nav className="flex gap-1">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className="rounded-md px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
              >
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">{children}</main>
    </div>
  );
}
