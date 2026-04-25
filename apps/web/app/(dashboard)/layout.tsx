import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

const NAV: Array<{ href: Route; label: string; section?: string }> = [
  { section: "Giai đoạn thiết kế", href: "/codeguard", label: "CodeGuard" },
  { href: "/drawbridge", label: "Drawbridge" },
  { section: "Giai đoạn đấu thầu", href: "/bidradar", label: "BidRadar" },
  { href: "/winwork", label: "WinWork" },
  { href: "/costpulse", label: "CostPulse" },
  { section: "Giai đoạn thi công", href: "/pulse", label: "Pulse" },
  { href: "/siteeye", label: "SiteEye" },
  { section: "Bàn giao", href: "/handover", label: "Handover" },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <aside className="w-60 border-r bg-muted/30 p-4">
        <div className="mb-6 text-lg font-semibold">AEC Platform</div>
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => (
            <div key={item.href}>
              {item.section && (
                <div className="mt-3 mb-1 px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {item.section}
                </div>
              )}
              <Link
                href={item.href}
                className="block rounded px-3 py-2 text-sm hover:bg-muted"
              >
                {item.label}
              </Link>
            </div>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-8">{children}</main>
    </div>
  );
}
