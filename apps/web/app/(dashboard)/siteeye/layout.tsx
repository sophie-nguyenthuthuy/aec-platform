import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

const NAV: Array<{ href: Route; label: string }> = [
  { href: "/siteeye/dashboard", label: "Dashboard" },
  { href: "/siteeye/visits", label: "Visits" },
  { href: "/siteeye/safety", label: "Safety" },
  { href: "/siteeye/progress", label: "Progress" },
  { href: "/siteeye/reports", label: "Reports" },
];

export default function SiteEyeLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-7xl p-4">
      <nav className="mb-6 flex gap-4 border-b border-gray-200 pb-2 text-sm">
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className="rounded px-2 py-1 text-gray-600 hover:bg-gray-100 hover:text-gray-900"
          >
            {n.label}
          </Link>
        ))}
      </nav>
      {children}
    </div>
  );
}
